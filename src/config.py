import json
from enum import Flag, auto, Enum
from pathlib import Path
from typing import List

from selenium.webdriver.common.by import By

from src.util.generic import log, LogType
from src.util.json_util import json_parse, json_parse_enum, json_parse_class_list
from src.util.selenium_util import UIElement, UITask

CONFIG_FILE = 'job.json'
CONFIG_VAL_COOKIES = 'cookies'
CONFIG_VAL_DATA_DIRECTORY = 'data_directory'
CONFIG_VAL_SUBSTRINGS_TO_SKIP = 'substrings_to_skip'
CONFIG_VAL_SCROLL_PAUSE_TIME = 'scroll_pause_time'
CONFIG_VAL_MAX_TIMEOUT = 'max_timeout'
CONFIG_VAL_MIN_TIMEOUT = 'min_timeout'
CONFIG_VAL_CACHE_COMPLETED_URLS = 'cache_completed_urls'
CONFIG_VAL_OUT_DIR = 'out_dir'
CONFIG_VAL_SCRAPE_TYPE = 'scrape_type'
CONFIG_VAL_SCRAPE_ELEMENTS = 'scrape_elements'
CONFIG_VAL_SCRAPE_SITEMAP = 'scrape_sitemap'
CONFIG_VAL_URLS = 'urls'
CONFIG_VAL_USER_AGENT = 'user_agent'
CONFIG_VAL_IFRAME_IGNORE = 'iframe_ignore'
CONFIG_VAL_POST_SCRAPE_JOBS = 'post_scrape_jobs'
CONFIG_VAL_POST_SCRAPE_JOBS_ONLY = 'post_scrape_jobs_only'

CONFIG_VAL_CONTENT_NAME = 'content_name'
CONFIG_VAL_CONTENT_NAME_ID = 'id'
CONFIG_VAL_CONTENT_NAME_PREFIX = 'prefix'

CONFIG_VAL_LOGIN = 'login'
CONFIG_VAL_LOGIN_ELEMENT_ID = 'id'
CONFIG_VAL_LOGIN_ELEMENT_TYPE = 'type'
CONFIG_VAL_LOGIN_ELEMENT_VALUE = 'value'
CONFIG_VAL_LOGIN_ELEMENT_TASK = 'task'
CONFIG_VAL_LOGIN_CHILDREN = 'children'
CONFIG_VAL_LOGIN_URL = 'url'


class ScrapeElements(Flag):
    VIDEOS = auto()
    IMAGES = auto()
    HTML = auto()
    IFRAMES = auto()
    ALL = VIDEOS | IMAGES | HTML | IFRAMES


class ScrapeType(Enum):
    SINGLE_PAGE = 0
    ALL_PAGES = 1


class IFrameIgnore:
    def __init__(self, identifier: str, obj_type: str):
        self.identifier = identifier
        self.obj_type = obj_type

    def __repr__(self):
        return str(self.__dict__)


class PostScrapeJobType(Enum):
    REPLACE = 'REPLACE'


class PostScrapeJob:
    def __init__(self, obj_type: PostScrapeJobType, identifier: str, text: str):
        self.obj_type = obj_type
        self.identifier = identifier
        self.text = text

    def __repr__(self):
        return str(self.__dict__)


class Login:
    def __init__(self, url: str, children: List[UIElement]):
        self.url = url
        self.children = children

    def __repr__(self):
        return str(self.__dict__)


class Cookie:
    def __init__(self, dictionary: dict = None, name: str = '', value: str = '', domain: str = '', path: str = ''):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path

        if dictionary:
            for key in dictionary:
                setattr(self, key, dictionary[key])

        if not self.name or not self.value or not self.domain or not self.path:
            log(f'Invalid Cookie', log_type=LogType.ERROR)

    def __repr__(self):
        return str(self.__dict__)


class ContentName:
    def __init__(self, identifier: str, prefix=''):
        self.identifier = identifier
        self.prefix = prefix

    def __repr__(self):
        return str(self.__dict__)


class Config:
    """
    Get cookies from Firefox's 'cookies.sqlite' using:
        SELECT json_group_array(cookie) FROM (SELECT json_object('name', name, 'value', value, 'host', host, 'path',
            path) as cookie FROM moz_cookies where host like '%host%')
    """
    def __init__(self, scrape_type: ScrapeType, urls: List[str] = None, out_dir: str = None, cookies: List[Cookie] = None, content_name: ContentName = None,
                 user_agent: str = None, login: Login = None, scrape_elements: ScrapeElements = None, scrape_sitemap: bool = True,
                 data_directory: str = 'data', substrings_to_skip: List[str] = None, scroll_pause_time: float = 1.0, min_timeout: float = 5.0,
                 max_timeout: float = 10.0, cache_completed_urls: bool = True, iframe_ignore: List[IFrameIgnore] = None,
                 post_scrape_jobs: List[PostScrapeJob] = None, post_scrape_jobs_only: bool = False):
        self.scrape_type = scrape_type
        self.urls: List[str] = [] if urls is None else urls
        self.out_dir = out_dir
        self.cookies: List[Cookie] = [] if cookies is None else cookies
        self.content_name = content_name
        self.user_agent = user_agent
        self.login = login
        self.scrape_elements = scrape_elements
        self.scrape_sitemap = scrape_sitemap
        self.data_directory = data_directory
        self.substrings_to_skip = substrings_to_skip
        self.scroll_pause_time = scroll_pause_time
        self.min_timeout = min_timeout
        self.max_timeout = max_timeout
        self.cache_completed_urls = cache_completed_urls
        self.iframe_ignore: List[IFrameIgnore] = [] if iframe_ignore is None else iframe_ignore
        self.post_scrape_jobs: List[PostScrapeJob] = [] if post_scrape_jobs is None else post_scrape_jobs
        self.post_scrape_jobs_only = post_scrape_jobs_only

    def __repr__(self):
        return str(self.__dict__)


def parse_content_name(obj) -> ContentName:
    content_name = None
    content_name_obj = json_parse(obj, CONFIG_VAL_CONTENT_NAME)
    if content_name_obj:
        identifier = json_parse(content_name_obj, CONFIG_VAL_CONTENT_NAME_ID, fatal=True)
        prefix = json_parse(content_name_obj, CONFIG_VAL_CONTENT_NAME_PREFIX)

        content_name = ContentName(identifier, prefix)

    return content_name


def parse_ui_element(obj):
    identifier = json_parse(obj, CONFIG_VAL_LOGIN_ELEMENT_ID, fatal=True)
    value = json_parse(obj, CONFIG_VAL_LOGIN_ELEMENT_VALUE, default=None)
    task: UITask = json_parse_enum(obj, CONFIG_VAL_LOGIN_ELEMENT_TASK, UITask)
    ui_type: By = json_parse_enum(obj, CONFIG_VAL_LOGIN_ELEMENT_TYPE, By)

    return UIElement(identifier, ui_type, value=value, task=task)


def parse_login(obj) -> Login:
    login = None
    login_obj = json_parse(obj, CONFIG_VAL_LOGIN)
    if login_obj:
        url = json_parse(login_obj, CONFIG_VAL_LOGIN_URL, fatal=True)

        children = []
        children_obj = json_parse(login_obj, CONFIG_VAL_LOGIN_CHILDREN, fatal=True)
        for child_obj in children_obj:
            child = parse_ui_element(child_obj)

            children.append(child)

        login = Login(url, children)

    return login


def json_to_config(obj) -> Config:
    scrape_type: ScrapeType = json_parse_enum(obj, CONFIG_VAL_SCRAPE_TYPE, ScrapeType)
    scrape_elements: ScrapeElements = json_parse_enum(obj, CONFIG_VAL_SCRAPE_ELEMENTS, ScrapeElements, fatal=True)
    scrape_sitemap: bool = json_parse(obj, CONFIG_VAL_SCRAPE_SITEMAP, default=True)
    urls = json_parse(obj, CONFIG_VAL_URLS, default=List[str])
    out_dir = json_parse(obj, CONFIG_VAL_OUT_DIR, default=None)
    user_agent = json_parse(obj, CONFIG_VAL_USER_AGENT, default=None)
    data_directory: str = json_parse(obj, CONFIG_VAL_DATA_DIRECTORY, default='data')
    substrings_to_skip: List[str] = json_parse(obj, CONFIG_VAL_SUBSTRINGS_TO_SKIP, default=None)
    scroll_pause_time: float = json_parse(obj, CONFIG_VAL_SCROLL_PAUSE_TIME, default=1.0)
    min_timeout: float = json_parse(obj, CONFIG_VAL_MIN_TIMEOUT, default=5.0)
    max_timeout: float = json_parse(obj, CONFIG_VAL_MAX_TIMEOUT, default=10.0)
    cache_completed_urls: bool = json_parse(obj, CONFIG_VAL_CACHE_COMPLETED_URLS, default=True)
    content_name = parse_content_name(obj)
    login = parse_login(obj)

    cookies_obj = json_parse(obj, CONFIG_VAL_COOKIES, default={})
    cookies = [Cookie(dictionary=cookie) for cookie in cookies_obj]

    iframe_ignore = json_parse_class_list(obj, IFrameIgnore, key=CONFIG_VAL_IFRAME_IGNORE, default=[])

    post_scrape_jobs_only: bool = json_parse(obj, CONFIG_VAL_POST_SCRAPE_JOBS_ONLY, default=False)
    post_scrape_jobs: List[PostScrapeJob] = json_parse_class_list(obj, PostScrapeJob, key=CONFIG_VAL_POST_SCRAPE_JOBS, default=[])

    config = Config(scrape_type, urls=urls, cookies=cookies, out_dir=out_dir, content_name=content_name, user_agent=user_agent, login=login,
                    scrape_elements=scrape_elements, scrape_sitemap=scrape_sitemap, data_directory=data_directory, substrings_to_skip=substrings_to_skip,
                    scroll_pause_time=scroll_pause_time, min_timeout=min_timeout, max_timeout=max_timeout, cache_completed_urls=cache_completed_urls,
                    iframe_ignore=iframe_ignore, post_scrape_jobs=post_scrape_jobs, post_scrape_jobs_only=post_scrape_jobs_only)

    return config


def get_config(file=CONFIG_FILE):
    config_file = Path(file)
    if not config_file.is_file():
        log(f'{file} not found in path', log_type=LogType.ERROR)

    with open(file, 'r') as file_obj:
        text = ''.join(file_obj.readlines())
        json_obj = json.loads(text)

        return json_to_config(json_obj)

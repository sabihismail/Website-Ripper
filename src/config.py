import json
from enum import Enum
from pathlib import Path
from typing import Optional, TypeVar

from selenium.webdriver.common.by import By

from src.util import *

CONFIG_FILE = 'job.json'
CONFIG_VAL_COOKIES = 'cookies'
CONFIG_VAL_OUT_DIR = 'out_dir'
CONFIG_VAL_SCRAPE_TYPE = 'scrape_type'
CONFIG_VAL_URLS = 'urls'
CONFIG_VAL_USER_AGENT = 'user_agent'

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


class ScrapeType(Enum):
    SINGLE_PAGE = 0
    ALL_PAGES = 1


class UITask(Enum):
    GO_TO = 0
    CLICK = 1


class UIElement:
    def __init__(self, identifier: str, ui_type: By, value: str = None, task: UITask = None):
        self.identifier = identifier
        self.ui_type = ui_type
        self.value = value
        self.task = task

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
            error(f'Invalid Cookie')

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
    def __init__(self, scrape_type: ScrapeType, urls: List[str] = None, out_dir: str = None,
                 cookies: List[Cookie] = None, content_name: ContentName = None, user_agent: str = None,
                 login: Login = None):
        self.scrape_type = scrape_type
        self.urls: List[str] = [] if urls is None else urls
        self.out_dir = out_dir
        self.cookies: List[Cookie] = [] if cookies is None else cookies
        self.content_name = content_name
        self.user_agent = user_agent
        self.login = login

    def __repr__(self):
        return str(self.__dict__)


def json_get(json, key, default=None, fatal=False):
    if key in json:
        return json[key]

    if fatal:
        error(f'Cannot find {key} in {json}.')

    return default


def get_content_name(obj) -> ContentName:
    content_name = None
    content_name_obj = json_get(obj, CONFIG_VAL_CONTENT_NAME)
    if content_name_obj:
        identifier = json_get(content_name_obj, CONFIG_VAL_CONTENT_NAME_ID, fatal=True)
        prefix = json_get(content_name_obj, CONFIG_VAL_CONTENT_NAME_PREFIX)

        content_name = ContentName(identifier, prefix)

    return content_name


def json_get_enum(obj, json_val, class_type, fatal=False):
    val = json_get(obj, json_val, default=None, fatal=fatal)

    if not val:
        return None

    val = str(val).upper()
    if val not in class_type.__dict__.keys():
        error(f'Invalid Enum: {val}, Keys: {class_type.__dict__.keys()}')

    return class_type.__dict__[val]


def get_ui_element(obj):
    identifier = json_get(obj, CONFIG_VAL_LOGIN_ELEMENT_ID, fatal=True)
    value = json_get(obj, CONFIG_VAL_LOGIN_ELEMENT_VALUE, default=None)
    task = json_get_enum(obj, CONFIG_VAL_LOGIN_ELEMENT_TASK, UITask)
    ui_type = json_get_enum(obj, CONFIG_VAL_LOGIN_ELEMENT_TYPE, By)

    return UIElement(identifier, ui_type, value=value, task=task)


def get_login(obj) -> Login:
    login = None
    login_obj = json_get(obj, CONFIG_VAL_LOGIN)
    if login_obj:
        url = json_get(login_obj, CONFIG_VAL_LOGIN_URL, fatal=True)

        children = []
        children_obj = json_get(login_obj, CONFIG_VAL_LOGIN_CHILDREN, fatal=True)
        for child_obj in children_obj:
            child = get_ui_element(child_obj)

            children.append(child)

        login = Login(url, children)

    return login


def json_to_config(obj) -> Config:
    scrape_type = json_get_enum(obj, CONFIG_VAL_SCRAPE_TYPE, ScrapeType)
    urls = json_get(obj, CONFIG_VAL_URLS, default=List[str])
    out_dir = json_get(obj, CONFIG_VAL_OUT_DIR, default=None)
    user_agent = json_get(obj, CONFIG_VAL_USER_AGENT, default=None)
    content_name = get_content_name(obj)
    login = get_login(obj)

    cookies_obj = json_get(obj, CONFIG_VAL_COOKIES, default={})
    cookies = [Cookie(dictionary=cookie) for cookie in cookies_obj]

    config = Config(scrape_type, urls=urls, cookies=cookies, out_dir=out_dir, content_name=content_name,
                    user_agent=user_agent, login=login)

    return config


def get_config(file=CONFIG_FILE):
    config_file = Path(file)
    if not config_file.is_file():
        error(f'{file} not found in path')

    with open(file, 'r') as file_obj:
        text = ''.join(file_obj.readlines())

        json_obj = json.loads(text)

        return json_to_config(json_obj)

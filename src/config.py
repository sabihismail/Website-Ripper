import json
from collections import namedtuple
from enum import Enum
from pathlib import Path
from typing import List

from src.util import *

CONFIG_FILE = 'job.json'
CONFIG_VAL_CONTENT_NAME = 'content_name'
CONFIG_VAL_CONTENT_NAME_ID = 'id'
CONFIG_VAL_CONTENT_NAME_PREFIX = 'prefix'
CONFIG_VAL_COOKIES = 'cookies'
CONFIG_VAL_OUT_DIR = 'out_dir'
CONFIG_VAL_SCRAPE_TYPE = 'scrape_type'
CONFIG_VAL_URLS = 'urls'


class ScrapeType(Enum):
    SINGLE_PAGE = 0
    ALL_PAGE = 1

    @staticmethod
    def keys():
        return [e.name for e in ScrapeType]


class Cookie:
    def __init__(self, dictionary: dict = None, name: str = '', value: str = '', domain: str = '', path: str = ''):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path

        if dictionary:
            for key in dictionary:
                setattr(self, key, dictionary[key])

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
    def __init__(self, scrape_type: ScrapeType, urls: List[str] = None, out_dir: str = '', cookies: List[Cookie] = None,
                 content_name: ContentName = None):
        self.scrape_type = scrape_type
        self.urls: List[str] = [] if urls is None else urls
        self.out_dir = out_dir
        self.cookies: List[Cookie] = [] if cookies is None else cookies
        self.content_name = content_name

    def __repr__(self):
        return str(self.__dict__)


def json_get(json, key, default=None, fatal=False):
    if key in json:
        return json[key]

    if fatal:
        error(f'Cannot find {key} in {json}.')

    return default


def get_content_name(obj):
    content_name = None
    content_name_obj = json_get(obj, CONFIG_VAL_CONTENT_NAME)
    if content_name_obj:
        json_get(content_name_obj, CONFIG_VAL_CONTENT_NAME_ID, fatal=True)
        identifier = content_name_obj[CONFIG_VAL_CONTENT_NAME_ID]

        prefix = ''
        if json_get(content_name_obj, CONFIG_VAL_CONTENT_NAME_PREFIX):
            prefix = content_name_obj[CONFIG_VAL_CONTENT_NAME_PREFIX]

        content_name = ContentName(identifier, prefix)

    return content_name


def json_to_config(obj) -> Config:
    json_get(obj, CONFIG_VAL_SCRAPE_TYPE, fatal=True)

    scrape_type_val = obj[CONFIG_VAL_SCRAPE_TYPE]
    if scrape_type_val not in ScrapeType.keys():
        error(f'Invalid ScrapeType: {scrape_type_val}')

    scrape_type = ScrapeType[scrape_type_val]

    urls = json_get(obj, CONFIG_VAL_URLS, default=List[str])
    out_dir = json_get(obj, CONFIG_VAL_OUT_DIR, default='')
    content_name = get_content_name(obj)

    cookies_obj = json_get(obj, CONFIG_VAL_COOKIES, default={})
    cookies = [Cookie(dictionary=cookie) for cookie in cookies_obj]

    config = Config(scrape_type, urls=urls, cookies=cookies, out_dir=out_dir, content_name=content_name)

    return config


def get_config(file=CONFIG_FILE):
    config_file = Path(file)
    if not config_file.is_file():
        error(f'{file} not found in path')

    with open(file, 'r') as file_obj:
        text = ''.join(file_obj.readlines())

        json_obj = json.loads(text)

        return json_to_config(json_obj)

import random
import shelve
from math import floor
from time import sleep
from typing import List, Tuple, Optional
from urllib.parse import urlparse, ParseResult

import filetype
from selenium import webdriver
from selenium.common.exceptions import NoSuchWindowException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By

from src.config import Config, ScrapeType, ContentName, Cookie, UITask, ScrapeElements, IFrameIgnore
from src.iframe.iframe import IFrameHandler
from src.iframe.vimeo import VimeoIFrameHandler
from src.scrape_classes import ScrapeJob, ScrapeJobType, ScrapeJobTask
from src.util.generic import name_of, distinct, any_list_in_str, first_or_none, replace_with_index, LogType
from src.util.io import validate_path, write_file, DuplicateHandler, ensure_directory_exists, split_full_path, move_file_to_dir, append_to_file, \
    replace_invalid_path_characters
from src.util.ordered_queue import OrderedSetQueue, QueueType
from src.util.selenium_util import wait_page_load, get_ui_element, driver_go_and_wait, wait_page_redirect
from src.util.web.generic import log, download_file, get_referer, get_origin, join_path, is_blank, DownloadedFileResult, GroupByMapping, GroupByPair, \
    get_content_type, url_in_domain, find_urls_in_html_or_js, get_relative_path, url_in_list, url_is_relative, join_url, get_base_url, \
    get_sub_directory_path, get_url_without_fragment
from src.util.web.html_parser import find_html_tag
from src.util.web.sitemap_xml import SitemapXml

CHROME_DRIVER_LOC = 'res/chromedriver.exe'

IGNORED_CONTENT_TYPES = [
    'text/html'
]

DEFAULT_GROUP_BY = GroupByMapping(
    GroupByPair(['.js'], 'js'),
    GroupByPair(['.wasm'], 'wasm'),
    GroupByPair(['.css'], 'css'),
    GroupByPair([f'.{matcher.EXTENSION}' for matcher in filetype.image_matchers], 'images'),
    GroupByPair([f'.{matcher.EXTENSION}' for matcher in filetype.video_matchers], 'videos'),
    GroupByPair([f'.{matcher.EXTENSION}' for matcher in filetype.audio_matchers], 'audio'),
    GroupByPair([f'.{matcher.EXTENSION}' for matcher in filetype.font_matchers], 'fonts'),
    GroupByPair([f'.{matcher.EXTENSION}' for matcher in filetype.archive_matchers], 'archives')
)

DEFAULT_IFRAME_HANDLERS = [
    VimeoIFrameHandler(),
]

CACHE_COMPLETED_URLS_FILE = 'cache/completed_urls.db'
CACHE_QUEUED_URLS_FILE = 'cache/queued_urls.db'

NOT_HANDLED_IFRAMES = []
ALREADY_LOGGED_DOWNLOADED_URLS = []

MAX_RETRIES = 5


def get_mapped_cookies(cookies: List[Cookie]):
    domains = list(set([get_base_url(cookie.domain) for cookie in cookies]))

    mapping = []
    for domain in domains:
        elem = [cookie for cookie in cookies if get_base_url(cookie.domain) == domain]
        mapping.append((f'https://{domain}', elem))

    return mapping


def scrape(config: Config):
    options = Options()
    options.headless = False

    if not is_blank(config.user_agent):
        options.add_argument(f'user-agent={config.user_agent}')

    driver = webdriver.Chrome(options=options, executable_path=CHROME_DRIVER_LOC)

    if len(config.cookies) > 0:
        log('Configuring cookies in Selenium.')
        mapped_cookies = get_mapped_cookies(config.cookies)

        for mapped_cookie in mapped_cookies:
            driver.get(mapped_cookie[0])
            wait_page_load(driver)

            for cookie in mapped_cookie[1]:
                cookie_dict = cookie.__dict__
                driver.add_cookie(cookie_dict)

    if config.login:
        log('Configuring login credentials in Selenium.')

        driver.get(config.login.url)
        for child in config.login.children:
            element = get_ui_element(driver, child, fatal=True)

            if child.value:
                element.send_keys(child.value)

            if child.task:
                if child.task == UITask.GO_TO:
                    driver.switch_to.frame(element)
                elif child.task == UITask.CLICK:
                    old_url = driver.current_url

                    element.click()
                    wait_page_redirect(driver, old_url)

    ensure_directory_exists('/cache')

    if config.scrape_type == ScrapeType.SINGLE_PAGE:
        scrape_single_page(driver, config)
    elif config.scrape_type == ScrapeType.ALL_PAGES:
        for url in config.urls:
            scrape_website(driver, config, url)

    log('All jobs completed!')


def scrape_sitemap(base_url: str) -> List[str]:
    sitemap = SitemapXml.parse_sitemap_by_url(base_url)

    lst = []
    for entry in sitemap.url_set:
        lst.append(entry.url)

    return lst


def add_completed_url_to_cache(url: str, base_url: str):
    with shelve.open(CACHE_COMPLETED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        if url not in lst:
            lst.append(url)

        url_cache[base_url] = lst


def is_url_completed(url: str, base_url: str):
    with shelve.open(CACHE_COMPLETED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        return url in lst


def get_non_cached_sites(urls: List[str], base_url: str, check_cache: bool = True) -> List[str]:
    if not check_cache:
        return urls

    base_url = get_base_url(base_url)

    with shelve.open(CACHE_COMPLETED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        return [url for url in urls if url not in lst]


def process_queue(queue: OrderedSetQueue, driver: WebDriver, config: Config, base_url: str, send_queue: bool = True):
    previously_queued_urls = get_queued_urls(base_url)
    queue.enqueue_list(previously_queued_urls)

    out_dir = config.out_dir.replace('\\', '/')
    while not queue.empty():
        url = queue.dequeue()
        remove_queued_url(url, base_url)

        scrape_page(driver, config, url, base_url, out_dir, queue if send_queue else None)

        if config.min_timeout or config.max_timeout:
            timeout = floor(random.uniform(config.min_timeout, config.max_timeout))
            sleep(timeout)


def add_list_to_queue(queue: OrderedSetQueue, urls: List[str], base_url: str, config: Config):
    for url in urls:
        add_to_queue(queue, url, base_url)


def add_to_queue(queue: OrderedSetQueue, url: str, base_url: str):
    defragmented_url = get_url_without_fragment(url)

    if is_url_completed(defragmented_url, base_url):
        return

    queue.enqueue(defragmented_url)

    with shelve.open(CACHE_QUEUED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        if defragmented_url not in lst:
            lst.append(defragmented_url)

        url_cache[base_url] = lst


def remove_queued_url(url: str, base_url: str):
    with shelve.open(CACHE_QUEUED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        if url in lst:
            lst.remove(url)

        url_cache[base_url] = lst


def get_queued_urls(base_url: str):
    with shelve.open(CACHE_QUEUED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        return lst


def scrape_website(driver: WebDriver, config: Config, base_url: str):
    queue = OrderedSetQueue(queue_type=QueueType.FIFO)
    add_to_queue(queue, base_url, base_url)

    if config.scrape_sitemap:
        sitemap = scrape_sitemap(base_url)
        non_cached_sites = get_non_cached_sites(sitemap, base_url, check_cache=config.cache_completed_urls)

        add_list_to_queue(queue, non_cached_sites, base_url, config)

    process_queue(queue, driver, config, base_url)


def scrape_single_page(driver: WebDriver, config: Config):
    queue = OrderedSetQueue(queue_type=QueueType.FIFO)
    for url in config.urls:
        base_url = get_base_url(url)
        add_to_queue(queue, url, base_url)

    process_queue(queue, driver, config, '', send_queue=False)


def is_ignored_iframe(iframe_ignore_lst: List[IFrameIgnore], identifier: str = '') -> bool:
    for iframe_ignore in iframe_ignore_lst:
        if iframe_ignore.obj_type and identifier and identifier in iframe_ignore.identifier:
            return False

    return True


def scrape_page(driver: WebDriver, config: Config, url: str, base_url: str, out_dir: str, queue: Optional[OrderedSetQueue],
                completed_pages: List[ParseResult] = None, iframe_handlers: List[IFrameHandler] = None):
    page_out_dir = get_sub_directory_path(base_url, url, prepend_dir=out_dir, append_slash=True)
    page_out_dir = replace_invalid_path_characters(page_out_dir)
    index_path = join_path(page_out_dir, filename='index.html')

    driver_go_and_wait(driver, url, config.scroll_pause_time)

    title = get_content_title(driver, content_name=config.content_name)
    downloaded_elements: List[ScrapeJob] = []
    if config.scrape_elements & ScrapeElements.VIDEOS:
        scrape_video_elements(downloaded_elements, config, driver, page_out_dir, title)

    if config.scrape_elements & ScrapeElements.IMAGES:
        scrape_image_elements(downloaded_elements, config, driver, page_out_dir, title)

    if config.scrape_elements & ScrapeElements.HTML:
        scrape_html_elements(downloaded_elements, config, driver, page_out_dir, title)

    if config.scrape_elements & ScrapeElements.IFRAMES:
        if not iframe_handlers:
            iframe_handlers = DEFAULT_IFRAME_HANDLERS

        iframes = driver.find_elements_by_tag_name('iframe')
        for iframe in iframes:
            iframe_handler: IFrameHandler = first_or_none(iframe_handlers, lambda x: x.can_handle(iframe))

            if not iframe_handler:
                outer_html = iframe.get_attribute('outerHTML')
                identifier = iframe.get_attribute('id')

                ignored_iframe = is_ignored_iframe(config.iframe_ignore, identifier=identifier)

                if identifier and not ignored_iframe and identifier not in NOT_HANDLED_IFRAMES:
                    NOT_HANDLED_IFRAMES.append(identifier)
                    append_to_file('cache/failed_iframes.txt', outer_html)
                    log(f'IFRAME_ERROR: No handler for: {outer_html}')

                continue

            driver.switch_to.frame(iframe)
            wait_page_load(driver)

            iframe_jobs = iframe_handler.handle(driver)

            driver.switch_to.default_content()
            wait_page_load(driver)

            for iframe_job in iframe_jobs:
                iframe_job.identifier = iframe.get_attribute('id')

                if iframe_job.scrape_job_type == ScrapeJobType.VIDEO:
                    videos_out_dir = join_path(page_out_dir, f'/{config.data_directory}/videos')
                    iframe_job.file_path = move_file_to_dir(iframe_job.file_path, videos_out_dir, duplicate_handler=DuplicateHandler.HASH_COMPARE)
                    iframe_job.html = '''
                        <video controls style="width: 100%; height: 100%;">
                            <source src="{0}" type="video/mp4">
                        </video> 
                    '''

                downloaded_elements.append(iframe_job)

    if not completed_pages:
        completed_pages = []

    completed_pages.append(urlparse(url))

    relative_links = []
    a_hrefs = []
    a_elements = driver.find_elements_by_tag_name('a')
    for a_element in a_elements:
        href = a_element.get_attribute('href')

        if not href:
            html = a_element.get_attribute('outerHTML')
            log(f'A_ELEMENT: Could not handle: {html})')
            continue

        if url_is_relative(href):
            href = join_url(base_url, href)

        content_type = get_content_type(href, headers=get_default_headers(driver.current_url, config.user_agent))
        if content_type and content_type != 'text/html':
            download_html_element(downloaded_elements, config, driver, href, href, page_out_dir, None)
            continue

        if url_in_domain(base_url, href):
            if href not in relative_links:
                relative_links.append(href)

            if href not in a_hrefs and not any_list_in_str(href, config.substrings_to_skip):
                a_hrefs.append(href)

    for relative_link in relative_links:
        sub_dir = get_sub_directory_path(base_url, relative_link, append_slash=False)
        sub_dir_replaced = replace_invalid_path_characters(sub_dir)
        filename = join_path(out_dir, sub_dir_replaced, filename='index.html')

        scrape_job_relative = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename, url=relative_link)
        scrape_job_sub_dir = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename, url=sub_dir)

        downloaded_elements.append(scrape_job_relative)
        downloaded_elements.append(scrape_job_sub_dir)

    store_html(driver, downloaded_elements, index_path)

    if config.cache_completed_urls:
        add_completed_url_to_cache(url, base_url)

    if queue:
        for src_url in a_hrefs:
            if url_in_list(src_url, completed_pages):
                continue

            add_to_queue(queue, src_url, base_url)


def download_html_element(downloaded_elements: List[ScrapeJob], config: Config, driver: WebDriver, file_url: str, original_url: str, page_out_dir: str,
                          ideal_filename: Optional[str]):
    content_out_dir = join_path(page_out_dir, f'/{config.data_directory}')

    headers = None
    retry = 0
    while not headers and retry < MAX_RETRIES:
        try:
            headers = get_default_headers(driver.current_url, config.user_agent)

            retry = MAX_RETRIES
        except NoSuchWindowException:
            retry += 1
            driver.refresh()
            wait_page_load(driver)

            if retry == MAX_RETRIES:
                pass

    if get_content_type(file_url, headers=headers) == 'text/html':
        return

    filename = download_element(driver.current_url, file_url, out_dir=content_out_dir, filename=ideal_filename, user_agent=config.user_agent,
                                group_by=DEFAULT_GROUP_BY)

    if not filename:
        return

    '''
    if filename.endswith('.js'):
        js_files.append(filename)
    '''

    scrape_job = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename, url=original_url or file_url)
    downloaded_elements.append(scrape_job)


def scrape_html_elements(downloaded_elements: List[ScrapeJob], config: Config, driver: WebDriver, page_out_dir: str, title: str):
    # js_files = []
    completed_urls = distinct([element.url for element in downloaded_elements])
    urls = find_urls_in_html_or_js(str(driver.page_source))
    urls = [(url, original_url) for url, original_url in urls if url not in completed_urls]
    for i in range(len(urls)):
        file_url, original_url = urls[i]

        ideal_filename = None
        if title:
            ideal_filename = title + (f' - {i + 1}' if len(urls) > 1 else '')

        download_html_element(downloaded_elements, config, driver, file_url, original_url, page_out_dir, ideal_filename)
        '''
        for js_file in js_files:
            parse_js_urls(js_file, driver.current_url, content_out_dir, downloaded_elements, user_agent=config.user_agent, group_by=DEFAULT_GROUP_BY)
        '''


def scrape_image_elements(downloaded_elements: List[ScrapeJob], config: Config, driver: WebDriver, page_out_dir: str, title: str):
    image_out_dir = join_path(page_out_dir, f'/{config.data_directory}/images')
    elements = scrape_generic_content(driver, config, title, 'img', 'src', image_out_dir)
    downloaded_elements.extend(elements)


def scrape_video_elements(downloaded_elements: List[ScrapeJob], config: Config, driver: WebDriver, page_out_dir: str, title: str):
    video_out_dir = join_path(page_out_dir, f'/{config.data_directory}/videos')
    elements = scrape_generic_content(driver, config, title, 'video', 'src', video_out_dir, src_element='source')
    downloaded_elements.extend(elements)


'''
def parse_js_urls(filename: str, current_url: str, content_out_dir: str, downloaded_elements: List[ScrapeJob], user_agent: str,
                  group_by: GroupByMapping = None):
    text = read_file(filename)

    completed_urls = distinct([element.url for element in downloaded_elements])
    urls = find_urls_in_html_or_js(text)
    urls = [(url, original_url) for url, original_url in urls if url not in completed_urls]
    for i in range(len(urls)):
        file_url, original_url = urls[i]

        if get_content_type(file_url, headers=get_default_headers(current_url, config)) == 'text/html':
            continue

        filename = download_element(current_url, file_url, out_dir=content_out_dir, user_agent=user_agent, group_by=group_by)

        if not filename:
            continue

        scrape_job = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename, url=original_url or file_url)
        downloaded_elements.append(scrape_job)
'''


def get_content_title(driver: WebDriver, content_name: ContentName) -> str:
    if not content_name:
        return ''

    element = driver.find_element_by_xpath(content_name.identifier)

    return element.text


def get_default_headers(current_url: str, user_agent: str) -> List[Tuple[str, str]]:
    lst = get_default_origin_headers(current_url)

    if user_agent:
        lst.append(('User-Agent', user_agent))

    return lst


def get_default_origin_headers(url: str) -> List[Tuple[str, str]]:
    return [
        ('Referer', get_referer(url)),
        ('Origin', get_origin(url)),
    ]


def download_element(current_url: str, src_url: str, out_dir: str = None, filename: str = None, user_agent: str = None, group_by: GroupByMapping = None,
                     log_every_time: bool = False) \
        -> Optional[str]:
    full_path = None

    if out_dir:
        full_path = validate_path(out_dir)

    headers = get_default_headers(current_url, user_agent)
    downloaded_file = download_file(src_url, ideal_filename=filename, out_dir=full_path, headers=headers, duplicate_handler=DuplicateHandler.HASH_COMPARE,
                                    ignored_content_types=IGNORED_CONTENT_TYPES, group_by=group_by)

    if downloaded_file.result == DownloadedFileResult.SKIPPED:
        if log_every_time or src_url not in ALREADY_LOGGED_DOWNLOADED_URLS:
            log(f'Skipped download {src_url}')
            ALREADY_LOGGED_DOWNLOADED_URLS.append(src_url)

        return None
    elif downloaded_file.result == DownloadedFileResult.FAIL:
        if log_every_time or src_url not in ALREADY_LOGGED_DOWNLOADED_URLS:
            log(f'Failed on download {src_url}', fatal=False, log_type=LogType.ERROR)
            ALREADY_LOGGED_DOWNLOADED_URLS.append(src_url)

        return None

    if log_every_time or src_url not in ALREADY_LOGGED_DOWNLOADED_URLS:
        log(f'Successfully downloaded {src_url}', fatal=False, log_type=LogType.INFO)
        ALREADY_LOGGED_DOWNLOADED_URLS.append(src_url)

    return downloaded_file.filename


def modify_url_for_replace(filename: str, url: str, types: List[str] = None) -> List[ScrapeJob]:
    if types is None:
        types = ['\'', '"', '()']

    lst = []
    for brace_type in types:
        start = None
        end = None
        if len(brace_type) == 1:
            start = end = brace_type[0]
        elif len(brace_type) == 2:
            start = brace_type[0]
            end = brace_type[1]
        else:
            log(f'Unsupported number of characters in type: {brace_type}', name_of(modify_url_for_replace), log_type=LogType.ERROR)

        filename_new = f'{start}{filename}{end}'
        url_new = f'{start}{url}{end}'

        lst.append(ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename_new, url=url_new))

    return lst


def store_html(driver: WebDriver, downloaded_elements: List[ScrapeJob], index_file: str):
    html = str(driver.page_source)

    out_dir, _ = split_full_path(index_file)

    for elem in downloaded_elements:
        if elem.scrape_job_type == ScrapeJobType.URL:
            if not elem.file_path:
                continue

            new_filename = get_relative_path(elem.file_path, out_dir)

            pairings = modify_url_for_replace(new_filename, elem.url)
            for pairing in pairings:
                html = html.replace(pairing.url, pairing.file_path)
        elif elem.scrape_job_type == ScrapeJobType.VIDEO:
            if not elem.file_path:
                continue

            new_filename = get_relative_path(elem.file_path, out_dir)
            start, end = find_html_tag(By.ID, elem.identifier, html)

            replacement_html = elem.html.format(new_filename)
            replaced_html = replace_with_index(html, replacement_html, start, end)

            html = replaced_html

    write_file(index_file, html, encoding='utf-8')


def scrape_generic_content(driver: WebDriver, config: Config, title: str, tag: str, link_attribute: str, out_dir: str, src_element: str = None,
                           group_by: GroupByMapping = None) -> List[ScrapeJob]:
    downloaded_elements = []

    tag_elements = driver.find_elements_by_tag_name(tag)
    for i in range(len(tag_elements)):
        source = tag_elements[i]
        if src_element:
            source = source.find_element_by_tag_name(src_element)

        src_url: str = source.get_attribute(link_attribute)
        if not src_url:
            outer_html = source.get_attribute('outerHTML')
            tag_outer_html = tag_elements[i].get_attribute('outerHTML')
            log(f'Could not find {name_of(src_url)}, skipping generic scrape on {tag} {i + 1}. HTML: {outer_html}, src_element: {src_element}, '
                f'tag: {tag_outer_html}', fatal=False, log_type=LogType.ERROR)
            continue

        log(f'Starting {link_attribute} download {i + 1}/{len(tag_elements)}.', end='\r')

        ideal_filename = None
        if title:
            ideal_filename = title + (f' - {i + 1}' if len(tag_elements) > 1 else '')

        filename = download_element(driver.current_url, src_url, out_dir=out_dir, filename=ideal_filename, user_agent=config.user_agent, group_by=group_by)

        scrape_job = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.URL, file_path=filename, url=src_url)
        downloaded_elements.append(scrape_job)

    return downloaded_elements

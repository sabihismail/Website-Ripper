import random
import shelve
from collections import deque
from math import floor
from time import sleep
from typing import List, Tuple, Optional, NamedTuple
from urllib.parse import urlparse, ParseResult

import filetype
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from src.config import Config, ScrapeType, ContentName, Cookie, UIElement, UITask, ScrapeElements
from src.util.generic import name_of, distinct, any_list_in_str
from src.util.io import validate_path, write_file, DuplicateHandler, ensure_directory_exists, split_full_path
from src.util.ordered_queue import OrderedSetQueue, QueueType
from src.util.web import error, download_file, get_referer, get_origin, combine_path, is_blank, DownloadedFileResult, GroupByMapping, GroupByPair, \
    get_content_type, url_in_domain, find_urls_in_html, get_relative_path, url_in_list, url_is_relative, join_url, is_url_exact, get_base_url, \
    get_sub_directory_path

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

CACHE_COMPLETED_URLS_FILE = 'cache/completed_urls.db'


class FileURLPair(NamedTuple):
    filename: str
    url: str


def wait_page_load(driver: WebDriver):
    page_state = driver.execute_script('return document.readyState;')

    while page_state != 'complete':
        sleep(1)


def scroll_to_bottom(driver: WebDriver, scroll_pause_time: float = 1.0):
    last_height = driver.execute_script('return document.body.scrollHeight - document.documentElement.scrollTop;')

    while True:
        driver.execute_script('''
            window.scrollBy({
              top: window.innerHeight - 10,
              left: 0,
              behavior: 'smooth'
            });
        ''')

        sleep(scroll_pause_time)

        new_height = driver.execute_script('return document.body.scrollHeight - document.documentElement.scrollTop;')
        if new_height == last_height:
            break

        last_height = new_height


def driver_go_and_wait(driver: WebDriver, url: str, scroll_pause_time: float, fail: int = 0):
    if fail >= 5:
        error(f'URL does not ever match, {url} never becomes {driver.current_url}')

    driver.get(url)
    wait_page_load(driver)

    if not is_url_exact(driver.current_url, url):
        driver_go_and_wait(driver, url, fail + 1)

    scroll_to_bottom(driver, scroll_pause_time=scroll_pause_time)


def get_mapped_cookies(cookies: List[Cookie]):
    domains = list(set([get_base_url(cookie.domain) for cookie in cookies]))

    mapping = []
    for domain in domains:
        elem = [cookie for cookie in cookies if get_base_url(cookie.domain) == domain]
        mapping.append((f'https://{domain}', elem))

    return mapping


def get_ui_element(driver: WebDriver, element: UIElement, timeout=30, fatal=True) -> Optional[WebElement]:
    specifier = (element.ui_type, element.identifier)

    try:
        wait = WebDriverWait(driver, timeout)
        found_element = wait.until(expected_conditions.visibility_of_element_located(specifier))

        return found_element
    except TimeoutException:
        if fatal:
            exit(f'Could not find {element}')
        else:
            return None


def scrape(config: Config):
    ensure_directory_exists('/cache')

    options = Options()
    options.headless = False

    if not is_blank(config.user_agent):
        options.add_argument(f'user-agent={config.user_agent}')

    driver = webdriver.Chrome(options=options, executable_path=CHROME_DRIVER_LOC)

    if len(config.cookies) > 0:
        print('Configuring cookies in Selenium.')
        mapped_cookies = get_mapped_cookies(config.cookies)

        for mapped_cookie in mapped_cookies:
            driver.get(mapped_cookie[0])
            wait_page_load(driver)

            for cookie in mapped_cookie[1]:
                cookie_dict = cookie.__dict__
                driver.add_cookie(cookie_dict)

    if config.login:
        print('Configuring login credentials in Selenium.')

        driver.get(config.login.url)
        for child in config.login.children:
            element = get_ui_element(driver, child, fatal=True)

            if child.value:
                element.send_keys(child.value)

            if child.task:
                if child.task == UITask.GO_TO:
                    driver.switch_to.frame(element)
                elif child.task == UITask.CLICK:
                    element.click()

    if config.scrape_type == ScrapeType.SINGLE_PAGE:
        scrape_single_page(driver, config)
    elif config.scrape_type == ScrapeType.ALL_PAGES:
        for url in config.urls:
            scrape_website(driver, config, url)

    print('All jobs completed!')


def scrape_sitemap(base_url: str) -> List[str]:
    return []


def add_completed_url_to_cache(url: str, base_url: str):
    base_url = get_base_url(base_url)

    with shelve.open(CACHE_COMPLETED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        if url not in lst:
            lst.append(url)

        url_cache[base_url] = lst


def get_non_cached_sites(urls: List[str], base_url: str, check_cache: bool = True) -> List[str]:
    if not check_cache:
        return urls

    base_url = get_base_url(base_url)

    with shelve.open(CACHE_COMPLETED_URLS_FILE, writeback=True) as url_cache:
        lst: List[str] = url_cache.get(base_url, default=[])

        return [url for url in urls if url not in lst]


def process_queue(queue: OrderedSetQueue, driver: WebDriver, config: Config, base_url: str, send_queue: bool = True):
    while not queue.empty():
        url = queue.dequeue()

        out_dir = combine_path(config.out_dir, url[len(base_url):])
        scrape_page(driver, config, url, base_url, out_dir, queue if send_queue else None)

        if config.min_timeout or config.max_timeout:
            timeout = floor(random.uniform(config.min_timeout, config.max_timeout))
            sleep(timeout)


def scrape_website(driver: WebDriver, config: Config, base_url: str):
    queue = OrderedSetQueue(queue_type=QueueType.FIFO)
    queue.enqueue(base_url)

    if config.scrape_sitemap:
        sitemap = scrape_sitemap(base_url)
        non_cached_sites = get_non_cached_sites(sitemap, base_url, check_cache=config.cache_completed_urls)

        queue.enqueue_list(non_cached_sites)

    process_queue(queue, driver, config, base_url)


def scrape_single_page(driver: WebDriver, config: Config):
    queue = OrderedSetQueue(queue_type=QueueType.FIFO)
    queue.enqueue_list(config.urls)

    process_queue(queue, driver, config, '', send_queue=False)


def scrape_page(driver: WebDriver, config: Config, url: str, base_url: str, out_dir: str, queue: Optional[OrderedSetQueue],
                completed_pages: List[ParseResult] = None):
    page_out_dir = get_sub_directory_path(base_url, url, prepend_dir=out_dir, append_slash=True)
    index_path = combine_path(page_out_dir, filename='index.html')

    driver_go_and_wait(driver, url, config.scroll_pause_time)

    title = get_content_title(driver, content_name=config.content_name)
    downloaded_elements: List[FileURLPair] = []
    if config.scrape_elements & ScrapeElements.VIDEOS:
        video_out_dir = combine_path(page_out_dir, f'/{config.data_directory}/videos')
        elements = scrape_generic_content(driver, config, title, 'video', 'src', video_out_dir, src_element='source')

        downloaded_elements.extend(elements)

    if config.scrape_elements & ScrapeElements.IMAGES:
        image_out_dir = combine_path(page_out_dir, f'/{config.data_directory}/images')
        elements = scrape_generic_content(driver, config, title, 'img', 'src', image_out_dir)

        downloaded_elements.extend(elements)

    if config.scrape_elements & ScrapeElements.HTML:
        completed_urls = distinct([element.url for element in downloaded_elements])

        urls = find_urls_in_html(str(driver.page_source))
        urls = [(url, original_url) for url, original_url in urls if url not in completed_urls]
        for i in range(len(urls)):
            file_url, original_url = urls[i]

            if url_in_domain(base_url, file_url) or get_content_type(file_url, headers=default_origin_headers(driver)) == 'text/html':
                continue

            content_out_dir = combine_path(page_out_dir, f'/{config.data_directory}')
            filename = download_element(driver, file_url, out_dir=content_out_dir, title=title, current_index=i, length=len(urls), user_agent=config.user_agent,
                                        group_by=DEFAULT_GROUP_BY)

            if not filename:
                continue

            downloaded_elements.append(FileURLPair(filename, original_url if original_url else file_url))

    if not completed_pages:
        completed_pages = []

    completed_pages.append(urlparse(url))

    relative_links = []
    a_hrefs = []
    a_elements = driver.find_elements_by_tag_name('a')
    for a_element in a_elements:
        href = a_element.get_attribute('href')

        if url_is_relative(href):
            href = join_url(base_url, href)

        if href and url_in_domain(base_url, href):
            if href not in relative_links:
                relative_links.append(href)

            if href not in a_hrefs and not any_list_in_str(href, config.substrings_to_skip):
                a_hrefs.append(href)

    for relative_link in relative_links:
        sub_dir = get_sub_directory_path(base_url, relative_link, append_slash=False)
        filename = combine_path(out_dir, sub_dir, filename='index.html')

        downloaded_elements.append(FileURLPair(filename, relative_link))
        downloaded_elements.append(FileURLPair(filename, sub_dir))

    store_html(driver, downloaded_elements, index_path)

    if config.cache_completed_urls:
        add_completed_url_to_cache(url, base_url)

    if queue:
        for src_url in a_hrefs:
            if url_in_list(src_url, completed_pages):
                continue

            queue.enqueue(src_url)


def get_content_title(driver: WebDriver, content_name: ContentName) -> str:
    if is_blank(content_name):
        return ''

    element = driver.find_element_by_xpath(content_name.identifier)

    return element.text


def default_origin_headers(driver: WebDriver) -> List[Tuple[str, str]]:
    return [
        ('Referer', get_referer(driver.current_url)),
        ('Origin', get_origin(driver.current_url)),
    ]


def download_element(driver: WebDriver, src_url: str, out_dir: str = None, title: str = None, current_index: int = -1, length: int = -1, user_agent: str = None,
                     group_by: GroupByMapping = None) -> Optional[str]:
    full_path = None
    filename = None
    if title:
        filename = title + (f' - {current_index + 1}' if length > 1 else '')

    if out_dir:
        full_path = validate_path(out_dir)

    headers = default_origin_headers(driver)

    if user_agent:
        headers.append(('User-Agent', user_agent))

    downloaded_file = download_file(src_url, ideal_filename=filename, out_dir=full_path, headers=headers, duplicate_handler=DuplicateHandler.HASH_COMPARE,
                                    ignored_content_types=IGNORED_CONTENT_TYPES, group_by=group_by)

    if downloaded_file.result == DownloadedFileResult.SKIPPED:
        print(f'Skipped download {src_url}')

        return None
    elif downloaded_file.result == DownloadedFileResult.FAIL:
        error(f'Failed on download {src_url}', fatal=False)

        return None

    return downloaded_file.filename


def modify_url_for_replace(filename: str, url: str, types: List[str] = None) -> List[FileURLPair]:
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
            error(f'Unsupported number of characters in type: {brace_type}', name_of(modify_url_for_replace))

        filename_new = f'{start}{filename}{end}'
        url_new = f'{start}{url}{end}'

        lst.append(FileURLPair(filename_new, url_new))

    return lst


def store_html(driver: WebDriver, downloaded_elements: List[FileURLPair], index_file: str):
    html = str(driver.page_source)

    for elem in downloaded_elements:
        if not elem.filename:
            continue

        out_dir, _ = split_full_path(index_file)
        new_filename = get_relative_path(elem[0], out_dir)

        pairings = modify_url_for_replace(new_filename, elem.url)
        for pairing in pairings:
            html = html.replace(pairing.url, pairing.filename)

    write_file(index_file, html, encoding='utf-8')


def scrape_generic_content(driver: WebDriver, config: Config, title: str, tag: str, link_attribute: str, out_dir: str, src_element: str = None,
                           group_by: GroupByMapping = None) \
        -> List[FileURLPair]:
    downloaded_elements = []

    tag_elements = driver.find_elements_by_tag_name(tag)
    for i in range(len(tag_elements)):
        print(f'Starting {link_attribute} download {i + 1}/{len(tag_elements)}.')

        source = tag_elements[i]
        if src_element:
            source = source.find_element_by_tag_name(src_element)

        src_url: str = source.get_attribute(link_attribute)

        if not src_url:
            error(f'Could not find {name_of(src_url)}, skipping generic scrape on {tag} {i + 1}', fatal=False)
            continue

        filename = download_element(driver, src_url, out_dir=out_dir, title=title, current_index=i, length=len(tag_elements), user_agent=config.user_agent,
                                    group_by=group_by)

        downloaded_elements.append(FileURLPair(filename, src_url))

    return downloaded_elements

from time import sleep
from typing import List, Tuple, Optional
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
from src.util.generic import name_of, distinct, contains_substring
from src.util.io import validate_path, write_file, DuplicateHandler
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


def wait_page_load(driver: WebDriver):
    page_state = driver.execute_script('return document.readyState;')

    while page_state != 'complete':
        sleep(1)


def driver_go_and_wait(driver: WebDriver, url: str, fail: int = 0):
    if fail >= 5:
        error(f'URL does not ever match, {url} never becomes {driver.current_url}')

    driver.get(url)
    wait_page_load(driver)

    if not is_url_exact(driver.current_url, url):
        driver_go_and_wait(driver, url, fail + 1)


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


def scrape_website(driver: WebDriver, config: Config, base_url: str):
    out_dir = combine_path(config.out_dir, base_url[len(base_url):])

    scrape_page(driver, config, base_url, base_url, out_dir, follow_links=True)


def scrape_single_page(driver: WebDriver, config: Config):
    print('Beginning URL downloads.')
    for i in range(len(config.urls)):
        print(f'Starting download of page {i + 1}/{len(config.urls)}.')
        scrape_page(driver, config, config.urls[i], '', config.out_dir, follow_links=False)


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


def scrape_page(driver: WebDriver, config: Config, url: str, base_url: str, out_dir: str, follow_links: bool = True,
                completed_pages: List[ParseResult] = None):
    driver_go_and_wait(driver, url)

    page_out_dir = get_sub_directory_path(base_url, url, prepend_dir=out_dir, append_slash=True)
    title = get_content_title(driver, content_name=config.content_name)

    downloaded_elements = []
    if config.scrape_elements & ScrapeElements.VIDEOS:
        video_out_dir = combine_path(page_out_dir, f'/{config.data_directory}/videos')
        elements = scrape_generic_content(driver, config, title, 'video', 'src', video_out_dir, src_element='source')

        downloaded_elements.extend(elements)

    if config.scrape_elements & ScrapeElements.IMAGES:
        image_out_dir = combine_path(page_out_dir, f'/{config.data_directory}/images')
        elements = scrape_generic_content(driver, config, title, 'img', 'src', image_out_dir)

        downloaded_elements.extend(elements)

    if config.scrape_elements & ScrapeElements.HTML:
        completed_urls = distinct([b for a, b in downloaded_elements])

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

            downloaded_elements.append((filename, original_url if original_url else file_url))

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

            if href not in a_hrefs and not contains_substring(href, config.substrings_to_skip):
                a_hrefs.append(href)

    for relative_link in relative_links:
        sub_dir = get_sub_directory_path(base_url, relative_link, append_slash=False)
        filename = combine_path(out_dir, sub_dir, 'index.html')

        downloaded_elements.append((filename, f'\'{relative_link}\''))
        downloaded_elements.append((filename, f'\'{sub_dir}\''))
        downloaded_elements.append((filename, f'"{relative_link}"'))
        downloaded_elements.append((filename, f'"{sub_dir}"'))

    store_html(driver, downloaded_elements, page_out_dir)

    for src_url in a_hrefs:
        if url_in_list(src_url, completed_pages):
            continue

        if follow_links:
            scrape_page(driver, config, src_url, base_url, out_dir, follow_links=True, completed_pages=completed_pages)


def store_html(driver: WebDriver, downloaded_elements: List[Tuple[str, str]], out_dir: str):
    html = str(driver.page_source)

    for elem in downloaded_elements:
        if not elem[0]:
            continue

        new_filename = get_relative_path(elem[0], out_dir)

        html = html.replace(elem[1], new_filename)

    write_file(out_dir, html, filename='index.html', encoding='utf-8')


def scrape_generic_content(driver: WebDriver, config: Config, title: str, tag: str, link_attribute: str, out_dir: str, src_element: str = None,
                           group_by: GroupByMapping = None) \
        -> List[Tuple[str, str]]:
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

        downloaded_elements.append((filename, src_url))

    return downloaded_elements

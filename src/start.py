from http.client import HTTPMessage
from time import sleep
from typing import List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.config import Config, ScrapeType, ContentName, Cookie
from src.util import error, get_file_extension, validate_path, download_file, get_valid_filename, get_referer, \
    get_origin, combine_path

CHROME_DRIVER_LOC = 'res/chromedriver.exe'


def get_base_url(domain: str):
    if domain.startswith('.'):
        domain = domain[1:]

    return domain


def wait_page_load(driver: WebDriver):
    page_state = driver.execute_script('return document.readyState;')

    while page_state != 'complete':
        sleep(1)


def driver_go_and_wait(driver: WebDriver, url: str):
    driver.get(url)
    wait_page_load(driver)

    fail = 0
    while driver.current_url != url:
        driver_go_and_wait(driver, url)
        fail += 1

        if fail >= 5:
            error(f'URL doesn\'t ever become requested URL')


def get_mapped_cookies(cookies: List[Cookie]):
    domains = list(set([get_base_url(cookie.domain) for cookie in cookies]))

    mapping = []
    for domain in domains:
        elem = [cookie for cookie in cookies if get_base_url(cookie.domain) == domain]
        mapping.append((f'https://{domain}', elem))

    return mapping


def get_by_any_type(driver: WebDriver, identifier: str, fatal: bool = False) -> List[WebElement]:
    element = driver.find_elements_by_id(identifier)
    if element:
        return element

    element = driver.find_elements_by_class_name(identifier)
    if element:
        return element

    element = driver.find_elements_by_tag_name(identifier)
    if element:
        return element

    element = driver.find_elements_by_xpath(identifier)
    if element:
        return element

    element = driver.find_elements_by_name(identifier)
    if element:
        return element

    if fatal:
        error(f'Cannot find element {identifier}')

    return []


def start(config: Config):
    options = Options()
    options.headless = False

    if config.user_agent:
        options.add_argument(f"user-agent={config.user_agent}")

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
        wait_page_load(driver)

        user_input = get_by_any_type(driver, config.login.user_id, fatal=True)[0]
        password_input = get_by_any_type(driver, config.login.password_id, fatal=True)[0]
        submit_button = get_by_any_type(driver, config.login.submit_id, fatal=True)[0]

    if config.scrape_type == ScrapeType.SINGLE_PAGE:
        scrape_single_page(driver, config)
    elif config.scrape_type == ScrapeType.ALL_PAGES:
        for url in config.urls:
            scrape_website(driver, config, url, url)

    print('All jobs completed!')


def scrape_website(driver, config, base_url, current_url):
    out_dir = combine_path(config.out_dir, current_url[len(base_url):])

    scrape_page(driver, config, current_url, out_dir)


def scrape_single_page(driver, config):
    print('Beginning URL downloads.')
    for i in range(len(config.urls)):
        print(f'Starting download of page {i + 1}/{len(config.urls)}.')
        scrape_page(driver, config, config.urls[i], config.out_dir)


def get_content_title(driver: WebDriver, content_name: ContentName) -> str:
    if not content_name or content_name.identifier.isspace():
        return ''

    element = driver.find_element_by_xpath(content_name.identifier)

    return element.text


def download_element(driver: WebDriver, src_url: str, out_dir: str = None, title: str = None, current_index: int = -1,
                     length: int = -1) -> Tuple[str, HTTPMessage]:
    ext = get_file_extension(src_url)
    filename = title + (f' - {current_index + 1}' if length > 1 else '') + '.' + ext

    full_path = validate_path(out_dir)
    full_path = get_valid_filename(full_path, filename)

    headers = [
        ('Referer', get_referer(driver.current_url)),
        ('Origin', get_origin(driver.current_url)),
    ]

    return download_file(src_url, full_path, headers=headers)


def get_relative_path(file: str, directory: str):
    directory = directory.replace('\\', '/')

    size = len(directory)
    if not directory.endswith('/'):
        size += 1

    ret = './' + file[size:]

    return ret


def scrape_page(driver: WebDriver, config: Config, url: str, out_dir: str):
    driver_go_and_wait(driver, url)

    title = get_content_title(driver, content_name=config.content_name)

    downloaded_elements = []
    videos = driver.find_elements_by_tag_name('video')
    for i in range(len(videos)):
        print(f'Starting video download {i + 1}/{len(videos)}.')

        source = videos[i].find_element_by_tag_name('source')
        src_url = source.get_attribute('src')

        filename, _ = download_element(driver, src_url, out_dir=out_dir, title=title, current_index=i,
                                       length=len(videos))

        downloaded_elements.append((src_url, filename))

    images = driver.find_elements_by_tag_name('img')
    for i in range(len(images)):
        print(f'Starting image download {i + 1}/{len(images)}.')

        src_url = images[i].get_attribute('src')

        filename, _ = download_element(driver, src_url, out_dir=out_dir, title=title, current_index=i,
                                       length=len(images))

        downloaded_elements.append((src_url, filename))

    html = str(driver.page_source)
    for elem in downloaded_elements:
        new_filename = get_relative_path(elem[1], out_dir)

        html.replace(elem[0], new_filename)


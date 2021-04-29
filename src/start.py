from time import sleep
from typing import List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver

from src.config import Config, ScrapeType, ContentName, Cookie
from src.util import error, get_file_extension, validate_path, download_file, get_valid_filename, get_referer, \
    get_origin

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


def start(config: Config):
    options = Options()
    options.headless = False
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

    print('Beginning URL downloads.')
    for i in range(len(config.urls)):
        print(f'Starting download of page {i + 1}/{len(config.urls)}.')
        start_driver(driver, config, config.urls[i])

    print('All jobs completed!')


def get_content_title(driver: WebDriver, content_name: ContentName) -> str:
    if not content_name or content_name.identifier.isspace():
        return ''

    element = driver.find_element_by_xpath(content_name.identifier)

    return element.text


def start_driver(driver: WebDriver, config: Config, url: str):
    driver_go_and_wait(driver, url)

    title = ''
    if config.scrape_type == ScrapeType.SINGLE_PAGE:
        title = get_content_title(driver, content_name=config.content_name)

    videos = driver.find_elements_by_tag_name('video')

    for i in range(len(videos)):
        print(f'Starting video download {i + 1}/{len(videos)}.')

        source = videos[i].find_element_by_tag_name('source')
        src_url = source.get_attribute('src')

        ext = get_file_extension(src_url)
        filename = title + (f' - {i + 1}' if len(videos) > 1 else '') + '.' + ext

        full_path = validate_path(config.out_dir)
        full_path = get_valid_filename(full_path, filename)

        headers = [
            ('Referer', get_referer(driver.current_url)),
            ('Origin', get_origin(driver.current_url)),
        ]

        download_file(src_url, full_path, headers=headers)

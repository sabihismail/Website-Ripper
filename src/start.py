import mimetypes
import os
import re
from http.client import HTTPMessage
from pathlib import Path
from time import sleep
from typing import List, Tuple, Optional
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from src.config import Config, ScrapeType, ContentName, Cookie, UIElement, UITask
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


def is_url_exact(u1: str, u2: str):
    smallest = u1 if min(len(u1), len(u2)) == len(u1) else u2
    largest = u2 if u1 == smallest else u1

    return smallest + '/' == largest


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
                     length: int = -1, user_agent: str = None) -> str:
    full_path = None
    if title:
        ext = get_file_extension(src_url)
        filename = title + (f' - {current_index + 1}' if length > 1 else '') + '.' + ext

        full_path = validate_path(out_dir)
        full_path = get_valid_filename(full_path, filename)

    headers = [
        ('Referer', get_referer(driver.current_url)),
        ('Origin', get_origin(driver.current_url)),
    ]

    filename, headers = download_file(src_url, full_path, headers=headers, user_agent=user_agent)

    actual_name = None
    content_disposition = headers.get('Content-Disposition', failobj=None)
    if content_disposition:
        actual_name = re.findall('filename=(.+)', content_disposition)[0]

    content_type = headers.get('Content-Type', failobj=None)
    if not content_disposition and content_type:
        ext = mimetypes.guess_extension(content_type)

        actual_name = f'{filename}.{ext}'

    if actual_name:
        real_path = Path(filename)
        out_path = combine_path(str(real_path.parent), actual_name)

        filename = str(real_path.rename(out_path)).replace('\\', '/')

    return filename


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

        filename = download_element(driver, src_url, out_dir=out_dir, title=title, current_index=i, length=len(videos),
                                    user_agent=config.user_agent)

        downloaded_elements.append((src_url, filename))

    images = driver.find_elements_by_tag_name('img')
    for i in range(len(images)):
        print(f'Starting image download {i + 1}/{len(images)}.')

        src_url = images[i].get_attribute('src')

        filename = download_element(driver, src_url, out_dir=out_dir, title=title, current_index=i, length=len(images),
                                    user_agent=config.user_agent)

        downloaded_elements.append((src_url, filename))

    html = str(driver.page_source)
    for elem in downloaded_elements:
        new_filename = get_relative_path(elem[1], out_dir)

        html.replace(elem[0], new_filename)


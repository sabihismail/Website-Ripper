from enum import Enum
from time import sleep
from typing import Optional

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from src.util.generic import log, LogType
from src.util.web.generic import is_url_exact


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


def driver_go_and_wait(driver: WebDriver, url: str, scroll_pause_time: float, fail: int = 0):
    if fail >= 5:
        log(f'URL does not ever match, {url} never becomes {driver.current_url}', log_type=LogType.ERROR)

    driver.get(url)
    wait_page_load(driver)

    if not is_url_exact(driver.current_url, url):
        driver_go_and_wait(driver, url, fail + 1)

    scroll_to_bottom(driver, scroll_pause_time=scroll_pause_time)


def wait_page_load(driver: WebDriver):
    page_state = driver.execute_script('return document.readyState;')

    while page_state != 'complete':
        sleep(1)


def wait_page_redirect(driver: WebDriver, current_url: str):
    wait = WebDriverWait(driver, 10)
    wait.until(expected_conditions.url_changes(current_url))

    wait_page_load(driver)


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

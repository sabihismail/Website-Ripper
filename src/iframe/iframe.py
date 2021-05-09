from typing import List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.util.web.generic import FileURLPair


class IFrameHandler:
    def can_handle(self, element: WebElement) -> bool:
        raise NotImplemented(f'Implement can_handle function')

    def handle(self, driver: WebDriver) -> List[FileURLPair]:
        raise NotImplemented(f'Implement handle function')

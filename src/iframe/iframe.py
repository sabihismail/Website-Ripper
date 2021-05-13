from typing import List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.scrape_classes import ScrapeJob


class IFrameHandler:
    def can_handle(self, element: WebElement) -> bool:
        raise NotImplemented(f'Implement can_handle function')

    def handle(self, driver: WebDriver) -> List[ScrapeJob]:
        raise NotImplemented(f'Implement handle function')

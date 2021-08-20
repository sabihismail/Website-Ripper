from typing import List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.config import Config
from src.scrape_classes import ScrapeJob


class VideoHandler:
    def can_handle(self, element: WebElement, driver: WebDriver) -> bool:
        raise NotImplemented(f'Implement can_handle function')

    def handle(self, driver: WebDriver, config: Config) -> List[ScrapeJob]:
        raise NotImplemented(f'Implement handle function')

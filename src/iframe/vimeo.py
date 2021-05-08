from typing import Optional, List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.iframe.iframe import IFrameHandler
from src.util.generic import first_or_none
from src.util.web.generic import FileURLPair, extract_json_from_text


class VimeoIFrameHandler(IFrameHandler):
    def can_handle(self, element: WebElement) -> bool:
        src: Optional[str] = element.get_attribute('src')

        return src and 'player.vimeo' in src

    def handle(self, driver: WebDriver) -> List[FileURLPair]:
        lst: List[FileURLPair] = []

        scripts = [script.get_attribute('innerHTML') for script in driver.find_elements_by_tag_name('script')]
        script = first_or_none(scripts, lambda element: 'player.vimeo.com' in element)
        json = extract_json_from_text(script)

        return lst

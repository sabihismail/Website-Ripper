import json
from typing import Optional, List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.config import Config
from src.scrape import get_default_headers
from src.scrape_classes import ScrapeJob, ScrapeJobTask, ScrapeJobType
from src.util.generic import first_or_none
from src.util.io import DuplicateHandler
from src.util.json_util import json_parse, json_parse_class_list
from src.util.web.generic import extract_json_from_text, download_to_str, download_file, get_filename_from_url, DownloadedFileResult
from src.video.iframe import VideoHandler


class WistiaVideoMediaAsset:
    def __init__(self, video_type: str, size: int, url: str):
        self.video_type = video_type
        self.size = size
        self.url = url

    def __repr__(self):
        return str(self.__dict__)


class WistiaVideoMedia:
    def __init__(self, assets: List[WistiaVideoMediaAsset], name: str, duration: float, hashed_id: str):
        self.assets = assets
        self.name = name
        self.duration = duration
        self.hashed_id = hashed_id

    def original_quality(self):
        return first_or_none(asset.video_type == 'original' for asset in self.assets)

    def best_mp4_quality(self):
        return first_or_none(asset.video_type == 'hd_mp4_video' for asset in self.assets)

    def __repr__(self):
        return str(self.__dict__)


class WistiaVideo:
    def __init__(self, media: WistiaVideoMedia):
        self.media = media

    def __repr__(self):
        return str(self.__dict__)


class WistiaVideoHandler(VideoHandler):
    def can_handle(self, element: WebElement, driver: WebDriver) -> bool:
        poster: Optional[str] = element.get_attribute('poster')

        return poster and 'wistia.' in poster

    def handle(self, driver: WebDriver, config: Config) -> List[ScrapeJob]:
        scripts = [script.get_attribute('src') for script in driver.find_elements_by_tag_name('script')]
        script_file = first_or_none(scripts, lambda element: 'embed/medias/' in element)

        file = WistiaVideoHandler.download_file_from_js(driver.current_url, config.user_agent, script_file)
        job = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.VIDEO, file_path=file)

        return [job]

    @staticmethod
    def download_file_from_js(current_url: str, user_agent: str, script_file_url: str, get_original_quality: bool = True):
        headers = get_default_headers(current_url, user_agent)
        text = download_to_str(script_file_url, headers)
        text = text[text.index('='):]

        json_str = extract_json_from_text(text)
        json_obj = json.loads(json_str)

        script = WistiaVideoHandler.parse_json(json_obj)

        if get_original_quality:
            download_url = script.media.original_quality()
        else:
            download_url = script.media.best_mp4_quality()

        filename = get_filename_from_url(download_url)
        downloaded_file = download_file(download_url, filename, duplicate_handler=DuplicateHandler.FIND_VALID_FILE)

        return downloaded_file.filename

    @staticmethod
    def parse_json(json_obj) -> WistiaVideo:
        media_json = json_parse(json_obj, 'media', fatal=True)
        media_assets_json = json_parse(media_json, 'assets', fatal=True)

        media_assets: List[WistiaVideoMediaAsset] = json_parse_class_list(media_assets_json, WistiaVideoMediaAsset)

        name: str = json_parse(media_json, 'name', fatal=True)
        duration: float = json_parse(media_json, 'duration', fatal=True)
        hashed_id: str = json_parse(media_json, 'hashedId', fatal=True)

        media = WistiaVideoMedia(media_assets, name, duration, hashed_id)
        video = WistiaVideo(media)

        return video

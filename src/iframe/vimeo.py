import json
from typing import Optional, List

from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from src.iframe.iframe import IFrameHandler
from src.scrape import ScrapeJobType, ScrapeJob, ScrapeJobTask
from src.util.generic import first_or_none
from src.util.io import DuplicateHandler
from src.util.json_util import json_parse, json_parse_class_list, json_parse_class_list_with_items
from src.util.web.generic import extract_json_from_text, download_file, DownloadedFileResult, get_filename_from_url
from src.util.web.stream_download import download_stream


class VimeoIFrameRequestFilesProgressive:
    def __init__(self, width: int, height: int, mime: str, fps: int, url: str, quality: str):
        self.width = width
        self.height = height
        self.mime = mime
        self.fps = fps
        self.url = url
        self.quality = quality

    def get_quality_number(self):
        val = int(first_or_none(filter(str.isdigit, self.quality)))
        return val

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameRequestFilesDashCDNStream:
    def __init__(self, identifier: int, quality: str, fps: int):
        self.identifier = identifier
        self.quality = quality
        self.fps = fps

    def get_quality_number(self):
        val = int(first_or_none(filter(str.isdigit, self.quality)))
        return val

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameRequestFilesDashCDN:
    def __init__(self, name: str, url: str, avc_url: str):
        self.name = name
        self.url = url
        self.avc_url = avc_url

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameRequestFilesDash:
    def __init__(self, streams: List[VimeoIFrameRequestFilesDashCDNStream], cdns: List[VimeoIFrameRequestFilesDashCDN],
                 streams_avc: List[VimeoIFrameRequestFilesDashCDNStream]):
        self.streams = streams
        self.cdns = cdns
        self.streams_avc = streams_avc

    def best(self) -> VimeoIFrameRequestFilesDashCDNStream:
        return VimeoIFrameRequestFilesDash.best_impl(self.streams)

    def best_avc(self) -> VimeoIFrameRequestFilesDashCDNStream:
        return VimeoIFrameRequestFilesDash.best_impl(self.streams_avc)

    def first_cdn(self) -> Optional[VimeoIFrameRequestFilesDashCDN]:
        return first_or_none(self.cdns)

    @staticmethod
    def best_impl(lst: List[VimeoIFrameRequestFilesDashCDNStream]) -> VimeoIFrameRequestFilesDashCDNStream:
        in_order = sorted(lst, key=lambda x: x.get_quality_number(), reverse=True)
        return first_or_none(in_order)

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameRequestFiles:
    def __init__(self, dash: VimeoIFrameRequestFilesDash, progressive: List[VimeoIFrameRequestFilesProgressive]):
        self.dash = dash
        self.progressive = progressive

    def best_progressive(self) -> VimeoIFrameRequestFilesProgressive:
        in_order = sorted(self.progressive, key=lambda x: x.get_quality_number(), reverse=True)
        return first_or_none(in_order)

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameRequest:
    def __init__(self, files: VimeoIFrameRequestFiles):
        self.files = files

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameScript:
    def __init__(self, request: VimeoIFrameRequest, referer: str):
        self.request = request
        self.referer = referer

    def __repr__(self):
        return str(self.__dict__)


class VimeoIFrameHandler(IFrameHandler):
    def can_handle(self, element: WebElement) -> bool:
        src: Optional[str] = element.get_attribute('src')

        return src and 'player.vimeo' in src

    def handle(self, driver: WebDriver) -> List[ScrapeJob]:
        scripts = [script.get_attribute('innerHTML') for script in driver.find_elements_by_tag_name('script')]
        script = first_or_none(scripts, lambda element: 'player.vimeo.com' in element)

        file = VimeoIFrameHandler.download_file_from_js(script)

        job = ScrapeJob(ScrapeJobTask.REPLACE, ScrapeJobType.VIDEO, file_path=file)

        return [job]

    @staticmethod
    def download_file_from_js(txt: str, check_progressive_first: bool = True):
        json_str = extract_json_from_text(txt)
        json_obj = json.loads(json_str)

        script = VimeoIFrameHandler.parse_json(json_obj)

        if check_progressive_first and len(script.request.files.progressive) > 0:
            progressive = script.request.files.best_progressive()
            progressive_url = progressive.url

            filename = get_filename_from_url(progressive_url)
            downloaded_file = download_file(progressive_url, filename, duplicate_handler=DuplicateHandler.FIND_VALID_FILE)

            if downloaded_file.result == DownloadedFileResult.SUCCESS:
                return downloaded_file.filename

        cdn_url = script.request.files.dash.first_cdn().url
        file = download_stream(cdn_url, script.request.files.dash.best().identifier)

        return file

    @staticmethod
    def parse_json(json_obj) -> VimeoIFrameScript:
        request_json = json_parse(json_obj, 'request', fatal=True)
        request_files_json = json_parse(request_json, 'files', fatal=True)
        request_files_dash_json = json_parse(request_files_json, 'dash', fatal=True)
        request_files_dash_streams_json = json_parse(request_files_dash_json, 'streams', fatal=True)
        request_files_dash_cdns_json = json_parse(request_files_dash_json, 'cdns', fatal=True)
        request_files_dash_streams_avc_json = json_parse(request_files_dash_json, 'streams_avc', fatal=True)
        request_files_progressive_json = json_parse(request_files_json, 'progressive', fatal=True)

        dash_streams: List[VimeoIFrameRequestFilesDashCDNStream] = json_parse_class_list(request_files_dash_streams_json, VimeoIFrameRequestFilesDashCDNStream)
        dash_cdns: List[VimeoIFrameRequestFilesDashCDN] = json_parse_class_list_with_items(request_files_dash_cdns_json, VimeoIFrameRequestFilesDashCDN,
                                                                                           'name')
        dash_streams_avc: List[VimeoIFrameRequestFilesDashCDNStream] = json_parse_class_list(request_files_dash_streams_avc_json,
                                                                                             VimeoIFrameRequestFilesDashCDNStream)
        dash = VimeoIFrameRequestFilesDash(dash_streams, dash_cdns, dash_streams_avc)
        progressive: List[VimeoIFrameRequestFilesProgressive] = json_parse_class_list(request_files_progressive_json, VimeoIFrameRequestFilesProgressive)
        request_files = VimeoIFrameRequestFiles(dash, progressive)
        request = VimeoIFrameRequest(request_files)

        referer = json_parse(request_json, 'referrer', fatal=True)

        script = VimeoIFrameScript(request, referer)

        return script

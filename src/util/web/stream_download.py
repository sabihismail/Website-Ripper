import base64
import tempfile
from typing import List, Optional, Union

import ffmpeg

from src.util.generic import first_or_none, error, find_nth_reverse
from src.util.io import move_file_same_dir, DuplicateHandler
from src.util.json_util import json_parse_class
from src.util.web import mimetypes_extended
from src.util.web.generic import join_url, download_file_stream, download_to_json


class JSONStreamSegment:
    def __init__(self, start: float, end: float, url: str, size: int):
        self.start = start
        self.end = end
        self.url = url
        self.size = size

    def __repr__(self):
        return str(self.__dict__)


class JSONSpecificStream:
    def __init__(self, identifier: str, base_url: str, mime_type: str, init_segment: str, duration: float, segments: List[JSONStreamSegment]):
        self.identifier = identifier
        self.base_url = base_url
        self.mime_type = mime_type
        self.init_segment = init_segment
        self.duration = duration
        self.segments = segments

    def __repr__(self):
        return str(self.__dict__)


class JSONAudioStream(JSONSpecificStream):
    def __init__(self, identifier: str, base_url: str, mime_type: str, duration: float, channels: int, sample_rate: int, init_segment: str,
                 segments: List[JSONStreamSegment]):
        super().__init__(identifier, base_url, mime_type, init_segment, duration, segments)
        self.channels = channels
        self.sample_rate = sample_rate

    def __repr__(self):
        return str(self.__dict__)


class JSONVideoStream(JSONSpecificStream):
    def __init__(self, identifier: str, base_url: str, mime_type: str, duration: float, framerate: int, width: int, height: int, init_segment: str,
                 segments: List[JSONStreamSegment]):
        super().__init__(identifier, base_url, mime_type, init_segment, duration, segments)
        self.framerate = framerate
        self.width = width
        self.height = height

    def __repr__(self):
        return str(self.__dict__)


class JSONStream:
    def __init__(self, base_url: str, video: List[JSONVideoStream], audio: List[JSONAudioStream]):
        self.base_url = base_url
        self.video = video
        self.audio = audio

    def __repr__(self):
        return str(self.__dict__)


def download_stream(json_url: str, specific_identifier: Union[str, int]) -> str:
    url_suffix = json_url[find_nth_reverse(json_url, '/', 1) + 1:]
    base_url = json_url[:find_nth_reverse(json_url, '/', 2)]
    base_video_url = f'{base_url}/{specific_identifier}'
    json_url = f'{base_video_url}/{url_suffix}'

    content = download_to_json(json_url)
    json_obj: JSONStream = json_parse_class(content, JSONStream)

    file = download_and_join_streams(json_obj, base_video_url)

    return file


def download_specific_stream_to_file(json_obj: JSONSpecificStream, json_url: str) -> Optional[str]:
    if not json_obj:
        return None

    full_base_url = join_url(json_url, json_obj.base_url)

    ext = mimetypes_extended.guess_extension(json_obj.mime_type, include_period=True)
    file_stream = tempfile.NamedTemporaryFile(suffix=ext, delete=False)

    init_segment = base64.b64decode(json_obj.init_segment)
    file_stream.write(init_segment)

    for segment in json_obj.segments:
        segment_url = join_url(full_base_url, segment.url)

        if not download_file_stream(segment_url, file_stream, with_progress_bar=True, fatal=True):
            break

    file_stream.flush()
    file_stream.close()

    return file_stream.name


def download_and_join_streams(json_obj: JSONStream, base_url: str) -> str:
    video_json: JSONVideoStream = first_or_none(json_obj.video)
    audio_json: JSONAudioStream = first_or_none(json_obj.audio)

    if not video_json:
        error(f'{json_obj} does not have video')

    video_file = download_specific_stream_to_file(video_json, base_url)

    if not audio_json:
        return video_file

    audio_file = download_specific_stream_to_file(audio_json, base_url)

    input_video = ffmpeg.input(video_file)
    input_audio = ffmpeg.input(audio_file)

    out_file = tempfile.NamedTemporaryFile(suffix='.mkv', delete=False).name
    ffmpeg.output(input_video, input_audio, out_file, vcodec='copy', acodec='copy').run(overwrite_output=True)

    combined_file = move_file_same_dir(out_file, f'{video_json.identifier}.mkv', duplicate_handler=DuplicateHandler.FIND_VALID_FILE)

    return combined_file

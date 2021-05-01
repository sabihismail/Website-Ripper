import hashlib
import mimetypes
import os
import re
import shelve
import sys
import tempfile
import urllib.request
from enum import Enum
from http.client import HTTPMessage
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.parse import urlparse

from urllib3 import HTTPResponse

from src.progress_bar import ProgressBarImpl

# Retrieved from https://referencesource.microsoft.com/#mscorlib/system/io/path.cs,090eca8621a248ee
INVALID_PATH_CHARACTERS = ['\"', '<', '>', '|', '\0', '*', '?'] + \
                          [chr(i) for i in range(1, 32)]

INVALID_FILENAME_CHARACTERS = ['\"', '<', '>', '|', '\0', ':', '*', '?', '\\', '/'] + \
                              [chr(i) for i in range(1, 32)]


class DownloadedFileResult(Enum):
    SUCCESS = 'success',
    FAIL = 'fail',
    SKIPPED = 'skipped'


class DownloadedFile:
    def __init__(self, filename: str, url: str, headers: Optional[HTTPMessage]):
        self.filename = filename.replace('\\', '/')
        self.url = url
        self.headers = headers

    def __repr__(self):
        return str(self.__dict__)


class DuplicateHandler(Enum):
    FIND_VALID_FILE = 'FIND_VALID_FILE'
    OVERWRITE = 'OVERWRITE'
    THROW_ERROR = 'THROW_ERROR'
    SKIP = 'SKIP'
    HASH_COMPARE = 'HASH_COMPARE'


def error(s, fatal: bool = True) -> None:
    print(s, file=sys.stderr)

    if fatal:
        exit(-1)


def name_of(var) -> str:
    return f'{var=}'.split('=')[0]


def get_file_extension(s: str) -> str:
    split = s.split('.')

    if len(split) == 1:
        error(f'No file extension found: {str}')

    return split[-1]


def replace_invalid_filename_characters(filename: str):
    for char in INVALID_FILENAME_CHARACTERS:
        filename = filename.replace(char, '')

    return filename


def split_full_path(full_path: str) -> Tuple[str, str]:
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)

    return directory, filename


def get_valid_filename(directory: str, filename: str = None) -> str:
    if not filename:
        directory, filename = split_full_path(directory)

    filename = replace_invalid_filename_characters(filename)

    full_path = combine_path(directory, filename)
    ext = get_file_extension(filename)
    filename_only = filename[0:filename.index(f'.{ext}')]
    i = 1
    while os.path.exists(full_path):
        new_file = f'{filename_only} {i}.{ext}'
        full_path = combine_path(directory, new_file)

        i += 1

    return full_path.replace('\\', '/')


def find_nth(haystack, needle, n):
    start = haystack.find(needle)

    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1

    return start


def get_referer(s: str):
    return s[0:find_nth(s, '/', 3) + 1]


def is_blank(s) -> bool:
    return not s or s.isspace()


def get_origin(s: str) -> str:
    return s[0:find_nth(s, '/', 3)]


def combine_path(directory: str, *new_dirs: str) -> str:
    directory = directory.replace('\\', '/')

    if directory.endswith('/'):
        directory = directory[:-1]

    for new_dir in new_dirs:
        new_dir = new_dir.replace('\\', '/')

        if not new_dir.startswith('/'):
            directory += '/'

        directory += new_dir

    return directory.replace('\\', '/')


def validate_path(directory: str) -> str:
    if is_blank(directory):
        directory = combine_path(os.getcwd(), '/out')

    path = directory.replace('\\', '/')

    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)

    return path


def get_sha1_hash_file(path, chunk_size: int = 1024 * 8) -> str:
    sha1 = hashlib.sha1()

    with open(path, 'rb') as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break

            sha1.update(data)

    return sha1.hexdigest()


def move_file(old: str, new: str) -> str:
    return str(Path(old).rename(new)).replace('\\', '/')


def write_file(path: str, text: str, filename: str = ''):
    if filename:
        path = combine_path(path, 'index.html')

    Path(path).write_text(text)


def configure_urllib_opener(headers: List[Tuple[str, str]]):
    opener = urllib.request.build_opener()

    if headers:
        opener.addheaders = headers

    urllib.request.install_opener(opener)


def ignorable_content_type(ignored_content_types: List[str], content_type: str, attempt_download_on_fail: bool = True) -> bool:
    if is_blank(content_type):
        return attempt_download_on_fail

    split = content_type.split(';')

    check = content_type
    if len(split) > 1:
        check = split[0].strip()

    return check in ignored_content_types


def add_to_cache(download_cache, cache, filename, *urls, headers: HTTPMessage = None) -> Optional[DownloadedFile]:
    if len(urls) == 0:
        error(f'Cache fail, no url sent.')

    downloaded_file = DownloadedFile(filename, urls[0], headers)

    if not cache:
        return downloaded_file

    for url in urls:
        download_cache[url] = downloaded_file

    return downloaded_file


def download_file_impl(filename: str, url: str, cache: bool, download_cache: shelve.DbfilenameShelf, with_progress_bar: bool = True):
    file_stream = open(filename, 'w+b')

    old_url: str = ''
    download_stream: HTTPResponse = urllib.request.urlopen(url)
    with download_stream:
        res_headers: HTTPMessage = download_stream.info()
        new_url: str = download_stream.geturl()

        if cache and new_url in download_cache:
            return DownloadedFileResult.SUCCESS, download_cache[new_url]

        if url != new_url:
            old_url = url
            url = new_url

        block_size = 1024 * 8
        read = 0
        block_num = 0
        total_size = int(res_headers.get('Content-Length', failobj=0))

        if with_progress_bar:
            progress_bar = ProgressBarImpl(total_size)

        with file_stream:
            while True:
                block: bytes = download_stream.read(block_size)
                if not block:
                    break

                read += len(block)
                file_stream.write(block)

                if with_progress_bar:
                    block_num += 1

                    progress_bar.run(block_num, block_size)

        if total_size >= 0 and read < total_size:
            error(f'File download incomplete, received {read} out of {total_size} bytes. URL: {url}, filename: {filename}', fatal=False)

    return url, old_url, res_headers


def download_file(url: str, ideal_filename: str = None, out_dir: str = None, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True,
                  cache: bool = True, duplicate_handler: DuplicateHandler = DuplicateHandler.FIND_VALID_FILE, ignored_content_types: List[str] = None) \
        -> Tuple[DownloadedFileResult, Optional[DownloadedFile]]:
    download_cache = shelve.open('cache.db', writeback=True)

    if cache and url in download_cache:
        return DownloadedFileResult.SUCCESS, download_cache[url]

    configure_urllib_opener(headers)

    filename = tempfile.TemporaryFile(delete=False).name
    url, old_url, res_headers = download_file_impl(filename, url, cache, download_cache, with_progress_bar=with_progress_bar)

    content_type = res_headers.get('Content-Type', failobj=None)
    if ignorable_content_type(ignored_content_types, content_type):
        return DownloadedFileResult.SKIPPED, None

    actual_name = None
    content_disposition = res_headers.get('Content-Disposition', failobj=None)
    if content_disposition:
        actual_name = re.findall('filename=(.+)', content_disposition)[0]

    potential_filename = os.path.basename(urlparse(url).path)
    if not actual_name and potential_filename and content_type:
        potential_mimetype = mimetypes.guess_type(potential_filename)

        if potential_mimetype and potential_mimetype[0]:
            ext = mimetypes.guess_extension(potential_mimetype[0])

            if potential_filename.endswith(ext):
                actual_name = potential_filename

    if not actual_name and not content_disposition and not potential_filename and content_type:
        ext = mimetypes.guess_extension(content_type)

        actual_name = f'{filename}.{ext}'

    if actual_name:
        if not out_dir:
            out_dir = str(Path(filename).parent)

        if filename:
            filename_split = os.path.splitext(actual_name)

            if ideal_filename and filename_split[1]:
                ideal_filename = os.path.splitext(ideal_filename)[0]

                actual_name = ideal_filename + filename_split[1]

        out_path = Path(combine_path(out_dir, actual_name))

        if os.path.exists(out_path):
            if duplicate_handler == DuplicateHandler.FIND_VALID_FILE:
                out_path = get_valid_filename(str(out_path))
            elif duplicate_handler == DuplicateHandler.THROW_ERROR:
                error(f'File "{out_path}" already exists')
            elif duplicate_handler == DuplicateHandler.OVERWRITE:
                os.remove(out_path)
            elif duplicate_handler == DuplicateHandler.SKIP:
                return DownloadedFileResult.SKIPPED, None
            elif duplicate_handler == DuplicateHandler.HASH_COMPARE:
                old_file = get_sha1_hash_file(out_path)
                new_file = get_sha1_hash_file(filename)
                
                if old_file == new_file:
                    downloaded_file = add_to_cache(download_cache, cache, str(out_path), url, old_url)

                    return DownloadedFileResult.SUCCESS, downloaded_file

                out_path = get_valid_filename(str(out_path))
    else:
        out_file = os.path.basename(urlparse(url).path)

        if not out_file:
            out_file = os.path.basename(filename)

        out_path = combine_path(out_dir, out_file)

    filename = move_file(filename, out_path)
    downloaded_file = add_to_cache(download_cache, cache, filename, url, old_url, headers=res_headers)

    download_cache.close()  # synchronizes automatically

    return DownloadedFileResult.SUCCESS, downloaded_file

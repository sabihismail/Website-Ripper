import mimetypes
import os
import re
import shelve
import tempfile
import urllib.request
from enum import Enum
from http.client import HTTPMessage
from pathlib import Path
from typing import List, Tuple, Optional, Union
from urllib.parse import urlparse, urlunparse

import validators
from tldextract import tldextract

from src.util.progress_bar import ProgressBarImpl
from src.util.generic import find_nth, is_blank, error, first_or_none
from src.util.io import DEFAULT_MAX_FILENAME_LENGTH, combine_path, get_valid_filename, get_sha1_hash_file, shorten_file_name, move_file, \
    split_path_components, join_filename_with_ext, get_file_extension, DuplicateHandler

URL_REGEX = re.compile(r'[=:] *(?:\'([^\']*)\'|"([^"]*)")| *\(([^()]*)\)')
RELATIVE_URL_REGEX = re.compile(r'^(?!www\.|(?:http|ftp)s?://|[A-Za-z]:\\|//).*')


class GroupByPair:
    def __init__(self, extensions: List[str], folder: str):
        self.extensions = extensions
        self.folder = folder

    def __repr__(self):
        return str(self.__dict__)


class GroupByMapping:
    def __init__(self, *pairs: GroupByPair, fail_dir: str = 'other'):
        self.pairs = list(pairs)
        self.fail_dir = fail_dir

    def __contains__(self, item: str) -> bool:
        return any(item in pair.extensions for pair in self.pairs)

    def __getitem__(self, item: str) -> str:
        val: GroupByPair = first_or_none([pair for pair in self.pairs if item in pair.extensions])
        return val.folder

    def __repr__(self):
        return str(self.__dict__)


class DownloadedFileResult(Enum):
    SUCCESS = 'success',
    FAIL = 'fail',
    SKIPPED = 'skipped'


class DownloadedFile:
    def __init__(self, filename: str = '', url: str = '', headers: Optional[HTTPMessage] = None, result: DownloadedFileResult = DownloadedFileResult.FAIL):
        self.filename = filename.replace('\\', '/')
        self.url = url
        self.headers = headers
        self.result = result

    def __repr__(self):
        return str(self.__dict__)


def get_pure_domain(base_url):
    extract = tldextract.extract(base_url)
    pure_domain = extract.domain + '.' + extract.suffix

    return pure_domain


def url_is_in_domain(base_url, url):
    pure_domain = get_pure_domain(base_url)

    return pure_domain in url or RELATIVE_URL_REGEX.search(url)


def get_referer(s: str):
    return s[0:find_nth(s, '/', 3) + 1]


def get_origin(s: str) -> str:
    return s[0:find_nth(s, '/', 3)]


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

    downloaded_file = DownloadedFile(filename=filename, url=urls[0], headers=headers, result=DownloadedFileResult.SUCCESS)

    if not cache:
        return downloaded_file

    for url in urls:
        download_cache[url] = downloaded_file

    return downloaded_file


def download_file_impl(filename: str, url: str, cache: bool, download_cache: shelve.DbfilenameShelf, with_progress_bar: bool = True) \
        -> Union[Tuple[str, str, HTTPMessage], DownloadedFile, None]:
    try:
        download_stream = urllib.request.urlopen(url)
    except:
        return None

    old_url: str = ''
    with download_stream:
        res_headers: HTTPMessage = download_stream.info()
        new_url: str = download_stream.geturl()

        if cache and new_url in download_cache:
            return download_cache[new_url]

        if url != new_url:
            old_url = url
            url = new_url

        block_size = 1024 * 8
        read = 0
        block_num = 0
        total_size = int(res_headers.get('Content-Length', failobj=0))

        if with_progress_bar:
            progress_bar = ProgressBarImpl(total_size)

        with open(filename, 'w+b') as file_stream:
            while True:
                block: bytes = download_stream.read(block_size)
                if not block:
                    break

                read += len(block)
                file_stream.write(block)

                if with_progress_bar:
                    block_num += 1

                    progress_bar.run(len(block))

        if total_size >= 0 and read < total_size:
            error(f'File download incomplete, received {read} out of {total_size} bytes. URL: {url}, filename: {filename}', fatal=False)

    return url, old_url, res_headers


def fix_relative_url(url: str, base_url: str):
    if not RELATIVE_URL_REGEX.search(url):
        return url

    base_parsed = urlparse(base_url)
    parsed = urlparse(url)

    if parsed.netloc and not parsed.scheme:
        parsed.scheme = 'https'

    if not parsed.netloc and not parsed.scheme:
        parsed.scheme = 'https'
        parsed.netloc = base_parsed.netloc

    return urlunparse(parsed)


def check_content_type(url: str, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True, cache: bool = True) -> Optional[str]:
    download_cache = shelve.open('cache.db', writeback=True)

    configure_urllib_opener(headers)

    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(filename, url, cache, download_cache, with_progress_bar=with_progress_bar)

    if not file_download:
        return None

    if type(file_download) == DownloadedFile:
        res_headers = file_download.headers
    else:
        _, _, res_headers = file_download

    content_type = res_headers.get('Content-Type', failobj=None)

    return content_type


def find_urls_in_html(html: str):
    lst = []
    for match in URL_REGEX.findall(html):
        url: Optional[str] = first_or_none(match)

        if not url:
            continue

        valid = False
        if validators.url(url):
            valid = True

        if url.startswith('//'):
            url = 'https:' + url
            valid = True

        if valid and url not in lst:
            lst.append(url)

    return lst


def download_file(url: str, ideal_filename: str = None, out_dir: str = None, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True,
                  cache: bool = True, duplicate_handler: DuplicateHandler = DuplicateHandler.FIND_VALID_FILE, ignored_content_types: List[str] = None,
                  max_file_length=DEFAULT_MAX_FILENAME_LENGTH, group_by: GroupByMapping = None) \
        -> DownloadedFile:
    download_cache = shelve.open('cache.db', writeback=True)

    if cache and url in download_cache:
        return download_cache[url]

    configure_urllib_opener(headers)

    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(filename, url, cache, download_cache, with_progress_bar=with_progress_bar)

    if not file_download:
        return DownloadedFile(result=DownloadedFileResult.FAIL)

    if type(file_download) == DownloadedFile:
        return file_download

    url, old_url, res_headers = file_download

    if not url:
        return DownloadedFile(result=DownloadedFileResult.FAIL)

    content_type = res_headers.get('Content-Type', failobj=None)
    if ignorable_content_type(ignored_content_types, content_type):
        return DownloadedFile(result=DownloadedFileResult.SKIPPED)

    actual_name = None
    content_disposition = res_headers.get('Content-Disposition', failobj=None)
    if content_disposition:
        result = re.findall('filename=(.+)', content_disposition)
        result = first_or_none(result)

        if get_file_extension(result):
            actual_name = result

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

    else:
        actual_name = os.path.basename(urlparse(url).path)

        if not actual_name:
            actual_name = os.path.basename(filename)

    out_path = combine_path(out_dir, actual_name)

    if out_dir and group_by:
        directory, filename_only, ext = split_path_components(out_path, fatal=False, include_ext_period=True)

        sub_dir = f'/{group_by.fail_dir}'
        if ext in group_by:
            sub_dir = f'/{group_by[ext]}'

        filename_with_ext = join_filename_with_ext(filename_only, ext)
        out_path = combine_path(directory, sub_dir, filename_with_ext)

    out_path = shorten_file_name(out_path, max_length=max_file_length)
    filename = move_file(filename, out_path, make_dirs=True, duplicate_handler=duplicate_handler)
    downloaded_file = add_to_cache(download_cache, cache, filename, url, old_url, headers=res_headers)

    download_cache.close()  # synchronizes automatically

    return downloaded_file

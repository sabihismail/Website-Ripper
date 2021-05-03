import os
import re
import shelve
import tempfile
import urllib.request
from enum import Enum
from http.client import HTTPMessage
from pathlib import Path
from typing import List, Tuple, Optional, Union
from urllib.parse import urlparse, ParseResult

import validators
from filetype import filetype
from tldextract import tldextract

from src.util.progress_bar import ProgressBarImpl
from src.util.generic import find_nth, is_blank, error, first_or_none, name_of
from src.util.io import DEFAULT_MAX_FILENAME_LENGTH, combine_path, shorten_file_name, move_file, split_path_components, join_filename_with_ext, \
    get_file_extension, DuplicateHandler, get_filename, split_filename
from src.util.mimetypes_extended import mimetypes_extended

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
        self.filename = filename.replace('\\', '/') if filename else ''
        self.url = url
        self.headers = headers
        self.result = result

    def __repr__(self):
        return str(self.__dict__)


def get_pure_domain(base_url: str) -> str:
    extract = tldextract.extract(base_url)
    pure_domain = extract.domain + '.' + extract.suffix

    return pure_domain


def get_relative_path(file: str, directory: str):
    file = file.replace('\\', '/')
    directory = directory.replace('\\', '/')
    if directory.endswith('/'):
        directory = directory[:-1]

    split_directory = directory.split('/')
    split_file = file.split('/')
    similar = 0
    for i in range(min(len(split_directory), len(split_file))):
        if split_directory[i] != split_file[i]:
            break

        similar += 1

    diff_directory = len(split_directory) - similar
    diff_file = '/'.join(split_file[similar:])

    ret = '/' + ('../' * diff_directory) + diff_file

    return ret


def get_sub_directory_path(base_url: str, new_url: str, prepend_dir: str = None, prepend_slash: bool = True, append_slash: bool = True) -> str:
    if not base_url:
        error(f'Invalid params: {base_url}, {new_url}, {prepend_dir}.', name_of(get_sub_directory_path))

    if new_url.endswith('/'):
        new_url = new_url[:-1]

    base_url = get_base_url(base_url)

    if base_url not in new_url:
        error(f'Invalid params: {base_url}, {new_url}, {prepend_dir}.', name_of(get_sub_directory_path))

    sub_dir = new_url[new_url.index(base_url) + len(base_url):]

    if not sub_dir.startswith('/'):
        sub_dir = f'/{sub_dir}'

    if append_slash:
        if not sub_dir.endswith('/'):
            sub_dir += '/'
    else:
        if sub_dir.endswith('/'):
            sub_dir = sub_dir[:-1]

    if prepend_dir:
        if prepend_dir.endswith('/'):
            prepend_dir = prepend_dir[:-1]

        return prepend_dir + sub_dir

    if prepend_slash:
        if not sub_dir.startswith('/'):
            sub_dir = f'/{sub_dir}'
    else:
        if sub_dir.startswith('/'):
            sub_dir = sub_dir[1:]

    return sub_dir


def url_in_list_parsed(parsed_url: ParseResult, lst: List[ParseResult]) -> bool:
    parsed_url_path = '' if parsed_url.path == '/' else parsed_url.path

    for elem in lst:
        elem_path = '' if elem.path == '/' else elem.path

        same = parsed_url_path == elem_path and \
               parsed_url.netloc == elem.netloc and \
               parsed_url.params == elem.params and \
               parsed_url.query == elem.query

        if same:
            return True

    return False


def url_in_list(url: str, lst: List[ParseResult], fragments: bool = True) -> bool:
    parsed_url = urlparse(url, allow_fragments=fragments)
    return url_in_list_parsed(parsed_url, lst)


def is_url_exact(u1: str, u2: str) -> True:
    return url_in_list(u1, [urlparse(u2)])


def join_url(url: str, path: str):
    return urllib.parse.urljoin(url, path)


def url_is_relative(url) -> bool:
    return bool(RELATIVE_URL_REGEX.search(url))


def url_in_domain(base_url, url):
    pure_domain = get_pure_domain(base_url)

    return pure_domain in url or RELATIVE_URL_REGEX.search(url)


def get_base_url(domain: str) -> str:
    parsed = urlparse(domain)

    if not parsed.scheme and not parsed.netloc:
        base_url = parsed.path[1:] if domain.startswith('.') else parsed.path
    else:
        base_url = parsed.netloc

    return base_url


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


def add_to_cache(download_cache, *urls, headers: HTTPMessage = None, filename: str = None, result=DownloadedFileResult.SUCCESS) -> Optional[DownloadedFile]:
    if len(urls) == 0:
        error(f'Cache fail, no url sent.')

    downloaded_file = DownloadedFile(filename=filename, url=urls[0], headers=headers, result=result)

    for url in urls:
        download_cache[url] = downloaded_file

    return downloaded_file


def get_filename_from_url(url: str) -> str:
    return os.path.basename(urlparse(url).path)


def get_content_type_from_headers(res_headers):
    if not res_headers:
        return None

    content_type: str = res_headers.get('Content-Type', failobj=None)

    if not content_type:
        return None

    if ';' in content_type:
        content_type = content_type[0:content_type.index(';')].strip()

    return content_type


def get_content_type_head(url: str):
    try:
        req = urllib.request.Request(url, method='HEAD')
        response = urllib.request.urlopen(req)
    except:
        return None

    res_headers: HTTPMessage = response.info()

    content_type = get_content_type_from_headers(res_headers)

    return content_type


def get_content_type_get(url: str, with_progress_bar: bool = True):
    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(filename, url, download_cache=None, with_progress_bar=with_progress_bar)

    if not file_download:
        return None

    if type(file_download) == DownloadedFile:
        res_headers = file_download.headers
    else:
        _, _, res_headers = file_download

    content_type = get_content_type_from_headers(res_headers)

    return content_type


def get_content_type_cache(url: str):
    download_cache = shelve.open('cache.db', writeback=True)
    cached = download_cache.get(url, default=None)

    if not cached:
        return None

    res_headers = cached.headers
    content_type = get_content_type_from_headers(res_headers)

    return content_type


def get_content_type(url: str, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True, cache: bool = True) -> Optional[str]:
    configure_urllib_opener(headers)

    if cache:
        check_cached = get_content_type_cache(url)

        if check_cached:
            return check_cached

    check_head = get_content_type_head(url)

    if check_head:
        return check_head

    return get_content_type_get(url, with_progress_bar=with_progress_bar)


def find_urls_in_html(html: str) -> List[Tuple[Optional[str], Optional[str]]]:
    lst = []
    for match in URL_REGEX.findall(html):
        url: Optional[str] = first_or_none(match)

        if not url:
            continue

        original_url = None
        valid = False
        if validators.url(url):
            valid = True

        if url.startswith('//'):
            original_url = url
            url = 'https:' + url
            valid = True

        if valid and url not in lst:
            lst.append((url, original_url))

    return lst


def download_file(url: str, ideal_filename: str = None, out_dir: str = None, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True,
                  cache: bool = True, duplicate_handler: DuplicateHandler = DuplicateHandler.FIND_VALID_FILE, ignored_content_types: List[str] = None,
                  max_file_length=DEFAULT_MAX_FILENAME_LENGTH, group_by: GroupByMapping = None) -> DownloadedFile:
    download_cache = shelve.open('cache.db', writeback=True)

    if cache and url in download_cache:
        return download_cache[url]

    configure_urllib_opener(headers)

    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(filename, url, download_cache, with_progress_bar=with_progress_bar)

    if not file_download:
        downloaded_file = add_to_cache(download_cache, url, result=DownloadedFileResult.FAIL)
        return downloaded_file

    if type(file_download) == DownloadedFile:
        return file_download

    if not file_download[0]:
        downloaded_file = add_to_cache(download_cache, url, result=DownloadedFileResult.FAIL)
        return downloaded_file

    url, old_url, res_headers = file_download

    content_type = get_content_type_from_headers(res_headers)
    if ignorable_content_type(ignored_content_types, content_type):
        downloaded_file = add_to_cache(download_cache, url, result=DownloadedFileResult.SKIPPED)
        return downloaded_file

    actual_name = None
    content_disposition = res_headers.get('Content-Disposition', failobj=None)
    if content_disposition:
        result = re.findall('filename=(.+)', content_disposition)
        result = first_or_none(result)

        if get_file_extension(result):
            actual_name = result

    potential_filename = os.path.basename(urlparse(url).path)
    if not actual_name and potential_filename:
        if content_type:
            potential_mimetype = content_type
        else:
            potential_mimetype = mimetypes_extended.guess_type(potential_filename)[0]

        if potential_mimetype:
            ext = mimetypes_extended.guess_extension(potential_mimetype)

            if ext and potential_filename.endswith(ext):
                actual_name = potential_filename

    if not actual_name or not get_file_extension(actual_name):
        ext = None
        if content_type:
            ext = mimetypes_extended.guess_extension(content_type)

        if ext:
            if actual_name:
                actual_name += ext
            else:
                actual_name = get_filename(filename) + ext
        else:
            kind = filetype.guess(filename)

            if kind:
                actual_name = f'{get_filename(filename)}.{kind.extension}'

    if actual_name:
        if not out_dir:
            out_dir = str(Path(filename).parent)

        filename_split = split_filename(actual_name, include_ext_period=True)

        if ideal_filename and filename_split[1]:
            ideal_filename = os.path.splitext(ideal_filename)[0]

            actual_name = ideal_filename + filename_split[1]
    else:
        actual_name = get_filename_from_url(url)

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
    downloaded_file = add_to_cache(download_cache, url, old_url, headers=res_headers, filename=filename)

    download_cache.close()  # synchronizes automatically

    return downloaded_file


def download_file_impl(filename: str, url: str, download_cache: Optional[shelve.DbfilenameShelf], with_progress_bar: bool = True) \
        -> Union[Tuple[str, str, HTTPMessage], DownloadedFile, None]:
    try:
        download_stream = urllib.request.urlopen(url)
    except:
        return None

    old_url: str = ''
    with download_stream:
        res_headers: HTTPMessage = download_stream.info()
        new_url: str = download_stream.geturl()

        if download_cache and new_url in download_cache:
            return download_cache[new_url]

        if url != new_url:
            old_url = url
            url = new_url

        block_size = 1024 * 8
        read = 0
        block_num = 0
        total_size = int(res_headers.get('Content-Length', failobj=0))

        if with_progress_bar:
            progress_bar = ProgressBarImpl(total_size, on_complete=lambda x: print(f'Downloaded {url} to {filename}'))

        with open(filename, 'w+b') as file_stream:
            while True:
                block: bytes = download_stream.read(block_size)
                if not block:
                    break

                read += len(block)
                file_stream.write(block)

                if with_progress_bar:
                    block_num += 1

                    if not progress_bar.run(len(block)):
                        break

        if total_size >= 0 and read < total_size:
            error(f'File download incomplete, received {read} out of {total_size} bytes. URL: {url}, filename: {filename}', fatal=False)

    return url, old_url, res_headers

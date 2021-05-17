import json
import os
import re
import shelve
import tempfile
import urllib.request
from enum import Enum
from http.client import HTTPMessage
from pathlib import Path
from queue import LifoQueue
from typing import List, Tuple, Optional, Union, Any
from typing.io import IO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, ParseResult

import validators
from filetype import filetype
from tldextract import tldextract

from src.util.generic import find_nth, is_blank, first_or_none, name_of, find_nth_reverse, LogType, log
from src.util.io import DEFAULT_MAX_FILENAME_LENGTH, join_path, shorten_file_name, move_file, split_path_components, join_filename_with_ext, \
    get_file_extension, DuplicateHandler, get_filename, split_filename, ensure_directory_exists
from src.util.web import mimetypes_extended
from src.util.web.progress_bar import DownloadProgressBar

URL_REGEX = re.compile(r'[=:] *(?:\'([^\']*)\'|"([^"]*)")| *\(([^()]*)\)')
RELATIVE_URL_REGEX = re.compile(r'^(?!www\.|(?:http|ftp)s?://|[A-Za-z]:\\|//).*')

CACHE_WEBSITE_LINKS_FILE = 'cache/website_links.db'

DEFAULT_HEADERS = [
    ('Accept', '*/*'),
    ('Accept-Encoding', 'identity'),
    ('User-Agent', 'website-ripper/1.0')
]


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


def find_first_previous_char(s: str, index: int, exclude: List[str] = None):
    if not exclude:
        exclude = []

    index -= 1
    while index >= 0:
        if s[index] not in exclude:
            return index

        index -= 1


def min_val(a: int, b: int, a_val: Any = None, b_val: Any = None, min_possible_val: int = 0) -> Union[Tuple[int, int], Tuple[int, int, Any, any]]:
    if a < min_possible_val:
        if a_val or b_val:
            return b, a, b_val, a_val

        return b, a

    if b < min_possible_val:
        if a_val or b_val:
            return a, b, a_val, b_val

        return a, b

    if a < b:
        if a_val or b_val:
            return a, b, a_val, b_val

        return a, b
    else:
        if a_val or b_val:
            return b, a, b_val, a_val

        return b, a


def extract_json_from_text(s: str):
    start = 0
    if not s.startswith('[') and not s.startswith('{'):
        bracket_i = brace_i = 1

        open_bracket = open_brace = 0
        while (open_bracket != -1 and open_brace != -1) and start == 0:
            open_bracket = find_nth(s, '[', bracket_i)
            open_brace = find_nth(s, '{', brace_i)

            lower, higher, lower_val, higher_val = min_val(open_brace, open_bracket, '{', '[', min_possible_val=0)

            prev_lower_char = find_first_previous_char(s, lower, exclude=[' '])
            if s[prev_lower_char] != '=' and s[prev_lower_char] != '(':
                if lower_val == '{':
                    brace_i += 1
                elif lower_val == '[':
                    bracket_i += 1
            else:
                start = lower

        if start == 0:
            return None

    end = 0
    stack = LifoQueue()
    for i in range(start, len(s)):
        if s[i] == '{':
            stack.put('{')

        if s[i] == '}':
            stack.get()

        if stack.empty():
            end = i
            break

    if end == 0:
        log('Error parsing JSON', log_type=LogType.ERROR)

    json = s[start:end + 1]

    return json


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

    ret = './' + ('../' * diff_directory) + diff_file

    return ret


def get_sub_directory_path(base_url: str, new_url: str, prepend_dir: str = None, prepend_slash: bool = True, append_slash: bool = True) -> str:
    if not base_url:
        log(f'Invalid params: {base_url}, {new_url}, {prepend_dir}.', name_of(get_sub_directory_path), log_type=LogType.ERROR)

    if new_url.endswith('/'):
        new_url = new_url[:-1]

    base_url = get_base_url(base_url)

    if base_url not in new_url:
        log(f'Invalid params: {base_url}, {new_url}, {prepend_dir}.', name_of(get_sub_directory_path), log_type=LogType.ERROR)

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


def join_url(url: str, *paths: str):
    for path in paths:
        if not url.endswith('/') and not path.startswith('/') and not path.startswith('.'):
            path = '/' + path

        while path.startswith('.'):
            if path.startswith('./'):
                path = path[2:]
            elif path.startswith('../'):
                path = path[3:]

                if url.endswith('/'):
                    url = url[:find_nth_reverse(url, '/', 2) + 1]
                else:
                    url = url[:find_nth_reverse(url, '/', 1) + 1]

        url += path

    return url


def url_is_relative(url) -> bool:
    if is_blank(url):
        return False

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
    return s[:find_nth(s, '/', 3) + 1]


def get_origin(s: str) -> str:
    return s[:find_nth(s, '/', 3)]


def configure_urllib_opener(headers: List[Tuple[str, str]], use_default_headers: bool = True):
    http_handler = urllib.request.HTTPHandler()
    http_handler.set_http_debuglevel(1)

    https_handler = urllib.request.HTTPSHandler()
    https_handler.set_http_debuglevel(1)

    opener = urllib.request.build_opener()  # http_handler, https_handler)

    if use_default_headers:
        for default_header in DEFAULT_HEADERS:
            opener.addheaders.append(default_header)

    if headers:
        opener.addheaders = headers

    urllib.request.install_opener(opener)


def ignorable_content_type(ignored_content_types: List[str], content_type: str, attempt_download_on_fail: bool = True) -> bool:
    if not ignored_content_types or len(ignored_content_types) == 0:
        return False

    if is_blank(content_type):
        return attempt_download_on_fail

    split = content_type.split(';')

    check = content_type
    if len(split) > 1:
        check = split[0].strip()

    return check in ignored_content_types


def download_to_json(url: str) -> dict:
    response = urllib.request.urlopen(url)
    charset = response.info().get_param('charset') or 'utf-8'
    data = response.read().decode(charset)
    json_obj = json.loads(data)

    return json_obj


def add_to_download_cache(download_cache, *urls, headers: HTTPMessage = None, filename: str = None, result=DownloadedFileResult.SUCCESS) \
        -> Optional[DownloadedFile]:
    if len(urls) == 0:
        log(f'Cache fail, no url sent.', log_type=LogType.ERROR)

    downloaded_file = DownloadedFile(filename=filename, url=urls[0], headers=headers, result=result)

    for url in urls:
        download_cache[url] = downloaded_file

    return downloaded_file


def get_filename_ext_from_url(url: str, fatal: bool = False, include_ext_period: bool = True) -> str:
    filename = os.path.basename(urlparse(url).path)
    _, ext = split_filename(filename, fatal=fatal, include_ext_period=include_ext_period)

    return ext


def get_filename_from_url(url: str) -> str:
    return os.path.basename(urlparse(url).path)


def get_content_type_from_header(content_type: str):
    if not content_type:
        return None

    if ';' in content_type:
        content_type = content_type[:content_type.index(';')].strip()

    return content_type


def get_content_type_from_headers(res_headers: HTTPMessage):
    if not res_headers:
        return None

    content_type: str = res_headers.get('Content-Type', failobj=None)

    return get_content_type_from_header(content_type)


def get_content_type_head(url: str):
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req) as response:
            res_headers: HTTPMessage = response.info()

            content_type = get_content_type_from_headers(res_headers)
    except HTTPError as e:
        if e and e.headers:
            content_type_tmp = e.headers.get('Content-Type', None)
            content_type = get_content_type_from_header(content_type_tmp)
        else:
            log(e, extra=f'URL: {url}', fatal=False, log_type=LogType.ERROR)
            content_type = None
    except Exception as e:
        log(e, extra=f'General Exception URL: {url}', fatal=False, log_type=LogType.ERROR)
        content_type = None

    return content_type


def get_content_type_get(url: str, with_progress_bar: bool = True):
    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(url, filename, download_cache=None, with_progress_bar=with_progress_bar)

    if not file_download:
        return None

    if type(file_download) == DownloadedFile:
        res_headers = file_download.headers
    else:
        _, _, res_headers = file_download

    content_type = get_content_type_from_headers(res_headers)

    return content_type


def get_content_type_cache(url: str):
    ensure_directory_exists('/cache')

    download_cache = shelve.open(CACHE_WEBSITE_LINKS_FILE, writeback=True)
    cached = download_cache.get(url, default=None)

    if not cached:
        return None

    res_headers = cached.headers
    content_type = get_content_type_from_headers(res_headers)

    return content_type


def get_content_type(url: str, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True, cache: bool = True) -> Optional[str]:
    if cache:
        check_cached = get_content_type_cache(url)

        if check_cached:
            return check_cached

    configure_urllib_opener(headers)

    check_head = get_content_type_head(url)

    if check_head:
        return check_head

    return get_content_type_get(url, with_progress_bar=with_progress_bar)


def find_urls_in_html_or_js(html: str) -> List[Tuple[Optional[str], Optional[str]]]:
    lst = []
    matches = URL_REGEX.findall(html)
    for match in matches:
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


def read_url_utf8(url: str) -> str:
    data: bytes = urllib.request.urlopen(url).read()
    s = data.decode('utf-8')

    return s


def download_file(url: str, ideal_filename: str = None, out_dir: str = None, headers: List[Tuple[str, str]] = None, with_progress_bar: bool = True,
                  cache: bool = True, duplicate_handler: DuplicateHandler = DuplicateHandler.FIND_VALID_FILE, ignored_content_types: List[str] = None,
                  max_filename_length=DEFAULT_MAX_FILENAME_LENGTH, group_by: GroupByMapping = None) -> DownloadedFile:
    ensure_directory_exists('/cache')

    download_cache = shelve.open(CACHE_WEBSITE_LINKS_FILE, writeback=True)

    if cache and url in download_cache:
        return download_cache[url]

    configure_urllib_opener(headers)

    filename = tempfile.TemporaryFile(delete=False).name
    file_download = download_file_impl(url, filename, download_cache, with_progress_bar=with_progress_bar)

    if not file_download:
        downloaded_file = add_to_download_cache(download_cache, url, result=DownloadedFileResult.FAIL)
        return downloaded_file

    if type(file_download) == DownloadedFile:
        return file_download

    if not file_download[0]:
        downloaded_file = add_to_download_cache(download_cache, url, result=DownloadedFileResult.FAIL)
        return downloaded_file

    url, old_url, res_headers = file_download

    content_type = get_content_type_from_headers(res_headers)
    if ignorable_content_type(ignored_content_types, content_type):
        downloaded_file = add_to_download_cache(download_cache, url, result=DownloadedFileResult.SKIPPED)
        return downloaded_file

    actual_name = None
    content_disposition = res_headers.get('Content-Disposition', failobj=None)
    if content_disposition:
        result = re.findall('filename="(.+)"', content_disposition)
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
            ext = mimetypes_extended.guess_extension(potential_mimetype, include_period=True)

            if ext and potential_filename.endswith(ext):
                actual_name = potential_filename

    if not actual_name or not get_file_extension(actual_name):
        ext = None
        if content_type:
            ext = mimetypes_extended.guess_extension(content_type, include_period=True)

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

    out_path = join_path(out_dir, filename=actual_name)

    if out_dir and group_by:
        directory, filename_only, ext = split_path_components(out_path, fatal=False, include_ext_period=True)

        sub_dir = f'/{group_by.fail_dir}'
        if ext in group_by:
            sub_dir = f'/{group_by[ext]}'

        filename_with_ext = join_filename_with_ext(filename_only, ext)
        out_path = join_path(directory, sub_dir, filename=filename_with_ext)

    out_path = shorten_file_name(out_path, max_length=max_filename_length)
    filename = move_file(filename, out_path, make_dirs=True, duplicate_handler=duplicate_handler)
    downloaded_file = add_to_download_cache(download_cache, url, old_url, headers=res_headers, filename=filename)

    download_cache.close()  # synchronizes automatically

    return downloaded_file


def download_file_stream(url: str, file_stream: IO, block_size: int = 1024 * 8, with_progress_bar: bool = True, fatal: bool = True) -> bool:
    try:
        download_stream = urllib.request.urlopen(url)
    except Exception as e:
        log(f'Failed on: {url}', fatal=False, log_type=LogType.ERROR)
        log(e, fatal=fatal, log_type=LogType.ERROR)
        return False

    with download_stream:
        res_headers: HTTPMessage = download_stream.info()
        total_size = int(res_headers.get('Content-Length', failobj=0))

        progress_bar = None
        if with_progress_bar and total_size > 0:
            progress_bar = DownloadProgressBar(total_size)

        read = 0
        while True:
            block: bytes = download_stream.read(block_size)
            if not block:
                break

            read += len(block)
            file_stream.write(block)

            if progress_bar and not progress_bar.run(len(block)):
                break

        if total_size >= 0 and read < total_size:
            return False

    return True


def download_file_impl(url: str, filename: str, download_cache: Optional[shelve.DbfilenameShelf], block_size: int = 1024 * 8, with_progress_bar: bool = True) \
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

        total_size = int(res_headers.get('Content-Length', failobj=0))

        progress_bar = None
        if with_progress_bar and total_size > 0:
            progress_bar = DownloadProgressBar(total_size, on_complete=lambda x: log(f'Downloaded {url} to {filename}'))

        read = 0
        with open(filename, 'w+b') as file_stream:
            while True:
                block: bytes = download_stream.read(block_size)
                if not block:
                    break

                read += len(block)
                file_stream.write(block)

                if progress_bar and not progress_bar.run(len(block)):
                    break

        if total_size >= 0 and read < total_size:
            log(f'File download incomplete, received {read} out of {total_size} bytes. URL: {url}, filename: {filename}', fatal=False, log_type=LogType.ERROR)

    return url, old_url, res_headers

import os
import urllib.request
from http.client import HTTPMessage
from typing import List, Tuple

from src.progress_bar import ProgressBarImpl

# Retrieved from https://referencesource.microsoft.com/#mscorlib/system/io/path.cs,090eca8621a248ee
INVALID_PATH_CHARACTERS = ['\"', '<', '>', '|', '\0', '*', '?'] + \
                          [chr(i) for i in range(1, 32)]

INVALID_FILENAME_CHARACTERS = ['\"', '<', '>', '|', '\0', ':', '*', '?', '\\', '/'] + \
                              [chr(i) for i in range(1, 32)]


def error(s) -> None:
    print(s)
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


def get_valid_filename(directory: str, filename: str):
    filename = replace_invalid_filename_characters(filename)

    full_path = os.path.join(directory, filename)
    ext = get_file_extension(filename)
    file_name_only = filename[0:filename.index(f'.{ext}')]
    i = 1
    while os.path.exists(full_path):
        new_file = f'{file_name_only} {i}.{ext}'
        full_path = os.path.join(directory, new_file)

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


def get_origin(s: str):
    return s[0:find_nth(s, '/', 3)]


def combine_path(directory: str, new_dir: str) -> str:
    return os.path.join(directory, new_dir)


def validate_path(directory: str) -> str:
    if directory.isspace():
        directory = os.path.join(os.getcwd(), '/out')

    path = directory.replace('\\', '/')

    if not os.path.exists(path):
        os.mkdir(path)

    return path


def download_file(url, filename: str = None, headers: List[Tuple[str, str]] = None, user_agent: str = None) \
        -> Tuple[str, HTTPMessage]:
    opener = urllib.request.build_opener()

    if user_agent:
        headers.append(('User-Agent', user_agent))

    if headers:
        opener.addheaders = headers

    urllib.request.install_opener(opener)
    return urllib.request.urlretrieve(url, filename=filename, reporthook=ProgressBarImpl())

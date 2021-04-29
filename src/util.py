import os
import urllib.request
from typing import List, Tuple

from src.progress_bar import ProgressBarImpl

INVALID_FILENAME_CHARACTERS = [
    '\"', '<', '>', '|', '\0', chr(1), chr(2), chr(3), chr(4), chr(5), chr(6), chr(7), chr(8), chr(9), chr(10), chr(12),
    chr(13), chr(14), chr(15), chr(16), chr(17), chr(18), chr(19), chr(20), chr(21), chr(22), chr(23), chr(24), chr(25),
    chr(26), chr(27), chr(28), chr(29), chr(30), chr(31), ':', '*', '?', '\\', '/'
]


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


def validate_path(directory: str) -> str:
    if directory.isspace():
        directory = os.path.join(os.getcwd(), '/out')

    path = directory.replace('\\', '/')

    return path


def download_file(url, filename: str = None, headers: List[Tuple[str, str]] = None):
    if headers:
        opener = urllib.request.build_opener()
        opener.addheaders = headers
        urllib.request.install_opener(opener)

    urllib.request.urlretrieve(url, filename=filename, reporthook=ProgressBarImpl())

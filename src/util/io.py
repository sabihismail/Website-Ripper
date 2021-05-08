import hashlib
import os
from enum import Enum
from pathlib import Path
from typing import Tuple, Optional

from charset_normalizer import CharsetNormalizerMatches

from src.util.generic import error, is_blank

# Retrieved and modified from https://referencesource.microsoft.com/#mscorlib/system/io/path.cs,090eca8621a248ee
INVALID_PATH_CHARACTERS = ['\"', '<', '>', '|', '\0', '*', '?'] + \
                          [chr(i) for i in range(1, 32)]

INVALID_FILENAME_CHARACTERS = ['\"', '<', '>', '|', '\0', ':', '*', '?', '\\', '/'] + \
                              [chr(i) for i in range(1, 32)]

DEFAULT_MAX_FILENAME_LENGTH = 80


class DuplicateHandler(Enum):
    FIND_VALID_FILE = 'FIND_VALID_FILE'
    OVERWRITE = 'OVERWRITE'
    THROW_ERROR = 'THROW_ERROR'
    SKIP = 'SKIP'
    HASH_COMPARE = 'HASH_COMPARE'


def ensure_directory_exists(path: str):
    if path.startswith('/'):
        path = combine_path(os.getcwd(), path)

    if not os.path.exists(path):
        os.makedirs(path)


def handle_extension_period(ext: str, include_ext_period: bool = False) -> Optional[str]:
    if is_blank(ext):
        return None

    if include_ext_period:
        if not ext.startswith('.'):
            ext = f'.{ext}'
    else:
        while ext.startswith('.'):
            ext = ext[1:]

    return ext


def split_filename(s: str, fatal=False, include_ext_period: bool = False) -> Tuple[str, Optional[str]]:
    split = s.split('.')

    if len(split) == 1:
        if fatal:
            error(f'No file extension found: {s}')

        return split[0], None

    ext = handle_extension_period(split[-1], include_ext_period=include_ext_period)

    return '.'.join(split[:-1]), ext


def get_file_extension(s: str, fatal=False, include_ext_period: bool = False) -> Optional[str]:
    if '/' in s:
        _, s = split_full_path(s)

    return split_filename(s, fatal=fatal, include_ext_period=include_ext_period)[1]


def replace_invalid_path_characters(path: str):
    for char in INVALID_PATH_CHARACTERS:
        path = path.replace(char, '')

    return path


def replace_invalid_filename_characters(filename: str):
    for char in INVALID_FILENAME_CHARACTERS:
        filename = filename.replace(char, '')

    return filename


def split_full_path(full_path: str) -> Tuple[str, str]:
    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)

    return directory, filename


def get_filename(full_path: str) -> str:
    return split_full_path(full_path)[1]


def get_valid_filename(directory: str, filename: str = None) -> str:
    if not filename:
        directory, filename = split_full_path(directory)

    filename = replace_invalid_filename_characters(filename)

    full_path = combine_path(directory, filename=filename)
    filename_only, ext = split_filename(filename, fatal=False, include_ext_period=False)
    i = 1
    while os.path.exists(full_path):
        new_file = f'{filename_only}{i}.{ext}'
        full_path = combine_path(directory, filename=new_file)

        i += 1

    return full_path.replace('\\', '/')


def combine_path(*directories: str, filename: str = None) -> str:
    full_path = ''
    for directory in directories:
        directory = directory.replace('\\', '/')

        if directory.startswith('/'):
            directory = directory[1:]

        if not directory.endswith('/'):
            directory += '/'

        full_path += directory

    if filename:
        full_path += filename

    return full_path.replace('//', '/')


def validate_path(directory: str, default_path: str = combine_path(os.getcwd(), '/out'), fatal: bool = False) -> str:
    if is_blank(directory):
        if fatal:
            error(f'Path {directory} does not exist.')

        directory = default_path

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


def move_file(old: str, new: str, make_dirs: bool = True, duplicate_handler: DuplicateHandler = None) -> str:
    if make_dirs:
        os.makedirs(Path(new).parent, exist_ok=True)

    if duplicate_handler and Path(new).exists():
        if duplicate_handler == DuplicateHandler.FIND_VALID_FILE:
            new = get_valid_filename(new)
        elif duplicate_handler == DuplicateHandler.THROW_ERROR:
            error(f'File "{new}" already exists')
        elif duplicate_handler == DuplicateHandler.OVERWRITE:
            os.remove(new)
        elif duplicate_handler == DuplicateHandler.SKIP:
            return new
        elif duplicate_handler == DuplicateHandler.HASH_COMPARE:
            old_file = get_sha1_hash_file(old)
            new_file = get_sha1_hash_file(new)

            if old_file == new_file:
                return new

            new = get_valid_filename(new)

    file = str(Path(old).rename(new)).replace('\\', '/')

    return file


def write_file(path: str, text: str, filename: str = '', encoding: Optional[str] = None):
    if filename:
        path = combine_path(path, filename=filename)

    Path(path).write_text(text, encoding=encoding)


def read_file(path: str, filename: str = ''):
    if filename:
        path = combine_path(path, filename=filename)

    file_bytes = Path(path).read_bytes()
    encoding = CharsetNormalizerMatches.from_bytes(file_bytes).best().first().encoding

    return Path(path).read_text(encoding=encoding)


def split_path_components(path: str, fatal=True, include_ext_period: bool = False):
    directory, filename = split_full_path(path)
    filename_only, ext = split_filename(filename, fatal=fatal, include_ext_period=include_ext_period)

    return directory, filename_only, ext


def shorten_file_name(path, max_length=DEFAULT_MAX_FILENAME_LENGTH):
    directory, filename, ext = split_path_components(path, fatal=False, include_ext_period=False)

    if len(filename) <= max_length:
        return path

    filename = filename[:max_length]

    return combine_path(directory, filename=f'{filename}.{ext}')


def join_filename_with_ext(filename: str, ext: str) -> str:
    if not ext:
        return filename

    ext = handle_extension_period(ext, include_ext_period=True)

    return filename + ext


def file_exists(path: str) -> bool:
    return os.path.exists(path)

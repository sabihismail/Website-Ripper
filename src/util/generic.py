import sys
from enum import Enum
from typing import Tuple, Optional, Any, List, NamedTuple, Callable, Union


class KeyValuePair(NamedTuple):
    key: Any
    val: Any


class LogType(Enum):
    INFO = 'INFO',
    ERROR = 'ERROR'


def log(s: Union[str, Exception], extra: str = None, method: str = None, fatal: bool = True, log_type: LogType = LogType.INFO, end: str = '\n') -> None:
    to_print = str(s)

    if not is_blank(extra):
        to_print = extra + ' - ' + to_print

    if method:
        to_print = s + ' - ' + method

    out_file = None
    if log_type == LogType.INFO:
        out_file = sys.stdout
    elif log_type == LogType.ERROR:
        out_file = sys.stderr

    print(to_print, file=out_file, end=end)

    if log_type == LogType.ERROR and fatal:
        exit(-1)


def ends_with_skip(txt: str, char: str, skip: List[str] = None) -> bool:
    if not skip:
        return txt.endswith(char)

    for i in range(len(txt) - 1, -1, -1):
        if txt[i] in skip:
            continue

        if txt[i] != char:
            return False
        elif txt[i] == char:
            return True

    return False


def first_or_none(lst, func: Callable = lambda x: x) -> Optional[Any]:
    if type(lst) == Tuple:
        lst = list(lst)

    return next(iter(filter(func, lst)), None)


def distinct(lst, compare_lst=None):
    new_lst = []

    for elem in lst:
        if elem not in new_lst and (not compare_lst or elem not in compare_lst):
            new_lst.append(elem)

    return new_lst


def any_list_in_str(s: str, lst: List[str] = None) -> bool:
    if not lst or not s:
        return False

    for elem in lst:
        if elem in s:
            return True

    return False


def any_list_equal_str(s: str, lst: List[str] = None) -> bool:
    if not lst or not s:
        return False

    for elem in lst:
        if elem == s:
            return True

    return False


def name_of(var) -> str:
    return f'{var=}'.split('=')[0]


def find_nth(haystack: str, needle: str, n: int) -> int:
    start = haystack.find(needle)

    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1

    return start


def find_nth_reverse(haystack: str, needle: str, n: int) -> int:
    end = haystack.rfind(needle)

    while end >= 0 and n > 1:
        end = haystack.rfind(needle, 0, end - len(needle))
        n -= 1

    return end


def replace_with_index(s: str, replacement: str, start: int = 0, end: int = -1) -> str:
    if end == -1:
        end = len(s) - 1

    return s[:start] + replacement + s[end + 1:]


def is_blank(s: str) -> bool:
    return not s or s.isspace()

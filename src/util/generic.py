import sys
from typing import Tuple, Optional, Any, List


def error(s: str, method: str = None, fatal: bool = True) -> None:
    to_print = s
    if method:
        to_print = s + ' - ' + method

    print(to_print, file=sys.stderr)

    if fatal:
        exit(-1)


def first_or_none(lst) -> Optional[Any]:
    if type(lst) == Tuple:
        lst = list(lst)

    return next(iter(filter(lambda x: x, lst)), None)


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


def name_of(var) -> str:
    return f'{var=}'.split('=')[0]


def find_nth(haystack, needle, n):
    start = haystack.find(needle)

    while start >= 0 and n > 1:
        start = haystack.find(needle, start + len(needle))
        n -= 1

    return start


def is_blank(s) -> bool:
    return not s or s.isspace()

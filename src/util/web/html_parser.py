import re
from enum import Enum
from queue import LifoQueue
from typing import NamedTuple, List, Tuple, Dict

from selenium.webdriver.common.by import By

from src.util.generic import is_blank, ends_with_skip


class HTMLAttribute(NamedTuple):
    name: str
    text: str


class HTMLTagType(Enum):
    START = 'START'
    END = 'END'
    SELF_CLOSING = 'SELF_CLOSING'


class HTMLTag(NamedTuple):
    tag: str
    tag_type: HTMLTagType

    attributes: Dict[str, HTMLAttribute] = {}
    inner_html: str = ''
    start_index: int = -1
    end_index: int = -1

    def identifier(self):
        return self.attributes.get('id', None)


def parse_html_tag(html: str, start_index: int) -> HTMLTag:
    tag = ''
    i = start_index

    if html[i] == '<':
        i += 1

    while i < len(html) and html[i] not in [' ', '>']:
        tag += html[i]
        i += 1

    end_index = html.index('>', i)
    sub_str = html[i:end_index]

    tag_type = HTMLTagType.START
    if tag.startswith('/'):
        tag_type = HTMLTagType.END
        tag = tag[1:]
    elif ends_with_skip(tag, '/', skip=[' ', '>']):
        tag_type = HTMLTagType.SELF_CLOSING

    attributes: Dict[str, HTMLAttribute] = {}
    if not is_blank(sub_str):
        regex_match = re.findall(r' *([a-zA-Z]+)=[\'"]([a-zA-Z0-9_-]+)[\'"]', sub_str)
        for key, val in regex_match:
            attributes[key] = val

    html_tag = HTMLTag(tag, attributes=attributes, start_index=start_index, end_index=end_index, tag_type=tag_type)

    return html_tag


def find_html_tag(by: By, identifier: str, html: str) -> Tuple[int, int]:
    stack = LifoQueue()
    begin_stack = False

    for i in range(len(html)):
        if html[i] != '<':
            continue

        element = parse_html_tag(html, i)

        if by == By.ID:
            if element.identifier() == identifier:
                if element.tag_type == HTMLTagType.SELF_CLOSING:
                    return element.start_index, element.end_index + 1

                begin_stack = True

        if begin_stack:
            if element.tag_type == HTMLTagType.START:
                stack.put(element)
            elif element.tag_type == HTMLTagType.END:
                if stack.qsize() == 1:
                    starting_element: HTMLTag = stack.get()

                    return starting_element.start_index, element.end_index + 1
                else:
                    stack.get()

    return -1, -1

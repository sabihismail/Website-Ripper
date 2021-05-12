from typing import NamedTuple, List, Tuple, Dict, Optional

from selenium.webdriver.common.by import By


class HTMLAttribute(NamedTuple):
    name: str
    text: str


class HTMLTag(NamedTuple):
    tag: str
    attributes: Dict[str, HTMLAttribute] = {}
    identifier: Optional[HTMLAttribute] = attributes.get('id', None)
    inner_html: str = ''


def parse_html_tag(html: str, start_index: int) -> Tuple[HTMLTag, int]:
    tag = ''

    i = start_index
    while html[i] != ' ':
        tag += html[i]
        i += 1

    attributes: Dict[str, HTMLAttribute] = {}

    html_tag = HTMLTag(tag)

    return html_tag


def find_html_tag(by: By, identifier: str, html: str) -> Tuple[int, int]:
    for i in range(len(html)):
        if html[i] is not '<':
            continue

        tag, i = parse_html_tag(html, i)

        if by == By.ID:
            if tag.identifier == identifier:
                return tag

    return -1, -1

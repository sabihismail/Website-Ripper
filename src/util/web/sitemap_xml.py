from datetime import datetime
from typing import List, Optional
from xml.dom.minidom import Element
from xml.etree import ElementTree

from src.util.generic import is_blank
from src.util.web.generic import get_base_url, read_url_utf8
from src.util.web.robots_txt import RobotsTxt


class SitemapXmlURL:
    def __init__(self, url: str, last_modified: datetime):
        self.url = url
        self.last_modified = last_modified

    def __repr__(self):
        return f'SitemapXmlURL([URL: {self.url}, Last Modified: {self.last_modified}])'


class SitemapXml:
    def __init__(self):
        self.url_set: List[SitemapXmlURL] = []

    def __iter__(self):
        return self.url_set.__iter__()

    def __getitem__(self, item):
        return self.url_set[item]

    def add_url(self, item: SitemapXmlURL):
        self.url_set.append(item)

    def __repr__(self):
        return f'SitemapXml([URL Set: {", ".join(map(repr, self.url_set))}])'

    @staticmethod
    def get_element_by_end_str(parent: Element, val: str, default=None) -> Optional[str]:
        element = SitemapXml.get_element_by_end(parent, val)

        if element is None or is_blank(element.text):
            return default

        return element.text

    @staticmethod
    def get_element_by_end(parent: Element, val: str, default=None) -> Optional[Element]:
        elements = SitemapXml.get_elements_by_end(parent, val)

        if len(elements) == 0:
            return default

        return elements[0]

    @staticmethod
    def get_elements_by_end(parent: Element, val: str) -> List[Element]:
        elements: List[Element] = [element for element in parent if element.tag.endswith(val)]
        return elements

    @staticmethod
    def parse_sitemap(data: str):
        tree = ElementTree.fromstring(data)
        urls = SitemapXml.get_elements_by_end(tree, 'url')

        sitemap = SitemapXml()
        for url in urls:
            loc: Optional[str] = SitemapXml.get_element_by_end_str(url, 'loc')
            last_modified_str: Optional[str] = SitemapXml.get_element_by_end_str(url, 'lastmod')

            last_modified = None
            if not is_blank(last_modified_str):
                last_modified = datetime.fromisoformat(last_modified_str)

            sitemap_url = SitemapXmlURL(url=loc, last_modified=last_modified)
            sitemap.add_url(sitemap_url)

        return sitemap

    @staticmethod
    def parse_sitemap_by_url(url: str):
        if 'sitemap.xml' in url:
            sitemap_url = url
        else:
            if url.startswith('http'):
                base_url = get_base_url(url)
            elif url.startswith('//'):
                base_url = get_base_url('http:' + url)
            else:
                base_url = get_base_url('https://' + url)

            robots = RobotsTxt.get_robots_txt_by_url(base_url)
            sitemap_url = robots.sitemap

        data = read_url_utf8(sitemap_url)

        return SitemapXml.parse_sitemap(data)

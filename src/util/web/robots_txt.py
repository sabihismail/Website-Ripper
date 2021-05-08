from typing import List, Optional

from src.util.generic import KeyValuePair, is_blank
from src.util.web.generic import get_base_url


class RobotsTxt:
    def __init__(self):
        self.user_agents: List[RobotsTxtUserAgent] = []
        self.current_user_agent: Optional[RobotsTxtUserAgent] = None
        self.sitemap = None

    def new_user_agent(self, user_agent: str):
        if self.current_user_agent:
            self.user_agents.append(self.current_user_agent)

        self.current_user_agent = RobotsTxtUserAgent(user_agent)

    def add_allowed_url(self, url: str):
        if self.current_user_agent and url not in self.current_user_agent.allowed_urls:
            self.current_user_agent.add_allowed_url(url)

    def add_disallowed_url(self, url: str):
        if self.current_user_agent and url not in self.current_user_agent.disallowed_urls:
            self.current_user_agent.add_disallowed_url(url)

    def set_sitemap(self, url: str):
        if is_blank(url):
            return

        self.sitemap = url

    def hit_blank(self):
        if self.current_user_agent:
            self.user_agents.append(self.current_user_agent)
            self.current_user_agent = None

    def parse(self, line: str):
        if line.startswith('#'):
            return
        elif line.startswith('User-agent:'):
            self.parse_user_agent(line)
        elif line.startswith('Disallow:'):
            self.parse_disallowed_url(line)
        elif line.startswith('Sitemap:'):
            self.parse_sitemap_url(line)
        elif is_blank(line):
            self.hit_blank()

    def parse_user_agent(self, line: str):
        user_agent = self.get_key_value(line).val
        self.new_user_agent(user_agent)

    def parse_allowed_url(self, line: str):
        allowed_url = self.get_key_value(line).val
        self.add_disallowed_url(allowed_url)

    def parse_disallowed_url(self, line: str):
        disallowed_url = self.get_key_value(line).val
        self.add_disallowed_url(disallowed_url)

    def parse_sitemap_url(self, line: str):
        sitemap_url = self.get_key_value(line).val
        self.set_sitemap(sitemap_url)

    def __repr__(self):
        return f'RobotsTxt([Sitemap: {self.sitemap}, UserAgents: {", ".join(map(repr, self.user_agents))}])'

    @staticmethod
    def get_key_value(line: str) -> KeyValuePair:
        key, val = line.split(':', 1)

        return KeyValuePair(key.strip(), val.strip())

    @staticmethod
    def get_robots_txt_by_url(url: str):
        if url.endswith('/robots.txt'):
            robots_url = url
        else:
            if url.startswith('http'):
                base_url = get_base_url(url)
            elif url.startswith('//'):
                base_url = get_base_url('http:' + url)
            else:
                base_url = get_base_url('https://' + url)

            robots_url = f'https://{base_url}/robots.txt'

        lines = read_url_utf8(robots_url).splitlines()

        robots_txt = RobotsTxt()
        for line in lines:
            robots_txt.parse(line)

        return robots_txt


class RobotsTxtUserAgent:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self.allowed_urls: List[str] = []
        self.disallowed_urls: List[str] = []

    def add_allowed_url(self, url: str):
        self.allowed_urls.append(url)

    def add_disallowed_url(self, url: str):
        self.disallowed_urls.append(url)

    def __repr__(self):
        return f'RobotsTxtUserAgent([UserAgent: {self.user_agent}, Allowed URLs: {", ".join(self.allowed_urls)}, ' \
               f'Disallowed URLs: {", ".join(self.disallowed_urls)}])'

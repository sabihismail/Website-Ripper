from enum import Enum
from typing import NamedTuple


class ScrapeJobType(Enum):
    VIDEO = 'VIDEO'
    URL = 'URL'


class ScrapeJobTask(Enum):
    REPLACE = 'REPLACE'


class ScrapeJob(NamedTuple):
    task: ScrapeJobTask
    scrape_job_type: ScrapeJobType
    url: str = ''
    file_path: str = ''
    html: str = ''
    identifier: str = ''

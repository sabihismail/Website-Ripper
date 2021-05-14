from enum import Enum


class ScrapeJobType(Enum):
    VIDEO = 'VIDEO'
    URL = 'URL'


class ScrapeJobTask(Enum):
    REPLACE = 'REPLACE'


class ScrapeJob:
    def __init__(self, task: ScrapeJobTask, scrape_job_type: ScrapeJobType, url: str = '', file_path: str = '', html: str = '', identifier: str = ''):
        self.task = task
        self.scrape_job_type = scrape_job_type
        self.url = url
        self.file_path = file_path
        self.html = html
        self.identifier = identifier

    def __repr__(self):
        return str(self.__dict__)

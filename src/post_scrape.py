from pathlib import Path

from src.config import Config, PostScrapeJobType
from src.util.io import scan_directory


def run_post_scrape(config: Config, encoding: str = 'utf-8'):
    _, files = scan_directory(config.out_dir, [".html"])

    for file in files:
        file_obj = Path(file)
        file_text = file_obj.read_text(encoding=encoding)

        for job in config.post_scrape_jobs:
            if job.obj_type == PostScrapeJobType.REPLACE:
                file_text = file_text.replace(job.identifier, job.text)

        file_obj.write_text(file_text, encoding=encoding)

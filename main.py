import sys

from src.config import CONFIG_FILE, get_config
from src.post_scrape import run_post_scrape
from src.scrape import scrape
from src.util.generic import log

'''
sys.argv = [
    __file__,
    'job3.json'
]'''

if __name__ == '__main__':
    config_file = CONFIG_FILE if len(sys.argv) == 1 else sys.argv[1]

    config = get_config(file=config_file)

    if not config.post_scrape_jobs_only:
        scrape(config)

    run_post_scrape(config)

    log('Completed everything. The program will now exit.')

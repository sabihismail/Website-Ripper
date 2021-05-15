import sys

from src.config import CONFIG_FILE, get_config
from src.scrape import scrape

'''
sys.argv = [
    __file__,
    'job3.json'
]'''

if __name__ == '__main__':
    config_file = CONFIG_FILE if len(sys.argv) == 1 else sys.argv[1]

    config = get_config(file=config_file)
    scrape(config)

import sys
from src.config import *
from src.start import *

if __name__ == '__main__':
    config_file = CONFIG_FILE if len(sys.argv) == 1 else sys.argv[1]

    config = get_config(file=config_file)
    scrape(config)

import sys
from src.config import *
from src.start import *

if __name__ == '__main__':
    config_file = CONFIG_FILE if len(sys.argv) == 1 else ''.join(sys.argv)

    config = get_config(file=config_file)
    scrape(config)

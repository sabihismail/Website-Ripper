# Website Ripper

Rips entire websites (or at least attempts to), or individual pages depending on configuration.

## Setup
1. Run `git clone https://github.com/sabihismail/Website-Ripper` and move into the directory
2. Run `virtualenv venv && source .env/bin/activate && pip install -r requirements.txt`
3. You will need a compatible ChromeDriver.exe available from [here](https://chromedriver.chromium.org/)
   * Place it in the `res/` folder
4. Copy `job.example.json` to `job.json` and configure variables below
5. Run `python main.py` and cross your fingers

## Job Configuration
1. To-Do

## FYI
There will probably be many bugs and inconsistencies since a website can deploy any number of measures to be inconsistent from other websites.

The code is provided as-is, and it should not be used maliciously. I do not take responsibility for the misuse of this tool. It's purely for learning purposes.

@echo off

set file="requirements.txt"

IF EXIST file (
  del file
)

cd venv/Scripts/

pip.exe freeze -l >> ../../requirements.txt

cd ../../

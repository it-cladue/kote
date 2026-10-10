@echo off
rem Gorev Zamanlayici bu dosyayi calistirir: once kendi klasorune gecer, sonra paneli pencere acmadan baslatir.
cd /d "%~dp0"
if not exist "%LOCALAPPDATA%\KanitPaneli" mkdir "%LOCALAPPDATA%\KanitPaneli"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0kanit_paneli.py"

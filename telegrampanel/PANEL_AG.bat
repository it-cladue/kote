@echo off
rem Ag modu: panel bu bilgisayarda calisir, digerleri tarayicidan http://<bu bilgisayar>:8080 ile girer.
cd /d "%~dp0"
start "" "%~dp0KanitPaneli.exe" --ag

@echo off
rem Tunel modu: panel yalnizca bu bilgisayarda calisir, Cloudflare Tunnel (TUNEL_BASLAT.bat) onu internete https ile acar.
cd /d "%~dp0"
start "" "%~dp0KanitPaneli.exe" --tunel

@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (echo Once KUR.bat calistirin. & pause & exit /b 1)
echo Yetki ornekleri:  admin   *   OF   OF:oku   OF:oku,kt   "OF,PP:oku GA"
set /p KADI=Kullanici adi: 
set /p YETKI=Yetki: 
venv\Scripts\python.exe -m app.panel kullanici-ekle "%KADI%" "%YETKI%"
pause

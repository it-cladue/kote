@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (echo Once KUR.bat calistirin. & pause & exit /b 1)
echo Panel, bu kullanici oturum actiginda arka planda otomatik baslayacak (Gorev Zamanlayici: KanitPaneli).
schtasks /Create /F /SC ONLOGON /TN "KanitPaneli" /TR "\"%~dp0venv\Scripts\pythonw.exe\" -m app.panel" /RL LIMITED
if errorlevel 1 (echo Gorev olusturulamadi. & pause & exit /b 1)
schtasks /Run /TN "KanitPaneli" >nul
echo Gorev kuruldu ve baslatildi. Kaldirmak icin:  schtasks /Delete /TN "KanitPaneli" /F
pause

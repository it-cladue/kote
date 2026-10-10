@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (echo Once KUR.bat calistirin. & pause & exit /b 1)
echo Panel, bu kullanici oturum actiginda arka planda otomatik baslayacak (Gorev Zamanlayici: KanitPaneli).
schtasks /Create /F /SC ONLOGON /TN "KanitPaneli" /TR "\"%~dp0GOREV_BASLAT.bat\"" /RL LIMITED
if errorlevel 1 (echo Gorev olusturulamadi. & pause & exit /b 1)
schtasks /Run /TN "KanitPaneli" >nul
timeout /t 5 >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/saglik -TimeoutSec 5; if ($r.StatusCode -eq 200) { 'Panel calisiyor: http://127.0.0.1:8080' } } catch { 'Panel henuz cevap vermiyor; %LOCALAPPDATA%\KanitPaneli\panel.log dosyasina bakin.' }"
echo Kaldirmak icin:  schtasks /Delete /TN "KanitPaneli" /F
pause

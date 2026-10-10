@echo off
rem Windows Guvenlik Duvari'nda 8080 portunu (panel) ac. Yonetici izni ister.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="KanitPaneli 8080" >nul 2>&1
netsh advfirewall firewall add rule name="KanitPaneli 8080" dir=in action=allow protocol=TCP localport=8080
echo Guvenlik duvari kurali eklendi (TCP 8080). Panel ag modunda acilinca diger bilgisayarlar baglanabilir.
pause

@echo off
rem Windows Guvenlik Duvari'nda 8080 portunu (panel) ac. Yonetici izni ister.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
netsh advfirewall firewall delete rule name="KanitPaneli 8080" >nul 2>&1
rem yalnizca ofis (ozel) aglarindan: internetten dogrudan gelen baglantilar guvenlik duvarinda durur
netsh advfirewall firewall add rule name="KanitPaneli 8080" dir=in action=allow protocol=TCP localport=8080 remoteip=localsubnet,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10
echo Guvenlik duvari kurali eklendi (TCP 8080). Panel ag modunda acilinca diger bilgisayarlar baglanabilir.
pause

@echo off
rem Cloudflare Tunnel'i baslatir. Gerekenler (ayni klasorde):
rem   cloudflared.exe  -> https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
rem                       (indirip adini cloudflared.exe yapin)
rem   tunel_token.txt  -> Cloudflare Zero Trust > Networks > Tunnels > tunelin "token" degeri (tek satir)
rem Yonetici izni gerekmez; pencere acik kaldigi surece tunel calisir.
cd /d "%~dp0"
if not exist "%~dp0cloudflared.exe" (
  echo cloudflared.exe bulunamadi. Su adresten indirip bu klasore "cloudflared.exe" adiyla koyun:
  echo https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  pause
  exit /b 1
)
if not exist "%~dp0tunel_token.txt" (
  echo tunel_token.txt bulunamadi. Cloudflare Zero Trust ^> Networks ^> Tunnels ^> tunelinizin token degerini
  echo Not Defteri ile tunel_token.txt adli dosyaya tek satir olarak yapistirip bu klasore koyun.
  pause
  exit /b 1
)
set /p TUNEL_TOKEN=<"%~dp0tunel_token.txt"
echo Tunel baslatiliyor... Bu pencere acik kaldigi surece panel internetten erisilebilir.
"%~dp0cloudflared.exe" tunnel run --token %TUNEL_TOKEN%
pause

<#
.SYNOPSIS
    Etiket Köprüsü'nü Windows'ta başlatır: Python'ı bulur, bağımlılığı kurar, config.json ve token'ları hazırlar,
    botu çalıştırır.

.EXAMPLE
    .\start.ps1           # ilk çalıştırmada token'ları sorar ve .env dosyasına yazar; sonrakilerde direkt başlatır
    .\start.ps1 -Reset    # token'ları yeniden sorar
    .\start.ps1 -Test     # botu başlatmadan testleri koşar

    "running scripts is disabled" hatası alırsan:
    powershell -ExecutionPolicy Bypass -File .\start.ps1
#>
param(
    [switch] $Reset,
    [switch] $Test
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# Python: önce 'py' başlatıcısı, yoksa 'python'
if (Get-Command py -ErrorAction SilentlyContinue)          { $script:UseLauncher = $true }
elseif (Get-Command python -ErrorAction SilentlyContinue)  { $script:UseLauncher = $false }
else {
    throw "Python bulunamadı. https://www.python.org/downloads/ adresinden kur; kurulumda 'Add python.exe to PATH' kutusunu işaretle."
}

function Invoke-Py {
    if ($script:UseLauncher) { & py -3 @args } else { & python @args }
}

Write-Host "Python : $(Invoke-Py --version)"

# 1) Bağımlılık
Invoke-Py -m pip install --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip kurulumu başarısız (internet / proxy?)." }

# 2) config.json
if (-not (Test-Path config.json)) {
    Copy-Item config.example.json config.json
    Write-Host ""
    Write-Host "config.json oluşturuldu. Notepad'de açılıyor:" -ForegroundColor Yellow
    Write-Host "  - admins   : kendi Slack kullanıcı ID'n (U...) ya da e-postan"
    Write-Host "  - keywords : @etiket -> hedefler (örnekleri kendi gruplarınla değiştir)"
    Write-Host "Kaydedip kapattıktan sonra bu scripti tekrar çalıştır." -ForegroundColor Yellow
    Start-Process notepad config.json
    exit 1
}

# 3) Token'lar -> .env (bu dosya git'e girmez, paylaşma)
if ($Reset -or -not (Test-Path .env)) {
    Write-Host ""
    Write-Host "Slack token'ları (api.slack.com/apps > Etiket Köprüsü):"
    $bot = (Read-Host "  Bot User OAuth Token   (OAuth & Permissions, xoxb-...)").Trim()
    $app = (Read-Host "  App-Level Token        (Basic Information > App-Level Tokens, xapp-...)").Trim()
    if ($bot -notlike 'xoxb-*') { throw "Bot token 'xoxb-' ile başlamalı." }
    if ($app -notlike 'xapp-*') { throw "App-level token 'xapp-' ile başlamalı." }
    @("SLACK_BOT_TOKEN=$bot", "SLACK_APP_TOKEN=$app") | Set-Content -Path .env -Encoding ascii
    Write-Host ".env yazıldı."
}
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        Set-Item -Path "Env:$($matches[1])" -Value $matches[2]
    }
}

# 4) Test ya da çalıştır
if ($Test) {
    Invoke-Py -m unittest
    exit $LASTEXITCODE
}
Write-Host ""
Write-Host "Bot başlatılıyor (durdurmak için Ctrl+C)..." -ForegroundColor Green
Invoke-Py app.py
exit $LASTEXITCODE

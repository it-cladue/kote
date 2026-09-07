<#
.SYNOPSIS
    Etiket Köprüsü'nü Windows'ta başlatır: Python'ı bulur, bu klasöre özel bir .venv kurar, config.json ve token'ları
    hazırlar, botu çalıştırır. Servis (NSSM) de aynı .venv\Scripts\python.exe ile çalıştırılmalıdır.

.EXAMPLE
    .\start.ps1           # ilk çalıştırmada token'ları sorar ve .env dosyasına yazar; sonrakilerde direkt başlatır
    .\start.ps1 -Reset    # token'ları yeniden sorar
    .\start.ps1 -Test     # botu başlatmadan testleri koşar
    .\start.ps1 -Force    # bu klasör için servis çalışıyor olsa da elle başlat (normalde istenmez)

    "running scripts is disabled" hatası alırsan:
    powershell -ExecutionPolicy Bypass -File .\start.ps1
#>
param(
    [switch] $Reset,
    [switch] $Test,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 0) Bu klasör için bir NSSM servisi zaten çalışıyorsa ikinci kopya olayları bölüşür ve config'i aynı anda yazar.
if (-not $Force -and -not $Test) {
    $here = $PSScriptRoot.TrimEnd('\')
    Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Services' -ErrorAction SilentlyContinue | ForEach-Object {
        $p = Get-ItemProperty -Path (Join-Path $_.PSPath 'Parameters') -ErrorAction SilentlyContinue
        if ($p -and $p.AppDirectory -and ($p.AppDirectory.TrimEnd('\') -ieq $here)) {
            $svc = Get-Service -Name $_.PSChildName -ErrorAction SilentlyContinue
            if ($svc -and $svc.Status -eq 'Running') {
                throw "Bu klasör için '$($svc.Name)' servisi zaten çalışıyor. Elle ikinci kopya başlatma; log için: Get-Content -Wait <log dosyası>. Yine de istiyorsan: .\start.ps1 -Force"
            }
        }
    }
}

# 1) Python: önce 'py' başlatıcısı, yoksa 'python'
if (Get-Command py -ErrorAction SilentlyContinue)          { $bootstrap = @('py', '-3') }
elseif (Get-Command python -ErrorAction SilentlyContinue)  { $bootstrap = @('python') }
else {
    throw "Python bulunamadı. https://www.python.org/downloads/ adresinden kur; kurulumda 'Add python.exe to PATH' kutusunu işaretle."
}

# 2) Bu klasöre özel sanal ortam (.venv): servis de aynı yorumlayıcıyı kullanır, başka Python'lardan etkilenmez
$venvPy = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host ".venv oluşturuluyor..."
    & $bootstrap[0] $bootstrap[1..($bootstrap.Count)] -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { throw ".venv oluşturulamadı." }
}
Write-Host "Python : $(& $venvPy --version)  ($venvPy)"

$marker = Join-Path $PSScriptRoot '.venv\.requirements-installed'
if (-not (Test-Path $marker) -or (Get-Item requirements.txt).LastWriteTime -gt (Get-Item $marker).LastWriteTime) {
    Write-Host "Bağımlılıklar kuruluyor..."
    & $venvPy -m pip install --quiet --disable-pip-version-check -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip kurulumu başarısız (internet / proxy?)." }
    Set-Content -Path $marker -Value (Get-Date).ToString('s')
}

# 3) config.json
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

# 4) Token'lar -> .env (tek doğru kaynak; git'e girmez, paylaşma)
if ($Reset -or -not (Test-Path .env)) {
    Write-Host ""
    Write-Host "Slack token'ları (api.slack.com/apps > Etiket Köprüsü):"
    $bot = (Read-Host "  Bot User OAuth Token   (OAuth & Permissions, xoxb-...)").Trim()
    $app = (Read-Host "  App-Level Token        (Basic Information > App-Level Tokens, xapp-...)").Trim()
    if ($bot -notlike 'xoxb-*') { throw "Bot token 'xoxb-' ile başlamalı." }
    if ($app -notlike 'xapp-*') { throw "App-level token 'xapp-' ile başlamalı." }
    @("SLACK_BOT_TOKEN=$bot", "SLACK_APP_TOKEN=$app") | Set-Content -Path .env -Encoding ascii
    Write-Host ".env yazıldı. Servis çalışıyorsa yeni token'ı alması için: nssm restart <servis adı>"
}

# 5) Test ya da çalıştır (app.py .env'i kendisi okur)
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
if ($Test) {
    & $venvPy -m unittest
    exit $LASTEXITCODE
}
Write-Host ""
Write-Host "Bot başlatılıyor (durdurmak için Ctrl+C)..." -ForegroundColor Green
& $venvPy app.py
exit $LASTEXITCODE

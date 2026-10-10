# ==================== WEB PANELI KOPRUSU (surum 3) ====================
# Web paneli (telegrampanel) Excel'e dogrudan yazmaz. Panelde yapilan onay (KT), duzenleme, silme ve geri alma
# islemleri panel_kuyruk.jsonl dosyasina satir satir eklenir; bot bu dosyayi dongude okur, KENDI Excel
# baglantisiyla uygular ve sonucu panel_kuyruk_sonuc.jsonl'a yazar. Boylece Excel'e tek yazan yine bottur.
# Ek olarak: her kayitta kayitlar.jsonl'a "kim ekledi, hangi link" satiri; 60 sn'de bir heartbeat.txt (bot canli mi).
# Panel kurulu degilse bu blok hicbir sey yapmaz (kuyruk dosyasi yoksa dongu aninda doner).
# PAYLASIM KLASORU MODU: config.json'a "PANEL_KLASOR": "C:\\...\\OneDrive - Get Mails\\KanitPaneli" yazilirsa panelle alisveris
# dosyalari (kuyruk, sonuc, Excel kopyasi, kayitlar.jsonl, heartbeat) o klasorde tutulur ve bot kucuk durum dosyalarini
# (onaylilar, engellenenler, kategoriler, kullanicilar, oturumlar, bakim bayraklari, bot_log) ile gorselleri oraya kopyalar.
# Boylece token'larin oldugu bot klasoru paylasilmaz; yalnizca PANEL_KLASOR paylasilir. Yazilmazsa her sey bot klasorundedir.
$PANEL_KLASOR       = [string](Get-ConfigValue "PANEL_KLASOR" $SCRIPT_DIR)
function Join-Panel($f) { return (Join-Path $PANEL_KLASOR $f) }
$PANEL_KUYRUK_DOSYA = [string](Get-ConfigValue "PANEL_KUYRUK_DOSYA" (Join-Panel "panel_kuyruk.jsonl"))
$PANEL_SONUC_DOSYA  = [string](Get-ConfigValue "PANEL_SONUC_DOSYA" (Join-Panel "panel_kuyruk_sonuc.jsonl"))
$PANEL_KUYRUK_KLASOR = [string](Get-ConfigValue "PANEL_KUYRUK_KLASOR" (Join-Panel "panel_kuyruk"))   # her bilgisayar kendi dosyasina yazar
$PANEL_OFFSET_DOSYA = [string](Get-ConfigValue "PANEL_OFFSET_DOSYA" (Join-Base "panel_kuyruk_offset.json"))        # botun kendi defteri (bot klasorunde)
$PANEL_ISLENEN_DOSYA = [string](Get-ConfigValue "PANEL_ISLENEN_DOSYA" (Join-Base "panel_kuyruk_islenen.txt"))   # islenen is kimlikleri (OneDrive catisma kopyasi / tekrar okuma korumasi)
$global:PanelIslenenler = $null
$PANEL_KAYIT_DOSYA  = [string](Get-ConfigValue "PANEL_KAYIT_DOSYA" (Join-Panel "kayitlar.jsonl"))
$HEARTBEAT_DOSYA    = [string](Get-ConfigValue "HEARTBEAT_DOSYA" (Join-Panel "heartbeat.txt"))
$PANEL_KUYRUK_SN    = [int](Get-ConfigValue "PANEL_KUYRUK_SN" 5)
# Panel icin Excel kopyasi: bot calisirken Excel COM dosyayi kilitli tutar, panel ana dosyayi kopyalayamaz (Permission denied).
# Bot, dosya degistikce (en sik PANEL_KOPYA_SN saniyede bir) SaveCopyAs ile bu kopyayi yazar; panel ana dosya kilitliyse bunu okur.
$PANEL_EXCEL_KOPYA  = [string](Get-ConfigValue "PANEL_EXCEL_KOPYA" (Join-Panel "panel_excel_kopya.xlsx"))
$PANEL_DURUM_SN     = [int](Get-ConfigValue "PANEL_DURUM_SN" 60)      # paylasim klasoru modunda durum dosyasi/gorsel esitleme araligi
$global:PanelSonDurum = [datetime]::MinValue
$global:PanelDurumImza = @{}
$PANEL_KOPYA_SN     = [int](Get-ConfigValue "PANEL_KOPYA_SN" 60)
$global:PanelSonKopya = [datetime]::MinValue
$global:PanelKopyaYazma = $null
$global:PanelSonKontrol = [datetime]::MinValue
$global:PanelSonNabiz   = [datetime]::MinValue
$script:PanelUtf8 = New-Object System.Text.UTF8Encoding $false
# --- WEB PANELI KOPRUSU: AYAR SONU ---
# --- PANEL FONKSIYONLARI ---

# ==================== WEB PANELI KOPRUSU: FONKSIYONLAR (surum 3) ====================
function Write-JsonSatir($dosya, $nesne) {
    # BOM'suz UTF-8, CRLF satir sonu; panel (Python) satir satir okur.
    $kd = Split-Path -Parent $dosya
    if ($kd -and -not (Test-Path -LiteralPath $kd)) { New-Item -ItemType Directory -Path $kd -Force | Out-Null }
    $json = ($nesne | ConvertTo-Json -Compress -Depth 6)
    [System.IO.File]::AppendAllText($dosya, ($json + "`r`n"), $script:PanelUtf8)
}

# Kucuk durum dosyalarini atomik yazar (tmp + Replace): elektrik kesilirse yarim dosya kalmaz.
function Write-PanelAtomik($yol, $metin) {
    $tmp = "$yol.tmp"
    [System.IO.File]::WriteAllText($tmp, $metin, $script:PanelUtf8)
    Move-Item -LiteralPath $tmp -Destination $yol -Force   # ayni surucude yerine koyma (botun Set-TextFileAtomic kalibi)
}

# Excel'in panel kopyasi (bot acikken ana dosya kilitli). Dosya degismediyse ya da sure dolmadiysa hicbir sey yapmaz.
function Update-PanelExcelKopyasi([bool]$zorla = $false) {
    try {
        if (-not $global:xlWb) { return }
        if (-not $zorla -and ((Get-Date) - $global:PanelSonKopya).TotalSeconds -lt $PANEL_KOPYA_SN) { return }
        $global:PanelSonKopya = Get-Date
        $kd = Split-Path -Parent $PANEL_EXCEL_KOPYA
        if ($kd -and -not (Test-Path -LiteralPath $kd)) { New-Item -ItemType Directory -Path $kd -Force | Out-Null }
        $anaYazma = $null
        try { $anaYazma = (Get-Item -LiteralPath $EXCEL_DOSYA).LastWriteTime } catch { $anaYazma = $null }
        if (-not $zorla -and $anaYazma -and $global:PanelKopyaYazma -and $anaYazma -le $global:PanelKopyaYazma -and (Test-Path -LiteralPath $PANEL_EXCEL_KOPYA)) { return }
        $gecici = $PANEL_EXCEL_KOPYA + ".yeni.xlsx"
        if (Test-Path -LiteralPath $gecici) { Remove-Item -LiteralPath $gecici -Force -ErrorAction SilentlyContinue }
        $global:xlWb.SaveCopyAs($gecici)
        Move-Item -LiteralPath $gecici -Destination $PANEL_EXCEL_KOPYA -Force
        $global:PanelKopyaYazma = if ($anaYazma) { $anaYazma } else { Get-Date }
    } catch {
        Write-Log "! Panel Excel kopyasi yazilamadi: $_"
    }
}

# Paylasim klasoru modu: bot klasorundeki kucuk durum dosyalarini, gizli alanlari ayiklanmis ayarlari ve gorselleri
# PANEL_KLASOR'e kopyalar (yalnizca degisenler). Tek klasor modunda (PANEL_KLASOR = bot klasoru) hicbir sey yapmaz.
function Sync-PanelDurumu([bool]$zorla = $false) {
    try {
        if ((Resolve-Path -LiteralPath $PANEL_KLASOR -ErrorAction SilentlyContinue).Path -eq (Resolve-Path -LiteralPath $SCRIPT_DIR).Path) { return }
        if (-not $zorla -and ((Get-Date) - $global:PanelSonDurum).TotalSeconds -lt $PANEL_DURUM_SN) { return }
        $global:PanelSonDurum = Get-Date
        if (-not (Test-Path -LiteralPath $PANEL_KLASOR)) { New-Item -ItemType Directory -Path $PANEL_KLASOR -Force | Out-Null }
        # 1) kucuk durum dosyalari (ayni adla)
        foreach ($yol in @($ONAYLILAR_DOSYA, $ENGELLENEN_DOSYA, $KATEGORI_DOSYA, $KULLANICI_DOSYA, $OTURUM_DOSYA, $BAKIM_DOSYA, $GYAZO_BAKIM_DOSYA, $LOG_DOSYA)) {
            if (-not $yol) { continue }
            $hedef = Join-Panel (Split-Path -Leaf $yol)
            if (-not (Test-Path -LiteralPath $yol)) {
                if ((Split-Path -Leaf $yol) -in @("bakim_modu.txt", "gyazo_bakim.txt") -and (Test-Path -LiteralPath $hedef)) { Remove-Item -LiteralPath $hedef -Force -ErrorAction SilentlyContinue }
                continue
            }
            $it = Get-Item -LiteralPath $yol
            $imza = "$($it.LastWriteTime.Ticks):$($it.Length)"
            if ($global:PanelDurumImza[$yol] -eq $imza -and (Test-Path -LiteralPath $hedef)) { continue }
            try { Copy-Item -LiteralPath $yol -Destination $hedef -Force; $global:PanelDurumImza[$yol] = $imza } catch { Write-Log "! Panel durum kopyasi ($hedef): $_" }
        }
        # 2) ayarlar: gizli alanlar (token/sifre) cikarilarak panel_bot_ayarlari.json
        try {
            if ($global:Config) {
                $temiz = [ordered]@{}
                foreach ($p in $global:Config.PSObject.Properties) {
                    if ($p.Name -match 'TOKEN|PASSWORD|SIFRE|SECRET') { continue }
                    $temiz[$p.Name] = $p.Value
                }
                $json = ($temiz | ConvertTo-Json -Depth 4)
                $hedef = Join-Panel "panel_bot_ayarlari.json"
                if (-not (Test-Path -LiteralPath $hedef) -or ([System.IO.File]::ReadAllText($hedef) -ne $json)) { Write-PanelAtomik $hedef $json }
            }
        } catch {}
        # 3) gorseller ve indirilmis ekran goruntuleri: yalnizca yeni/degismis dosyalar
        foreach ($kl in @($GORSEL_KLASOR, (Join-Base "ekran_goruntuleri"))) {
            if (-not $kl -or -not (Test-Path -LiteralPath $kl)) { continue }
            $kok = (Resolve-Path -LiteralPath $kl).Path
            $hedefKok = Join-Panel (Split-Path -Leaf $kok)
            foreach ($f in (Get-ChildItem -LiteralPath $kok -Recurse -File -ErrorAction SilentlyContinue)) {
                $goreli = $f.FullName.Substring($kok.Length).TrimStart('\', '/')
                $hedef = Join-Path $hedefKok $goreli
                if ((Test-Path -LiteralPath $hedef) -and ((Get-Item -LiteralPath $hedef).Length -eq $f.Length) -and ((Get-Item -LiteralPath $hedef).LastWriteTime -ge $f.LastWriteTime)) { continue }
                $hd = Split-Path -Parent $hedef
                if (-not (Test-Path -LiteralPath $hd)) { New-Item -ItemType Directory -Path $hd -Force | Out-Null }
                try { Copy-Item -LiteralPath $f.FullName -Destination $hedef -Force } catch { Write-Log "! Panel gorsel kopyasi ($goreli): $_" }
            }
        }
    } catch {
        Write-Log "! Panel durum esitleme hatasi: $_"
    }
}

function Write-Heartbeat {
    try {
        if (((Get-Date) - $global:PanelSonNabiz).TotalSeconds -lt 60) { return }
        $global:PanelSonNabiz = Get-Date
        $kd = Split-Path -Parent $HEARTBEAT_DOSYA
        if ($kd -and -not (Test-Path -LiteralPath $kd)) { New-Item -ItemType Directory -Path $kd -Force | Out-Null }
        [System.IO.File]::WriteAllText($HEARTBEAT_DOSYA, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $script:PanelUtf8)
    } catch {}
}

# Her basarili kayitta: panelin "ekleyen" bilgisini tahmin degil KESIN bilmesi icin.
function Write-PanelKayit($userId, $userName, $sayfaAdi, $katKodu, $katEtiket, $oturum, $link, $dosyaAdi, $girisTipi) {
    try {
        $o = [ordered]@{
            zaman    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            proje    = [string]$sayfaAdi
            kategori = ([string]$katEtiket).ToUpperInvariant()
            kat_kodu = [string]$katKodu
            personel = [string]$oturum.personel
            uyeid    = [string]$oturum.uyeid
            anaid    = [string]$oturum.anaid
            tip      = [string]$oturum.tip
            link     = [string]$link
            dosya    = [string]$dosyaAdi
            tg_id    = [string]$userId
            tg_ad    = [string]$userName
            giris    = [string]$girisTipi
        }
        Write-JsonSatir $PANEL_KAYIT_DOSYA $o
    } catch { Write-Log "! kayitlar.jsonl yazilamadi: $_" }
}

# Offset sozlugu: { "<dosya adi>": <bayt> }  (panel_kuyruk_offset.json). Eski tek dosyali surumun .txt offseti de tasinir.
# Offset sozlugu: { "<dosya>": { "ofs": <bayt>, "son_id": "<son islenen satirin id'si>" } }
# son_id parmak izi: dosya ayni adla yeniden olusturulduysa (OneDrive geri yukleme, elle silme) bastan okunur.
function Get-PanelOffsetler {
    $h = @{}
    if (Test-Path -LiteralPath $PANEL_OFFSET_DOSYA) {
        try {
            $ham = [string](Get-Content -LiteralPath $PANEL_OFFSET_DOSYA -Raw)
            if ($ham.Trim()) {
                $o = $ham | ConvertFrom-Json
                foreach ($p in $o.PSObject.Properties) {
                    $v = $p.Value
                    if ($v -is [System.Management.Automation.PSCustomObject]) { $h[[string]$p.Name] = @{ ofs = [int64]$v.ofs; son_id = [string]$v.son_id } }
                    else { $h[[string]$p.Name] = @{ ofs = [int64]$v; son_id = "" } }
                }
            }
        } catch {
            # Bozuk/yarim dosya: kenara al, bastan oku (islenen kimlik listesi tekrar uygulamayi engeller)
            Write-Log "! Panel offset dosyasi okunamadi, bastan okunacak: $_"
            try { Move-Item -LiteralPath $PANEL_OFFSET_DOSYA -Destination ($PANEL_OFFSET_DOSYA + ".bozuk-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) -Force } catch {}
            $h = @{}
        }
    } else {
        $eski = Join-Path (Split-Path -Parent $PANEL_OFFSET_DOSYA) "panel_kuyruk_offset.txt"
        if (Test-Path -LiteralPath $eski) { try { $h["panel_kuyruk.jsonl"] = @{ ofs = [int64](([string](Get-Content -LiteralPath $eski -Raw)).Trim()); son_id = "" } } catch {} }
    }
    return $h
}

function Set-PanelOffsetler($h) {
    $o = [ordered]@{}
    foreach ($k in ($h.Keys | Sort-Object)) { $o[[string]$k] = [ordered]@{ ofs = [int64]$h[$k].ofs; son_id = [string]$h[$k].son_id } }
    Write-PanelAtomik $PANEL_OFFSET_DOSYA ($o | ConvertTo-Json -Depth 4)
}

# Offset'ten hemen onceki satirin id'si beklenen son_id mi? Degilse dosya degismis demektir.
function Test-PanelOffsetUyumlu($fs, [int64]$offset, [string]$sonId) {
    if ($offset -le 0 -or -not $sonId) { return $true }
    $bas = [math]::Max(0, $offset - 65536)
    $fs.Seek($bas, [System.IO.SeekOrigin]::Begin) | Out-Null
    $buf = New-Object byte[] ($offset - $bas)
    $n = $fs.Read($buf, 0, $buf.Length)
    $metin = $script:PanelUtf8.GetString($buf, 0, $n)
    if (-not $metin.EndsWith("`n")) { return $false }
    # Offset'ten geriye dogru ilk JSON satirini bul (bozuk/bos satirlar atlanir) ve id'sini karsilastir
    $satirlar = $metin.TrimEnd("`r", "`n") -split "`n"
    for ($k = $satirlar.Count - 1; $k -ge 0; $k--) {
        $t = $satirlar[$k].Trim()
        if (-not $t) { continue }
        try { $o = ConvertFrom-Json $t } catch { continue }
        if ($o -and $o.id) { return (([string]$o.id) -eq $sonId) }
    }
    return $true   # dogrulanacak satir yok
}

# Islenen is kimlikleri: ayni is (OneDrive catisma kopyasi "pc_a-DESKTOP.jsonl", yeniden yuklenen eski surum, offset sifirlanmasi) ikinci kez uygulanmaz.
# (PowerShell bir koleksiyonu fonksiyondan dondururken acar; bos HashSet $null olur. O yuzden set donmez, global degisken dogrudan kullanilir.)
function Initialize-PanelIslenenler {
    if ($null -eq $global:PanelIslenenler) {
        $global:PanelIslenenler = New-Object System.Collections.Generic.HashSet[string]
        try {
            if (Test-Path -LiteralPath $PANEL_ISLENEN_DOSYA) {
                foreach ($satir in [System.IO.File]::ReadAllLines($PANEL_ISLENEN_DOSYA)) { $t = $satir.Trim(); if ($t) { [void]$global:PanelIslenenler.Add($t) } }
            }
        } catch {}
    }
}

function Test-PanelIslendi($id) {
    Initialize-PanelIslenenler
    return $global:PanelIslenenler.Contains([string]$id)
}

function Add-PanelIslenen($id) {
    Initialize-PanelIslenenler
    [void]$global:PanelIslenenler.Add([string]$id)
    try {
        [System.IO.File]::AppendAllText($PANEL_ISLENEN_DOSYA, ([string]$id + "`r`n"), $script:PanelUtf8)
        if ($global:PanelIslenenler.Count -gt 100000) {
            # dosyayi kucult: son 50000 kimlik kalsin
            $hepsi = [System.IO.File]::ReadAllLines($PANEL_ISLENEN_DOSYA)
            $kalan = $hepsi[[math]::Max(0, $hepsi.Count - 50000)..($hepsi.Count - 1)]
            [System.IO.File]::WriteAllLines($PANEL_ISLENEN_DOSYA, $kalan, $script:PanelUtf8)
            $global:PanelIslenenler = $null
        }
    } catch {}
}

# Okunacak kuyruk dosyalari: eski tek dosya + panel_kuyruk\*.jsonl (bilgisayar basina bir dosya; OneDrive catismasi olmaz)
function Get-PanelKuyrukDosyalari {
    $liste = @()
    if (Test-Path -LiteralPath $PANEL_KUYRUK_DOSYA) { $liste += ,@{ Ad = "panel_kuyruk.jsonl"; Yol = $PANEL_KUYRUK_DOSYA } }
    if (Test-Path -LiteralPath $PANEL_KUYRUK_KLASOR) {
        foreach ($f in (Get-ChildItem -LiteralPath $PANEL_KUYRUK_KLASOR -Filter *.jsonl -File | Sort-Object Name)) {
            $liste += ,@{ Ad = ("panel_kuyruk/" + $f.Name); Yol = $f.FullName }
        }
    }
    return $liste
}

# Bir kuyruk dosyasini verilen bayttan itibaren okur; yalnizca tam satirlari isler.
# Donus: @{ Isler = @( @{ Is=<json>; SonrakiOffset=<bayt> } ... ); Degisti; SonOffset }
function Read-PanelKuyrukDosyasi($yol, [int64]$offset, [string]$sonId = "") {
    $bos = @{ Isler = @(); Degisti = $false; SonOffset = $offset }
    $fs = [System.IO.File]::Open($yol, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $uzunluk = [int64]$fs.Length
        if ($offset -gt $uzunluk) { $offset = [int64]0 }   # dosya sifirlanmis/kucultulmus
        if ($offset -gt 0 -and -not (Test-PanelOffsetUyumlu $fs $offset $sonId)) {
            Write-Log "  Panel kuyruk dosyasi degismis, bastan okunuyor: $yol"
            $offset = [int64]0
        }
        if ($offset -eq $uzunluk) { return @{ Isler = @(); Degisti = $false; SonOffset = $offset } }
        $fs.Seek($offset, [System.IO.SeekOrigin]::Begin) | Out-Null
        $buf = New-Object byte[] ($uzunluk - $offset)
        $okunan = $fs.Read($buf, 0, $buf.Length)
    } finally { $fs.Close() }
    $metin = $script:PanelUtf8.GetString($buf, 0, $okunan)
    $sonNl = $metin.LastIndexOf("`n")
    if ($sonNl -lt 0) { return $bos }
    $tam = $metin.Substring(0, $sonNl)
    $isler = @()
    $pos = [int64]$offset
    foreach ($satir in ($tam -split "`n")) {
        $pos += $script:PanelUtf8.GetByteCount($satir) + 1
        $s = $satir.Trim()
        if (-not $s) { continue }
        try { $isler += ,@{ Is = (ConvertFrom-Json $s); SonrakiOffset = $pos } }
        catch { Write-Log "! Panel kuyruk satiri okunamadi ($yol): $s" }
    }
    return @{ Isler = $isler; Degisti = $true; SonOffset = $pos }
}

function Get-PanelWorksheet($sayfaAdi) {
    if (-not $global:xlWb) { Open-Excel }
    foreach ($s in $global:xlWb.Worksheets) { if ($s.Name -eq $sayfaAdi) { return $s } }
    return $null
}

# Hucre degerini karsilastirma icin metne cevirir (sayi -> "123", tarih sayisi -> "yyyy-MM-dd HH:mm:ss").
function Get-PanelHucreMetni($ws, $satir, $sutun) {
    try {
        $hucre = $ws.Cells($satir, $sutun)
        $v = $hucre.Value2
        if ($null -eq $v) { return "" }
        if ($v -is [double]) {
            # Tarih olarak yazilmis hucre (G sutunu ya da tarih bicimli herhangi bir hucre) -> panelin gordugu metin
            $nf = ""; try { $nf = [string]$hucre.NumberFormat } catch { $nf = "" }
            if (($sutun -eq 7 -and $v -gt 20000) -or ($v -gt 20000 -and $v -lt 80000 -and $nf -match '[dmyDMY]')) {
                $dt = [DateTime]::FromOADate($v)
                return $dt.ToString("yyyy-MM-dd HH:mm:ss")
            }
            if ([math]::Floor($v) -eq $v) { return ([int64]$v).ToString() }
        }
        return ([string]$v).Trim()
    } catch { return "" }
}

# Parmak izi karsilastirmasi: panelin bildigi A,B,C,D,F (ve varsa G) degerleri satirla ayni mi?
function Test-PanelParmakIzi($ws, $satir, $parmak, [bool]$bosOlabilir) {
    if (-not $parmak) { return $bosOlabilir }
    $dolu = 0
    foreach ($a in @(@(1, 'personel'), @(2, 'uye'), @(3, 'ana'), @(4, 'tip'), @(6, 'kategori'))) {
        $prop = $parmak.PSObject.Properties[$a[1]]
        if (-not $prop) { continue }   # panel bu alani gondermemis: karsilastirma
        $beklenen = ([string]$prop.Value).Trim()
        if ($beklenen -ne (Get-PanelHucreMetni $ws $satir $a[0])) { return $false }
        if ($beklenen) { $dolu++ }
    }
    if ($dolu -eq 0 -and -not $bosOlabilir) { return $false }
    $t = ""; $tp = $parmak.PSObject.Properties['tarih']; if ($tp) { $t = ([string]$tp.Value).Trim() }
    if ($t) { $h = Get-PanelHucreMetni $ws $satir 7; if ($h -and $h -ne $t) { return $false } }
    return $true
}

function Test-PanelSatirEslesiyor($ws, $satir, $link, $parmak) {
    if ($link) {
        if ((Get-PanelHucreMetni $ws $satir 5) -ne $link) { return $false }
        # Ayni link birden fazla satirda olabilir (ayni ekran goruntusu iki uye icin): A,B,C,D,F de uymali
        return (Test-PanelParmakIzi $ws $satir $parmak $true)
    }
    return (Test-PanelParmakIzi $ws $satir $parmak $false)
}

# Panelin bildigi satir numarasi hala ayni kaydi gosteriyorsa onu kullanir; degilse E sutununda (link) arar,
# link yoksa A,B,C,D,F,G parmak iziyle tarar. 0 = bulunamadi.
# Linki (E sutunu) ya da linksizse parmak izi eslesen TUM satirlar (artan sira)
function Get-PanelAdaySatirlar($ws, $link, $parmak) {
    $link = ([string]$link).Trim()
    $sonSatir = [int](Get-ExcelLastDataRow $ws 7)
    $adaylar = @()
    if ($sonSatir -lt 2) { return @() }
    if ($link) {
        $linkli = @()
        if ($sonSatir -eq 2) {
            if (([string]$ws.Cells(2, 5).Value2).Trim() -eq $link) { $linkli += 2 }
        } else {
            $degerler = $ws.Range("E2:E$sonSatir").Value2
            $lb0 = $degerler.GetLowerBound(0); $lb1 = $degerler.GetLowerBound(1)
            for ($i = 2; $i -le $sonSatir; $i++) {
                $v = $degerler[($lb0 + $i - 2), $lb1]
                if ($null -eq $v) { continue }
                $m = if ($v -is [double]) { Get-PanelHucreMetni $ws $i 5 } else { ([string]$v).Trim() }
                if ($m -eq $link) { $linkli += $i }
            }
        }
        if ($linkli.Count -le 1) { return $linkli }
        foreach ($a in $linkli) { if (Test-PanelParmakIzi $ws $a $parmak $true) { $adaylar += $a } }
        $script:PanelLinkAdaylari = $linkli
        return $adaylar
    }
    for ($i = 2; $i -le $sonSatir; $i++) {
        if (Test-PanelParmakIzi $ws $i $parmak $false) { $adaylar += $i }
    }
    return $adaylar
}

# Panelin bildigi satir numarasi hala ayni kaydi gosteriyorsa onu kullanir; degilse E sutununda (link) arar,
# link yoksa A,B,C,D,F,G parmak iziyle tarar. Birden fazla satir uyuyorsa ipucuna en yakin TEK satir secilir;
# yine belirsizse 0 doner (yanlis satiri degistirmektense "bulunamadi" demek daha guvenli).
function Find-PanelSatir($ws, $link, $parmak, $ipucu) {
    $script:PanelBulunamadiSebep = "link / bilgiler uymuyor; satir elle degismis olabilir"
    $script:PanelLinkAdaylari = @()
    $link = ([string]$link).Trim()
    $sonSatir = [int](Get-ExcelLastDataRow $ws 7)
    if ($ipucu -and $ipucu -ge 2 -and $ipucu -le $sonSatir) {
        if (Test-PanelSatirEslesiyor $ws $ipucu $link $parmak) { return [int]$ipucu }
    }
    $adaylar = @(Get-PanelAdaySatirlar $ws $link $parmak)
    if ($adaylar.Count -eq 1) { return [int]$adaylar[0] }
    if ($adaylar.Count -eq 0) {
        if ($script:PanelLinkAdaylari.Count -gt 1) { $script:PanelBulunamadiSebep = "ayni link $($script:PanelLinkAdaylari.Count) satirda var ama bilgiler (uye/tip/kategori) hicbiriyle uymuyor; paneli yenileyip tekrar deneyin" }
        return 0
    }
    if ($ipucu -and $ipucu -gt 0) {
        $sirali = $adaylar | Sort-Object { [math]::Abs($_ - $ipucu) }
        $enYakin = [int]$sirali[0]
        $ikinci = if ($sirali.Count -gt 1) { [int]$sirali[1] } else { $null }
        if ($null -eq $ikinci -or [math]::Abs($ikinci - $ipucu) -gt [math]::Abs($enYakin - $ipucu)) { return $enYakin }
    }
    $script:PanelBulunamadiSebep = "birebir ayni $($adaylar.Count) satir var (satirlar: $($adaylar -join ', ')); hangisi oldugu belirsiz, Excel'de elle islem yapin"
    return 0
}

# Super adminin panelden gonderdigi bot komutlari (dosyalara yine BOT yazar; OneDrive'da iki yazici olmaz).
function Invoke-PanelBotIslemi($is) {
    $op = [string]$is.op
    $d = $is.deger
    $id = ""
    try { $id = ([string]$d.tg_id).Trim() } catch { $id = "" }
    switch ($op) {
        "bot_onayla" {
            if (-not $id) { return @{ durum = "hata"; mesaj = "ID bos"; satir = $null } }
            Clear-KullaniciDurumu $id | Out-Null
            if (Is-Onayli $id) { return @{ durum = "ok"; mesaj = "zaten onayli (engel/deneme/oturum temizlendi)"; satir = $null } }
            $ad = [string]$d.ad; if (-not $ad) { $ad = $id }
            Add-Onayli $id $ad
            return @{ durum = "ok"; mesaj = "onaylandi"; satir = $null }
        }
        "bot_onay_kaldir" {
            if (-not $id) { return @{ durum = "hata"; mesaj = "ID bos"; satir = $null } }
            $b = Remove-Onayli $id
            return @{ durum = "ok"; mesaj = $(if ($b) { "onay kaldirildi" } else { "onay kaydi yoktu" }); satir = $null }
        }
        "bot_engelle" {
            if (-not $id) { return @{ durum = "hata"; mesaj = "ID bos"; satir = $null } }
            $sebep = [string]$d.sebep; if (-not $sebep) { $sebep = "panel" }
            Add-Engellenen $id ([string]$d.ad) $sebep
            return @{ durum = "ok"; mesaj = "engellendi"; satir = $null }
        }
        "bot_engel_kaldir" {
            if (-not $id) { return @{ durum = "hata"; mesaj = "ID bos"; satir = $null } }
            $b = Clear-KullaniciDurumu $id
            $bildirim = $false
            try { $bildirim = Send-EngelKaldirildiBildirim $id } catch { $bildirim = $false }
            return @{ durum = "ok"; mesaj = ($(if ($b) { "engel kaldirildi" } else { "engel kaydi yoktu; deneme/oturum sifirlandi" }) + $(if ($bildirim) { ", kullaniciya bildirildi" } else { "" })); satir = $null }
        }
        "bot_bakim" {
            Set-MaintenanceMode ([bool]$d.acik)
            return @{ durum = "ok"; mesaj = $(if ($d.acik) { "bakim modu ACIK" } else { "bakim modu kapali" }); satir = $null }
        }
        "bot_gyazo_bakim" {
            Set-GyazoBakim ([bool]$d.acik)
            return @{ durum = "ok"; mesaj = $(if ($d.acik) { "gyazo bakim ACIK (diske kayit)" } else { "gyazo acik" }); satir = $null }
        }
        "bot_oturum_temizle" {
            if ($id) { Remove-Oturum $id; return @{ durum = "ok"; mesaj = "oturum silindi: $id"; satir = $null } }
            Save-Oturumlar @{}
            return @{ durum = "ok"; mesaj = "tum oturumlar silindi"; satir = $null }
        }
        "bot_kategori_ekle" {
            $hata = Add-OrUpdate-Kategori ([string]$d.code) ([string]$d.label) ([string]$d.mode)
            if ($hata) { return @{ durum = "hata"; mesaj = [string]$hata; satir = $null } }
            return @{ durum = "ok"; mesaj = "kategori kaydedildi: $($d.code)"; satir = $null }
        }
        "bot_kategori_sil" {
            $b = Remove-Kategori ([string]$d.code)
            return @{ durum = $(if ($b) { "ok" } else { "hata" }); mesaj = $(if ($b) { "kategori silindi" } else { "kategori bulunamadi" }); satir = $null }
        }
        "bot_yedek" {
            $y = Invoke-Backup $true
            return @{ durum = "ok"; mesaj = "yedek alindi: $y"; satir = $null }
        }
        default { return @{ durum = "hata"; mesaj = "bilinmeyen bot islemi: $op"; satir = $null } }
    }
}

function Invoke-PanelIslem($is) {
    if (([string]$is.op).StartsWith("bot_")) { return (Invoke-PanelBotIslemi $is) }
    $sayfa = [string]$is.sayfa
    $ws = Get-PanelWorksheet $sayfa
    if (-not $ws) { return @{ durum = "bulunamadi"; mesaj = "Sayfa yok: $sayfa"; satir = $null } }
    $op = [string]$is.op
    $deger = $is.deger
    $ipucu = 0
    try { if ($deger -and $deger.satir) { $ipucu = [int]$deger.satir } } catch { $ipucu = 0 }
    if ($op -eq "ekle") {
        # Panelden "geri al": satir hala duruyorsa (silme uygulanmamis / bulunamamis) ikinci satir ACILMAZ, sadece KT/I/J yazilir.
        $degerler = @()
        foreach ($d in @($deger.degerler)) { $degerler += [string]$d }
        if ($degerler.Count -lt 5) { return @{ durum = "hata"; mesaj = "ekle: eksik deger"; satir = $null } }
        $mevcut = @(Get-PanelAdaySatirlar $ws $degerler[4] $is.parmak)
        if ($mevcut.Count -gt 0) {
            $yeni = [int]$mevcut[$mevcut.Count - 1]
            $mesaj = "satir zaten vardi (satir $yeni), yeniden eklenmedi"
        } else {
            Add-ExcelRow $sayfa $degerler[0..6] $degerler[4]
            $sonra = @(Get-PanelAdaySatirlar $ws $degerler[4] $is.parmak)
            if ($sonra.Count -eq 0) { return @{ durum = "hata"; mesaj = "satir eklendi ama bulunamadi"; satir = $null } }
            $yeni = [int]$sonra[$sonra.Count - 1]   # en alttaki = yeni eklenen
            $mesaj = "eklendi"
        }
        $ws.Cells($yeni, 8).Value2 = [bool]$deger.kt
        foreach ($ek in @(@(9, 'gorsel2'), @(10, 'aciklama'))) {
            $prop = $deger.PSObject.Properties[$ek[1]]
            if ($prop -and ([string]$prop.Value) -ne "") { $h = $ws.Cells($yeni, $ek[0]); $h.NumberFormat = "@"; $h.Value2 = (Protect-ExcelValue ([string]$prop.Value)) }
        }
        $global:xlWb.Save()
        return @{ durum = "ok"; mesaj = $mesaj; satir = $yeni }
    }
    $satir = Find-PanelSatir $ws $is.link $is.parmak $ipucu
    if ($satir -lt 2) { return @{ durum = "bulunamadi"; mesaj = "Excel'de satir bulunamadi ($($script:PanelBulunamadiSebep))"; satir = $null } }
    switch ($op) {
        "kt" {
            $ws.Cells($satir, 8).Value2 = [bool]$deger.kt
        }
        "duzenle" {
            # Yalnizca panelin GONDERDIGI alanlar yazilir; digerleri Excel'de ne ise oyle kalir (baska adminin duzeltmesi ezilmez).
            $yazildi = 0
            foreach ($k in @(@(1, 'personel'), @(2, 'uye'), @(3, 'ana'), @(4, 'tip'), @(6, 'kategori'), @(10, 'aciklama'))) {
                $prop = $deger.PSObject.Properties[$k[1]]
                if (-not $prop) { continue }
                $hucre = $ws.Cells($satir, $k[0])
                $hucre.NumberFormat = "@"
                $v = [string]$prop.Value
                if ($k[0] -eq 6) { $v = $v.ToUpperInvariant() }
                $hucre.Value2 = (Protect-ExcelValue $v)
                $yazildi++
            }
            if ($yazildi -eq 0) { return @{ durum = "hata"; mesaj = "duzenle: degisecek alan yok"; satir = $satir } }
        }
        "sil" {
            $ws.Rows($satir).Delete() | Out-Null
        }
        default { return @{ durum = "hata"; mesaj = "bilinmeyen islem: $op"; satir = $null } }
    }
    $global:xlWb.Save()
    return @{ durum = "ok"; mesaj = $op; satir = $(if ($op -eq "sil") { $null } else { $satir }) }
}

# Ana dongude cagrilir: en fazla PANEL_KUYRUK_SN saniyede bir tum kuyruk dosyalarina bakar, her isi uygular, sonucunu yazar.
function Process-PanelKuyrugu {
    try {
        if (((Get-Date) - $global:PanelSonKontrol).TotalSeconds -lt $PANEL_KUYRUK_SN) { return }
        $global:PanelSonKontrol = Get-Date
        $dosyalar = Get-PanelKuyrukDosyalari
        if ($dosyalar.Count -eq 0) { return }
        $uygulanan = 0
        $offsetler = Get-PanelOffsetler
        foreach ($dosya in $dosyalar) {
            $ad = [string]$dosya.Ad
            $offset = [int64]0; $sonId = ""
            if ($offsetler.ContainsKey($ad)) { $offset = [int64]$offsetler[$ad].ofs; $sonId = [string]$offsetler[$ad].son_id }
            $okuma = $null
            try { $okuma = Read-PanelKuyrukDosyasi $dosya.Yol $offset $sonId } catch { Write-Log "! Panel kuyrugu okunamadi ($ad): $_"; continue }
            if (-not $okuma.Degisti) { continue }
            $dosyaTamam = $true
            foreach ($kalem in @($okuma.Isler)) {
                $is = $kalem.Is
                if ($is -and $is.id -and (Test-PanelIslendi $is.id)) {
                    Write-Log "  Panel islemi atlandi (daha once islendi): $($is.op) $($is.id)"
                } elseif ($is -and $is.id) {
                    $sonuc = $null
                    try {
                        $sonuc = Invoke-PanelIslem $is
                    } catch {
                        $sonuc = @{ durum = "hata"; mesaj = [string]$_; satir = $null }
                        Write-Log "! Panel islemi hatasi ($($is.op) [$($is.sayfa)]): $_"
                        if (([string]$_) -match '0x800706BA|0x800706BE|0x80010108|RPC') {
                            try { Close-Excel } catch {}
                            Start-Sleep -Seconds 3
                            try { Open-Excel } catch {}
                        }
                    }
                    Write-Log "  Panel islemi: $($is.op) [$($is.sayfa)] $($is.kullanici) -> $($sonuc.durum) $($sonuc.mesaj)"
                    # Sonuc satiri yazilmadan is "islendi" sayilmaz; OneDrive dosyayi kisa sure kilitlerse birkac kez denenir.
                    $yazildi = $false
                    for ($deneme = 1; $deneme -le 5 -and -not $yazildi; $deneme++) {
                        try {
                            Write-JsonSatir $PANEL_SONUC_DOSYA ([ordered]@{ id = [string]$is.id; durum = [string]$sonuc.durum; mesaj = [string]$sonuc.mesaj; satir = $sonuc.satir; op = [string]$is.op; zaman = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') })
                            $yazildi = $true
                        } catch { Start-Sleep -Milliseconds 300 }
                    }
                    if (-not $yazildi) {
                        # Bu is bir sonraki turda yeniden denenir (offset ilerletilmez); KT/duzenle tekrarina dayanikli.
                        Write-Log "! Panel sonucu yazilamadi ($($is.op) $($is.id)); sonraki turda tekrar denenecek"
                        $dosyaTamam = $false
                        break
                    }
                    Add-PanelIslenen $is.id
                    $uygulanan++
                }
                # Her kalemden sonra offset + son islenen id (parmak izi)
                $offsetler[$ad] = @{ ofs = [int64]$kalem.SonrakiOffset; son_id = $(if ($is -and $is.id) { [string]$is.id } else { $sonId }) }
                if ($is -and $is.id) { $sonId = [string]$is.id }
                Set-PanelOffsetler $offsetler
            }
            if ($dosyaTamam) {
                # Okunan tum tam satirlar (bozuk/bos olanlar dahil) gecildi; ayni satir tekrar tekrar okunmasin.
                $offsetler[$ad] = @{ ofs = [int64]$okuma.SonOffset; son_id = $sonId }
                Set-PanelOffsetler $offsetler
            }
        }
        if ($uygulanan -gt 0) { Update-PanelExcelKopyasi $true }   # panel kendi degisikligini hemen gorsun
    } catch {
        Write-Log "! Panel kuyrugu islenemedi: $_"
    }
}

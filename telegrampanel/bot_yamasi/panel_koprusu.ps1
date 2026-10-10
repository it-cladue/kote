# ==================== WEB PANELI KOPRUSU ====================
# Web paneli (telegrampanel) Excel'e dogrudan yazmaz. Panelde yapilan onay (KT), duzenleme, silme ve geri alma
# islemleri panel_kuyruk.jsonl dosyasina satir satir eklenir; bot bu dosyayi dongude okur, KENDI Excel
# baglantisiyla uygular ve sonucu panel_kuyruk_sonuc.jsonl'a yazar. Boylece Excel'e tek yazan yine bottur.
# Ek olarak: her kayitta kayitlar.jsonl'a "kim ekledi, hangi link" satiri; 60 sn'de bir heartbeat.txt (bot canli mi).
# Panel kurulu degilse bu blok hicbir sey yapmaz (kuyruk dosyasi yoksa dongu aninda doner).
$PANEL_KUYRUK_DOSYA = [string](Get-ConfigValue "PANEL_KUYRUK_DOSYA" (Join-Base "panel_kuyruk.jsonl"))
$PANEL_SONUC_DOSYA  = [string](Get-ConfigValue "PANEL_SONUC_DOSYA" (Join-Base "panel_kuyruk_sonuc.jsonl"))
$PANEL_KUYRUK_KLASOR = [string](Get-ConfigValue "PANEL_KUYRUK_KLASOR" (Join-Base "panel_kuyruk"))   # her bilgisayar kendi dosyasina yazar
$PANEL_OFFSET_DOSYA = [string](Get-ConfigValue "PANEL_OFFSET_DOSYA" (Join-Base "panel_kuyruk_offset.json"))
$PANEL_ISLENEN_DOSYA = [string](Get-ConfigValue "PANEL_ISLENEN_DOSYA" (Join-Base "panel_kuyruk_islenen.txt"))   # islenen is kimlikleri (OneDrive catisma kopyasi / tekrar okuma korumasi)
$global:PanelIslenenler = $null
$PANEL_KAYIT_DOSYA  = [string](Get-ConfigValue "PANEL_KAYIT_DOSYA" (Join-Base "kayitlar.jsonl"))
$HEARTBEAT_DOSYA    = [string](Get-ConfigValue "HEARTBEAT_DOSYA" (Join-Base "heartbeat.txt"))
$PANEL_KUYRUK_SN    = [int](Get-ConfigValue "PANEL_KUYRUK_SN" 5)
$global:PanelSonKontrol = [datetime]::MinValue
$global:PanelSonNabiz   = [datetime]::MinValue
$script:PanelUtf8 = New-Object System.Text.UTF8Encoding $false
# --- PANEL FONKSIYONLARI ---

# ==================== WEB PANELI KOPRUSU: FONKSIYONLAR ====================
function Write-JsonSatir($dosya, $nesne) {
    # BOM'suz UTF-8, CRLF satir sonu; panel (Python) satir satir okur.
    $json = ($nesne | ConvertTo-Json -Compress -Depth 6)
    [System.IO.File]::AppendAllText($dosya, ($json + "`r`n"), $script:PanelUtf8)
}

function Write-Heartbeat {
    try {
        if (((Get-Date) - $global:PanelSonNabiz).TotalSeconds -lt 60) { return }
        $global:PanelSonNabiz = Get-Date
        [System.IO.File]::WriteAllText($HEARTBEAT_DOSYA, (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $script:PanelUtf8)
    } catch {}
}

# Her basarili kayitta: panelin "ekleyen" bilgisini tahmin degil KESIN bilmesi icin.
function Write-PanelKayit($userId, $userName, $sayfaAdi, $katKodu, $katEtiket, $oturum, $link, $dosyaAdi, $girisTipi) {
    try {
        $o = [ordered]@{
            zaman    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
            proje    = [string]$sayfaAdi
            kategori = ([string]$katEtiket).ToUpper()
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
function Get-PanelOffsetler {
    $h = @{}
    try {
        if (Test-Path -LiteralPath $PANEL_OFFSET_DOSYA) {
            $o = (Get-Content -LiteralPath $PANEL_OFFSET_DOSYA -Raw) | ConvertFrom-Json
            foreach ($p in $o.PSObject.Properties) { $h[[string]$p.Name] = [int64]$p.Value }
        } else {
            $eski = Join-Path (Split-Path -Parent $PANEL_OFFSET_DOSYA) "panel_kuyruk_offset.txt"
            if (Test-Path -LiteralPath $eski) { $h["panel_kuyruk.jsonl"] = [int64](([string](Get-Content -LiteralPath $eski -Raw)).Trim()) }
        }
    } catch { $h = @{} }
    return $h
}

function Set-PanelOffsetler($h) {
    $o = [ordered]@{}
    foreach ($k in ($h.Keys | Sort-Object)) { $o[[string]$k] = [int64]$h[$k] }
    [System.IO.File]::WriteAllText($PANEL_OFFSET_DOSYA, ($o | ConvertTo-Json), $script:PanelUtf8)
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
        if ($global:PanelIslenenler.Count -gt 20000) {
            # dosyayi kucult: son 10000 kimlik kalsin
            $hepsi = [System.IO.File]::ReadAllLines($PANEL_ISLENEN_DOSYA)
            $kalan = $hepsi[[math]::Max(0, $hepsi.Count - 10000)..($hepsi.Count - 1)]
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
function Read-PanelKuyrukDosyasi($yol, [int64]$offset) {
    $bos = @{ Isler = @(); Degisti = $false; SonOffset = $offset }
    $fs = [System.IO.File]::Open($yol, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $uzunluk = [int64]$fs.Length
        if ($offset -gt $uzunluk) { $offset = [int64]0 }   # dosya sifirlanmis/kucultulmus
        if ($offset -eq $uzunluk) { return $bos }
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
        $v = $ws.Cells($satir, $sutun).Value2
        if ($null -eq $v) { return "" }
        if ($v -is [double]) {
            if ($sutun -eq 7 -and $v -gt 20000) { return ([DateTime]::FromOADate($v)).ToString("yyyy-MM-dd HH:mm:ss") }
            if ([math]::Floor($v) -eq $v) { return ([int64]$v).ToString() }
        }
        return ([string]$v).Trim()
    } catch { return "" }
}

function Test-PanelSatirEslesiyor($ws, $satir, $link, $parmak) {
    if ($link) {
        if ((Get-PanelHucreMetni $ws $satir 5) -ne $link) { return $false }
        if ($parmak -and $parmak.personel -and ((Get-PanelHucreMetni $ws $satir 1) -ne ([string]$parmak.personel).Trim())) { return $false }
        return $true
    }
    if (-not $parmak) { return $false }
    $dolu = 0
    foreach ($a in @(@(1, 'personel'), @(2, 'uye'), @(3, 'ana'), @(4, 'tip'), @(6, 'kategori'))) {
        $beklenen = ([string]$parmak.($a[1])).Trim()
        if ($beklenen -ne (Get-PanelHucreMetni $ws $satir $a[0])) { return $false }
        if ($beklenen) { $dolu++ }
    }
    if ($dolu -eq 0) { return $false }
    $t = ([string]$parmak.tarih).Trim()
    if ($t) { $h = Get-PanelHucreMetni $ws $satir 7; if ($h -and $h -ne $t) { return $false } }
    return $true
}

# Panelin bildigi satir numarasi hala ayni kaydi gosteriyorsa onu kullanir; degilse E sutununda (link) arar,
# link yoksa A,B,C,D,F,G parmak iziyle tarar. 0 = bulunamadi.
function Find-PanelSatir($ws, $link, $parmak, $ipucu) {
    $link = ([string]$link).Trim()
    $sonSatir = [int](Get-ExcelLastDataRow $ws 7)
    if ($ipucu -and $ipucu -ge 2 -and $ipucu -le $sonSatir) {
        if (Test-PanelSatirEslesiyor $ws $ipucu $link $parmak) { return [int]$ipucu }
    }
    if ($sonSatir -lt 2) { return 0 }
    if ($link) {
        $adaylar = @()
        if ($sonSatir -eq 2) {
            if (([string]$ws.Cells(2, 5).Value2).Trim() -eq $link) { $adaylar += 2 }
        } else {
            $degerler = $ws.Range("E2:E$sonSatir").Value2
            $lb0 = $degerler.GetLowerBound(0); $lb1 = $degerler.GetLowerBound(1)
            for ($i = 2; $i -le $sonSatir; $i++) {
                $v = $degerler[($lb0 + $i - 2), $lb1]
                if ($null -ne $v -and ([string]$v).Trim() -eq $link) { $adaylar += $i }
            }
        }
        if ($adaylar.Count -eq 1) { return [int]$adaylar[0] }
        if ($adaylar.Count -gt 1) {
            foreach ($a in $adaylar) { if (Test-PanelSatirEslesiyor $ws $a $link $parmak) { return [int]$a } }
            return [int]$adaylar[0]
        }
        return 0
    }
    for ($i = 2; $i -le $sonSatir; $i++) {
        if (Test-PanelSatirEslesiyor $ws $i "" $parmak) { return [int]$i }
    }
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
        # Panelden "geri al": satir Excel'e yeniden eklenir (A..G), istenirse KT isaretlenir.
        $degerler = @()
        foreach ($d in @($deger.degerler)) { $degerler += [string]$d }
        if ($degerler.Count -lt 5) { return @{ durum = "hata"; mesaj = "ekle: eksik deger"; satir = $null } }
        Add-ExcelRow $sayfa $degerler $degerler[4]
        $yeni = Find-PanelSatir $ws $degerler[4] $is.parmak 0
        if ($yeni -gt 0 -and $deger.kt) { $ws.Cells($yeni, 8).Value2 = $true; $global:xlWb.Save() }
        return @{ durum = "ok"; mesaj = "eklendi"; satir = $(if ($yeni -gt 0) { $yeni } else { $null }) }
    }
    $satir = Find-PanelSatir $ws $is.link $is.parmak $ipucu
    if ($satir -lt 2) { return @{ durum = "bulunamadi"; mesaj = "Excel'de satir bulunamadi (link / bilgiler uymuyor; satir elle degismis olabilir)"; satir = $null } }
    switch ($op) {
        "kt" {
            $ws.Cells($satir, 8).Value2 = [bool]$deger.kt
        }
        "duzenle" {
            $yaz = @{ 1 = $deger.personel; 2 = $deger.uye; 3 = $deger.ana; 4 = $deger.tip; 6 = $deger.kategori }
            foreach ($k in @(1, 2, 3, 4, 6)) {
                $hucre = $ws.Cells($satir, $k)
                $hucre.NumberFormat = "@"
                $v = [string]$yaz[$k]
                if ($k -eq 6) { $v = $v.ToUpper() }
                $hucre.Value2 = (Protect-ExcelValue $v)
            }
            if ($null -ne $deger.aciklama) {
                $hucre = $ws.Cells($satir, 10)
                $hucre.NumberFormat = "@"
                $hucre.Value2 = (Protect-ExcelValue ([string]$deger.aciklama))
            }
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
        $offsetler = Get-PanelOffsetler
        foreach ($dosya in $dosyalar) {
            $ad = [string]$dosya.Ad
            $offset = [int64]0
            if ($offsetler.ContainsKey($ad)) { $offset = [int64]$offsetler[$ad] }
            $okuma = $null
            try { $okuma = Read-PanelKuyrukDosyasi $dosya.Yol $offset } catch { Write-Log "! Panel kuyrugu okunamadi ($ad): $_"; continue }
            if (-not $okuma.Degisti) { continue }
            foreach ($kalem in @($okuma.Isler)) {
                $is = $kalem.Is
                if ($is -and $is.id -and (Test-PanelIslendi $is.id)) {
                    Write-Log "  Panel islemi atlandi (daha once islendi): $($is.op) $($is.id)"
                } elseif ($is -and $is.id) {
                    Add-PanelIslenen $is.id
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
                    try {
                        Write-JsonSatir $PANEL_SONUC_DOSYA ([ordered]@{ id = [string]$is.id; durum = [string]$sonuc.durum; mesaj = [string]$sonuc.mesaj; satir = $sonuc.satir; op = [string]$is.op; zaman = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') })
                    } catch { Write-Log "! Panel sonucu yazilamadi: $_" }
                }
                # Her kalemden sonra offset: bot kesilirse en fazla 1 islem tekrar denenir (KT/duzenle tekrarina dayanikli).
                $offsetler[$ad] = [int64]$kalem.SonrakiOffset
                Set-PanelOffsetler $offsetler
            }
            # Okunan tum tam satirlar (bozuk/bos olanlar dahil) gecildi; ayni satir tekrar tekrar okunmasin.
            $offsetler[$ad] = [int64]$okuma.SonOffset
            Set-PanelOffsetler $offsetler
        }
    } catch {
        Write-Log "! Panel kuyrugu islenemedi: $_"
    }
}

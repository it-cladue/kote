# ==================== WEB PANELI KOPRUSU ====================
# Web paneli (telegrampanel) Excel'e dogrudan yazmaz. Panelde yapilan onay (KT), duzenleme, silme ve geri alma
# islemleri panel_kuyruk.jsonl dosyasina satir satir eklenir; bot bu dosyayi dongude okur, KENDI Excel
# baglantisiyla uygular ve sonucu panel_kuyruk_sonuc.jsonl'a yazar. Boylece Excel'e tek yazan yine bottur.
# Ek olarak: her kayitta kayitlar.jsonl'a "kim ekledi, hangi link" satiri; 60 sn'de bir heartbeat.txt (bot canli mi).
# Panel kurulu degilse bu blok hicbir sey yapmaz (kuyruk dosyasi yoksa dongu aninda doner).
$PANEL_KUYRUK_DOSYA = [string](Get-ConfigValue "PANEL_KUYRUK_DOSYA" (Join-Base "panel_kuyruk.jsonl"))
$PANEL_SONUC_DOSYA  = [string](Get-ConfigValue "PANEL_SONUC_DOSYA" (Join-Base "panel_kuyruk_sonuc.jsonl"))
$PANEL_OFFSET_DOSYA = [string](Get-ConfigValue "PANEL_OFFSET_DOSYA" (Join-Base "panel_kuyruk_offset.txt"))
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

# Kuyruk dosyasini son okunan bayttan itibaren okur; yalnizca tam satirlari isler.
# Donus: @{ Isler = @( @{ Is=<json nesnesi>; SonrakiOffset=<bayt> } ... ); Degisti = $true/$false }
function Read-PanelKuyruk {
    $bos = @{ Isler = @(); Degisti = $false; SonOffset = [int64]0 }
    if (-not (Test-Path -LiteralPath $PANEL_KUYRUK_DOSYA)) { return $bos }
    $offset = [int64]0
    try {
        if (Test-Path -LiteralPath $PANEL_OFFSET_DOSYA) { $offset = [int64](([string](Get-Content -LiteralPath $PANEL_OFFSET_DOSYA -Raw)).Trim()) }
    } catch { $offset = [int64]0 }
    $fs = [System.IO.File]::Open($PANEL_KUYRUK_DOSYA, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
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
        catch { Write-Log "! Panel kuyruk satiri okunamadi: $s" }
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

function Invoke-PanelIslem($is) {
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

# Ana dongude cagrilir: en fazla PANEL_KUYRUK_SN saniyede bir kuyruga bakar, her isi uygular, sonucunu yazar.
function Process-PanelKuyrugu {
    try {
        if (((Get-Date) - $global:PanelSonKontrol).TotalSeconds -lt $PANEL_KUYRUK_SN) { return }
        $global:PanelSonKontrol = Get-Date
        $okuma = Read-PanelKuyruk
        if (-not $okuma.Degisti) { return }
        foreach ($kalem in @($okuma.Isler)) {
            $is = $kalem.Is
            if ($is -and $is.id) {
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
            # Her kalemden sonra offset: bot capraz kesilirse en fazla 1 islem tekrar denenir (KT/duzenle tekrarina dayanikli).
            [System.IO.File]::WriteAllText($PANEL_OFFSET_DOSYA, [string]$kalem.SonrakiOffset, $script:PanelUtf8)
        }
        # Okunan tum tam satirlar (bozuk/bos olanlar dahil) gecildi; ayni satir tekrar tekrar okunmasin.
        [System.IO.File]::WriteAllText($PANEL_OFFSET_DOSYA, [string]$okuma.SonOffset, $script:PanelUtf8)
    } catch {
        Write-Log "! Panel kuyrugu islenemedi: $_"
    }
}

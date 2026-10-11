# -*- coding: utf-8 -*-
"""telebot.ps1'e web paneli koprusunu ekler (tek seferlik, geri alinabilir; yedek .panel_oncesi.bak).
Kullanim: python uygula.py <telebot.ps1 yolu>
Eklenen 4 parca: (1) ayar satirlari, (2) fonksiyonlar, (3) kayit sonrasi kayitlar.jsonl satiri, (4) ana dongude kuyruk+nabiz."""
import sys, os, re, shutil

KOK = os.path.dirname(os.path.abspath(__file__))
ANCHOR_AYAR = '$EXCEL_MOD_DOSYA  = [string](Get-ConfigValue "EXCEL_MOD_DOSYA" (Join-Base "excel_yazma_modu.txt"))'
ANCHOR_FONK = '# ==================== CALLBACK ===================='
ANCHOR_KAYIT = '        Register-KullaniciKayit $userId $userName $cb.from.first_name $sayfaAdi $oturum.kategori $katLabel'
ANCHOR_DONGU = '        Start-Sleep -Milliseconds $NORMAL_SLEEP_MS'
EK_KAYIT = '        Write-PanelKayit $userId $userName $sayfaAdi $oturum.kategori $katLabel $oturum $gyazoUrl $kayitDosyaAdi $girisTipi'
EK_DONGU = '        try { Process-PanelKuyrugu; Update-PanelExcelKopyasi; Sync-PanelDurumu; Write-Heartbeat } catch { Write-Log "! Panel koprusu: $_" }'
EK_DONGU_ESKI = ['        try { Process-PanelKuyrugu; Write-Heartbeat } catch { Write-Log "! Panel koprusu: $_" }',
                 '        try { Process-PanelKuyrugu; Update-PanelExcelKopyasi; Write-Heartbeat } catch { Write-Log "! Panel koprusu: $_" }']


def kopru_surumu(metin):
    m = re.search(r"WEB PANELI KOPRUSU \(surum (\d+)\)", metin)
    return int(m.group(1)) if m else (1 if "WEB PANELI KOPRUSU" in metin else 0)


def kaldir(m):
    """Daha once eklenmis kopru parcalarini (herhangi bir surum) soker; geriye temiz bot kalir."""
    # 1) ayar blogu: baslik satirindan AYAR SONU isaretine (yoksa $script:PanelUtf8 satirina) kadar
    i = m.find("# ==================== WEB PANELI KOPRUSU")
    if i >= 0:
        j = m.find("# --- WEB PANELI KOPRUSU: AYAR SONU ---\n", i)
        if j >= 0:
            j += len("# --- WEB PANELI KOPRUSU: AYAR SONU ---\n")
        else:
            j = m.find("$script:PanelUtf8 = New-Object System.Text.UTF8Encoding $false\n", i)
            if j < 0:
                raise SystemExit("Eski kopru ayar blogunun sonu bulunamadi")
            j += len("$script:PanelUtf8 = New-Object System.Text.UTF8Encoding $false\n")
        m = m[:i] + m[j:]
    # 2) fonksiyon blogu: FONKSIYONLAR basligindan CALLBACK capasina kadar
    i = m.find("# ==================== WEB PANELI KOPRUSU: FONKSIYONLAR")
    if i >= 0:
        j = m.find(ANCHOR_FONK + "\n", i)
        if j < 0:
            raise SystemExit("Eski kopru fonksiyon blogunun sonu bulunamadi")
        m = m[:i].rstrip("\n") + "\n\n" + m[j:]
    # 3-4) tek satirlik eklemeler (eski surumlerin satirlari dahil)
    m = m.replace(EK_KAYIT + "\n", "").replace(EK_DONGU + "\n", "")
    for e in EK_DONGU_ESKI:
        m = m.replace(e + "\n", "")
    return m


def uygula(yol):
    ham = open(yol, "rb").read()
    bom = ham.startswith(b"\xef\xbb\xbf")
    metin = ham.decode("utf-8-sig")
    crlf = "\r\n" in metin
    blok = open(os.path.join(KOK, "panel_koprusu.ps1"), encoding="utf-8-sig").read().replace("\r\n", "\n")
    yeni_surum = kopru_surumu(blok)
    eski_surum = kopru_surumu(metin)
    ayar, fonk = blok.split("# --- PANEL FONKSIYONLARI ---\n", 1)
    m = metin.replace("\r\n", "\n")
    if eski_surum and ayar in m and fonk.rstrip("\n") in m and EK_KAYIT in m and EK_DONGU in m:
        return f"zaten uygulanmis (surum {yeni_surum}, blok birebir ayni)"
    if eski_surum:
        m = kaldir(m)
    for a, adi in ((ANCHOR_AYAR, "ayar"), (ANCHOR_FONK, "fonksiyon"), (ANCHOR_KAYIT, "kayit"), (ANCHOR_DONGU, "dongu")):
        n = m.count(a + "\n")
        if n != 1:
            raise SystemExit(f"Capa bulunamadi veya birden fazla ({adi}: {n})")
    m = m.replace(ANCHOR_AYAR + "\n", ANCHOR_AYAR + "\n" + ayar.rstrip("\n") + "\n", 1)
    m = m.replace(ANCHOR_FONK + "\n", fonk.rstrip("\n") + "\n\n" + ANCHOR_FONK + "\n", 1)
    m = m.replace(ANCHOR_KAYIT + "\n", ANCHOR_KAYIT + "\n" + EK_KAYIT + "\n", 1)
    m = m.replace(ANCHOR_DONGU + "\n", EK_DONGU + "\n" + ANCHOR_DONGU + "\n", 1)
    if crlf:
        m = m.replace("\n", "\r\n")
    shutil.copy2(yol, yol + ".panel_oncesi.bak")
    with open(yol, "wb") as f:
        f.write((b"\xef\xbb\xbf" if bom else b"") + m.encode("utf-8"))
    return f"yukseltildi (surum {eski_surum} -> {yeni_surum})" if eski_surum else f"uygulandi (surum {yeni_surum})"


def kopru_ayni_mi(bot_yolu):
    """Bottaki kopru bloklari panel_koprusu.ps1 ile birebir ayni mi? (test icin)"""
    metin = open(bot_yolu, encoding="utf-8-sig").read().replace("\r\n", "\n")
    blok = open(os.path.join(KOK, "panel_koprusu.ps1"), encoding="utf-8-sig").read().replace("\r\n", "\n")
    ayar, fonk = blok.split("# --- PANEL FONKSIYONLARI ---\n", 1)
    return ayar in metin and fonk.rstrip("\n") in metin and EK_KAYIT in metin and EK_DONGU in metin


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(uygula(sys.argv[1]))

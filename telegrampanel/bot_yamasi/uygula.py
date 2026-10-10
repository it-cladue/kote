# -*- coding: utf-8 -*-
"""telebot.ps1'e web paneli koprusunu ekler (tek seferlik, geri alinabilir; yedek .panel_oncesi.bak).
Kullanim: python uygula.py <telebot.ps1 yolu>
Eklenen 4 parca: (1) ayar satirlari, (2) fonksiyonlar, (3) kayit sonrasi kayitlar.jsonl satiri, (4) ana dongude kuyruk+nabiz."""
import sys, os, shutil

KOK = os.path.dirname(os.path.abspath(__file__))
ANCHOR_AYAR = '$EXCEL_MOD_DOSYA  = [string](Get-ConfigValue "EXCEL_MOD_DOSYA" (Join-Base "excel_yazma_modu.txt"))'
ANCHOR_FONK = '# ==================== CALLBACK ===================='
ANCHOR_KAYIT = '        Register-KullaniciKayit $userId $userName $cb.from.first_name $sayfaAdi $oturum.kategori $katLabel'
ANCHOR_DONGU = '        Start-Sleep -Milliseconds $NORMAL_SLEEP_MS'
EK_KAYIT = '        Write-PanelKayit $userId $userName $sayfaAdi $oturum.kategori $katLabel $oturum $gyazoUrl $kayitDosyaAdi $girisTipi'
EK_DONGU = '        try { Process-PanelKuyrugu; Write-Heartbeat } catch { Write-Log "! Panel koprusu: $_" }'


def uygula(yol):
    ham = open(yol, "rb").read()
    bom = ham.startswith(b"\xef\xbb\xbf")
    metin = ham.decode("utf-8-sig")
    crlf = "\r\n" in metin
    if "WEB PANELI KOPRUSU" in metin:
        return "zaten uygulanmis"
    blok = open(os.path.join(KOK, "panel_koprusu.ps1"), encoding="utf-8-sig").read().replace("\r\n", "\n")
    ayar, fonk = blok.split("# --- PANEL FONKSIYONLARI ---\n", 1)
    m = metin.replace("\r\n", "\n")
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
    return "uygulandi"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(uygula(sys.argv[1]))

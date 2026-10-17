# -*- coding: utf-8 -*-
import os
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest
from PIL import Image

# Bazı pytest eklentileri kökü sys.path'e koymaz; test bu depoda tek başına da
# çalışabilsin.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, excel_oku, ice_aktar
from app.gorsel import GorselCozucu, arsiv_tara


GID1 = "0123456789abcdef0123456789abcdef"
GID2 = "fedcba9876543210fedcba9876543210"
GID3 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
GID4 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _xlsx_sparse(yol):
    """1048576 boyut bildiren fakat yalnız üç XML satırı olan test çalışma kitabı.

    Eski openpyxl dikdörtgen döngüsü son H hücresi yüzünden bir milyon satır
    gezerdi. Yeni XML tarayıcı yalnız gerçek XML satırlarını okur.
    """
    base = str(yol) + ".base"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "pp"  # küçük harf giriş adı normalize edilmelidir
    wb.create_sheet("HATALI")
    wb.save(base)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    def c(ref, value, typ="inlineStr"):
        if typ == "b":
            return f'<c r="{ref}" t="b"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    baslik = ["Personel", "Uye", "Ana", "Tip", "Link", "Kategori", "Tarih", "KT", "Gorsel2", "Aciklama", "Ek"]
    r1 = "".join(c(f"{openpyxl.utils.get_column_letter(i)}1", v) for i, v in enumerate(baslik, 1))
    r2 = "".join([
        c("A2", "p1"), c("B2", "u1"), c("C2", "a1"), c("D2", "t1"),
        c("E2", f"https://gyazo.com/{GID1}"), c("F2", "ark"), c("G2", "01.02.2024"),
        c("H2", "1", "b"), c("I2", f"https://gyazo.com/{GID3}"), c("J2", "ilk aciklama"), c("K2", "ek-deger"),
    ])
    # 37 boş satır sonra gerçek kayıt; H1000000 tek başına FALSE kayıt değildir.
    r40 = "".join([
        c("A40", "p2"), c("B40", "u2"), c("E40", f"https://gyazo.com/{GID2}"),
        c("F40", "dds"), c("G40", "2024-03-04 05:06"), c("H40", "0", "b"),
        c("J40", "alt kayit"), c("K40", "ek-40"),
    ])
    xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <worksheet xmlns="{ns}"><dimension ref="A1:K1048576"/><sheetData>
      <row r="1">{r1}</row><row r="2">{r2}</row><row r="40">{r40}</row>
      <row r="1048576"><c r="H1048576" t="b"><v>0</v></c></row>
    </sheetData></worksheet>'''.encode()
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(yol, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            veri = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                veri = xml
            zout.writestr(item, veri)
    os.unlink(base)


def _ayar(tmp_path, legacy):
    media = tmp_path / "media"
    archive = tmp_path / "archive"
    media.mkdir()
    archive.mkdir()
    return {
        "BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(media), "ARSIV_KLASOR": str(archive),
        "EK_GORSEL_KLASORLERI": [str(archive)], "ONBELLEK": str(tmp_path / "cache"),
        "LEGACY_SOURCE": str(legacy), "PROJELER": ["PP", "PA", "OF", "HI", "VI", "GA"],
    }


def test_sparse_xml_gaps_false_million_and_extra_columns(tmp_path):
    xlsx = tmp_path / "telegrambot_gyazo.xlsx"
    _xlsx_sparse(xlsx)
    sonuc = excel_oku.oku(xlsx)
    assert list(sonuc) == ["PP"]
    assert [x["satir"] for x in sonuc["PP"]] == [2, 40]
    assert sonuc["PP"][0]["kt"] == 1
    assert sonuc["PP"][1]["kt"] == 0
    assert sonuc["PP"][0]["tarih_ham"] == "01.02.2024"
    assert "K=ek-deger" in sonuc["PP"][0]["ek_not"]
    assert "K=ek-40" in sonuc["PP"][1]["ek_not"]


def test_explicit_reimport_is_idempotent_and_never_overwrites_live_change(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    _xlsx_sparse(legacy / "telegrambot_gyazo.xlsx")
    (legacy / "onaylilar.txt").write_text("12345\n", encoding="utf-8")
    (legacy / "engellenenler.txt").write_text("67890\n", encoding="utf-8")
    (legacy / "kullanicilar.json").write_text('{"12345":{"username":"eski","first_name":"Eski"}}', encoding="utf-8")
    ayar = _ayar(tmp_path, legacy)
    conn = db.baglan(str(tmp_path / "panel.db"))
    try:
        ilk = ice_aktar.calistir(ayar, conn, ayar["ONBELLEK"], kaynak=str(legacy))
        assert ilk["hata"] is None, ilk
        assert ilk["yeni"] == 2
        assert ilk["kullanicilar"]["yeni"] >= 2
        assert conn.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] == 2
        conn.execute("UPDATE kayitlar SET aciklama='panelde duzeltildi', kt=1 WHERE excel_satir=40")
        ikinci = ice_aktar.calistir(ayar, conn, ayar["ONBELLEK"], kaynak=str(legacy))
        assert ikinci["hata"] is None, ikinci
        assert ikinci["yeni"] == 0
        assert ikinci["yinelenen"] == 2
        r = conn.execute("SELECT aciklama,kt FROM kayitlar WHERE excel_satir=40").fetchone()
        assert tuple(r) == ("panelde duzeltildi", 1)
        assert conn.execute("SELECT onayli FROM tg_kullanicilar WHERE id='12345'").fetchone()[0] == 1
        assert conn.execute("SELECT engelli FROM tg_kullanicilar WHERE id='67890'").fetchone()[0] == 1
    finally:
        conn.close()


def _image(yol, renk=(20, 100, 200)):
    Image.new("RGB", (30, 20), renk).save(yol)


def test_local_index_windows_relocation_ambiguity_second_image_and_path_safety(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    ayar = _ayar(tmp_path, legacy)
    archive = Path(ayar["ARSIV_KLASOR"])
    (archive / "PP").mkdir()
    (archive / "AA").mkdir()
    (archive / "BB").mkdir()
    _image(archive / "PP" / "moved.png")
    _image(archive / "PP" / "second.png", (200, 50, 50))
    _image(archive / "AA" / "one.png")
    _image(archive / "BB" / "two.png")
    outside = tmp_path / "outside.png"
    _image(outside)
    try:
        os.symlink(outside, archive / "PP" / "escape.png")
    except OSError:
        pytest.skip("Bu ortam symlink oluşturmaya izin vermiyor")
    (archive / "indeks.csv").write_text(
        "Gyazo Id;Dosya Yolu;Dosya Adı;Proje\n"
        f"{GID1};C:\\\\eski\\\\telegram_gorseller\\\\PP\\\\moved.png;moved.png;PP\n"
        f"{GID2};AA/one.png;one.png;AA\n"
        f"{GID2};BB/two.png;two.png;BB\n"
        f"{GID3};C:\\\\eski\\\\telegram_gorseller\\\\PP\\\\second.png;second.png;PP\n"
        f"{GID4};PP/escape.png;escape.png;PP\n",
        encoding="utf-8",
    )
    cozucu = GorselCozucu(ayar, ayar["ONBELLEK"])
    yol, kaynak = cozucu.yerel_dosya({"link": f"https://gyazo.com/{GID1}", "proje": "PP"})
    assert yol and yol.endswith("moved.png") and kaynak == "yerel"
    assert cozucu.yerel_dosya({"link": f"https://gyazo.com/{GID2}", "proje": "PP"}) == (None, "yok")
    yol2, _ = cozucu.ikinci_dosya({"gorsel2": f"https://gyazo.com/{GID3}", "proje": "PP"})
    assert yol2 and yol2.endswith("second.png")
    assert cozucu.yerel_dosya({"link": f"https://gyazo.com/{GID4}", "proje": "PP"}) == (None, "yok")
    # Current media relative path works, traversal does not.
    _image(Path(ayar["GORSEL_KLASOR"]) / "current.png")
    assert cozucu.yerel_dosya({"gorsel_dosya": "current.png", "link": ""})[0].endswith("current.png")
    assert cozucu.yerel_dosya({"gorsel_dosya": "../outside.png", "link": ""}) == (None, "yok")


def test_arsiv_tara_only_auto_assigns_a_single_exact_link_id(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    ayar = _ayar(tmp_path, legacy)
    archive = Path(ayar["ARSIV_KLASOR"])
    _image(archive / f"{GID1}.png")
    _image(archive / f"{GID2}.png")
    conn = db.baglan(str(tmp_path / "archive.db"))
    try:
        conn.execute("INSERT INTO kayitlar(anahtar,proje,link,link_turu) VALUES(?,?,?,?)", ("one", "PP", f"https://gyazo.com/{GID1}", "gyazo"))
        conn.execute("INSERT INTO kayitlar(anahtar,proje,link,link_turu) VALUES(?,?,?,?)", ("two-a", "PP", f"https://gyazo.com/{GID2}", "gyazo"))
        conn.execute("INSERT INTO kayitlar(anahtar,proje,link,link_turu) VALUES(?,?,?,?)", ("two-b", "PA", f"https://gyazo.com/{GID2}", "gyazo"))
        rapor = arsiv_tara(ayar, conn, GorselCozucu(ayar, ayar["ONBELLEK"]))
        assert rapor["eslesti"] == 1
        assert rapor["belirsiz"] == 1
        satirlar = {r["kimlik"]: r["kayit_id"] for r in conn.execute("SELECT kimlik,kayit_id FROM arsiv_dosyalar")}
        assert satirlar[GID1] is not None
        assert satirlar[GID2] is None
    finally:
        conn.close()

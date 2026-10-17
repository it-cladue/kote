# -*- coding: utf-8 -*-
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.excel_check import ExcelCheckError, check_source, inspect_source, validate_source


def _record(conn, project, uye):
    return conn.execute(
        "INSERT INTO kayitlar(anahtar,proje,uye_id,silindi,kaynak) VALUES(?,?,?,?,?)",
        (f"key:{project}:{uye}:{conn.execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0]}", project, uye, 0, "telegram"),
    ).lastrowid


def _ods(path: Path, content: str):
    # ODF mimetype ilk ve STORED girdidir; loader bunu açıkça kontrol eder.
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), b"application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        archive.writestr("content.xml", content)


def _content(rows: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
<office:body><office:spreadsheet><table:table table:name="Kontrol">{rows}</table:table></office:spreadsheet></office:body>
</office:document-content>'''


def test_utf8bom_cp1254_csv_semicolon_and_tsv_preserve_leading_zeros(tmp_path):
    conn = db.baglan(str(tmp_path / "panel.db"))
    try:
        kid = _record(conn, "OF", "00123")
        csv_file = tmp_path / "kontrol.csv"
        csv_file.write_bytes("\ufeffProje;Üye ID\nOF;00123\n".encode("utf-8"))
        inspected = inspect_source(csv_file, {"delimiter": "semicolon", "header_row": 1})
        assert inspected["encoding"] == "utf8bom" and inspected["delimiter"] == "semicolon"
        report = check_source(csv_file, conn, ["OF"], {"columns": {"proje": "A", "uye_id": "B"},
                              "match_fields": ["proje", "uye_id"], "project": "", "kt": "hepsi",
                              "encoding": "utf8bom", "delimiter": "semicolon", "header_row": 1})
        assert report["rows"][0]["ids"] == [kid]

        cp_file = tmp_path / "turkce.csv"
        cp_file.write_bytes("Proje;Üye ID\nÖF;00123\n".encode("cp1254"))
        inspected = inspect_source(cp_file, {"encoding": "cp1254", "delimiter": "semicolon"})
        assert inspected["sheets"][0]["headers"][1]["label"] == "Üye ID"
        # CP1254 katı okunur; erişim dışı proje sonucunda kayıt bilgisi dönmez.
        report = check_source(cp_file, conn, ["OF"], {"columns": {"proje": "A", "uye_id": "B"},
                              "match_fields": ["uye_id"], "project": "", "kt": "hepsi",
                              "encoding": "cp1254", "delimiter": "semicolon", "header_row": 1})
        assert report["rows"][0]["status"] == "erisim_kapsami_disi"

        tsv = tmp_path / "kontrol.tsv"; tsv.write_text("Üye ID\n00123\n", encoding="utf-8")
        report = check_source(tsv, conn, ["OF"], {"columns": {"uye_id": "A"}, "match_fields": ["uye_id"],
                              "project": "OF", "kt": "hepsi", "delimiter": "tab", "header_row": 1})
        assert report["rows"][0]["status"] == "bulundu"
    finally:
        conn.close()


def test_txt_id_lines_are_not_split_and_no_header(tmp_path):
    text = tmp_path / "id.txt"
    text.write_text("00123\n\nABC,123\nABC;123\n", encoding="utf-8")
    conn = db.baglan(str(tmp_path / "panel.db"))
    try:
        first = _record(conn, "OF", "00123")
        second = _record(conn, "OF", "ABC,123")
        third = _record(conn, "OF", "ABC;123")
        report = check_source(text, conn, ["OF"], {"text_mode": "ids", "id_field": "uye_id",
                              "match_fields": ["uye_id"], "project": "OF", "kt": "hepsi"})
        assert [row["values"]["uye_id"] for row in report["rows"]] == ["00123", "ABC,123", "ABC;123"]
        assert [row["ids"] for row in report["rows"]] == [[first], [second], [third]]
        assert report["metadata"]["options"]["header_row"] == 0
        with pytest.raises(ExcelCheckError, match="yalnızca tek"):
            check_source(text, conn, ["OF"], {"text_mode": "ids", "id_field": "uye_id",
                         "match_fields": ["uye_id", "personel"], "project": "OF", "kt": "hepsi"})
    finally:
        conn.close()


def test_ods_valid_and_repeat_bomb_and_dtd_are_rejected(tmp_path):
    good = tmp_path / "good.ods"
    _ods(good, _content('''
      <table:table-row><table:table-cell office:value-type="string"><text:p>Üye ID</text:p></table:table-cell></table:table-row>
      <table:table-row><table:table-cell office:value-type="string"><text:p>00123</text:p></table:table-cell></table:table-row>'''))
    conn = db.baglan(str(tmp_path / "panel.db"))
    try:
        kid = _record(conn, "OF", "00123")
        inspected = inspect_source(good, {"header_row": 1})
        assert inspected["format"] == "ods" and inspected["sheets"][0]["name"] == "Kontrol"
        report = check_source(good, conn, ["OF"], {"sheet": "Kontrol", "header_row": 1,
                              "columns": {"uye_id": "A"}, "match_fields": ["uye_id"], "project": "OF", "kt": "hepsi"})
        assert report["rows"][0]["ids"] == [kid]
    finally:
        conn.close()

    bomb = tmp_path / "repeat.ods"
    _ods(bomb, _content('<table:table-row table:number-rows-repeated="50001"><table:table-cell office:value-type="string"><text:p>x</text:p></table:table-cell></table:table-row>'))
    with pytest.raises(ExcelCheckError, match="tekrar satır"):
        inspect_source(bomb, {"header_row": 1})

    dtd = tmp_path / "dtd.ods"
    _ods(dtd, '<!DOCTYPE office:document-content [<!ENTITY x "x">]>' + _content(""))
    with pytest.raises(ExcelCheckError, match="DTD"):
        validate_source(dtd)


def test_duplicate_archive_rejected_and_parse_limit_is_not_missing(tmp_path, monkeypatch):
    bad = tmp_path / "duplicate.ods"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("mimetype", b"application/vnd.oasis.opendocument.spreadsheet")
        archive.writestr("content.xml", _content(""))
        archive.writestr("content.xml", _content(""))
    with pytest.raises(ExcelCheckError, match="yinelenen"):
        validate_source(bad)

    csv_file = tmp_path / "limit.csv"; csv_file.write_text("Üye ID\n001\n002\n", encoding="utf-8")
    conn = db.baglan(str(tmp_path / "panel.db"))
    try:
        # Gerçek 20.000 eşiğinin aynı kontrol yolu, küçük test sınırıyla doğrulanır.
        monkeypatch.setattr("app.excel_check.MAX_RELEVANT_ROWS", 1)
        with pytest.raises(ExcelCheckError, match="20.000"):
            check_source(csv_file, conn, ["OF"], {"columns": {"uye_id": "A"}, "match_fields": ["uye_id"],
                         "project": "OF", "kt": "hepsi", "header_row": 1})
    finally:
        conn.close()

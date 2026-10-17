# -*- coding: utf-8 -*-
"""Dinamik katalog sözleşmesi için yalnız geçici SQLite kullanan testler."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, katalog


@pytest.fixture
def conn(tmp_path):
    connection = db.baglan(str(tmp_path / "katalog-test.db"))
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def legacy_conn(tmp_path):
    """Katalog migration'ı hiç çağrılmamış eski db.py şeması."""
    connection = sqlite3.connect(tmp_path / "legacy-katalog-test.db", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(db.SEMA)
    connection.executemany(
        "INSERT OR IGNORE INTO kategoriler(code,label,mode) VALUES(?,?,?)",
        db.DEFAULT_CATEGORIES,
    )
    # db.denetim_yaz güncel uygulamada additive denetim alanlarını kullanır;
    # katalog migration'ından önceki fixture bu alanları da taşımalıdır.
    for name, declaration in (
        ("sonuc", "TEXT DEFAULT 'ok'"), ("hedef_turu", "TEXT"),
        ("hedef_id", "TEXT"), ("aciklama", "TEXT"),
    ):
        connection.execute(f"ALTER TABLE denetim ADD COLUMN {name} {declaration}")
    try:
        yield connection
    finally:
        connection.close()


def custom_questions():
    return [
        {
            "key": "personel", "label": "Personel", "preset": "personel",
            "type": "text", "required": True, "options": [],
        },
        {
            "key": "notu", "label": "Açıklama notu", "preset": "",
            "type": "text", "required": False, "options": [],
        },
        {
            "key": "durum", "label": "Durum", "preset": "",
            "type": "select", "required": True, "options": ["yeni", "takip"],
        },
    ]


def test_migration_two_times_seeds_legacy_and_keeps_existing_records(legacy_conn):
    conn = legacy_conn
    # Gerçek geçmiş kayıt salt okunur kabul edilir; migration yalnız referans
    # projesini ekler, kayıt satırını değiştirmez.
    conn.execute(
        "INSERT INTO kayitlar(anahtar,proje,kategori,kategori_code,kategori_mode) VALUES(?,?,?,?,?)",
        ("legacy-1", "TARIHSEL", "ARK", "ark", "ark_ana"),
    )
    katalog.ensure_schema(conn)

    first_projects = katalog.list_projects(conn)
    assert {project["code"] for project in first_projects} >= {"PP", "PA", "OF", "HI", "VI", "GA", "TARIHSEL"}
    historical = katalog.get_project(conn, "TARIHSEL")
    assert historical["aktif"] == 0 and historical["color"] == "#999999"
    assert conn.execute("SELECT proje,kategori,kategori_code,kategori_mode FROM kayitlar WHERE anahtar='legacy-1'").fetchone()[0] == "TARIHSEL"
    # 2.2: BETA projesi geçişte eksikse aktif olarak eklenir (6 legacy + BETA).
    assert len(katalog.list_projects(conn, active_only=True)) == 7
    assert katalog.get_project(conn, "BETA")["color"] == "#FFA500"

    # Dört legacy mode soru tanımı üretir; sessiz/telesekreter değerleri korunur.
    assert [question["key"] for question in katalog.questions(conn, "ark")] == ["personel", "uye_id", "ana_uye_id"]
    assert katalog.questions(conn, "dds")[-1]["options"] == ["sessiz", "telesekreter"]
    active_categories = conn.execute("SELECT COUNT(*) FROM kategoriler WHERE aktif=1").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM proje_kategorileri WHERE aktif=1").fetchone()[0] == 7 * active_categories
    assert {row["name"] for row in conn.execute("PRAGMA table_info(kayitlar)")} >= {
        "kategori_soru_surumu", "soru_anlik_json", "cevaplar_json"
    }

    # İlk migration sonrası bir admin tercihi değiştiğinde sonraki bağlantı / ensure
    # bunu eski seed ile geri getiremez.
    pa = katalog.get_project(conn, "PA")
    katalog.save_project(conn, "PA", "PA yönetilen", "#123456", False, actor="super", expected_revision=pa["revision"])
    ark = katalog.get_category(conn, "ark")
    katalog.save_category(conn, "ark", "Özel ARK", "ark_ana", projects=["GA"], actor="super", expected_revision=ark["revision"])
    katalog.ensure_schema(conn)

    assert katalog.get_project(conn, "PA")["label"] == "PA yönetilen"
    assert katalog.get_project(conn, "PA")["aktif"] == 0
    assert katalog.get_category(conn, "ark")["projects"] == ["GA"]
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE name=?", (katalog.MIGRATION_NAME,)).fetchone()[0] == 1


def test_project_category_isolation(conn):
    katalog.ensure_schema(conn)
    katalog.save_project(conn, "YENI", "Yeni proje", "#112233", actor="super")
    katalog.save_category(
        conn, "yalniz_yeni", "Yalnız yeni", "custom", projects=["YENI"],
        questions=custom_questions(), actor="super",
    )

    assert [row["code"] for row in katalog.list_categories(conn, "YENI")] == ["yalniz_yeni"]
    assert katalog.get_category(conn, "yalniz_yeni", "YENI")["label"] == "Yalnız yeni"
    assert katalog.get_category(conn, "yalniz_yeni", "PP") is None
    assert "yalniz_yeni" not in {row["code"] for row in katalog.list_categories(conn, "PP")}


def test_custom_questions_sort_and_duplicate_validation(conn):
    katalog.ensure_schema(conn)
    katalog.save_project(conn, "OZEL", "Özel", "#445566", actor="super")
    saved = katalog.save_category(
        conn, "ozel_kat", "Özel kategori", projects=["OZEL"],
        questions=custom_questions(), actor="super",
    )
    assert [question["key"] for question in saved["questions"]] == ["personel", "notu", "durum"]
    assert saved["questions"][2]["options"] == ["yeni", "takip"]

    duplicated_key = custom_questions()
    duplicated_key.append({"key": "notu", "label": "İkinci", "preset": "", "type": "text", "required": True, "options": []})
    with pytest.raises(ValueError, match="Tekrarlanan soru anahtarı"):
        katalog.save_category(conn, "hata_anahtar", "Hata", projects=["OZEL"], questions=duplicated_key)

    duplicated_preset = custom_questions()
    duplicated_preset.append({"key": "uye_id", "label": "Üye", "preset": "uye_id", "type": "text", "required": True, "options": []})
    duplicated_preset.append({"key": "uye_id2", "label": "Üye iki", "preset": "uye_id", "type": "text", "required": True, "options": []})
    with pytest.raises(ValueError, match="Tekrarlanan hazır soru"):
        katalog.save_category(conn, "hata_preset", "Hata", projects=["OZEL"], questions=duplicated_preset)

    with pytest.raises(ValueError, match="ADMIN"):
        katalog.save_project(conn, "ADMIN", "Rol değil", "#000000")


def test_revision_concurrency_and_audit(conn):
    katalog.ensure_schema(conn)
    created = katalog.save_project(conn, "REV", "İlk", "#010203", actor="super")
    updated = katalog.save_project(
        conn, "REV", "İkinci", "#040506", actor="super", expected_revision=created["revision"]
    )
    assert updated["revision"] == created["revision"] + 1
    with pytest.raises(katalog.RevisionConflict):
        katalog.save_project(conn, "REV", "Bayat", "#070809", actor="super", expected_revision=created["revision"])
    assert katalog.get_project(conn, "REV")["label"] == "İkinci"

    category = katalog.save_category(conn, "rev_kat", "İlk kategori", projects=["REV"], questions=custom_questions(), actor="super")
    category_updated = katalog.save_category(
        conn, "rev_kat", "İkinci kategori", projects=["REV"], questions=custom_questions(),
        actor="super", expected_revision=category["revision"],
    )
    assert category_updated["revision"] == category["revision"] + 1
    with pytest.raises(katalog.RevisionConflict):
        katalog.save_category(
            conn, "rev_kat", "Bayat kategori", projects=["REV"], questions=custom_questions(),
            actor="super", expected_revision=category["revision"],
        )
    assert katalog.get_category(conn, "rev_kat")["label"] == "İkinci kategori"
    assert conn.execute("SELECT COUNT(*) FROM denetim WHERE kullanici='super' AND islem LIKE 'katalog_%'").fetchone()[0] >= 4


def test_ensure_schema_respects_outer_transaction(legacy_conn):
    conn = legacy_conn
    # Parent db.py bir BEGIN IMMEDIATE içinde çağırdığında ensure_schema kendi
    # commit/rollback'ini yapmamalı; SQLite execute DDL'si de bu transaction'a
    # dahil kalmalıdır.
    conn.execute("BEGIN IMMEDIATE")
    katalog.ensure_schema(conn)
    assert conn.in_transaction
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projeler'").fetchone()
    conn.rollback()
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='projeler'").fetchone()

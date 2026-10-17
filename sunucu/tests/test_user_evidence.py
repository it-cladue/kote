# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pytest

# Bazı pytest çağrıları depo kökünü sys.path'e koymaz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.user_evidence import get_profile


@pytest.fixture
def conn(tmp_path):
    connection = db.baglan(str(tmp_path / "profile.db"))
    # Bu geçiş üretimde parent endpoint tarafından yapılacak; yardımcı modül eski
    # şemada da salt-okunur çalışır, test atama davranışını ayrıca doğrular.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(tg_kullanicilar)")}
    if "ana_proje" not in columns:
        connection.execute("ALTER TABLE tg_kullanicilar ADD COLUMN ana_proje TEXT")
    yield connection
    connection.close()


def add_user(conn, tg_id, username="", first_name="", assigned=None):
    conn.execute(
        "INSERT INTO tg_kullanicilar(id,username,first_name,ana_proje) VALUES(?,?,?,?)",
        (str(tg_id), username, first_name, assigned),
    )


def add_record(
    conn,
    serial,
    project,
    tg_id,
    confidence="kesin",
    source="telegram",
    *,
    kt=0,
    deleted=0,
    category="HGST",
):
    conn.execute(
        """INSERT INTO kayitlar(
             anahtar,proje,ekleyen_id,ekleyen_ad,ekleyen_guven,kaynak,
             kategori,personel,uye_id,tarih,kt,silindi
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            f"profile:{serial}", project, str(tg_id), "ekleyen", confidence,
            source, category, f"P{serial}", f"U{serial}", f"2025-01-{(serial % 27) + 1:02d}",
            kt, deleted,
        ),
    )


def test_allowed_projects_scope_covers_counts_rows_and_filters_without_leak(conn):
    add_user(conn, "101", "scope", "Kapsam")
    add_record(conn, 1, "PA", "101", kt=1)
    add_record(conn, 2, "OF", "101", kt=0)
    # Başka kullanıcının satırı da hiçbir profile karışmamalı.
    add_record(conn, 3, "PA", "202")

    with pytest.raises(PermissionError):
        get_profile(conn, "101", ["PA"], {"project": "OF", "kt": "hepsi"})
    profile = get_profile(conn, "101", ["PA"], {"kt": "hepsi"})

    assert profile["counts"] == {
        "total": 1, "outside": 0, "pending": 0, "approved": 1, "deleted": 0, "estimated": 0,
    }
    assert profile["filters"]["project"] == ""  # Yetkisiz proje isteği genişletmez.
    assert [item["proje"] for item in profile["projects"]] == ["PA"]
    assert [row["proje"] for row in profile["rows"]] == ["PA"]
    assert "OF" not in repr(profile)


def test_assigned_project_outside_allowed_scope_is_never_disclosed(conn):
    add_user(conn, "102", "hidden", "Gizli", assigned="OF")
    add_record(conn, 1, "PA", "102", confidence="kesin", source="legacy_excel")

    profile = get_profile(conn, "102", ["PA"], {}, superadmin=False)

    assert profile["expected_project"] == "PA"
    assert profile["expected_source"] == "hesaplanan"
    assert "OF" not in repr(profile)


def test_expected_project_majority_ignores_estimated_and_null_history(conn):
    add_user(conn, "103")
    add_record(conn, 1, "PA", "103", confidence="kesin", source="legacy_excel")
    for serial in range(2, 8):
        add_record(conn, serial, "OF", "103", confidence="tahmini", source="legacy_excel")
    add_record(conn, 8, "OF", "103", confidence=None, source="legacy_excel")

    profile = get_profile(conn, "103", ["PA", "OF"], {})

    assert profile["expected_project"] == "PA"
    assert profile["expected_source"] == "hesaplanan"
    assert profile["counts"]["estimated"] == 7
    history = [row for row in profile["rows"] if row["proje"] == "OF"]
    assert history and all(row["estimated"] for row in history)


def test_outside_filter_is_subset_of_allowed_profile_and_uses_known_expected(conn):
    add_user(conn, "104", assigned="PA")
    add_record(conn, 1, "PA", "104", kt=1)
    add_record(conn, 2, "PA", "104", kt=0)
    add_record(conn, 3, "OF", "104", kt=0)
    add_record(conn, 4, "SECRET", "104", kt=0)

    profile = get_profile(conn, "104", ["PA", "OF"], {"outside": "1", "kt": "hepsi"})

    assert profile["expected_project"] == "PA"
    assert profile["counts"]["outside"] == 1
    assert profile["total_filtered"] == 1
    assert {row["proje"] for row in profile["rows"]} == {"OF"}
    assert "SECRET" not in repr(profile)


def test_default_zero_user_requires_scope_for_normal_user_but_superadmin_can_read_metadata(conn):
    add_user(conn, "105", "zero", "Sıfır")

    with pytest.raises(PermissionError):
        get_profile(conn, "105", ["PA"], {})

    profile = get_profile(conn, "105", ["PA"], {}, superadmin=True)
    assert profile["user"] == {"id": "105", "username": "zero", "first_name": "Sıfır"}
    assert profile["counts"] == {
        "total": 0, "outside": 0, "pending": 0, "approved": 0, "deleted": 0, "estimated": 0,
    }
    assert profile["rows"] == [] and profile["projects"] == []
    assert profile["page"] == 1 and profile["pages"] == 1


def test_page_limit_and_strict_numeric_id(conn):
    add_user(conn, "106")
    for serial in range(1, 57):
        add_record(conn, serial, "PA", "106")

    first = get_profile(conn, "106", ["PA"], {})
    second = get_profile(conn, "106", ["PA"], {"page": "2"})
    assert len(first["rows"]) == 50 and first["pages"] == 2
    assert len(second["rows"]) == 6 and second["page"] == 2
    with pytest.raises(ValueError):
        get_profile(conn, "106 ", ["PA"], {})

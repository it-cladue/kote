# -*- coding: utf-8 -*-
"""Dış ağ olmadan kalıcı Gyazo iş kuyruğu davranışları."""
from __future__ import annotations

from pathlib import Path

from app import db, donusum_isleri


def _record(conn, key="r1"):
    conn.execute("INSERT INTO kayitlar(anahtar,proje,gorsel_dosya) VALUES(?,?,?)", (key, "PP", "local.png"))
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def test_dedup_upload_verify_ve_kayit_baglama(tmp_path):
    conn = db.baglan(str(tmp_path / "queue.db"))
    try:
        kid = _record(conn)
        one = donusum_isleri.enqueue(conn, kid, "site", local_path=str(tmp_path / "local.png"))
        two = donusum_isleri.enqueue(conn, kid, "site", local_path=str(tmp_path / "local.png"))
        assert one["job_key"] == two["job_key"] == f"record:{kid}"
        calls = []
        upload = lambda path: calls.append(("upload", path)) or {"ok": True, "image_id": "a" * 32, "image_url": "https://i.gyazo.com/" + "a" * 32 + ".png", "http_status": 200}
        verify = lambda iid, url: calls.append(("verify", iid)) or {"ok": True, "url": "https://gyazo.com/" + "a" * 32, "http_status": 200}
        assert donusum_isleri.worker_step(conn, "w1", upload=upload, verify=verify)["durum"] == "verify"
        done = donusum_isleri.worker_step(conn, "w1", upload=upload, verify=verify)
        assert done["durum"] == "tamam"
        assert calls == [("upload", str(tmp_path / "local.png")), ("verify", "a" * 32)]
        row = conn.execute("SELECT link,link_turu FROM kayitlar WHERE id=?", (kid,)).fetchone()
        assert row["link"] == "https://gyazo.com/" + "a" * 32 and row["link_turu"] == "gyazo"
    finally:
        conn.close()


def test_verify_retry_does_not_repeat_successful_upload(tmp_path):
    conn = db.baglan(str(tmp_path / "retry.db"))
    try:
        job = donusum_isleri.enqueue(conn, None, "u", local_path=str(tmp_path / "source.png"), bot_id="b", chat_id="c", source_message_id=9)
        calls = []
        upload = lambda path: calls.append("upload") or {"ok": True, "image_id": "b" * 32, "image_url": "https://i.gyazo.com/" + "b" * 32 + ".png"}
        verify_fail = lambda iid, url: calls.append("verify") or {"ok": False, "error": "gecici", "http_status": 503, "retryable": True}
        assert donusum_isleri.worker_step(conn, "w", upload=upload, verify=verify_fail)["phase"] == "verify"
        retry = donusum_isleri.worker_step(conn, "w", upload=upload, verify=verify_fail)
        assert retry["durum"] == "verify" and calls == ["upload", "verify"]
        conn.execute("UPDATE donusum_isleri SET next_try='2000-01-01 00:00:00' WHERE id=?", (job["id"],))
        verify_ok = lambda iid, url: calls.append("verify-ok") or {"ok": True, "url": "https://gyazo.com/" + "b" * 32}
        assert donusum_isleri.worker_step(conn, "w", upload=upload, verify=verify_ok)["durum"] == "tamam"
        assert calls == ["upload", "verify", "verify-ok"]
    finally:
        conn.close()


def test_ambiguous_post_ve_suresi_dolan_upload_lease_korlemesine_yenilenmez(tmp_path):
    conn = db.baglan(str(tmp_path / "ambiguous.db"))
    try:
        job = donusum_isleri.enqueue(conn, None, "u", local_path=str(tmp_path / "source.png"), bot_id="b", chat_id="c", source_message_id=10)
        row = donusum_isleri.worker_step(conn, "w", upload=lambda path: {"ok": False, "error": "timeout", "ambiguous": True}, verify=lambda *_: {})
        assert row["durum"] == "belirsiz" and row["ambiguous"] == 1
        assert donusum_isleri.worker_step(conn, "w", upload=lambda path: (_ for _ in ()).throw(AssertionError("blind retry")), verify=lambda *_: {}) is None
        job2 = donusum_isleri.enqueue(conn, None, "u", local_path=str(tmp_path / "source2.png"), bot_id="b", chat_id="c", source_message_id=11)
        conn.execute("UPDATE donusum_isleri SET durum='calisiyor',phase='upload',lease_until='2000-01-01 00:00:00' WHERE id=?", (job2["id"],))
        assert donusum_isleri.claim(conn, "other") is None
        expired = conn.execute("SELECT durum,ambiguous FROM donusum_isleri WHERE id=?", (job2["id"],)).fetchone()
        assert tuple(expired) == ("belirsiz", 1)
    finally:
        conn.close()


def test_basari_kayit_baglanana_kadar_bildirim_ertelenir_ve_sonra_uygulanir(tmp_path):
    """Doğrulanmış uzak URL, onaylanmış yerel kayıt yokken terminal sayılmaz."""
    conn = db.baglan(str(tmp_path / "deferred.db"))
    try:
        job = donusum_isleri.enqueue(
            conn, None, "u", local_path=str(tmp_path / "source.png"),
            bot_id="b", chat_id="c", source_message_id=12,
        )
        upload = lambda path: {"ok": True, "image_id": "c" * 32, "image_url": "https://i.gyazo.com/" + "c" * 32 + ".png"}
        verify = lambda iid, url: {"ok": True, "url": "https://gyazo.com/" + "c" * 32}
        assert donusum_isleri.worker_step(conn, "w", upload=upload, verify=verify)["durum"] == "verify"
        done = donusum_isleri.worker_step(conn, "w", upload=upload, verify=verify)
        assert done["durum"] == "tamam" and done["record_id"] is None
        assert donusum_isleri.claim_notices(conn, bot_id="b") == []

        kid = _record(conn, "deferred")
        bound = donusum_isleri.bind_record(conn, job["job_key"], kid, str(tmp_path / "source.png"))
        assert bound["record_applied"] == 1 and bound["uygulama_durumu"] == "uygulandi"
        record = conn.execute("SELECT link,link_turu FROM kayitlar WHERE id=?", (kid,)).fetchone()
        assert tuple(record) == ("https://gyazo.com/" + "c" * 32, "gyazo")
        notices = donusum_isleri.claim_notices(conn, bot_id="b")
        assert len(notices) == 1 and notices[0]["job_key"] == job["job_key"]
    finally:
        conn.close()

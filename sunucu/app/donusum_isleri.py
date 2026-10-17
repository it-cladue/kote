# -*- coding: utf-8 -*-
"""Kalıcı, tekilleştirilmiş dış görsel dönüşüm işleri.

Bu modül Telegram ve site tarafından aynı SQLite bağlantısı ile kullanılabilir.
Ağ çağrısı hiçbir zaman SQLite transaction'ı içinde yapılmaz. ``enqueue`` kaynak
anahtarını tekilleştirir; ``worker_step`` bir iş için en çok bir dış çağrı yapar.

Site entegrasyonu:
    ensure_schema(conn)
    enqueue(conn, record_id, actor, local_path='/mutlak/yerel.png')
    worker_step(conn, worker_id='web-gyazo-1')

Telegram entegrasyonu bot/chat/source_message alanları ile aynı API'yi kullanır.
``record_id`` sonradan ``bind_record`` ile bağlanabilir. Upload POST'u sonrası
process çökmesi dış sağlayıcıda tek upload garantisi vermez; süresi dolan upload
lease'i dürüstçe ``belirsiz`` terminal durumuna alınır ve körlemesine tekrar POST
edilmez.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from . import db

MAX_ATTEMPTS = 4
LEASE_SECONDS = 90
BACKOFF_SECONDS = (5, 30, 120, 600)
TERMINAL = {"tamam", "hata", "belirsiz", "iptal"}

_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS donusum_isleri (
 id INTEGER PRIMARY KEY,
 job_key TEXT NOT NULL UNIQUE,
 record_id INTEGER,
 actor TEXT,
 provider TEXT NOT NULL DEFAULT 'gyazo',
 bot_id TEXT, chat_id TEXT, source_message_id INTEGER, user_id TEXT,
 local_path TEXT NOT NULL, source_path TEXT, expected_gorsel TEXT,
 durum TEXT NOT NULL DEFAULT 'bekliyor',
 phase TEXT NOT NULL DEFAULT 'upload',
 deneme INTEGER NOT NULL DEFAULT 0,
 verify_deneme INTEGER NOT NULL DEFAULT 0,
 next_try TEXT NOT NULL,
 lease_owner TEXT, lease_until TEXT,
 image_id TEXT, image_url TEXT, url TEXT,
 http_status INTEGER, hata TEXT, ambiguous INTEGER NOT NULL DEFAULT 0,
 notice_durum TEXT NOT NULL DEFAULT 'bekliyor', notice_replace_message_id INTEGER,
 record_applied INTEGER NOT NULL DEFAULT 0,
 uygulama_durumu TEXT NOT NULL DEFAULT 'bekliyor',
 olusturma TEXT NOT NULL, guncelleme TEXT NOT NULL
)
"""

_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS ix_donusum_bekleyen
 ON donusum_isleri(durum,next_try,lease_until,id);
CREATE INDEX IF NOT EXISTS ix_donusum_kayit ON donusum_isleri(record_id,durum);
"""


def _now() -> str:
    return db.simdi()


def _later(seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=max(0, int(seconds)))).strftime("%Y-%m-%d %H:%M:%S")


def ensure_schema(conn) -> None:
    """Additive/idempotent schema migration; safe for old shared databases."""
    # sqlite3.executescript() açık bir transaction'ı örtük commit edebilir.
    # Parent'ın db.baglan çekirdeği bunu kendi BEGIN IMMEDIATE bloğunda da
    # çağırabildiğinden DDL'yi tekil execute ile yürütürüz.  Özellikle indeksler
    # *kolon eklemelerinden sonra* oluşturulur: erken bir 2.1 tablosunda durum
    # ya da record_id yoksa önceki sıra migration'ı daha ALTER'a gelmeden düşürüyordu.
    conn.execute(_TABLE_SCHEMA)
    # Early review branches had a shorter table. Additions keep restarts safe.
    required = {
        "record_id": "INTEGER", "actor": "TEXT", "provider": "TEXT NOT NULL DEFAULT 'gyazo'",
        "bot_id": "TEXT", "chat_id": "TEXT", "source_message_id": "INTEGER", "user_id": "TEXT",
        "local_path": "TEXT", "source_path": "TEXT", "expected_gorsel": "TEXT",
        "durum": "TEXT NOT NULL DEFAULT 'bekliyor'", "phase": "TEXT NOT NULL DEFAULT 'upload'",
        "deneme": "INTEGER NOT NULL DEFAULT 0", "verify_deneme": "INTEGER NOT NULL DEFAULT 0",
        "next_try": "TEXT", "lease_owner": "TEXT", "lease_until": "TEXT", "image_id": "TEXT",
        "image_url": "TEXT", "url": "TEXT", "http_status": "INTEGER", "hata": "TEXT",
        "ambiguous": "INTEGER NOT NULL DEFAULT 0", "notice_durum": "TEXT NOT NULL DEFAULT 'bekliyor'",
        "notice_replace_message_id": "INTEGER", "record_applied": "INTEGER NOT NULL DEFAULT 0",
        "uygulama_durumu": "TEXT NOT NULL DEFAULT 'bekliyor'",
        "olusturma": "TEXT", "guncelleme": "TEXT",
    }
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(donusum_isleri)")}
    for name, kind in required.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE donusum_isleri ADD COLUMN {name} {kind}")
    # NULL yeni-kolon değerleri eski yarım işleri görünmez bırakmasın. Bu
    # güncellemeler bulunduğumuz transaction'a katılır; burada commit edilmez.
    now = _now()
    conn.execute(
        "UPDATE donusum_isleri SET source_path=CASE WHEN source_path IS NULL OR source_path='' THEN local_path ELSE source_path END, "
        "next_try=COALESCE(next_try,?), phase=COALESCE(phase,'upload'), record_applied=COALESCE(record_applied,0), "
        "uygulama_durumu=COALESCE(NULLIF(uygulama_durumu,''),'bekliyor'), "
        "durum=COALESCE(durum,'bekliyor'), olusturma=COALESCE(olusturma,?), "
        "guncelleme=COALESCE(guncelleme,?)",
        (now, now, now),
    )
    for statement in (piece.strip() for piece in _INDEX_SCHEMA.split(";") if piece.strip()):
        conn.execute(statement)


def _record_image(conn, record_id: Optional[int]) -> Optional[str]:
    """Return the raw local-image path which a remote link is allowed to replace."""
    if record_id is None:
        return None
    row = conn.execute("SELECT gorsel_dosya FROM kayitlar WHERE id=?", (int(record_id),)).fetchone()
    if not row or row["gorsel_dosya"] is None:
        return None
    image = str(row["gorsel_dosya"])
    return image or None


def source_key(*, bot_id: Optional[str] = None, chat_id: Optional[str] = None,
               source_message_id: Optional[int] = None, record_id: Optional[int] = None,
               job_key: Optional[str] = None) -> str:
    """Stable dedup key. A caller may explicitly provide a site-specific key."""
    if job_key:
        return str(job_key)[:220]
    if bot_id is not None and chat_id is not None and source_message_id is not None:
        return f"tg:{str(bot_id)[:64]}:{str(chat_id)[:96]}:{int(source_message_id)}"
    if record_id is not None:
        return f"record:{int(record_id)}"
    raise ValueError("Dönüşüm işi için kaynak anahtarı veya kayıt kimliği gerekir")


def enqueue(conn, record_id: Optional[int], actor: Any, *, local_path: str,
            bot_id: Optional[str] = None, chat_id: Optional[str] = None,
            source_message_id: Optional[int] = None, user_id: Optional[str] = None,
            job_key: Optional[str] = None, provider: str = "gyazo",
            expected_gorsel: Optional[str] = None) -> dict:
    """Insert-or-return one durable job without doing I/O.

    The key is ``(bot_id, chat_id, source_message_id)`` for Telegram.  Site code
    can use ``record_id`` (or an explicit opaque ``job_key``).  Re-enqueueing the
    same source never creates another upload job and never resets a terminal job.
    """
    ensure_schema(conn)
    key = source_key(bot_id=bot_id, chat_id=chat_id, source_message_id=source_message_id,
                     record_id=record_id, job_key=job_key)
    path = str(local_path or "")
    if not path:
        raise ValueError("Yerel dönüşüm dosyası gerekir")
    now = _now()
    # This is a raw DB path, not a filesystem path supplied by a client.  The
    # later compare-and-update means a newer evidence image can never receive an
    # old upload's URL.
    expected = expected_gorsel if expected_gorsel is not None else _record_image(conn, record_id)
    conn.execute(
        "INSERT OR IGNORE INTO donusum_isleri(job_key,record_id,actor,provider,bot_id,chat_id,source_message_id,user_id,local_path,source_path,expected_gorsel,durum,phase,next_try,olusturma,guncelleme) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,'bekliyor','upload',?,?,?)",
        (key, record_id, str(actor or "")[:120], str(provider or "gyazo")[:32],
         None if bot_id is None else str(bot_id)[:64], None if chat_id is None else str(chat_id)[:96],
         source_message_id, None if user_id is None else str(user_id)[:96], path, path, expected, now, now, now),
    )
    # A record may become available after an earlier Telegram enqueue.  Never
    # revive cancelled work and never replace a known local source with empty data.
    if record_id is not None:
        conn.execute(
            "UPDATE donusum_isleri SET record_id=COALESCE(record_id,?), "
            "local_path=CASE WHEN local_path IS NULL OR local_path='' THEN ? ELSE local_path END, "
            "source_path=CASE WHEN source_path IS NULL OR source_path='' THEN ? ELSE source_path END, "
            "expected_gorsel=CASE WHEN record_id IS NULL OR record_id=? THEN COALESCE(expected_gorsel,?) ELSE expected_gorsel END, "
            "guncelleme=? WHERE job_key=? AND durum!='iptal'",
            (int(record_id), path, path, int(record_id), expected, now, key),
        )
    row = conn.execute("SELECT * FROM donusum_isleri WHERE job_key=?", (key,)).fetchone()
    return dict(row)


def bind_record(conn, job_key: str, record_id: int, local_path: str,
                *, notice_replace_message_id: Optional[int] = None) -> Optional[dict]:
    """Safely attach a confirmed local record to its original conversion job.

    A cancelled session cannot bind a later/new record: the caller must pass the
    exact source key, and cancelled jobs are deliberately left unbound.
    """
    ensure_schema(conn)
    row = conn.execute("SELECT * FROM donusum_isleri WHERE job_key=?", (str(job_key),)).fetchone()
    if not row or row["durum"] == "iptal":
        return dict(row) if row else None
    # A source key is a single evidence operation.  Do not let a late/new flow
    # retarget an already bound operation to another record.
    if row["record_id"] is not None and int(row["record_id"]) != int(record_id):
        return dict(row)
    expected = _record_image(conn, int(record_id))
    conn.execute(
        "UPDATE donusum_isleri SET record_id=?,local_path=?,expected_gorsel=?, "
        "notice_replace_message_id=COALESCE(notice_replace_message_id,?),guncelleme=? "
        "WHERE job_key=? AND durum!='iptal' AND (record_id IS NULL OR record_id=?)",
        (int(record_id), str(local_path), expected, notice_replace_message_id, _now(), str(job_key), int(record_id)),
    )
    row = conn.execute("SELECT * FROM donusum_isleri WHERE job_key=?", (str(job_key),)).fetchone()
    if row and row["durum"] == "tamam" and row["url"]:
        # Completion may predate confirmation. Apply the exact same snapshot
        # check as the worker's normal terminal path.
        _apply_remote_link(conn, dict(row))
    row = conn.execute("SELECT * FROM donusum_isleri WHERE job_key=?", (str(job_key),)).fetchone()
    return dict(row) if row else None


def cancel(conn, *, job_key: Optional[str] = None, bot_id: Optional[str] = None,
           chat_id: Optional[str] = None, source_message_id: Optional[int] = None) -> bool:
    """Cancel only unfinished work; terminal results and local files are untouched."""
    ensure_schema(conn)
    key = source_key(bot_id=bot_id, chat_id=chat_id, source_message_id=source_message_id, job_key=job_key)
    result = conn.execute(
        "UPDATE donusum_isleri SET durum='iptal',lease_owner=NULL,lease_until=NULL,guncelleme=? "
        "WHERE job_key=? AND record_id IS NULL AND durum NOT IN ('tamam','hata','belirsiz','iptal')", (_now(), key),
    )
    return bool(result.rowcount)


def is_path_reserved(conn, bot_id: str, path: str) -> bool:
    """Whether a pending Telegram file must survive final-record cleanup."""
    ensure_schema(conn)
    return bool(conn.execute(
        "SELECT 1 FROM donusum_isleri WHERE bot_id=? AND (local_path=? OR source_path=?) AND durum NOT IN ('tamam','hata','belirsiz','iptal') LIMIT 1",
        (str(bot_id), str(path), str(path)),
    ).fetchone())


def _row_dict(conn, job_id: int) -> dict:
    row = conn.execute("SELECT * FROM donusum_isleri WHERE id=?", (int(job_id),)).fetchone()
    return dict(row) if row else {}


def _set_application_status(conn, job: dict, applied: bool, *, reason: str,
                            record=None) -> None:
    """Persist whether a verified URL reached the queued record snapshot.

    A completed provider conversion is not itself proof that the evidence record
    was updated.  The separate durable flag lets notification delivery remain
    honest across worker and bot restarts.
    """
    state = "uygulandi" if applied else "uygulanmadi"
    current = conn.execute(
        "SELECT uygulama_durumu FROM donusum_isleri WHERE id=?", (int(job["id"]),)
    ).fetchone()
    conn.execute(
        "UPDATE donusum_isleri SET record_applied=?,uygulama_durumu=?,guncelleme=? WHERE id=?",
        (1 if applied else 0, state, _now(), int(job["id"])),
    )
    # Do not emit repeated warnings when a restart revisits the same terminal
    # job.  Audit data deliberately contains only a fixed outcome, never URL or
    # provider response material.
    if not applied and (not current or current["uygulama_durumu"] != "uygulanmadi"):
        db.denetim_yaz(
            conn, str(job.get("actor") or "sistem"), "gyazo_link_yerel_korundu",
            record["proje"] if record else None, record["anahtar"] if record else None,
            yeni={"sonuc": reason}, sonuc="uyari", hedef_turu="kayit",
            hedef_id=int(job["record_id"]) if job.get("record_id") is not None else None,
            aciklama="Görsel değişti; bağlantı kayda eklenmedi, yerel kanıt korunuyor.",
        )
        db.degisti(conn)


def _apply_remote_link(conn, job: dict) -> bool:
    """Apply a completed URL only to the exact evidence image it was queued for.

    ``expected_gorsel`` is captured at enqueue/bind time.  Keeping it on the
    durable job lets a user edit/replace the evidence while Gyazo is in flight
    without the old conversion overwriting the newer image's link.
    """
    record_id = job.get("record_id")
    expected = job.get("expected_gorsel")
    url = str(job.get("url") or "")[:2000]
    # ``record_id is None`` is a normal pre-confirmation state.  Keep it in
    # ``bekliyor`` so a successful conversion cannot generate a final bot
    # notice until ``bind_record`` supplies the confirmed local record.
    if record_id is None:
        return False
    if not expected or not url:
        _set_application_status(conn, job, False, reason="eksik_donusum_verisi")
        return False
    record = conn.execute(
        "SELECT id,proje,anahtar,link,link_turu,gorsel_dosya FROM kayitlar WHERE id=?",
        (int(record_id),),
    ).fetchone()
    if not record:
        _set_application_status(conn, job, False, reason="kayit_bulunamadi")
        return False
    if record["gorsel_dosya"] != expected:
        _set_application_status(conn, job, False, reason="gorsel_degisti", record=record)
        return False
    # Idempotent restart/rebind: the record already proves that this exact
    # URL was applied to the original image, even though no UPDATE is needed.
    if record["link"] == url and record["link_turu"] == "gyazo":
        _set_application_status(conn, job, True, reason="zaten_uygulandi", record=record)
        return True
    now = _now()
    updated = conn.execute(
        "UPDATE kayitlar SET link=?,link_turu='gyazo',surum=COALESCE(surum,0)+1,guncelleme=? "
        "WHERE id=? AND gorsel_dosya=? AND (link IS NOT ? OR COALESCE(link_turu,'')!='gyazo')",
        (url, now, int(record_id), expected, url),
    )
    if not updated.rowcount:
        latest = conn.execute(
            "SELECT id,proje,anahtar,link,link_turu,gorsel_dosya FROM kayitlar WHERE id=?",
            (int(record_id),),
        ).fetchone()
        if latest and latest["gorsel_dosya"] == expected and latest["link"] == url and latest["link_turu"] == "gyazo":
            _set_application_status(conn, job, True, reason="zaten_uygulandi", record=latest)
            return True
        _set_application_status(conn, job, False, reason="baglanti_guncellenemedi", record=latest)
        return False
    db.denetim_yaz(
        conn, str(job.get("actor") or "sistem"), "gyazo_link_guncelle",
        record["proje"], record["anahtar"],
        eski={"link": record["link"], "link_turu": record["link_turu"]},
        yeni={"link": url, "link_turu": "gyazo"}, hedef_turu="kayit",
        hedef_id=int(record_id), aciklama="Dönüşüm sonucu doğrulanmış görsel sürümüne bağlandı.",
    )
    _set_application_status(conn, job, True, reason="uygulandi", record=record)
    db.degisti(conn)
    return True


def _expired_uploads(conn, now: str) -> int:
    """Do not replay a POST whose process died after the request began."""
    result = conn.execute(
        "UPDATE donusum_isleri SET durum='belirsiz',ambiguous=1,hata=?,lease_owner=NULL,lease_until=NULL,guncelleme=? "
        "WHERE durum='calisiyor' AND phase='upload' AND lease_until<?",
        ("Gyazo yükleme isteğinin sonucu süreç kesintisi nedeniyle belirsiz; tekrar yükleme yapılmadı.", now, now),
    )
    return int(result.rowcount or 0)


def claim(conn, worker_id: str, *, lease_seconds: int = LEASE_SECONDS) -> Optional[dict]:
    """Claim one job atomically. The returned lease is owned by ``worker_id``."""
    ensure_schema(conn)
    now = _now()
    with db.transaction(conn):
        _expired_uploads(conn, now)
        row = conn.execute(
            "SELECT * FROM donusum_isleri WHERE "
            "(durum IN ('bekliyor','tekrar','verify') AND next_try<=?) OR "
            "(durum='calisiyor' AND phase='verify' AND lease_until<?) "
            "ORDER BY id LIMIT 1", (now, now),
        ).fetchone()
        if not row:
            return None
        lease = _later(lease_seconds)
        conn.execute("UPDATE donusum_isleri SET durum='calisiyor',lease_owner=?,lease_until=?,guncelleme=? WHERE id=?",
                     (str(worker_id)[:120], lease, now, row["id"]))
        return _row_dict(conn, int(row["id"]))


def _retry_or_terminal(conn, job: dict, result: dict, *, verify: bool) -> dict:
    attempts_key = "verify_deneme" if verify else "deneme"
    attempts = int(job.get(attempts_key) or 0) + 1
    retryable = bool(result.get("retryable")) and not bool(result.get("ambiguous"))
    status = result.get("http_status")
    error = str(result.get("error") or "Gyazo dönüşümü tamamlanamadı.")[:500]
    if retryable and attempts < MAX_ATTEMPTS:
        delay = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        # Successful upload enters the verify state.  A failed upload instead
        # remains in the upload phase and must be represented as ``tekrar``;
        # otherwise dashboards/tests can mistake an unsubmitted POST retry for
        # a CDN verification retry.
        next_state = "verify" if verify else "tekrar"
        conn.execute(
            f"UPDATE donusum_isleri SET durum=?,{attempts_key}=?,next_try=?,lease_owner=NULL,lease_until=NULL,http_status=?,hata=?,guncelleme=? WHERE id=?",
            (next_state, attempts, _later(delay), status, error, _now(), job["id"]),
        )
    else:
        final = "belirsiz" if result.get("ambiguous") else "hata"
        conn.execute(
            f"UPDATE donusum_isleri SET durum=?,{attempts_key}=?,ambiguous=?,lease_owner=NULL,lease_until=NULL,http_status=?,hata=?,guncelleme=? WHERE id=?",
            (final, attempts, 1 if result.get("ambiguous") else 0, status, error, _now(), job["id"]),
        )
    return _row_dict(conn, int(job["id"]))


def _finish_success(conn, job: dict, result: dict) -> dict:
    url = str(result.get("url") or "")[:2000]
    conn.execute(
        "UPDATE donusum_isleri SET durum='tamam',url=?,lease_owner=NULL,lease_until=NULL,http_status=?,hata=NULL,guncelleme=? WHERE id=?",
        (url, result.get("http_status"), _now(), job["id"]),
    )
    # ``job`` was the claim-time snapshot. A user can confirm/bind the record
    # while the network request is outstanding, so never use that stale dict
    # for the final evidence update.
    fresh = _row_dict(conn, int(job["id"]))
    if fresh and fresh.get("record_id") is not None:
        _apply_remote_link(conn, fresh)
    return _row_dict(conn, int(job["id"]))


def worker_step(conn, worker_id: str, *, upload: Optional[Callable[..., dict]] = None,
                verify: Optional[Callable[..., dict]] = None) -> Optional[dict]:
    """Claim and process at most one phase, with no DB transaction during network I/O.

    Inject ``upload`` / ``verify`` in tests. Default functions are
    ``app.gyazo.upload`` and ``app.gyazo.verify``.  The returned row is the
    resulting durable state, or ``None`` when no work is ready.
    """
    job = claim(conn, worker_id)
    if not job:
        return None
    if upload is None or verify is None:
        from . import gyazo
        upload = upload or gyazo.upload
        verify = verify or gyazo.verify
    try:
        if job.get("phase") == "upload":
            result = upload(job["local_path"])
        else:
            result = verify(job.get("image_id"), job.get("image_url"))
        if not isinstance(result, dict):
            result = {"ok": False, "error": "Gyazo geçersiz sonuç döndürdü.", "retryable": False}
    except Exception:
        # Never serialize exception text: provider responses could contain tokens.
        result = {"ok": False, "error": "Gyazo isteği güvenli şekilde tamamlanamadı.", "retryable": False, "ambiguous": job.get("phase") == "upload"}

    with db.transaction(conn):
        live = _row_dict(conn, int(job["id"]))
        if not live or live.get("durum") != "calisiyor" or live.get("lease_owner") != str(worker_id)[:120]:
            return live or None
        if result.get("ok"):
            if live.get("phase") == "upload":
                image_id = str(result.get("image_id") or "")[:80]
                image_url = str(result.get("image_url") or "")[:2000]
                if not image_id or not image_url:
                    return _retry_or_terminal(conn, live, {"error": "Gyazo yükleme kimliği geçersiz.", "retryable": False}, verify=False)
                conn.execute(
                    "UPDATE donusum_isleri SET durum='verify',phase='verify',image_id=?,image_url=?,http_status=?,lease_owner=NULL,lease_until=NULL,next_try=?,hata=NULL,guncelleme=? WHERE id=?",
                    (image_id, image_url, result.get("http_status"), _now(), _now(), live["id"]),
                )
                return _row_dict(conn, int(live["id"]))
            if not str(result.get("url") or ""):
                return _retry_or_terminal(
                    conn, live,
                    {"error": "Gyazo doğrulaması geçerli bir bağlantı döndürmedi.", "retryable": False},
                    verify=True,
                )
            return _finish_success(conn, live, result)
        return _retry_or_terminal(conn, live, result, verify=live.get("phase") == "verify")


def claim_notices(conn, limit: int = 20, *, bot_id: Optional[str] = None) -> list[dict]:
    """Reserve terminal notifications for Telegram-bound, confirmed jobs only.

    Web workers use the same durable queue but must never cause a Telegram bot
    to invent a chat notification for a site job. ``bot_id`` optionally scopes
    the reservation to the calling bot instance.
    """
    ensure_schema(conn)
    selected: list[dict] = []
    with db.transaction(conn):
        # A previous deployment can have a completed provider job without the
        # additive state fields. Re-check it before reserving any success
        # notice; a normal pre-bind result remains deliberately deferred.
        pending = conn.execute(
            "SELECT * FROM donusum_isleri WHERE record_id IS NOT NULL AND durum='tamam' "
            "AND uygulama_durumu='bekliyor'"
        ).fetchall()
        for row in pending:
            _apply_remote_link(conn, dict(row))
        where = (
            "record_id IS NOT NULL AND bot_id IS NOT NULL AND chat_id IS NOT NULL "
            "AND ((durum='tamam' AND uygulama_durumu IN ('uygulandi','uygulanmadi')) "
            "OR durum IN ('hata','belirsiz')) AND notice_durum!='tamam'"
        )
        params: list[Any] = []
        if bot_id is not None:
            where += " AND bot_id=?"
            params.append(str(bot_id))
        params.append(max(1, min(int(limit), 100)))
        rows = conn.execute(
            "SELECT * FROM donusum_isleri WHERE " + where + " ORDER BY id LIMIT ?",
            tuple(params),
        ).fetchall()
        for row in rows:
            # A process may die after reservation but before its outbox INSERT.
            # Retaining/reselecting ``kuyrukta`` is safe: the outbox action key
            # is unique and therefore no duplicate notification is delivered.
            conn.execute("UPDATE donusum_isleri SET notice_durum='kuyrukta',guncelleme=? WHERE id=? AND notice_durum!='tamam'",
                         (_now(), row["id"]))
            selected.append(dict(row))
    return selected


def mark_notice_delivered(conn, job_key: str, *, bot_id: Optional[str] = None) -> None:
    ensure_schema(conn)
    query = "UPDATE donusum_isleri SET notice_durum='tamam',guncelleme=? WHERE job_key=?"
    params: list[Any] = [_now(), str(job_key)]
    if bot_id is not None:
        query += " AND bot_id=?"
        params.append(str(bot_id))
    conn.execute(query, tuple(params))

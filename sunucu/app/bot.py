# -*- coding: utf-8 -*-
"""SQLite tabanlı Telegram kanıt botu.

Çalıştırma: ``python -m app.bot``

Bot yalnızca Telegram HTTP API'sini ``requests`` ile kullanır. Güncellemeler,
Telegram offset'i ilerletilmeden önce ``tg_gelen`` tablosuna kalıcı biçimde
alınır; bir çökme sonrasında bekleyen kayıtlar yeniden işlenir. Bu modül tokenı
loglamaz ve webhook'u değiştirmez/silmez.
"""
from __future__ import annotations

import contextlib
import hmac
import hashlib
import html
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
import warnings
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import requests
from PIL import Image, UnidentifiedImageError

from . import db
from . import donusum_isleri

LOG = logging.getLogger("kanit.telegram")
MAX_DENEME = 3
MAX_RETRY = 5
_RETRY_SECONDS = (5, 30, 120, 600)
_GECERLI_MODLAR = {"tek_uye", "ark_ana", "ana_only", "sessiz_tip"}
_GECERLI_FORMATLAR = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
_GUVENLI = re.compile(r"[^A-Za-z0-9_.-]+")
_TOKEN_URL = re.compile(r"(bot)(?:\d+:[A-Za-z0-9_-]+)", re.I)
_GYAZO_URL = re.compile(r"^https?://(?:[a-z0-9-]+\.)?gyazo\.com/[^\s]+$", re.I)

# db.py ortak şemasına dokunmadan bot teslimatları ve indirilmiş medya için
# kendi küçük, yeniden başlatmaya dayanıklı tablolarımız. API çağrıları bu
# tablolara yazan transaction tamamlandıktan sonra yapılır.
BOT_SEMA = """
CREATE TABLE IF NOT EXISTS tg_giden (
 id INTEGER PRIMARY KEY, bot_id TEXT NOT NULL, source_update_id INTEGER,
 action_key TEXT NOT NULL, tur TEXT NOT NULL, chat_id TEXT NOT NULL, user_id TEXT,
 message_id INTEGER, replace_message_id INTEGER, job_key TEXT, metin TEXT, klavye TEXT, guard_revision INTEGER,
 durum TEXT NOT NULL DEFAULT 'bekliyor', deneme INTEGER NOT NULL DEFAULT 0, hata TEXT,
 olusturma TEXT NOT NULL, guncelleme TEXT NOT NULL,
 UNIQUE(bot_id, action_key)
);
CREATE INDEX IF NOT EXISTS ix_tg_giden_bekleyen ON tg_giden(bot_id,durum,guncelleme,id);
CREATE TABLE IF NOT EXISTS tg_indirilen (
 bot_id TEXT NOT NULL, update_id INTEGER NOT NULL, chat_id TEXT NOT NULL, message_id INTEGER NOT NULL,
 pending_path TEXT NOT NULL, extension TEXT NOT NULL, olusturma TEXT NOT NULL,
 PRIMARY KEY(bot_id,update_id)
);
CREATE INDEX IF NOT EXISTS ix_tg_indirilen_mesaj ON tg_indirilen(bot_id,chat_id,message_id);
CREATE TABLE IF NOT EXISTS tg_donusum_cache (
 bot_id TEXT NOT NULL, update_id INTEGER NOT NULL, pending_path TEXT NOT NULL,
 ok INTEGER NOT NULL DEFAULT 0, url TEXT, hata TEXT, guncelleme TEXT NOT NULL,
 PRIMARY KEY(bot_id,update_id)
);
"""


class TelegramHatasi(RuntimeError):
    """Telegram API veya indirilen dosya doğrulama hatası."""


def _simdi() -> str:
    return db.simdi()


def _redact(value: Any) -> str:
    """İstek istisnalarındaki token ve olası parolaları log öncesi maskeler."""
    text = str(value or "")
    text = _TOKEN_URL.sub(r"\1***", text)
    text = re.sub(r"((?:token|password|sifre)\s*[=:]\s*)\S+", r"\1***", text, flags=re.I)
    return text


def _safe_piece(value: Any, limit: int = 32) -> str:
    value = _GUVENLI.sub("_", str(value or "").strip())
    value = value.strip("._") or "x"
    return value[:limit]


def _h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


class TelegramAPI:
    """Küçük, kolay taklit edilebilir requests Telegram API istemcisi."""

    def __init__(self, token: str, session=None, api_base: str = "https://api.telegram.org", timeout: int = 40):
        self.token = token
        self.session = session or requests.Session()
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _method_url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def _file_url(self, remote_path: str) -> str:
        # Telegram file_path mutlak URL veya dizin geçişi olamaz.
        remote_path = str(remote_path or "").lstrip("/")
        if not remote_path or ".." in Path(remote_path).parts:
            raise TelegramHatasi("Geçersiz Telegram dosya yolu")
        return f"{self.api_base}/file/bot{self.token}/{remote_path}"

    def call(self, method: str, payload: Optional[dict] = None, timeout: Optional[int] = None) -> Any:
        try:
            response = self.session.post(self._method_url(method), json=payload or {}, timeout=timeout or self.timeout)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError, OSError) as exc:
            raise TelegramHatasi(_redact(exc)) from exc
        if not isinstance(data, dict) or not data.get("ok"):
            description = data.get("description", "Telegram API yanıtı geçersiz") if isinstance(data, dict) else "Telegram API yanıtı geçersiz"
            raise TelegramHatasi(_redact(description))
        return data.get("result")

    def get_updates(self, offset: int, timeout: int = 25):
        return self.call("getUpdates", {"offset": int(offset), "timeout": int(timeout), "limit": 100}, timeout=timeout + 15) or []

    def get_file(self, file_id: str):
        result = self.call("getFile", {"file_id": file_id}, timeout=20)
        if not isinstance(result, dict) or not result.get("file_path"):
            raise TelegramHatasi("Telegram dosya bilgisi eksik")
        return result

    def download(self, remote_path: str, max_bytes: int) -> bytes:
        try:
            response = self.session.get(self._file_url(remote_path), stream=True, timeout=40)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            content_length = getattr(response, "headers", {}).get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise TelegramHatasi("Dosya izinli boyut sınırını aşıyor")
            chunks = []
            total = 0
            iterator = response.iter_content(chunk_size=64 * 1024) if hasattr(response, "iter_content") else [response.content]
            for chunk in iterator:
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise TelegramHatasi("Dosya izinli boyut sınırını aşıyor")
                chunks.append(chunk)
            return b"".join(chunks)
        except TelegramHatasi:
            raise
        except (requests.RequestException, OSError, ValueError) as exc:
            raise TelegramHatasi(_redact(exc)) from exc

    def send_message(self, chat_id: str, text: str, keyboard: Optional[list] = None) -> Optional[int]:
        payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        result = self.call("sendMessage", payload, timeout=20)
        return int(result["message_id"]) if isinstance(result, dict) and result.get("message_id") is not None else None

    def edit_message(self, chat_id: str, message_id: int, text: str, keyboard: Optional[list] = None) -> None:
        payload = {"chat_id": chat_id, "message_id": int(message_id), "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True}
        if keyboard is not None:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        self.call("editMessageText", payload, timeout=20)

    def answer_callback(self, callback_id: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id}, timeout=10)

    def delete_message(self, chat_id: str, message_id: int) -> None:
        self.call("deleteMessage", {"chat_id": chat_id, "message_id": int(message_id)}, timeout=10)


class BotLock:
    """Bot kimliği başına tek süreç kilidi; POSIX flock, Windows msvcrt, son çare dosya kilidi."""

    def __init__(self, path: Path):
        self.path = path
        self.file = None
        self.kind = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        if os.name == "posix":
            try:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.kind = "flock"
                return True
            except BlockingIOError:
                self.file.close()
                self.file = None
                return False
        if os.name == "nt":
            try:
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                self.kind = "msvcrt"
                return True
            except OSError:
                self.file.close()
                self.file = None
                return False
        # Nadir platform fallback'i: atomik oluşturma. Süreç öldürülürse dosya
        # kalabilir; normal platformlar flock/msvcrt yolunu kullanır.
        self.file.close()
        self.file = None
        try:
            fd = os.open(str(self.path) + ".portable", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            self.kind = "portable"
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if self.kind == "portable":
            with contextlib.suppress(OSError):
                os.unlink(str(self.path) + ".portable")
        elif self.file:
            with contextlib.suppress(Exception):
                if self.kind == "flock":
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
                elif self.kind == "msvcrt":
                    import msvcrt
                    self.file.seek(0)
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()
        self.file = None
        self.kind = None

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Bu bot için başka bir süreç zaten çalışıyor.")
        return self

    def __exit__(self, *exc):
        self.release()


class KanitBot:
    """Kalıcı inbox ve kullanıcı akışının uygulama servisi."""

    def __init__(self, ayar: dict, token: Optional[str] = None, api: Optional[TelegramAPI] = None, bot_id: Optional[str] = None):
        self.ayar = dict(ayar)
        self.token = token if token is not None else os.environ.get("TELEGRAM_TOKEN", "")
        candidate = bot_id or (self.token.split(":", 1)[0] if ":" in self.token else "")
        self.bot_id = _safe_piece(candidate or "tanimsiz", 64)
        self.api = api or (TelegramAPI(self.token) if self.token else None)
        self.media_root = Path(self.ayar["GORSEL_KLASOR"]).resolve()
        self.media_root.mkdir(parents=True, exist_ok=True)
        (self.media_root / "pending").mkdir(parents=True, exist_ok=True)
        self._stopped = False
        # Bu alanlar yalnızca tek bot sürecinin bir update transaction'ı boyunca
        # kullanılır; API çağrısına asla bu sırada izin verilmez.
        self._outbox_context: Optional[dict] = None
        self._post_commit: Optional[list] = None

    # ---- bağlantı, log ve kalıcı inbox -------------------------------------------------
    def _conn(self):
        conn = db.baglan(self.ayar["DB"])
        conn.executescript(BOT_SEMA)
        # Eski kurulumlardaki outbox'a yalnız ek sütun eklenir; db.py ortak
        # şemasına dokunulmaz. Dönüşüm işleri de parent/site aynı API'yi çağırabilir.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tg_giden)")}
        for name, kind in (("replace_message_id", "INTEGER"), ("job_key", "TEXT")):
            if name not in columns:
                conn.execute(f"ALTER TABLE tg_giden ADD COLUMN {name} {kind}")
        donusum_isleri.ensure_schema(conn)
        # Katalog ajanı henüz ortak dosyayı teslim etmemiş eski deploylarda bot
        # dört legacy modu korur; dosya geldiğinde public API otomatik kullanılır.
        try:
            from . import katalog
            katalog.ensure_schema(conn)
        except (ImportError, AttributeError):
            pass
        return conn

    def _log(self, level: int, message: Any) -> None:
        line = f"[{_simdi()}] {_redact(message)}"
        LOG.log(level, line)
        path = Path(self.ayar.get("LOG_DOSYA") or Path(self.ayar["BOT_KLASOR"]) / "bot_log.txt")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _heartbeat(self, hata: Optional[str] = None, username: Optional[str] = None) -> None:
        conn = self._conn()
        try:
            with db.transaction(conn):
                previous = conn.execute("SELECT offset,username FROM tg_durum WHERE bot_id=?", (self.bot_id,)).fetchone()
                offset = int(previous["offset"] or 0) if previous else 0
                conn.execute(
                    "INSERT INTO tg_durum(bot_id,offset,heartbeat,username,hata) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(bot_id) DO UPDATE SET heartbeat=excluded.heartbeat,username=COALESCE(excluded.username,tg_durum.username),hata=excluded.hata",
                    (self.bot_id, offset, _simdi(), username, _redact(hata)[:1000] if hata else None),
                )
        finally:
            conn.close()

    def _offset(self, conn) -> int:
        row = conn.execute("SELECT offset FROM tg_durum WHERE bot_id=?", (self.bot_id,)).fetchone()
        return int(row["offset"] or 0) if row else 0

    def _durable_insert(self, updates: list[dict]) -> int:
        """Güncellemeleri ve bir sonraki offset'i aynı transaction'da kalıcılaştırır."""
        if not updates:
            self._heartbeat()
            return 0
        conn = self._conn()
        try:
            with db.transaction(conn):
                current = self._offset(conn)
                maximum = current
                now = _simdi()
                for update in updates:
                    if not isinstance(update, dict) or "update_id" not in update:
                        continue
                    uid = int(update["update_id"])
                    payload = json.dumps(update, ensure_ascii=False, separators=(",", ":"))
                    conn.execute(
                        "INSERT OR IGNORE INTO tg_gelen(bot_id,update_id,veri,durum,deneme,hata,olusturma,guncelleme) VALUES(?,?,?,'bekliyor',0,NULL,?,?)",
                        (self.bot_id, uid, payload, now, now),
                    )
                    maximum = max(maximum, uid + 1)
                conn.execute(
                    "INSERT INTO tg_durum(bot_id,offset,heartbeat,hata) VALUES(?,?,?,NULL) "
                    "ON CONFLICT(bot_id) DO UPDATE SET offset=MAX(tg_durum.offset,excluded.offset),heartbeat=excluded.heartbeat,hata=NULL",
                    (self.bot_id, maximum, now),
                )
            return len(updates)
        finally:
            conn.close()

    def _has_outbox_retry(self) -> bool:
        """Yeniden denenecek yardımcı iş varken uzun polling'i kısa tutar."""
        conn = self._conn()
        try:
            return bool(conn.execute(
                "SELECT 1 FROM tg_giden WHERE bot_id=? AND durum='tekrar' LIMIT 1", (self.bot_id,)
            ).fetchone())
        finally:
            conn.close()

    def poll_once(self, timeout: int = 25) -> int:
        if not self.api:
            raise TelegramHatasi("TELEGRAM_TOKEN ayarlanmamış")
        conn = self._conn()
        try:
            offset = self._offset(conn)
        finally:
            conn.close()
        # Bekleyen teslimat tekrarları 25 sn long-poll arkasında kalmasın.
        timeout = min(int(timeout), 2) if self._has_outbox_retry() else int(timeout)
        updates = self.api.get_updates(offset, timeout)
        if not isinstance(updates, list):
            raise TelegramHatasi("getUpdates sonucu liste değil")
        return self._durable_insert(updates)

    def process_pending(self, limit: int = 50) -> int:
        """Kalıcı gelen kutusunu işler; durum geçişi ile inbox ack aynı commit'tedir."""
        conn = self._conn()
        try:
            now = _simdi()
            rows = conn.execute(
                "SELECT update_id,veri,deneme FROM tg_gelen WHERE bot_id=? AND "
                "(durum='bekliyor' OR (durum='tekrar' AND guncelleme<=?)) ORDER BY update_id LIMIT ?",
                (self.bot_id, now, max(1, min(limit, 200))),
            ).fetchall()
        finally:
            conn.close()
        done = 0
        for row in rows:
            try:
                update = json.loads(row["veri"])
                self.handle_update(update, inbox_update_id=int(row["update_id"]))
            except Exception as exc:  # transaction rollback; offset kaybolmadan geri dene
                attempt = int(row["deneme"] or 0) + 1
                message = _redact(exc)[:1000]
                retry_at = _simdi()
                state = "olu"
                if attempt < MAX_RETRY:
                    delay = _RETRY_SECONDS[min(attempt - 1, len(_RETRY_SECONDS) - 1)]
                    retry_at = (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                    state = "tekrar"
                conn2 = self._conn()
                try:
                    with db.transaction(conn2):
                        conn2.execute(
                            "UPDATE tg_gelen SET durum=?,deneme=?,hata=?,guncelleme=? WHERE bot_id=? AND update_id=? "
                            "AND durum!='tamam'",
                            (state, attempt, message, retry_at, self.bot_id, row["update_id"]),
                        )
                        conn2.execute("UPDATE tg_durum SET heartbeat=?,hata=? WHERE bot_id=?", (_simdi(), message, self.bot_id))
                finally:
                    conn2.close()
                self._log(logging.WARNING, f"Güncelleme {row['update_id']} {state}: {message}")
            else:
                done += 1
        # API çağrıları tüm iş/ack transaction'larından sonra yürür. Böylece
        # geçici Telegram kesintisi kullanıcı durumunu ya da inbox'ı geri almaz.
        self.process_outbox(limit=max(10, limit * 3))
        return done

    def _queue_outbox(self, conn, tur: str, chat_id: str, text: str = "", keyboard: Optional[list] = None,
                      message_id: Optional[int] = None, user_id: Optional[str] = None,
                      guard_revision: Optional[int] = None, replace_message_id: Optional[int] = None,
                      job_key: Optional[str] = None) -> str:
        """Yanıtı aynı iş transaction'ında kalıcı sıraya ekler; burada ağ yoktur."""
        context = self._outbox_context
        if context is None or context.get("conn") is not conn:
            raise RuntimeError("Telegram yanıtı transaction dışından kuyruğa eklenemez")
        context["sequence"] += 1
        source_id = int(context["update_id"])
        key = f"u{source_id}:{context['sequence']}:{tur}"
        now = _simdi()
        conn.execute(
            "INSERT OR IGNORE INTO tg_giden(bot_id,source_update_id,action_key,tur,chat_id,user_id,message_id,replace_message_id,job_key,metin,klavye,guard_revision,durum,deneme,hata,olusturma,guncelleme) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'bekliyor',0,NULL,?,?)",
            (self.bot_id, source_id, key, tur, str(chat_id), None if user_id is None else str(user_id),
             message_id, replace_message_id, job_key, str(text or ""), json.dumps(keyboard, ensure_ascii=False, separators=(",", ":")) if keyboard is not None else None,
             guard_revision, now, now),
        )
        return key

    def _outbox_guard_current(self, row) -> bool:
        """Eski bir render'ın yeni ekranı ezmesini veya eski UI'ye bağlanmasını engeller."""
        if row["guard_revision"] is None:
            return True
        user_id = row["user_id"]
        if not user_id:
            return False
        conn = self._conn()
        try:
            session = self._get_session(conn, str(user_id))
            if not session or int(session.get("ui_revision") or 0) != int(row["guard_revision"]):
                return False
            if row["tur"] == "send":
                return session.get("ui_pending_key") == row["action_key"]
            return int(session.get("ui_message_id") or -1) == int(row["message_id"] or -2)
        finally:
            conn.close()

    def _finish_outbox(self, row, delivered_message_id: Optional[int] = None, error: Optional[Exception] = None) -> None:
        conn = self._conn()
        try:
            with db.transaction(conn):
                if error is None:
                    conn.execute("UPDATE tg_giden SET durum='tamam',hata=NULL,guncelleme=? WHERE id=?", (_simdi(), row["id"]))
                    # New UI is always sent at the bottom. Once delivery succeeds,
                    # remove the former active UI instead of editing it in place.
                    if row["tur"] == "send" and row["guard_revision"] is not None and delivered_message_id is not None:
                        session = self._get_session(conn, str(row["user_id"]))
                        if session and int(session.get("ui_revision") or 0) == int(row["guard_revision"]) and session.get("ui_pending_key") == row["action_key"]:
                            session["ui_message_id"] = int(delivered_message_id)
                            session.pop("ui_pending_key", None)
                            self._save_session(conn, str(row["user_id"]), session)
                    if row["tur"] == "send" and row["replace_message_id"] is not None:
                        delete_key = f"{row['action_key']}:replace"
                        conn.execute(
                            "INSERT OR IGNORE INTO tg_giden(bot_id,source_update_id,action_key,tur,chat_id,user_id,message_id,metin,durum,deneme,olusturma,guncelleme) VALUES(?,?,?,?,?,?,?,'','bekliyor',0,?,?)",
                            (self.bot_id, row["source_update_id"], delete_key, "delete", row["chat_id"], row["user_id"], int(row["replace_message_id"]), _simdi(), _simdi()),
                        )
                    if row["tur"] == "send" and row["job_key"]:
                        # A terminal conversion notice belongs only to this
                        # bot. Site jobs share the worker API but never get a
                        # Telegram delivery state from an unrelated bot.
                        donusum_isleri.mark_notice_delivered(conn, str(row["job_key"]), bot_id=self.bot_id)
                    return
                attempt = int(row["deneme"] or 0) + 1
                delay = _RETRY_SECONDS[min(attempt - 1, len(_RETRY_SECONDS) - 1)]
                retry_at = (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    "UPDATE tg_giden SET durum='tekrar',deneme=?,hata=?,guncelleme=? WHERE id=? AND durum!='tamam'",
                    (attempt, _redact(error)[:1000], retry_at, row["id"]),
                )
        finally:
            conn.close()

    def process_outbox(self, limit: int = 100) -> int:
        """Teslimat kuyruğunu DB kilidi tutmadan gönderir; başarısız mesajlar geri denenir."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM tg_giden WHERE bot_id=? AND (durum='bekliyor' OR (durum='tekrar' AND guncelleme<=?)) "
                "ORDER BY CASE WHEN tur='answer' THEN 0 WHEN tur IN ('send','edit') THEN 1 ELSE 2 END, id LIMIT ?",
                (self.bot_id, _simdi(), max(1, min(limit, 500)))
            ).fetchall()
        finally:
            conn.close()
        sent = 0
        for row in rows:
            if not self._outbox_guard_current(row):
                self._finish_outbox(row)  # stale render: gönderme, fakat tekrar da etme
                continue
            try:
                keyboard = json.loads(row["klavye"]) if row["klavye"] else None
                result = None
                if not self.api:
                    raise TelegramHatasi("TELEGRAM_TOKEN ayarlanmamış")
                if row["tur"] == "send":
                    result = self.api.send_message(row["chat_id"], row["metin"], keyboard)
                elif row["tur"] == "edit":
                    self.api.edit_message(row["chat_id"], int(row["message_id"]), row["metin"], keyboard)
                elif row["tur"] == "delete":
                    self.api.delete_message(row["chat_id"], int(row["message_id"]))
                elif row["tur"] == "answer":
                    self.api.answer_callback(row["metin"])
                else:
                    raise TelegramHatasi("Bilinmeyen giden mesaj türü")
            except Exception as exc:
                self._finish_outbox(row, error=exc)
                self._log(logging.WARNING, f"Mesaj teslim edilemedi: {exc}")
            else:
                self._finish_outbox(row, result)
                sent += 1
        return sent

    # ---- kullanıcı ve oturum ------------------------------------------------------------
    def _touch_user(self, conn, user: dict) -> dict:
        uid = str(user.get("id") or "")
        if not uid:
            raise TelegramHatasi("Telegram kullanıcı kimliği eksik")
        username = str(user.get("username") or "")[:120]
        first = str(user.get("first_name") or "")[:120]
        conn.execute(
            "INSERT INTO tg_kullanicilar(id,username,first_name,last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_seen=excluded.last_seen",
            (uid, username, first, _simdi()),
        )
        row = conn.execute("SELECT * FROM tg_kullanicilar WHERE id=?", (uid,)).fetchone()
        return dict(row)

    def _authorized(self, conn, profile: Optional[dict], user_id: str) -> bool:
        """Onay, bot kimliği bazlı ilk başarılı giriş olmadan bu botta yetki vermez."""
        if not profile or not bool(profile.get("onayli")) or bool(profile.get("engelli")):
            return False
        return bool(conn.execute(
            "SELECT 1 FROM tg_girisler WHERE bot_id=? AND user_id=?", (self.bot_id, str(user_id))
        ).fetchone())

    def _get_session(self, conn, user_id: str) -> Optional[dict]:
        row = conn.execute("SELECT veri FROM tg_oturumlar WHERE bot_id=? AND user_id=?", (self.bot_id, user_id)).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row["veri"])
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError):
            return None

    def _save_session(self, conn, user_id: str, value: dict) -> None:
        conn.execute(
            "INSERT INTO tg_oturumlar(bot_id,user_id,veri,guncelleme) VALUES(?,?,?,?) "
            "ON CONFLICT(bot_id,user_id) DO UPDATE SET veri=excluded.veri,guncelleme=excluded.guncelleme",
            (self.bot_id, user_id, json.dumps(value, ensure_ascii=False, separators=(",", ":")), _simdi()),
        )

    def _delete_session(self, conn, user_id: str) -> None:
        conn.execute("DELETE FROM tg_oturumlar WHERE bot_id=? AND user_id=?", (self.bot_id, user_id))

    def _remove_pending_now(self, pending_path: Any) -> None:
        if not pending_path:
            return
        try:
            path = (self.media_root / str(pending_path)).resolve()
            if self.media_root in path.parents and path.parent.name == "pending":
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def _remove_pending(self, session: Optional[dict]) -> None:
        """Pending silme işlemini DB commit'inden sonrasına erteler."""
        pending_path = session.get("pending_path") if session else None
        if not pending_path:
            return
        if self._post_commit is not None:
            self._post_commit.append(("remove_pending", str(pending_path)))
        else:
            self._remove_pending_now(pending_path)

    def _maintenance(self, conn) -> bool:
        return db.ayar_al(conn, "bakim_modu", "0") == "1"

    def _is_allowed_admin(self, user_id: str) -> bool:
        ids = {x.strip() for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()}
        return bool(ids) and user_id in ids

    def _admin_active(self, session: Optional[dict]) -> bool:
        try:
            return float(session.get("admin_until", 0)) > time.time()
        except (AttributeError, TypeError, ValueError):
            return False

    def _admin_command(self, conn, chat_id: str, user: dict, text: str, session: Optional[dict]) -> tuple[bool, Optional[dict]]:
        """(işlendi_mi, güncel_oturum) — temel yönetici komutları."""
        uid = str(user["id"])
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        if session and session.get("admin_prompt") and text and not text.startswith("/"):
            session.pop("admin_prompt", None)
            expected = os.environ.get("ADMIN_PASSWORD", "")
            if self._is_allowed_admin(uid) and expected and hmac.compare_digest(expected, text):
                session["admin_until"] = int(time.time()) + 3600
                self._save_session(conn, uid, session)
                self._say(chat_id, "<b>Yönetici girişi başarılı.</b> Oturum 60 dakika geçerlidir.")
            else:
                self._save_session(conn, uid, session)
                self._say(chat_id, "Yönetici girişi başarısız.")
            return True, session
        if cmd == "/admin":
            if not self._is_allowed_admin(uid) or not os.environ.get("ADMIN_PASSWORD"):
                self._say(chat_id, "Bu Telegram ID için yönetici erişimi tanımlı değil.")
                return True, session
            session = session or {"step": "idle"}
            session["admin_prompt"] = int(time.time()) + 300
            self._save_session(conn, uid, session)
            self._say(chat_id, "Yönetici parolasını yazın.")
            return True, session
        if cmd == "/admin_cikis":
            if session:
                session.pop("admin_until", None)
                session.pop("admin_prompt", None)
                self._save_session(conn, uid, session)
            self._say(chat_id, "Yönetici oturumu kapatıldı.")
            return True, session
        # Büyük eski Telegram yönetim komutları ayrı modülde tutulur. Modül
        # geçici olarak yoksa güvenli biçimde yerleşik sınırlı komutlara düşer.
        try:
            from .admin_commands import process as process_admin_command
        except ImportError:
            process_admin_command = None
        if process_admin_command and process_admin_command(self, conn, chat_id, user, text, session):
            return True, session
        admin_commands = {"/durum", "/bakim", "/bakim_ac", "/bakim_kapat", "/kategori_liste", "/engel", "/engel_kaldir", "/oturumlar"}
        if cmd not in admin_commands:
            return False, session
        if not self._admin_active(session):
            self._say(chat_id, "Bu komut için önce /admin ile giriş yapın.")
            return True, session
        if cmd == "/durum":
            users = conn.execute("SELECT COUNT(*) FROM tg_kullanicilar").fetchone()[0]
            inbox = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE bot_id=? AND durum IN ('bekliyor','tekrar')", (self.bot_id,)).fetchone()[0]
            dead = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE bot_id=? AND durum='olu'", (self.bot_id,)).fetchone()[0]
            self._say(chat_id, f"<b>DURUM</b>\nBakım: {'açık' if self._maintenance(conn) else 'kapalı'}\nKullanıcı: {users}\nBekleyen: {inbox}\nÖlü mektup: {dead}")
        elif cmd in {"/bakim", "/bakim_ac", "/bakim_kapat"}:
            val = arg.lower() if cmd == "/bakim" else ("ac" if cmd.endswith("_ac") else "kapat")
            if val in {"ac", "aç", "on", "1"}:
                db.ayar_yaz(conn, "bakim_modu", "1")
                db.denetim_yaz(conn, uid, "bot_bakim_ac")
                db.degisti(conn)
                self._say(chat_id, "Bakım modu açıldı.")
            elif val in {"kapat", "off", "0"}:
                db.ayar_yaz(conn, "bakim_modu", "0")
                db.denetim_yaz(conn, uid, "bot_bakim_kapat")
                db.degisti(conn)
                self._say(chat_id, "Bakım modu kapatıldı.")
            else:
                self._say(chat_id, "Kullanım: /bakim ac|kapat")
        elif cmd == "/kategori_liste":
            rows = conn.execute("SELECT code,label,mode FROM kategoriler WHERE aktif=1 ORDER BY label").fetchall()
            text_out = "<b>KATEGORİLER</b>\n" + ("\n".join(f"{_h(r['label'])} — <code>{_h(r['code'])}</code> ({_h(r['mode'])})" for r in rows) or "Kayıt yok.")
            self._say(chat_id, text_out)
        elif cmd == "/engel":
            target, _, reason = arg.partition(" ")
            if not target:
                self._say(chat_id, "Kullanım: /engel TELEGRAM_ID [sebep]")
            else:
                conn.execute(
                    "INSERT INTO tg_kullanicilar(id,engelli,onayli,engel_sebep,last_seen,deneme) VALUES(?,1,0,?,?,3) "
                    "ON CONFLICT(id) DO UPDATE SET engelli=1,onayli=0,engel_sebep=excluded.engel_sebep,deneme=3",
                    (target[:64], reason[:300] or "Yönetici engeli", _simdi()),
                )
                conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (target[:64],))
                conn.execute("DELETE FROM tg_girisler WHERE bot_id=? AND user_id=?", (self.bot_id, target[:64]))
                db.denetim_yaz(conn, uid, "bot_engelle", yeni=target[:64])
                db.degisti(conn)
                self._say(chat_id, f"{_h(target)} engellendi.")
        elif cmd == "/engel_kaldir":
            if not arg:
                self._say(chat_id, "Kullanım: /engel_kaldir TELEGRAM_ID")
            else:
                conn.execute("UPDATE tg_kullanicilar SET engelli=0,onayli=0,engel_sebep=NULL,deneme=0 WHERE id=?", (arg[:64],))
                conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (arg[:64],))
                conn.execute("DELETE FROM tg_girisler WHERE bot_id=? AND user_id=?", (self.bot_id, arg[:64]))
                db.denetim_yaz(conn, uid, "bot_engel_kaldir", yeni=arg[:64])
                db.degisti(conn)
                self._say(chat_id, f"{_h(arg)} engeli kaldırıldı; yeniden parola gerekir.")
        elif cmd == "/oturumlar":
            rows = conn.execute("SELECT user_id,veri FROM tg_oturumlar WHERE bot_id=? ORDER BY guncelleme DESC LIMIT 30", (self.bot_id,)).fetchall()
            vals = []
            for r in rows:
                try:
                    vals.append(f"{_h(r['user_id'])}: {_h(json.loads(r['veri']).get('step','?'))}")
                except (TypeError, ValueError):
                    pass
            self._say(chat_id, "<b>AKTİF OTURUMLAR</b>\n" + ("\n".join(vals) or "Yok."))
        return True, session

    # ---- Telegram ile yanıt (kalıcı outbox; transaction sırasında ağ yok) ---------------
    def _say(self, chat_id: str, text: str, keyboard: Optional[list] = None) -> Optional[int]:
        self._queue_outbox(self._outbox_context["conn"], "send", str(chat_id), text, keyboard)
        return None

    def _edit(self, chat_id: str, message_id: int, text: str, keyboard: Optional[list] = None) -> bool:
        self._queue_outbox(self._outbox_context["conn"], "edit", str(chat_id), text, keyboard, int(message_id))
        return True

    def _answer_callback(self, callback_id: str, chat_id: str) -> None:
        if callback_id:
            self._queue_outbox(self._outbox_context["conn"], "answer", str(chat_id), str(callback_id))

    def _delete_user_message(self, chat_id: str, message_id: int) -> None:
        self._queue_outbox(self._outbox_context["conn"], "delete", str(chat_id), message_id=int(message_id))

    def _delete_typed_message(self, chat_id: str, message_id: int, sensitive: bool = False) -> None:
        """Parola her zaman silinmeye çalışılır; diğer alanlar opt-in temizlenir."""
        if sensitive or os.environ.get("TELEGRAM_CLEANUP", "0") == "1":
            self._delete_user_message(chat_id, message_id)

    def _decorate_keyboard(self, conn, user_id: str, keyboard: Optional[list]) -> Optional[list]:
        """Sabit, gerçek Telegram native style politikası; hex/tema iddiası yok."""
        if keyboard is None:
            return None
        result = []
        for row in keyboard:
            out = []
            for raw in row:
                button = dict(raw)
                data = str(button.get("callback_data") or "")
                if data.startswith(("p:", "k:", "storage:", "t:", "q:")) or data == "lead:change":
                    button["style"] = "primary"
                elif data in {"confirm", "lead:ok"}:
                    button["style"] = "success"
                elif data in {"cancel", "lead:exit", "cancel:start"}:
                    button["style"] = "danger"
                # Other buttons deliberately omit style and use Telegram defaults.
                out.append(button)
            result.append(out)
        return result

    def _show(self, conn, user_id: str, session: dict, chat_id: str, text: str, keyboard: Optional[list]) -> None:
        """Her aktif adımı altta yeni bir UI ile teslim eder; eski UI sonra silinir."""
        keyboard = self._decorate_keyboard(conn, user_id, keyboard)
        revision = int(session.get("ui_revision") or 0) + 1
        session["ui_revision"] = revision
        old_ui = session.get("ui_message_id")
        session.pop("ui_pending_key", None)
        key = self._queue_outbox(conn, "send", str(chat_id), text, keyboard, None, str(user_id), revision,
                                 replace_message_id=int(old_ui) if old_ui else None)
        session["ui_pending_key"] = key
        self._save_session(conn, user_id, session)

    def _terminal(self, conn, chat_id: str, previous_message_id: Optional[int], text: str, *, job_key: Optional[str] = None) -> None:
        """Send a terminal result at the bottom, deleting the prior active UI after delivery."""
        self._queue_outbox(conn, "send", str(chat_id), text, None, None, None, None,
                           replace_message_id=int(previous_message_id) if previous_message_id else None,
                           job_key=job_key)

    def _cancel_conversion(self, conn, session: Optional[dict]) -> None:
        if not session or not session.get("conversion_job_key"):
            return
        donusum_isleri.cancel(conn, job_key=str(session["conversion_job_key"]))

    # ---- klavyeler ve ekran metinleri ----------------------------------------------------
    @staticmethod
    def _button(text: str, data: str) -> dict:
        return {"text": text, "callback_data": data}

    def _catalog(self):
        try:
            from . import katalog
            return katalog
        except ImportError:
            return None

    def _project_rows(self, conn) -> list[dict]:
        """Katalog API hazır olduğunda aktif dinamik projeler, aksi halde legacy ayar."""
        configured = {str(x).upper() for x in self.ayar.get("PROJELER", [])}
        catalog = self._catalog()
        if catalog and hasattr(catalog, "list_projects"):
            try:
                # Katalog mevcutsa aktiflik ve bot üyeliği katalogdaki proje
                # kaydıdır. Legacy ``PROJELER`` yalnız katalog bulunmayan eski
                # kurulumların fallback'i olabilir; burada ikinci bir filtre
                # yeni eklenen projeyi klavye/callback/final kayıttan düşürür.
                return [dict(row) for row in catalog.list_projects(conn, active_only=True)]
            except Exception as exc:
                self._log(logging.WARNING, f"Katalog proje seçimi okunamadı: {exc}")
        return [{"code": code, "label": code, "aktif": 1, "revision": None}
                for code in sorted(configured)]

    def _project_codes(self, conn) -> set[str]:
        return {str(row.get("code") or "").upper() for row in self._project_rows(conn)}

    def _project_keyboard(self, conn):
        rows = self._project_rows(conn)
        return [[self._button(str(row.get("label") or row.get("code")), f"p:{str(row.get('code')).upper()}")
                 for row in rows[i:i + 3]] for i in range(0, len(rows), 3)]

    def _category_rows(self, conn, project: str) -> list[dict]:
        catalog = self._catalog()
        if catalog and hasattr(catalog, "list_categories"):
            try:
                return [dict(row) for row in catalog.list_categories(conn, project_code=project, active_only=True)]
            except Exception as exc:
                self._log(logging.WARNING, f"Katalog kategori seçimi okunamadı: {exc}")
        return [dict(row) for row in conn.execute(
            "SELECT code,label,mode,aktif FROM kategoriler WHERE aktif=1 ORDER BY label COLLATE NOCASE").fetchall()]

    def _category_keyboard(self, conn, project: str):
        rows = self._category_rows(conn, project)
        keys = [[self._button(str(r["label"]), f"k:{r['code']}") for r in rows[i:i + 3]] for i in range(0, len(rows), 3)]
        keys.append([self._button("← Geri", "back:project")])
        return keys

    def _category_snapshot(self, conn, code: str, project: str) -> Optional[dict]:
        """Get active project membership plus immutable ordered question snapshot."""
        catalog = self._catalog()
        if catalog and hasattr(catalog, "get_category"):
            try:
                row = catalog.get_category(conn, code, project_code=project)
                if not row:
                    return None
                row = dict(row)
                qs = row.get("questions")
                if qs is None and hasattr(catalog, "questions"):
                    qs = catalog.questions(conn, code)
                row["questions"] = [dict(q) for q in (qs or [])]
                return row if row.get("aktif", True) else None
            except Exception as exc:
                self._log(logging.WARNING, f"Katalog kategori doğrulaması okunamadı: {exc}")
                return None
        row = conn.execute("SELECT code,label,mode,aktif FROM kategoriler WHERE code=? AND aktif=1", (code,)).fetchone()
        return dict(row) if row else None

    def _tip_keyboard(self):
        return [[self._button("Sessiz", "t:sessiz"), self._button("Telesekreter", "t:telesekreter")], [self._button("← Geri", "back:member")]]

    def _summary_keyboard(self):
        return [[self._button("Onayla", "confirm"), self._button("İptal", "cancel")]]

    def _storage_keyboard(self):
        return [
            [self._button("Sunucuda görsel (varsayılan)", "storage:local")],
            [self._button("Gyazo linkine dönüştür (isteğe bağlı)", "storage:gyazo")],
        ]

    def _cancel_keyboard(self):
        return [[self._button("Başa dön", "cancel:start")], [self._button("Proje seç", "cancel:project")], [self._button("Kategori seç", "cancel:category")], [self._button("Bilgileri düzelt", "cancel:info")]]

    def _screen(self, session: dict) -> str:
        step = session.get("step")
        if step == "storage":
            return ("<b>Görsel alındı.</b> Nasıl kaydedelim?\n\n"
                    "<b>Sunucuda görsel</b> varsayılandır. Gyazo seçeneği görseli dış servise gönderir; "
                    "bağlantıyı bilen görebilir.")
        if step == "project":
            return "<b>Bilgileriniz alındı.</b>\n\nŞimdi <b>projeyi</b> seçin."
        if step == "category":
            return f"<b>Proje:</b> {_h(session.get('project'))}\n\nŞimdi <b>kategoriyi</b> seçin."
        if step == "question":
            questions = session.get("questions") or []
            index = int(session.get("question_index") or 0)
            if 0 <= index < len(questions):
                question = questions[index]
                required = " (zorunlu)" if question.get("required") else " (isteğe bağlı)"
                return (f"<b>Proje:</b> {_h(session.get('project'))} | <b>Kategori:</b> {_h(session.get('category_label'))}\n\n"
                        f"<b>{index + 1}/{len(questions)} — {_h(question.get('label'))}</b>{required}\n"
                        + ("Bir seçenek belirleyin." if question.get("type") == "select" else "Yanıtı yazın."))
            return "Kategori soruları yeniden seçilmeli."
        if step == "personel":
            return f"<b>Proje:</b> {_h(session.get('project'))} | <b>Kategori:</b> {_h(session.get('category_label'))}\n\n<b>Personel kodunu</b> yazın."
        if step == "member":
            mode = session.get("category_mode")
            label = "Arkadaş Üye ID" if mode == "ark_ana" else ("Ana Üye ID" if mode == "ana_only" else "Üye ID")
            return f"<b>Personel:</b> {_h(session.get('personel'))}\n\n<b>{label}</b> yazın."
        if step == "ana":
            return f"<b>Arkadaş Üye ID:</b> {_h(session.get('uye_id'))}\n\n<b>Ana Üye ID</b> yazın."
        if step == "tip":
            return "<b>Sessiz / Telesekreter</b> türünü seçin."
        if step == "lead_confirm":
            return f"<b>Lead ID mi gireceksiniz?</b>\n\nGirdiğiniz metin: <code>{_h(session.get('lead_id'))}</code>"
        if step == "lead_write":
            return "Yeni <b>Lead ID</b> değerini yazın."
        return "İşleme devam edin."

    def _summary(self, session: dict) -> str:
        lines = ["<b>SON KONTROL</b>", "────────────────", f"<b>Proje:</b> {_h(session.get('project'))}", f"<b>Kategori:</b> {_h(session.get('category_label'))}"]
        if session.get("questions"):
            answers = session.get("answers") or {}
            for question in session.get("questions") or []:
                value = answers.get(str(question.get("key")), "")
                if value or question.get("required"):
                    lines.append(f"<b>{_h(question.get('label'))}:</b> {_h(value or '-')}")
        else:
            lines.append(f"<b>Personel Kodu:</b> {_h(session.get('personel'))}")
        mode = session.get("category_mode")
        if not session.get("questions"):
            if mode == "ark_ana":
                lines += [f"<b>Arkadaş Üye ID:</b> {_h(session.get('uye_id'))}", f"<b>Ana Üye ID:</b> {_h(session.get('ana_uye_id'))}"]
            elif mode == "ana_only":
                lines += [f"<b>Ana Üye ID:</b> {_h(session.get('ana_uye_id'))}"]
            else:
                lines.append(f"<b>Üye ID:</b> {_h(session.get('uye_id'))}")
            if session.get("tip"):
                lines.append(f"<b>Tür:</b> {_h(session.get('tip'))}")
        if session.get("source_type") == "yazili":
            lines.append(f"<b>Lead ID:</b> <code>{_h(session.get('lead_id'))}</code>")
        else:
            if session.get("save_mode") == "gyazo" and session.get("gyazo_url"):
                lines.append("<b>Görsel:</b> Gyazo bağlantısı ve sunucu kopyası hazır")
            else:
                lines.append("<b>Görsel:</b> sunucuda saklanacak")
        lines += ["────────────────", "Bilgiler doğruysa <b>Onayla</b>'ya basın; düzeltmek için <b>İptal</b>'i seçin."]
        return "\n".join(lines)

    # ---- görsel alma --------------------------------------------------------------------
    def _image_from_message(self, message: dict) -> Optional[dict]:
        cached = message.get("_cached_image")
        if isinstance(cached, dict) and cached.get("file_id") and cached.get("_pending_path"):
            return dict(cached)
        photos = message.get("photo")
        if isinstance(photos, list) and photos:
            photo = photos[-1]
            if isinstance(photo, dict) and photo.get("file_id"):
                return {"file_id": str(photo["file_id"]), "file_unique_id": str(photo.get("file_unique_id") or ""), "file_size": photo.get("file_size"), "name": "photo"}
        doc = message.get("document")
        if isinstance(doc, dict) and str(doc.get("mime_type") or "").lower().startswith("image/") and doc.get("file_id"):
            return {"file_id": str(doc["file_id"]), "file_unique_id": str(doc.get("file_unique_id") or ""), "file_size": doc.get("file_size"), "name": str(doc.get("file_name") or "image")}
        return None

    def _download_image(self, image: dict, chat_id: str, message_id: int) -> tuple[str, str]:
        """Ağ çağrısı; sadece _prepare_update içinden, DB transaction dışında çağrılır."""
        max_bytes = int(self.ayar.get("MAX_GORSEL_BYTES", 10 * 1024 * 1024))
        advertised = image.get("file_size")
        if advertised is not None and int(advertised) > max_bytes:
            raise TelegramHatasi("Görsel 10 MiB sınırını aşıyor")
        if not self.api:
            raise TelegramHatasi("TELEGRAM_TOKEN ayarlanmamış")
        info = self.api.get_file(image["file_id"])
        if info.get("file_size") is not None and int(info["file_size"]) > max_bytes:
            raise TelegramHatasi("Görsel 10 MiB sınırını aşıyor")
        raw = self.api.download(str(info["file_path"]), max_bytes)
        max_pixels = int(self.ayar.get("MAX_IMAGE_PIXELS", 25_000_000))
        try:
            # Pillow uyarısını istisnaya çevirip hem deklaratif hem gerçek piksel
            # sınırını uygularız; bomb benzeri görsel belleğe açılmaz.
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as im:
                    fmt = (im.format or "").upper()
                    if fmt not in _GECERLI_FORMATLAR:
                        raise TelegramHatasi("Görsel türüne izin verilmiyor")
                    if int(im.width) * int(im.height) > max_pixels:
                        raise TelegramHatasi("Görsel piksel sınırını aşıyor")
                    im.verify()
        except TelegramHatasi:
            raise
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise TelegramHatasi("İndirilen dosya doğrulanmış bir görsel değil") from exc
        ext = _GECERLI_FORMATLAR[fmt]
        stable = "_".join((_safe_piece(self.bot_id, 32), _safe_piece(chat_id, 32), _safe_piece(message_id, 32), _safe_piece(image.get("file_unique_id") or image["file_id"], 32)))
        relative = f"pending/{stable}.{ext}"
        target = (self.media_root / relative).resolve()
        if self.media_root not in target.parents:
            raise TelegramHatasi("Güvenli olmayan medya yolu")
        temp = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
        temp.write_bytes(raw)
        os.replace(temp, target)
        return relative, ext

    def _prepare_update(self, update: dict) -> dict:
        """İzinli görseli transaction başlamadan indirip inbox update'ına geçici olarak bağlar."""
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return update
        image = self._image_from_message(message)
        chat, user = message.get("chat") or {}, message.get("from") or {}
        if not image or chat.get("type") != "private" or not user.get("id") or str(chat.get("id")) != str(user.get("id")):
            return update
        update_id = update.get("update_id")
        if update_id is None:
            return update
        # Yetkisiz görsel hiç indirilmez; handler aynı update'te engel politikasını uygular.
        conn = self._conn()
        try:
            profile_row = conn.execute("SELECT * FROM tg_kullanicilar WHERE id=?", (str(user["id"]),)).fetchone()
            profile = dict(profile_row) if profile_row else None
            allowed = self._authorized(conn, profile, str(user["id"]))
            cached = conn.execute("SELECT pending_path,extension FROM tg_indirilen WHERE bot_id=? AND update_id=?", (self.bot_id, int(update_id))).fetchone()
        finally:
            conn.close()
        # Eski/aktarılmış genel onay tek başına indirme yetkisi değildir.
        if not allowed:
            return update
        if cached:
            pending = (self.media_root / cached["pending_path"]).resolve()
            if self.media_root in pending.parents and pending.parent.name == "pending" and pending.is_file():
                image.update({"_pending_path": cached["pending_path"], "_extension": cached["extension"]})
                message["_cached_image"] = image
                return update
        pending, ext = self._download_image(image, str(chat["id"]), int(message["message_id"]))
        conn = self._conn()
        try:
            with db.transaction(conn):
                conn.execute(
                    "INSERT INTO tg_indirilen(bot_id,update_id,chat_id,message_id,pending_path,extension,olusturma) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(bot_id,update_id) DO UPDATE SET chat_id=excluded.chat_id,message_id=excluded.message_id,pending_path=excluded.pending_path,extension=excluded.extension",
                    (self.bot_id, int(update_id), str(chat["id"]), int(message["message_id"]), pending, ext, _simdi()),
                )
        finally:
            conn.close()
        image.update({"_pending_path": pending, "_extension": ext})
        message["_cached_image"] = image
        return update

    def _gyazo_convert(self, pending_path: str) -> dict:
        """Opsiyonel sağlayıcıyı geç yükler; seçilmedikçe modül/ağ kullanılmaz."""
        path = (self.media_root / str(pending_path or "")).resolve()
        if self.media_root not in path.parents or path.parent.name != "pending" or not path.is_file():
            return {"ok": False, "url": None, "error": "Dönüştürülecek yerel görsel bulunamadı."}
        try:
            from . import gyazo
            result = gyazo.convert(path, token=None)
        except ImportError:
            return {"ok": False, "url": None, "error": "Gyazo seçeneği bu kurulumda kullanılamıyor."}
        except Exception as exc:
            self._log(logging.WARNING, f"Gyazo dönüşüm hatası: {exc}")
            return {"ok": False, "url": None, "error": "Gyazo dönüşümü tamamlanamadı."}
        if not isinstance(result, dict):
            return {"ok": False, "url": None, "error": "Gyazo geçerli bir sonuç döndürmedi."}
        ok, url = bool(result.get("ok")), str(result.get("url") or "")[:2000]
        if ok and url:
            return {"ok": True, "url": url, "error": None}
        return {"ok": False, "url": None, "error": str(result.get("error") or "Gyazo dönüşümü tamamlanamadı.")[:500]}

    def _preflight_storage_conversion(self, update: dict) -> dict:
        """Compatibility hook: callback processing must never do Gyazo network I/O."""
        return update

    def _start_image(self, conn, chat_id: str, user: dict, message: dict, image: dict, old_session: Optional[dict]) -> None:
        pending, ext = image.get("_pending_path"), image.get("_extension")
        path = (self.media_root / str(pending or "")).resolve()
        if not pending or not ext or self.media_root not in path.parents or path.parent.name != "pending" or not path.is_file():
            raise TelegramHatasi("İndirilmiş görsel bulunamadı; lütfen görseli yeniden gönderin")
        self._cancel_conversion(conn, old_session)
        self._remove_pending(old_session)
        session = {
            "step": "storage", "chat_id": str(chat_id), "source_type": "resim", "source_message_id": int(message["message_id"]),
            "file_id": image["file_id"], "file_unique_id": image.get("file_unique_id") or "", "pending_path": pending, "extension": ext,
            # Varsayılan yereldir; kullanıcı yine de açıkça saklama seçimini yapar.
            "save_mode": "local", "username": str(user.get("username") or user.get("first_name") or ""),
        }
        self._save_session(conn, str(user["id"]), session)
        self._show(conn, str(user["id"]), session, chat_id, self._screen(session), self._storage_keyboard())

    # ---- metin ve callback işleme -------------------------------------------------------
    def _block(self, conn, user_id: str, reason: str) -> None:
        conn.execute("UPDATE tg_kullanicilar SET engelli=1,onayli=0,deneme=?,engel_sebep=? WHERE id=?", (MAX_DENEME, reason[:300], user_id))
        conn.execute("DELETE FROM tg_girisler WHERE bot_id=? AND user_id=?", (self.bot_id, str(user_id)))
        session = self._get_session(conn, user_id)
        self._cancel_conversion(conn, session)
        self._remove_pending(session)
        self._delete_session(conn, user_id)
        db.denetim_yaz(conn, user_id, "telegram_engel", yeni=reason[:300])
        db.degisti(conn)

    def _start_lead(self, conn, chat_id: str, user_id: str, text: str, message_id: int, old_session: Optional[dict]) -> None:
        self._cancel_conversion(conn, old_session)
        self._remove_pending(old_session)
        session = {"step": "lead_confirm", "chat_id": str(chat_id), "source_type": "yazili", "source_message_id": int(message_id), "lead_id": text[:500]}
        self._save_session(conn, user_id, session)
        self._show(conn, user_id, session, chat_id, self._screen(session), [[self._button("Onayla", "lead:ok"), self._button("Değiştir", "lead:change")], [self._button("Çık", "lead:exit")]])

    def _text_input(self, conn, chat_id: str, user_id: str, session: dict, text: str, message_id: int) -> bool:
        step = session.get("step")
        text = text.strip()
        if not text or len(text) > 200:
            self._say(chat_id, "Değer boş olamaz ve en fazla 200 karakter olabilir.")
            return True
        if step == "question":
            self._set_question_answer(conn, user_id, session, chat_id, text)
            self._delete_typed_message(chat_id, message_id)
            return True
        if step == "lead_write":
            session["lead_id"] = text[:500]
            session["step"] = "lead_confirm"
            self._save_session(conn, user_id, session)
            self._delete_typed_message(chat_id, message_id)
            self._show(conn, user_id, session, chat_id, self._screen(session), [[self._button("Onayla", "lead:ok"), self._button("Değiştir", "lead:change")], [self._button("Çık", "lead:exit")]])
            return True
        if step == "personel":
            session["personel"] = text
            session["step"] = "member"
            self._save_session(conn, user_id, session)
            self._delete_typed_message(chat_id, message_id)
            self._show(conn, user_id, session, chat_id, self._screen(session), [[self._button("← Geri", "back:personel")]])
            return True
        if step == "member":
            if session.get("category_mode") == "ana_only":
                session["ana_uye_id"] = text
                session["step"] = "summary"
            else:
                session["uye_id"] = text
                session["step"] = "ana" if session.get("category_mode") == "ark_ana" else ("tip" if session.get("category_mode") == "sessiz_tip" else "summary")
            self._save_session(conn, user_id, session)
            self._delete_typed_message(chat_id, message_id)
            if session["step"] == "summary":
                self._show(conn, user_id, session, chat_id, self._summary(session), self._summary_keyboard())
            elif session["step"] == "tip":
                self._show(conn, user_id, session, chat_id, self._screen(session), self._tip_keyboard())
            else:
                self._show(conn, user_id, session, chat_id, self._screen(session), [[self._button("← Geri", "back:member")]])
            return True
        if step == "ana":
            session["ana_uye_id"] = text
            session["step"] = "summary"
            self._save_session(conn, user_id, session)
            self._delete_typed_message(chat_id, message_id)
            self._show(conn, user_id, session, chat_id, self._summary(session), self._summary_keyboard())
            return True
        return False

    def _question_keyboard(self, session: dict) -> Optional[list]:
        questions = session.get("questions") or []
        index = int(session.get("question_index") or 0)
        if not (0 <= index < len(questions)):
            return None
        question = questions[index]
        keys: list[list[dict]] = []
        if question.get("type") == "select":
            options = [str(value) for value in question.get("options") or []]
            keys.extend([[self._button(value, f"q:{index}:{position}") for position, value in enumerate(options[i:i + 3], i)]
                         for i in range(0, len(options), 3)])
        keys.append([self._button("← Geri", "back:question")])
        return keys

    def _rebuild_question_presets(self, session: dict) -> None:
        for field in ("personel", "uye_id", "ana_uye_id", "lead_id", "tip"):
            session.pop(field, None)
        answers = session.get("answers") or {}
        for question in session.get("questions") or []:
            preset = str(question.get("preset") or "")
            if preset in {"personel", "uye_id", "ana_uye_id", "lead_id", "tip"} and str(question.get("key")) in answers:
                session[preset] = answers[str(question.get("key"))]

    def _set_question_answer(self, conn, uid: str, session: dict, chat_id: str, value: str) -> None:
        questions = session.get("questions") or []
        index = int(session.get("question_index") or 0)
        if not (0 <= index < len(questions)):
            raise TelegramHatasi("Kategori sorusu geçersiz; kategoriyi yeniden seçin")
        question = questions[index]
        value = str(value).strip()[:200]
        if question.get("required") and not value:
            self._show(conn, uid, session, chat_id, "Bu alan zorunludur.\n\n" + self._screen(session), self._question_keyboard(session))
            return
        answers = dict(session.get("answers") or {})
        answers[str(question.get("key"))] = value
        session["answers"] = answers
        session["question_index"] = index + 1
        self._rebuild_question_presets(session)
        if session["question_index"] >= len(questions):
            session["step"] = "summary"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._summary(session), self._summary_keyboard())
        else:
            session["step"] = "question"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._question_keyboard(session))

    def _final_path(self, session: dict) -> tuple[Path, str]:
        """Tüm kaynak kimliklerini görünen ad + sabit hash sonekiyle namespace'e ayırır."""
        ext = _safe_piece(session.get("extension") or "jpg", 8).lower()
        pieces = [
            _safe_piece(self.bot_id, 18), _safe_piece(session.get("user_id"), 18), _safe_piece(session.get("username"), 18),
            _safe_piece(session.get("chat_id"), 18), _safe_piece(session.get("project"), 12), _safe_piece(session.get("category_code"), 16),
            _safe_piece(session.get("personel"), 18), _safe_piece(session.get("uye_id") or "ana", 18), _safe_piece(session.get("ana_uye_id") or "na", 18),
            _safe_piece(session.get("source_message_id"), 16), _safe_piece(session.get("file_unique_id") or session.get("file_id") or "f", 24),
        ]
        identity = {"bot": self.bot_id, "user": session.get("user_id"), "username": session.get("username"), "chat": session.get("chat_id"),
                    "project": session.get("project"), "category": session.get("category_code"), "personel": session.get("personel"),
                    "uye": session.get("uye_id"), "ana": session.get("ana_uye_id"), "message": session.get("source_message_id"),
                    "file": session.get("file_unique_id") or session.get("file_id")}
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()[:20]
        prefix = "tg_" + "_".join(pieces)
        # Uzantı ve çarpışma önleyici hash her zaman yer ayırır; kör kesme yoktur.
        max_prefix = 240 - len(ext) - 1 - len(digest) - 1
        name = f"{prefix[:max_prefix].rstrip('._')}_{digest}.{ext}"
        path = (self.media_root / name).resolve()
        if self.media_root not in path.parents:
            raise TelegramHatasi("Güvenli olmayan hedef medya yolu")
        return path, name

    def _prepare_final_file(self, user: dict, session: dict) -> str:
        """Onay transaction'ından önce pending'i atomik kopya ile finale hazırlar; pending korunur."""
        uid = str(user["id"])
        pending = (self.media_root / str(session.get("pending_path") or "")).resolve()
        if self.media_root not in pending.parents or pending.parent.name != "pending" or not pending.is_file():
            raise TelegramHatasi("Bekleyen görsel bulunamadı; lütfen görseli yeniden gönderin")
        final, relative = self._final_path({**session, "user_id": uid, "username": session.get("username") or user.get("username") or user.get("first_name") or ""})
        if not final.is_file():
            temp = final.with_name(final.name + f".{uuid.uuid4().hex}.tmp")
            try:
                shutil.copyfile(pending, temp)
                os.replace(temp, final)
            finally:
                with contextlib.suppress(OSError):
                    temp.unlink(missing_ok=True)
        return relative

    def _commit_record(self, conn, user: dict, session: dict, prepared_gorsel: Optional[str] = None) -> tuple[int, bool]:
        """Commit local evidence first, then bind any already-enqueued Gyazo job."""
        uid, chat_id = str(user["id"]), str(session["chat_id"])
        key = f"tg:{self.bot_id}:{chat_id}:{int(session['source_message_id'])}"
        existing = conn.execute("SELECT id FROM kayitlar WHERE anahtar=?", (key,)).fetchone()
        if existing:
            self._delete_session(conn, uid)
            if session.get("source_type") == "resim" and self._post_commit is not None:
                self._post_commit.append(("commit_media", str(session.get("pending_path") or "")))
            return int(existing["id"]), False

        # Commit-time membership validation prevents a removed category/project
        # from being attached even when an old inline keyboard is replayed.
        project = str(session.get("project") or "").upper()
        category = self._category_snapshot(conn, str(session.get("category_code") or ""), project)
        if project not in self._project_codes(conn) or not category:
            raise TelegramHatasi("Proje veya kategori artık etkin değil; yeniden seçim yapın")
        questions = session.get("question_snapshot") or session.get("questions") or []
        answers = dict(session.get("answers") or {})
        # Legacy wizard answers are also written under their snapshot keys so
        # old columns and the new cevaplar_json remain transactionally aligned.
        for question in questions:
            preset = str(question.get("preset") or "")
            if preset and str(question.get("key")) not in answers and session.get(preset) is not None:
                answers[str(question.get("key"))] = str(session[preset])
        for question in questions:
            if question.get("required") and not str(answers.get(str(question.get("key")), "")).strip():
                raise TelegramHatasi("Zorunlu kategori yanıtı eksik; bilgileri yeniden kontrol edin")

        gorsel = None
        if session.get("source_type") == "resim":
            _, expected = self._final_path({**session, "user_id": uid, "username": session.get("username") or user.get("username") or user.get("first_name") or ""})
            final = (self.media_root / expected).resolve()
            if prepared_gorsel != expected or self.media_root not in final.parents or not final.is_file():
                raise TelegramHatasi("Görsel onay için hazır değil; lütfen tekrar onaylayın")
            gorsel = expected
        # The durable job is intentionally still pending here.  Empty strings
        # are neither a Gyazo URL nor a local-link value; preserve NULL until a
        # verified worker result atomically updates this exact image snapshot.
        link = None
        if gorsel and session.get("save_mode") == "gyazo":
            candidate = str(session.get("gyazo_url") or "")[:2000]
            link = candidate or None
        link_turu = "gyazo" if link else ("yerel" if gorsel else None)
        now = _simdi()
        columns = ["anahtar", "proje", "kategori", "personel", "uye_id", "ana_uye_id", "tip", "link", "link_turu", "gorsel_dosya", "tarih", "tarih_ham",
                   "kt", "excel_durum", "ekleyen_id", "ekleyen_ad", "ekleyen_guven", "kaynak", "giris_tipi", "lead_id", "telegram_bot_id", "file_id", "file_unique_id", "message_id", "chat_id", "kategori_code", "kategori_mode"]
        values = [key, project, session["category_label"], session.get("personel"), session.get("uye_id"), session.get("ana_uye_id"), session.get("tip"),
                  link, link_turu, gorsel, now, now, 0, "var", uid, str(user.get("username") or user.get("first_name") or uid)[:120], "telegram",
                  "telegram", session["source_type"], session.get("lead_id"), self.bot_id, session.get("file_id"), session.get("file_unique_id"), int(session["source_message_id"]), chat_id,
                  session["category_code"], session.get("category_mode")]
        available = {row["name"] for row in conn.execute("PRAGMA table_info(kayitlar)")}
        snapshot = {"questions": questions, "category_code": session.get("category_code"), "project": project}
        extras = {
            "kategori_soru_surumu": int(session["category_revision"]) if str(session.get("category_revision") or "").isdigit() else None,
            "soru_anlik_json": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            "cevaplar_json": json.dumps(answers, ensure_ascii=False, separators=(",", ":")),
        }
        for name, value in extras.items():
            if name in available:
                columns.append(name); values.append(value)
        conn.execute(f"INSERT INTO kayitlar({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", values)
        kid = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        # A conversion may already have verified before user confirmation. Binding
        # the exact source key atomically updates only this newly committed record.
        if gorsel and session.get("conversion_job_key"):
            donusum_isleri.bind_record(
                conn, str(session["conversion_job_key"]), kid,
                str((self.media_root / gorsel).resolve()),
                notice_replace_message_id=int(session["ui_message_id"]) if session.get("ui_message_id") else None,
            )
        conn.execute("UPDATE tg_kullanicilar SET kayit_sayisi=kayit_sayisi+1,last_seen=? WHERE id=?", (now, uid))
        self._delete_session(conn, uid)
        db.bildirim_uret(conn, kid)
        db.denetim_yaz(conn, uid, "telegram_kayit", project, key, yeni=str(kid))
        db.degisti(conn)
        if gorsel and self._post_commit is not None:
            self._post_commit.append(("commit_media", str(session.get("pending_path") or "")))
        return kid, True

    def _cleanup_committed_media(self, pending_path: str) -> None:
        conn = self._conn()
        try:
            with db.transaction(conn):
                absolute = str((self.media_root / str(pending_path)).resolve())
                # A confirmed record has a final local copy. Keep the pending
                # source until any leased Gyazo worker switches to that final copy.
                if donusum_isleri.is_path_reserved(conn, self.bot_id, absolute):
                    return
                conn.execute("DELETE FROM tg_indirilen WHERE bot_id=? AND pending_path=?", (self.bot_id, pending_path))
        finally:
            conn.close()
        self._remove_pending_now(pending_path)

    def _recover_pending_media(self) -> int:
        """Çökme DB commit ile pending temizliği arasındaysa finale tekrar kopyalar ve temizler."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT i.pending_path,k.gorsel_dosya FROM tg_indirilen i JOIN kayitlar k "
                "ON k.telegram_bot_id=i.bot_id AND k.chat_id=i.chat_id AND k.message_id=i.message_id "
                "WHERE i.bot_id=? AND k.gorsel_dosya IS NOT NULL", (self.bot_id,)
            ).fetchall()
        finally:
            conn.close()
        recovered = 0
        for row in rows:
            pending = (self.media_root / row["pending_path"]).resolve()
            final = (self.media_root / row["gorsel_dosya"]).resolve()
            if self.media_root not in pending.parents or self.media_root not in final.parents:
                continue
            try:
                if not final.is_file() and pending.is_file():
                    temp = final.with_name(final.name + f".{uuid.uuid4().hex}.tmp")
                    shutil.copyfile(pending, temp)
                    os.replace(temp, final)
                if final.is_file():
                    self._cleanup_committed_media(row["pending_path"])
                    recovered += 1
            except OSError as exc:
                self._log(logging.WARNING, f"Pending medya kurtarılamadı: {exc}")
        return recovered

    def _resume_ui(self,conn,uid,session,chat_id,note='',fresh=True):
        """Durumu değiştirmeden doğru düğmeleri görünür son mesaj olarak yeniler."""
        # Önceki sürümden kalan yarım fotoğraf yeni seçim sorusunu atlamaz.
        if session.get('source_type') == 'resim' and session.get('save_mode') not in ('local','gyazo'):
            session['step'] = 'storage'
        step=session.get('step')
        keyboard={
            'storage':self._storage_keyboard(),
            'project':self._project_keyboard(conn),
            'category':self._category_keyboard(conn, str(session.get('project') or '')),
            'question':self._question_keyboard(session),'personel':[[self._button('← Geri','back:category')]],
            'member':[[self._button('← Geri','back:personel')]],
            'ana':[[self._button('← Geri','back:member')]],
            'tip':self._tip_keyboard(),'summary':self._summary_keyboard(),
            'cancel_menu':self._cancel_keyboard(),
            'lead_confirm':[[self._button('Onayla','lead:ok'),self._button('Değiştir','lead:change')],[self._button('Çık','lead:exit')]],
            'lead_write':None,
        }
        if step not in keyboard:
            self._say(chat_id,'Başlamak için görsel veya Lead ID gönderin.');return
        # _show always sends a new message and deletes the prior delivered UI.
        screen=self._summary(session) if step=='summary' else ('Nereye dönmek istersiniz?' if step=='cancel_menu' else self._screen(session))
        self._show(conn,uid,session,chat_id,(note+'\n\n' if note else '')+screen,keyboard[step])

    def _callback(self, conn, callback: dict) -> None:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user = callback.get("from") or {}
        if chat.get("type") != "private" or not user.get("id") or str(chat.get("id")) != str(user.get("id")):
            return
        chat_id, uid = str(chat["id"]), str(user["id"])
        self._answer_callback(str(callback.get("id") or ""), chat_id)
        profile = self._touch_user(conn, user)
        if profile.get("engelli"):
            self._say(chat_id, "Erişiminiz engellenmiştir.")
            return
        session = self._get_session(conn, uid)
        # Callback'ler de yeni botun ilk parola kaydı olmadan akışı ilerletemez.
        if not self._authorized(conn, profile, uid):
            self._say(chat_id, "Bu botu kullanmak için önce /start yazıp parolayı gönderin.")
            return
        if self._maintenance(conn) and not self._admin_active(session):
            self._say(chat_id, "Bot şu anda bakım modunda.");return
        if not session:
            self._say(chat_id,"Bu işlem tamamlanmış veya iptal edilmiş. Yeni görsel ya da Lead ID gönderebilirsiniz.");return
        # Eski düğme kaydı değiştirmez; yeni ekran teslim edilirken eski UI de
        # geçiş yaratamaz. Callback answer yukarıda zaten ilk outbox işidir.
        if str(session.get("chat_id")) != chat_id:
            return
        if session.get("ui_pending_key"):
            self._say(chat_id, "Yeni seçim ekranı hazırlanıyor; lütfen en alttaki ekrandan devam edin.")
            return
        if int(session.get("ui_message_id") or -1) != int(message.get("message_id") or -2):
            db.denetim_yaz(conn,uid,'telegram_eski_buton',yeni=str(session.get('step')))
            self._resume_ui(conn,uid,session,chat_id,'Bu düğme eski seçim ekranına ait. Güncel adımdan devam edin.');return
        data = str(callback.get("data") or "")
        step = session.get("step")
        if data == "storage:local" and step == "storage":
            session["save_mode"] = "local"
            session.pop("gyazo_url", None)
            session.pop("gyazo_error", None)
            session["step"] = "project"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._project_keyboard(conn))
        elif data == "storage:gyazo" and step == "storage":
            # Only a durable DB row is created here. Upload/verify run later on
            # this bot process' worker loop, never in callback or transaction.
            job = donusum_isleri.enqueue(
                conn, None, uid, bot_id=self.bot_id, chat_id=chat_id,
                source_message_id=int(session["source_message_id"]), user_id=uid,
                local_path=str((self.media_root / str(session.get("pending_path") or "")).resolve()),
            )
            session.update({"save_mode": "gyazo", "conversion_job_key": job["job_key"], "step": "project"})
            session.pop("gyazo_url", None)
            session.pop("gyazo_error", None)
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._project_keyboard(conn))
        elif data == "lead:ok" and step == "lead_confirm":
            session["step"] = "project"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._project_keyboard(conn))
        elif data == "lead:change" and step == "lead_confirm":
            session["step"] = "lead_write"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), None)
        elif data == "lead:exit" and step in {"lead_confirm", "lead_write"}:
            self._delete_session(conn, uid)
            self._terminal(conn, chat_id, int(message["message_id"]), "İptal edildi. Yeni bir Lead ID yazabilir veya görsel gönderebilirsiniz.")
        elif data.startswith("p:") and step == "project":
            project = data[2:].upper()
            if project not in self._project_codes(conn):
                self._show(conn, uid, session, chat_id, "Bu proje artık etkin değil; yeniden seçim yapın.", self._project_keyboard(conn))
                return
            session.update({"project": project, "step": "category"})
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._category_keyboard(conn, project))
        elif data.startswith("k:") and step == "category":
            code = data[2:].lower()
            row = self._category_snapshot(conn, code, str(session.get("project") or ""))
            if not row:
                self._show(conn, uid, session, chat_id, "Bu kategori bu projede artık etkin değil; yeniden seçim yapın.", self._category_keyboard(conn, str(session.get("project") or "")))
                return
            snapshot_questions = [dict(q) for q in row.get("questions") or []]
            mode = str(row.get("mode") or "custom")
            # Catalog exposes generated snapshots for legacy presets too. Keep
            # the established four-step wizard for those modes, while retaining
            # that snapshot for the eventual record.
            questions = [] if mode in _GECERLI_MODLAR else snapshot_questions
            if not questions and mode not in _GECERLI_MODLAR:
                self._show(conn, uid, session, chat_id, "Kategori soru tanımı geçersiz; yeniden seçim yapın.", self._category_keyboard(conn, str(session.get("project") or "")))
                return
            session.update({"category_code": row["code"], "category_label": row["label"], "category_mode": mode,
                            "category_revision": row.get("revision"), "questions": questions,
                            "question_snapshot": snapshot_questions, "answers": {}, "question_index": 0,
                            "step": "question" if questions else "personel"})
            self._save_session(conn, uid, session)
            keyboard = self._question_keyboard(session) if questions else [[self._button("← Geri", "back:category")]]
            self._show(conn, uid, session, chat_id, self._screen(session), keyboard)
        elif data.startswith("q:") and step == "question":
            try:
                _, raw_index, raw_option = data.split(":", 2)
                index, option = int(raw_index), int(raw_option)
                question = (session.get("questions") or [])[index]
                choices = [str(value) for value in question.get("options") or []]
                if index != int(session.get("question_index") or 0) or question.get("type") != "select":
                    raise ValueError
                self._set_question_answer(conn, uid, session, chat_id, choices[option])
            except (ValueError, IndexError, TypeError):
                self._resume_ui(conn, uid, session, chat_id, "Bu seçenek artık geçerli değil.")
        elif data == "back:question" and step == "question":
            index = int(session.get("question_index") or 0)
            if index <= 0:
                for key in ("category_code", "category_label", "category_mode", "category_revision", "questions", "question_snapshot", "answers", "question_index", "personel", "uye_id", "ana_uye_id", "lead_id", "tip"):
                    session.pop(key, None)
                session["step"] = "category"
                self._save_session(conn, uid, session)
                self._show(conn, uid, session, chat_id, self._screen(session), self._category_keyboard(conn, str(session.get("project") or "")))
            else:
                index -= 1
                questions = session.get("questions") or []
                answers = dict(session.get("answers") or {})
                for question in questions[index:]:
                    answers.pop(str(question.get("key")), None)
                session.update({"answers": answers, "question_index": index, "step": "question"})
                self._rebuild_question_presets(session)
                self._save_session(conn, uid, session)
                self._show(conn, uid, session, chat_id, self._screen(session), self._question_keyboard(session))
        elif data == "back:project" and step == "category":
            for key in ("project", "category_code", "category_label", "category_mode", "personel", "uye_id", "ana_uye_id", "tip"):
                session.pop(key, None)
            session["step"] = "project"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._project_keyboard(conn))
        elif data == "back:category" and step == "personel":
            for key in ("category_code", "category_label", "category_mode", "personel", "uye_id", "ana_uye_id", "tip"):
                session.pop(key, None)
            session["step"] = "category"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), self._category_keyboard(conn, str(session.get("project") or "")))
        elif data == "back:personel" and step == "member":
            for key in ("personel", "uye_id", "ana_uye_id", "tip"):
                session.pop(key, None)
            session["step"] = "personel"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), [[self._button("← Geri", "back:category")]])
        elif data == "back:member" and step in {"ana", "tip"}:
            for key in ("uye_id", "ana_uye_id", "tip"):
                session.pop(key, None)
            session["step"] = "member"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._screen(session), [[self._button("← Geri", "back:personel")]])
        elif data.startswith("t:") and step == "tip" and data[2:] in {"sessiz", "telesekreter"}:
            session["tip"] = data[2:]
            session["step"] = "summary"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, self._summary(session), self._summary_keyboard())
        elif data == "confirm" and step == "summary":
            prepared = (self._outbox_context or {}).get("prepared_final")
            kid, created = self._commit_record(conn, user, session, prepared)
            message_text = "<b>Kanıtınız eklendi, teşekkürler.</b>" if created else "Bu kaynak mesaj zaten kaydedilmişti; tekrar kayıt oluşturulmadı."
            # A Gyazo submission has one durable terminal source: its queue
            # notice (success, honest failure, or ambiguity).  Sending this
            # normal confirmation too would produce a second final message and
            # falsely imply the remote conversion has already completed.
            waiting_for_gyazo = bool(
                created and session.get("source_type") == "resim"
                and session.get("save_mode") == "gyazo" and session.get("conversion_job_key")
            )
            if not waiting_for_gyazo:
                self._terminal(conn, chat_id, int(message["message_id"]), message_text + f"\nKayıt: <code>{kid}</code>")
        elif data == "cancel" and step == "summary":
            session["step"] = "cancel_menu"
            self._save_session(conn, uid, session)
            self._show(conn, uid, session, chat_id, "Nereye dönmek istersiniz?", self._cancel_keyboard())
        elif data.startswith("cancel:") and step == "cancel_menu":
            choice = data[7:]
            if choice == "start":
                self._cancel_conversion(conn, session)
                self._remove_pending(session)
                self._delete_session(conn, uid)
                self._terminal(conn, chat_id, int(message["message_id"]), "İptal edildi. Yeni görsel veya Lead ID gönderebilirsiniz.")
            elif choice == "project":
                for key in ("project", "category_code", "category_label", "category_mode", "personel", "uye_id", "ana_uye_id", "tip"):
                    session.pop(key, None)
                session["step"] = "project"
                self._save_session(conn, uid, session)
                self._show(conn, uid, session, chat_id, self._screen(session), self._project_keyboard(conn))
            elif choice == "category":
                for key in ("category_code", "category_label", "category_mode", "personel", "uye_id", "ana_uye_id", "tip"):
                    session.pop(key, None)
                session["step"] = "category"
                self._save_session(conn, uid, session)
                self._show(conn, uid, session, chat_id, self._screen(session), self._category_keyboard(conn, str(session.get("project") or "")))
            elif choice == "info":
                for key in ("personel", "uye_id", "ana_uye_id", "tip"):
                    session.pop(key, None)
                session["step"] = "personel"
                self._save_session(conn, uid, session)
                self._show(conn, uid, session, chat_id, self._screen(session), [[self._button("← Geri", "back:category")]])
        else:
            db.denetim_yaz(conn,uid,'telegram_yanlis_adim_butonu',yeni=str(step))
            self._resume_ui(conn,uid,session,chat_id,'Bu seçenek mevcut adım için geçerli değil. Güncel ekran yenilendi.')

    def _message(self, conn, message: dict) -> None:
        chat = message.get("chat") or {}
        user = message.get("from") or {}
        if chat.get("type") != "private" or not user.get("id") or str(chat.get("id")) != str(user.get("id")):
            return
        chat_id, uid = str(chat["id"]), str(user["id"])
        profile = self._touch_user(conn, user)
        text = str(message.get("text") or "").strip()
        if text.split(" ", 1)[0].lower() == "/kimim":
            self._say(chat_id, f"<b>Telegram ID:</b> <code>{_h(uid)}</code>\n<b>Ad:</b> {_h(user.get('username') or user.get('first_name') or '-')}")
            return
        session = self._get_session(conn, uid)
        if profile.get("engelli"):
            self._say(chat_id, "Erişiminiz engellenmiştir.")
            return

        password = os.environ.get("BOT_PASSWORD", "")
        if not password:
            # Parola olmadan yönetici komutları dahil hiçbir normal akışa izin
            # verilmez; /kimim yukarıda zararsız kimlik sorgusu olarak kalır.
            self._say(chat_id, "Bot henüz güvenli biçimde yapılandırılmadı; yöneticiyle iletişime geçin.")
            return
        handled, session = self._admin_command(conn, chat_id, user, text, session)
        if handled:
            return
        if self._maintenance(conn) and not self._admin_active(session):
            self._say(chat_id, "Bot şu anda bakım modunda. Lütfen daha sonra tekrar deneyin.")
            return

        image = self._image_from_message(message)
        if not self._authorized(conn, profile, uid):
            if image:
                # Aktarımdan gelen eski genel onay sahibi yeni botta önce parola
                # girer; gerçekten onaysız kişide eski engel politikası sürer.
                if profile.get("onayli"):
                    self._say(chat_id, "Bu bot için önce parolayı yazın. Görseliniz indirilmedi; paroladan sonra yeniden gönderin.")
                else:
                    self._block(conn, uid, "yetkisiz_gorsel_gonderimi")
                    self._say(chat_id, "Bu bota görsel gönderme yetkiniz yok; erişiminiz engellendi.")
                return
            if text.startswith("/"):
                self._say(chat_id, "Hoş geldiniz. Devam etmek için parolayı yazın.")
                return
            if hmac.compare_digest(password, text):
                conn.execute("UPDATE tg_kullanicilar SET onayli=1,engelli=0,engel_sebep=NULL,deneme=0,onay_tarihi=? WHERE id=?", (_simdi(), uid))
                conn.execute("INSERT OR IGNORE INTO tg_girisler(bot_id,user_id,zaman) VALUES(?,?,?)", (self.bot_id, uid, _simdi()))
                self._delete_typed_message(chat_id, int(message["message_id"]), sensitive=True)
                db.denetim_yaz(conn, uid, "telegram_onay")
                db.degisti(conn)
                # Parola yenilemesi mevcut yarım görsel akışını bozmaz.
                if session and session.get("step") != "idle":
                    self._resume_ui(conn, uid, session, chat_id, "Giriş başarılı. Mevcut işleminiz korunuyor.", fresh=False)
                else:
                    self._say(chat_id, "<b>Hoş geldiniz.</b> Görsel gönderin veya Lead ID yazın.")
                return
            trial = int(profile.get("deneme") or 0) + 1
            if trial >= MAX_DENEME:
                self._block(conn, uid, "3_yanlis_parola")
                self._say(chat_id, "Erişiminiz engellendi.")
            else:
                conn.execute("UPDATE tg_kullanicilar SET deneme=? WHERE id=?", (trial, uid))
                self._say(chat_id, f"Parola yanlış. {MAX_DENEME - trial} deneme hakkınız kaldı.")
            return

        if text:
            command = text.split(" ", 1)[0].lower()
            if command == "/tema":
                self._say(chat_id, "Görünüm seçeneği kaldırıldı; Telegram'ın native düğme stilleri sabittir.")
                return
            if command == "/start":
                if session and session.get('step')!='idle':
                    self._resume_ui(conn,uid,session,chat_id,'Mevcut işleminiz korundu. Bu ekrandan devam edebilirsiniz.')
                else:
                    self._say(chat_id, "Başlamak için görsel gönderin veya Lead ID yazın. /iptal ile mevcut akışı iptal edebilirsiniz.")
                return
            if command == "/iptal":
                self._cancel_conversion(conn, session)
                self._remove_pending(session)
                self._delete_session(conn, uid)
                self._terminal(conn, chat_id, int(session.get("ui_message_id") or 0) if session else None, "Mevcut işlem iptal edildi.")
                return
        if image:
            self._start_image(conn, chat_id, user, message, image, session)
            return
        if message.get("document") and not image:
            self._say(chat_id, "Yalnızca gerçek görsel türündeki fotoğraf veya belge kabul edilir.")
            return
        if not text:
            self._say(chat_id, "Başlamak için görsel gönderin veya Lead ID yazın.")
            return
        if text.startswith("/"):
            self._say(chat_id, "Başlamak için görsel gönderin veya Lead ID yazın. /iptal ile işlem iptal edilir.")
            return
        if session and self._text_input(conn, chat_id, uid, session, text, int(message["message_id"])):
            return
        # URL'den görsel indirmeyiz: doğrulanmış Telegram dosyası olmadan Gyazo
        # bağlantısını Lead ID olarak kaydetmek güvenli değildir.
        if _GYAZO_URL.fullmatch(text):
            self._say(chat_id, "Bu akışta Gyazo linkinden otomatik görsel çekmiyorum. Görseli Telegram’dan gönderin; yerel veya Gyazo kayıt biçimini seçebilirsiniz.")
            return
        # Veri alanı beklenmiyorsa metin yeni bir Lead ID başlatır; yarım fotoğraf akışını sıfırlar.
        self._start_lead(conn, chat_id, uid, text, int(message["message_id"]), session)

    def _preflight_confirmation(self, update: dict) -> Optional[str]:
        """Confirm callback'inin dosya kopyasını DB transaction'ından önce hazırlar."""
        callback = update.get("callback_query") if isinstance(update, dict) else None
        if not isinstance(callback, dict) or str(callback.get("data") or "") != "confirm":
            return None
        user, message = callback.get("from") or {}, callback.get("message") or {}
        chat = message.get("chat") or {}
        if not user.get("id") or str(chat.get("id")) != str(user.get("id")):
            return None
        conn = self._conn()
        try:
            profile_row = conn.execute("SELECT * FROM tg_kullanicilar WHERE id=?", (str(user["id"]),)).fetchone()
            profile = dict(profile_row) if profile_row else None
            session = self._get_session(conn, str(user["id"]))
            allowed = self._authorized(conn, profile, str(user["id"]))
        finally:
            conn.close()
        if not allowed or not session or session.get("step") != "summary" or session.get("source_type") != "resim":
            return None
        # Stale bir UI için gereksiz dosya yazmayalım; handler bunu yine kesin
        # olarak transaction içinde kontrol eder.
        if int(session.get("ui_message_id") or -1) != int(message.get("message_id") or -2):
            return None
        return self._prepare_final_file(user, session)

    def handle_update(self, update: dict, inbox_update_id: Optional[int] = None) -> None:
        """Bir update'in state geçişi, cevap outbox'ı ve inbox ack'ini tek commit yapar.

        Ağ/dosya indirme ve final dosya kopyalama transaction başlamadan yapılır;
        pending temizliği ancak commit sonrasında yapılır.
        """
        if not isinstance(update, dict):
            return
        update = self._prepare_update(update)
        update = self._preflight_storage_conversion(update)
        prepared_final = self._preflight_confirmation(update)
        source_id = int(inbox_update_id if inbox_update_id is not None else update.get("update_id") or 0)
        conn = self._conn()
        post_commit: list[tuple[str, str]] = []
        old_context, old_post = self._outbox_context, self._post_commit
        try:
            with db.transaction(conn):
                self._outbox_context = {"conn": conn, "update_id": source_id, "sequence": 0, "prepared_final": prepared_final}
                self._post_commit = post_commit
                if isinstance(update.get("callback_query"), dict):
                    self._callback(conn, update["callback_query"])
                elif isinstance(update.get("message"), dict):
                    self._message(conn, update["message"])
                if inbox_update_id is not None:
                    # State/outbox ve ack tek commit: kill olursa hepsi rollback,
                    # restart'ta aynı kaynak anahtarlarıyla güvenle tekrar denenir.
                    conn.execute(
                        "UPDATE tg_gelen SET durum='tamam',veri='{}',hata=NULL,guncelleme=? WHERE bot_id=? AND update_id=?",
                        (_simdi(), self.bot_id, int(inbox_update_id)),
                    )
                    conn.execute("UPDATE tg_durum SET heartbeat=?,hata=NULL WHERE bot_id=?", (_simdi(), self.bot_id))
        finally:
            self._outbox_context, self._post_commit = old_context, old_post
            conn.close()
        # Bu noktaya yalnız başarılı DB commit'ten sonra gelinir. Temizlik
        # başarısız kalırsa tg_indirilen + _recover_pending_media restartta tamamlar.
        for operation, value in post_commit:
            if operation == "remove_pending":
                self._remove_pending_now(value)
            elif operation == "commit_media":
                self._cleanup_committed_media(value)

    def process_conversion_jobs(self, limit: int = 4) -> int:
        """Run bounded Gyazo phases on this bot process, then enqueue one result/outbox."""
        conn = self._conn()
        completed = 0
        cleanup_pending: list[str] = []
        try:
            worker_id = f"telegram:{self.bot_id}:{os.getpid()}"
            for _ in range(max(1, min(int(limit), 20))):
                row = donusum_isleri.worker_step(conn, worker_id)
                if not row:
                    break
                completed += 1
                # Confirmation may have left the pending source in place while
                # this job held an upload/verify lease. Once a bound Telegram
                # job reaches a terminal state, the final local record copy is
                # durable and this process can finish the deferred cleanup.
                if (row.get("bot_id") == self.bot_id and row.get("record_id") is not None
                        and row.get("durum") in donusum_isleri.TERMINAL and row.get("source_path")):
                    try:
                        source = Path(str(row["source_path"])).resolve()
                        if source.parent == self.media_root / "pending":
                            cleanup_pending.append(str(source.relative_to(self.media_root)))
                    except (OSError, ValueError):
                        pass
            # ``claim_notices`` also returns prior queued reservations after a
            # crash. Unique action keys make this outbox handoff idempotent.
            for job in donusum_isleri.claim_notices(conn, limit=max(1, limit * 2), bot_id=self.bot_id):
                if job.get("durum") == "tamam" and bool(job.get("record_applied")) and job.get("uygulama_durumu") == "uygulandi":
                    text = f"<b>Gyazo bağlantısı kayda eklendi.</b>\nKayıt: <code>{int(job['record_id'])}</code>\n{_h(job.get('url'))}"
                elif job.get("durum") == "tamam":
                    text = (f"<b>Görsel değişti; bağlantı kayda eklenmedi, yerel kanıt korunuyor.</b>\n"
                            f"Kayıt: <code>{int(job['record_id'])}</code>")
                elif job.get("durum") == "belirsiz":
                    text = (f"<b>Gyazo yüklemesinin sonucu belirsiz.</b> Tekrar yükleme yapılmadı; yerel görsel korunuyor.\n"
                            f"Kayıt: <code>{int(job['record_id'])}</code>")
                else:
                    text = f"<b>Gyazo bağlantısı eklenemedi.</b> Yerel görsel korunuyor.\nKayıt: <code>{int(job['record_id'])}</code>"
                action = f"job:{job['job_key']}:result"
                now = _simdi()
                conn.execute(
                    "INSERT OR IGNORE INTO tg_giden(bot_id,source_update_id,action_key,tur,chat_id,user_id,replace_message_id,job_key,metin,durum,deneme,hata,olusturma,guncelleme) "
                    "VALUES(?,NULL,?,'send',?,?,?,?,?,'bekliyor',0,NULL,?,?)",
                    (self.bot_id, action, str(job["chat_id"]), str(job.get("user_id") or ""),
                     job.get("notice_replace_message_id"), str(job["job_key"]), text, now, now),
                )
        finally:
            conn.close()
        for pending_path in dict.fromkeys(cleanup_pending):
            self._cleanup_committed_media(pending_path)
        return completed

    # ---- süreç yaşam döngüsü -------------------------------------------------------------
    def _paused(self) -> bool:
        conn = self._conn()
        try:
            return db.ayar_al(conn, "bot_durdur", "0") == "1"
        finally:
            conn.close()

    def run_forever(self, poll_timeout: int = 25, once: bool = False) -> bool:
        """Long-poll döngüsünü çalıştırır; yapılandırma eksikse dış çağrı yapmadan döner."""
        if not os.environ.get("BOT_PASSWORD"):
            self._log(logging.ERROR, "BOT_PASSWORD ayarlanmamış; bot güvenli nedenle başlatılmadı.")
            return False
        if not self.token or not self.api:
            self._log(logging.ERROR, "TELEGRAM_TOKEN ayarlanmamış; bot başlatılmadı.")
            return False
        lock = BotLock(Path(self.ayar["BOT_KLASOR"]) / "locks" / f"telegram-{_safe_piece(self.bot_id, 64)}.lock")
        if not lock.acquire():
            self._log(logging.ERROR, "Bu bot için başka bir süreç zaten çalışıyor.")
            return False
        try:
            # Webhook varsa asla sessizce deleteWebhook çağrısı yapmayız. getMe yalnızca
            # nabız/kimlik görünümü içindir; webhook sahipliği olduğu gibi korunur.
            try:
                me = self.api.call("getMe", {}, timeout=20)
                self._heartbeat(username=str((me or {}).get("username") or ""))
                webhook = self.api.call("getWebhookInfo", {}, timeout=20) or {}
                if isinstance(webhook, dict) and webhook.get("url"):
                    message = "Bot webhook ile yapılandırılmış; webhook silinmedi ve long polling başlatılmadı."
                    self._heartbeat(message)
                    self._log(logging.ERROR, message)
                    return False
            except TelegramHatasi as exc:
                self._heartbeat(str(exc))
                self._log(logging.ERROR, f"Telegram bağlantı hatası: {exc}")
                return False
            while not self._stopped:
                try:
                    # Site yönetimi duraklattığında ne polling ne stored-event
                    # processing yapılır; Docker yeniden başlasa da DB bayrağı kalır.
                    if self._paused():
                        self._heartbeat()
                        time.sleep(1)
                        if once:
                            break
                        continue
                    # Eski kalıcı işler, ağdaki uzun getUpdates çağrısından önce
                    # işlenir: Telegram erişilemezse bile restart sonrası aç kalmaz.
                    self._recover_pending_media()
                    self.process_conversion_jobs()
                    self.process_pending()
                    self.process_outbox()
                    self.poll_once(poll_timeout)
                    self.process_pending()
                    self.process_conversion_jobs()
                    self.process_outbox()
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    self._heartbeat(str(exc))
                    self._log(logging.ERROR, f"Long polling hatası: {exc}")
                    if once:
                        return False
                    time.sleep(3)
                if once:
                    break
            return True
        finally:
            lock.release()

    def stop(self) -> None:
        self._stopped = True


# Kısa ad, harici test/işletme kodunun sınıfı kolay bulabilmesi için korunur.
Bot = KanitBot


def main() -> int:
    from .settings import AYAR

    import signal
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    bot = KanitBot(AYAR)
    signal.signal(signal.SIGTERM, lambda signum, frame: bot.stop())
    signal.signal(signal.SIGINT, lambda signum, frame: bot.stop())
    return 0 if bot.run_forever() else 2


if __name__ == "__main__":
    sys.exit(main())

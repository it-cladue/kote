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
from .guvenli_log import text as _guvenli_metin

LOG = logging.getLogger("kanit.telegram")
# Geriye dönük sabit; etkin eşik .env'deki MAX_DENEME ile _max_deneme() üzerinden okunur.
MAX_DENEME = 3
MAX_RETRY = 5
_RETRY_SECONDS = (5, 30, 120, 600)
_GECERLI_MODLAR = {"tek_uye", "ark_ana", "ana_only", "sessiz_tip"}
_GECERLI_FORMATLAR = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
_GUVENLI = re.compile(r"[^A-Za-z0-9_.-]+")
_TOKEN_URL = re.compile(r"(bot)(?:\d+:[A-Za-z0-9_-]+)", re.I)
_GYAZO_URL = re.compile(r"^https?://(?:[a-z0-9-]+\.)?gyazo\.com/[^\s]+$", re.I)
# Telegram kullanıcı kimliği: yalnız rakam, 5-15 hane (yönetici komutlarının hedefi).
_TG_ID = re.compile(r"[1-9][0-9]{4,14}")
# Telegram getFile tavanı 20 MB; MAX_GORSEL_BYTES bunu aşamaz.
_INDIRME_TAVANI = 20 * 1024 * 1024
# Tek mesaj 4096 karakter; HTML güvenli bölme için pay bırakılır.
_MESAJ_SINIRI = 3900
_MAX_PARCA = 5
_DEVAM_NOTU = "… (devamı var)"
_KISALTMA_NOTU = "… (çıktı kısaltıldı)"
_HTML_ATOM = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?>|&[A-Za-z0-9#]+;|.", re.S)
_HTML_ETIKET = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?>")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    """.env/ortam tam sayısı; yoksa veya geçersizse varsayılan, sınır dışıysa kırpılır."""
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _max_deneme() -> int:
    """BOT_PASSWORD için izinli yanlış deneme sayısı (MAX_DENEME, varsayılan 3, 1-10)."""
    return _env_int("MAX_DENEME", MAX_DENEME, 1, 10)


def _outbox_max_deneme() -> int:
    return _env_int("BOT_OUTBOX_MAX_DENEME", MAX_RETRY, 1, 20)


def _admin_prompt_saniye() -> int:
    return _env_int("ADMIN_PROMPT_SANIYE", 120, 30, 900)


def _admin_max_deneme() -> int:
    return _env_int("ADMIN_MAX_DENEME", 3, 1, 10)


def _admin_kilit_saniye() -> int:
    return _env_int("ADMIN_KILIT_SANIYE", 600, 60, 86400)


def _admin_oturum_saniye() -> int:
    return _env_int("ADMIN_OTURUM_SANIYE", 1800, 300, 86400)


def _engelli_uyari_saniye() -> int:
    return _env_int("BOT_ENGELLI_UYARI_SANIYE", 600, 60, 86400)


def _parola_istem_saniye() -> int:
    return _env_int("BOT_PAROLA_ISTEM_SANIYE", 20, 1, 3600)


def _saklama_gun() -> int:
    return _env_int("BOT_GUNLUK_SAKLAMA_GUN", 30, 1, 3650)


def _pending_saklama_saat() -> int:
    return _env_int("BOT_PENDING_SAKLAMA_SAAT", 24, 1, 720)


def _log_max_bytes() -> int:
    return _env_int("BOT_LOG_MAX_MB", 5, 1, 100) * 1024 * 1024


def _yetkisiz_gorsel_politikasi() -> str:
    """'engelle' (varsayılan, eski davranış) veya 'parola' (parola istemine yönlendir)."""
    value = str(os.environ.get("BOT_YETKISIZ_GORSEL_POLITIKA", "") or "").strip().lower()
    return "parola" if value == "parola" else "engelle"


def _esit(expected: Any, given: Any) -> bool:
    """Sabit zamanlı karşılaştırma; ASCII dışı karakterlerde hmac.compare_digest str ile çöker."""
    try:
        return hmac.compare_digest(str(expected or "").encode("utf-8"), str(given or "").encode("utf-8"))
    except (TypeError, ValueError):
        return False

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
    """Telegram API veya indirilen dosya doğrulama hatası.

    ``status`` Telegram'ın JSON gövdesiyle bildirdiği error_code'dur; ``kalici``
    4xx (429 hariç) hataları işaretler: yeniden denemek işe yaramaz. Ağ hataları ve
    JSON gövdesi olmayan HTTP hataları geçicidir (status=None). ``retry_after`` 429 için
    Telegram'ın istediği bekleme süresidir (saniye).
    """

    def __init__(self, message: Any = "", status: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = int(status) if isinstance(status, int) and not isinstance(status, bool) else None
        try:
            self.retry_after = max(1, int(retry_after)) if retry_after is not None else None
        except (TypeError, ValueError):
            self.retry_after = None

    @property
    def kalici(self) -> bool:
        return self.status is not None and 400 <= self.status < 500 and self.status != 429


class GorselReddedildi(TelegramHatasi):
    """Kalıcı içerik/boyut reddi: yeniden indirme işe yaramaz, kullanıcıya bildirilir."""


def _simdi() -> str:
    return db.simdi()


def _redact(value: Any) -> str:
    """İstek istisnalarındaki token ve olası parolaları log öncesi maskeler.

    'bot<id>:<token>' URL biçimine ek olarak guvenli_log.text çıplak token,
    'password=' alanları ve ortamdaki gerçek BOT_PASSWORD/ADMIN_PASSWORD/TELEGRAM_TOKEN
    değerlerini de maskeler.
    """
    text = str(value or "")
    text = _TOKEN_URL.sub(r"\1***", text)
    text = re.sub(r"((?:token|password|sifre)\s*[=:]\s*)\S+", r"\1***", text, flags=re.I)
    return _guvenli_metin(text)


def _etiket_izle(open_tags: list, closing: bool, name: str, raw: str) -> None:
    """HTML parçalamada açık etiket yığınını günceller."""
    name = name.lower()
    if closing:
        for index in range(len(open_tags) - 1, -1, -1):
            if open_tags[index][0] == name:
                del open_tags[index]
                break
    else:
        open_tags.append((name, raw))


def _html_parcala(text: str, limit: int = _MESAJ_SINIRI, max_parts: int = _MAX_PARCA) -> list[str]:
    """Uzun HTML metni etiket/entity ortasından kesmeden, tercihen satır sınırında böler.

    Her parçada açık kalan etiketler kapatılır ve sonraki parçada yeniden açılır;
    son olmayan parçalara '… (devamı var)' notu eklenir. ``max_parts`` aşılırsa
    kalan satırlar atılır ve son parçada kısaltma notu bulunur.
    """
    text = str(text or "")
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf: list[str] = []
    open_tags: list[tuple[str, str]] = []
    state = {"len": 0, "base": 0}

    def closing() -> str:
        return "".join(f"</{name}>" for name, _ in reversed(open_tags))

    def reserve() -> int:
        return len(closing()) + len(_DEVAM_NOTU) + 1

    def add(piece: str) -> None:
        buf.append(piece)
        state["len"] += len(piece)

    def flush() -> None:
        parts.append("".join(buf).rstrip("\n") + closing() + "\n" + _DEVAM_NOTU)
        buf.clear()
        state["len"] = 0
        for _, raw in open_tags:
            add(raw)
        state["base"] = state["len"]

    def has_content() -> bool:
        return state["len"] > state["base"]

    for line in text.splitlines(keepends=True):
        if has_content() and state["len"] + len(line) + reserve() > limit:
            flush()
        if state["len"] + len(line) + reserve() <= limit:
            add(line)
            for tag in _HTML_ETIKET.finditer(line):
                _etiket_izle(open_tags, bool(tag.group(1)), tag.group(2), tag.group(0))
            continue
        # Tek satır bile sınırı aşıyor: etiket/entity atomları bazında böl.
        for atom in _HTML_ATOM.finditer(line):
            raw = atom.group(0)
            if has_content() and state["len"] + len(raw) + reserve() > limit:
                flush()
            add(raw)
            if atom.group(2):
                _etiket_izle(open_tags, bool(atom.group(1)), atom.group(2), raw)
    if has_content():
        parts.append("".join(buf) + closing())
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        last = parts[-1]
        if last.endswith(_DEVAM_NOTU):
            last = last[:-len(_DEVAM_NOTU)] + _KISALTMA_NOTU
        parts[-1] = last
    return parts or [text[:limit]]


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
        except (requests.RequestException, OSError) as exc:
            raise TelegramHatasi(_redact(exc)) from exc
        status = getattr(response, "status_code", None)
        status = int(status) if isinstance(status, int) and not isinstance(status, bool) else None
        # Gövde HTTP hatasından ÖNCE okunur: 4xx yanıtlarda Telegram'ın açıklaması,
        # error_code'u ve 429 için parameters.retry_after kaybolmasın.
        data: Any = None
        try:
            data = response.json()
        except (requests.RequestException, ValueError, OSError, AttributeError):
            data = None
        if isinstance(data, dict) and not data.get("ok"):
            code = data.get("error_code")
            code = int(code) if isinstance(code, int) and not isinstance(code, bool) else status
            parameters = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
            retry_after = parameters.get("retry_after") if code == 429 else None
            description = data.get("description") or f"Telegram API hatası {code or ''}".strip()
            raise TelegramHatasi(_redact(description), status=code, retry_after=retry_after)
        if status is not None and status >= 400:
            # JSON gövdesi olmayan HTTP hatası (ara vekil, bakım sayfası vb.) Telegram'ın
            # kendi kararı değildir; geçici sayılır, sınırlı sayıda yeniden denenir.
            try:
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
            except (requests.RequestException, OSError) as exc:
                raise TelegramHatasi(_redact(exc)) from exc
            raise TelegramHatasi(f"Telegram HTTP {status}")
        if not isinstance(data, dict) or not data.get("ok"):
            raise TelegramHatasi("Telegram API yanıtı geçersiz")
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
            try:
                declared = int(content_length) if content_length else 0
            except (TypeError, ValueError):
                declared = 0
            if declared > max_bytes:
                raise GorselReddedildi("Dosya izinli boyut sınırını aşıyor")
            chunks = []
            total = 0
            iterator = response.iter_content(chunk_size=64 * 1024) if hasattr(response, "iter_content") else [response.content]
            for chunk in iterator:
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise GorselReddedildi("Dosya izinli boyut sınırını aşıyor")
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
        # Şema/ALTER işi süreç başına bir kez yapılır (eşzamanlı yazma kilidi azalır).
        self._schema_ready = False
        # Bellek içi hız sınırı ve yönetici parola deneme sayaçları; yeniden
        # başlatmada sıfırlanmaları kabul edilir, DB sütunu gerekmez.
        self._uyari_zamani: dict[str, float] = {}
        self._admin_hatali: dict[str, dict] = {}
        self._son_temizlik: Optional[float] = None
        # Telegram 429 retry_after: bu ana kadar hiçbir gönderim yapılmaz (monotonic).
        self._outbox_duraklat_bitis: float = 0.0

    # ---- bağlantı, log ve kalıcı inbox -------------------------------------------------
    def _conn(self):
        conn = db.baglan(self.ayar["DB"])
        if self._schema_ready:
            return conn
        try:
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
        except BaseException:
            conn.close()
            raise
        self._schema_ready = True
        return conn

    def _log_path(self) -> Path:
        return Path(self.ayar.get("LOG_DOSYA") or Path(self.ayar["BOT_KLASOR"]) / "bot_log.txt")

    def _rotate_log(self, path: Path) -> None:
        """bot_log.txt BOT_LOG_MAX_MB'ı aşınca bot_log.txt.1 … .3 olarak döndürülür."""
        try:
            if not path.is_file() or path.stat().st_size < _log_max_bytes():
                return
            oldest = Path(f"{path}.3")
            if oldest.exists():
                oldest.unlink()
            for index in (2, 1):
                older = Path(f"{path}.{index}")
                if older.exists():
                    os.replace(older, f"{path}.{index + 1}")
            os.replace(path, f"{path}.1")
        except OSError:
            pass

    def _log(self, level: int, message: Any) -> None:
        line = f"[{_simdi()}] {_redact(message)}"
        LOG.log(level, line)
        path = self._log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_log(path)
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

    def _has_outbox_retry(self, within_seconds: int = 25) -> bool:
        """Bu poll penceresinde zamanı gelecek bir teslimat tekrarı varken long-poll kısa tutulur.

        Yalnız 'tekrar' satırları (deneme üst sınırının altındakiler) sayılır; 'olu'
        satırları ve çok ileriye planlanmış tekrarlar polling'i kısaltmaz.
        """
        due = (datetime.now() + timedelta(seconds=max(0, int(within_seconds)))).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._conn()
        try:
            return bool(conn.execute(
                "SELECT 1 FROM tg_giden WHERE bot_id=? AND durum='tekrar' AND deneme<? AND guncelleme<=? LIMIT 1",
                (self.bot_id, _outbox_max_deneme(), due),
            ).fetchone())
        finally:
            conn.close()

    def _outbox_duraklama(self) -> float:
        """429 sonrası kalan duraklama süresi (sn); 0 ise gönderim serbest."""
        return max(0.0, self._outbox_duraklat_bitis - time.monotonic())

    def poll_once(self, timeout: int = 25) -> int:
        if not self.api:
            raise TelegramHatasi("TELEGRAM_TOKEN ayarlanmamış")
        conn = self._conn()
        try:
            offset = self._offset(conn)
        finally:
            conn.close()
        # Bekleyen teslimat tekrarları 25 sn long-poll arkasında kalmasın; 429
        # duraklaması bitince de kuyruk hemen akmaya devam etsin.
        timeout = int(timeout)
        pause = self._outbox_duraklama()
        if pause > 0:
            timeout = max(1, min(timeout, int(pause) + 1))
        elif self._has_outbox_retry(timeout):
            timeout = min(timeout, 2)
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
            update = None
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
                veri = None  # None: ham update yeniden deneme için saklanır
                if self._parola_mesaji_mi(update):
                    # Parola (ya da parola denemesi) içeren metin yedeklere ve
                    # 'tekrar'/'olu' satırlarına düz metin olarak yazılmaz.
                    state, veri = "olu", "{}"
                    message = ("Parola içerebilecek mesaj güvenlik nedeniyle yeniden denenmez; "
                               "kullanıcı parolayı tekrar yazmalı. Hata: " + message)[:1000]
                conn2 = self._conn()
                try:
                    with db.transaction(conn2):
                        conn2.execute(
                            "UPDATE tg_gelen SET durum=?,deneme=?,hata=?,guncelleme=?,veri=COALESCE(?,veri) "
                            "WHERE bot_id=? AND update_id=? AND durum!='tamam'",
                            (state, attempt, message, retry_at, veri, self.bot_id, row["update_id"]),
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

    def _finish_outbox(self, row, delivered_message_id: Optional[int] = None, error: Optional[Exception] = None,
                       retry_in: Optional[int] = None) -> str:
        """Teslimat sonucunu yazar; dönüş değeri yeni durumdur ('tamam', 'tekrar' veya 'olu')."""
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
                    return "tamam"
                if retry_in is not None:
                    # 429: deneme sayılmaz; satır Telegram'ın istediği süre sonra yeniden alınır.
                    retry_at = (datetime.now() + timedelta(seconds=int(retry_in))).strftime("%Y-%m-%d %H:%M:%S")
                    conn.execute(
                        "UPDATE tg_giden SET durum='tekrar',hata=?,guncelleme=? WHERE id=? AND durum!='tamam'",
                        (_redact(error)[:1000], retry_at, row["id"]),
                    )
                    return "tekrar"
                attempt = int(row["deneme"] or 0) + 1
                permanent = bool(getattr(error, "kalici", False))
                state, retry_at = "olu", _simdi()
                if not permanent and attempt < _outbox_max_deneme():
                    delay = _RETRY_SECONDS[min(attempt - 1, len(_RETRY_SECONDS) - 1)]
                    retry_at = (datetime.now() + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")
                    state = "tekrar"
                conn.execute(
                    "UPDATE tg_giden SET durum=?,deneme=?,hata=?,guncelleme=? WHERE id=? AND durum!='tamam'",
                    (state, attempt, _redact(error)[:1000], retry_at, row["id"]),
                )
                if state == "olu" and row["tur"] == "send" and row["job_key"]:
                    # Teslim edilemeyecek dönüşüm bildirimi her döngüde yeniden seçilmesin.
                    donusum_isleri.mark_notice_delivered(conn, str(row["job_key"]), bot_id=self.bot_id)
                return state
        finally:
            conn.close()

    def process_outbox(self, limit: int = 100) -> int:
        """Teslimat kuyruğunu DB kilidi tutmadan gönderir; geçici hatalar sınırlı sayıda geri denenir.

        Kalıcı Telegram hataları (400 chat not found, 403 bot engellendi, HTML
        ayrıştırma hatası...) ilk denemede 'olu' olur. 429'da Telegram'ın retry_after
        süresi boyunca tüm gönderimler duraklatılır.
        """
        if self._outbox_duraklama() > 0:
            return 0
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
            if self._outbox_duraklama() > 0:
                break
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
                retry_after = getattr(exc, "retry_after", None)
                if retry_after:
                    wait = max(1, min(int(retry_after), 300))
                    self._outbox_duraklat_bitis = time.monotonic() + wait
                    self._finish_outbox(row, error=exc, retry_in=wait)
                    self._log(logging.WARNING, f"Telegram hız sınırı (429): gönderimler {wait} sn duraklatıldı: {exc}")
                    break
                state = self._finish_outbox(row, error=exc)
                if state == "olu":
                    self._log(logging.WARNING, f"Mesaj teslim edilemedi; vazgeçildi ({row['tur']}, deneme {int(row['deneme'] or 0) + 1}): {exc}")
                else:
                    self._log(logging.WARNING, f"Mesaj teslim edilemedi; yeniden denenecek ({row['tur']}): {exc}")
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

    def _admin_yetkili(self, user_id: str, session: Optional[dict]) -> bool:
        """Etkin yönetici oturumu yalnız ADMIN_IDS'te hâlâ bulunan kişi için geçerlidir."""
        return self._is_allowed_admin(str(user_id)) and self._admin_active(session)

    def _admin_touch(self, conn, user_id: str, session: Optional[dict]) -> None:
        """Her yönetici komutu hareketsizlik süresini (ADMIN_OTURUM_SANIYE) yeniden başlatır."""
        if session and self._admin_active(session):
            session["admin_until"] = int(time.time()) + _admin_oturum_saniye()
            self._save_session(conn, str(user_id), session)

    def _uyari_izinli(self, user_id: str, anahtar: str, saniye: int) -> bool:
        """Kullanıcı+anahtar başına kayan pencere: aynı uyarı ``saniye`` içinde bir kez gönderilir."""
        now = time.monotonic()
        key = f"{user_id}:{anahtar}"
        if len(self._uyari_zamani) > 20000:
            self._uyari_zamani = {k: v for k, v in self._uyari_zamani.items() if now - v < 86400}
            if len(self._uyari_zamani) > 20000:
                self._uyari_zamani.clear()
        last = self._uyari_zamani.get(key)
        if last is not None and now - last < max(1, int(saniye)):
            return False
        self._uyari_zamani[key] = now
        return True

    def _admin_kilit_dakika(self, user_id: str) -> int:
        """Yönetici parola kilidinin kalan süresi (dakika); 0 ise kilit yok."""
        info = self._admin_hatali.get(user_id)
        if not info:
            return 0
        now = time.monotonic()
        remaining = float(info.get("kilit") or 0.0) - now
        if remaining > 0:
            return max(1, int(remaining // 60) + 1)
        # Kilit süresi dolmuş ya da uzun süredir yanlış deneme yok: sayaç sıfırlanır.
        if info.get("kilit") or now - float(info.get("son") or now) > _admin_kilit_saniye():
            self._admin_hatali.pop(user_id, None)
        return 0

    def _admin_hata_kaydet(self, user_id: str) -> int:
        info = self._admin_hatali.setdefault(user_id, {"sayi": 0, "kilit": 0.0, "son": time.monotonic()})
        info["sayi"] += 1
        info["son"] = time.monotonic()
        if info["sayi"] >= _admin_max_deneme():
            info["kilit"] = time.monotonic() + _admin_kilit_saniye()
        return int(info["sayi"])

    def _parola_mesaji_mi(self, update: Any) -> bool:
        """İşlenemeyen update'in metni parola ya da parola denemesi olabilir mi?

        BOT_PASSWORD/ADMIN_PASSWORD ile eşleşen metin, onaysız kullanıcının düz
        metni (akış gereği parola denemesidir) ve açık yönetici parola isteminde
        yazılan metin parola sayılır; bunlar tg_gelen.veri'de saklanmaz.
        """
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return False
        text = str(message.get("text") or message.get("caption") or "").strip()
        if not text or text.startswith("/"):
            return False
        for key in ("BOT_PASSWORD", "ADMIN_PASSWORD"):
            secret = os.environ.get(key, "")
            if secret and _esit(secret, text):
                return True
        user = message.get("from") or {}
        uid = str(user.get("id") or "")
        if not uid:
            return False
        try:
            conn = self._conn()
        except Exception:
            return False
        try:
            row = conn.execute("SELECT * FROM tg_kullanicilar WHERE id=?", (uid,)).fetchone()
            profile = dict(row) if row else None
            if not self._authorized(conn, profile, uid):
                return True
            session = self._get_session(conn, uid)
            return bool(session and session.get("admin_prompt"))
        except Exception:
            return False
        finally:
            conn.close()

    def _admin_command(self, conn, chat_id: str, user: dict, text: str, session: Optional[dict],
                       message_id: Optional[int] = None) -> tuple[bool, Optional[dict]]:
        """(işlendi_mi, güncel_oturum) — temel yönetici komutları."""
        uid = str(user["id"])
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        if session and session.get("admin_prompt") and text and not text.startswith("/"):
            deadline = session.pop("admin_prompt", None)
            self._save_session(conn, uid, session)
            # Parola mesajı doğru/yanlış/geç fark etmeksizin sohbetten silinmeye çalışılır;
            # silme başarısız olursa (eski mesaj, yetki) sessizce yutulur.
            if message_id:
                self._delete_typed_message(chat_id, int(message_id), sensitive=True)
            try:
                prompt_ok = float(deadline) > time.time()
            except (TypeError, ValueError):
                prompt_ok = False
            if not prompt_ok:
                self._say(chat_id, "Yönetici parola isteğinin süresi doldu; /admin yazıp yeniden isteyin.")
                return True, session
            locked = self._admin_kilit_dakika(uid)
            if locked:
                self._say(chat_id, f"Çok fazla hatalı yönetici denemesi. Lütfen {locked} dakika sonra yeniden deneyin.")
                return True, session
            expected = os.environ.get("ADMIN_PASSWORD", "")
            if self._is_allowed_admin(uid) and expected and _esit(expected, text):
                minutes = _admin_oturum_saniye() // 60
                session["admin_until"] = int(time.time()) + _admin_oturum_saniye()
                self._save_session(conn, uid, session)
                self._admin_hatali.pop(uid, None)
                db.denetim_yaz(conn, uid, "telegram_onay", yeni={"tur": "admin"},
                               aciklama="Telegram yönetici parolasıyla giriş yapıldı.")
                self._say(chat_id, f"<b>Yönetici girişi başarılı.</b> Oturum {minutes} dakika hareketsizlikten sonra kapanır.")
            else:
                count = self._admin_hata_kaydet(uid)
                db.denetim_yaz(conn, uid, "telegram_onay", yeni={"tur": "admin", "sonuc": "basarisiz", "deneme": count},
                               sonuc="hata", aciklama="Telegram yönetici parolası yanlış girildi.")
                if count >= _admin_max_deneme():
                    self._say(chat_id, f"Yönetici girişi başarısız. Çok fazla hatalı deneme; {_admin_kilit_saniye() // 60} dakika beklemeniz gerekir.")
                else:
                    self._say(chat_id, f"Yönetici girişi başarısız. {_admin_max_deneme() - count} deneme hakkınız kaldı.")
            return True, session
        if cmd == "/admin":
            if not self._is_allowed_admin(uid) or not os.environ.get("ADMIN_PASSWORD"):
                if self._uyari_izinli(uid, "admin", 60):
                    self._say(chat_id, "Bu Telegram ID için yönetici erişimi tanımlı değil.")
                return True, session
            locked = self._admin_kilit_dakika(uid)
            if locked:
                self._say(chat_id, f"Çok fazla hatalı yönetici denemesi. Lütfen {locked} dakika sonra yeniden deneyin.")
                return True, session
            session = session or {"step": "idle"}
            session["admin_prompt"] = int(time.time()) + _admin_prompt_saniye()
            self._save_session(conn, uid, session)
            self._say(chat_id, f"Yönetici parolasını yazın. İstek {max(1, _admin_prompt_saniye() // 60)} dakika geçerlidir; parola mesajınız sohbetten silinir.")
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
            self._admin_touch(conn, uid, session)
            return True, session
        # /engel_kaldir admin_commands tarafından yürütülür (onay korunur); eski
        # yerleşik kopyası ölü koddu ve kaldırıldı.
        admin_commands = {"/durum", "/bakim", "/bakim_ac", "/bakim_kapat", "/kategori_liste", "/engel", "/oturumlar"}
        if cmd not in admin_commands:
            return False, session
        if not self._admin_yetkili(uid, session):
            self._say(chat_id, "Bu komut için önce /admin ile giriş yapın.")
            return True, session
        self._admin_touch(conn, uid, session)
        if cmd == "/durum":
            users = conn.execute("SELECT COUNT(*) FROM tg_kullanicilar").fetchone()[0]
            inbox = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE bot_id=? AND durum IN ('bekliyor','tekrar')", (self.bot_id,)).fetchone()[0]
            dead = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE bot_id=? AND durum='olu'", (self.bot_id,)).fetchone()[0]
            undelivered = conn.execute("SELECT COUNT(*) FROM tg_giden WHERE bot_id=? AND durum='olu'", (self.bot_id,)).fetchone()[0]
            self._say(chat_id, f"<b>DURUM</b>\nBakım: {'açık' if self._maintenance(conn) else 'kapalı'}\nKullanıcı: {users}\nBekleyen: {inbox}\nÖlü mektup: {dead}\nTeslim edilemeyen mesaj: {undelivered}")
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
            elif not _TG_ID.fullmatch(target):
                self._say(chat_id, "Telegram ID yalnız rakamlardan oluşmalı (5-15 hane). Örnek: /engel 123456789 sebep")
            elif target == uid:
                self._say(chat_id, "Kendi hesabınızı engelleyemezsiniz.")
            else:
                # Tek yol: panel ve /engelle ile aynı servis (islem_sonuclari + denetim tutarlı).
                from . import bot_yonetim
                bot_yonetim.engelle(self.ayar, conn, target, "", reason.strip()[:300] or "Yönetici engeli", uid)
                self._say(chat_id, f"{_h(target)} engellendi.")
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
        """Uzun çıktıyı HTML güvenli parçalara böler; klavye son parçaya eklenir."""
        conn = self._outbox_context["conn"]
        parts = _html_parcala(str(text or ""))
        for index, part in enumerate(parts):
            self._queue_outbox(conn, "send", str(chat_id), part, keyboard if index == len(parts) - 1 else None)
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

    def _max_image_bytes(self) -> int:
        """Ayardaki görsel sınırı; Telegram getFile tavanı (20 MB) hiçbir durumda aşılmaz."""
        try:
            configured = int(self.ayar.get("MAX_GORSEL_BYTES", 10 * 1024 * 1024))
        except (TypeError, ValueError):
            configured = 10 * 1024 * 1024
        return max(1024, min(configured, _INDIRME_TAVANI))

    def _download_image(self, image: dict, chat_id: str, message_id: int) -> tuple[str, str]:
        """Ağ çağrısı; sadece _prepare_update içinden, DB transaction dışında çağrılır.

        Boyut, tür, piksel ve Pillow doğrulama hataları ``GorselReddedildi`` (kalıcı)
        olarak fırlar; yalnız ağ/zaman aşımı hataları geçici ``TelegramHatasi`` kalır.
        """
        max_bytes = self._max_image_bytes()
        limit_text = f"{max_bytes // (1024 * 1024)} MiB"
        advertised = image.get("file_size")
        try:
            if advertised is not None and int(advertised) > max_bytes:
                raise GorselReddedildi(f"Görsel {limit_text} sınırını aşıyor")
        except (TypeError, ValueError):
            pass
        if not self.api:
            raise TelegramHatasi("TELEGRAM_TOKEN ayarlanmamış")
        info = self.api.get_file(image["file_id"])
        try:
            if info.get("file_size") is not None and int(info["file_size"]) > max_bytes:
                raise GorselReddedildi(f"Görsel {limit_text} sınırını aşıyor")
        except (TypeError, ValueError):
            pass
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
                        raise GorselReddedildi("Görsel türüne izin verilmiyor")
                    if int(im.width) * int(im.height) > max_pixels:
                        raise GorselReddedildi("Görsel piksel sınırını aşıyor")
                    im.verify()
        except TelegramHatasi:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise GorselReddedildi("İndirilen dosya doğrulanmış bir görsel değil") from exc
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
            uid = str(user["id"])
            profile_row = conn.execute("SELECT * FROM tg_kullanicilar WHERE id=?", (uid,)).fetchone()
            profile = dict(profile_row) if profile_row else None
            allowed = self._authorized(conn, profile, uid)
            cached = conn.execute("SELECT pending_path,extension FROM tg_indirilen WHERE bot_id=? AND update_id=?", (self.bot_id, int(update_id))).fetchone()
            # Bakım modunda (yönetici dışı) görsel indirilmez; sahipsiz pending oluşmaz.
            maintenance = allowed and self._maintenance(conn) and not self._admin_yetkili(uid, self._get_session(conn, uid))
        finally:
            conn.close()
        # Eski/aktarılmış genel onay tek başına indirme yetkisi değildir.
        if not allowed or maintenance:
            return update
        if cached:
            pending = (self.media_root / cached["pending_path"]).resolve()
            if self.media_root in pending.parents and pending.parent.name == "pending" and pending.is_file():
                image.update({"_pending_path": cached["pending_path"], "_extension": cached["extension"]})
                message["_cached_image"] = image
                return update
        try:
            pending, ext = self._download_image(image, str(chat["id"]), int(message["message_id"]))
        except GorselReddedildi as exc:
            # Kalıcı red: yeniden indirme yok; handler kullanıcıya tek açıklama gönderir
            # ve update normal 'tamam' yolunu izler.
            message["_image_error"] = str(exc)
            return update
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
        # Yönetici oturumu akış başlatınca sessizce düşmesin.
        if old_session and old_session.get("admin_until"):
            session["admin_until"] = old_session["admin_until"]
        self._save_session(conn, str(user["id"]), session)
        self._show(conn, str(user["id"]), session, chat_id, self._screen(session), self._storage_keyboard())

    # ---- metin ve callback işleme -------------------------------------------------------
    def _block(self, conn, user_id: str, reason: str) -> None:
        conn.execute("UPDATE tg_kullanicilar SET engelli=1,onayli=0,deneme=?,engel_sebep=? WHERE id=?", (_max_deneme(), reason[:300], user_id))
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
        if old_session and old_session.get("admin_until"):
            session["admin_until"] = old_session["admin_until"]
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

    # ---- periyodik temizlik -------------------------------------------------------------
    def _pending_abs(self, value: Any) -> Optional[str]:
        try:
            path = Path(str(value or ""))
            path = path if path.is_absolute() else (self.media_root / path)
            return str(path.resolve())
        except (OSError, ValueError):
            return None

    def _eski_gunlukleri_sil(self) -> tuple[int, int]:
        """BOT_GUNLUK_SAKLAMA_GUN'den eski 'tamam'/'olu' tg_gelen ve tg_giden satırlarını siler (VACUUM yok)."""
        sinir = (datetime.now() - timedelta(days=_saklama_gun())).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._conn()
        try:
            with db.transaction(conn):
                gelen = conn.execute(
                    "DELETE FROM tg_gelen WHERE bot_id=? AND durum IN ('tamam','olu') AND guncelleme<?", (self.bot_id, sinir)
                ).rowcount
                giden = conn.execute(
                    "DELETE FROM tg_giden WHERE bot_id=? AND durum IN ('tamam','olu') AND guncelleme<?", (self.bot_id, sinir)
                ).rowcount
            return int(gelen or 0), int(giden or 0)
        finally:
            conn.close()

    def _sahipsiz_pending_temizle(self) -> tuple[int, int]:
        """24 saatten (BOT_PENDING_SAKLAMA_SAAT) eski, hiçbir kayıtla eşleşmeyen pending dosyalarını siler.

        Korunanlar: açık oturumların pending_path'i, bitmemiş dönüşüm işlerinin
        yolları, kayda bağlı tg_indirilen satırları (çökme kurtarması için) ve henüz
        işlenmemiş inbox update'lerinin indirmeleri. Ardından dosyası kalmamış
        tg_indirilen satırları temizlenir.
        """
        cutoff = time.time() - _pending_saklama_saat() * 3600
        protected: set[str] = set()
        conn = self._conn()
        try:
            for row in conn.execute("SELECT veri FROM tg_oturumlar").fetchall():
                try:
                    value = json.loads(row["veri"])
                except (TypeError, ValueError):
                    continue
                if isinstance(value, dict) and value.get("pending_path"):
                    protected.add(self._pending_abs(value["pending_path"]) or "")
            for row in conn.execute(
                "SELECT local_path,source_path FROM donusum_isleri WHERE durum NOT IN ('tamam','hata','belirsiz','iptal')"
            ).fetchall():
                for value in (row["local_path"], row["source_path"]):
                    if value:
                        protected.add(self._pending_abs(value) or "")
            for row in conn.execute(
                "SELECT i.pending_path FROM tg_indirilen i JOIN kayitlar k ON k.telegram_bot_id=i.bot_id "
                "AND k.chat_id=i.chat_id AND k.message_id=i.message_id WHERE k.gorsel_dosya IS NOT NULL"
            ).fetchall():
                protected.add(self._pending_abs(row["pending_path"]) or "")
            for row in conn.execute(
                "SELECT i.pending_path FROM tg_indirilen i JOIN tg_gelen g ON g.bot_id=i.bot_id AND g.update_id=i.update_id "
                "WHERE g.durum IN ('bekliyor','tekrar')"
            ).fetchall():
                protected.add(self._pending_abs(row["pending_path"]) or "")
        finally:
            conn.close()
        protected.discard("")
        removed = 0
        pending_dir = self.media_root / "pending"
        try:
            entries = list(pending_dir.iterdir())
        except OSError:
            entries = []
        for path in entries:
            try:
                if not path.is_file() or str(path.resolve()) in protected or path.stat().st_mtime > cutoff:
                    continue
                path.unlink()
                removed += 1
            except OSError:
                continue
        conn = self._conn()
        try:
            with db.transaction(conn):
                rows = conn.execute("SELECT update_id,pending_path FROM tg_indirilen WHERE bot_id=?", (self.bot_id,)).fetchall()
                gone = [row["update_id"] for row in rows if not Path(self._pending_abs(row["pending_path"]) or "").is_file()]
                for update_id in gone:
                    conn.execute("DELETE FROM tg_indirilen WHERE bot_id=? AND update_id=?", (self.bot_id, int(update_id)))
        finally:
            conn.close()
        return removed, len(gone)

    def _gunluk_temizlik(self, force: bool = False) -> dict:
        """Başlangıçta ve günde bir: eski günlük satırları ve sahipsiz pending dosyaları (hata yutar)."""
        now = time.monotonic()
        if not force and self._son_temizlik is not None and now - self._son_temizlik < 86400:
            return {}
        self._son_temizlik = now
        result: dict[str, int] = {}
        try:
            result["tg_gelen"], result["tg_giden"] = self._eski_gunlukleri_sil()
        except Exception as exc:
            self._log(logging.WARNING, f"Günlük tablo temizliği yapılamadı: {exc}")
        try:
            result["pending"], result["tg_indirilen"] = self._sahipsiz_pending_temizle()
        except Exception as exc:
            self._log(logging.WARNING, f"Pending temizliği yapılamadı: {exc}")
        if any(result.values()):
            self._log(logging.INFO, "Temizlik: " + ", ".join(f"{k}={v}" for k, v in result.items()))
        return result

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
            # Engelli kullanıcıya bilgilendirme bir kez; sonrası sessiz (callback yine yanıtlanır).
            if self._uyari_izinli(uid, "engel", _engelli_uyari_saniye()):
                self._say(chat_id, "Erişiminiz engellenmiştir.")
            return
        session = self._get_session(conn, uid)
        # Callback'ler de yeni botun ilk parola kaydı olmadan akışı ilerletemez.
        if not self._authorized(conn, profile, uid):
            if self._uyari_izinli(uid, "parola", _parola_istem_saniye()):
                self._say(chat_id, "Bu botu kullanmak için önce /start yazıp parolayı gönderin.")
            return
        if self._maintenance(conn) and not self._admin_yetkili(uid, session):
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
        authorized = self._authorized(conn, profile, uid)
        if text.split(" ", 1)[0].lower() == "/kimim":
            # Yetkili kullanıcıya her zaman; engelli/onaysız kişiye hız sınırıyla yanıt.
            if authorized or self._uyari_izinli(uid, "kimim", 60):
                self._say(chat_id, f"<b>Telegram ID:</b> <code>{_h(uid)}</code>\n<b>Ad:</b> {_h(user.get('username') or user.get('first_name') or '-')}")
            return
        session = self._get_session(conn, uid)
        if profile.get("engelli"):
            # İlk mesajda bir kez bilgilendirilir; sonra BOT_ENGELLI_UYARI_SANIYE boyunca sessiz.
            if self._uyari_izinli(uid, "engel", _engelli_uyari_saniye()):
                self._say(chat_id, "Erişiminiz engellenmiştir.")
            return

        password = os.environ.get("BOT_PASSWORD", "")
        if not password:
            # Parola olmadan yönetici komutları dahil hiçbir normal akışa izin
            # verilmez; /kimim yukarıda zararsız kimlik sorgusu olarak kalır.
            if self._uyari_izinli(uid, "yapilandirma", 60):
                self._say(chat_id, "Bot henüz güvenli biçimde yapılandırılmadı; yöneticiyle iletişime geçin.")
            return
        handled, session = self._admin_command(conn, chat_id, user, text, session, int(message.get("message_id") or 0) or None)
        if handled:
            return
        if self._maintenance(conn) and not self._admin_yetkili(uid, session):
            if authorized or self._uyari_izinli(uid, "bakim", _parola_istem_saniye()):
                self._say(chat_id, "Bot şu anda bakım modunda. Lütfen daha sonra tekrar deneyin.")
            return

        image = self._image_from_message(message)
        if not authorized:
            if image:
                # Aktarımdan gelen eski genel onay sahibi yeni botta önce parola
                # girer. Gerçekten onaysız kişide politika .env ile seçilir:
                # 'engelle' (varsayılan): ilk görselde kalıcı engel;
                # 'parola': görsel indirilmez, deneme sayılır, MAX_DENEME'de engel.
                if profile.get("onayli"):
                    if self._uyari_izinli(uid, "parola", _parola_istem_saniye()):
                        self._say(chat_id, "Bu bot için önce parolayı yazın. Görseliniz indirilmedi; paroladan sonra yeniden gönderin.")
                elif _yetkisiz_gorsel_politikasi() == "parola":
                    trial = int(profile.get("deneme") or 0) + 1
                    if trial >= _max_deneme():
                        self._block(conn, uid, "yetkisiz_gorsel_gonderimi")
                        self._say(chat_id, "Bu bota görsel gönderme yetkiniz yok; erişiminiz engellendi.")
                    else:
                        conn.execute("UPDATE tg_kullanicilar SET deneme=? WHERE id=?", (trial, uid))
                        if self._uyari_izinli(uid, "parola", _parola_istem_saniye()):
                            self._say(chat_id, "Bu bota görsel göndermek için önce parolayı yazın; görseliniz indirilmedi.")
                else:
                    self._block(conn, uid, "yetkisiz_gorsel_gonderimi")
                    self._say(chat_id, "Bu bota görsel gönderme yetkiniz yok; erişiminiz engellendi.")
                return
            if text.startswith("/"):
                if self._uyari_izinli(uid, "parola", _parola_istem_saniye()):
                    self._say(chat_id, "Hoş geldiniz. Devam etmek için parolayı yazın.")
                return
            if not text:
                # Sticker, ses, konum, kişi, belge: parola denemesi sayılmaz.
                if self._uyari_izinli(uid, "parola", _parola_istem_saniye()):
                    self._say(chat_id, "Devam etmek için parolayı metin olarak yazın.")
                return
            if _esit(password, text):
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
            limit = _max_deneme()
            if trial >= limit:
                self._block(conn, uid, f"{limit}_yanlis_parola")
                self._say(chat_id, "Erişiminiz engellendi.")
            else:
                conn.execute("UPDATE tg_kullanicilar SET deneme=? WHERE id=?", (trial, uid))
                self._say(chat_id, f"Parola yanlış. {limit - trial} deneme hakkınız kaldı.")
            return
        if message.get("_image_error"):
            # Kalıcı görsel reddi: tek açıklama, yeniden indirme/deneme yok.
            self._say(chat_id, f"Görsel okunamadı: {_h(message['_image_error'])}. Lütfen fotoğrafı JPEG, PNG, WEBP veya GIF biçiminde, "
                               f"{self._max_image_bytes() // (1024 * 1024)} MiB altında yeniden gönderin.")
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
            self._log(logging.ERROR, "Yapılandırma hatası: BOT_PASSWORD ayarlanmamış; bot güvenli nedenle başlatılmadı (çıkış kodu 2). .env dosyasına BOT_PASSWORD ekleyip servisi yeniden başlatın.")
            return False
        if not self.token or not self.api:
            self._log(logging.ERROR, "Yapılandırma hatası: TELEGRAM_TOKEN ayarlanmamış; bot başlatılmadı (çıkış kodu 2). .env dosyasına TELEGRAM_TOKEN ekleyip servisi yeniden başlatın.")
            return False
        lock = BotLock(Path(self.ayar["BOT_KLASOR"]) / "locks" / f"telegram-{_safe_piece(self.bot_id, 64)}.lock")
        if not lock.acquire():
            self._log(logging.ERROR, "Bu bot için başka bir süreç zaten çalışıyor; ikinci kopya başlatılmadı (çıkış kodu 2). Çift kurulum/servis olup olmadığını kontrol edin.")
            return False
        try:
            # Webhook varsa asla sessizce deleteWebhook çağrısı yapmayız. getMe yalnızca
            # nabız/kimlik görünümü içindir; webhook sahipliği olduğu gibi korunur.
            # Geçici ağ hatasında süreç hemen çıkmaz (systemd hızlı yeniden başlatma
            # döngüsü yerine bekleyip yeniden dener); kalıcı hatada (geçersiz token) çıkar.
            attempt = 0
            while True:
                try:
                    me = self.api.call("getMe", {}, timeout=20)
                    self._heartbeat(username=str((me or {}).get("username") or ""))
                    webhook = self.api.call("getWebhookInfo", {}, timeout=20) or {}
                    if isinstance(webhook, dict) and webhook.get("url"):
                        message = "Yapılandırma hatası: bot webhook ile yapılandırılmış; webhook silinmedi ve long polling başlatılmadı (çıkış kodu 2). Telegram'da webhook'u kaldırın ya da bu servisi durdurun."
                        self._heartbeat(message)
                        self._log(logging.ERROR, message)
                        return False
                    break
                except TelegramHatasi as exc:
                    self._heartbeat(str(exc))
                    if exc.kalici or once or self._stopped:
                        self._log(logging.ERROR, f"Telegram bağlantı hatası; bot başlatılmadı (çıkış kodu 2). TELEGRAM_TOKEN değerini ve ağ erişimini kontrol edin: {exc}")
                        return False
                    attempt += 1
                    wait = min(300, 15 * attempt)
                    self._log(logging.WARNING, f"Telegram'a ulaşılamadı (deneme {attempt}); {wait} sn sonra yeniden denenecek: {exc}")
                    time.sleep(wait)
                    if self._stopped:
                        return True
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
                    self._gunluk_temizlik()
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

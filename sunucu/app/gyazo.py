"""Opsiyonel Gyazo adaptörü.

Token yalnız HTTP gövdesine gider; bu modül tokenı veya sağlayıcı yanıt gövdesini
loglamaz. ``upload`` ve ``verify`` kuyruk işçisinin ayrı safhalarıdır: başarılı
bir upload sonrasında doğrulama yeniden denenirken tekrar POST yapılmaz.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from . import db
from .settings import AYAR

MAX_BYTES = 10 * 1024 * 1024
IMAGE_ID = re.compile(r"^[0-9a-f]{32}$", re.I)
UPLOAD_URL = "https://upload.gyazo.com/api/upload"


def _failure(message: str, *, status: int | None = None, retryable: bool = False,
             ambiguous: bool = False) -> dict:
    return {"ok": False, "url": None, "error": message, "http_status": status,
            "retryable": bool(retryable), "ambiguous": bool(ambiguous)}


def _message(status: int | None, *, verify: bool = False) -> str:
    if status in (401, 403):
        return "Gyazo erişim anahtarı/yetkilendirmesi reddedildi."
    if status == 429:
        return "Gyazo istek sınırına ulaştı."
    if status is not None and status >= 500:
        return "Gyazo sunucusunda hata var."
    return "Gyazo bağlantısı erişilemiyor; yerel görsel korunuyor." if verify else "Gyazo dönüşümü doğrulanamadı."


def _local_image(path: str | Path) -> tuple[Path, str] | dict:
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return _failure("Dönüştürülecek yerel görsel yok veya 10 MB sınırını aşıyor.")
        with Image.open(path) as image:
            if image.width * image.height > 25_000_000:
                return _failure("Görsel piksel sınırını aşıyor.")
            fmt = image.format
            image.verify()
        ext = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}.get(str(fmt or "").upper())
        if not ext:
            return _failure("Bu görsel biçimi dönüştürülemiyor.")
        return path, ext
    except (OSError, ValueError, Image.DecompressionBombError):
        return _failure("Yerel görüntü doğrulanamadı.")


def _safe_image_url(url: object) -> str | None:
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if (parsed.scheme not in ("http", "https") or parsed.hostname != "i.gyazo.com"
            or parsed.username or parsed.password or not parsed.path.startswith("/")):
        return None
    # The returned host is rebuilt rather than trusting a textual prefix.
    return "https://i.gyazo.com" + parsed.path


def _close(response) -> None:
    try:
        response.close()
    except Exception:
        pass


def upload(path: str | Path, token: str | None = None, *, http=None) -> dict:
    """POST a local image once; it does **not** perform CDN verification.

    A read timeout after request submission is marked ambiguous and must not be
    blind-retried. Connection setup failures, HTTP 429 and HTTP 5xx are marked
    retryable for the durable worker's bounded backoff policy.
    """
    token = os.getenv("GYAZO_TOKEN", "") if token is None else token
    if not token:
        return _failure("Gyazo dönüşümü için GYAZO_TOKEN yapılandırılmamış.")
    local = _local_image(path)
    if isinstance(local, dict):
        return local
    path, ext = local
    owned_http = http is None
    http = http or requests.Session()
    response = None
    try:
        mime = "image/jpeg" if ext == "jpg" else "image/" + ext
        with path.open("rb") as image:
            response = http.post(
                UPLOAD_URL,
                data={"access_token": token, "access_policy": "anyone", "metadata_is_public": "false", "app": "KanitPaneli"},
                files={"imagedata": ("kanit." + ext, image, mime)},
                timeout=(3, 8), allow_redirects=False,
            )
        status = int(getattr(response, "status_code", 0) or 0)
        if not 200 <= status < 300:
            return _failure(_message(status), status=status, retryable=status == 429 or status >= 500)
        try:
            result = response.json()
        except (ValueError, TypeError):
            # 2xx sonrasında bozuk/yarım yanıt, sağlayıcının görseli kabul edip
            # etmediğini kanıtlamaz. Aynı POST'u körlemesine tekrarlamayız.
            return _failure("Gyazo yanıt biçimi geçersiz; yerel görsel korunuyor.", status=status, ambiguous=True)
        gid = str(result.get("image_id", "")) if isinstance(result, dict) else ""
        image_url = _safe_image_url(result.get("url") if isinstance(result, dict) else None)
        if not IMAGE_ID.fullmatch(gid) or not image_url:
            return _failure("Gyazo bağlantısı erişilemiyor; yerel görsel korunuyor.", status=status, ambiguous=True)
        return {"ok": True, "image_id": gid.lower(), "image_url": image_url, "url": None,
                "error": None, "http_status": status, "retryable": False, "ambiguous": False}
    except requests.ConnectTimeout:
        return _failure("Gyazo bağlantısı kurulamadı; yerel görsel korunuyor.", retryable=True)
    except requests.ReadTimeout:
        return _failure("Gyazo yanıt süresi aşıldı; yüklemenin dış serviste tamamlanıp tamamlanmadığı belirsiz.", ambiguous=True)
    except requests.Timeout:
        return _failure("Gyazo yanıt süresi aşıldı; yüklemenin dış serviste tamamlanıp tamamlanmadığı belirsiz.", ambiguous=True)
    except requests.ConnectionError:
        # requests burada HTTP yanıtı alınmadan bağlantı kurulamadığını bildirir.
        return _failure("Gyazo bağlantısı kurulamadı; yerel görsel korunuyor.", retryable=True)
    except (requests.RequestException, OSError):
        # Generic request failures may be raised after bytes have left the
        # process. Treat them as unknown rather than risking a duplicate POST.
        return _failure("Gyazo servisine ulaşılamadı; yerel görsel korunuyor.", ambiguous=True)
    finally:
        _close(response)
        if owned_http:
            _close(http)


def verify(image_id: str | None, image_url: str | None, *, http=None) -> dict:
    """Verify an already-uploaded CDN image without submitting another POST."""
    gid = str(image_id or "")
    safe_url = _safe_image_url(image_url)
    if not IMAGE_ID.fullmatch(gid) or not safe_url:
        return _failure("Gyazo doğrulama verisi geçersiz.")
    owned_http = http is None
    http = http or requests.Session()
    response = None
    try:
        response = http.get(safe_url, stream=True, timeout=(3, 4), allow_redirects=False)
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).lower()
        if status == 200 and content_type.startswith("image/"):
            return {"ok": True, "url": "https://gyazo.com/" + gid.lower(), "error": None,
                    "http_status": status, "retryable": False, "ambiguous": False}
        return _failure(_message(status, verify=True), status=status, retryable=status == 429 or status >= 500)
    except (requests.ConnectTimeout, requests.ConnectionError):
        return _failure("Gyazo görüntü bağlantısına ulaşılamadı.", retryable=True)
    except requests.Timeout:
        return _failure("Gyazo görüntü bağlantısının yanıt süresi aşıldı.", retryable=True)
    except requests.RequestException:
        return _failure("Gyazo görüntü bağlantısına ulaşılamadı.")
    finally:
        _close(response)
        if owned_http:
            _close(http)


def _reachable(http, url: str) -> bool:
    """Backward-compatible boolean verifier used only by ``convert`` cache."""
    result = verify("a" * 32, url, http=http)
    return bool(result.get("ok"))


def convert(path: str | Path, token: str | None = None) -> dict:
    """Compatibility wrapper for legacy synchronous callers.

    New work should enqueue a durable job instead.  This wrapper retains the old
    24-hour cache and returns the historical ``ok/url/error`` shape.
    """
    token = os.getenv("GYAZO_TOKEN", "") if token is None else token
    if not token:
        return _failure("Gyazo dönüşümü için GYAZO_TOKEN yapılandırılmamış.")
    local = _local_image(path)
    if isinstance(local, dict):
        return local
    local_path, _ = local
    digest = hashlib.sha256(local_path.read_bytes() + str(token).encode()).hexdigest()
    conn = db.baglan(AYAR["DB"])
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS gyazo_cache(anahtar TEXT PRIMARY KEY,url TEXT,gorsel_url TEXT,zaman REAL)")
        old = conn.execute("SELECT * FROM gyazo_cache WHERE anahtar=?", (digest,)).fetchone()
    finally:
        conn.close()
    http = requests.Session()
    try:
        if old and old["zaman"] > time.time() - 86400:
            verified = verify(str(old["url"]).rsplit("/", 1)[-1], old["gorsel_url"], http=http)
            if verified.get("ok"):
                return {"ok": True, "url": old["url"], "error": None}
        posted = upload(local_path, token=token, http=http)
        if not posted.get("ok"):
            return {"ok": False, "url": None, "error": posted["error"]}
        checked = verify(posted["image_id"], posted["image_url"], http=http)
        if not checked.get("ok"):
            return {"ok": False, "url": None, "error": checked["error"]}
        conn = db.baglan(AYAR["DB"])
        try:
            conn.execute(
                "INSERT INTO gyazo_cache(anahtar,url,gorsel_url,zaman) VALUES(?,?,?,?) "
                "ON CONFLICT(anahtar) DO UPDATE SET url=excluded.url,gorsel_url=excluded.gorsel_url,zaman=excluded.zaman",
                (digest, checked["url"], posted["image_url"], time.time()),
            )
        finally:
            conn.close()
        return {"ok": True, "url": checked["url"], "error": None}
    finally:
        _close(http)

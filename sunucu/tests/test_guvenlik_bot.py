# -*- coding: utf-8 -*-
"""Güvenlik düzeltme turu (v2.3.0) — Telegram botu sağlamlık/güvenlik regresyonları.

Gerçek Telegram API'sine istek atılmaz; tests/test_bot.py'deki sahte oturum deseni
hata enjeksiyonu (403/429/ağ) ile genişletilmiştir.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import pytest
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bot as bot_module  # noqa: E402
from app import bot_yonetim, db, donusum_isleri  # noqa: E402
from app.bot import GorselReddedildi, KanitBot, TelegramAPI, TelegramHatasi, _html_parcala, _redact  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, content=b"", status=200):
        self.payload = payload or {"ok": True, "result": True}
        self.content = content
        self.status_code = status
        self.headers = {"Content-Length": str(len(content))} if content else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} /bot123:secret/")

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


def tg_error(code, description, **params):
    payload = {"ok": False, "error_code": code, "description": description}
    if params:
        payload["parameters"] = params
    return payload


class FakeTelegram:
    """sendMessage/getMe için sıralı hata enjeksiyonu destekleyen sahte requests oturumu."""

    def __init__(self, files=None, fail_download=False):
        self.files = files or {}
        self.fail_download = fail_download
        self.calls = []
        self.downloads = 0
        self.next_message = 100
        self.updates = []
        self.send_errors = []   # her sendMessage bir öğe tüketir: Exception ya da ok=false payload
        self.getme_errors = []

    def _inject(self, queue):
        if not queue:
            return None
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item, status=int(item.get("error_code") or 200))

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json or {}))
        if method == "getUpdates":
            return FakeResponse({"ok": True, "result": self.updates})
        if method == "getFile":
            fid = (json or {}).get("file_id")
            if fid not in self.files:
                return FakeResponse(tg_error(400, "Bad Request: file missing"), status=400)
            data = self.files[fid]
            return FakeResponse({"ok": True, "result": {"file_path": f"files/{fid}", "file_size": len(data)}})
        if method == "sendMessage":
            injected = self._inject(self.send_errors)
            if injected is not None:
                return injected
            self.next_message += 1
            return FakeResponse({"ok": True, "result": {"message_id": self.next_message}})
        if method == "getMe":
            injected = self._inject(self.getme_errors)
            if injected is not None:
                return injected
            return FakeResponse({"ok": True, "result": {"id": 123, "username": "fake"}})
        return FakeResponse({"ok": True, "result": True})

    def get(self, url, stream=True, timeout=None):
        self.downloads += 1
        if self.fail_download:
            raise requests.ConnectionError("http://example.invalid/file/bot123:secret/x")
        fid = url.rsplit("/", 1)[-1]
        return FakeResponse(content=self.files[fid])


def png_bytes():
    bio = io.BytesIO()
    Image.new("RGB", (3, 3), "red").save(bio, format="PNG")
    return bio.getvalue()


def zip_bytes():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("a.txt", "görsel değil")
    return bio.getvalue()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BOT_PASSWORD", "parola")
    monkeypatch.setenv("ADMIN_PASSWORD", "yonetici")
    monkeypatch.setenv("ADMIN_IDS", "1")
    for key in ("MAX_DENEME", "BOT_YETKISIZ_GORSEL_POLITIKA", "BOT_OUTBOX_MAX_DENEME", "BOT_GUNLUK_SAKLAMA_GUN",
                "BOT_LOG_MAX_MB", "ADMIN_PROMPT_SANIYE", "ADMIN_KILIT_SANIYE", "ADMIN_MAX_DENEME", "ADMIN_OTURUM_SANIYE",
                "BOT_ENGELLI_UYARI_SANIYE", "BOT_PAROLA_ISTEM_SANIYE", "BOT_PENDING_SAKLAMA_SAAT"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def setup(tmp_path, env):
    ayar = {
        "DB": str(tmp_path / "panel.db"), "BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(tmp_path / "medya"),
        "LOG_DOSYA": str(tmp_path / "bot.log"), "MAX_GORSEL_BYTES": 10 * 1024 * 1024,
        "PROJELER": ["PP", "PA", "OF", "HI", "VI", "GA"],
    }
    fake = FakeTelegram({"f1": png_bytes(), "zip": zip_bytes()})
    api = TelegramAPI("123:secret", session=fake, api_base="http://fake.telegram")
    return ayar, fake, KanitBot(ayar, token="123:secret", api=api)


def message(update_id, message_id, text=None, photo=False, document=False, user=1, file_id="f1", file_size=100, extra=None):
    m = {"message_id": message_id, "chat": {"id": user, "type": "private"}, "from": {"id": user, "username": f"u{user}", "first_name": "U"}}
    if text is not None:
        m["text"] = text
    if photo:
        m["photo"] = [{"file_id": file_id, "file_unique_id": "uniq" + file_id, "file_size": file_size}]
    if document:
        m["document"] = {"file_id": file_id, "file_unique_id": "uniq" + file_id, "file_size": file_size, "mime_type": "image/png", "file_name": "iddia.png"}
    if extra:
        m.update(extra)
    return {"update_id": update_id, "message": m}


def callback(update_id, ui_message_id, data, user=1):
    return {"update_id": update_id, "callback_query": {
        "id": f"cb{update_id}", "from": {"id": user, "username": f"u{user}"}, "data": data,
        "message": {"message_id": ui_message_id, "chat": {"id": user, "type": "private"}},
    }}


def q(ayar, sql, params=()):
    conn = db.baglan(ayar["DB"])
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run(ayar, sql, params=()):
    conn = db.baglan(ayar["DB"])
    try:
        with db.transaction(conn):
            conn.execute(sql, params)
    finally:
        conn.close()


def session(ayar, bot, user=1):
    rows = q(ayar, "SELECT veri FROM tg_oturumlar WHERE bot_id=? AND user_id=?", (bot.bot_id, str(user)))
    return json.loads(rows[0]["veri"]) if rows else None


def feed(bot, update):
    bot._durable_insert([update])
    assert bot.process_pending() == 1


def sends(fake, start=0):
    return [payload.get("text", "") for method, payload in fake.calls[start:] if method == "sendMessage"]


def authorize(ayar, bot, user=1, uid_base=1):
    feed(bot, message(uid_base, uid_base, "/start", user=user))
    feed(bot, message(uid_base + 1, uid_base + 1, "parola", user=user))
    return q(ayar, "SELECT * FROM tg_kullanicilar WHERE id=?", (str(user),))[0]


def admin_login(ayar, fake, bot, base=900):
    feed(bot, message(base, base, "/admin"))
    feed(bot, message(base + 1, base + 1, "yonetici"))
    assert session(ayar, bot)["admin_until"] > time.time()


# ---- 1. kalıcı görsel hatası -------------------------------------------------------------------
def test_kalici_gorsel_hatasi_tek_deneme_ve_kullanici_mesaji(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    start = len(fake.calls)
    downloads = fake.downloads
    feed(bot, message(10, 10, document=True, file_id="zip"))  # mime image/png, içerik ZIP
    row = q(ayar, "SELECT durum,deneme,veri FROM tg_gelen WHERE bot_id=? AND update_id=10", (bot.bot_id,))[0]
    assert (row["durum"], row["deneme"], row["veri"]) == ("tamam", 0, "{}")
    assert sum(1 for m, _ in fake.calls[start:] if m == "getFile") == 1
    assert fake.downloads - downloads == 1
    texts = sends(fake, start)
    assert len(texts) == 1 and "Görsel okunamadı" in texts[0] and "yeniden gönderin" in texts[0]
    assert session(ayar, bot) is None
    assert not list((Path(ayar["GORSEL_KLASOR"]) / "pending").iterdir())
    # Panelden 'tekrar dene' yapılsa bile ikinci indirme yok: update tamamlandı.
    assert bot.process_pending() == 0

    # Beyan edilen boyut sınırı aşılıyorsa ağ hiç kullanılmaz; yine tek açıklama.
    start = len(fake.calls)
    feed(bot, message(11, 11, photo=True, file_size=11 * 1024 * 1024))
    assert sum(1 for m, _ in fake.calls[start:] if m == "getFile") == 0
    assert any("MiB sınırını aşıyor" in t for t in sends(fake, start))
    assert q(ayar, "SELECT durum FROM tg_gelen WHERE bot_id=? AND update_id=11", (bot.bot_id,))[0]["durum"] == "tamam"


def test_ag_hatasi_gecici_kalir_ve_gorsel_dogrulama_hatasi_kalici_siniftir(setup):
    ayar, _, bot = setup
    authorize(ayar, bot)
    failing = FakeTelegram({"f1": png_bytes()}, fail_download=True)
    bot2 = KanitBot(ayar, token="123:secret", api=TelegramAPI("123:secret", session=failing, api_base="http://fake"))
    bot2._durable_insert([message(50, 50, photo=True)])
    assert bot2.process_pending() == 0
    row = q(ayar, "SELECT durum,deneme,hata FROM tg_gelen WHERE bot_id=? AND update_id=50", (bot2.bot_id,))[0]
    assert row["durum"] == "tekrar" and row["deneme"] == 1 and "secret" not in (row["hata"] or "")
    with pytest.raises(GorselReddedildi):
        bot.ayar["MAX_IMAGE_PIXELS"] = 1
        bot._download_image({"file_id": "f1", "file_unique_id": "u", "file_size": 100}, "1", 1)
    assert issubclass(GorselReddedildi, TelegramHatasi)
    # İndirme boyutu tavanı: ayar ne derse desin Telegram getFile sınırı (20 MB) aşılmaz.
    bot.ayar["MAX_GORSEL_BYTES"] = 500 * 1024 * 1024
    assert bot._max_image_bytes() == 20 * 1024 * 1024


# ---- 2. outbox kalıcı hata / 8. 429 ----------------------------------------------------------
def test_outbox_kalici_hata_olu_ve_long_poll_normale_doner(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    start = len(fake.calls)
    fake.send_errors = [tg_error(403, "Forbidden: bot was blocked by the user")] * 5
    feed(bot, message(10, 10, "/start"))
    row = q(ayar, "SELECT durum,deneme,hata FROM tg_giden WHERE bot_id=? AND source_update_id=10", (bot.bot_id,))[0]
    assert row["durum"] == "olu" and row["deneme"] == 1 and "blocked by the user" in row["hata"]
    assert sum(1 for m, _ in fake.calls[start:] if m == "sendMessage") == 1
    assert bot.process_outbox() == 0  # ölü satır yeniden denenmez
    bot.poll_once(25)
    assert fake.calls[-1][1]["timeout"] == 25
    log = Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")
    assert "vazgeçildi" in log and "secret" not in log


def test_outbox_gecici_hata_sinirli_tekrar_sonra_olu(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    fake.send_errors = [requests.ConnectionError("http://x/bot123:secret/send")] * 20
    feed(bot, message(10, 10, "/start"))
    key = q(ayar, "SELECT action_key,durum,deneme FROM tg_giden WHERE bot_id=? AND source_update_id=10", (bot.bot_id,))[0]
    assert (key["durum"], key["deneme"]) == ("tekrar", 1)
    # Zamanı gelmemiş tekrar long-poll'u kısaltmaz; zamanı gelen 2 sn'ye çeker.
    run(ayar, "UPDATE tg_giden SET guncelleme='2099-01-01 00:00:00' WHERE bot_id=? AND action_key=?", (bot.bot_id, key["action_key"]))
    bot.poll_once(25); assert fake.calls[-1][1]["timeout"] == 25
    run(ayar, "UPDATE tg_giden SET guncelleme='2000-01-01 00:00:00' WHERE bot_id=? AND action_key=?", (bot.bot_id, key["action_key"]))
    bot.poll_once(25); assert fake.calls[-1][1]["timeout"] == 2
    states = []
    for _ in range(6):
        run(ayar, "UPDATE tg_giden SET guncelleme='2000-01-01 00:00:00' WHERE bot_id=? AND action_key=? AND durum='tekrar'", (bot.bot_id, key["action_key"]))
        bot.process_outbox()
        r = q(ayar, "SELECT durum,deneme FROM tg_giden WHERE bot_id=? AND action_key=?", (bot.bot_id, key["action_key"]))[0]
        states.append((r["durum"], r["deneme"]))
    assert states == [("tekrar", 2), ("tekrar", 3), ("tekrar", 4), ("olu", 5), ("olu", 5), ("olu", 5)]
    bot.poll_once(25); assert fake.calls[-1][1]["timeout"] == 25
    assert q(ayar, "SELECT COUNT(*) n FROM tg_giden WHERE bot_id=? AND durum='tekrar'", (bot.bot_id,))[0]["n"] == 0


def test_429_retry_after_ilgili_sohbetin_gonderimlerini_duraklatir(setup):
    """429 yalnız o sohbeti duraklatır (tek sohbetin seli diğerlerini durdurmaz; bkz. test_qa_bot.py)."""
    ayar, fake, bot = setup
    authorize(ayar, bot)
    bot._durable_insert([message(10, 10, "/start"), message(11, 11, "/start"), message(12, 12, "/start")])
    start = len(fake.calls)
    fake.send_errors = [tg_error(429, "Too Many Requests: retry after 5", retry_after=5)]
    assert bot.process_pending() == 3
    assert sum(1 for m, _ in fake.calls[start:] if m == "sendMessage") == 1  # aynı sohbetin kalanı denenmedi
    rows = q(ayar, "SELECT durum,deneme FROM tg_giden WHERE bot_id=? AND source_update_id IN (10,11,12) ORDER BY id", (bot.bot_id,))
    assert [tuple(r.values()) for r in rows] == [("tekrar", 0), ("bekliyor", 0), ("bekliyor", 0)]  # 429 deneme saymaz
    assert bot.process_outbox() == 0 and bot._outbox_duraklama("1") > 0
    assert bot._outbox_duraklama() == 0  # tek sohbet: genel duraklama yok
    bot.poll_once(25)
    assert fake.calls[-1][1]["timeout"] <= 6  # duraklama bitince kuyruk hemen akar
    bot._chat_duraklat.clear()  # süre doldu
    run(ayar, "UPDATE tg_giden SET guncelleme='2000-01-01 00:00:00' WHERE bot_id=? AND durum='tekrar'", (bot.bot_id,))
    assert bot.process_outbox() == 3
    assert q(ayar, "SELECT COUNT(*) n FROM tg_giden WHERE bot_id=? AND durum!='tamam'", (bot.bot_id,))[0]["n"] == 0


def test_telegram_api_hatasi_durum_ve_retry_after_tasir(setup):
    _, fake, bot = setup
    fake.send_errors = [tg_error(400, "Bad Request: can't parse entities")]
    with pytest.raises(TelegramHatasi) as info:
        bot.api.send_message("1", "<b>x")
    assert info.value.status == 400 and info.value.kalici and info.value.retry_after is None
    fake.send_errors = [tg_error(429, "Too Many Requests", retry_after=7)]
    with pytest.raises(TelegramHatasi) as info:
        bot.api.send_message("1", "x")
    assert info.value.status == 429 and not info.value.kalici and info.value.retry_after == 7
    fake.send_errors = [requests.ConnectionError("http://x/bot123:secret/")]
    with pytest.raises(TelegramHatasi) as info:
        bot.api.send_message("1", "x")
    assert info.value.status is None and not info.value.kalici and "secret" not in str(info.value)


# ---- 3. yönetici parola akışı ----------------------------------------------------------------
def test_admin_parola_istemi_suresi_ve_mesaj_silme(setup):
    ayar, fake, bot = setup
    feed(bot, message(1, 1, "/admin"))
    assert any("dakika geçerlidir" in t for t in sends(fake))
    s = session(ayar, bot)
    s["admin_prompt"] = int(time.time()) - 5
    run(ayar, "UPDATE tg_oturumlar SET veri=? WHERE bot_id=? AND user_id='1'", (json.dumps(s), bot.bot_id))
    start = len(fake.calls)
    feed(bot, message(2, 2, "yonetici"))
    assert any("süresi doldu" in t for t in sends(fake, start))
    assert "admin_until" not in (session(ayar, bot) or {})
    assert any(m == "deleteMessage" and p.get("message_id") == 2 for m, p in fake.calls[start:])
    # Süresi içinde doğru parola: oturum açılır, parola mesajı silinir, denetim yazılır.
    feed(bot, message(3, 3, "/admin"))
    start = len(fake.calls)
    feed(bot, message(4, 4, "yonetici"))
    assert any(m == "deleteMessage" and p.get("message_id") == 4 for m, p in fake.calls[start:])
    s = session(ayar, bot)
    assert s["admin_until"] > time.time() + 1700
    audit = q(ayar, "SELECT islem,sonuc,yeni FROM denetim WHERE kullanici='1' AND islem='telegram_admin_giris' ORDER BY id DESC LIMIT 1")[0]
    assert audit["sonuc"] == "ok" and "admin" in audit["yeni"]
    assert not any("yonetici" in p.get("text", "") for m, p in fake.calls if m == "sendMessage")


def test_admin_yanlis_deneme_sayaci_ve_kilit(setup, monkeypatch):
    ayar, fake, bot = setup
    for i in range(3):
        feed(bot, message(10 + 2 * i, 10 + 2 * i, "/admin"))
        start = len(fake.calls)
        feed(bot, message(11 + 2 * i, 11 + 2 * i, f"yanlis{i}"))
        assert any(m == "deleteMessage" and p.get("message_id") == 11 + 2 * i for m, p in fake.calls[start:])
    texts = sends(fake)
    assert any("2 deneme hakkınız kaldı" in t for t in texts)
    assert any("beklemeniz gerekir" in t for t in texts)
    assert q(ayar, "SELECT COUNT(*) n FROM denetim WHERE kullanici='1' AND islem='telegram_admin_giris_hata' AND sonuc='hata'")[0]["n"] == 3
    start = len(fake.calls)
    feed(bot, message(30, 30, "/admin"))
    assert any("Çok fazla hatalı" in t for t in sends(fake, start))
    assert "admin_prompt" not in (session(ayar, bot) or {})
    # Kilit süresi dolunca sayaç sıfırlanır ve doğru parola kabul edilir.
    bot._admin_hatali["1"]["kilit"] = time.monotonic() - 1
    feed(bot, message(31, 31, "/admin")); feed(bot, message(32, 32, "yonetici"))
    assert session(ayar, bot)["admin_until"] > time.time()
    # Yönetici parolası yanlış deneme BOT_PASSWORD sayacını ve engel durumunu etkilemez.
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='1'")[0]
    assert (user["deneme"], user["engelli"]) == (0, 0)


def test_admin_oturumu_hareketsizlik_admin_ids_ve_akis_korumasi(setup, monkeypatch):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    admin_login(ayar, fake, bot)
    # Her komut hareketsizlik süresini yeniler.
    s = session(ayar, bot); s["admin_until"] = int(time.time()) + 10
    run(ayar, "UPDATE tg_oturumlar SET veri=? WHERE bot_id=? AND user_id='1'", (json.dumps(s), bot.bot_id))
    start = len(fake.calls)
    feed(bot, message(20, 20, "/durum"))
    assert any("DURUM" in t and "Teslim edilemeyen" in t for t in sends(fake, start))
    assert session(ayar, bot)["admin_until"] > time.time() + 1000
    # Fotoğraf/Lead akışı başlatmak yönetici oturumunu düşürmez.
    feed(bot, message(21, 21, photo=True))
    assert session(ayar, bot)["admin_until"] > time.time()
    feed(bot, message(22, 22, "LEAD-1"))
    assert session(ayar, bot)["admin_until"] > time.time()
    # ADMIN_IDS'ten çıkarılan kişi yerleşik komutları kullanamaz, bakımı aşamaz.
    monkeypatch.setenv("ADMIN_IDS", "999")
    start = len(fake.calls)
    feed(bot, message(23, 23, "/durum"))
    assert any("önce /admin" in t for t in sends(fake, start))
    run(ayar, "INSERT INTO ayarlar(anahtar,deger) VALUES('bakim_modu','1') ON CONFLICT(anahtar) DO UPDATE SET deger='1'")
    start = len(fake.calls)
    feed(bot, message(24, 24, "LEAD-2"))
    assert any("bakım modunda" in t for t in sends(fake, start))
    # Yönetici olmayan kişinin /admin seli hız sınırlıdır.
    for i in range(5):
        feed(bot, message(40 + i, 40 + i, "/admin", user=5))
    assert sum(1 for t in sends(fake) if "yönetici erişimi tanımlı değil" in t) == 1


# ---- 4. engelli/yabancı yanıt sınırı ve budama -----------------------------------------------
def test_engelli_kullaniciya_yanit_siniri(setup):
    ayar, fake, bot = setup
    for i in range(3):
        feed(bot, message(10 + i, 10 + i, f"yanlis{i}", user=2))
    assert q(ayar, "SELECT engelli FROM tg_kullanicilar WHERE id='2'")[0]["engelli"] == 1
    start = len(fake.calls)
    for i in range(20):
        feed(bot, message(100 + i, 100 + i, f"spam {i}", user=2))
    for i in range(5):
        feed(bot, callback(200 + i, 1, "storage:local", user=2))
    texts = sends(fake, start)
    assert texts.count("Erişiminiz engellenmiştir.") == 1 and len(texts) == 1
    assert sum(1 for m, _ in fake.calls[start:] if m == "answerCallbackQuery") == 5
    # Süre geçince (bellek içi pencere) yeniden tek uyarı.
    bot._uyari_zamani.clear()
    start = len(fake.calls)
    feed(bot, message(300, 300, "yine", user=2))
    assert sends(fake, start) == ["Erişiminiz engellenmiştir."]
    assert bot_module._engelli_uyari_saniye() == 600


def test_onaysiz_kullanici_parola_istemi_hiz_sinirli_ve_kimim(setup, monkeypatch):
    ayar, fake, bot = setup
    start = len(fake.calls)
    for i in range(10):
        feed(bot, message(10 + i, 10 + i, f"/start{i}", user=3))
    assert sum(1 for t in sends(fake, start) if "Hoş geldiniz" in t) == 1
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='3'")[0]
    assert (user["deneme"], user["engelli"]) == (0, 0)
    start = len(fake.calls)
    for i in range(5):
        feed(bot, message(30 + i, 30 + i, "/kimim", user=3))
    assert sum(1 for t in sends(fake, start) if "Telegram ID" in t) == 1
    monkeypatch.setenv("BOT_PAROLA_ISTEM_SANIYE", "0")  # 0 → en az 1 sn'ye kırpılır
    assert bot_module._parola_istem_saniye() == 1


def test_sticker_ve_metinsiz_mesaj_parola_denemesi_sayilmaz(setup):
    ayar, fake, bot = setup
    start = len(fake.calls)
    feed(bot, message(10, 10, user=4, extra={"sticker": {"file_id": "s1"}}))
    feed(bot, message(11, 11, user=4, extra={"voice": {"file_id": "v1"}}))
    feed(bot, message(12, 12, user=4, extra={"document": {"file_id": "d1", "mime_type": "application/pdf", "file_name": "x.pdf"}}))
    feed(bot, message(13, 13, user=4, extra={"location": {"latitude": 1, "longitude": 2}}))
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='4'")[0]
    assert (user["deneme"], user["engelli"]) == (0, 0)
    texts = sends(fake, start)
    assert texts == ["Devam etmek için parolayı metin olarak yazın."]
    # Ardından doğru parola normal şekilde kabul edilir.
    feed(bot, message(14, 14, "parola", user=4))
    assert q(ayar, "SELECT onayli FROM tg_kullanicilar WHERE id='4'")[0]["onayli"] == 1


def test_budama_eski_satirlari_siler_aktif_olanlari_korur(setup, monkeypatch):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    assert q(ayar, "SELECT COUNT(*) n FROM tg_gelen WHERE durum='tamam'")[0]["n"] >= 2
    run(ayar, "UPDATE tg_gelen SET guncelleme='2020-01-01 00:00:00'")
    run(ayar, "UPDATE tg_giden SET guncelleme='2020-01-01 00:00:00'")
    now = db.simdi()
    run(ayar, "INSERT INTO tg_gelen(bot_id,update_id,veri,durum,deneme,olusturma,guncelleme) VALUES(?,999,'{}','bekliyor',0,'2020-01-01 00:00:00','2020-01-01 00:00:00')", (bot.bot_id,))
    run(ayar, "INSERT INTO tg_gelen(bot_id,update_id,veri,durum,deneme,olusturma,guncelleme) VALUES(?,998,'{}','olu',5,'2020-01-01 00:00:00',?)", (bot.bot_id, now))
    run(ayar, "INSERT INTO tg_giden(bot_id,action_key,tur,chat_id,metin,durum,deneme,olusturma,guncelleme) VALUES(?,'k:tekrar','send','1','x','tekrar',1,'2020-01-01 00:00:00','2020-01-01 00:00:00')", (bot.bot_id,))
    monkeypatch.setenv("BOT_GUNLUK_SAKLAMA_GUN", "3650")
    assert bot._gunluk_temizlik(force=True)["tg_gelen"] == 0  # saklama süresi içindeyse silinmez
    monkeypatch.delenv("BOT_GUNLUK_SAKLAMA_GUN")
    result = bot._gunluk_temizlik(force=True)
    assert result["tg_gelen"] >= 2 and result["tg_giden"] >= 2
    remaining = q(ayar, "SELECT update_id,durum FROM tg_gelen WHERE bot_id=? ORDER BY update_id", (bot.bot_id,))
    assert [(r["update_id"], r["durum"]) for r in remaining] == [(998, "olu"), (999, "bekliyor")]
    assert [r["durum"] for r in q(ayar, "SELECT durum FROM tg_giden WHERE bot_id=?", (bot.bot_id,))] == ["tekrar"]
    # Günde bir: hemen ardından zorlamasız çağrı hiçbir şey yapmaz; hata yutulur.
    assert bot._gunluk_temizlik() == {}
    monkeypatch.setattr(bot, "_eski_gunlukleri_sil", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    assert "tg_gelen" not in bot._gunluk_temizlik(force=True)
    assert "temizliği yapılamadı" in Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")


# ---- 6. bakım modunda indirme yok, sahipsiz pending temizliği -------------------------------
def test_bakim_modunda_gorsel_indirilmez_ve_pending_olusmaz(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    run(ayar, "INSERT INTO ayarlar(anahtar,deger) VALUES('bakim_modu','1')")
    start = len(fake.calls)
    feed(bot, message(10, 10, photo=True))
    assert not any(m == "getFile" for m, _ in fake.calls[start:])
    assert any("bakım modunda" in t for t in sends(fake, start))
    assert not list((Path(ayar["GORSEL_KLASOR"]) / "pending").iterdir())
    assert q(ayar, "SELECT COUNT(*) n FROM tg_indirilen")[0]["n"] == 0 and session(ayar, bot) is None


def test_sahipsiz_pending_dosyalari_ve_tg_indirilen_artiklari_temizlenir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))  # açık oturumun pending dosyası
    pending_dir = Path(ayar["GORSEL_KLASOR"]) / "pending"
    aktif = pending_dir / session(ayar, bot)["pending_path"].split("/")[-1]
    assert aktif.is_file()
    old = time.time() - 3 * 86400
    os.utime(aktif, (old, old))
    orphan_old = pending_dir / "123_9_9_eski.png"; orphan_old.write_bytes(png_bytes()); os.utime(orphan_old, (old, old))
    orphan_new = pending_dir / "123_9_9_yeni.png"; orphan_new.write_bytes(png_bytes())
    tmp_old = pending_dir / "123_9_9_x.png.deadbeef.tmp"; tmp_old.write_bytes(b"x"); os.utime(tmp_old, (old, old))
    run(ayar, "INSERT INTO tg_indirilen(bot_id,update_id,chat_id,message_id,pending_path,extension,olusturma) VALUES(?,777,'9',9,'pending/123_9_9_eski.png','png','2020-01-01 00:00:00')", (bot.bot_id,))
    removed, rows = bot._sahipsiz_pending_temizle()
    assert removed == 2 and rows == 1
    assert aktif.is_file() and orphan_new.is_file()
    assert not orphan_old.exists() and not tmp_old.exists()
    assert q(ayar, "SELECT COUNT(*) n FROM tg_indirilen WHERE update_id=777")[0]["n"] == 0
    assert q(ayar, "SELECT COUNT(*) n FROM tg_indirilen WHERE update_id=10")[0]["n"] == 1


# ---- 7. parola metni işlem hatasında saklanmaz ------------------------------------------------
def test_parola_mesaji_islem_hatasinda_veri_alaninda_kalmaz(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.setattr(bot, "_delete_typed_message", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    bot._durable_insert([message(1, 1, "parola", user=6)])
    assert bot.process_pending() == 0
    row = q(ayar, "SELECT durum,deneme,veri,hata FROM tg_gelen WHERE bot_id=? AND update_id=1", (bot.bot_id,))[0]
    assert row["durum"] == "olu" and row["veri"] == "{}" and "yeniden denenmez" in row["hata"]
    assert "parola" not in row["veri"]
    # Yönetici parola isteminde yazılan metin de saklanmaz.
    monkeypatch.undo()
    monkeypatch.setenv("BOT_PASSWORD", "parola"); monkeypatch.setenv("ADMIN_PASSWORD", "yonetici"); monkeypatch.setenv("ADMIN_IDS", "1")
    feed(bot, message(2, 2, "/admin"))
    monkeypatch.setattr(bot, "_delete_typed_message", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bot._durable_insert([message(3, 3, "yonetici-tahmin")])
    bot.process_pending()
    row = q(ayar, "SELECT durum,veri FROM tg_gelen WHERE bot_id=? AND update_id=3", (bot.bot_id,))[0]
    assert (row["durum"], row["veri"]) == ("olu", "{}")
    # Parola olmayan bir metin yeniden deneme için saklanır ('tekrar').
    monkeypatch.undo()
    monkeypatch.setenv("BOT_PASSWORD", "parola"); monkeypatch.setenv("ADMIN_PASSWORD", "yonetici"); monkeypatch.setenv("ADMIN_IDS", "1")
    authorize(ayar, bot, user=7, uid_base=40)
    monkeypatch.setattr(bot, "_start_lead", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    bot._durable_insert([message(50, 50, "LEAD-77", user=7)])
    bot.process_pending()
    row = q(ayar, "SELECT durum,veri FROM tg_gelen WHERE bot_id=? AND update_id=50", (bot.bot_id,))[0]
    assert row["durum"] == "tekrar" and "LEAD-77" in row["veri"]


# ---- 9. MAX_DENEME .env'den -----------------------------------------------------------------
def test_max_deneme_env_okunur_ve_gecersizde_3(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.setenv("MAX_DENEME", "5")
    for i in range(4):
        feed(bot, message(10 + i, 10 + i, f"yanlis{i}", user=2))
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='2'")[0]
    assert (user["deneme"], user["engelli"]) == (4, 0)
    assert any("1 deneme hakkınız kaldı" in t for t in sends(fake))
    feed(bot, message(14, 14, "yanlis4", user=2))
    user = q(ayar, "SELECT deneme,engelli,engel_sebep FROM tg_kullanicilar WHERE id='2'")[0]
    assert (user["deneme"], user["engelli"], user["engel_sebep"]) == (5, 1, "5_yanlis_parola")
    monkeypatch.setenv("MAX_DENEME", "abc"); assert bot_module._max_deneme() == 3
    monkeypatch.setenv("MAX_DENEME", "50"); assert bot_module._max_deneme() == 10
    monkeypatch.setenv("MAX_DENEME", "0"); assert bot_module._max_deneme() == 1
    monkeypatch.delenv("MAX_DENEME"); assert bot_module._max_deneme() == 3


def test_ascii_disi_parola_metni_cokmez(setup):
    ayar, fake, bot = setup
    feed(bot, message(10, 10, "şifre-değil", user=2))
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='2'")[0]
    assert (user["deneme"], user["engelli"]) == (1, 0)
    assert any("Parola yanlış" in t for t in sends(fake))
    assert bot_module._esit("parola", "parola") and not bot_module._esit("parola", "parolа")
    assert bot_yonetim.admin_sifresi_dogru(ayar, "yonetici") and not bot_yonetim.admin_sifresi_dogru(ayar, "yönetici")


# ---- 11. ilk mesajı fotoğraf olan onaysız kullanıcı ---------------------------------------------
def test_fotografla_gelen_onaysiz_kullanici_parola_politikasinda_engellenmez(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.setenv("BOT_YETKISIZ_GORSEL_POLITIKA", "parola")
    start = len(fake.calls)
    feed(bot, message(10, 10, photo=True, user=7))
    user = q(ayar, "SELECT deneme,engelli,onayli FROM tg_kullanicilar WHERE id='7'")[0]
    assert (user["deneme"], user["engelli"], user["onayli"]) == (1, 0, 0)
    assert not any(m == "getFile" for m, _ in fake.calls[start:])
    assert any("önce parolayı yazın" in t for t in sends(fake, start))
    feed(bot, message(11, 11, "parola", user=7))
    assert q(ayar, "SELECT onayli,deneme FROM tg_kullanicilar WHERE id='7'")[0] == {"onayli": 1, "deneme": 0}
    feed(bot, message(12, 12, photo=True, user=7))
    assert session(ayar, bot, user=7)["step"] == "storage"
    # Tekrarlayan yetkisiz görsel (pencere dışı, ≥20 sn arayla) MAX_DENEME'de engellenir;
    # aynı pencerede gelen albüm/fotoğraf seli ise tek deneme sayılır (tests/test_qa_bot.py).
    gercek_monotonic = time.monotonic
    clock = {"t": gercek_monotonic()}
    monkeypatch.setattr(bot_module.time, "monotonic", lambda: clock["t"])
    for i in range(3):
        clock["t"] += 25
        feed(bot, message(20 + i, 20 + i, photo=True, user=8))
    user = q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='8'")[0]
    assert (user["deneme"], user["engelli"]) == (3, 1)
    monkeypatch.setattr(bot_module.time, "monotonic", gercek_monotonic)
    # Varsayılan politika 'parola'dır: ilk görselde engel YOK, deneme sayılır.
    monkeypatch.delenv("BOT_YETKISIZ_GORSEL_POLITIKA")
    feed(bot, message(30, 30, photo=True, user=9))
    assert q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='9'")[0] == {"deneme": 1, "engelli": 0}
    # Eski davranış yalnız açıkça istenirse: BOT_YETKISIZ_GORSEL_POLITIKA=engelle → ilk görselde engel.
    monkeypatch.setenv("BOT_YETKISIZ_GORSEL_POLITIKA", "engelle")
    feed(bot, message(31, 31, photo=True, user=12))
    assert q(ayar, "SELECT engelli FROM tg_kullanicilar WHERE id='12'")[0]["engelli"] == 1


# ---- 12. /engel hedef doğrulaması ve tek yol ---------------------------------------------------
def test_engel_hedefi_dogrulanir_ve_servis_uzerinden_calisir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    admin_login(ayar, fake, bot)
    start = len(fake.calls)
    feed(bot, message(20, 20, "/engel <script>x</script> deneme"))
    assert any("yalnız rakamlardan" in t for t in sends(fake, start))
    assert q(ayar, "SELECT COUNT(*) n FROM tg_kullanicilar WHERE id LIKE '%script%'")[0]["n"] == 0
    start = len(fake.calls)
    feed(bot, message(21, 21, "/engel 1 sebep"))  # 1 hane: geçersiz
    assert any("yalnız rakamlardan" in t for t in sends(fake, start))
    start = len(fake.calls)
    feed(bot, message(22, 22, "/engel 123456789 kötü niyet"))
    assert any("engellendi" in t for t in sends(fake, start))
    user = q(ayar, "SELECT engelli,engel_sebep FROM tg_kullanicilar WHERE id='123456789'")[0]
    assert user["engelli"] == 1 and user["engel_sebep"] == "kötü niyet"
    assert q(ayar, "SELECT COUNT(*) n FROM islem_sonuclari WHERE op='engelle'")[0]["n"] == 1
    assert q(ayar, "SELECT COUNT(*) n FROM denetim WHERE islem='bot_engelle'")[0]["n"] == 1
    # /engel_kaldir tek yoldan (admin_commands → servis): onay korunur.
    start = len(fake.calls)
    feed(bot, message(23, 23, "/engel_kaldir 123456789"))
    assert any("mevcut onay korundu" in t for t in sends(fake, start))
    assert q(ayar, "SELECT engelli FROM tg_kullanicilar WHERE id='123456789'")[0]["engelli"] == 0
    for cmd in ("/engelle abc sebep", "/engel_kaldir abc", "/kullanici_durum abc", "/onayli_sil 12", "/engel_kaldir_sifirla x"):
        start = len(fake.calls)
        feed(bot, message(100 + len(cmd), 100 + len(cmd), cmd))
        assert any("Hata: Telegram ID yalnız rakamlardan" in t for t in sends(fake, start)), cmd
    start = len(fake.calls)
    feed(bot, message(60, 60, "/son_kullanicilar abc"))
    assert any("Kullanım: /son_kullanicilar" in t for t in sends(fake, start))


# ---- 13. _redact kapsamlı maskeleme -------------------------------------------------------------
def test_redact_ciplak_token_bot_biçimi_ve_parolalari_maskeler(env):
    token = "123456789:" + "A" * 35
    assert "A" * 35 not in _redact(f"token {token} bare")
    assert "secret" not in _redact("http://x/bot123:secret/getUpdates") and "bot***" in _redact("http://x/bot123:secret/getUpdates")
    assert "A" * 35 not in _redact(f"https://api.telegram.org/bot{token}/sendMessage") and "A" * 35 not in _redact(f"token={token}")
    assert "parola" not in _redact("girilen=parola") and "yonetici" not in _redact("ADMIN_PASSWORD=yonetici")
    assert "gizli123" not in _redact("password: gizli123")
    assert _redact(None) == "" and "\x00" not in _redact("a\x00b")


# ---- 14. bot_log.txt döndürme ------------------------------------------------------------------
def test_bot_log_dondurme_ve_son_log_okumasi(setup, monkeypatch):
    ayar, _, bot = setup
    monkeypatch.setenv("BOT_LOG_MAX_MB", "1")
    log = Path(ayar["LOG_DOSYA"])
    log.write_text("".join(f"[2026-01-01 00:00:0{i % 10}] eski satır {i} hata\n" for i in range(30000)), encoding="utf-8")
    assert log.stat().st_size > 1024 * 1024
    bot._log(20, "yeni satır")
    assert Path(str(log) + ".1").is_file() and log.stat().st_size < 1024
    lines = bot_yonetim.son_log(ayar, 50)
    assert lines[-1].endswith("yeni satır") and len(lines) == 50 and "eski satır 29999" in lines[-2]
    assert bot_yonetim.son_log(ayar, 5, True) and all("hata" in s or "!" in s or "error" in s.lower() for s in bot_yonetim.son_log(ayar, 5, True)[:-1])
    for _ in range(3):
        log.write_bytes(b"x" * (1024 * 1024 + 1))
        bot._log(20, "tur")
    assert Path(str(log) + ".3").is_file() and not Path(str(log) + ".4").exists()


# ---- 15. uzun çıktıda HTML güvenli bölme ---------------------------------------------------------
def test_html_parcala_etiket_ve_entity_butunlugu():
    lines = [f"<b>Kullanıcı {i}</b> &amp; <code>id{i}</code> · 2026-01-01 &lt;x&gt;" for i in range(250)]
    text = "<b>KULLANICILAR</b>\n" + "\n".join(lines)
    parts = _html_parcala(text)
    assert 1 < len(parts) <= 5
    for part in parts[:-1]:
        assert part.endswith("… (devamı var)")
    for part in parts:
        assert len(part) <= 4096
        assert part.count("<b>") == part.count("</b>") and part.count("<code>") == part.count("</code>")
        assert "&amp" not in part.replace("&amp;", "") and "&lt" not in part.replace("&lt;", "")
    joined = "".join(p.replace("\n… (devamı var)", "") for p in parts)
    assert joined.replace("\n", "") == text.replace("\n", "")
    # Tek uzun satır: etiket ortasından kesilmez, açık etiket kapatılıp yeniden açılır.
    long_line = "<b>" + " ".join(f"kelime{i}" for i in range(1500)) + "</b>"
    parts = _html_parcala(long_line)
    assert len(parts) >= 2 and all(p.count("<b>") == p.count("</b>") for p in parts) and all(len(p) <= 4096 for p in parts)
    assert "".join(p.replace("</b>\n… (devamı var)<b>", "") for p in parts).count("kelime") == 1500
    # Parça üst sınırı: fazlası atılır, son parça kısaltma notu taşır.
    huge = "\n".join("satır %d" % i for i in range(20000))
    parts = _html_parcala(huge)
    assert len(parts) == 5 and parts[-1].endswith("… (çıktı kısaltıldı)")
    assert _html_parcala("kısa") == ["kısa"]


def test_uzun_yonetici_ciktisi_birden_cok_mesaja_bolunur(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    admin_login(ayar, fake, bot)
    conn = db.baglan(ayar["DB"])
    try:
        with db.transaction(conn):
            conn.executemany("INSERT INTO tg_kullanicilar(id,username,first_name,last_seen) VALUES(?,?,?,?)",
                             [(str(100000 + i), "kullanici_adi_%d <&>" % i, "", "2026-01-01 00:00:00") for i in range(150)])
    finally:
        conn.close()
    start = len(fake.calls)
    feed(bot, message(20, 20, "/son_kullanicilar 1000"))
    texts = sends(fake, start)
    assert len(texts) >= 2 and all(len(t) <= 4096 for t in texts)
    assert texts[0].endswith("… (devamı var)") and not texts[-1].endswith("… (devamı var)")
    rows = [line for t in texts for line in t.splitlines() if "·" in line]
    assert len(rows) == 100  # üst sınır 100
    assert sum(1 for r in rows if "&lt;&amp;&gt;" in r) >= 99  # yetkili test kullanıcısı (u1) listede olabilir
    start = len(fake.calls)
    feed(bot, message(21, 21, "/son_hatalar"))
    assert all(len(t) <= 4096 for t in sends(fake, start))


# ---- 10. donusum_isleri.ensure_schema yazmaz, _conn şemayı bir kez kurar -----------------------
def test_ensure_schema_gerekmedikce_yazmaz_ve_conn_bir_kez_kurar(setup, monkeypatch):
    ayar, _, bot = setup
    conn = db.baglan(ayar["DB"])
    try:
        with db.transaction(conn):
            donusum_isleri.enqueue(conn, None, "t", local_path="/tmp/a.png", bot_id="123", chat_id="1", source_message_id=1)
        before = conn.total_changes
        donusum_isleri.ensure_schema(conn)
        assert conn.total_changes == before  # onarım gerekmiyor: UPDATE çalışmadı
        with db.transaction(conn):
            conn.execute("UPDATE donusum_isleri SET source_path='' WHERE job_key='tg:123:1:1'")
        before = conn.total_changes
        donusum_isleri.ensure_schema(conn)
        assert conn.total_changes == before + 1
        assert conn.execute("SELECT source_path FROM donusum_isleri WHERE job_key='tg:123:1:1'").fetchone()[0] == "/tmp/a.png"
    finally:
        conn.close()
    calls = []
    original = donusum_isleri.ensure_schema
    monkeypatch.setattr(donusum_isleri, "ensure_schema", lambda c: calls.append(1) or original(c))
    fresh = KanitBot(ayar, token="123:secret", api=bot.api)
    for _ in range(5):
        fresh._conn().close()
    assert calls == [1]


# ---- 16. run_forever: getMe ağ hatasında bekleyip yeniden dener ----------------------------------
def test_run_forever_getme_ag_hatasinda_bekler_kalici_hatada_cikar(setup, monkeypatch):
    ayar, fake, bot = setup
    sleeps = []
    # Bekleme artık kesilebilir _bekle (threading.Event.wait) üzerinden; time.sleep çağrılmaz.
    monkeypatch.setattr(bot_module.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("time.sleep kullanılmamalı")))
    monkeypatch.setattr(KanitBot, "_bekle", lambda self, s: sleeps.append(s) or False)
    fake.getme_errors = [requests.ConnectionError("http://x/bot123:secret/getMe"), tg_error(502, "Bad Gateway")]
    monkeypatch.setattr(bot, "_paused", lambda: bot.stop() or True)
    assert bot.run_forever() is True
    assert sleeps[:2] == [15, 30] and sum(1 for m, _ in fake.calls if m == "getMe") == 3
    log = Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")
    assert "yeniden denenecek" in log and "secret" not in log
    # Kalıcı hata (geçersiz token): açık Türkçe hata, False → main() çıkış kodu 2.
    bot2 = KanitBot(ayar, token="123:secret", api=bot.api, bot_id="ikinci")
    fake.getme_errors = [tg_error(401, "Unauthorized")]
    assert bot2.run_forever() is False
    assert "çıkış kodu 2" in Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")
    # once=True (test/işletme) ağ hatasında beklemez.
    bot3 = KanitBot(ayar, token="123:secret", api=bot.api, bot_id="ucuncu")
    fake.getme_errors = [requests.ConnectionError("x")]
    before = len(sleeps)
    assert bot3.run_forever(once=True) is False and len(sleeps) == before
    monkeypatch.delenv("BOT_PASSWORD")
    assert bot3.run_forever(once=True) is False
    assert "BOT_PASSWORD ayarlanmamış" in Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")

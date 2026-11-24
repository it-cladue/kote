# -*- coding: utf-8 -*-
"""QA düzeltme turu (v2.3.0 son tur) — Telegram botu bulguları (qa_fix/bot.txt).

Gerçek Telegram API'sine istek atılmaz; tests/test_guvenlik_bot.py'deki sahte oturum
düzeni (FakeTelegram) kullanılır. Kapsam: albüm tek deneme, getFile kalıcı 4xx,
ölü UI mesajında ui_pending_key, parola işlem hatasında bildirim, kesilebilir bekleme,
kısa sır maskeleme, güncelleme artığı 'tekrar' satırları, sohbet bazlı 429.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bot as bot_module  # noqa: E402
from app import guvenli_log  # noqa: E402
from app.bot import KanitBot, TelegramAPI  # noqa: E402
from test_guvenlik_bot import (  # noqa: E402,F401  (env/setup fixture'ları ad alanına alınır)
    FakeTelegram, authorize, callback, env, feed, message, png_bytes, q, run, sends, session, setup, tg_error,
)


class QaTelegram(FakeTelegram):
    """getFile için de sıralı hata enjeksiyonu (400 'file is too big', 502 vb.)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.getfile_errors = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        if method == "getFile" and self.getfile_errors:
            self.calls.append((method, json or {}))
            return self._inject(self.getfile_errors)
        return super().post(url, json=json, timeout=timeout)


def qa_bot(ayar, bot_id=None):
    fake = QaTelegram({"f1": png_bytes()})
    api = TelegramAPI("123:secret", session=fake, api_base="http://fake.telegram")
    return fake, KanitBot(ayar, token="123:secret", api=api, bot_id=bot_id)


def log_text(ayar):
    path = Path(ayar["LOG_DOSYA"])
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# ---- 1. albüm / fotoğraf seli tek deneme ------------------------------------------------------
@pytest.mark.parametrize("adet", [3, 5])
def test_album_gonderen_onaysiz_kullanici_tek_deneme_ve_parola_ile_onaylanir(setup, adet):
    ayar, fake, bot = setup  # varsayılan politika 'parola', MAX_DENEME=3
    start = len(fake.calls)
    for i in range(adet):  # Telegram albümü: aynı media_group_id, ayrı update'ler, aynı saniye
        feed(bot, message(100 + i, 100 + i, photo=True, user=7, extra={"media_group_id": "g1"}))
    user = q(ayar, "SELECT deneme,engelli,onayli FROM tg_kullanicilar WHERE id='7'")[0]
    assert (user["deneme"], user["engelli"], user["onayli"]) == (1, 0, 0)
    assert sum(1 for m, _ in fake.calls[start:] if m == "getFile") == 0  # indirme yine yok
    texts = sends(fake, start)
    assert texts == ["Bu bota görsel göndermek için önce parolayı yazın; görseliniz indirilmedi."]
    assert session(ayar, bot, user=7) is None
    # Ardından doğru parola normal şekilde kabul edilir ve fotoğraf akışı başlar.
    feed(bot, message(200, 200, "parola", user=7))
    assert q(ayar, "SELECT deneme,engelli,onayli FROM tg_kullanicilar WHERE id='7'")[0] == {"deneme": 0, "engelli": 0, "onayli": 1}
    feed(bot, message(201, 201, photo=True, user=7))
    assert session(ayar, bot, user=7)["step"] == "storage"


def test_pencere_disi_fotograf_seli_yine_engellenir(setup, monkeypatch):
    """Sel savunması korunur: 20 sn'den seyrek gelen yetkisiz görseller MAX_DENEME'de engel."""
    ayar, fake, bot = setup
    gercek = time.monotonic
    clock = {"t": gercek()}
    monkeypatch.setattr(bot_module.time, "monotonic", lambda: clock["t"])
    for i in range(2):  # aynı pencerede: tek deneme
        feed(bot, message(10 + i, 10 + i, photo=True, user=8))
    assert q(ayar, "SELECT deneme,engelli FROM tg_kullanicilar WHERE id='8'")[0] == {"deneme": 1, "engelli": 0}
    for i in range(2):
        clock["t"] += 25
        feed(bot, message(20 + i, 20 + i, photo=True, user=8))
    user = q(ayar, "SELECT deneme,engelli,engel_sebep FROM tg_kullanicilar WHERE id='8'")[0]
    assert (user["deneme"], user["engelli"], user["engel_sebep"]) == (3, 1, "yetkisiz_gorsel_gonderimi")
    monkeypatch.setattr(bot_module.time, "monotonic", gercek)
    # Aktarılmış (onayli=1, bu botta girişsiz) kullanıcı albümde sayılmaz, engellenmez.
    run(ayar, "INSERT INTO tg_kullanicilar(id,username,first_name,onayli,engelli,deneme) VALUES('9','eski','E',1,0,0)")
    for i in range(5):
        feed(bot, message(30 + i, 30 + i, photo=True, user=9, extra={"media_group_id": "g3"}))
    assert q(ayar, "SELECT deneme,engelli,onayli FROM tg_kullanicilar WHERE id='9'")[0] == {"deneme": 0, "engelli": 0, "onayli": 1}


# ---- 2. getFile kalıcı 4xx tek deneme, kullanıcıya açıklama --------------------------------------
def test_getfile_kalici_400_tek_deneme_ve_kullanici_mesaji_5xx_gecici_kalir(setup):
    ayar, _, _ = setup
    fake, bot = qa_bot(ayar)
    authorize(ayar, bot)
    start = len(fake.calls)
    fake.getfile_errors = [tg_error(400, "Bad Request: file is too big")] * 5
    feed(bot, message(10, 10, photo=True))
    row = q(ayar, "SELECT durum,deneme,veri FROM tg_gelen WHERE bot_id=? AND update_id=10", (bot.bot_id,))[0]
    assert (row["durum"], row["deneme"], row["veri"]) == ("tamam", 0, "{}")
    assert sum(1 for m, _ in fake.calls[start:] if m == "getFile") == 1 and fake.downloads == 0
    texts = sends(fake, start)
    assert len(texts) == 1 and texts[0].startswith("Görsel okunamadı: Bad Request: file is too big") and "yeniden gönderin" in texts[0]
    assert session(ayar, bot) is None
    assert bot.process_pending() == 0  # tekrar kuyruğu yok
    assert q(ayar, "SELECT COUNT(*) n FROM tg_gelen WHERE bot_id=? AND durum IN ('tekrar','olu')", (bot.bot_id,))[0]["n"] == 0
    # Telegram'ın 5xx (ve JSON'suz) yanıtı geçici kalır: 'tekrar', kullanıcıya mesaj yok.
    start = len(fake.calls)
    fake.getfile_errors = [tg_error(502, "Bad Gateway")]
    bot._durable_insert([message(11, 11, photo=True)])
    assert bot.process_pending() == 0
    row = q(ayar, "SELECT durum,deneme FROM tg_gelen WHERE bot_id=? AND update_id=11", (bot.bot_id,))[0]
    assert (row["durum"], row["deneme"]) == ("tekrar", 1) and sends(fake, start) == []
    # Ağ hatası da geçici kalır.
    start = len(fake.calls)
    fake.getfile_errors = [requests.ConnectionError("http://x/bot123:secret/getFile")]
    bot._durable_insert([message(12, 12, photo=True)])
    assert bot.process_pending() == 0
    row = q(ayar, "SELECT durum,hata FROM tg_gelen WHERE bot_id=? AND update_id=12", (bot.bot_id,))[0]
    assert row["durum"] == "tekrar" and "secret" not in (row["hata"] or "") and sends(fake, start) == []


# ---- 3. ölü korumalı UI mesajında ui_pending_key temizlenir ------------------------------------
def test_ui_mesaji_kalici_hatayla_olunce_sonraki_dugme_ekrani_yeniden_gonderir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    ui = s["ui_message_id"]
    assert s["step"] == "storage" and "ui_pending_key" not in s
    fake.send_errors = [tg_error(403, "Forbidden: bot was blocked by the user")]
    feed(bot, callback(11, ui, "storage:local"))
    row = q(ayar, "SELECT durum,deneme,action_key FROM tg_giden WHERE bot_id=? AND source_update_id=11 AND tur='send'", (bot.bot_id,))[0]
    assert (row["durum"], row["deneme"]) == ("olu", 1)
    s = session(ayar, bot)
    assert s["step"] == "project" and "ui_pending_key" not in s and s["ui_message_id"] == ui  # takılı anahtar yok
    # Kullanıcı botu yeniden açıp eski ekrandaki düğmeye basar: 'hazırlanıyor' yerine ekran yeniden gelir.
    start = len(fake.calls)
    feed(bot, callback(12, ui, "storage:local"))
    texts = sends(fake, start)
    assert not any("hazırlanıyor" in t for t in texts)
    assert len(texts) == 1 and "projeyi" in texts[0]
    s = session(ayar, bot)
    assert s["step"] == "project" and "ui_pending_key" not in s and s["ui_message_id"] != ui
    # Eski UI'nin silinmesi (replace) bir sonraki outbox turunda gider; kuyrukta başka iş kalmaz.
    assert bot.process_outbox() == 1
    assert q(ayar, "SELECT COUNT(*) n FROM tg_giden WHERE bot_id=? AND durum NOT IN ('tamam','olu')", (bot.bot_id,))[0]["n"] == 0
    # Akış normal sürer.
    feed(bot, callback(13, s["ui_message_id"], "p:PP"))
    assert session(ayar, bot)["step"] == "category"


# ---- 4. parola mesajı işlem hatasında kullanıcı bilgilendirilir ---------------------------------
def test_parola_mesaji_islem_hatasinda_kullaniciya_yeniden_yazin_bildirimi(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.setenv("BOT_PASSWORD", "gizli-sifre-77")
    original = bot._delete_typed_message
    state = {"fail": 1}

    def flaky(*args, **kwargs):
        if state["fail"]:
            state["fail"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return original(*args, **kwargs)

    monkeypatch.setattr(bot, "_delete_typed_message", flaky)
    bot._durable_insert([message(1, 1, "gizli-sifre-77", user=6)])
    start = len(fake.calls)
    assert bot.process_pending() == 0
    row = q(ayar, "SELECT durum,veri,hata FROM tg_gelen WHERE bot_id=? AND update_id=1", (bot.bot_id,))[0]
    assert (row["durum"], row["veri"]) == ("olu", "{}") and "yeniden denenmez" in row["hata"]
    giden = q(ayar, "SELECT action_key,chat_id,user_id,metin,durum,guard_revision FROM tg_giden WHERE bot_id=? AND source_update_id=1", (bot.bot_id,))
    assert giden == [{"action_key": "u1:parola:send", "chat_id": "6", "user_id": "6",
                      "metin": "Mesajınız geçici bir hata nedeniyle işlenemedi; lütfen parolayı yeniden yazın.",
                      "durum": "tamam", "guard_revision": None}]
    assert sends(fake, start) == ["Mesajınız geçici bir hata nedeniyle işlenemedi; lütfen parolayı yeniden yazın."]
    dump = json.dumps(q(ayar, "SELECT * FROM tg_giden") + q(ayar, "SELECT * FROM tg_gelen"), ensure_ascii=False)
    assert "gizli-sifre-77" not in dump  # parola metni hiçbir yerde saklanmaz
    assert q(ayar, "SELECT onayli FROM tg_kullanicilar WHERE id='6'") == []  # transaction geri alındı: onay yok
    # Aynı update bir daha işlenmez (idempotent anahtar); kullanıcı yeniden yazınca onaylanır.
    assert bot.process_pending() == 0
    feed(bot, message(2, 2, "gizli-sifre-77", user=6))
    assert q(ayar, "SELECT onayli,deneme FROM tg_kullanicilar WHERE id='6'")[0] == {"onayli": 1, "deneme": 0}
    assert q(ayar, "SELECT COUNT(*) n FROM tg_giden WHERE bot_id=? AND action_key LIKE '%:parola:send'", (bot.bot_id,))[0]["n"] == 1


# ---- 5. kesilebilir bekleme: stop() uykuyu keser -------------------------------------------------
def _bekle_kosul(kosul, saniye=5.0):
    deadline = time.monotonic() + saniye
    while time.monotonic() < deadline:
        if kosul():
            return True
        time.sleep(0.02)
    return False


def test_stop_baslangic_geri_cekilmesini_ve_duraklama_uykusunu_keser(setup):
    ayar, fake, bot = setup
    fake.getme_errors = [requests.ConnectionError("http://x/bot123:secret/getMe")] * 100
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("r", bot.run_forever()), daemon=True)
    worker.start()
    assert _bekle_kosul(lambda: "yeniden denenecek" in log_text(ayar))  # 15 sn'lik beklemeye girdi
    t0 = time.monotonic()
    bot.stop()
    worker.join(3)
    assert not worker.is_alive() and time.monotonic() - t0 < 1.0
    assert result["r"] is True and sum(1 for m, _ in fake.calls if m == "getMe") == 1
    assert "secret" not in log_text(ayar)
    # Site yönetimi duraklattığında (bot_durdur=1) ana döngü 1 sn uyur; stop() onu da keser.
    run(ayar, "INSERT INTO ayarlar(anahtar,deger) VALUES('bot_durdur','1') ON CONFLICT(anahtar) DO UPDATE SET deger='1'")
    fake2, bot2 = qa_bot(ayar, bot_id="ikinci")
    before = len(fake2.calls)
    worker2 = threading.Thread(target=lambda: result.setdefault("r2", bot2.run_forever()), daemon=True)
    worker2.start()
    assert _bekle_kosul(lambda: any(m == "getWebhookInfo" for m, _ in fake2.calls[before:]))
    time.sleep(0.1)
    t0 = time.monotonic()
    bot2.stop()
    worker2.join(3)
    assert not worker2.is_alive() and time.monotonic() - t0 < 1.0 and result["r2"] is True
    assert not any(m == "getUpdates" for m, _ in fake2.calls)  # duraklatılmış bot poll yapmaz
    # stop() sonrası _bekle hemen döner; stop öncesi gerçek bekleme süresi uygulanır.
    bot3 = KanitBot(ayar, token="123:secret", api=bot.api, bot_id="ucuncu")
    t0 = time.monotonic(); assert bot3._bekle(0.2) is False and 0.15 <= time.monotonic() - t0 < 1.0
    bot3.stop(); t0 = time.monotonic(); assert bot3._bekle(30) is True and time.monotonic() - t0 < 0.5


# ---- 6. kısa sırlar maskelenmez (kimlikler bozulmaz), kısa parola uyarısı ------------------------
def test_kisa_ortam_sirlari_kimlikleri_bozmaz_uzunlar_bitisik_bile_maskelenir(monkeypatch):
    monkeypatch.setenv("BOT_PASSWORD", "34")
    monkeypatch.setenv("ADMIN_PASSWORD", "1234")
    monkeypatch.setenv("SESSION_SECRET", "abcde")  # 5 karakter: eşik altı
    monkeypatch.setenv("GYAZO_TOKEN", "gyzTok3nXYZ")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456789:" + "A" * 35)
    satir = "Güncelleme 123456 olu: kullanıcı 345678 deneme 1234 kodu 34 abcdef"
    assert guvenli_log.text(satir) == satir
    assert "[GİZLİ]" not in bot_module._redact(satir)
    # ≥ 6 karakterlik sır bitişik (URL/sorgu içinde) geçse de maskelenir; kelime sınırı aranmaz.
    assert guvenli_log.text("https://x/upload?access=gyzTok3nXYZ&y=1") == "https://x/upload?access=[GİZLİ]&y=1"
    assert "A" * 35 not in guvenli_log.text("https://api.telegram.org/bot123456789:" + "A" * 35 + "/getMe")
    monkeypatch.setenv("BOT_PASSWORD", "parola")
    assert guvenli_log.text("girilen=parola!") == "girilen=[GİZLİ]!"
    # Denetim/log satırındaki Telegram kimliği (db.denetim_yaz de text() kullanır) bütün kalır.
    monkeypatch.setenv("BOT_PASSWORD", "2026")
    assert guvenli_log.text("hesap 120265634") == "hesap 120265634"


def test_run_forever_kisa_parolada_uyari_loglar_degeri_yazmaz(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.setenv("BOT_PASSWORD", "ab1")  # 3 karakter: maskeleme eşiği altında; değer loga girmemeli
    assert bot.run_forever(once=True) is True
    log = log_text(ayar)
    assert "BOT_PASSWORD 8 karakterden kısa" in log and "en az 8 karakter" in log
    assert "ab1" not in log and "ADMIN_PASSWORD 8 karakterden" not in log  # 'yonetici' 8 karakter: uyarı yok
    monkeypatch.setenv("BOT_PASSWORD", "uzun-parola-123")
    monkeypatch.setenv("ADMIN_PASSWORD", "kisa")
    bot2 = KanitBot(ayar, token="123:secret", api=bot.api, bot_id="ikinci")
    assert bot2.run_forever(once=True) is True
    log = log_text(ayar)
    assert "ADMIN_PASSWORD 8 karakterden kısa" in log and "kisa" not in log.replace("karakterden kısa", "")
    assert log.count("BOT_PASSWORD 8 karakterden kısa") == 1


# ---- 7. güncelleme artığı 'tekrar' satırları ---------------------------------------------------
def test_ust_siniri_asmis_tekrar_satirlari_secilmez_ve_baslangicta_olu_yapilir(setup, monkeypatch):
    ayar, fake, bot = setup
    bot._conn().close()  # bot şeması (tg_giden) kurulur
    now = bot_module._simdi()
    for key, deneme in (("eski:1", 5), ("eski:2", 9), ("yeni:1", 2)):
        run(ayar, "INSERT INTO tg_giden(bot_id,action_key,tur,chat_id,metin,durum,deneme,hata,olusturma,guncelleme) "
                  "VALUES(?,?,'send','1',?,'tekrar',?,'HTTP 403','2020-01-01 00:00:00','2020-01-01 00:00:00')",
            (bot.bot_id, key, f"mesaj {key}", deneme))
    run(ayar, "INSERT INTO tg_giden(bot_id,action_key,tur,chat_id,metin,durum,deneme,olusturma,guncelleme) "
              "VALUES(?,'bekle:1','send','1','bekleyen','bekliyor',0,?,?)", (bot.bot_id, now, now))
    start = len(fake.calls)
    assert bot.process_outbox() == 2  # yalnız deneme<5 olan tekrar + bekliyor gönderilir
    assert sorted(p["text"] for m, p in fake.calls[start:] if m == "sendMessage") == ["bekleyen", "mesaj yeni:1"]
    rows = {r["action_key"]: (r["durum"], r["deneme"]) for r in q(ayar, "SELECT action_key,durum,deneme FROM tg_giden WHERE bot_id=?", (bot.bot_id,))}
    assert rows == {"eski:1": ("tekrar", 5), "eski:2": ("tekrar", 9), "yeni:1": ("tamam", 2), "bekle:1": ("tamam", 0)}
    assert not bot._has_outbox_retry(10 ** 6)  # eski satırlar long-poll'u da kısaltmaz
    # Başlangıç (run_forever) tek seferlik temizlik: 'olu' + açıklayıcı hata eki, mesaj gönderilmez.
    start = len(fake.calls)
    assert bot.run_forever(once=True) is True
    assert not any(m == "sendMessage" for m, _ in fake.calls[start:])
    eski = q(ayar, "SELECT action_key,durum,hata FROM tg_giden WHERE bot_id=? AND action_key LIKE 'eski:%' ORDER BY action_key", (bot.bot_id,))
    assert [(r["durum"], r["hata"]) for r in eski] == [("olu", "HTTP 403 | üst sınır aşıldı (güncelleme)")] * 2
    assert "Güncelleme artığı 2 teslimat tekrarı 'olu' yapıldı" in log_text(ayar)
    assert bot._eski_tekrarlari_kapat() == 0  # ikinci çağrı: iş yok
    # Üst sınır .env ile düşürülmüşse de tutarlı: BOT_OUTBOX_MAX_DENEME=2 → deneme 2 olan satır da artık seçilmez.
    run(ayar, "INSERT INTO tg_giden(bot_id,action_key,tur,chat_id,metin,durum,deneme,olusturma,guncelleme) "
              "VALUES(?,'sinir:1','send','1','x','tekrar',2,'2020-01-01 00:00:00','2020-01-01 00:00:00')", (bot.bot_id,))
    monkeypatch.setenv("BOT_OUTBOX_MAX_DENEME", "2")
    assert bot.process_outbox() == 0 and bot._eski_tekrarlari_kapat() == 1


# ---- 8. 429 sohbet bazlı: tek sohbetin seli diğerlerini durdurmaz -------------------------------
def test_429_tek_sohbeti_duraklatir_diger_sohbet_teslim_edilir_iki_sohbette_genel(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)                       # chat A = 1
    authorize(ayar, bot, user=2, uid_base=5)   # chat B = 2
    bot._durable_insert([message(10, 10, "/start", user=1), message(11, 11, "/start", user=2), message(12, 12, "/start", user=1)])
    start = len(fake.calls)
    fake.send_errors = [tg_error(429, "Too Many Requests: retry after 5", retry_after=5)]
    assert bot.process_pending() == 3
    sent = [p for m, p in fake.calls[start:] if m == "sendMessage"]
    assert [p["chat_id"] for p in sent] == ["1", "2"]  # A 429 aldı, B aynı turda teslim edildi
    rows = q(ayar, "SELECT source_update_id,durum,deneme FROM tg_giden WHERE bot_id=? AND source_update_id IN (10,11,12) ORDER BY id", (bot.bot_id,))
    assert [tuple(r.values()) for r in rows] == [(10, "tekrar", 0), (11, "tamam", 0), (12, "bekliyor", 0)]
    assert bot._outbox_duraklama() == 0 and 0 < bot._outbox_duraklama("1") <= 5 and bot._outbox_duraklama("2") == 0
    log = log_text(ayar)
    assert "1 sohbetine gönderimler 5 sn duraklatıldı" in log and "tüm gönderimler" not in log
    # A duraklatılmışken B'nin yeni mesajı hemen akar; A'nın bekleyen satırı dokunulmaz.
    start = len(fake.calls)
    feed(bot, message(13, 13, "/start", user=2))
    assert [p["chat_id"] for m, p in fake.calls[start:] if m == "sendMessage"] == ["2"]
    assert q(ayar, "SELECT durum FROM tg_giden WHERE bot_id=? AND source_update_id=12", (bot.bot_id,))[0]["durum"] == "bekliyor"
    bot.poll_once(25)
    assert fake.calls[-1][1]["timeout"] <= 6  # A'nın tekrarı zamanı gelince hemen alınır
    # Aynı 60 sn içinde ikinci bir sohbet de 429 alırsa gerçek genel sınır: tümü duraklar, tavan 60 sn.
    fake.send_errors = [tg_error(429, "Too Many Requests: retry after 300", retry_after=300)]
    start = len(fake.calls)
    feed(bot, message(14, 14, "/start", user=2))
    assert sum(1 for m, _ in fake.calls[start:] if m == "sendMessage") == 1
    assert 0 < bot._outbox_duraklama() <= 60 and bot.process_outbox() == 0
    assert "birden çok sohbette: tüm gönderimler 60 sn duraklatıldı" in log_text(ayar)
    bot.poll_once(25)
    assert fake.calls[-1][1]["timeout"] <= 25
    # Süreler dolunca kuyruk eksiksiz akar: 10 (tekrar), 12 (bekliyor), 14 (tekrar).
    bot._outbox_duraklat_bitis = 0.0
    bot._chat_duraklat.clear()
    run(ayar, "UPDATE tg_giden SET guncelleme='2000-01-01 00:00:00' WHERE bot_id=? AND durum='tekrar'", (bot.bot_id,))
    start = len(fake.calls)
    assert bot.process_outbox() == 3
    assert sorted(p["chat_id"] for m, p in fake.calls[start:] if m == "sendMessage") == ["1", "1", "2"]
    assert q(ayar, "SELECT COUNT(*) n FROM tg_giden WHERE bot_id=? AND durum!='tamam'", (bot.bot_id,))[0]["n"] == 0
    # Aynı sohbetin ikinci 429'u genel duraklama tetiklemez (farklı sohbet sayısı < 2).
    bot._hiz_siniri_zamani.clear()
    assert bot._hiz_siniri_kaydet("1", 5) == 0 and bot._hiz_siniri_kaydet("1", 5) == 0 and bot._outbox_duraklama() == 0
    assert bot._hiz_siniri_kaydet("2", 200) == 60 and 59 < bot._outbox_duraklama() <= 60

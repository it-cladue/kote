# -*- coding: utf-8 -*-
"""Dış ağa çıkmadan Telegram bot iş kuralları regresyon testleri."""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db
from app.bot import KanitBot, TelegramAPI, TelegramHatasi


class FakeResponse:
    def __init__(self, payload=None, content=b"", status=200):
        self.payload = payload or {"ok": True, "result": True}
        self.content = content
        self.status_code = status
        self.headers = {"Content-Length": str(len(content))} if content else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code} /bot123:secret/")

    def json(self):
        return self.payload

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


class FakeTelegram:
    def __init__(self, files=None, fail_download=False, fail_send=0, slow_aux=False):
        self.files = files or {}
        self.fail_download = fail_download
        self.fail_send = fail_send
        self.slow_aux = slow_aux
        self.calls = []
        self.next_message = 100
        self.updates = []

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, json or {}))
        if self.slow_aux and method in {"answerCallbackQuery", "deleteMessage"}:
            # Yardımcı çağrı yavaş olsa da UI çağrısının bunun önüne geçmediğini test eder.
            time.sleep(0.01)
        if method == "getUpdates":
            return FakeResponse({"ok": True, "result": self.updates})
        if method == "getFile":
            fid = (json or {}).get("file_id")
            if fid not in self.files:
                return FakeResponse({"ok": False, "description": "file missing"})
            data = self.files[fid]
            return FakeResponse({"ok": True, "result": {"file_path": f"files/{fid}", "file_size": len(data)}})
        if method == "sendMessage":
            if self.fail_send:
                self.fail_send -= 1
                import requests
                raise requests.ConnectionError("http://example.invalid/bot123:secret/send")
            self.next_message += 1
            return FakeResponse({"ok": True, "result": {"message_id": self.next_message}})
        if method == "getMe":
            return FakeResponse({"ok": True, "result": {"id": 123, "username": "fake"}})
        return FakeResponse({"ok": True, "result": True})

    def get(self, url, stream=True, timeout=None):
        if self.fail_download:
            import requests
            raise requests.ConnectionError("http://example.invalid/file/bot123:secret/x")
        fid = url.rsplit("/", 1)[-1]
        return FakeResponse(content=self.files[fid])


def png_bytes():
    bio = io.BytesIO()
    Image.new("RGB", (3, 3), "red").save(bio, format="PNG")
    return bio.getvalue()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BOT_PASSWORD", "parola")
    monkeypatch.setenv("ADMIN_PASSWORD", "yonetici")
    monkeypatch.setenv("ADMIN_IDS", "1")


@pytest.fixture
def setup(tmp_path, env):
    ayar = {
        "DB": str(tmp_path / "panel.db"), "BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(tmp_path / "medya"),
        "LOG_DOSYA": str(tmp_path / "bot.log"), "MAX_GORSEL_BYTES": 10 * 1024 * 1024,
        "PROJELER": ["PP", "PA", "OF", "HI", "VI", "GA"],
    }
    fake = FakeTelegram({"f1": png_bytes()})
    api = TelegramAPI("123:secret", session=fake, api_base="http://fake.telegram")
    return ayar, fake, KanitBot(ayar, token="123:secret", api=api)


def message(update_id, message_id, text=None, photo=False, document=False, user=1):
    m = {"message_id": message_id, "chat": {"id": user, "type": "private"}, "from": {"id": user, "username": f"u{user}", "first_name": "U"}}
    if text is not None:
        m["text"] = text
    if photo:
        m["photo"] = [{"file_id": "f1", "file_unique_id": "uniq1", "file_size": 100}]
    if document:
        m["document"] = {"file_id": "f1", "file_unique_id": "uniq1", "file_size": 100, "mime_type": "image/png", "file_name": "iddia.exe"}
    return {"update_id": update_id, "message": m}


def callback(update_id, ui_message_id, data, user=1):
    return {"update_id": update_id, "callback_query": {
        "id": f"cb{update_id}", "from": {"id": user, "username": f"u{user}"}, "data": data,
        "message": {"message_id": ui_message_id, "chat": {"id": user, "type": "private"}},
    }}


def session(ayar, bot, user=1):
    conn = db.baglan(ayar["DB"])
    try:
        r = conn.execute("SELECT veri FROM tg_oturumlar WHERE bot_id=? AND user_id=?", (bot.bot_id, str(user))).fetchone()
        return __import__("json").loads(r["veri"]) if r else None
    finally:
        conn.close()


def feed(bot, update):
    bot._durable_insert([update])
    assert bot.process_pending() == 1


def authorize(ayar, bot):
    feed(bot, message(1, 1, "/start"))
    feed(bot, message(2, 2, "parola"))
    conn = db.baglan(ayar["DB"])
    try:
        return conn.execute("SELECT * FROM tg_kullanicilar WHERE id='1'").fetchone()
    finally:
        conn.close()


def choose_local(ayar, bot, update_id=11, user=1):
    s = session(ayar, bot, user)
    assert s["step"] == "storage"
    feed(bot, callback(update_id, s["ui_message_id"], "storage:local", user=user))
    s = session(ayar, bot, user)
    assert s["step"] == "project" and s["save_mode"] == "local"
    return s


def do_image_flow(ayar, bot, code, mode):
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11)
    feed(bot, callback(12, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot)
    feed(bot, callback(13, s["ui_message_id"], f"k:{code}"))
    feed(bot, message(14, 14, "P-55"))
    if mode == "ark_ana":
        feed(bot, message(15, 15, "ARK-ÜYE"))
        feed(bot, message(16, 16, "ANA-ÜYE"))
    elif mode == "ana_only":
        feed(bot, message(15, 15, "ANA-ÜYE"))
    else:
        feed(bot, message(15, 15, "ÜYE-1"))
        if mode == "sessiz_tip":
            s = session(ayar, bot)
            feed(bot, callback(16, s["ui_message_id"], "t:sessiz"))
    s = session(ayar, bot)
    assert s["step"] == "summary"
    feed(bot, callback(20, s["ui_message_id"], "confirm"))


@pytest.mark.parametrize("code,mode", [("hgst", "tek_uye"), ("ark", "ark_ana"), ("lpst", "ana_only"), ("dds", "sessiz_tip")])
def test_dort_kategori_modu_gercek_gorsel_ve_metadata(setup, code, mode):
    ayar, _, bot = setup
    do_image_flow(ayar, bot, code, mode)
    conn = db.baglan(ayar["DB"])
    try:
        r = conn.execute("SELECT * FROM kayitlar").fetchone()
        assert r["giris_tipi"] == "resim"
        assert r["kategori_code"] == code
        assert r["kategori_mode"] == mode
        assert r["telegram_bot_id"] == "123"
        assert r["file_id"] == "f1" and r["message_id"] == 10 and r["chat_id"] == "1"
        assert r["gorsel_dosya"] and not r["gorsel_dosya"].startswith("pending/")
        assert (Path(ayar["GORSEL_KLASOR"]) / r["gorsel_dosya"]).is_file()
        if mode == "ark_ana":
            assert r["uye_id"] == "ARK-ÜYE" and r["ana_uye_id"] == "ANA-ÜYE"
        elif mode == "ana_only":
            assert r["uye_id"] is None and r["ana_uye_id"] == "ANA-ÜYE"
        elif mode == "sessiz_tip":
            assert r["tip"] == "sessiz"
    finally:
        conn.close()


def test_yazili_lead_ve_tekrarlanan_callback_tek_kayit(setup):
    ayar, _, bot = setup
    conn = db.baglan(ayar["DB"])
    try:
        conn.executemany("INSERT INTO panel_kullanicilari(kullanici_adi,ad,sifre_hash,yetki,aktif) VALUES(?,?,?,?,1)", [
            ("super", "Super", "x", "admin"), ("kontrol", "Kontrol", "x", "GA:oku,kt"), ("salt_okur", "Salt Okur", "x", "GA:oku"),
        ])
    finally:
        conn.close()
    authorize(ayar, bot)
    feed(bot, message(10, 10, "LEAD-007"))
    s = session(ayar, bot)
    assert s["step"] == "lead_confirm"
    feed(bot, callback(11, s["ui_message_id"], "lead:ok"))
    s = session(ayar, bot); feed(bot, callback(12, s["ui_message_id"], "p:GA"))
    s = session(ayar, bot); feed(bot, callback(13, s["ui_message_id"], "k:lpst"))
    feed(bot, message(14, 14, "P")); feed(bot, message(15, 15, "ANA"))
    s = session(ayar, bot); assert s["step"] == "summary"
    confirm = callback(16, s["ui_message_id"], "confirm")
    feed(bot, confirm)
    # Aynı callback yeni update kimliği ile gelse bile stale UI/session koruması ikinci kayıt üretmez.
    confirm["update_id"] = 17
    feed(bot, confirm)
    conn = db.baglan(ayar["DB"])
    try:
        rows = conn.execute("SELECT * FROM kayitlar").fetchall()
        assert len(rows) == 1
        assert rows[0]["giris_tipi"] == "yazili" and rows[0]["lead_id"] == "LEAD-007"
        assert rows[0]["ana_uye_id"] == "ANA" and rows[0]["gorsel_dosya"] is None
        recipients = {r[0] for r in conn.execute("SELECT kullanici_adi FROM bildirimler WHERE kayit_id=?", (rows[0]["id"],))}
        assert recipients == {"super", "kontrol"}
    finally:
        conn.close()


def test_parola_yok_bakim_callback_ve_yetkisiz_gorsel(setup, monkeypatch):
    ayar, _, bot = setup
    monkeypatch.delenv("BOT_PASSWORD")
    feed(bot, message(1, 1, photo=True))
    conn = db.baglan(ayar["DB"])
    try:
        r = conn.execute("SELECT * FROM tg_kullanicilar WHERE id='1'").fetchone()
        assert r["onayli"] == 0 and r["engelli"] == 0
    finally:
        conn.close()
    monkeypatch.setenv("BOT_PASSWORD", "parola")
    # update_id kalıcı inbox anahtarıdır; önceki parola-yok olayıyla aynı ID
    # yeniden gönderilirse Telegram idempotency gereği tekrar işlenmez.
    feed(bot, message(2, 2, "/start"))
    feed(bot, message(3, 3, "parola"))
    feed(bot, message(10, 10, document=True))  # image document gerçek PNG doğrulamasından geçer
    s = choose_local(ayar, bot, 11)
    conn = db.baglan(ayar["DB"])
    try:
        db.ayar_yaz(conn, "bakim_modu", "1")
    finally:
        conn.close()
    feed(bot, callback(12, s["ui_message_id"], "p:PP"))
    assert session(ayar, bot)["step"] == "project"  # bakım callback'i ilerletmedi
    conn = db.baglan(ayar["DB"])
    try:
        db.ayar_yaz(conn, "bakim_modu", "0")
    finally:
        conn.close()
    # Onaysız başka bir kullanıcının görseli 3 deneme politikasından bağımsız doğrudan engeldir.
    feed(bot, message(13, 13, photo=True, user=2))
    conn = db.baglan(ayar["DB"])
    try:
        assert conn.execute("SELECT engelli FROM tg_kullanicilar WHERE id='2'").fetchone()[0] == 1
    finally:
        conn.close()


def test_yeniden_baslatma_oturumu_ve_indirme_hatasi_backoff(tmp_path, env):
    ayar = {"DB": str(tmp_path / "p.db"), "BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(tmp_path / "m"), "LOG_DOSYA": str(tmp_path / "b.log"), "MAX_GORSEL_BYTES": 10 * 1024 * 1024, "PROJELER": ["PP", "PA", "OF", "HI", "VI", "GA"]}
    fake = FakeTelegram({"f1": png_bytes()})
    bot = KanitBot(ayar, token="123:secret", api=TelegramAPI("123:secret", session=fake, api_base="http://fake"))
    authorize(ayar, bot)
    feed(bot, message(10, 10, "DEVAM-LEAD"))
    # Yeni süreç aynı DB'deki onay ekranını sürdürebilir.
    bot2 = KanitBot(ayar, token="123:secret", api=TelegramAPI("123:secret", session=fake, api_base="http://fake"))
    s = session(ayar, bot2)
    feed(bot2, callback(11, s["ui_message_id"], "lead:change"))
    assert session(ayar, bot2)["step"] == "lead_write"

    failing = FakeTelegram({"f1": png_bytes()}, fail_download=True)
    bot3 = KanitBot(ayar, token="123:secret", api=TelegramAPI("123:secret", session=failing, api_base="http://fake"))
    bot3._durable_insert([message(50, 50, photo=True)])
    assert bot3.process_pending() == 0
    conn = db.baglan(ayar["DB"])
    try:
        r = conn.execute("SELECT durum,deneme,hata FROM tg_gelen WHERE bot_id=? AND update_id=50", (bot3.bot_id,)).fetchone()
        assert r["durum"] == "tekrar" and r["deneme"] == 1
        assert "secret" not in (r["hata"] or "")
    finally:
        conn.close()


def test_personel_geri_dugmesi_kategoriye_doner_ve_dogru_callback_uretir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11); feed(bot, callback(12, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot); feed(bot, callback(13, s["ui_message_id"], "k:hgst"))
    s = session(ayar, bot)
    assert s["step"] == "personel"
    # Kategori seçiminden sonra gösterilen keyboard artık handler'ın kabul ettiği
    # back:category değerini taşımalıdır (eski back:project burada yanıtsızdı).
    # Her adım altta yeni mesajla teslim edilir; eski UI başarılı teslimden sonra
    # silinir. Görünüm/toggle satırı artık yoktur.
    send_payload = [payload for method, payload in fake.calls if method == "sendMessage"][-1]
    assert send_payload["reply_markup"]["inline_keyboard"] == [[{"text": "← Geri", "callback_data": "back:category"}]]
    feed(bot, callback(14, s["ui_message_id"], "back:category"))
    assert session(ayar, bot)["step"] == "category"


def test_final_dosya_adi_namespace_ve_uzanti_soneki(setup):
    _, _, bot = setup
    path, name = bot._final_path({
        "user_id": "987654321", "username": "uzun.kullanici", "chat_id": "987654321",
        "project": "PP", "category_code": "hgst", "personel": "PERSONEL-123",
        "uye_id": "UYE-456", "ana_uye_id": "ANA-789", "source_message_id": "4567",
        "file_unique_id": "telegram-file-unique", "extension": "PNG",
    })
    assert path.parent == Path(bot.ayar["GORSEL_KLASOR"]).resolve()
    assert name.endswith(".png") and len(name) <= 240
    # Bot, kullanıcı ID+adı, proje/kategori/personel ve kaynak kimlikleri görünen
    # adın içinde; tam girdinin hash'i ise kısalmada çarpışmayı önler.
    for piece in ("123", "987654321", "uzun.kullanici", "PP", "hgst", "PERSONEL-123", "UYE-456", "ANA-789", "4567", "telegram-file-unique"):
        assert piece in name


def test_ui_send_hatasi_outbox_ile_yeniden_dener(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    fake.fail_send = 1
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    assert s["step"] == "storage" and "ui_message_id" not in s and s.get("ui_pending_key")
    conn = db.baglan(ayar["DB"])
    try:
        out = conn.execute("SELECT durum,deneme FROM tg_giden WHERE bot_id=? AND action_key=?", (bot.bot_id, s["ui_pending_key"])).fetchone()
        assert out["durum"] == "tekrar" and out["deneme"] == 1
        conn.execute("UPDATE tg_giden SET guncelleme='2000-01-01 00:00:00' WHERE bot_id=? AND action_key=?", (bot.bot_id, s["ui_pending_key"]))
    finally:
        conn.close()
    assert bot.process_outbox() == 1
    assert session(ayar, bot)["ui_message_id"]


def test_commit_sonrasi_crash_pending_den_finale_kurtarilir(setup, monkeypatch):
    ayar, _, bot = setup
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11); feed(bot, callback(12, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot); feed(bot, callback(13, s["ui_message_id"], "k:hgst"))
    feed(bot, message(14, 14, "P-55")); feed(bot, message(15, 15, "UYE-1"))
    s = session(ayar, bot); assert s["step"] == "summary"
    # DB commit ile pending temizliği arasındaki process kill'i taklit et.
    monkeypatch.setattr(bot, "_cleanup_committed_media", lambda pending: None)
    feed(bot, callback(20, s["ui_message_id"], "confirm"))
    conn = db.baglan(ayar["DB"])
    try:
        record = conn.execute("SELECT gorsel_dosya FROM kayitlar").fetchone()
        cached = conn.execute("SELECT pending_path FROM tg_indirilen WHERE bot_id=?", (bot.bot_id,)).fetchone()
        inbox = conn.execute("SELECT durum,veri FROM tg_gelen WHERE bot_id=? AND update_id=20", (bot.bot_id,)).fetchone()
        assert inbox["durum"] == "tamam"  # kayıt/state/outbox ile aynı transaction ack'i
        assert inbox["veri"] == "{}"  # onaylanan update'in ham metni/parolası kalmaz
    finally:
        conn.close()
    final = Path(ayar["GORSEL_KLASOR"]) / record["gorsel_dosya"]
    pending = Path(ayar["GORSEL_KLASOR"]) / cached["pending_path"]
    assert final.is_file() and pending.is_file()
    final.unlink()  # yalnız pending kalmış crash sonrası kayıp finali de onarılabilir.
    restarted = KanitBot(ayar, token="123:secret", api=bot.api)
    assert restarted._recover_pending_media() == 1
    assert final.is_file() and not pending.exists()


def test_gorsel_piksel_siniri_ag_olmadan_reddedilir(setup):
    ayar, _, bot = setup
    ayar["MAX_IMAGE_PIXELS"] = 1
    bot.ayar["MAX_IMAGE_PIXELS"] = 1
    with pytest.raises(TelegramHatasi, match="piksel sınırını aşıyor"):
        bot._download_image({"file_id": "f1", "file_unique_id": "uniq1", "file_size": 100}, "1", 1)


def test_eski_buton_guncel_ekran_yeniler_ve_start_akisi_korur(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(30, 30, photo=True))
    old = session(ayar, bot)['ui_message_id']
    feed(bot, message(31, 31, photo=True))
    current = session(ayar, bot)['ui_message_id']
    assert old != current
    # Eski saklama ekranı yeni oturumu ilerletmez; doğru ekran tekrar görünür.
    feed(bot, callback(32, old, 'storage:local'))
    s = session(ayar, bot)
    assert s['step'] == 'storage' and s['ui_message_id'] != current
    assert any('eski seçim' in payload.get('text','') for method,payload in fake.calls)
    feed(bot, callback(33, s['ui_message_id'], 'storage:local'))
    assert session(ayar, bot)['step'] == 'project'
    s = session(ayar, bot)
    feed(bot, callback(34, s['ui_message_id'], 'p:OF'))
    assert session(ayar, bot)['step'] == 'category'
    feed(bot, message(35, 35, '/start'))
    s = session(ayar, bot)
    assert s['step'] == 'category' and s['project'] == 'OF'
    feed(bot, callback(36, s['ui_message_id'], 'p:PA'))
    assert session(ayar, bot)['step'] == 'category'
    assert any('mevcut adım' in payload.get('text','') for method,payload in fake.calls)


def test_aktarilmis_onayli_kullanici_yeni_botta_parola_girer_ve_fotograf_engellenmez(setup):
    ayar, fake, bot = setup
    conn = db.baglan(ayar["DB"])
    try:
        conn.execute("INSERT INTO tg_kullanicilar(id,username,onayli,engelli,last_seen) VALUES('1','u1',1,0,?)", (db.simdi(),))
    finally:
        conn.close()
    feed(bot, message(1, 1, photo=True))
    conn = db.baglan(ayar["DB"])
    try:
        profile = conn.execute("SELECT onayli,engelli FROM tg_kullanicilar WHERE id='1'").fetchone()
        assert tuple(profile) == (1, 0)
        assert not conn.execute("SELECT 1 FROM tg_girisler WHERE bot_id=? AND user_id='1'", (bot.bot_id,)).fetchone()
        assert not conn.execute("SELECT 1 FROM tg_indirilen WHERE bot_id=?", (bot.bot_id,)).fetchone()
    finally:
        conn.close()
    assert any('önce parolayı' in payload.get('text', '') for method, payload in fake.calls)
    feed(bot, message(2, 2, 'parola'))
    conn = db.baglan(ayar["DB"])
    try:
        assert conn.execute("SELECT 1 FROM tg_girisler WHERE bot_id=? AND user_id='1'", (bot.bot_id,)).fetchone()
    finally:
        conn.close()


def test_gorsel_saklama_menusu_ve_yerel_varsayim_gyazo_cagirmadan_ilerler(setup, monkeypatch):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    monkeypatch.setattr(bot, '_gyazo_convert', lambda path: pytest.fail('Yerel seçim Gyazo çağırmamalı'))
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    assert s['step'] == 'storage' and s['save_mode'] == 'local'
    storage = [payload for method, payload in fake.calls if method == 'sendMessage'][-1]
    choices = storage['reply_markup']['inline_keyboard']
    assert any(b['callback_data'] == 'storage:local' for row in choices for b in row)
    assert any(b['callback_data'] == 'storage:gyazo' for row in choices for b in row)
    choose_local(ayar, bot, 11)


def test_gyazo_secimi_ag_beklemeden_ilerler_ve_onay_sonrasi_tek_sonuc_verir(setup, monkeypatch):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    import app.gyazo as gyazo
    calls = []
    monkeypatch.setattr(gyazo, 'upload', lambda path: calls.append(('upload', path)) or {'ok': True, 'image_id': 'a' * 32, 'image_url': 'https://i.gyazo.com/' + 'a' * 32 + '.png', 'http_status': 200})
    monkeypatch.setattr(gyazo, 'verify', lambda image_id, image_url: calls.append(('verify', image_id)) or {'ok': True, 'url': 'https://gyazo.com/' + 'a' * 32, 'http_status': 200})
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    feed(bot, callback(11, s['ui_message_id'], 'storage:gyazo'))
    s = session(ayar, bot)
    assert s['step'] == 'project' and s['save_mode'] == 'gyazo' and s['conversion_job_key'] == 'tg:123:1:10'
    assert not calls  # callback transaction'ında upload/verify ağı yok
    feed(bot, callback(12, s['ui_message_id'], 'p:PP'))
    s = session(ayar, bot); feed(bot, callback(13, s['ui_message_id'], 'k:hgst'))
    feed(bot, message(14, 14, 'P')); feed(bot, message(15, 15, 'U'))
    s = session(ayar, bot); feed(bot, callback(16, s['ui_message_id'], 'confirm'))
    conn = db.baglan(ayar['DB'])
    try:
        r = conn.execute('SELECT link,link_turu,gorsel_dosya FROM kayitlar').fetchone()
        assert r['link'] is None and r['link_turu'] == 'yerel' and r['gorsel_dosya']
    finally:
        conn.close()
    assert bot.process_conversion_jobs(limit=4) >= 2
    bot.process_outbox()
    conn = db.baglan(ayar['DB'])
    try:
        r = conn.execute('SELECT link,link_turu FROM kayitlar').fetchone()
        assert r['link'] == 'https://gyazo.com/' + 'a' * 32 and r['link_turu'] == 'gyazo'
        assert conn.execute("SELECT COUNT(*) FROM donusum_isleri WHERE job_key='tg:123:1:10'").fetchone()[0] == 1
    finally:
        conn.close()
    assert [kind for kind, _ in calls] == ['upload', 'verify']


def test_tema_kaldirildi_ve_native_stiller_sabittir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(3, 3, '/tema'))
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11)
    keyboard = [payload for method, payload in fake.calls if method == 'sendMessage'][-1]['reply_markup']['inline_keyboard']
    pp = next(b for row in keyboard for b in row if b['callback_data'] == 'p:PP')
    assert pp['text'] == 'PP' and pp['style'] == 'primary'
    assert not any(b['callback_data'] == 'theme:toggle' for row in keyboard for b in row)
    assert any('Görünüm seçeneği kaldırıldı' in payload.get('text', '') for method, payload in fake.calls)
    # Yeni kullanıcıda da kişisel tema kaydı yazılmaz.
    feed(bot, message(20, 20, '/start', user=2)); feed(bot, message(21, 21, 'parola', user=2))
    feed(bot, message(22, 22, photo=True, user=2))
    s2 = choose_local(ayar, bot, 23, user=2)
    colored = [payload for method, payload in fake.calls if method == 'sendMessage'][-1]['reply_markup']['inline_keyboard']
    pa = next(b for row in colored for b in row if b['callback_data'] == 'p:PA')
    assert pa['text'] == 'PA' and pa['style'] == 'primary'
    conn = db.baglan(ayar['DB'])
    try:
        assert conn.execute("SELECT 1 FROM tg_tema WHERE user_id='1'").fetchone() is None
        assert conn.execute("SELECT 1 FROM tg_tema WHERE user_id='2'").fetchone() is None
    finally:
        conn.close()


def test_callback_cevabi_ui_tesliminden_once_gonderilir(setup):
    ayar, fake, bot = setup
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    start = len(fake.calls)
    fake.slow_aux = True
    feed(bot, callback(11, s['ui_message_id'], 'storage:local'))
    methods = [method for method, _ in fake.calls[start:]]
    assert methods.index('answerCallbackQuery') < methods.index('sendMessage')


def test_custom_snapshot_sorulari_sirali_ve_geri_sonrasi_temizdir(setup):
    ayar, _, bot = setup
    from app import katalog

    conn = db.baglan(ayar['DB'])
    try:
        katalog.ensure_schema(conn)
        katalog.save_category(
            conn, 'ozel', 'Özel Akış', mode='custom', projects=['PP'], actor='test',
            questions=[
                {'key': 'personel', 'label': 'Personel kodu', 'preset': 'personel', 'type': 'text', 'required': True, 'options': []},
                {'key': 'sonuc', 'label': 'Sonuç', 'preset': '', 'type': 'select', 'required': True, 'options': ['başarılı', 'bekliyor']},
            ],
        )
    finally:
        conn.close()
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11)
    feed(bot, callback(12, s['ui_message_id'], 'p:PP'))
    s = session(ayar, bot)
    feed(bot, callback(13, s['ui_message_id'], 'k:ozel'))
    s = session(ayar, bot)
    assert s['step'] == 'question' and s['question_index'] == 0
    feed(bot, message(14, 14, 'P-OLD'))
    s = session(ayar, bot)
    assert s['question_index'] == 1 and s['answers']['personel'] == 'P-OLD'
    # Geri, mevcut ve sonraki yanıtları temizler; yeni girilen değer snapshot'a gider.
    feed(bot, callback(15, s['ui_message_id'], 'back:question'))
    s = session(ayar, bot)
    assert s['question_index'] == 0 and s['answers'] == {} and 'personel' not in s
    feed(bot, message(16, 16, 'P-NEW'))
    s = session(ayar, bot)
    feed(bot, callback(17, s['ui_message_id'], 'q:1:0'))
    s = session(ayar, bot)
    assert s['step'] == 'summary' and s['answers'] == {'personel': 'P-NEW', 'sonuc': 'başarılı'}
    feed(bot, callback(18, s['ui_message_id'], 'confirm'))
    conn = db.baglan(ayar['DB'])
    try:
        row = conn.execute('SELECT personel,kategori_soru_surumu,soru_anlik_json,cevaplar_json FROM kayitlar').fetchone()
        assert row['personel'] == 'P-NEW' and row['kategori_soru_surumu']
        assert __import__('json').loads(row['cevaplar_json']) == {'personel': 'P-NEW', 'sonuc': 'başarılı'}
        assert __import__('json').loads(row['soru_anlik_json'])['questions'][1]['key'] == 'sonuc'
    finally:
        conn.close()


def test_katalogdaki_yeni_proje_menude_callbackte_ve_kayitta_kullanilir(setup):
    """Legacy PROJELER listesinde olmayan aktif katalog projesi botta görünür."""
    ayar, fake, bot = setup
    from app import katalog

    conn = db.baglan(ayar['DB'])
    try:
        katalog.save_project(conn, 'YENI', 'Yeni Proje', '#13579B', actor='test')
        katalog.save_category(conn, 'yeni_kat', 'Yeni Kategori', mode='tek_uye', projects=['YENI'], actor='test')
    finally:
        conn.close()

    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = choose_local(ayar, bot, 11)
    project_keyboard = [payload for method, payload in fake.calls if method == 'sendMessage'][-1]['reply_markup']['inline_keyboard']
    assert any(button['callback_data'] == 'p:YENI' for row in project_keyboard for button in row)
    feed(bot, callback(12, s['ui_message_id'], 'p:YENI'))
    s = session(ayar, bot)
    assert s['step'] == 'category' and s['project'] == 'YENI'
    category_keyboard = [payload for method, payload in fake.calls if method == 'sendMessage'][-1]['reply_markup']['inline_keyboard']
    assert any(button['callback_data'] == 'k:yeni_kat' for row in category_keyboard for button in row)
    feed(bot, callback(13, s['ui_message_id'], 'k:yeni_kat'))
    feed(bot, message(14, 14, 'PERSONEL-YENI'))
    feed(bot, message(15, 15, 'UYE-YENI'))
    s = session(ayar, bot)
    assert s['step'] == 'summary'
    feed(bot, callback(16, s['ui_message_id'], 'confirm'))
    conn = db.baglan(ayar['DB'])
    try:
        row = conn.execute("SELECT proje,kategori_code,personel,uye_id FROM kayitlar").fetchone()
        assert tuple(row) == ('YENI', 'yeni_kat', 'PERSONEL-YENI', 'UYE-YENI')
    finally:
        conn.close()


def test_gyazo_gorsel_degistiginde_baglanti_uygulandi_diye_bildirilmez(setup, monkeypatch):
    """Sıradaki görsel değişirse sahte doğrulama başarılı olsa da yerel kayıt korunur."""
    ayar, fake, bot = setup
    import app.gyazo as gyazo

    uploaded = 'b' * 32
    monkeypatch.setattr(
        gyazo, 'upload',
        lambda path: {'ok': True, 'image_id': uploaded, 'image_url': f'https://i.gyazo.com/{uploaded}.png', 'http_status': 200},
    )
    monkeypatch.setattr(
        gyazo, 'verify',
        lambda image_id, image_url: {'ok': True, 'url': f'https://gyazo.com/{uploaded}', 'http_status': 200},
    )
    authorize(ayar, bot)
    feed(bot, message(10, 10, photo=True))
    s = session(ayar, bot)
    feed(bot, callback(11, s['ui_message_id'], 'storage:gyazo'))
    s = session(ayar, bot)
    feed(bot, callback(12, s['ui_message_id'], 'p:PP'))
    s = session(ayar, bot)
    feed(bot, callback(13, s['ui_message_id'], 'k:hgst'))
    feed(bot, message(14, 14, 'P'))
    feed(bot, message(15, 15, 'U'))
    s = session(ayar, bot)
    feed(bot, callback(16, s['ui_message_id'], 'confirm'))

    # İlk bounded tur yalnız upload fazını bitirir. Kayıt görüntüsü bundan sonra
    # değişirse doğrulanan eski URL'nin yeni kanıta yazılması engellenmelidir.
    assert bot.process_conversion_jobs(limit=1) == 1
    conn = db.baglan(ayar['DB'])
    try:
        conn.execute("UPDATE kayitlar SET gorsel_dosya='sonra.png' WHERE telegram_bot_id=?", (bot.bot_id,))
    finally:
        conn.close()
    assert bot.process_conversion_jobs(limit=1) == 1
    assert bot.process_outbox() >= 1

    conn = db.baglan(ayar['DB'])
    try:
        record = conn.execute("SELECT link,link_turu,gorsel_dosya FROM kayitlar").fetchone()
        job = conn.execute("SELECT durum,record_applied,uygulama_durumu FROM donusum_isleri").fetchone()
        audit = conn.execute("SELECT islem,yeni FROM denetim WHERE islem='gyazo_link_yerel_korundu'").fetchone()
        assert tuple(record) == (None, 'yerel', 'sonra.png')
        assert tuple(job) == ('tamam', 0, 'uygulanmadi')
        assert audit['islem'] == 'gyazo_link_yerel_korundu' and 'gyazo.com' not in (audit['yeni'] or '')
    finally:
        conn.close()
    texts = [payload.get('text', '') for method, payload in fake.calls if method == 'sendMessage']
    assert any('Görsel değişti; bağlantı kayda eklenmedi, yerel kanıt korunuyor' in text for text in texts)
    assert not any('Gyazo bağlantısı kayda eklendi' in text for text in texts)

# -*- coding: utf-8 -*-
"""2.4.0 (Takım C) — Telegram botu: panelden ekleyene bildirim kuyruğu (bot_giden), onay/silme geri bildirimi,
"Ekleyene sor (Telegram)" ve Reply / /yanit ile yanıt, albüm ve yarım akış güvenliği, daha az dokunuş
(saklama sorusu yok, ⚡ Son kullanılan, hemen kayıt numarası, /son + Düzelt, /yardim, setMyCommands)
ve mükerrer kanıt uyarısı (bot + panel). Telegram tamamen sahte istemciyle taklit edilir; dış ağ yok."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app import bot_bildirim, db, kullanicilar
from app.bot import KOMUT_MENUSU, KanitBot, TelegramAPI
from tests.test_bot import FakeResponse, FakeTelegram, callback, feed, message, session
from tests.test_web import web, login, csrf  # noqa: F401
from tests.test_panel_kanit_ekle_236 import XHR, gonder

SIFRE = 'Test-Password-123!'


def png(color="red"):
    bio = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(bio, format="PNG")
    return bio.getvalue()


class Fake(FakeTelegram):
    """FakeTelegram + kalıcı hata (403) ve setMyCommands kaydı."""

    def __init__(self, *a, permanent_fail=0, **k):
        super().__init__(*a, **k)
        self.permanent_fail = permanent_fail

    def post(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        if method == "sendMessage" and self.permanent_fail:
            self.permanent_fail -= 1
            self.calls.append((method, json or {}))
            return FakeResponse({"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"})
        return super().post(url, json=json, timeout=timeout)

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("BOT_PASSWORD", "parola")
    monkeypatch.setenv("ADMIN_PASSWORD", "yonetici")
    monkeypatch.setenv("ADMIN_IDS", "1")
    for key in ("BOT_GYAZO_SOR", "BOT_ONAY_BILDIRIMI", "BOT_SILME_BILDIRIMI", "BOT_SORU_BILDIRIMI", "BOT_BILDIRIM_MAX_DENEME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BOT_ONAY_TOPLAMA_SN", "0")


def yap_bot(ayar, fake=None):
    fake = fake or Fake({"f1": png("red"), "f2": png("blue"), "f3": png("green"), "f4": png("white")})
    api = TelegramAPI("123:secret", session=fake, api_base="http://fake.telegram")
    return fake, KanitBot(ayar, token="123:secret", api=api)


@pytest.fixture
def setup(tmp_path, env):
    ayar = {"DB": str(tmp_path / "panel.db"), "BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(tmp_path / "medya"),
            "LOG_DOSYA": str(tmp_path / "bot.log"), "MAX_GORSEL_BYTES": 10 * 1024 * 1024,
            "PROJELER": ["PP", "PA", "OF", "HI", "VI", "GA"]}
    fake, bot = yap_bot(ayar)
    return ayar, fake, bot


def foto(update_id, message_id, fid="f1", uniq="u1", group=None, user=1):
    upd = message(update_id, message_id, user=user)
    upd["message"]["photo"] = [{"file_id": fid, "file_unique_id": uniq, "file_size": 100}]
    if group:
        upd["message"]["media_group_id"] = group
    return upd


def q(ayar, sql, *params):
    conn = db.baglan(ayar["DB"])
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def giris(bot, user=1, base=1):
    feed(bot, message(base, base, "/start", user=user))
    feed(bot, message(base + 1, base + 1, "parola", user=user))


def kanit(ayar, bot, uid0, fid="f1", uniq="u1", uye="ÜYE-1", project="p:PP", kisayol=False):
    """Fotoğraf → proje → HGST → personel → üye → (uyarı yoksa) SON KONTROL → Onayla. Dönüş: son oturum."""
    feed(bot, foto(uid0, uid0, fid, uniq))
    s = session(ayar, bot)
    assert s["step"] == "project"
    if kisayol:
        feed(bot, callback(uid0 + 1, s["ui_message_id"], "son:kullan"))
    else:
        feed(bot, callback(uid0 + 1, s["ui_message_id"], project))
        s = session(ayar, bot)
        feed(bot, callback(uid0 + 2, s["ui_message_id"], "k:hgst"))
    feed(bot, message(uid0 + 3, uid0 + 3, "P-1"))
    feed(bot, message(uid0 + 4, uid0 + 4, uye))
    s = session(ayar, bot)
    if s["step"] == "summary":
        feed(bot, callback(uid0 + 5, s["ui_message_id"], "confirm"))
    return s


# ------------------------------------------------------------------ C5: daha az dokunuş
def test_saklama_sorusu_yok_kayit_numarasi_hemen_ve_son_kullanilan_kisayolu(setup):
    ayar, fake, bot = setup
    giris(bot)
    feed(bot, foto(10, 10))
    s = session(ayar, bot)
    assert s["step"] == "project" and s["save_mode"] == "local"
    kb = [p for m, p in fake.calls if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"]
    datas = [b["callback_data"] for row in kb for b in row]
    assert not any(d.startswith("storage:") for d in datas) and "son:kullan" not in datas  # önceki kayıt yok
    feed(bot, callback(11, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot); feed(bot, callback(12, s["ui_message_id"], "k:hgst"))
    feed(bot, message(13, 13, "P-1")); feed(bot, message(14, 14, "ÜYE-1"))
    s = session(ayar, bot); assert s["step"] == "summary"
    feed(bot, callback(15, s["ui_message_id"], "confirm"))
    kid = q(ayar, "SELECT id FROM kayitlar")[0]["id"]
    assert any(f"Kayıt: <code>{kid}</code>" in t and "panele işlendi" in t for t in fake.texts())
    # İkinci görselde "⚡ Son kullanılan: PP / HGST" ilk satırda; tek dokunuşla personel adımına geçer.
    feed(bot, foto(20, 20, "f2", "u2"))
    s = session(ayar, bot)
    kb = [p for m, p in fake.calls if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["callback_data"] == "son:kullan" and kb[0][0]["text"] == "⚡ Son kullanılan: PP / HGST"
    feed(bot, callback(21, s["ui_message_id"], "son:kullan"))
    s = session(ayar, bot)
    assert (s["step"], s["project"], s["category_code"]) == ("personel", "PP", "hgst")


def test_gyazo_tercihi_ve_kayit_numarasi_gyazoda_da_hemen(setup, monkeypatch):
    ayar, fake, bot = setup
    monkeypatch.delenv("GYAZO_TOKEN", raising=False)
    giris(bot)
    feed(bot, message(4, 4, "/gyazo"))
    assert "yapılandırılmamış" in fake.texts()[-1]
    monkeypatch.setenv("GYAZO_TOKEN", "x")
    feed(bot, message(5, 5, "/gyazo"))
    assert any("Gyazo <b>açık</b>" in t for t in fake.texts())
    feed(bot, foto(10, 10))
    s = session(ayar, bot)
    assert s["save_mode"] == "gyazo" and s["conversion_job_key"] and s["step"] == "project"
    feed(bot, callback(11, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot); feed(bot, callback(12, s["ui_message_id"], "k:hgst"))
    feed(bot, message(13, 13, "P")); feed(bot, message(14, 14, "U"))
    s = session(ayar, bot); feed(bot, callback(15, s["ui_message_id"], "confirm"))
    kid = q(ayar, "SELECT id FROM kayitlar")[0]["id"]
    final = [t for t in fake.texts() if f"Kayıt: <code>{kid}</code>" in t]
    assert final and "arka planda" in final[-1] and "panele işlendi" not in final[-1]
    feed(bot, message(16, 16, "/gyazo"))
    assert any("Gyazo <b>kapalı</b>" in t for t in fake.texts())


def test_yardim_ve_setmycommands(setup):
    ayar, fake, bot = setup
    giris(bot)
    feed(bot, message(5, 5, "/yardim"))
    assert any("KISA REHBER" in t and "/son" in t and "/yanit" in t for t in fake.texts())
    assert bot.run_forever(poll_timeout=1, once=True)
    assert bot.komutlari_kaydet()  # tekrar çağrı zararsız
    calls = [p for m, p in fake.calls if m == "setMyCommands"]
    assert len(calls) == 2 and calls[0]["commands"] == KOMUT_MENUSU
    assert {c["command"] for c in KOMUT_MENUSU} >= {"start", "son", "yardim", "iptal", "yanit"}


def test_son_listesi_durumlar_ve_duzelt_akisi(setup):
    ayar, fake, bot = setup
    giris(bot)
    kanit(ayar, bot, 10, "f1", "u1", "ÜYE-1")
    kanit(ayar, bot, 20, "f2", "u2", "ÜYE-2", kisayol=True)
    kanit(ayar, bot, 30, "f3", "u3", "ÜYE-3", kisayol=True)
    ids = [r["id"] for r in q(ayar, "SELECT id FROM kayitlar ORDER BY id")]
    assert len(ids) == 3
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        conn.execute("UPDATE kayitlar SET kt=1 WHERE id=?", (ids[0],))
        conn.execute("UPDATE kayitlar SET silindi=1 WHERE id=?", (ids[1],))
    conn.close()
    feed(bot, message(40, 40, "/kayitlarim"))
    listing = [p for m, p in fake.calls if m == "sendMessage"][-1]
    assert f"#{ids[0]}" in listing["text"] and "✅ onaylı" in listing["text"] and "❌ silindi" in listing["text"] and "⏳ bekliyor" in listing["text"]
    buttons = [b["callback_data"] for row in listing["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == [f"duzelt:{ids[2]}"]  # yalnız onay bekleyen kayıt düzeltilebilir
    # Onaylı kaydın düzeltmesi reddedilir.
    feed(bot, callback(41, 999, f"duzelt:{ids[0]}"))
    assert any("düzeltilemez" in t for t in fake.texts())
    feed(bot, callback(42, 999, f"duzelt:{ids[2]}"))
    s = session(ayar, bot)
    assert s["step"] == "question" and s["duzelt_kayit"] == ids[2]
    assert "Şu anki değer: <code>P-1</code>" in fake.texts()[-1]
    feed(bot, message(43, 43, "P-YENI"))                        # personel değişir
    s = session(ayar, bot)
    feed(bot, callback(44, s["ui_message_id"], "duzelt:ayni"))  # üye ID aynı kalır
    s = session(ayar, bot)
    assert s["step"] == "duzelt_ozet" and "(değişti)" in fake.texts()[-1]
    feed(bot, callback(45, s["ui_message_id"], "duzelt:kaydet"))
    r = q(ayar, "SELECT personel,uye_id,surum FROM kayitlar WHERE id=?", ids[2])[0]
    assert (r["personel"], r["uye_id"], r["surum"]) == ("P-YENI", "ÜYE-3", 2)
    audit = q(ayar, "SELECT eski,yeni FROM denetim WHERE islem='tg_duzeltme'")
    assert len(audit) == 1 and "P-YENI" in audit[0]["yeni"] and "P-1" in audit[0]["eski"]
    assert session(ayar, bot) is None and any(f"#{ids[2]} güncellendi" in t for t in fake.texts())


# ------------------------------------------------------------------ C4: albüm ve yarım akış
def test_album_iki_gorsel_tek_kayit_ucuncusu_alinmaz(setup):
    ayar, fake, bot = setup
    giris(bot)
    feed(bot, foto(10, 10, "f1", "u1", group="alb1"))
    feed(bot, foto(11, 11, "f2", "u2", group="alb1"))
    s = session(ayar, bot)
    assert s["pending2_path"] and s["source_message_id"] == 10 and s["step"] == "project"
    feed(bot, foto(12, 12, "f3", "u3", group="alb1"))
    assert any("En çok 2 görsel; fazlası alınmadı" in t for t in fake.texts())
    s = session(ayar, bot)
    assert s["source_message_id"] == 10 and s["file2_unique_id"] == "u2"
    feed(bot, callback(13, s["ui_message_id"], "p:PP"))
    s = session(ayar, bot); feed(bot, callback(14, s["ui_message_id"], "k:hgst"))
    feed(bot, message(15, 15, "P")); feed(bot, message(16, 16, "U"))
    s = session(ayar, bot)
    assert "2 görsel" in fake.texts()[-1]
    feed(bot, callback(17, s["ui_message_id"], "confirm"))
    rows = q(ayar, "SELECT gorsel_dosya,gorsel2_dosya FROM kayitlar")
    assert len(rows) == 1 and rows[0]["gorsel_dosya"] and rows[0]["gorsel2_dosya"]
    medya = Path(ayar["GORSEL_KLASOR"])
    assert (medya / rows[0]["gorsel_dosya"]).is_file() and (medya / rows[0]["gorsel2_dosya"]).is_file()
    assert (medya / rows[0]["gorsel2_dosya"]).read_bytes() == png("blue")
    assert not any((medya / "pending").iterdir())  # 2. görselin pending kopyası da temizlendi


def test_dugme_adiminda_yazilan_metin_oturumu_silmez(setup):
    ayar, fake, bot = setup
    giris(bot)
    feed(bot, foto(10, 10))
    before = session(ayar, bot)
    feed(bot, message(11, 11, "LEAD-77"))
    s = session(ayar, bot)
    assert s["step"] == "yarim" and s["pending_path"] == before["pending_path"] and s["source_type"] == "resim"
    last = [p for m, p in fake.calls if m == "sendMessage"][-1]
    assert "Yarım kalan kanıt işlemi var." in last["text"]
    assert [b["callback_data"] for row in last["reply_markup"]["inline_keyboard"] for b in row] == ["yarim:devam", "yarim:yeni"]
    feed(bot, callback(12, s["ui_message_id"], "yarim:devam"))
    s = session(ayar, bot)
    assert s["step"] == "project" and s["pending_path"] == before["pending_path"]
    feed(bot, message(13, 13, "LEAD-88"))
    s = session(ayar, bot)
    feed(bot, callback(14, s["ui_message_id"], "yarim:yeni"))
    s = session(ayar, bot)
    assert (s["step"], s["source_type"], s["lead_id"]) == ("lead_confirm", "yazili", "LEAD-88")
    assert not (Path(ayar["GORSEL_KLASOR"]) / before["pending_path"]).exists()


# ------------------------------------------------------------------ C6: mükerrer uyarısı (bot)
def test_bot_mukerrer_uye_id_ve_ayni_gorsel_uyarisi(setup):
    ayar, fake, bot = setup
    giris(bot)
    kanit(ayar, bot, 10, "f1", "u1", "ÜYE-9")
    first = q(ayar, "SELECT id FROM kayitlar")[0]["id"]
    s = kanit(ayar, bot, 20, "f2", "u2", "ÜYE-9", kisayol=True)
    assert s["step"] == "dup_warn"
    warn = [p for m, p in fake.calls if m == "sendMessage"][-1]
    today = datetime.now().strftime("%d.%m")
    assert f"⚠️ Bu üye ID {today}'de #{first} olarak kaydedilmiş. Yine de kaydet?" in warn["text"]
    feed(bot, callback(26, s["ui_message_id"], "dup:evet"))
    s = session(ayar, bot); assert s["step"] == "summary"
    feed(bot, callback(27, s["ui_message_id"], "confirm"))
    assert len(q(ayar, "SELECT id FROM kayitlar")) == 2
    # Aynı görsel (file_unique_id) farklı üye ID ile: uyarı; Vazgeç düzeltme menüsüne döner.
    s = kanit(ayar, bot, 30, "f1", "u1", "ÜYE-YENI", kisayol=True)
    assert s["step"] == "dup_warn" and "Bu görsel" in fake.texts()[-1]
    feed(bot, callback(36, s["ui_message_id"], "dup:vazgec"))
    assert session(ayar, bot)["step"] == "cancel_menu"
    assert len(q(ayar, "SELECT id FROM kayitlar")) == 2


# ------------------------------------------------------------------ C1: kuyruk, yeniden deneme, kalıcı hata
def test_bot_giden_yaz_bosalt_tekrar_ve_olu(setup, monkeypatch):
    ayar, fake, bot = setup
    giris(bot)
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        a = bot_bildirim.kuyruga(conn, "1", "deneme 1", "test")
    conn.close()
    fake.fail_send = 1
    assert bot.process_bildirimler() == 0
    row = q(ayar, "SELECT * FROM bot_giden WHERE id=?", a)[0]
    assert (row["durum"], row["deneme"], row["gonderildi"]) == ("bekliyor", 1, 0) and row["sonraki_deneme"] > db.simdi()
    assert bot.process_bildirimler() == 0  # bekleme süresi dolmadan yeniden denenmez
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        conn.execute("UPDATE bot_giden SET sonraki_deneme='2000-01-01 00:00:00' WHERE id=?", (a,))
    conn.close()
    assert bot.process_bildirimler() == 1
    row = q(ayar, "SELECT * FROM bot_giden WHERE id=?", a)[0]
    assert (row["durum"], row["gonderildi"]) == ("tamam", 1) and row["message_id"] == fake.next_message
    # Üst sınır: BOT_BILDIRIM_MAX_DENEME=2, iki geçici hata → 'olu' ve bot günlüğünde kayıt.
    monkeypatch.setenv("BOT_BILDIRIM_MAX_DENEME", "2")
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        b = bot_bildirim.kuyruga(conn, "1", "deneme 2", "test")
    conn.close()
    fake.fail_send = 2
    bot.process_bildirimler()
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        conn.execute("UPDATE bot_giden SET sonraki_deneme='2000-01-01 00:00:00' WHERE id=?", (b,))
    conn.close()
    bot.process_bildirimler()
    assert q(ayar, "SELECT durum,deneme FROM bot_giden WHERE id=?", b)[0] == {"durum": "olu", "deneme": 2}
    # Kalıcı hata (403 bot engellendi) ilk denemede 'olu'.
    fake.permanent_fail = 1
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        c = bot_bildirim.kuyruga(conn, "1", "deneme 3", "test")
    conn.close()
    bot.process_bildirimler()
    assert q(ayar, "SELECT durum,deneme FROM bot_giden WHERE id=?", c)[0] == {"durum": "olu", "deneme": 1}
    log = Path(ayar["LOG_DOSYA"]).read_text(encoding="utf-8")
    assert "Panel bildirimi (test" in log and "vazgeçildi" in log and "secret" not in log
    # Başka bir botun satırı bu bot tarafından gönderilmez.
    conn = db.baglan(ayar["DB"])
    with db.transaction(conn):
        d = bot_bildirim.kuyruga(conn, "1", "başka bot", "test", bot_id="999")
    conn.close()
    bot.process_bildirimler()
    assert q(ayar, "SELECT durum FROM bot_giden WHERE id=?", d)[0]["durum"] == "bekliyor"


# ------------------------------------------------------------------ panel tarafı (web + bot aynı DB)
def tg_kayit(a, chat="1", project="OF", gun_once=0, uye="00099", anahtar=None, kaynak="telegram"):
    tarih = (datetime.now() - timedelta(days=gun_once)).strftime("%Y-%m-%d %H:%M:%S")
    c = db.baglan(a["DB"])
    with db.transaction(c):
        kid = c.execute(
            "INSERT INTO kayitlar(anahtar,proje,personel,uye_id,kategori,kategori_code,kaynak,giris_tipi,ekleyen_id,ekleyen_ad,"
            "chat_id,telegram_bot_id,tarih,guncelleme) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (anahtar or f"tg:123:{chat}:{datetime.now().timestamp()}", project, "P1", uye, "HGST", "hgst", kaynak, "yazili",
             chat if kaynak == "telegram" else "panel:testadmin", "Ali", chat if kaynak == "telegram" else None,
             "123" if kaynak == "telegram" else None, tarih, tarih)).lastrowid
    c.close()
    return kid


def web_bot(a):
    ayar = {"DB": a["DB"], "BOT_KLASOR": a["BOT_KLASOR"], "GORSEL_KLASOR": a["GORSEL_KLASOR"],
            "LOG_DOSYA": a["LOG_DOSYA"], "MAX_GORSEL_BYTES": 10 * 1024 * 1024, "PROJELER": ["OF", "PA"]}
    return yap_bot(ayar)


def test_onay_toplu_ve_tekil_ekleyen_basina_tek_mesaj_kaynak_ve_yas_haric(web, env):
    c, a = web
    login(c)
    a1, a2 = tg_kayit(a, "1"), tg_kayit(a, "1", project="PA")
    b1 = tg_kayit(a, "2")
    eski = tg_kayit(a, "1", gun_once=45)
    panel_kaydi = tg_kayit(a, kaynak="panel", anahtar="panel:abc")
    legacy = tg_kayit(a, "1", anahtar="legacy:k:OF:5")
    r = c.post("/kayitlar/toplu-kt", json={"ids": [a1, a2, b1, eski, panel_kaydi, legacy], "deger": "1"},
               headers={"X-CSRF": csrf(c)})
    assert r.status_code == 200 and r.json["degisen"] == 6, r.json
    rows = q(a, "SELECT chat_id,tur,metin,kayit_idler FROM bot_giden ORDER BY id")
    assert [x["chat_id"] for x in rows] == ["1", "2"]
    assert rows[0]["metin"] == f"✅ 2 kanıtın onaylandı: #{a1}, #{a2} (OF, PA)"
    assert rows[1]["metin"] == f"✅ 1 kanıtın onaylandı: #{b1} (OF)"
    # Onay kaldırma mesaj üretmez; gönderilmemiş bildirimden o kayıt çıkar.
    assert c.post(f"/kayit/{a2}/kt", data={"csrf": csrf(c), "deger": "0"}).json["ok"]
    rows = q(a, "SELECT metin FROM bot_giden WHERE chat_id='1'")
    assert len(rows) == 1 and rows[0]["metin"] == f"✅ 1 kanıtın onaylandı: #{a1} (OF)"
    # Tekil onay aynı (henüz gönderilmemiş) mesaja eklenir; on taneden fazlası '…' ile kısalır.
    more = [tg_kayit(a, "1") for _ in range(11)]
    for kid in more:
        assert c.post(f"/kayit/{kid}/kt", data={"csrf": csrf(c), "deger": "1"}).json["ok"]
    text = q(a, "SELECT metin FROM bot_giden WHERE chat_id='1'")[0]["metin"]
    assert text.startswith("✅ 12 kanıtın onaylandı: ") and text.endswith(" … (OF)") and f"#{more[-1]}" not in text
    # Bot kuyruğu boşaltır: ekleyen başına tek Telegram mesajı.
    fake, bot = web_bot(a)
    assert bot.process_bildirimler() == 2
    sent = [p for m, p in fake.calls if m == "sendMessage"]
    assert sorted(p["chat_id"] for p in sent) == ["1", "2"]
    # Kapalı ayar: yeni onay bildirimi yazılmaz.
    env_kid = tg_kayit(a, "3")
    import os
    os.environ["BOT_ONAY_BILDIRIMI"] = "0"
    try:
        assert c.post(f"/kayit/{env_kid}/kt", data={"csrf": csrf(c), "deger": "1"}).json["ok"]
    finally:
        del os.environ["BOT_ONAY_BILDIRIMI"]
    assert not q(a, "SELECT 1 FROM bot_giden WHERE chat_id='3'")


def test_silme_bildirimi_nedenle_ve_eski_kayit_haric(web, env):
    c, a = web
    login(c)
    kid = tg_kayit(a, "1")
    eski = tg_kayit(a, "1", gun_once=31)
    sessiz = tg_kayit(a, "1")
    assert c.post(f"/kayit/{kid}/sil", data={"csrf": csrf(c), "sebep": "Yanlış üye <b>ID</b>"}).json["ok"]
    assert c.post(f"/kayit/{eski}/sil", data={"csrf": csrf(c), "sebep": "temizlik"}).json["ok"]
    assert c.post(f"/kayit/{sessiz}/sil", data={"csrf": csrf(c)}).json["ok"]
    rows = q(a, "SELECT kayit_id,tur,metin FROM bot_giden ORDER BY id")
    assert rows == [{"kayit_id": kid, "tur": "silme", "metin": f"❌ #{kid} kaydın silindi. Neden: Yanlış üye &lt;b&gt;ID&lt;/b&gt;"},
                    {"kayit_id": sessiz, "tur": "silme", "metin": f"❌ #{sessiz} kaydın silindi."}]
    # Geri alma yeni mesaj üretmez.
    assert c.post(f"/kayit/{kid}/geri-al", data={"csrf": csrf(c)}).json["ok"]
    assert len(q(a, "SELECT 1 FROM bot_giden")) == 2


def test_ekleyene_sor_reply_ve_yanit_komutu_yorum_ve_bildirim(web, env):
    c, a = web
    login(c)
    kid = tg_kayit(a, "1")
    panel_kaydi = tg_kayit(a, kaynak="panel", anahtar="panel:xyz")
    assert c.get(f"/kayit/{kid}").json["tg_ekleyen"] is True
    assert c.get(f"/kayit/{panel_kaydi}").json["tg_ekleyen"] is False
    assert c.post(f"/kayit/{panel_kaydi}/yorum", data={"csrf": csrf(c), "yorum": "x", "alici": "tg"}).status_code == 400
    q1 = c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "Üye ID doğru mu?", "alici": "tg"}).json["yorum_id"]
    q2 = c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "Personel kodu?", "alici": "tg"}).json["yorum_id"]
    yorumlar = c.get(f"/kayit/{kid}").json["yorumlar"]
    assert [(y["alici"], y["tur"]) for y in yorumlar] == [("tg:1", "soru"), ("tg:1", "soru")]
    fake, bot = web_bot(a)
    giris(bot)
    assert bot.process_bildirimler() == 2
    sorular = q(a, "SELECT yorum_id,message_id,metin FROM bot_giden WHERE tur='soru' ORDER BY id")
    assert [s["yorum_id"] for s in sorular] == [q1, q2] and all(s["message_id"] for s in sorular)
    assert f"❓ <b>#{kid}</b> için takım liderinin sorusu" in sorular[0]["metin"] and f"/yanit {kid}" in sorular[0]["metin"]
    # Bot oturumu yarımken bile Reply yanıtı akışı bozmaz ve doğru soruya (ilk mesaj) bağlanır.
    upd = message(30, 30, "Evet, doğru.")
    upd["message"]["reply_to_message"] = {"message_id": sorular[0]["message_id"]}
    feed(bot, upd)
    feed(bot, message(31, 31, f"/yanit {kid} Kod P1"))
    yorumlar = q(a, "SELECT kullanici,metin,yanit_id,alici,tur FROM yorumlar WHERE tur='yanit' ORDER BY id")
    assert yorumlar == [
        {"kullanici": "Telegram: U", "metin": "Evet, doğru.", "yanit_id": q1, "alici": "testadmin", "tur": "yanit"},
        {"kullanici": "Telegram: U", "metin": "Kod P1", "yanit_id": q2, "alici": "testadmin", "tur": "yanit"},
    ]
    alerts = [x for x in c.get("/bildirim.json").json["bildirimler"] if x.get("tur") == "yanit"]
    assert len(alerts) == 2 and alerts[0]["kim"] == "Telegram: U"
    assert sum("Yanıtınız" in t for t in fake.texts()) == 2
    # Başkasının kaydına /yanit: soru yok → kayıt yazılmaz.
    feed(bot, message(32, 32, "/yanit 999999 deneme"))
    assert "bulunamadı" in fake.texts()[-1]
    # Lider, Telegram yanıtına panelden yanıt verince yine Telegram'a gider.
    tg_reply = q(a, "SELECT id FROM yorumlar WHERE tur='yanit' ORDER BY id LIMIT 1")[0]["id"]
    assert c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "Teşekkürler", "yanit_id": tg_reply}).json["ok"]
    assert q(a, "SELECT COUNT(*) n FROM bot_giden WHERE tur='soru'")[0]["n"] == 3
    # Ayar kapalıysa seçenek gizlenir ve gönderim reddedilir.
    import os
    os.environ["BOT_SORU_BILDIRIMI"] = "0"
    try:
        assert c.get(f"/kayit/{kid}").json["tg_ekleyen"] is False
        assert c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "x", "alici": "tg"}).status_code == 400
    finally:
        del os.environ["BOT_SORU_BILDIRIMI"]


def test_panel_kanit_ekle_mukerrer_yumusak_uyari(web, env):
    c, a = web
    login(c)
    r = gonder(c, uye_id="771", yine_de=None)
    assert r.status_code == 200 and r.json["ok"], r.json
    first = r.json["id"]
    # Aynı bağlantı: bir kez uyarı (kayıt açılmaz), yine_de=1 ile geçer.
    r = gonder(c, uye_id="772", yine_de=None)
    assert r.status_code == 409 and r.json["hatalar"]["mukerrer"].startswith("⚠️ Bu bağlantı") and f"#{first}" in r.json["hata"]
    assert len(q(a, "SELECT id FROM kayitlar")) == 1
    r = gonder(c, uye_id="772", yine_de="1")
    assert r.status_code == 200 and r.json["ok"]
    # Aynı proje + kategori + üye ID (farklı bağlantı) da uyarır.
    r = gonder(c, uye_id="771", link="https://gyazo.com/" + "e" * 32, yine_de=None)
    assert r.status_code == 409 and "Bu üye ID" in r.json["hata"]
    # Form sayfası (JSON olmayan) uyarıda yine_de gizli alanını taşır.
    r = gonder(c, json_mu=False, uye_id="771", link="https://gyazo.com/" + "e" * 32, yine_de=None)
    assert r.status_code == 409 and b'name="yine_de" value="1"' in r.data


# ------------------------------------------------------------------ inceleme düzeltmeleri (2.4.0)
def test_panel_mukerrer_baska_projedeki_kaydi_sizdirmaz(web, env):
    from tests.test_panel_kanit_ekle_236 import GYAZO, hesap, istemci
    c, a = web
    con = db.baglan(a["DB"])
    with db.transaction(con):
        pa = con.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,link,kaynak,giris_tipi,ekleyen_id,tarih,silindi,kt) "
                         "VALUES('tg:x:1','PA','HGST','P',?,'telegram','link','9',?,0,0)", (GYAZO, db.simdi())).lastrowid
    con.close()
    hesap(a, "lider", "OF:oku,kt")
    k = istemci("lider")
    r = gonder(k, yine_de=None)
    assert r.status_code == 200 and r.json["ok"], r.json  # PA kaydı (#id, tarih) görünmez, uyarı çıkmaz
    assert f"#{pa}" not in json.dumps(r.json, ensure_ascii=False)
    # Aynı projede aynı bağlantı yine uyarır.
    r = gonder(k, uye_id="999001", yine_de=None)
    assert r.status_code == 409 and "Bu bağlantı" in r.json["hata"]


def test_soru_kapaliyken_telegram_yanitina_panelden_yanit_verilebilir(web, env):
    import os
    c, a = web
    login(c)
    kid = tg_kayit(a, "1")
    q1 = c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "Üye ID?", "alici": "tg"}).json["yorum_id"]
    fake, bot = web_bot(a)
    giris(bot)
    assert bot.process_bildirimler() == 1
    feed(bot, message(40, 40, f"/yanıt {kid} Evet"))  # Türkçe 'ı' ile de tanınır
    tg_reply = q(a, "SELECT id FROM yorumlar WHERE tur='yanit' AND yanit_id=?", q1)[0]["id"]
    os.environ["BOT_SORU_BILDIRIMI"] = "0"
    try:
        r = c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": "Not aldım", "yanit_id": tg_reply})
        assert r.status_code == 200 and r.json["ok"], r.json
    finally:
        del os.environ["BOT_SORU_BILDIRIMI"]
    son = q(a, "SELECT alici,tur,yanit_id FROM yorumlar ORDER BY id DESC LIMIT 1")[0]
    assert son["tur"] == "yanit" and son["yanit_id"] == tg_reply and not str(son["alici"] or "").startswith("tg:")
    assert q(a, "SELECT COUNT(*) n FROM bot_giden WHERE tur='soru'")[0]["n"] == 1


def test_uzun_ozel_karakterli_soru_kesilmez_ve_iletilemeyince_lider_bilgilenir(web, env):
    c, a = web
    login(c)
    kid = tg_kayit(a, "1")
    metin = "<&" * 1500
    assert c.post(f"/kayit/{kid}/yorum", data={"csrf": csrf(c), "yorum": metin, "alici": "tg"}).json["ok"]
    giden = q(a, "SELECT metin FROM bot_giden WHERE tur='soru'")[0]["metin"]
    assert len(giden) < 4000 and giden.endswith(f"<code>/yanit {kid} metniniz</code> yazın.")
    govde = giden.split(":\n", 1)[1].split("\n\n—", 1)[0]
    assert govde.endswith("…") and "&lt;&amp;" in govde and not govde[:-1].endswith(("&", "&l", "&lt", "&a", "&am", "&amp"))
    fake, bot = web_bot(a)
    fake.permanent_fail = 1
    bot.process_bildirimler()
    assert q(a, "SELECT durum FROM bot_giden WHERE tur='soru'")[0]["durum"] == "olu"
    uyari = [x for x in c.get("/bildirim.json").json["bildirimler"] if "iletilemedi" in (x.get("metin") or "")]
    assert len(uyari) == 1 and uyari[0]["kim"] == "Telegram botu"


def test_turkce_yazimli_komutlar(setup):
    ayar, fake, bot = setup
    giris(bot)
    feed(bot, message(5, 5, "/yardım"))
    assert "KISA REHBER" in fake.texts()[-1]
    feed(bot, message(6, 6, "/kayıtlarım"))
    assert "Henüz Telegram ile girdiğiniz kayıt yok" in fake.texts()[-1]

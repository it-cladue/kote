"""python -m unittest  (app.py olay işleyicisini Slack'e bağlanmadan sahte istemciyle test eder)"""
import json
import os
import tempfile
import time
import unittest

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
_TMP = tempfile.mkdtemp()
os.environ["BRIDGE_CONFIG"] = os.path.join(_TMP, "config.json")

import app  # noqa: E402  (ortam değişkenleri ayarlandıktan sonra)


class FakeResponse(dict):
    pass


class FakeError(app.SlackApiError):
    def __init__(self, error):
        super().__init__(error, FakeResponse(error=error))


class FakeClient:
    """Sadece botun kullandığı Slack metodları; çağrıları kaydeder."""

    def __init__(self):
        self.groups = {"petra": ("S111", ["U00000001", "U00000002"]), "kote": ("S222", ["U00000002", "U00000003"])}
        self.emails = {"ali@firma.com": "U00000009", "yonetici@firma.com": "U0000ADMIN"}
        self.posted = []
        self.reactions = []
        self.created = []
        self.updated = []
        self.channels = [{"id": "C000000001", "name": "cozum", "is_ext_shared": True}, {"id": "C000000002", "name": "genel"}]

    def usergroups_list(self, **_):
        return {"usergroups": [{"id": gid, "handle": h, "users": list(users), "user_count": len(users), "date_delete": 0}
                               for h, (gid, users) in self.groups.items()]}

    def usergroups_create(self, name, handle):
        gid = "S_" + handle.upper()
        self.groups[handle] = (gid, [])
        self.created.append((name, handle))
        return {"usergroup": {"id": gid, "handle": handle, "name": name}}

    def usergroups_enable(self, usergroup):
        return {"ok": True}

    def usergroups_users_update(self, usergroup, users):
        for h, (gid, _) in list(self.groups.items()):
            if gid == usergroup:
                self.groups[h] = (gid, users.split(","))
                self.updated.append((h, users.split(",")))
                return {"ok": True}
        raise FakeError("no_such_subteam")

    def users_conversations(self, **_):
        return {"channels": self.channels, "response_metadata": {"next_cursor": ""}}

    history = {}            # kanal -> conversations.history mesaj listesi
    history_calls = []

    def conversations_history(self, channel, oldest, inclusive=False, limit=200):
        self.history_calls.append((channel, float(oldest)))
        return {"messages": [m for m in self.history.get(channel, []) if float(m["ts"]) > float(oldest)]}

    permalink_error = None

    def chat_getPermalink(self, channel, message_ts):
        if self.permalink_error:
            raise FakeError(self.permalink_error)
        return {"permalink": f"https://yeni.slack.com/archives/{channel}/p{message_ts.replace('.', '')}?from=api"}

    def usergroups_users_list(self, usergroup):
        for gid, users in self.groups.values():
            if gid == usergroup:
                return {"users": users}
        raise FakeError("no_such_subteam")

    def users_lookupByEmail(self, email):
        if email in self.emails:
            return {"user": {"id": self.emails[email]}}
        raise FakeError("users_not_found")

    def chat_postMessage(self, **kw):
        self.posted.append(kw)
        return {"ok": True}

    def reactions_add(self, **kw):
        self.reactions.append(kw)
        return {"ok": True}


def write_config(data):
    with open(os.environ["BRIDGE_CONFIG"], "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.utime(os.environ["BRIDGE_CONFIG"], None)


def msg(text, user="U000000EXT", channel="C000000001", ts="1700000000.000100", **extra):
    e = {"type": "message", "channel": channel, "user": user, "text": text, "ts": ts}
    e.update(extra)
    return e


_dm_ts = [1700001000.0]


def dm(text, user="U0000ADMIN"):
    _dm_ts[0] += 1
    return msg(text, user=user, channel="D1", ts=f"{_dm_ts[0]:.6f}", channel_type="im")


def read_config():
    with open(os.environ["BRIDGE_CONFIG"], encoding="utf-8") as f:
        return json.load(f)


class OnMessage(unittest.TestCase):
    def setUp(self):
        app.state.update({"config": None, "resolved": {"usergroups": {}, "users": {}}, "admin_ids": set(),
                          "resolved_at": 0.0, "members": {}, "team_url": "https://yeni.slack.com",
                          "team_name": "Yeni Zone", "seen": {}, "last_ts": {}, "last_notice": None,
                          "sent_total": 0, "failed_total": 0, "catchup": None, "handler": None})
        for f in ("state.json", "config.json.bak1", "config.json.bak2", "config.json.bak3"):
            try:
                os.remove(os.path.join(_TMP, f))
            except FileNotFoundError:
                pass
        app.loader = app.bridge.ConfigLoader(os.environ["BRIDGE_CONFIG"])
        write_config({"admins": ["yonetici@firma.com"], "keywords": {"petra": ["petra", "ali@firma.com"], "kote": "kote"}})
        self.client = FakeClient()

    def test_dm_modu_kanala_yazmaz_uyelere_dm_atar(self):
        app.on_message(msg("@petra sunucu düştü"), self.client)
        targets = [p["channel"] for p in self.client.posted]
        self.assertEqual(targets, ["U00000001", "U00000002", "U00000009"])            # kanal (C000000001) yok, sadece kişiler
        self.assertNotIn("C000000001", targets)
        body = self.client.posted[0]["text"]
        self.assertIn("<#C000000001>", body)
        self.assertIn("<@U000000EXT>", body)
        self.assertIn("> @petra sunucu düştü", body)
        self.assertIn("https://yeni.slack.com/archives/C000000001/p1700000000000100?from=api", body)  # Slack'in linki
        self.assertEqual(self.client.reactions, [])             # ack_reaction boş: iz yok

    def test_permalink_api_calismazsa_elle_kurulur(self):
        self.client.permalink_error = "message_not_found"
        app.on_message(msg("@petra"), self.client)
        body = self.client.posted[0]["text"]
        self.assertIn("https://yeni.slack.com/archives/C000000001/p1700000000000100|Mesaja git", body)
        self.assertNotIn("?from=api", body)

    def test_birden_fazla_keyword_tekrarsiz_ve_yazan_haric(self):
        app.on_message(msg("@petra ve @kote bakın", user="U00000002"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["U00000001", "U00000009", "U00000003"])

    def test_thread_yaniti_ayni_threade_link_verir(self):
        self.client.permalink_error = "fatal_error"   # elle kurulan biçimde thread parametreleri olmalı
        app.on_message(msg("@kote", ts="1700000005.000200", thread_ts="1700000000.000100"), self.client)
        self.assertIn("?thread_ts=1700000000.000100&cid=C000000001", self.client.posted[0]["text"])

    def test_eslesme_yoksa_sessiz(self):
        app.on_message(msg("bugün toplantı var"), self.client)
        app.on_message(msg("<!subteam^S111|@petra> gerçek mention"), self.client)   # kendi grubumuz: Slack bildirdi
        self.assertEqual(self.client.posted, [])

    def test_diger_zonun_gercek_etiketi_bizim_uyelere_dm(self):
        # İki zone'lu kurulum: A'daki kişi gerçek @petra yazdı (S999 A'nın grubu), bu bot B'nin.
        app.on_message(msg("<!subteam^S999|@petra> sunucu düştü"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["U00000001", "U00000002", "U00000009"])
        self.assertIn("> @petra sunucu düştü", self.client.posted[0]["text"])   # alıntıda ham token yok

    def test_bot_ve_alt_turler_atlanir(self):
        app.on_message(msg("@petra", bot_id="B1"), self.client)
        app.on_message(msg("@petra", subtype="message_changed"), self.client)
        app.on_message(msg("@petra", subtype="channel_join"), self.client)
        self.assertEqual(self.client.posted, [])
        app.on_message(msg("@petra", subtype="file_share"), self.client)
        self.assertEqual(len(self.client.posted), 3)

    def test_ayni_event_iki_kez_islenmez(self):
        app.on_message(msg("@petra"), self.client)
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(len(self.client.posted), 3)

    def test_kanal_filtresi(self):
        write_config({"keywords": {"petra": "petra"}, "channels": ["C_DIGER"]})
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(self.client.posted, [])

    def test_ack_reaction(self):
        write_config({"keywords": {"petra": "petra"}, "ack_reaction": "bell"})
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(self.client.reactions, [{"channel": "C000000001", "timestamp": "1700000000.000100", "name": "bell"}])

    def test_thread_modu_gercek_mention_yazar(self):
        write_config({"keywords": {"petra": "petra"}, "notify_mode": "thread"})
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(len(self.client.posted), 1)
        p = self.client.posted[0]
        self.assertEqual(p["channel"], "C000000001")
        self.assertEqual(p["thread_ts"], "1700000000.000100")
        self.assertIn("<!subteam^S111|@petra>", p["text"])

    def test_config_degisince_yeniden_yuklenir(self):
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(len(self.client.posted), 3)
        write_config({"keywords": {"fransa": ["ali@firma.com"]}})
        app.on_message(msg("@petra", ts="1700000001.000000"), self.client)      # artık tanımlı değil
        app.on_message(msg("@fransa", ts="1700000002.000000"), self.client)     # yeni keyword
        self.assertEqual([p["channel"] for p in self.client.posted], ["U00000001", "U00000002", "U00000009", "U00000009"])

    def test_bilinmeyen_grup_bot_dusurmez(self):
        write_config({"keywords": {"yok": "yokgrup", "petra": "petra"}})
        app.on_message(msg("@yok @petra"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["U00000001", "U00000002"])


class DmCommands(OnMessage):
    """Bota DM'den yazılan yönetim komutları."""

    def replies(self):
        return [p["text"] for p in self.client.posted if p["channel"] == "D1"]

    def test_dm_de_etiket_bildirim_tetiklemez(self):
        app.on_message(dm("@petra bakar mısın", user="U000000EXT"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["D1"])   # sadece yetki yanıtı

    def test_yetkisiz_reddedilir(self):
        app.on_message(dm("liste", user="U000000EXT"), self.client)
        self.assertIn("yetkin yok", self.replies()[0])
        self.assertEqual(read_config()["keywords"], {"petra": ["petra", "ali@firma.com"], "kote": "kote"})

    def test_yonetici_yoksa_kapali(self):
        write_config({"keywords": {"petra": "petra"}})
        app.on_message(dm("liste"), self.client)
        self.assertIn("Yönetici tanımlı değil", self.replies()[0])

    def test_yardim_ve_liste(self):
        app.on_message(dm("yardım"), self.client)
        app.on_message(dm("liste"), self.client)
        self.assertIn("komutları", self.replies()[0])
        self.assertIn("`@petra`", self.replies()[1])

    def test_ekle_kaydeder_ve_hemen_kullanilir(self):
        app.on_message(dm("ekle fransa <mailto:ali@firma.com|ali@firma.com> <@U00000005>"), self.client)
        self.assertEqual(read_config()["keywords"]["fransa"], ["ali@firma.com", "U00000005"])
        self.assertIn("Eklendi", self.replies()[0])
        app.on_message(msg("@fransa acil"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted[1:]], ["U00000009", "U00000005"])

    def test_cikar_ve_hata(self):
        app.on_message(dm("çıkar kote"), self.client)
        self.assertNotIn("kote", read_config()["keywords"])
        app.on_message(dm("çıkar yok"), self.client)
        self.assertIn("diye bir etiket yok", self.replies()[1])
        self.assertIn("`yardım`", self.replies()[1])
        app.on_message(dm("uçur"), self.client)
        self.assertIn("komut yok", self.replies()[2])

    def test_grup_olustur_slackte_acar_ve_etiket_tanimlar(self):
        app.on_message(dm("grup oluştur paris Paris Ekibi"), self.client)
        self.assertEqual(self.client.created, [("Paris Ekibi", "paris")])
        self.assertEqual(read_config()["keywords"]["paris"], ["paris"])
        self.assertIn("user group'u açıldı", self.replies()[0])
        app.on_message(dm("grup oluştur paris"), self.client)
        self.assertIn("zaten vardı", self.replies()[1])
        self.assertEqual(len(self.client.created), 1)

    def test_grup_ekle_cikar_uyelik(self):
        app.on_message(dm("grup ekle petra <@U00000007> <mailto:ali@firma.com|ali@firma.com> <@U00000001>"), self.client)
        self.assertEqual(self.client.updated, [("petra", ["U00000001", "U00000002", "U00000007", "U00000009"])])
        self.assertIn("eklendi", self.replies()[0])
        app.on_message(dm("grup çıkar petra <@U00000002>"), self.client)
        self.assertEqual(self.client.updated[-1], ("petra", ["U00000001", "U00000007", "U00000009"]))
        app.on_message(dm("grup ekle yokgrup <@U00000007>"), self.client)
        self.assertIn("diye bir user group yok", self.replies()[2])
        app.on_message(dm("grup ekle petra <mailto:kimse@firma.com|kimse@firma.com>"), self.client)
        self.assertIn("bulunamadı", self.replies()[3])
        self.assertEqual(len(self.client.updated), 2)
        # yeni üye bildirimde hemen görülür (üye önbelleği temizlenir)
        app.on_message(msg("@petra selam"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted if p["channel"].startswith("U")], ["U00000001", "U00000007", "U00000009"])

    def test_grup_son_uye_cikarilamaz(self):
        self.client.groups["kote"] = ("S222", ["U00000003"])
        app.on_message(dm("grup çıkar kote <@U00000003>"), self.client)
        self.assertIn("son üyeyi", self.replies()[0])
        self.assertEqual(self.client.updated, [])

    def test_grup_liste(self):
        app.on_message(dm("grup liste"), self.client)
        self.assertIn("`@petra` 2 üye", self.replies()[0])
        app.on_message(dm("grup liste petra"), self.client)
        self.assertIn("<@U00000001> <@U00000002>", self.replies()[1])

    def test_kanallar_durum_mod_emoji(self):
        app.on_message(dm("kanallar"), self.client)
        self.assertIn("<#C000000001> (Slack Connect)", self.replies()[0])
        self.assertIn("her kanalda", self.replies()[0])
        app.on_message(dm("kanal ekle <#C000000002|genel>"), self.client)
        self.assertEqual(read_config()["channels"], ["C000000002"])
        app.on_message(msg("@petra", channel="C000000001"), self.client)            # artık filtre dışı
        self.assertEqual([p for p in self.client.posted if p["channel"] == "U00000001"], [])
        app.on_message(dm("kanal temizle"), self.client)
        app.on_message(dm("mod thread"), self.client)
        app.on_message(dm("emoji bell"), self.client)
        cfg = read_config()
        self.assertEqual((cfg["channels"], cfg["notify_mode"], cfg["ack_reaction"]), ([], "thread", "bell"))
        app.on_message(dm("durum"), self.client)
        self.assertIn("`thread`", self.replies()[-1])
        self.assertIn("<@U0000ADMIN>", self.replies()[-1])

    def test_yetkili_ekle_hemen_gecerli(self):
        app.on_message(dm("yetkili ekle <@U000000EXT>"), self.client)
        self.assertEqual(read_config()["admins"], ["yonetici@firma.com", "U000000EXT"])
        app.on_message(dm("liste", user="U000000EXT"), self.client)
        self.assertIn("`@petra`", self.replies()[1])


class Resilience(DmCommands):
    """state.json, açılış taraması, yedekler, yazma hatası, durum."""

    def state_file(self):
        with open(app.STATE_PATH, encoding="utf-8") as f:
            return json.load(f)

    def test_islenen_mesajin_ts_i_state_jsona_yazilir(self):
        app.on_message(msg("selam", ts="1700000000.000100"), self.client)          # eşleşmese de kaydedilir
        self.assertEqual(self.state_file()["last_ts"], {"C000000001": "1700000000.000100"})
        app.on_message(msg("@petra", ts="1700000005.000100"), self.client)
        self.assertEqual(self.state_file()["last_ts"]["C000000001"], "1700000005.000100")
        app.on_message(msg("eski", ts="1700000001.000100"), self.client)          # geriye gitmez
        self.assertEqual(self.state_file()["last_ts"]["C000000001"], "1700000005.000100")
        self.assertIn("last_ping", self.state_file())

    def test_acilis_taramasi_kacirilan_etiketi_bildirir(self):
        now = time.time()
        old_ts = f"{now - 600:.6f}"
        app.state["last_ts"] = {"C000000001": old_ts}
        self.client.history["C000000001"] = [
            {"ts": f"{now - 900:.6f}", "user": "U000000EXT", "text": "@petra eski, zaten görüldü"},
            {"ts": f"{now - 300:.6f}", "user": "U000000EXT", "text": "@petra kaçırılan"},
            {"ts": f"{now - 200:.6f}", "user": "U000000EXT", "text": "alakasız"},
            {"ts": f"{now - 100:.6f}", "user": "U000000EXT", "text": "@petra düzenlendi", "subtype": "message_changed"},
        ]
        self.client.history["C000000002"] = [{"ts": f"{now - 50:.6f}", "user": "U000000EXT", "text": "@petra"}]  # last_ts yok
        app.catch_up(self.client)
        self.assertEqual([c for c, _ in self.client.history_calls], ["C000000001"])       # C2 hiç görülmemiş: taranmaz
        dms = [p for p in self.client.posted if p["channel"].startswith("U")]
        self.assertEqual(len(dms), 3)                                                     # sadece "kaçırılan"
        self.assertIn("> @petra kaçırılan", dms[0]["text"])
        self.assertEqual(app.state["catchup"], {"scanned": 3, "notified": 3, "channels": 1})
        # son ts = son İNSAN mesajı ("alakasız"); düzenleme olayı (message_changed) sayılmaz
        self.assertEqual(self.state_file()["last_ts"]["C000000001"], f"{now - 200:.6f}")
        # ikinci kez çağrılırsa aynı mesaj yeniden bildirilmez (last_ts ilerledi)
        app.catch_up(self.client)
        self.assertEqual(len([p for p in self.client.posted if p["channel"].startswith("U")]), 3)

    def test_acilis_taramasi_pencereyle_sinirli(self):
        now = time.time()
        app.state["last_ts"] = {"C000000001": f"{now - 7200:.6f}"}     # 2 saat önce
        self.client.history["C000000001"] = [{"ts": f"{now - 5000:.6f}", "user": "U000000EXT", "text": "@petra çok eski"}]
        app.catch_up(self.client)
        self.assertGreaterEqual(self.client.history_calls[0][1], now - app.CATCHUP_WINDOW - 1)
        self.assertEqual([p for p in self.client.posted if p["channel"].startswith("U")], [])

    def test_config_kaydinda_yedek_alinir(self):
        app.on_message(dm("mod thread"), self.client)
        app.on_message(dm("mod dm"), self.client)
        b1 = os.path.join(_TMP, "config.json.bak1")
        b2 = os.path.join(_TMP, "config.json.bak2")
        self.assertTrue(os.path.exists(b1) and os.path.exists(b2))
        with open(b1, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["notify_mode"], "thread")      # bir önceki hâl
        self.assertEqual(read_config()["notify_mode"], "dm")

    def test_config_yazilamazsa_komut_yaniti(self):
        orig = app.bridge.atomic_write_json

        def boom(path, data):
            raise PermissionError("dosya kilitli")
        app.bridge.atomic_write_json = boom
        try:
            app.on_message(dm("mod thread"), self.client)
        finally:
            app.bridge.atomic_write_json = orig
        self.assertIn("config.json yazılamadı", self.replies()[0])
        self.assertEqual(read_config().get("notify_mode", "dm"), "dm")   # değişmedi

    def test_durum_canlilik_bilgisi(self):
        app.on_message(msg("@petra"), self.client)
        app.on_message(dm("durum"), self.client)
        out = self.replies()[-1]
        self.assertIn("*Bağlantı:* KOPUK", out)                          # testte socket yok
        self.assertIn("*Son bildirim:* <#C000000001> @petra → 3 kişi", out)
        self.assertIn("3 gönderildi, 0 başarısız", out)
        self.assertIn("*Config:*", out)

    def test_dm_gonderim_hatasi_sayilir(self):
        orig = self.client.chat_postMessage

        def flaky(**kw):
            if kw["channel"] == "U00000002":
                raise FakeError("user_not_found")
            return orig(**kw)
        self.client.chat_postMessage = flaky
        app.on_message(msg("@petra"), self.client)
        self.assertEqual((app.state["sent_total"], app.state["failed_total"]), (2, 1))


class DotEnv(unittest.TestCase):
    def test_env_dosyasi_ortami_ezer(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w", encoding="utf-8") as f:
                f.write("# yorum\nSLACK_BOT_TOKEN=\"xoxb-dosya\"\nBOS=\nSLACK_APP_TOKEN=xapp-dosya\n")
            os.environ["SLACK_BOT_TOKEN"] = "xoxb-ortam"
            os.environ.pop("BOS", None)
            app.load_dotenv(p)
            self.assertEqual(os.environ["SLACK_BOT_TOKEN"], "xoxb-dosya")
            self.assertEqual(os.environ["SLACK_APP_TOKEN"], "xapp-dosya")
            self.assertNotIn("BOS", os.environ)
            app.load_dotenv(os.path.join(d, "yok.env"))                   # yoksa sessiz


if __name__ == "__main__":
    unittest.main()

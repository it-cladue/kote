"""python -m unittest  (app.py olay işleyicisini Slack'e bağlanmadan sahte istemciyle test eder)"""
import json
import os
import tempfile
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
        self.groups = {"petra": ("S111", ["U1", "U2"]), "kote": ("S222", ["U2", "U3"])}
        self.emails = {"ali@firma.com": "U9"}
        self.posted = []
        self.reactions = []

    def usergroups_list(self, **_):
        return {"usergroups": [{"id": gid, "handle": h} for h, (gid, _) in self.groups.items()]}

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


def msg(text, user="UEXT", channel="C1", ts="1700000000.000100", **extra):
    e = {"type": "message", "channel": channel, "user": user, "text": text, "ts": ts}
    e.update(extra)
    return e


class OnMessage(unittest.TestCase):
    def setUp(self):
        app.state.update({"config": None, "resolved": {"usergroups": {}, "users": {}},
                          "resolved_at": 0.0, "members": {}, "team_url": "https://yeni.slack.com", "seen": {}})
        app.loader = app.bridge.ConfigLoader(os.environ["BRIDGE_CONFIG"])
        write_config({"keywords": {"petra": ["petra", "ali@firma.com"], "kote": "kote"}})
        self.client = FakeClient()

    def test_dm_modu_kanala_yazmaz_uyelere_dm_atar(self):
        app.on_message(msg("@petra sunucu düştü"), self.client)
        targets = [p["channel"] for p in self.client.posted]
        self.assertEqual(targets, ["U1", "U2", "U9"])            # kanal (C1) yok, sadece kişiler
        self.assertNotIn("C1", targets)
        body = self.client.posted[0]["text"]
        self.assertIn("<#C1>", body)
        self.assertIn("<@UEXT>", body)
        self.assertIn("> @petra sunucu düştü", body)
        self.assertIn("https://yeni.slack.com/archives/C1/p1700000000000100", body)
        self.assertEqual(self.client.reactions, [])             # ack_reaction boş: iz yok

    def test_birden_fazla_keyword_tekrarsiz_ve_yazan_haric(self):
        app.on_message(msg("@petra ve @kote bakın", user="U2"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["U1", "U9", "U3"])

    def test_thread_yaniti_ayni_threade_link_verir(self):
        app.on_message(msg("@kote", ts="1700000005.000200", thread_ts="1700000000.000100"), self.client)
        self.assertIn("?thread_ts=1700000000.000100&cid=C1", self.client.posted[0]["text"])

    def test_eslesme_yoksa_sessiz(self):
        app.on_message(msg("bugün toplantı var"), self.client)
        app.on_message(msg("<!subteam^S111|@petra> gerçek mention"), self.client)
        self.assertEqual(self.client.posted, [])

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
        self.assertEqual(self.client.reactions, [{"channel": "C1", "timestamp": "1700000000.000100", "name": "bell"}])

    def test_thread_modu_gercek_mention_yazar(self):
        write_config({"keywords": {"petra": "petra"}, "notify_mode": "thread"})
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(len(self.client.posted), 1)
        p = self.client.posted[0]
        self.assertEqual(p["channel"], "C1")
        self.assertEqual(p["thread_ts"], "1700000000.000100")
        self.assertIn("<!subteam^S111|@petra>", p["text"])

    def test_config_degisince_yeniden_yuklenir(self):
        app.on_message(msg("@petra"), self.client)
        self.assertEqual(len(self.client.posted), 3)
        write_config({"keywords": {"fransa": ["ali@firma.com"]}})
        app.on_message(msg("@petra", ts="1700000001.000000"), self.client)      # artık tanımlı değil
        app.on_message(msg("@fransa", ts="1700000002.000000"), self.client)     # yeni keyword
        self.assertEqual([p["channel"] for p in self.client.posted], ["U1", "U2", "U9", "U9"])

    def test_bilinmeyen_grup_bot_dusurmez(self):
        write_config({"keywords": {"yok": "yokgrup", "petra": "petra"}})
        app.on_message(msg("@yok @petra"), self.client)
        self.assertEqual([p["channel"] for p in self.client.posted], ["U1", "U2"])


if __name__ == "__main__":
    unittest.main()

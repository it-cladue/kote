"""python -m unittest  (Slack'e bağlanmadan eşleştirme, config ve metin mantığını test eder)"""
import json
import os
import tempfile
import time
import unittest

import bridge

KW = ["petra", "kote", "fransa", "paris"]


class FindKeywords(unittest.TestCase):
    def test_duz_metin_etiket(self):
        self.assertEqual(bridge.find_keywords("Merhaba @petra bakar mısınız", KW), ["petra"])
        self.assertEqual(bridge.find_keywords("@Petra acil", KW), ["petra"])
        self.assertEqual(bridge.find_keywords("@petra'ya iletildi", KW), ["petra"])
        self.assertEqual(bridge.find_keywords("(@petra) ve @kote.", KW), ["petra", "kote"])
        self.assertEqual(bridge.find_keywords("@paris\n@fransa", KW), ["fransa", "paris"])
        self.assertEqual(bridge.find_keywords("şu @petra için", KW), ["petra"])

    def test_yanlis_pozitifler(self):
        self.assertEqual(bridge.find_keywords("@petrax", KW), [])
        self.assertEqual(bridge.find_keywords("ali@petra.com", KW), [])
        self.assertEqual(bridge.find_keywords("@petra-2", KW), [])
        self.assertEqual(bridge.find_keywords("petra bugün yok", KW), [])
        self.assertEqual(bridge.find_keywords("", KW), [])
        self.assertEqual(bridge.find_keywords(None, KW), [])

    def test_gercek_mention_tokenlari_eslesmez(self):
        self.assertEqual(bridge.strip_slack_tokens("<!subteam^S123|@petra> bak").strip(), "bak")
        self.assertEqual(bridge.find_keywords("<!subteam^S123|@petra> bakar mısın", KW), [])
        self.assertEqual(bridge.find_keywords("<@U123> <#C1|petra> <https://x.y/@petra>", KW), [])
        self.assertEqual(bridge.find_keywords("<!subteam^S123|@petra> ayrıca @kote", KW), ["kote"])

    def test_baska_zonun_gercek_etiketi_duz_metin_olur(self):
        local = {"S111"}
        # kendi grubumuz: dokunulmaz -> strip eder -> eşleşmez (Slack zaten bildirdi)
        t = bridge.expose_foreign_subteams("<!subteam^S111|@petra> bak", local)
        self.assertEqual(t, "<!subteam^S111|@petra> bak")
        self.assertEqual(bridge.find_keywords(t, KW), [])
        # başka workspace'in grubu: "@petra" olur -> eşleşir
        t = bridge.expose_foreign_subteams("<!subteam^S999|@petra> bak", local)
        self.assertEqual(t.split(), ["@petra", "bak"])
        self.assertEqual(bridge.find_keywords(t, KW), ["petra"])
        # bitişik ek / karakter eşleşmeyi bozmaz
        t = bridge.expose_foreign_subteams("x<!subteam^S999|@petra>lar", local)
        self.assertEqual(bridge.find_keywords(t, KW), ["petra"])
        # handle'sız token ve boş metin
        self.assertEqual(bridge.expose_foreign_subteams("<!subteam^S999> x", local), "<!subteam^S999> x")
        self.assertEqual(bridge.expose_foreign_subteams(None, local), "")

    def test_alintida_grup_etiketi_duz_metin(self):
        self.assertEqual(bridge.quote("<!subteam^S111|@petra> acil"), "> @petra acil")
        self.assertEqual(bridge.plain_subteams("<!subteam^S1> x"), "@grup x")

    def test_kod_icindeki_etiket_tetiklemez(self):
        self.assertEqual(bridge.find_keywords("etiket için `@petra` yazın", KW), [])
        self.assertEqual(bridge.find_keywords("```\n@petra\n```", KW), [])
        self.assertEqual(bridge.find_keywords("`@petra` değil @petra", KW), ["petra"])

    def test_noktali_handle_ayri_etikettir(self):
        self.assertEqual(bridge.find_keywords("@petra.ops bakar mı", KW + ["petra.ops"]), ["petra.ops"])
        self.assertEqual(bridge.find_keywords("@petra. Sonra", KW), ["petra"])

    def test_turkce_buyuk_harf(self):
        self.assertEqual(bridge.find_keywords("@İŞ acil", ["iş"]), ["iş"])
        self.assertEqual(bridge.find_keywords("@PARİS", KW), ["paris"])
        self.assertEqual(bridge.fold("İstanbul Iıİ"), "istanbul iıi".replace("ı", "i"))

    def test_require_at_false(self):
        self.assertEqual(bridge.find_keywords("petra bakar mı", KW, require_at=False), ["petra"])
        self.assertEqual(bridge.find_keywords("@petra bakar mı", KW, require_at=False), ["petra"])
        self.assertEqual(bridge.find_keywords("x@petra", KW, require_at=False), [])


class Config(unittest.TestCase):
    def test_hedef_turleri(self):
        self.assertEqual(bridge.parse_target("petra", "k"), {"type": "usergroup", "handle": "petra"})
        self.assertEqual(bridge.parse_target("@Petra", "k"), {"type": "usergroup", "handle": "petra"})
        self.assertEqual(bridge.parse_target("Ali@Firma.com", "k"), {"type": "email", "email": "ali@firma.com"})
        self.assertEqual(bridge.parse_target("U0123ABCD", "k"), {"type": "user", "id": "U0123ABCD"})
        with self.assertRaisesRegex(ValueError, "boş"):
            bridge.parse_target("", "k")
        with self.assertRaisesRegex(ValueError, "geçerli"):
            bridge.parse_target("a b", "k")

    def test_normalize(self):
        c = bridge.normalize_config({
            "keywords": {
                "_not": "yok sayılır",
                "petra": "petra",
                "kote": ["kote", "mehmet@firma.com"],
                "@Fransa": ["ali@firma.com", "U0123ABCD"],
            },
            "channels": ["C1"],
            "notify_mode": "thread",
            "require_at": False,
            "ack_reaction": ":bell:",
        })
        self.assertEqual(list(c["keywords"]), ["petra", "kote", "fransa"])
        self.assertEqual(len(c["keywords"]["kote"]), 2)
        self.assertEqual(c["keywords"]["fransa"][1]["type"], "user")
        self.assertIn("C1", c["channels"])
        self.assertEqual(c["notify_mode"], "thread")
        self.assertFalse(c["require_at"])
        self.assertEqual(c["ack_reaction"], "bell")
        self.assertIn("{link}", c["dm_template"])
        self.assertIn("{mentions}", c["reply_template"])

    def test_varsayilanlar(self):
        c = bridge.normalize_config({"keywords": {"petra": "petra"}})
        self.assertEqual(c["notify_mode"], "dm")
        self.assertTrue(c["require_at"])
        self.assertEqual(c["ack_reaction"], "")
        self.assertEqual(c["channels"], set())

    def test_anahtarlar_kanonik_ve_birlesik(self):
        c = bridge.normalize_config({"keywords": {"@Fransa": ["ali@firma.com"], "fransa": ["U0123ABCD"], "İş": "is"}})
        self.assertEqual(sorted(c["keywords"]), ["fransa", "iş"])
        self.assertEqual([t["type"] for t in c["keywords"]["fransa"]], ["email", "user"])

    def test_sablon_ve_require_at_dogrulanir(self):
        with self.assertRaisesRegex(ValueError, "dm_template hatalı"):
            bridge.normalize_config({"keywords": {"petra": "petra"}, "dm_template": "{link} {kanal}"})
        with self.assertRaisesRegex(ValueError, "dm_template"):
            bridge.normalize_config({"keywords": {"petra": "petra"}, "dm_template": "link yok"})
        with self.assertRaisesRegex(ValueError, "require_at"):
            bridge.normalize_config({"keywords": {"petra": "petra"}, "require_at": "false"})
        ok = bridge.normalize_config({"keywords": {"petra": "petra"}, "dm_template": "{keyword} -> {link}"})
        self.assertEqual(ok["dm_template"], "{keyword} -> {link}")

    def test_alinti_token_ortasinda_kesilmez(self):
        text = "x " * 190 + "<@U0123456789ABCDEFGH|uzun-isim-buraya>"
        q = bridge.quote(text, limit=400)
        self.assertNotIn("<@", q)
        self.assertTrue(q.endswith("…"))

    def test_hatali_girisler(self):
        with self.assertRaisesRegex(ValueError, "keywords"):
            bridge.normalize_config({})
        with self.assertRaisesRegex(ValueError, "hiç keyword"):
            bridge.normalize_config({"keywords": {}})
        with self.assertRaisesRegex(ValueError, "en az bir hedef"):
            bridge.normalize_config({"keywords": {"petra": []}})
        with self.assertRaisesRegex(ValueError, "notify_mode"):
            bridge.normalize_config({"keywords": {"petra": "petra"}, "notify_mode": "sms"})

    def test_loader_degisiklik_gorur(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"keywords": {"petra": "petra"}}, f)
            loader = bridge.ConfigLoader(p)
            c1, changed = loader.load()
            self.assertTrue(changed)
            c2, changed = loader.load()
            self.assertFalse(changed)
            self.assertIs(c1, c2)
            time.sleep(0.01)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"keywords": {"kote": "kote"}}, f)
            os.utime(p, (time.time() + 2, time.time() + 2))
            c3, changed = loader.load()
            self.assertTrue(changed)
            self.assertEqual(list(c3["keywords"]), ["kote"])

    def test_ornek_config_gecerli(self):
        here = os.path.dirname(os.path.abspath(__file__))
        c, _ = bridge.ConfigLoader(os.path.join(here, "config.example.json")).load()
        self.assertEqual(list(c["keywords"]), ["petra", "kote", "fransa", "paris"])
        self.assertEqual(c["notify_mode"], "dm")


class Notify(unittest.TestCase):
    def setUp(self):
        self.cfg = bridge.normalize_config({
            "keywords": {"petra": ["petra", "ali@firma.com"], "kote": ["petra", "U0123ABCD"]},
        })
        self.resolved = {"usergroups": {"petra": "S111"}, "users": {"ali@firma.com": "U222"}}

    def test_dm_alicilari(self):
        members = {"S111": ["U1", "U2", "U222"]}
        got = bridge.recipients_for(["petra"], self.cfg, self.resolved, members.get)
        self.assertEqual(got, ["U1", "U2", "U222"])
        got = bridge.recipients_for(["petra", "kote"], self.cfg, self.resolved, members.get, exclude=("U2",))
        self.assertEqual(got, ["U1", "U222", "U0123ABCD"])
        got = bridge.recipients_for(["kote"], self.cfg, {"usergroups": {}, "users": {}}, members.get)
        self.assertEqual(got, ["U0123ABCD"])

    def test_mention_uretimi(self):
        self.assertEqual(bridge.mentions_for(["petra"], self.cfg, self.resolved), ["<!subteam^S111|@petra>", "<@U222>"])
        self.assertEqual(
            bridge.mentions_for(["petra", "kote"], self.cfg, self.resolved),
            ["<!subteam^S111|@petra>", "<@U222>", "<@U0123ABCD>"],
        )
        self.assertEqual(bridge.mentions_for(["kote"], self.cfg, {"usergroups": {}, "users": {}}), ["<@U0123ABCD>"])

    def test_permalink(self):
        self.assertEqual(
            bridge.permalink("https://yenizone.slack.com/", "C1", "1700000000.123456"),
            "https://yenizone.slack.com/archives/C1/p1700000000123456",
        )
        self.assertEqual(
            bridge.permalink("https://yenizone.slack.com", "C1", "1700000001.000100", "1700000000.123456"),
            "https://yenizone.slack.com/archives/C1/p1700000001000100?thread_ts=1700000000.123456&cid=C1",
        )
        self.assertNotIn("?", bridge.permalink("https://x.slack.com", "C1", "1.2", "1.2"))

    def test_dm_metni(self):
        text = bridge.build_dm_text(bridge.DEFAULT_DM_TEMPLATE, "C1", "U9", ["petra"], "sunucu düştü\nacil", "https://l")
        self.assertIn("<#C1>", text)
        self.assertIn("<@U9>", text)
        self.assertIn("*@petra*", text)
        self.assertIn("> sunucu düştü\n> acil", text)
        self.assertIn("<https://l|Mesaja git>", text)
        self.assertIn("> _(metin yok)_", bridge.build_dm_text(bridge.DEFAULT_DM_TEMPLATE, "C1", "U9", ["petra"], "", "l"))
        self.assertTrue(bridge.quote("x" * 1000).endswith("…"))

    def test_yanit_sablonu(self):
        self.assertEqual(
            bridge.build_reply(bridge.DEFAULT_REPLY_TEMPLATE, ["<!subteam^S1|@petra>"], "U9"),
            "<!subteam^S1|@petra> <@U9> sizi etiketledi.",
        )
        self.assertEqual(bridge.build_reply(bridge.DEFAULT_REPLY_TEMPLATE, ["<@U1>"], None), "<@U1> sizi etiketledi.")


if __name__ == "__main__":
    unittest.main()

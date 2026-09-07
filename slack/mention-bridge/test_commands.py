"""python -m unittest  (DM komutlarının ayrıştırma ve config değişiklikleri; Slack'e bağlanmaz)"""
import unittest

import bridge
import commands
from commands import CommandError


class Parse(unittest.TestCase):
    def test_tokenize_slack_tokenlari(self):
        self.assertEqual(
            commands.tokenize("ekle petra <@U123|ali> <mailto:a@b.co|a@b.co> <#C9|genel> <!subteam^S1|@kote> <https://x.y>"),
            ["ekle", "petra", "U123", "a@b.co", "C9", "kote"],
        )
        self.assertEqual(commands.tokenize("  "), [])

    def test_turkce_ve_buyuk_harf(self):
        self.assertEqual(commands.parse("ÇIKAR petra"), ("cikar", ["petra"]))
        self.assertEqual(commands.parse("çıkar petra"), ("cikar", ["petra"]))
        self.assertEqual(commands.parse("Grup Oluştur kote Kote Ekibi"), ("grup olustur", ["kote", "Kote", "Ekibi"]))
        self.assertEqual(commands.parse("YARDIM"), ("yardim", []))
        self.assertEqual(commands.parse("LİSTE"), ("liste", []))
        self.assertEqual(commands.parse("YETKİLİ EKLE <@U1>"), ("yetkili ekle", ["U1"]))
        self.assertEqual(commands.parse("EMOJİ kapat"), ("emoji", ["kapat"]))
        self.assertEqual(commands.parse("help"), ("yardim", []))
        self.assertEqual(commands.parse("kanal temizle"), ("kanal temizle", []))
        self.assertEqual(commands.parse("yetkili ekle <@U00000001>"), ("yetkili ekle", ["U00000001"]))

    def test_bilinmeyen(self):
        with self.assertRaisesRegex(CommandError, "komut yok"):
            commands.parse("uçur petra")
        with self.assertRaisesRegex(CommandError, "alt komutu eksik"):
            commands.parse("grup")
        with self.assertRaisesRegex(CommandError, "komut yok"):
            commands.parse("grup patlat x")
        with self.assertRaisesRegex(CommandError, "Boş"):
            commands.parse("")


class ConfigCommands(unittest.TestCase):
    def setUp(self):
        self.raw = {"admins": ["U000000ME"], "keywords": {"petra": "petra"}, "channels": []}
        self.ctx = {"me": "U000000ME", "known_groups": {"petra", "kote"}}

    def run_cmd(self, text):
        cmd, args = commands.parse(text)
        return commands.apply(self.raw, cmd, args, self.ctx)

    def test_ekle_yeni_etiket_ve_hedefler(self):
        reply, changed = self.run_cmd("ekle kote")
        self.assertTrue(changed)
        self.assertEqual(self.raw["keywords"]["kote"], ["kote"])
        reply, _ = self.run_cmd("ekle fransa <mailto:ali@firma.com|ali@firma.com> <@U00000077>")
        self.assertEqual(self.raw["keywords"]["fransa"], ["ali@firma.com", "U00000077"])
        self.assertIn("Eklendi", reply)
        reply, _ = self.run_cmd("ekle petra kote <@U00000077>")           # mevcut etikete ekleme, string->liste
        self.assertEqual(self.raw["keywords"]["petra"], ["petra", "kote", "U00000077"])
        reply, _ = self.run_cmd("ekle petra kote")                  # tekrar
        self.assertIn("Zaten vardı", reply)
        bridge.normalize_config(self.raw)                           # kaydedilebilir olmalı

    def test_ekle_olmayan_grup_uyarir(self):
        reply, _ = self.run_cmd("ekle paris")
        self.assertIn("@paris diye bir user group", reply)
        self.assertEqual(self.raw["keywords"]["paris"], ["paris"])  # yine de kaydedilir

    def test_ekle_hatali(self):
        with self.assertRaises(CommandError):
            self.run_cmd("ekle")
        with self.assertRaises(CommandError):
            self.run_cmd("ekle 'x y'")
        with self.assertRaisesRegex(CommandError, "kişi, kanal ya da e-posta olamaz"):
            self.run_cmd("ekle <@U00000077> petra")                       # kişi seçilmiş, etiket adı değil
        with self.assertRaisesRegex(CommandError, "kişi, kanal ya da e-posta olamaz"):
            self.run_cmd("ekle <#C0123ABCDE|genel>")
        with self.assertRaisesRegex(CommandError, "ile başlayamaz"):
            self.run_cmd("ekle _gizli <@U00000077>")

    def test_elle_yazilmis_anahtar_birlestirilir(self):
        self.raw["keywords"] = {"@Fransa": ["ali@firma.com"], "_not": "x"}
        self.run_cmd("ekle fransa <@U00000077>")
        self.assertEqual(self.raw["keywords"]["fransa"], ["ali@firma.com", "U00000077"])
        self.assertNotIn("@Fransa", self.raw["keywords"])
        self.assertEqual(self.raw["keywords"]["_not"], "x")

    def test_cikar(self):
        self.run_cmd("ekle petra <mailto:ali@firma.com|ali@firma.com> <@U00000077>")
        reply, _ = self.run_cmd("çıkar petra <@U00000077>")
        self.assertEqual(self.raw["keywords"]["petra"], ["petra", "ali@firma.com"])
        with self.assertRaisesRegex(CommandError, "zaten"):
            self.run_cmd("çıkar petra <@U00000077>")
        with self.assertRaisesRegex(CommandError, "Son etiketi"):
            self.run_cmd("sil petra")                                  # tek etiket kaldı
        self.run_cmd("ekle kote <@U00000001>")
        reply, _ = self.run_cmd("sil petra")
        self.assertNotIn("petra", self.raw["keywords"])
        with self.assertRaisesRegex(CommandError, "diye bir etiket yok"):
            self.run_cmd("çıkar petra")
        with self.assertRaisesRegex(CommandError, "Son etiketi"):
            self.run_cmd("çıkar kote <@U00000001>")                   # son hedef -> etiket silinirdi

    def test_liste(self):
        reply, changed = self.run_cmd("liste")
        self.assertFalse(changed)
        self.assertIn("`@petra`", reply)

    def test_kanal_filtresi(self):
        with self.assertRaisesRegex(CommandError, "bir kanal değil"):
            self.run_cmd("kanal ekle genel")
        self.run_cmd("kanal ekle <#C0123ABCD|genel> <#C0123ABCE|ops>")
        self.assertEqual(self.raw["channels"], ["C0123ABCD", "C0123ABCE"])
        self.run_cmd("kanal çıkar <#C0123ABCD|genel>")
        self.assertEqual(self.raw["channels"], ["C0123ABCE"])
        reply, _ = self.run_cmd("kanal temizle")
        self.assertEqual(self.raw["channels"], [])
        self.assertIn("her kanalda", reply)

    def test_mod_ve_emoji(self):
        self.run_cmd("mod thread")
        self.assertEqual(self.raw["notify_mode"], "thread")
        with self.assertRaises(CommandError):
            self.run_cmd("mod sms")
        self.run_cmd("emoji :bell:")
        self.assertEqual(self.raw["ack_reaction"], "bell")
        self.run_cmd("emoji kapat")
        self.assertEqual(self.raw["ack_reaction"], "")
        with self.assertRaises(CommandError):
            self.run_cmd("emoji 'çan sesi'")

    def test_yetkili(self):
        self.run_cmd("yetkili ekle <@U00000002> <mailto:x@f.com|x@f.com>")
        self.assertEqual(self.raw["admins"], ["U000000ME", "U00000002", "x@f.com"])
        with self.assertRaisesRegex(CommandError, "Kendini"):
            self.run_cmd("yetkili çıkar <@U000000ME>")
        self.run_cmd("yetkili çıkar <@U00000002>")
        self.assertEqual(self.raw["admins"], ["U000000ME", "x@f.com"])
        with self.assertRaises(CommandError):
            self.run_cmd("yetkili ekle petra")           # grup handle'ı kişi değil
        self.raw["admins"] = ["U000000ME"]
        with self.assertRaisesRegex(CommandError, "Son yetkili"):
            self.run_cmd("yetkili çıkar <@U000000ME>")
        reply, _ = self.run_cmd("yetkili liste")
        self.assertIn("<@U000000ME>", reply)

    def test_yetkili_eposta_buyuk_kucuk_harf(self):
        self.raw["admins"] = ["U000000ME", "Ali@Firma.com"]
        reply, _ = self.run_cmd("yetkili ekle <mailto:ali@firma.com|ali@firma.com>")
        self.assertIn("Zaten", reply)
        self.assertEqual(self.raw["admins"], ["U000000ME", "ali@firma.com"])
        self.run_cmd("yetkili çıkar <mailto:ALI@firma.com|ALI@firma.com>")
        self.assertEqual(self.raw["admins"], ["U000000ME"])

    def test_eposta_ile_tanimli_yetkili_kendini_cikaramaz(self):
        self.raw["admins"] = ["ben@firma.com", "U00000002"]
        ctx = {"me": "U000000ME", "me_email": "ben@firma.com", "known_groups": set()}
        cmd, args = commands.parse("yetkili çıkar <@U00000002>")
        commands.apply(self.raw, cmd, args, ctx)                              # başkasını çıkarabilir
        self.assertEqual(self.raw["admins"], ["ben@firma.com"])
        self.raw["admins"] = ["ben@firma.com", "U00000002"]
        cmd, args = commands.parse("yetkili çıkar <mailto:ben@firma.com|ben@firma.com>")
        with self.assertRaisesRegex(CommandError, "Kendini"):
            commands.apply(self.raw, cmd, args, ctx)


if __name__ == "__main__":
    unittest.main()

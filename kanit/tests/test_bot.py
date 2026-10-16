# -*- coding: utf-8 -*-
"""Telegram botu: sifre kapisi, bakim, gorsel (gyazo/dosya) akislari, ark_ana / ana_only / sessiz_tip, Geri/Iptal menuleri,
Lead ID akisi, cift Onayla, kopya gorsel, admin komutlari, nabiz/offset, 409/429, oturum temizligi, patlama korumasi.
Calistirma: cd kanit && python3 tests/test_bot.py   (dis ag yok: sahte Telegram+Gyazo sunucusu localhost'ta)"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TD = tempfile.mkdtemp(prefix="kanit-bot-")
os.environ["KANIT_VERI"] = os.path.join(TD, "veri")
os.environ.pop("KANIT_ENV", None)
from kanit import ayar as A, db, gorsel
import importlib
import kanit.bot  # paket: calistir(ayar=None, bir_tur=False) fonksiyonunu sunar
from kanit.bot import akis
C = importlib.import_module("kanit.bot.calistir")  # modul (paketteki 'calistir' adi fonksiyondur)
from sahte_telegram import SahteSunucu

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        raise SystemExit(1)


def calistir():
    ayar = A.yukle()
    s = SahteSunucu("TEST")
    ayar.update({"TELEGRAM_TOKEN": "TEST", "TELEGRAM_API": s.url, "GYAZO_API": s.url, "GYAZO_TOKEN": "gz", "BOT_PASSWORD": "gizli123",
                 "ADMIN_IDS": ["999"], "MAX_DENEME": 3, "MAX_GORSEL_MB": 8, "LOG_EKRAN": "0", "HATA_BEKLEME_SN": 0, "CAKISMA_BEKLEME_SN": 0})
    b = C.Bot(ayar)
    b.uyku = lambda sn: None
    conn = b.conn
    s.dosyalar["foto3"] = s.dosyalar["foto1"][:-2] + b"\x01\xff\xd9"
    s.dosyalar["foto4"] = s.dosyalar["foto1"][:-2] + b"\x02\xff\xd9"
    for i in range(5, 10):
        s.dosyalar[f"foto{i}"] = s.dosyalar["foto1"][:-2] + bytes([i]) + b"\xff\xd9"
    s.dosyalar["sahte"] = b"bu bir gorsel degil, duz metin" * 3

    def tur():
        return b.tur()

    def yaz(uid, metin, **k):
        s.temizle(); s.mesaj(uid, metin, **k); tur()

    def foto(uid, fid="foto1", **k):
        s.temizle(); s.foto(uid, fid, **k); tur()

    def bas(uid, data, msg_id=None):
        s.temizle(); s.geri_arama(uid, data, msg_id); tur()

    def ot(uid):
        return db.oturum_al(conn, str(uid))

    def kayitlar():
        return [dict(r) for r in conn.execute("SELECT * FROM kayitlar ORDER BY id").fetchall()]

    # ================= sifre kapisi =================
    yaz(101, "/start")
    check("Merhaba" in s.son_metin(101) and "\u015fifreyi yaz\u0131n" in s.son_metin(101), "onaysiz kullanici /start -> sifre istenir")
    yaz(101, "yanlis1"); check("Yanl\u0131\u015f \u015fifre! 2 deneme" in s.son_metin(101), "yanlis sifre 1 -> 2 hak kaldi")
    yaz(101, "yanlis2"); check("1 deneme" in s.son_metin(101) and db.tg_al(conn, "101")["deneme"] == 2, "yanlis sifre 2 -> deneme sayaci 2")
    yaz(101, "yanlis3")
    u = db.tg_al(conn, "101")
    check("engellendi" in s.son_metin(101) and u["engelli"] == 1 and "\u015fifre" in u["engel_sebep"] and s.liste("deleteMessage", 101), "3. yanlis -> engelli (sebep sifre), mesaj silindi")
    yaz(101, "gizli123"); check(not s.liste("sendMessage", 101) and len(s.liste("deleteMessage", 101)) == 1, "engelli kullanicinin mesaji silinir, yanit yok")
    foto(102); u = db.tg_al(conn, "102")
    check("yetkiniz yok" in s.son_metin(102) and u["engelli"] == 1 and "g\u00f6rsel" in u["engel_sebep"] and s.liste("deleteMessage", 102), "onaysizken gorsel -> engel (yetkisiz gorsel)")
    yaz(103, "gizli123", username="ayse", ad="Ayse")
    u = db.tg_al(conn, "103")
    check(u["onayli"] == 1 and u["username"] == "ayse" and "Ho\u015f geldiniz" in s.son_metin(103), "dogru sifre -> onayli + hos geldiniz")
    check(conn.execute("SELECT COUNT(*) FROM denetim WHERE islem='bot_onayla' AND kullanici='bot'").fetchone()[0] == 1, "onay denetime kim='bot' ile yazildi")
    yaz(103, "/foo"); check("g\u00f6rsel g\u00f6nderin ya da Lead ID" in s.son_metin(103), "onayli kullanici komut yazarsa 'basla' mesaji")
    s.temizle(); s.mesaj(103, "selam", chat_tipi="group"); tur(); check(not s.liste("sendMessage"), "grup mesaji yok sayilir")

    # ================= bakim modu =================
    db.ayar_yaz(conn, "bakim_modu", "1")
    yaz(103, "merhaba"); check("bak\u0131m modunda" in s.son_metin(103) and ot(103) is None, "bakim modu -> 'Bot bakimda', oturum acilmaz")
    yaz(999, "/durum"); check("<b>DURUM</b>" in s.son_metin(999), "bakimda admin komutlari calisir")
    db.ayar_yaz(conn, "bakim_modu", "0")

    # ================= gorsel -> gyazo =================
    foto(103)
    o = ot(103)
    check(o and o["adim"] == "kayit_secim" and o["fileId"] == "foto1" and o["fotoSha"] and o["girisTipi"] == "resim" and o["fotoTarih"] == 1760000000, "foto -> oturum kayit_secim (fileId, sha, fotoTarih)")
    check("G\u00f6rsel al\u0131nd\u0131" in s.son_metin(103) and s.klavye_verileri(103) == ["kayit_gyazo", "kayit_dosya", "iptal_basa"] and o["msgId"] == s.son_mesaj_id(103), "KB-KayitSecim + msgId oturumda")
    check(os.path.exists(b.gecici_yol("103")), "gorsel gecici dosyaya indirildi")
    bas(103, "kayit_gyazo")
    o = ot(103)
    kb = s.klavye_metinleri(103)
    check(o["adim"] == "proje" and o["kayitModu"] == "gyazo" and "Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr\u00fclecek" in s.son_metin(103), "kayit_gyazo -> proje adimi")
    check([len(r) for r in kb] == [3, 3, 1] and kb[0][0].endswith(" PP") and kb[2][0].endswith(" BETA") and s.klavye_verileri(103)[2] == "proje_of", f"proje klavyesi 3+3+1 emoji ile {kb}")
    check(s.liste("editMessageText", 103) and s.liste("editMessageText", 103)[0]["message_id"] == o["msgId"], "bot mesaji yerinde duzenlendi (editMessageText msgId)")
    bas(103, "proje_of")
    o = ot(103); kb = s.klavye_metinleri(103)
    check(o["proje"] == "of" and o["adim"] == "kategori" and "<b>Proje:</b> OF" in s.son_metin(103), "proje_of -> kategori adimi")
    check(kb == [["ARK", "DDS", "DDT"], ["HGST", "PRCST", "LPST"], ["\u2b05 Geri"]] and s.klavye_verileri(103)[-1] == "geri_proje", f"kategori klavyesi 3'lu + Geri {kb}")
    bas(103, "kat_hgst")
    o = ot(103); m = s.son_metin(103)
    check(o["kategori"] == "hgst" and o["adim"] == "personel" and "SE\u00c7\u0130LENLER" in m and "Kategori:</b> HGST" in m and "\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN" in m and "Personel kodunuzu yaz\u0131n" in m and s.klavye_verileri(103) == ["geri_kategori"], "kat_hgst -> personel istemi (Get-AdimMesaji) + Geri")
    yaz(103, " 215 ")
    o = ot(103); m = s.son_metin(103)
    check(o["personel"] == "215" and o["adim"] == "uyeid" and "\u00dcye ID'sini yaz\u0131n" in m and "Personel:</b> 215" in m and s.liste("deleteMessage", 103) and s.liste("editMessageText", 103), "personel yazildi -> uye id istemi, kullanici mesaji silindi, bot mesaji duzenlendi")
    yaz(103, "4956")
    o = ot(103); m = s.son_metin(103)
    check(o["uyeid"] == "4956" and o["adim"] == "ozet" and "SON KONTROL" in m and "<b>\u00dcye ID:</b> 4956" in m and "Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr\u00fclecek" in m and s.klavye_verileri(103) == ["onayla", "iptal"], "tek_uye -> SON KONTROL + Onayla/Iptal")
    bas(103, "onayla")
    ks = kayitlar(); k = ks[-1] if ks else {}
    check(len(ks) == 1 and k["proje"] == "OF" and k["kategori"] == "HGST" and k["kategori_kod"] == "hgst" and k["personel"] == "215" and k["uye_id"] == "4956" and k["ana_uye_id"] == "", "kayit_ekle: proje/kategori/personel/uye")
    check(k["link"].startswith("https://gyazo.com/") and k["link_turu"] == "gyazo" and len(s.gyazo_yuklemeler) == 1 and k["giris_tipi"] == "resim", "gyazo linki + link_turu gyazo + yukleme yapildi")
    check(k["gorsel_dosya"].startswith("OF/HGST_2025-10-09_") and k["gorsel_dosya"].endswith("_215_4956.jpg") and gorsel.tam_yol(ayar["GORSELLER"], k["gorsel_dosya"]), f"yerel gorsel de saklandi ({k['gorsel_dosya']})")
    check(k["ekleyen_tg_id"] == "103" and k["ekleyen_ad"] == "ayse" and k["ekleyen_guven"] == "kesin" and k["kaynak"] == "bot" and k["foto_tarih"] and k["foto_tarih"].startswith("2025-10-09"), "ekleyen bilgisi kesin, kaynak bot, foto_tarih")
    check(db.arsiv_kayitlari(conn, k["id"])[0]["kim"] == "bot" and conn.execute("SELECT COUNT(*) FROM denetim WHERE islem='ekle' AND kullanici='bot'").fetchone()[0] == 1, "arsiv + denetim kim='bot'")
    m = s.son_metin(103)
    check(ot(103) is None and "Kan\u0131t\u0131n\u0131z eklendi" in m and "Yeni kay\u0131t i\u00e7in g\u00f6rsel g\u00f6nderin" in m and not os.path.exists(b.gecici_yol("103")), "oturum silindi, basari mesaji, gecici dosya temizlendi")
    u = db.tg_al(conn, "103"); check(u["kayit_sayisi"] == 1 and u["proje_sayilari"] == {"OF": 1} and u["kategori_sayilari"] == {"HGST": 1} and u["son_kayit_kategori"] == "HGST", "tg_kayit_sayaci")
    bas(103, "onayla")
    check(len(kayitlar()) == 1 and not s.liste("editMessageText", 103) and not s.liste("sendMessage", 103) and len(s.gyazo_yuklemeler) == 1, "ikinci Onayla bos islem (oturum yok)")
    foto(103)
    check("az \u00f6nce kaydedildi" in s.son_metin(103) and ot(103) is None, "ayni gorsel 5 dk icinde -> 'az once kaydedildi', oturum yok")
    b.son_gorseller["103"] = (b.son_gorseller["103"][0], time.time() - 400)
    foto(103); check(ot(103) is not None and ot(103)["adim"] == "kayit_secim", "5 dk gecince ayni gorsel kabul edilir")
    bas(103, "iptal_basa"); check(ot(103) is None and "\u0130ptal edildi" in s.son_metin(103), "iptal_basa -> oturum silindi")

    # ================= gorsel -> dosya, ark_ana =================
    foto(103, "foto2"); bas(103, "kayit_dosya")
    o = ot(103); check(o["kayitModu"] == "dosya" and o["adim"] == "proje" and "dosyaya kaydedilecek" in s.son_metin(103), "kayit_dosya -> proje")
    bas(103, "proje_pa"); bas(103, "kat_ark")
    yaz(103, "7"); m = s.son_metin(103)
    check("Arkada\u015f \u00dcye ID'sini yaz\u0131n" in m and ot(103)["adim"] == "uyeid" and s.klavye_verileri(103) == ["geri_personel"], "ark_ana: arkadas uye id sorulur")
    yaz(103, "111"); m = s.son_metin(103)
    check("Ana \u00dcye ID'sini yaz\u0131n" in m and "Arkada\u015f ID al\u0131nd\u0131" in m and ot(103)["adim"] == "anaid" and "\u00dcye ID:</b> 111" in m and s.klavye_verileri(103) == ["geri_uyeid"], "ark_ana: ana uye id sorulur (ucuncu alan)")
    yaz(103, "222"); m = s.son_metin(103)
    check(ot(103)["adim"] == "ozet" and "Arkada\u015f \u00dcye ID:</b> 111" in m and "Ana \u00dcye ID:</b> 222" in m and "dosyaya kaydedilecek" in m, "ark_ana ozet: arkadas + ana")
    bas(103, "onayla"); k = kayitlar()[-1]
    check(len(kayitlar()) == 2 and k["proje"] == "PA" and k["kategori"] == "ARK" and k["personel"] == "7" and k["uye_id"] == "111" and k["ana_uye_id"] == "222", "ark_ana kaydi")
    check(k["link"] == "" and k["link_turu"] == "dosya" and k["gorsel_dosya"].startswith("PA/ARK_") and k["gorsel_dosya"].endswith("_7_111_222.jpg") and gorsel.tam_yol(ayar["GORSELLER"], k["gorsel_dosya"]) and len(s.gyazo_yuklemeler) == 1, "dosya modu: gyazo yok, link_turu dosya, dosya PA/ARK_...")
    check("Dosya: <code>" in s.son_metin(103) and os.path.basename(k["gorsel_dosya"]) in s.son_metin(103), "dosya modunda basari mesaji dosya adini verir")

    # ================= belge (PNG) + sessiz_tip =================
    s.temizle(); s.belge(103, "png1", "image/png"); tur()
    o = ot(103); check(o and o["adim"] == "kayit_secim" and o["fileId"] == "png1", "resim MIME'li belge de gorsel sayilir")
    bas(103, "kayit_dosya"); bas(103, "proje_hi"); bas(103, "kat_dds"); yaz(103, "9"); yaz(103, "333")
    o = ot(103); kb = s.klavye_metinleri(103)
    check(o["adim"] == "tip" and "Sessiz / Telesekreter t\u00fcr\u00fcn\u00fc se\u00e7in" in s.son_metin(103) and kb == [["Sessiz", "Telesekreter"], ["\u2b05 Geri"]], "sessiz_tip: tur butonlari")
    bas(103, "tip_telesekreter"); m = s.son_metin(103)
    check(ot(103)["tip"] == "Telesekreter" and ot(103)["adim"] == "ozet" and "<b>T\u00fcr:</b> Telesekreter" in m, "tip secildi -> ozet")
    bas(103, "onayla"); k = kayitlar()[-1]
    check(k["proje"] == "HI" and k["kategori"] == "DDS" and k["tip"] == "Telesekreter" and k["uye_id"] == "333" and k["gorsel_dosya"].endswith("_9_333_Telesekreter.jpg"), "sessiz_tip kaydi (PNG -> jpg)")
    with open(gorsel.tam_yol(ayar["GORSELLER"], k["gorsel_dosya"]), "rb") as f:
        check(f.read(2) == b"\xff\xd8", "PNG jpeg_yap ile JPEG'e cevrildi")

    # ================= ana_only =================
    foto(103, "foto3"); bas(103, "kayit_dosya"); bas(103, "proje_ga"); bas(103, "kat_lpst"); yaz(103, "5")
    check("Ana \u00dcye ID'sini yaz\u0131n" in s.son_metin(103), "ana_only: personelden sonra ana uye id")
    yaz(103, "555"); m = s.son_metin(103)
    check(ot(103)["adim"] == "ozet" and ot(103)["anaid"] == "555" and ot(103)["uyeid"] is None and "Ana \u00dcye ID:</b> 555" in m and "<b>\u00dcye ID:" not in m, "ana_only ozet")
    bas(103, "onayla"); k = kayitlar()[-1]
    check(k["kategori"] == "LPST" and k["ana_uye_id"] == "555" and k["uye_id"] == "" and k["gorsel_dosya"].endswith("_5_555.jpg"), "ana_only kaydi")

    # ================= Geri / Iptal menuleri =================
    foto(103, "foto4"); bas(103, "kayit_gyazo"); bas(103, "proje_ga"); bas(103, "kat_prcst")
    bas(103, "geri_kategori"); o = ot(103)
    check(o["adim"] == "kategori" and o["personel"] is None and o["proje"] == "ga" and "Kategoriyi se\u00e7in" in s.son_metin(103) and s.klavye_verileri(103)[0] == "kat_ark", "geri_kategori (orijinal gibi: personel silinir, kategori yeniden secilir)")
    bas(103, "kat_hgst"); yaz(103, "p1"); bas(103, "geri_personel"); o = ot(103)
    check(o["adim"] == "personel" and o["uyeid"] is None and "Personel kodunuzu yaz\u0131n" in s.son_metin(103), "geri_personel")
    bas(103, "geri_proje"); o = ot(103)
    check(o["adim"] == "proje" and o["kategori"] is None and s.klavye_verileri(103)[0] == "proje_pp", "geri_proje")
    bas(103, "proje_pp"); bas(103, "kat_hgst"); yaz(103, "<b>p2</b>"); yaz(103, "u2")
    check("&lt;b&gt;p2&lt;/b&gt;" in s.son_metin(103) and ot(103)["personel"] == "<b>p2</b>", "kullanici metni HTML kacirilir")
    bas(103, "iptal"); kb = s.klavye_verileri(103)
    check("Nereye d\u00f6nmek" in s.son_metin(103) and kb == ["iptal_basa", "iptal_proje", "iptal_kategori", "iptal_bilgi"], "Iptal menusu 4 secenek")
    bas(103, "iptal_bilgi"); o = ot(103)
    check(o["adim"] == "personel" and o["personel"] is None and o["uyeid"] is None and o["proje"] == "pp" and o["kategori"] == "hgst", "iptal_bilgi: proje/kategori korunur, bilgiler silinir")
    yaz(103, "p3"); yaz(103, "u3"); bas(103, "iptal"); bas(103, "iptal_kategori"); o = ot(103)
    check(o["adim"] == "kategori" and o["personel"] is None and o["proje"] == "pp", "iptal_kategori")
    bas(103, "kat_hgst"); yaz(103, "p4"); yaz(103, "u4"); bas(103, "iptal"); bas(103, "iptal_proje"); o = ot(103)
    check(o["adim"] == "proje" and o["kategori"] is None and o["personel"] is None and o["fileId"] == "foto4", "iptal_proje: gorsel korunur")
    bas(103, "proje_zz"); check("art\u0131k aktif de\u011fil" in s.son_metin(103) and ot(103)["adim"] == "proje", "pasif/bilinmeyen proje reddedilir")
    db.kategori_sil(conn, "prcst", "test")
    bas(103, "proje_pp"); bas(103, "kat_prcst"); check("kategori art\u0131k aktif de\u011fil" in s.son_metin(103) and ot(103)["adim"] == "kategori", "pasif kategori reddedilir")
    db.kategori_kaydet(conn, "prcst", "PRCST", "tek_uye", "test")
    yaz(103, "LEAD-X"); o = ot(103)
    check(o["adim"] == "lead_onay" and o["girisTipi"] == "yazili" and o["leadId"] == "LEAD-X", "secim adiminda yazilan metin Lead ID akisini baslatir (foto oturumu yerine)")
    foto(103, "foto4"); check(ot(103)["adim"] == "kayit_secim" and ot(103)["girisTipi"] == "resim", "yeni foto oturumu her zaman sifirdan baslatir")
    bas(103, "iptal_basa")

    # ================= gyazo bakim =================
    db.ayar_yaz(conn, "gyazo_bakim", "1")
    foto(103, "foto5"); o = ot(103); kb = s.klavye_verileri(103)
    check(o["adim"] == "gyazo_bakim" and "Gyazo sunucusu \u015fu anda bak\u0131mda" in s.son_metin(103) and kb == ["kayit_dosya", "iptal_basa"], "gyazo bakimda: KB-GyazoBakim (gyazo secenegi yok)")
    bas(103, "kayit_gyazo"); check(ot(103)["adim"] == "gyazo_bakim" and "bak\u0131mda" in s.son_metin(103), "bakimda kayit_gyazo basilsa da uyari")
    bas(103, "kayit_dosya"); check(ot(103)["kayitModu"] == "dosya" and ot(103)["adim"] == "proje", "bakimda dosya secenegi devam eder")
    bas(103, "iptal_basa")
    db.ayar_yaz(conn, "gyazo_bakim", "0")
    foto(103, "foto6"); bas(103, "kayit_gyazo"); bas(103, "proje_pp"); bas(103, "kat_hgst"); yaz(103, "1"); yaz(103, "2")
    db.ayar_yaz(conn, "gyazo_bakim", "1")
    bas(103, "onayla"); o = ot(103)
    check(o and o["adim"] == "gyazo_bakim" and "bilgileriniz korunur" in s.son_metin(103) and s.klavye_verileri(103) == ["kayit_dosya", "iptal_basa"] and len(kayitlar()) == 4, "Onayla aninda gyazo bakima girdi -> secenek, kayit yok")
    bas(103, "kayit_dosya"); o = ot(103)
    check(o["adim"] == "ozet" and o["kayitModu"] == "dosya" and o["personel"] == "1" and "dosyaya kaydedilecek" in s.son_metin(103), "bakimdan dosyaya gecis: bilgiler korunur, dogrudan ozet")
    bas(103, "onayla"); k = kayitlar()[-1]
    check(len(kayitlar()) == 5 and k["link_turu"] == "dosya" and k["proje"] == "PP" and ot(103) is None, "dosya olarak kaydedildi")
    db.ayar_yaz(conn, "gyazo_bakim", "0")

    # ================= gyazo hatasi -> KB-Hata, tekrar dene =================
    foto(103, "foto7"); bas(103, "kayit_gyazo"); bas(103, "proje_pp"); bas(103, "kat_hgst"); yaz(103, "1"); yaz(103, "2")
    s.gyazo_hata = True
    bas(103, "onayla"); o = ot(103)
    check(o and o["adim"] == "ozet" and o.get("gorselDosya", "").startswith("PP/HGST_") and "y\u00fcklenemedi" in s.son_metin(103) and s.klavye_verileri(103) == ["onayla", "iptal_basa"], "gyazo hatasi: oturum korunur, KB-Hata, yerel dosya yazildi")
    check(len(kayitlar()) == 5 and "gyazo" in (db.ayar_al(conn, "son_hata") or "").lower(), "hata kayit yazmadi, son_hata ayarlandi")
    s.gyazo_hata = False
    yerel = o["gorselDosya"]
    bas(103, "onayla"); k = kayitlar()[-1]
    check(len(kayitlar()) == 6 and k["link_turu"] == "gyazo" and k["gorsel_dosya"] == yerel and ot(103) is None and len(s.gyazo_yuklemeler) == 2, "Tekrar Dene: ayni yerel dosya, gyazo linki, kayit")
    s.temizle(); s.geri_arama(103, "onayla"); s.geri_arama(103, "onayla"); tur()
    check(len(kayitlar()) == 6 and not s.liste("editMessageText", 103), "ayni pakette iki Onayla da bos islem")

    # ================= Lead ID akisi =================
    yaz(103, "LEAD-77"); o = ot(103); m = s.son_metin(103)
    check(o["adim"] == "lead_onay" and o["leadId"] == "LEAD-77" and "Lead ID mi gireceksiniz" in m and "LEAD-77" in m and s.klavye_verileri(103) == ["lead_onay", "lead_degistir", "lead_iptal"], "metin -> Lead ID sorusu (KB-LeadOnay)")
    yaz(103, "LEAD-78"); check(ot(103)["leadId"] == "LEAD-78" and s.liste("deleteMessage", 103) and "LEAD-78" in s.son_metin(103), "onay beklerken yeni metin Lead ID'yi gunceller")
    bas(103, "lead_degistir"); check("Yeni Lead ID'yi yaz\u0131n" in s.son_metin(103) and ot(103)["adim"] == "lead_onay", "lead_degistir")
    yaz(103, "LEAD-79"); bas(103, "lead_onay"); o = ot(103)
    check(o["adim"] == "proje" and o["girisTipi"] == "yazili" and "Lead ID al\u0131nd\u0131:</b> LEAD-79" in s.son_metin(103), "lead_onay -> proje")
    bas(103, "proje_vi"); bas(103, "kat_hgst"); yaz(103, "p"); yaz(103, "u"); m = s.son_metin(103)
    check(ot(103)["adim"] == "ozet" and "<b>Lead ID:</b> LEAD-79" in m and "G\u00f6rsel" not in m, "yazili ozet Lead ID gosterir")
    bas(103, "onayla"); k = kayitlar()[-1]
    check(len(kayitlar()) == 7 and k["giris_tipi"] == "yazili" and k["lead_id"] == "LEAD-79" and k["link"] == "LEAD-79" and k["link_turu"] == "metin" and k["gorsel_dosya"] == "" and k["proje"] == "VI" and len(s.gyazo_yuklemeler) == 2, "yazili kayit: lead_id, link=metin, gorsel yok")
    yaz(103, "x"); bas(103, "lead_iptal"); check(ot(103) is None and "\u0130ptal edildi" in s.son_metin(103), "lead_iptal")

    # ================= gorsel sinirlari =================
    foto(103, "buyuk"); check("\u00e7ok b\u00fcy\u00fck" in s.son_metin(103) and ot(103) is None, "MAX_GORSEL_MB asan gorsel reddedilir (getFile file_size)")
    s.dosya_boyutu_bildir = False
    foto(103, "buyuk"); check("\u00e7ok b\u00fcy\u00fck" in s.son_metin(103) and ot(103) is None, "file_size yoksa indirme sirasinda sinir")
    s.dosya_boyutu_bildir = True
    s.temizle(); s.belge(103, "sahte", "image/jpeg"); tur(); check("g\u00f6rsel de\u011fil" in s.son_metin(103) and ot(103) is None, "gorsel olmayan bayt reddedilir")
    s.temizle(); s.belge(103, "png1", "application/pdf"); tur(); check(not s.liste("sendMessage", 103) and ot(103) is None, "resim olmayan belge yok sayilir")

    # ================= admin komutlari =================
    yaz(103, "/kimim"); check("Telegram ID:</b> 103" in s.son_metin(103) and "ayse" in s.son_metin(103), "/kimim herkese acik")
    yaz(103, "/durum"); check("DURUM" not in s.son_metin(103) and "Lead ID" in s.son_metin(103), "admin olmayan /durum alamaz")
    yaz(999, "/yardim"); check("ADMIN KOMUTLARI" in s.son_metin(999) and "/engel_kaldir" in s.son_metin(999), "/yardim")
    yaz(999, "/durum"); m = s.son_metin(999)
    check("<b>DURUM</b>" in m and "Kay\u0131t:</b> 7" in m and "onayl\u0131 1, engelli 2" in m and "Bak\u0131m:</b> KAPALI" in m and "Gyazo:</b> A\u00c7IK" in m and "Son hata:" in m, "/durum: sayilar, bakim, gyazo, son hata")
    yaz(999, "/istatistik"); m = s.son_metin(999); check("\u0130STAT\u0130ST\u0130K" in m and "PP: 2" in m and "Kay\u0131t saya\u00e7l\u0131 kullan\u0131c\u0131:</b> 1" in m, "/istatistik")
    yaz(999, "/bakim_ac"); check(db.bakim_modu(conn) and "Bak\u0131m modu a\u00e7\u0131ld\u0131" in s.son_metin(999), "/bakim_ac")
    yaz(103, "selam"); check("bak\u0131m modunda" in s.son_metin(103), "bakimda uye yanit alir")
    yaz(999, "/bakim_kapat"); check(not db.bakim_modu(conn), "/bakim_kapat")
    yaz(999, "/gyazo_bakim_ac"); check(db.gyazo_bakim(conn) and "A\u00c7ILDI" in s.son_metin(999), "/gyazo_bakim_ac")
    yaz(999, "/gyazo_bakim_kapat"); check(not db.gyazo_bakim(conn) and "KAPATILDI" in s.son_metin(999), "/gyazo_bakim_kapat")
    yaz(999, "/engelle"); check("Kullan\u0131m:</b> /engelle ID sebep" in s.son_metin(999), "/engelle kullanim")
    yaz(999, "/engelle 103 spam gonderdi"); kb = s.klavye_verileri(999)
    check("Onay gerekli" in s.son_metin(999) and "spam gonderdi" in s.son_metin(999) and kb == ["admin_engelle_onay", "admin_engelle_vazgec"], "/engelle -> inline Onayla/Vazgec")
    bas(999, "admin_engelle_vazgec"); check("iptal edildi" in s.son_metin(999) and not db.tg_al(conn, "103")["engelli"], "Vazgec -> engel yok")
    bas(999, "admin_engelle_onay"); check("Bekleyen onay yok" in s.son_metin(999), "bekleyen onay yokken Onayla")
    yaz(999, "/engelle 103 spam"); bas(103, "admin_engelle_onay"); check(not db.tg_al(conn, "103")["engelli"], "admin olmayan admin butonuna basamaz")
    bas(999, "admin_engelle_onay"); u = db.tg_al(conn, "103")
    check(u["engelli"] == 1 and u["engel_sebep"] == "spam" and u["engelleyen"] == "admin:999" and "engellendi: 103" in s.son_metin(999), "Onayla -> tg_engelle (kim=admin:999)")
    yaz(103, "selam"); check(not s.liste("sendMessage", 103) and s.liste("deleteMessage", 103), "engelli uye yanit alamaz")
    yaz(999, "/engel_kaldir 103"); u = db.tg_al(conn, "103")
    check(u["engelli"] == 0 and u["onayli"] == 1 and "Engel kald\u0131rma tamamland\u0131" in s.son_metin(999) and "Engel kayd\u0131 silindi" in s.son_metin(999), "/engel_kaldir -> engel kalkti, onay durdu")
    check(s.liste("sendMessage", 103) and "Engeliniz kald\u0131r\u0131ld\u0131" in s.son_metin(103) and "bildirim g\u00f6nderildi" in s.son_metin(999), "uyeye Send-EngelKaldirildiBildirim")
    yaz(999, "/engel_kaldir 404404"); check("bulunamad\u0131" in s.son_metin(999) and "g\u00f6nderilemedi" in s.son_metin(999), "/engel_kaldir: bildirim gonderilemedi durumu (403)")
    yaz(999, "/son_hatalar"); m = s.son_metin(999)
    check("SON LOG" in m and "[20" in m and "Admin komutu: /son_hatalar" in m and "Engel kaldirma bildirimi" in m and m.count("\n") <= 27, "/son_hatalar son 25 log satirini verir")
    yaz(999, "/kimim"); check("Telegram ID:</b> 999" in s.son_metin(999), "/kimim admin")
    db.oturum_yaz(conn, "999", {"adim": "proje"}); yaz(999, "/iptal"); check(ot(999) is None and "temizlendi" in s.son_metin(999), "/iptal kendi oturumunu siler")
    check(conn.execute("SELECT COUNT(*) FROM denetim WHERE islem IN ('bakim_ac','bakim_kapat','gyazo_bakim_ac','gyazo_bakim_kapat','bot_engelle','bot_engel_kaldir') AND kullanici='admin:999'").fetchone()[0] == 7, "admin islemleri denetimde (4 bakim + 1 engel + 2 engel kaldirma)")

    # ================= nabiz / offset / log =================
    nabiz = db.ayar_al(conn, "bot_nabiz"); check(nabiz and nabiz[:10] == db.simdi()[:10], "bot_nabiz yaziliyor")
    ofs = int(db.ayar_al(conn, "telegram_offset"))
    check(ofs == s.sonraki_update and all(g["update_id"] < ofs for g in s.kuyruk), "telegram_offset = son update + 1 (kuyruktaki her sey islenmis)")
    s.temizle(); tur(); check(int(db.ayar_al(conn, "telegram_offset")) == ofs and s.liste("getUpdates")[0]["offset"] == ofs and s.liste("getUpdates")[0]["timeout"] == 25, "bos tur: offset korunur, getUpdates offset+timeout 25")
    s.mesaj(103, "/x"); b2 = C.Bot(ayar); b2.uyku = lambda sn: None; n = b2.tur()
    check(n == 1 and int(db.ayar_al(conn, "telegram_offset")) == ofs + 1, "yeni surec kaldigi offset'ten devam eder")
    b.log = C.log_kur(ayar)
    with open(os.path.join(ayar["LOG"], "bot.log"), encoding="utf-8") as f:
        log = f.read()
    check(log.startswith("[20") and "] Kaydedildi -> [OF] [HGST]" in log and "Sifre dogru" in log, "bot.log '[tarih] mesaj' bicimi")
    s.getupdates_hatasi = (409, "Conflict: terminated by other getUpdates request")
    s.temizle(); n = tur()
    check(n == 0 and "409" in (db.ayar_al(conn, "son_hata") or "") and "409 CONFLICT" in open(os.path.join(ayar["LOG"], "bot.log"), encoding="utf-8").read(), "409 Conflict loglanir, son_hata, dongu devam eder")
    s.hata_429 = 1; yaz(103, "/x")
    check(s.denemeler.get("sendMessage") == 2 and "Lead ID" in s.son_metin(103), "429 -> retry_after bekleyip tekrar gonderir")
    bb = kanit.bot.calistir(ayar, bir_tur=True); check(isinstance(bb, C.Bot), "calistir(ayar, bir_tur=True) tek tur isler ve doner")

    # ================= oturum temizligi (24 saat) =================
    db.oturum_yaz(conn, "777", {"adim": "proje"}); db.oturum_yaz(conn, "778", {"adim": "proje"})
    conn.execute("UPDATE bot_oturumlari SET guncelleme='2020-01-01 00:00:00' WHERE tg_id='777'")
    check(b.bakim_isleri() == 0 and ot(777) is not None, "temizlik saatte bir (henuz degil)")
    b.son_temizlik = 0; tur()
    check(ot(777) is None and ot(778) is not None, "24 saatten eski oturum temizlendi, yenisi durdu")
    db.oturum_sil(conn, "778")

    # ================= patlama korumasi =================
    s.temizle(); s.foto(103, "foto8"); s.foto(103, "foto9"); tur()
    m = s.metinler(103)
    check(sum(1 for x in m if "G\u00f6rsel al\u0131nd\u0131" in x) == 1 and sum(1 for x in m if "Bot kapal\u0131yd\u0131" in x) == 1 and ot(103)["fileId"] == "foto9", "ayni pakette 2 foto -> yalniz sonuncusu + tek uyari")
    bas(103, "iptal_basa")
    s.temizle(); s.foto(104, "foto8"); s.foto(104, "foto9"); tur()
    check(not any("Bot kapal\u0131yd\u0131" in x for x in s.metinler(104)) and db.tg_al(conn, "104")["engelli"] == 1, "onaysiz uyeye patlama uyarisi yok (yetkisiz gorsel -> engel)")

    s.kapat()
    print(f"\nBOT TESTLERI GECTI ({ok})")


if __name__ == "__main__":
    calistir()
else:
    def test_bot():
        calistir()

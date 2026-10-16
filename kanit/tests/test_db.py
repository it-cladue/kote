# -*- coding: utf-8 -*-
"""Temel: sema, ortak yazma islemleri, arsiv dokunulmazligi, yorum/bildirim, tg kullanicilari, oturumlar.
Calistirma: cd kanit && python3 -m pytest -q tests  (ya da python3 tests/test_db.py)"""
import os, sys, json, tempfile, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from kanit import db, normalle as N, gorsel

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
    td = tempfile.mkdtemp()
    conn = db.baglan(os.path.join(td, "t.db"))
    check(conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal", "WAL")
    check([p["kod"] for p in db.projeler(conn)] == ["PP", "PA", "OF", "HI", "VI", "GA", "BETA"], "proje tohumu")
    check(len(db.kategoriler(conn)) == 6 and db.kategori_bul(conn, "ARK")["akis"] == "ark_ana", "kategori tohumu + etiketle bulma")
    # normalizasyon
    check(N.normalle(" 00123 ") == "123" and N.normalle("HTTPS://www.Gyazo.com/abc/?x=1") == "gyazo.com/abc" and N.kucuk("IŞIK İzmir") == "ışık izmir" and N.buyuk("ışık izmir") == "IŞIK İZMİR", "normalle / kucuk / buyuk")
    # kullanicilar + yetki
    db.kullanici_ekle(conn, "patron", "admin", "Gizli1234", olusturan="kurulum")
    db.kullanici_ekle(conn, "ofadmin", "OF:oku,kt", "Gizli1234", olusturan="patron")
    db.kullanici_ekle(conn, "paadmin", "PA", "Gizli1234", olusturan="patron")
    check(db.kullanici_dogrula(conn, "Patron", "Gizli1234", "1.1.1.1")[0]["kullanici_adi"] == "patron", "giris")
    for _ in range(5):
        db.kullanici_dogrula(conn, "ofadmin", "yanlis", "9.9.9.9")
    check(db.kullanici_dogrula(conn, "ofadmin", "Gizli1234", "9.9.9.9")[0] is None and db.kullanici_dogrula(conn, "ofadmin", "Gizli1234", "9.9.9.8")[0] is not None, "kilit adrese bagli")
    # kayit ekle -> arsiv + denetim + bildirim
    k = db.kayit_ekle(conn, {"proje": "of", "kategori": "ark", "personel": " 215 ", "uye_id": "0495682791", "ana_uye_id": "123", "link": "https://gyazo.com/" + "a" * 32,
                             "ekleyen_tg_id": "111", "ekleyen_ad": "ali", "ekleyen_guven": "kesin"}, kim="bot")
    check(k["proje"] == "OF" and k["kategori"] == "ARK" and k["kategori_kod"] == "ark" and k["personel"] == "215" and k["uye_norm"] == "495682791" and k["link_turu"] == "gyazo" and k["surum"] == 1, "kayit_ekle alanlari + norm + link turu")
    ar = db.arsiv_kayitlari(conn, k["id"]); check(len(ar) == 1 and ar[0]["olay"] == "olustur" and ar[0]["veri"]["personel"] == "215", "arsiv olustur")
    b = db.bildirimler(conn, "ofadmin"); check(len(b) == 1 and b[0]["tur"] == "yeni_kayit" and db.okunmamis_bildirim_sayisi(conn, "paadmin") == 0 and db.okunmamis_bildirim_sayisi(conn, "patron") == 1, "yeni_kayit bildirimi yalniz OF okuyanlara")
    # arsiv dokunulmaz
    try:
        conn.execute("UPDATE arsiv SET veri='x'"); check(False, "arsiv update yasak")
    except sqlite3.DatabaseError as e:
        check("degistirilemez" in str(e), "arsiv update yasak")
    try:
        conn.execute("DELETE FROM arsiv"); check(False, "arsiv delete yasak")
    except sqlite3.DatabaseError as e:
        check("silinemez" in str(e), "arsiv delete yasak")
    # guncelle + iyimser kilit
    okk, k2, h = db.kayit_guncelle(conn, k["id"], {"personel": "216", "kategori": "dds", "aciklama": "not"}, "ofadmin", surum=1)
    check(okk and k2["personel"] == "216" and k2["kategori"] == "DDS" and k2["surum"] == 2 and k2["personel_norm"] == "216", "kayit_guncelle")
    okk, k3, h = db.kayit_guncelle(conn, k["id"], {"personel": "217"}, "paadmin", surum=1)
    check(not okk and h == "catisma" and k3["personel"] == "216", "eski surumle yazma -> catisma")
    okk, k3, h = db.kayit_guncelle(conn, k["id"], {"personel": "216"}, "ofadmin", surum=2); check(okk and k3["surum"] == 2, "ayni deger -> degisiklik yok, surum sabit")
    # kt
    k4 = db.kt_ayarla(conn, k["id"], True, "ofadmin"); check(k4["kt"] == 1 and k4["kt_kim"] == "ofadmin" and k4["surum"] == 3, "kt")
    k5 = db.kt_ayarla(conn, k["id"], True, "patron"); check(k5["surum"] == 3 and k5["kt_kim"] == "ofadmin", "kt idempotent")
    check(db.okunmamis_bildirim_sayisi(conn, "ofadmin") == 1, "duzenleyen kendi degisikligi icin bildirim almaz")
    # yorum
    y = db.yorum_ekle(conn, k["id"], "paadmin", "  kontrol ettim ")
    check(y["metin"] == "kontrol ettim" and db.kayit_al(conn, k["id"])["yorum_sayisi"] == 1, "yorum ekle + sayac")
    check(db.okunmamis_bildirim_sayisi(conn, "ofadmin") == 2, "kaydi onaylayan OF admini yorum bildirimi aldi")
    check(db.okunmamis_bildirim_sayisi(conn, "paadmin") == 0, "yorum yazan kendine bildirim almaz")
    check(db.okunmamis_yorumlar(conn, "ofadmin", [k["id"]]) == {k["id"]: 1} and db.okunmamis_yorumlar(conn, "paadmin", [k["id"]]) == {}, "okunmamis yorum sayisi")
    db.yorum_okundu(conn, "ofadmin", k["id"]); check(db.okunmamis_yorumlar(conn, "ofadmin", [k["id"]]) == {}, "yorum okundu")
    check(db.yorum_duzenle(conn, y["id"], "ofadmin", "x")[1] == "yalniz yazar duzeltebilir" and db.yorum_duzenle(conn, y["id"], "paadmin", "duzeltildi")[0], "yorum duzenleme kurali")
    check(db.yorum_sil(conn, y["id"], "ofadmin")[0] is False and db.yorum_sil(conn, y["id"], "patron", admin=True)[0] and db.kayit_al(conn, k["id"])["yorum_sayisi"] == 0, "yorum silme kurali")
    # sil / geri al
    s = db.kayit_sil(conn, k["id"], "patron", "mukerrer"); check(s["silindi"] == 1 and s["silme_nedeni"] == "mukerrer", "sil")
    g = db.kayit_geri_al(conn, k["id"], "patron"); check(g["silindi"] == 0 and g["surum"] == s["surum"] + 1, "geri al")
    ar = db.arsiv_kayitlari(conn, k["id"]); check([a["olay"] for a in ar] == ["olustur", "degistir", "kt", "sil", "geri_al"], f"arsiv olay zinciri {[a['olay'] for a in ar]}")
    gec = db.kayit_gecmisi(conn, k["id"]); check(gec[0]["islem"] == "geri_al" and any(x["islem"] == "duzenle" and x["eski"]["personel"] == "215" for x in gec), "gecmis (denetim)")
    # bildirim okundu
    db.bildirim_okundu(conn, "ofadmin"); check(db.okunmamis_bildirim_sayisi(conn, "ofadmin") == 0, "tumunu okundu")
    # excel'den aktarim: bildirim yok
    k6 = db.kayit_ekle(conn, {"proje": "PA", "kategori": "HGST", "personel": "5", "eski_sayfa": "PA", "eski_satir": 77, "eski_anahtar": "x|y", "kt": 1, "kt_kaynak": "excel"}, kim="aktarim", kaynak="excel")
    check(k6["kt"] == 1 and k6["kt_kaynak"] == "excel" and k6["eski_satir"] == 77 and db.okunmamis_bildirim_sayisi(conn, "paadmin") == 0 and db.arsiv_kayitlari(conn, k6["id"])[0]["olay"] == "ice_aktar", "excel aktarimi: bildirimsiz, arsiv ice_aktar")
    # sayaclar
    sy = db.proje_sayaclari(conn); check(sy["OF"]["onayli"] == 1 and sy["PA"]["onayli"] == 1 and sy["OF"]["toplam"] == 1, "proje sayaclari")
    # tg kullanicilari
    db.tg_guncelle(conn, 555, username="ayse", first_name="Ayse", last_seen=db.simdi())
    check(db.tg_deneme(conn, 555) == 1 and db.tg_deneme(conn, 555) == 2, "deneme sayaci")
    db.tg_onayla(conn, 555, "ayse", kim="patron"); u = db.tg_al(conn, "555"); check(u["onayli"] == 1 and u["deneme"] == 0, "tg onayla")
    db.tg_engelle(conn, 555, "spam", kim="patron"); check(db.tg_al(conn, "555")["engelli"] == 1, "tg engelle")
    check(db.tg_engel_kaldir(conn, 555, kim="patron") is True and db.tg_al(conn, "555")["engelli"] == 0 and db.tg_al(conn, "555")["onayli"] == 1, "engel kaldir onayi korur")
    r = db.tg_tam_sifirla(conn, 555, kim="patron"); check(r == {"engel_silindi": False, "onay_silindi": True} and db.tg_al(conn, "555")["onayli"] == 0, "tam sifirla")
    db.tg_kayit_sayaci(conn, 555, "ayse", "Ayse", "pp", "cvpsz", "CVPS"); db.tg_kayit_sayaci(conn, 555, "ayse", "Ayse", "pp", "ark", "ARK")
    u = db.tg_al(conn, "555"); check(u["kayit_sayisi"] == 2 and u["proje_sayilari"] == {"PP": 2} and u["kategori_sayilari"] == {"CVPSZ": 1, "ARK": 1}, "kayit sayaclari")
    # oturum
    db.oturum_yaz(conn, 555, {"adim": "kategori", "proje": "pa"}); check(db.oturum_al(conn, 555)["adim"] == "kategori" and db.oturumlar(conn)[0]["id"] == "555", "oturum yaz/oku")
    db.oturum_sil(conn, 555); check(db.oturum_al(conn, 555) is None, "oturum sil")
    # kategori yonetimi
    check(db.kategori_kaydet(conn, "Bonus", "BONUS", "tek_uye", "patron") is None and db.kategori_bul(conn, "bonus")["etiket"] == "BONUS", "kategori ekle")
    check(db.kategori_kaydet(conn, "x", "X", "bozuk") is not None and db.kategori_sil(conn, "bonus", "patron") and not db.kategori_bul(conn, "bonus")["aktif"], "kategori hata + pasife alma")
    # gorsel deposu
    gk = os.path.join(td, "gorseller"); os.makedirs(gk)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    rel = gorsel.kaydet(gk, "of", png, gorsel.dosya_adi("ARK", "2026-10-16 10:00:00", "215", "4956", "", "Sessiz", ".png"))
    check(rel == "OF/ARK_2026-10-16_10-00-00_215_4956_Sessiz.png" and gorsel.tam_yol(gk, rel) and gorsel.tam_yol(gk, "../t.db") is None, f"gorsel kaydet + yol sinirlama ({rel})")
    rel2 = gorsel.kaydet(gk, "of", png, "ARK_2026-10-16_10-00-00_215_4956_Sessiz.png"); check(rel2.endswith("-2.png"), "ayni ad -> -2")
    check(gorsel.link_turu_ve_kimlik("http://evil/x/gyazo.com/" + "b" * 32)[0] != "gyazo" and gorsel.link_turu_ve_kimlik("https://i.gyazo.com/" + "b" * 32 + ".png") == ("gyazo", "b" * 32) and gorsel.link_turu_ve_kimlik("C:\\x\\y.jpg")[0] == "dosya" and gorsel.link_turu_ve_kimlik("666666")[0] == "metin", "link turu")
    # yedek
    y = db.yedekle(conn, os.path.join(td, "yedek", "t.db")); c2 = sqlite3.connect(y); check(c2.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] == 2, "yedek")
    print(f"\nTEMEL TESTLERI GECTI ({ok})")


if __name__ == "__main__":
    calistir()
else:
    def test_temel():
        calistir()

# -*- coding: utf-8 -*-
"""Admin komutlari (yalniz ayar ADMIN_IDS icindeki Telegram ID'leri; /admin sifre girisi YOK).

/kimim herkese acik. Digerleri: /yardim /durum /istatistik /bakim_ac /bakim_kapat /gyazo_bakim_ac /gyazo_bakim_kapat
/engelle ID sebep (inline Onayla/Vazgec) /engel_kaldir ID (uyeye bildirim) /son_hatalar /iptal.
Kategori, kullanici listesi, yedek gibi islerin hepsi web panelinde.
"""
import os
from .. import db
from .telegram_api import html_kacir as H, klavye

E_ONAY, E_IPTAL, E_UYARI, E_YASAK, E_BAKIM, E_BILGI = "\u2705", "\u274c", "\u26a0", "\u26d4", "\U0001f6e0", "\u2139"
KOMUTLAR = ("/yardim", "/yardim_admin", "/durum", "/istatistik", "/bakim_ac", "/bakim_kapat", "/gyazo_bakim_ac", "/gyazo_bakim_kapat",
            "/engelle", "/engel_kaldir", "/son_hatalar", "/iptal")
M_ENGEL_KALDIRILDI = E_ONAY + " <b>Engeliniz kald\u0131r\u0131ld\u0131.</b>\n\n\u015eifreyi tekrar yazarak sisteme giri\u015f yapabilirsiniz."
M_ENGELLE_KULLANIM = "<b>Kullan\u0131m:</b> /engelle ID sebep\n\n<b>\u00d6rnek:</b> /engelle 123456789 spam"
M_ENGEL_KALDIR_KULLANIM = "<b>Kullan\u0131m:</b> /engel_kaldir ID\n\n<b>\u00d6rnek:</b> /engel_kaldir 123456789"


def yardim():
    return ("<b>ADMIN KOMUTLARI</b>\n--------------------\n"
            "/durum - Bot ve veritaban\u0131 durumu\n"
            "/istatistik - Kay\u0131t ve kullan\u0131c\u0131 \u00f6zeti\n"
            "/engelle ID sebep - Kullan\u0131c\u0131 engelle (onay ister)\n"
            "/engel_kaldir ID - Engeli kald\u0131r, deneme ve oturumu s\u0131f\u0131rla, \u00fcyeye haber ver\n"
            "/bakim_ac - Bak\u0131m modunu a\u00e7\n"
            "/bakim_kapat - Bak\u0131m modunu kapat\n"
            "/gyazo_bakim_ac - Gyazo se\u00e7ene\u011fi 'sunucu bak\u0131mda' desin (g\u00f6rsel dosyaya kaydedilir)\n"
            "/gyazo_bakim_kapat - Gyazo se\u00e7ene\u011fini yeniden a\u00e7\n"
            "/son_hatalar - Son log sat\u0131rlar\u0131\n"
            "/iptal - Kendi oturumunu temizle\n"
            "/kimim - Telegram ID'ni g\u00f6ster\n\n"
            + E_BILGI + " Kategori, \u00fcye listesi, oturumlar, yedek ve Excel \u00e7\u0131kt\u0131s\u0131 web panelinde.")


def _sayilar(conn):
    tg = db.tg_listesi(conn)
    sayac = db.proje_sayaclari(conn)
    return {"uye": len(tg), "onayli": sum(1 for u in tg if u and u.get("onayli")), "engelli": sum(1 for u in tg if u and u.get("engelli")),
            "sayacli": sum(1 for u in tg if u and u.get("kayit_sayisi")), "oturum": len(db.oturumlar(conn)),
            "kayit": sum(s["toplam"] for s in sayac.values()), "silinen": sum(s["silinen"] for s in sayac.values()),
            "bekleyen": sum(s["bekleyen"] for s in sayac.values()), "kt": sum(s["onayli"] for s in sayac.values()), "projeler": sayac}


ACIK, KAPALI, GYAZO_BAKIMDA = "A\u00c7IK", "KAPALI", "BAKIMDA (g\u00f6rseller dosyaya kaydediliyor)"


def durum_metni(b):
    s = _sayilar(b.conn)
    bakim = ACIK if db.bakim_modu(b.conn) else KAPALI
    gyazo = GYAZO_BAKIMDA if db.gyazo_bakim(b.conn) else ACIK
    return ("<b>DURUM</b>\n--------------------\n"
            f"<b>Bot:</b> \u00e7al\u0131\u015f\u0131yor (ba\u015flang\u0131\u00e7 {H(b.baslangic)}, nab\u0131z {H(db.ayar_al(b.conn, 'bot_nabiz', '-'))})\n"
            f"<b>Veritaban\u0131:</b> {H(b.ayar.get('DB'))}\n"
            f"<b>Kay\u0131t:</b> {s['kayit']} (bekleyen {s['bekleyen']}, KT {s['kt']}, silinmi\u015f {s['silinen']})\n"
            f"<b>Telegram \u00fcyesi:</b> {s['uye']} (onayl\u0131 {s['onayli']}, engelli {s['engelli']})\n"
            f"<b>Aktif oturum:</b> {s['oturum']}\n"
            f"<b>Bak\u0131m:</b> {bakim}\n"
            f"<b>Gyazo:</b> {gyazo}\n"
            f"<b>G\u00f6rsel klas\u00f6r\u00fc:</b> {H(b.ayar.get('GORSELLER'))}\n"
            f"<b>Son hata:</b> {H(db.ayar_al(b.conn, 'son_hata', '') or '-')}")


def istatistik_metni(b):
    s = _sayilar(b.conn)
    bakim = ACIK if db.bakim_modu(b.conn) else KAPALI
    m = ("<b>\u0130STAT\u0130ST\u0130K</b>\n--------------------\n"
         f"<b>Kullan\u0131c\u0131 defteri:</b> {s['uye']}\n<b>Onayl\u0131:</b> {s['onayli']}\n<b>Engelli:</b> {s['engelli']}\n<b>Aktif oturum:</b> {s['oturum']}\n"
         f"<b>Kay\u0131t saya\u00e7l\u0131 kullan\u0131c\u0131:</b> {s['sayacli']}\n<b>Bak\u0131m modu:</b> {bakim}\n\n"
         f"<b>Kay\u0131tlar:</b> {s['kayit']} (bekleyen {s['bekleyen']}, KT {s['kt']}, silinmi\u015f {s['silinen']})\n")
    for p in sorted(s["projeler"]):
        x = s["projeler"][p]
        m += f"  {H(p)}: {x['toplam']} (bekleyen {x['bekleyen']}, KT {x['onayli']})\n"
    return m


def son_hatalar_metni(b, n=25):
    yol = os.path.join(b.ayar.get("LOG") or "", "bot.log")
    satirlar = []
    try:
        with open(yol, encoding="utf-8", errors="replace") as f:
            satirlar = f.read().splitlines()[-n:]
    except OSError:
        pass
    return "<b>SON LOG SATIRLARI</b>\n--------------------\n" + H("\n".join(satirlar) or "(log bo\u015f)")


def isle(b, chat_id, uid, u, metin):
    """-> True: komut islendi (mesaj akisa gitmez)."""
    t = metin.strip()
    if not t.startswith("/"):
        return False
    komut, _, arg = t.partition(" ")
    komut = komut.lower().split("@", 1)[0]
    arg = arg.strip()
    if komut == "/kimim":
        b.api.mesaj_gonder(chat_id, f"<b>Telegram ID:</b> {H(uid)}\n<b>Ad:</b> {H(u.get('username') or u.get('first_name') or '')}")
        return True
    if not b.admin_mi(uid) or komut not in KOMUTLAR:
        return False
    b.log.info("  Admin komutu: %s (%s)", komut, uid)
    kim = f"admin:{uid}"
    gonder = lambda m, kb=None: b.api.mesaj_gonder(chat_id, m, kb)
    if komut in ("/yardim", "/yardim_admin"):
        gonder(yardim())
    elif komut == "/durum":
        gonder(durum_metni(b))
    elif komut == "/istatistik":
        gonder(istatistik_metni(b))
    elif komut == "/bakim_ac":
        db.ayar_yaz(b.conn, "bakim_modu", "1")
        db.denetim_yaz(b.conn, kim, "bakim_ac")
        gonder(E_BAKIM + " Bak\u0131m modu a\u00e7\u0131ld\u0131.")
    elif komut == "/bakim_kapat":
        db.ayar_yaz(b.conn, "bakim_modu", "0")
        db.denetim_yaz(b.conn, kim, "bakim_kapat")
        gonder(E_ONAY + " Bak\u0131m modu kapat\u0131ld\u0131.")
    elif komut == "/gyazo_bakim_ac":
        db.ayar_yaz(b.conn, "gyazo_bakim", "1")
        db.denetim_yaz(b.conn, kim, "gyazo_bakim_ac")
        gonder(E_BAKIM + " Gyazo bak\u0131m modu A\u00c7ILDI. Kullan\u0131c\u0131lar Gyazo se\u00e7ince 'sunucu bak\u0131mda' uyar\u0131s\u0131 al\u0131r; g\u00f6rseller dosyaya kaydedilir.")
    elif komut == "/gyazo_bakim_kapat":
        db.ayar_yaz(b.conn, "gyazo_bakim", "0")
        db.denetim_yaz(b.conn, kim, "gyazo_bakim_kapat")
        gonder(E_ONAY + " Gyazo bak\u0131m modu KAPATILDI. Gyazo se\u00e7ene\u011fi yeniden \u00e7al\u0131\u015f\u0131yor.")
    elif komut == "/engelle":
        hedef, _, sebep = arg.partition(" ")
        hedef = hedef.strip()
        if not hedef.isdigit():
            gonder(M_ENGELLE_KULLANIM)
            return True
        sebep = sebep.strip() or "Admin engeli"
        b.bekleyen_onay[uid] = {"tur": "engelle", "id": hedef, "sebep": sebep}
        gonder(E_UYARI + f" <b>Onay gerekli</b>\nKullan\u0131c\u0131 engellensin mi?\nID: {H(hedef)}\nSebep: {H(sebep)}",
               klavye([[(E_ONAY + " Onayla", "admin_engelle_onay"), (E_IPTAL + " Vazge\u00e7", "admin_engelle_vazgec")]]))
    elif komut == "/engel_kaldir":
        hedef = arg.split(" ", 1)[0].strip()
        if not hedef.isdigit():
            gonder(M_ENGEL_KALDIR_KULLANIM)
            return True
        vardi = db.tg_engel_kaldir(b.conn, hedef, kim=kim)
        b.gecici_sil(hedef)
        bildirim = engel_kaldirildi_bildir(b, hedef)
        durum = "Engel kayd\u0131 silindi" if vardi else "Engel kayd\u0131 bulunamad\u0131; yine de deneme ve oturum s\u0131f\u0131rland\u0131"
        bd = "Kullan\u0131c\u0131ya bildirim g\u00f6nderildi" if bildirim else "Bildirim g\u00f6nderilemedi (kullan\u0131c\u0131 botu hi\u00e7 ba\u015flatmam\u0131\u015f veya botu engellemi\u015f olabilir)"
        gonder(E_ONAY + f" <b>Engel kald\u0131rma tamamland\u0131.</b>\nID: {H(hedef)}\nDurum: {durum}\nDeneme sayac\u0131: s\u0131f\u0131rland\u0131\nOturum: temizlendi\nBildirim: {bd}")
    elif komut == "/son_hatalar":
        gonder(son_hatalar_metni(b))
    elif komut == "/iptal":
        b.oturum_kaldir(uid)
        gonder(E_ONAY + " Oturumunuz temizlendi. Yeni bir g\u00f6rsel g\u00f6nderebilir veya Lead ID yazabilirsiniz.")
    return True


def engel_kaldirildi_bildir(b, hedef):
    """Send-EngelKaldirildiBildirim: uyeye 'engeliniz kaldirildi' mesaji. -> bool"""
    ok = b.api.mesaj_gonder(hedef, M_ENGEL_KALDIRILDI)
    if ok:
        b.log.info("  Engel kaldirma bildirimi gonderildi: %s", hedef)
    else:
        b.log.info("! Engel kaldirma bildirimi gonderilemedi: %s", hedef)
    return bool(ok)


def geri_arama(b, chat_id, uid, msg_id, data):
    """admin_* butonlari (yalniz admin)."""
    if not b.admin_mi(uid):
        return
    op = b.bekleyen_onay.get(uid)
    if data in ("admin_engelle_onay", "admin_engelle_vazgec"):
        if not op or op.get("tur") != "engelle":
            b.api.mesaj_duzenle(chat_id, msg_id, "Bekleyen onay yok.")
            return
        b.bekleyen_onay.pop(uid, None)
        if data == "admin_engelle_vazgec":
            b.api.mesaj_duzenle(chat_id, msg_id, "\u0130\u015flem iptal edildi.")
            return
        db.tg_engelle(b.conn, op["id"], sebep=op["sebep"], kim=f"admin:{uid}")
        b.gecici_sil(op["id"])
        b.log.info("  Engellendi: %s - %s (admin %s)", op["id"], op["sebep"], uid)
        b.api.mesaj_duzenle(chat_id, msg_id, E_YASAK + f" Kullan\u0131c\u0131 engellendi: {H(op['id'])}\nSebep: {H(op['sebep'])}")

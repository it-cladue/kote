# -*- coding: utf-8 -*-
"""Uye akislari: sifre kapisi, gorsel akisi, yazili (Lead ID) akisi, buton (callback) isleme.

telegram/telebot.ps1 Process-Message / Process-Callback'in birebir portu; durum SQLite'ta (db.oturum_*).
Oturum anahtarlari botun oturumlar.json'u ile ayni (panel bunlari okur):
  adim, girisTipi (resim|yazili), kayitModu (gyazo|dosya|None), fileId, fotoSha, fotoTarih, leadId, msgId,
  proje, kategori, personel, uyeid, anaid, tip, gorselDosya (kaydedilmis goreli yol; tekrar denemede yeniden yazilmaz)
Adimlar: kayit_secim | gyazo_bakim | lead_onay | proje | kategori | personel | uyeid | anaid | tip | ozet
"""
import hashlib
import os
import time
from datetime import datetime
from .. import db, gorsel
from . import gyazo as G
from .telegram_api import html_kacir as H, klavye, GorselBuyuk

YAZI_ADIMLARI = ("personel", "uyeid", "anaid", "lead_onay")
KOPYA_SURESI_SN = 300  # ayni gorsel (sha256) ayni uyeden 5 dk icinde tekrar gelirse yok sayilir

# ---- emoji ----
E_GORSEL, E_LINK, E_DISK, E_IPTAL, E_ONAY, E_KALEM, E_GERI = "\U0001f5bc", "\U0001f517", "\U0001f4be", "\u274c", "\u2705", "\u270f", "\u2b05"
E_BASA, E_KLASOR, E_LISTE, E_TEKRAR, E_BUYUTEC, E_RAPTIYE, E_PARMAK = "\U0001f504", "\U0001f4c1", "\U0001f4cb", "\U0001f501", "\U0001f50d", "\U0001f4cc", "\U0001f449"
E_BILGI, E_SAAT, E_UYARI, E_SORU, E_KAMERA, E_YASAK, E_BAKIM = "\u2139", "\u23f3", "\u26a0", "\u2753", "\U0001f4f7", "\u26d4", "\U0001f6e0"

# ---- metinler (botun mesajlari, Turkce) ----
M_SIFRE = "<b>Merhaba!</b>\n\nDevam etmek i\u00e7in l\u00fctfen \u015fifreyi yaz\u0131n."
M_HOSGELDIN = "<b>Ho\u015f geldiniz!</b>\n\nBa\u015flamak i\u00e7in bir <b>g\u00f6rsel</b> g\u00f6nderin veya <b>Lead ID</b>'yi yaz\u0131n; ard\u0131ndan bot sizi ad\u0131m ad\u0131m y\u00f6nlendirecek."
M_YANLIS_SIFRE = E_UYARI + " Yanl\u0131\u015f \u015fifre! {kalan} deneme hakk\u0131n\u0131z kald\u0131."
M_ENGELLENDI = E_YASAK + " Eri\u015fim engellendi."
M_YETKISIZ_GORSEL = E_YASAK + " Bu bota yazma yetkiniz yok."
M_BAKIM = E_BAKIM + " <b>Bot \u015fu anda bak\u0131m modunda.</b>\nL\u00fctfen biraz sonra tekrar deneyin."
M_BASLA = E_KAMERA + " Ba\u015flamak i\u00e7in bir g\u00f6rsel g\u00f6nderin ya da Lead ID'yi yaz\u0131n."
M_GORSEL_ALINDI = (E_GORSEL + " <b>G\u00f6rsel al\u0131nd\u0131.</b>\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Ne yapmak istersiniz?</b>\n\n"
                   + E_LINK + " <b>Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr</b>: g\u00f6rsel Gyazo'ya y\u00fcklenir, kayda link yaz\u0131l\u0131r.\n"
                   + E_DISK + " <b>G\u00f6rseli direkt kaydet</b>: g\u00f6rsel, girdi\u011finiz bilgilerle (kategori, tarih, ID'ler) adland\u0131r\u0131l\u0131p sunucuya kaydedilir.")
M_GORSEL_ALINDI_BAKIM = (E_GORSEL + " <b>G\u00f6rsel al\u0131nd\u0131.</b>\n\n" + E_UYARI + " <b>Gyazo sunucusu \u015fu anda bak\u0131mda.</b>\nGyazo taraf\u0131nda sorun oldu\u011fu i\u00e7in link olu\u015fturulam\u0131yor.\n\n"
                         + E_DISK + " <b>G\u00f6rseli direkt kaydet</b> se\u00e7ene\u011fiyle devam edebilirsiniz; g\u00f6rsel, girdi\u011finiz bilgilerle adland\u0131r\u0131l\u0131p kaydedilir.")
M_GYAZO_BAKIM = (E_UYARI + " <b>Gyazo sunucusu \u015fu anda bak\u0131mda.</b>\nGyazo taraf\u0131nda sorun oldu\u011fu i\u00e7in link olu\u015fturulam\u0131yor.\n\n"
                 + E_DISK + " <b>G\u00f6rseli direkt kaydet</b> se\u00e7ene\u011fiyle devam edebilirsiniz; g\u00f6rsel, girdi\u011finiz bilgilerle adland\u0131r\u0131l\u0131p kaydedilir.")
M_GYAZO_BAKIM_ONAY = E_UYARI + " <b>Gyazo sunucusu \u015fu anda bak\u0131mda.</b>\nLink olu\u015fturulam\u0131yor. G\u00f6rseli direkt kaydetmek ister misiniz? (bilgileriniz korunur)"
M_GYAZO_SECILDI = E_LINK + " <b>Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr\u00fclecek.</b>\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Projeyi se\u00e7in.</b>"
M_DOSYA_SECILDI = E_DISK + " <b>G\u00f6rsel dosyaya kaydedilecek.</b>\nDosya ad\u0131: kategori + tarih + girdi\u011finiz bilgiler.\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Projeyi se\u00e7in.</b>"
M_PROJE_SEC = "<b>Bilgileriniz al\u0131nd\u0131.</b>\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Projeyi se\u00e7in.</b>"
M_KATEGORI_SEC = "<b>Proje:</b> {proje}\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Kategoriyi se\u00e7in.</b>"
M_KATEGORI_PASIF = E_UYARI + " Bu kategori art\u0131k aktif de\u011fil. L\u00fctfen kategori se\u00e7imine d\u00f6n\u00fcn."
M_PROJE_PASIF = E_UYARI + " Bu proje art\u0131k aktif de\u011fil. L\u00fctfen projeyi yeniden se\u00e7in."
M_LEAD_SORU = (E_SORU + " <b>Lead ID mi gireceksiniz?</b>\n\n<b>Girdi\u011finiz metin:</b> {metin}\n\n"
               + E_ONAY + " <b>Onayla</b> ile devam edin, " + E_KALEM + " <b>De\u011fi\u015ftir</b> ile yeniden yaz\u0131n, " + E_IPTAL + " <b>\u00c7\u0131k</b> ile vazge\u00e7in.")
M_LEAD_ALINDI = E_ONAY + " <b>Lead ID al\u0131nd\u0131:</b> {lead}\n\n<b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN:</b>\n<b>-> Projeyi se\u00e7in.</b>"
M_LEAD_DEGISTIR = E_KALEM + " <b>Yeni Lead ID'yi yaz\u0131n.</b>\n\n<b>\u015eu anki Lead ID:</b> {lead}\n\nYeni metni yazd\u0131\u011f\u0131n\u0131zda tekrar onay ekran\u0131 gelecek."
M_LEAD_IPTAL = E_IPTAL + " \u0130ptal edildi. Yeni bir Lead ID yazabilir veya g\u00f6rsel g\u00f6nderebilirsiniz."
M_IPTAL_BASA = E_IPTAL + " \u0130ptal edildi. Yeni bir g\u00f6rsel g\u00f6nderebilir veya Lead ID yazabilirsiniz."
M_IPTAL_NEREYE = "Nereye d\u00f6nmek istersiniz?"
M_KAYDEDILIYOR = E_SAAT + " <b>G\u00f6rsel kaydediliyor...</b>"
M_YUKLENIYOR = E_SAAT + " <b>Y\u00fckleniyor...</b>"
M_KAYDEDILEMEDI = E_UYARI + " <b>G\u00f6rsel kaydedilemedi.</b>\nNe yapmak istersiniz?"
M_YUKLENEMEDI = E_UYARI + " <b>G\u00f6rsel y\u00fcklenemedi.</b>\nNe yapmak istersiniz?"
M_KAYIT_HATASI = E_UYARI + " <b>Kay\u0131t yaz\u0131lamad\u0131.</b>\nNe yapmak istersiniz?"
M_BASARILI = E_ONAY + " <b>Kan\u0131t\u0131n\u0131z eklendi, te\u015fekk\u00fcrler!</b>"
M_BASARILI_DOSYA = E_ONAY + " <b>Kan\u0131t\u0131n\u0131z eklendi, te\u015fekk\u00fcrler!</b>\n" + E_KLASOR + " Dosya: <code>{dosya}</code>"
M_YENI_KAYIT = "\n\n" + E_KAMERA + " Yeni kay\u0131t i\u00e7in g\u00f6rsel g\u00f6nderin ya da Lead ID yaz\u0131n."
M_KOPYA = E_BILGI + " Bu g\u00f6rsel az \u00f6nce kaydedildi; yeniden kaydedilmedi.\nYeni kay\u0131t i\u00e7in ba\u015fka bir g\u00f6rsel g\u00f6nderin."
M_GORSEL_BUYUK = E_UYARI + " G\u00f6rsel \u00e7ok b\u00fcy\u00fck (en fazla {mb} MB). L\u00fctfen daha k\u00fc\u00e7\u00fck bir g\u00f6rsel g\u00f6nderin."
M_GORSEL_DEGIL = E_UYARI + " G\u00f6nderilen dosya bir g\u00f6rsel de\u011fil. L\u00fctfen foto\u011fraf ya da resim dosyas\u0131 g\u00f6nderin."
M_GORSEL_ALINAMADI = E_UYARI + " G\u00f6rsel Telegram'dan al\u0131namad\u0131. L\u00fctfen yeniden g\u00f6nderin."
M_PATLAMA = E_UYARI + " Bot kapal\u0131yd\u0131, l\u00fctfen g\u00f6rselleri tek tek yeniden g\u00f6nderin.\nYaln\u0131zca en son g\u00f6nderdi\u011finiz g\u00f6rsel i\u015fleme al\u0131nd\u0131."
M_PERSONEL_BASLIK = "Personel kodunuzu yaz\u0131n"
M_PERSONEL_ACIKLAMA = "\u00d6rnek: 12345. Mesaj\u0131 yazd\u0131ktan sonra bot bu mesaj\u0131 temizler ve sonraki ad\u0131ma ge\u00e7er."
M_ID_ACIKLAMA = "L\u00fctfen sadece istenen ID bilgisini yaz\u0131n."
M_ANA_BASLIK = "Ana \u00dcye ID'sini yaz\u0131n"
M_ANA_ACIKLAMA = "Arkada\u015f ID al\u0131nd\u0131. \u015eimdi ana \u00fcye ID bilgisini yaz\u0131n."
M_TIP_BASLIK = "Sessiz / Telesekreter t\u00fcr\u00fcn\u00fc se\u00e7in"
M_TIP_ACIKLAMA = "A\u015fa\u011f\u0131daki butonlardan uygun t\u00fcr\u00fc se\u00e7in."
TIPLER = {"sessiz": "Sessiz", "telesekreter": "Telesekreter"}


# ==================== klavyeler ====================
def kb_proje(conn):
    """db.projeler -> 3'lu satirlar (emoji + kod); botun KB-Proje duzeni (3+3+1)."""
    satirlar, satir = [], []
    for p in db.projeler(conn):
        satir.append((f"{p.get('emoji') or ''} {p['kod']}".strip(), "proje_" + p["kod"].lower()))
        if len(satir) == 3:
            satirlar.append(satir)
            satir = []
    if satir:
        satirlar.append(satir)
    return klavye(satirlar)


def kb_kategori(conn):
    satirlar, satir = [], []
    for k in db.kategoriler(conn):
        satir.append((k["etiket"], "kat_" + k["kod"]))
        if len(satir) == 3:
            satirlar.append(satir)
            satir = []
    if satir:
        satirlar.append(satir)
    satirlar.append([(E_GERI + " Geri", "geri_proje")])
    return klavye(satirlar)


def kb_kayit_secim():
    return klavye([[(E_LINK + " Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr", "kayit_gyazo")], [(E_DISK + " G\u00f6rseli direkt kaydet", "kayit_dosya")], [(E_IPTAL + " \u0130ptal", "iptal_basa")]])


def kb_gyazo_bakim():
    return klavye([[(E_DISK + " G\u00f6rseli direkt kaydet", "kayit_dosya")], [(E_IPTAL + " \u0130ptal", "iptal_basa")]])


def kb_sessiz():
    return klavye([[("Sessiz", "tip_sessiz"), ("Telesekreter", "tip_telesekreter")], [(E_GERI + " Geri", "geri_uyeid")]])


def kb_onay():
    return klavye([[(E_ONAY + " Onayla", "onayla"), (E_IPTAL + " \u0130ptal", "iptal")]])


def kb_lead_onay():
    return klavye([[(E_ONAY + " Onayla", "lead_onay"), (E_KALEM + " De\u011fi\u015ftir", "lead_degistir")], [(E_IPTAL + " \u00c7\u0131k", "lead_iptal")]])


def kb_iptal():
    return klavye([[(E_BASA + " Ba\u015fa D\u00f6n", "iptal_basa")], [(E_KLASOR + " Proje Se\u00e7", "iptal_proje")],
                   [(E_LISTE + " Kategori Se\u00e7", "iptal_kategori")], [(E_KALEM + " Bilgileri D\u00fczelt", "iptal_bilgi")]])


def kb_hata():
    return klavye([[(E_TEKRAR + " Tekrar Dene", "onayla")], [(E_BASA + " Ba\u015fa D\u00f6n", "iptal_basa")]])


def kb_geri(callback):
    return klavye([[(E_GERI + " Geri", callback)]])


# ==================== metin uretimi ====================
def kategori_etiket(conn, kod):
    k = db.kategori_bul(conn, kod) if kod else None
    return k["etiket"] if k else (kod or "").upper()


def kategori_akis(conn, kod):
    k = db.kategori_bul(conn, kod) if kod else None
    return k["akis"] if k else "tek_uye"


def adim_mesaji(conn, ot, istenen, aciklama):
    """Get-AdimMesaji: SECILENLER + SIMDI SIZDEN BEKLENEN"""
    proje = (ot.get("proje") or "-").upper()
    kat = kategori_etiket(conn, ot.get("kategori")) if ot.get("kategori") else "-"
    personel = f"\n<b>Personel:</b> {H(ot['personel'])}" if ot.get("personel") else ""
    uye = f"\n<b>\u00dcye ID:</b> {H(ot['uyeid'])}" if ot.get("uyeid") else ""
    return (E_RAPTIYE + " <b>SE\u00c7\u0130LENLER</b>\n" + f"<b>Proje:</b> {H(proje)} | <b>Kategori:</b> {H(kat)}{personel}{uye}\n\n"
            + E_PARMAK + " <b>\u015e\u0130MD\u0130 S\u0130ZDEN BEKLENEN</b>\n" + f"<b>{istenen}</b>\n\n" + E_BILGI + " " + aciklama)


def ozet_metni(conn, ot):
    """Get-OzetMetni: SON KONTROL"""
    akis = kategori_akis(conn, ot.get("kategori"))
    m = E_BUYUTEC + " <b>SON KONTROL</b>\n--------------------\n"
    m += f"<b>Proje:</b> {H((ot.get('proje') or '').upper())}\n<b>Kategori:</b> {H(kategori_etiket(conn, ot.get('kategori')))}\n<b>Personel Kodu:</b> {H(ot.get('personel'))}\n"
    if akis == "ark_ana":
        m += f"<b>Arkada\u015f \u00dcye ID:</b> {H(ot.get('uyeid'))}\n<b>Ana \u00dcye ID:</b> {H(ot.get('anaid'))}\n"
    elif akis == "ana_only":
        m += f"<b>Ana \u00dcye ID:</b> {H(ot.get('anaid'))}\n"
    else:
        m += f"<b>\u00dcye ID:</b> {H(ot.get('uyeid'))}\n"
    if ot.get("tip"):
        m += f"<b>T\u00fcr:</b> {H(ot['tip'])}\n"
    if (ot.get("girisTipi") or "resim") == "yazili":
        m += f"<b>Lead ID:</b> {H(ot.get('leadId'))}\n"
    elif (ot.get("kayitModu") or "gyazo") == "dosya":
        m += "<b>G\u00f6rsel:</b> Al\u0131nd\u0131 (dosyaya kaydedilecek)\n"
    else:
        m += "<b>G\u00f6rsel:</b> Al\u0131nd\u0131 (Gyazo linkine d\u00f6n\u00fc\u015ft\u00fcr\u00fclecek)\n"
    m += "--------------------\n" + E_ONAY + " <b>Bilgiler do\u011fruysa Onayla butonuna bas\u0131n.</b>\n" + E_KALEM + " Hata varsa \u0130ptal ile d\u00fczeltin."
    return m


def id_basligi(akis):
    return {"ark_ana": "Arkada\u015f \u00dcye ID'sini yaz\u0131n:", "ana_only": "Ana \u00dcye ID'sini yaz\u0131n:"}.get(akis, "\u00dcye ID'sini yaz\u0131n:")


def yeni_oturum(**alan):
    ot = {"adim": None, "girisTipi": "resim", "kayitModu": None, "fileId": None, "fotoSha": None, "fotoTarih": None, "leadId": None, "msgId": None,
          "proje": None, "kategori": None, "personel": None, "uyeid": None, "anaid": None, "tip": None, "gorselDosya": None}
    ot.update(alan)
    return ot


def gorunen_ad(u):
    return u.get("username") or u.get("first_name") or "Bilinmeyen"


def foto_kimligi(m):
    """Sikistirilmis fotograf ya da resim MIME'li belge -> file_id | None"""
    if m.get("photo"):
        try:
            return m["photo"][-1]["file_id"]
        except (KeyError, IndexError, TypeError):
            return None
    d = m.get("document") or {}
    if d.get("file_id") and str(d.get("mime_type") or "").lower().startswith("image/"):
        return d["file_id"]
    return None


def unix_yerel(ts):
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return db.simdi()


# ==================== mesaj ====================
def mesaj_isle(b, upd):
    """Process-Message portu. b: calistir.Bot (ayar, conn, api, log, admin_mi, ...)."""
    from . import komutlar
    m = upd.get("message") or {}
    chat = m.get("chat") or {}
    chat_id, mid = chat.get("id"), m.get("message_id")
    u = m.get("from") or {}
    uid = str(u.get("id") or chat_id or "")
    if not uid or chat_id is None:
        return
    ad = gorunen_ad(u)
    if chat.get("type", "private") != "private":
        return
    db.tg_guncelle(b.conn, uid, username=u.get("username") or "", first_name=u.get("first_name") or "", last_seen=db.simdi(), status="mesaj")
    b.log.info("  Mesaj geldi: %s (ID: %s)", ad, uid)
    metin = (m.get("text") or "").strip()
    foto = foto_kimligi(m)

    if metin and komutlar.isle(b, chat_id, uid, u, metin):
        return
    tg = db.tg_al(b.conn, uid) or {}
    if tg.get("engelli"):
        b.api.mesaj_sil(chat_id, mid)
        return
    if db.bakim_modu(b.conn) and not b.admin_mi(uid):
        b.api.mesaj_gonder(chat_id, M_BAKIM)
        return

    if tg.get("onayli"):
        if foto:
            foto_geldi(b, chat_id, uid, m, foto)
        elif metin:
            yazi_geldi(b, chat_id, uid, mid, metin)
        return

    # ---- sifre kapisi ----
    if metin:
        if metin.startswith("/"):
            b.api.mesaj_gonder(chat_id, M_SIFRE)
            return
        if b.ayar.get("BOT_PASSWORD") and metin == b.ayar["BOT_PASSWORD"]:
            db.tg_onayla(b.conn, uid, ad, kim="bot")
            b.api.mesaj_gonder(chat_id, M_HOSGELDIN)
            b.log.info("  Sifre dogru: %s onaylandi.", ad)
            return
        n = db.tg_deneme(b.conn, uid)
        en_fazla = int(b.ayar.get("MAX_DENEME") or 3)
        if n >= en_fazla:
            db.tg_engelle(b.conn, uid, sebep=f"{en_fazla} yanl\u0131\u015f \u015fifre denemesi", kim="bot")
            b.api.mesaj_sil(chat_id, mid)
            b.api.mesaj_gonder(chat_id, M_ENGELLENDI)
            b.log.info("  Engellendi: %s (%s) - sifre", ad, uid)
        else:
            b.api.mesaj_gonder(chat_id, M_YANLIS_SIFRE.format(kalan=en_fazla - n))
        return
    if foto:
        b.api.mesaj_gonder(chat_id, M_YETKISIZ_GORSEL)
        b.api.mesaj_sil(chat_id, mid)
        db.tg_engelle(b.conn, uid, sebep="Yetkisiz g\u00f6rsel g\u00f6nderimi", kim="bot")
        b.log.info("  Engellendi: %s (%s) - yetkisiz gorsel", ad, uid)
        return
    b.api.mesaj_gonder(chat_id, M_SIFRE)


def foto_geldi(b, chat_id, uid, m, file_id):
    """Yeni fotograf her zaman oturumu sifirdan baslatir (botun davranisi). Gorsel hemen indirilir:
    boyut/gorsel kontrolu, sha256 (5 dk kopya korumasi) ve gecici dosya (Onayla'da yeniden indirilmez)."""
    sinir = int(b.ayar.get("MAX_GORSEL_MB") or 8) * 1024 * 1024
    baytlar, sha = None, None
    try:
        baytlar = b.api.gorsel_indir(file_id, sinir)
    except GorselBuyuk:
        b.api.mesaj_gonder(chat_id, M_GORSEL_BUYUK.format(mb=b.ayar.get("MAX_GORSEL_MB") or 8))
        return
    except Exception as e:
        b.log.warning("! Gorsel indirme hatasi (%s): %s", uid, e)
    if baytlar is not None:
        if not gorsel.gorsel_mi(baytlar):
            b.api.mesaj_gonder(chat_id, M_GORSEL_DEGIL)
            return
        sha = hashlib.sha256(baytlar).hexdigest()
        son = b.son_gorseller.get(uid)
        if son and son[0] == sha and time.time() - son[1] < KOPYA_SURESI_SN:
            b.log.info("  Kopya gorsel yok sayildi: %s", uid)
            b.api.mesaj_gonder(chat_id, M_KOPYA)
            return
        b.gecici_yaz(uid, baytlar)
    bakim = db.gyazo_bakim(b.conn)
    ot = yeni_oturum(adim="gyazo_bakim" if bakim else "kayit_secim", girisTipi="resim", fileId=file_id, fotoSha=sha, fotoTarih=m.get("date"))
    db.oturum_yaz(b.conn, uid, ot)
    mid = b.api.mesaj_gonder(chat_id, M_GORSEL_ALINDI_BAKIM if bakim else M_GORSEL_ALINDI, kb_gyazo_bakim() if bakim else kb_kayit_secim())
    if mid:
        ot["msgId"] = mid
        db.oturum_yaz(b.conn, uid, ot)


def yazi_geldi(b, chat_id, uid, mid, metin):
    ot = db.oturum_al(b.conn, uid)
    if not ot or (ot.get("adim") not in YAZI_ADIMLARI):
        if not metin or metin.startswith("/"):
            b.api.mesaj_gonder(chat_id, M_BASLA)
            return
        ot = yeni_oturum(adim="lead_onay", girisTipi="yazili", leadId=metin)
        db.oturum_yaz(b.conn, uid, ot)
        bmid = b.api.mesaj_gonder(chat_id, M_LEAD_SORU.format(metin=H(metin)), kb_lead_onay())
        if bmid:
            ot["msgId"] = bmid
            db.oturum_yaz(b.conn, uid, ot)
        return
    bmid = ot.get("msgId")
    adim = ot.get("adim")
    akis = kategori_akis(b.conn, ot.get("kategori"))
    b.api.mesaj_sil(chat_id, mid)
    if adim == "lead_onay":
        ot["leadId"] = metin
        db.oturum_yaz(b.conn, uid, ot)
        _duzenle(b, chat_id, uid, ot, bmid, M_LEAD_SORU.format(metin=H(metin)), kb_lead_onay())
    elif adim == "personel":
        ot["personel"], ot["adim"] = metin, "uyeid"
        db.oturum_yaz(b.conn, uid, ot)
        _duzenle(b, chat_id, uid, ot, bmid, adim_mesaji(b.conn, ot, id_basligi(akis), M_ID_ACIKLAMA), kb_geri("geri_personel"))
    elif adim == "uyeid":
        ot["uyeid"] = metin
        if akis == "ark_ana":
            ot["adim"] = "anaid"
            db.oturum_yaz(b.conn, uid, ot)
            _duzenle(b, chat_id, uid, ot, bmid, adim_mesaji(b.conn, ot, M_ANA_BASLIK, M_ANA_ACIKLAMA), kb_geri("geri_uyeid"))
        elif akis == "ana_only":
            ot["anaid"], ot["uyeid"], ot["adim"] = metin, None, "ozet"
            db.oturum_yaz(b.conn, uid, ot)
            _duzenle(b, chat_id, uid, ot, bmid, ozet_metni(b.conn, ot), kb_onay())
        elif akis == "sessiz_tip":
            ot["adim"] = "tip"
            db.oturum_yaz(b.conn, uid, ot)
            _duzenle(b, chat_id, uid, ot, bmid, adim_mesaji(b.conn, ot, M_TIP_BASLIK, M_TIP_ACIKLAMA), kb_sessiz())
        else:
            ot["adim"] = "ozet"
            db.oturum_yaz(b.conn, uid, ot)
            _duzenle(b, chat_id, uid, ot, bmid, ozet_metni(b.conn, ot), kb_onay())
    elif adim == "anaid":
        ot["anaid"], ot["adim"] = metin, "ozet"
        db.oturum_yaz(b.conn, uid, ot)
        _duzenle(b, chat_id, uid, ot, bmid, ozet_metni(b.conn, ot), kb_onay())


def _duzenle(b, chat_id, uid, ot, bmid, metin, kb=None):
    """Botun mesajini yerinde duzenler; mesaj yoksa/duzenlenemezse yeni mesaj gonderir ve msgId'yi gunceller."""
    yeni = b.api.mesaj_duzenle(chat_id, bmid, metin, kb)
    if yeni and yeni != ot.get("msgId"):
        ot["msgId"] = yeni
        db.oturum_yaz(b.conn, uid, ot)


# ==================== callback ====================
def geri_arama_isle(b, upd):
    """Process-Callback portu."""
    from . import komutlar
    cb = upd.get("callback_query") or {}
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    msg_id = msg.get("message_id")
    u = cb.get("from") or {}
    uid = str(u.get("id") or "")
    data = cb.get("data") or ""
    if not uid or chat_id is None:
        return
    db.tg_guncelle(b.conn, uid, username=u.get("username") or "", first_name=u.get("first_name") or "", last_seen=db.simdi(), status="callback")
    b.api.geri_arama_yanitla(cb.get("id"))
    if data.startswith("admin_"):
        komutlar.geri_arama(b, chat_id, uid, msg_id, data)
        return
    tg = db.tg_al(b.conn, uid) or {}
    if not tg.get("onayli") or tg.get("engelli"):
        return
    if db.bakim_modu(b.conn) and not b.admin_mi(uid):
        b.api.mesaj_duzenle(chat_id, msg_id, M_BAKIM)
        return
    ot = db.oturum_al(b.conn, uid)
    if not ot:
        return
    if msg_id and ot.get("msgId") != msg_id:
        ot["msgId"] = msg_id
    conn = b.conn

    def kaydet():
        db.oturum_yaz(conn, uid, ot)

    def duzenle(metin, kb=None):
        b.api.mesaj_duzenle(chat_id, msg_id, metin, kb)

    # ---- yazili baslatma ----
    if data == "lead_onay":
        if ot.get("adim") != "lead_onay":
            return
        ot["girisTipi"], ot["adim"] = "yazili", "proje"
        kaydet()
        duzenle(M_LEAD_ALINDI.format(lead=H(ot.get("leadId"))), kb_proje(conn))
        return
    if data == "lead_degistir":
        if ot.get("adim") != "lead_onay":
            return
        duzenle(M_LEAD_DEGISTIR.format(lead=H(ot.get("leadId"))))
        return
    if data == "lead_iptal":
        b.oturum_kaldir(uid)
        duzenle(M_LEAD_IPTAL)
        return
    # ---- gorsel kayit secimi ----
    if data == "kayit_gyazo":
        if ot.get("adim") not in ("kayit_secim", "gyazo_bakim"):
            return
        if db.gyazo_bakim(conn):
            ot["adim"] = "gyazo_bakim"
            kaydet()
            duzenle(M_GYAZO_BAKIM, kb_gyazo_bakim())
            return
        ot["kayitModu"], ot["adim"] = "gyazo", "proje"
        kaydet()
        duzenle(M_GYAZO_SECILDI, kb_proje(conn))
        return
    if data == "kayit_dosya":
        if ot.get("adim") not in ("kayit_secim", "gyazo_bakim"):
            return
        ot["kayitModu"] = "dosya"
        if ot.get("proje") and ot.get("kategori") and ot.get("personel"):
            ot["adim"] = "ozet"
            kaydet()
            duzenle(ozet_metni(conn, ot), kb_onay())
            return
        ot["adim"] = "proje"
        kaydet()
        duzenle(M_DOSYA_SECILDI, kb_proje(conn))
        return
    # ---- proje / kategori / tip ----
    if data.startswith("proje_"):
        kod = data[6:].upper()
        if kod not in db.proje_kodlari(conn):
            duzenle(M_PROJE_PASIF, kb_proje(conn))
            return
        ot["proje"], ot["adim"] = kod.lower(), "kategori"
        kaydet()
        duzenle(M_KATEGORI_SEC.format(proje=H(kod)), kb_kategori(conn))
        return
    if data.startswith("kat_"):
        k = db.kategori_bul(conn, data[4:])
        if not k or not k.get("aktif"):
            duzenle(M_KATEGORI_PASIF, kb_kategori(conn))
            return
        ot["kategori"], ot["adim"] = k["kod"], "personel"
        kaydet()
        duzenle(adim_mesaji(conn, ot, M_PERSONEL_BASLIK, M_PERSONEL_ACIKLAMA), kb_geri("geri_kategori"))
        return
    if data.startswith("tip_"):
        tip = TIPLER.get(data[4:].lower())
        if not tip:
            return
        ot["tip"], ot["adim"] = tip, "ozet"
        kaydet()
        duzenle(ozet_metni(conn, ot), kb_onay())
        return
    # ---- geri ----
    akis = kategori_akis(conn, ot.get("kategori"))
    if data == "geri_proje":
        ot["kategori"], ot["adim"] = None, "proje"
        kaydet()
        duzenle(M_PROJE_SEC, kb_proje(conn))
        return
    if data == "geri_kategori":
        ot["personel"], ot["adim"] = None, "kategori"
        kaydet()
        duzenle(M_KATEGORI_SEC.format(proje=H((ot.get("proje") or "").upper())), kb_kategori(conn))
        return
    if data == "geri_personel":
        ot["uyeid"], ot["anaid"], ot["adim"] = None, None, "personel"
        kaydet()
        duzenle(adim_mesaji(conn, ot, M_PERSONEL_BASLIK, M_PERSONEL_ACIKLAMA), kb_geri("geri_kategori"))
        return
    if data == "geri_uyeid":
        ot["anaid"], ot["tip"], ot["adim"] = None, None, "uyeid"
        kaydet()
        duzenle(adim_mesaji(conn, ot, id_basligi(akis), M_ID_ACIKLAMA), kb_geri("geri_personel"))
        return
    # ---- onay ----
    if data == "onayla":
        onayla(b, chat_id, uid, u, msg_id, ot)
        return
    # ---- iptal menusu ----
    if data == "iptal":
        duzenle(M_IPTAL_NEREYE, kb_iptal())
        return
    if data == "iptal_basa":
        b.oturum_kaldir(uid)
        duzenle(M_IPTAL_BASA)
        return
    if data == "iptal_proje":
        ot.update({"kategori": None, "personel": None, "uyeid": None, "anaid": None, "tip": None, "adim": "proje"})
        kaydet()
        duzenle(M_PROJE_SEC, kb_proje(conn))
        return
    if data == "iptal_kategori":
        ot.update({"personel": None, "uyeid": None, "anaid": None, "tip": None, "adim": "kategori"})
        kaydet()
        duzenle(M_KATEGORI_SEC.format(proje=H((ot.get("proje") or "").upper())), kb_kategori(conn))
        return
    if data == "iptal_bilgi":
        ot.update({"personel": None, "uyeid": None, "anaid": None, "tip": None, "adim": "personel"})
        kaydet()
        duzenle(adim_mesaji(conn, ot, M_PERSONEL_BASLIK, M_PERSONEL_ACIKLAMA), kb_geri("geri_kategori"))
        return


# ==================== onayla ====================
def onayla(b, chat_id, uid, u, msg_id, ot):
    """Onayla: gorseli indir/dogrula/kaydet (+Gyazo), kaydi yaz, oturumu sil (cevaptan ONCE: ikinci tiklama bos doner)."""
    conn = b.conn
    if ot.get("adim") != "ozet" or not (ot.get("proje") and ot.get("kategori") and ot.get("personel")):
        return
    giris = ot.get("girisTipi") or "resim"
    mod = ot.get("kayitModu") or "gyazo"
    kat = db.kategori_bul(conn, ot["kategori"]) or {"kod": ot["kategori"], "etiket": ot["kategori"].upper(), "akis": "tek_uye"}
    proje = (ot["proje"] or "").upper()
    link, link_turu, gorsel_dosya, dosya_adi, foto_tarih = "", "bos", "", "", None

    def duzenle(metin, kb=None):
        b.api.mesaj_duzenle(chat_id, msg_id, metin, kb)

    if giris == "yazili":
        link, link_turu = ot.get("leadId") or "", "metin"
    else:
        if mod != "dosya" and db.gyazo_bakim(conn):
            ot["adim"] = "gyazo_bakim"
            db.oturum_yaz(conn, uid, ot)
            duzenle(M_GYAZO_BAKIM_ONAY, kb_gyazo_bakim())
            return
        duzenle(M_KAYDEDILIYOR if mod == "dosya" else M_YUKLENIYOR)
        foto_tarih = unix_yerel(ot.get("fotoTarih")) if ot.get("fotoTarih") else db.simdi()
        try:
            baytlar = None
            gorsel_dosya = ot.get("gorselDosya") or ""
            if gorsel_dosya and gorsel.tam_yol(b.ayar["GORSELLER"], gorsel_dosya):
                with open(gorsel.tam_yol(b.ayar["GORSELLER"], gorsel_dosya), "rb") as f:
                    baytlar = f.read()
            else:
                baytlar = b.gorsel_baytlari(uid, ot)
                if not gorsel.gorsel_mi(baytlar):
                    raise ValueError("gorsel degil")
                baytlar, uz = gorsel.jpeg_yap(baytlar)
                ad = gorsel.dosya_adi(kat["etiket"], foto_tarih, ot.get("personel"), ot.get("uyeid"), ot.get("anaid"), ot.get("tip"), uz)
                gorsel_dosya = gorsel.kaydet(b.ayar["GORSELLER"], proje, baytlar, ad)
                ot["gorselDosya"] = gorsel_dosya
                db.oturum_yaz(conn, uid, ot)
                b.log.info("  Gorsel diske kaydedildi -> %s", gorsel_dosya)
        except Exception as e:
            b.hata(f"Gorsel kaydetme hatasi ({uid}): {e}")
            duzenle(M_KAYDEDILEMEDI, kb_hata())
            return
        dosya_adi = os.path.basename(gorsel_dosya)
        if mod == "gyazo":
            url = G.yukle(b.ayar.get("GYAZO_TOKEN"), baytlar, b.ayar.get("GYAZO_API"))
            if not url:
                b.hata(f"Gyazo yukleme basarisiz ({uid})")
                duzenle(M_YUKLENEMEDI, kb_hata())
                return
            link, link_turu = url, "gyazo"
        else:
            link, link_turu = "", "dosya"

    alanlar = {"proje": proje, "kategori": kat["etiket"], "kategori_kod": kat["kod"], "personel": ot.get("personel") or "",
               "uye_id": ot.get("uyeid") or "", "ana_uye_id": ot.get("anaid") or "", "tip": ot.get("tip") or "",
               "link": link, "link_turu": link_turu, "gorsel_dosya": gorsel_dosya, "giris_tipi": giris,
               "lead_id": (ot.get("leadId") or "") if giris == "yazili" else "", "foto_tarih": foto_tarih,
               "ekleyen_tg_id": uid, "ekleyen_ad": gorunen_ad(u), "ekleyen_guven": "kesin"}
    try:
        kayit = db.kayit_ekle(conn, alanlar, kim="bot", kaynak="bot")
        db.tg_kayit_sayaci(conn, uid, u.get("username") or "", u.get("first_name") or "", proje, kat["kod"], kat["etiket"])
    except Exception as e:
        b.hata(f"Kayit yazma hatasi ({uid}): {e}")
        duzenle(M_KAYIT_HATASI, kb_hata())
        return
    # oturum CEVAPTAN ONCE silinir: ikinci Onayla tiklamasi oturum bulamaz, bos doner
    b.oturum_kaldir(uid)
    if ot.get("fotoSha"):
        b.son_gorseller[uid] = (ot["fotoSha"], time.time())
    if giris != "yazili" and mod == "dosya":
        duzenle(M_BASARILI_DOSYA.format(dosya=H(dosya_adi)) + M_YENI_KAYIT)
    else:
        duzenle(M_BASARILI + M_YENI_KAYIT)
    b.log.info("Kaydedildi -> [%s] [%s] #%s %s", proje, kat["etiket"].upper(), kayit["id"], link or gorsel_dosya)
    return kayit

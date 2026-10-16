# -*- coding: utf-8 -*-
"""Komut satiri: python -m kanit <komut>

  web                      Flask paneli (kanit.web)
  bot                      Telegram botu (kanit.bot)
  ice-aktar ...            Windows surumunden gecis (once --kuru ile deneme, sonra --uygula)
  excel-ekle --excel X     sonradan gelen duzeltme kitabi (yalniz yeni satir + KT)
  disa-aktar --cikti X     tam kitap Excel ciktisi
  yedekle [--klasor K]     veritabani yedegi (VERI/yedek/kanit-YYYY-MM-DD_HHMM.db)
  kullanici-ekle AD YETKI  panel kullanicisi (gecici sifre basilir)
  sifre-sifirla AD         yeni gecici sifre
  saglik                   veritabani / sayaclar / bot nabzi (cikis 0 saglikli, 1 sorun)
Ciktilar Turkce ASCII.
"""
import os, sys, argparse, secrets, string
from datetime import datetime

NABIZ_SINIR_SN = 300


def _ayar():
    from . import ayar
    return ayar.yukle()


def _baglan(a):
    from . import db
    return db.baglan(a["DB"])


def _gecici_sifre(n=12):
    alfabe = string.ascii_letters + string.digits
    while True:
        s = "".join(secrets.choice(alfabe) for _ in range(n))
        if any(c.isdigit() for c in s) and any(c.isupper() for c in s) and any(c.islower() for c in s):
            return s


def _rapor_yaz(rapor, dosya):
    from . import ice_aktar
    import json
    with open(dosya, "w", encoding="utf-8") as f:
        f.write(ice_aktar.rapor_metni(rapor, tam=True))
        f.write("\n\n---- JSON ----\n")
        f.write(json.dumps(rapor, ensure_ascii=False, indent=1, default=str))


def k_ice_aktar(args):
    from . import db, ice_aktar
    if not (args.excel or args.bot_klasor or args.panel_db or args.gorseller):
        print("En az bir kaynak verin: --excel, --bot-klasor, --panel-db, --gorseller")
        return 2
    for y in [args.excel, args.bot_klasor] + list(args.panel_db or []) + list(args.gorseller or []):
        if y and not os.path.exists(y):
            print(f"Bulunamadi: {y}")
            return 2
    a = _ayar()
    conn = _baglan(a)
    kuru = not args.uygula
    rapor = ice_aktar.calistir(conn, a, excel=args.excel, bot_klasor=args.bot_klasor, panel_db=args.panel_db or [], gorseller=args.gorseller or [], kuru=kuru)
    print(ice_aktar.rapor_metni(rapor))
    if args.rapor:
        _rapor_yaz(rapor, args.rapor)
        print(f"\nTam rapor: {args.rapor}")
    if kuru:
        print("\nBu bir DENEME idi; uygulamak icin --uygula ekleyin.")
    return 1 if rapor["hata"] else 0


def k_excel_ekle(args):
    from . import ice_aktar
    if not os.path.exists(args.excel):
        print(f"Bulunamadi: {args.excel}")
        return 2
    a = _ayar()
    conn = _baglan(a)
    rapor = ice_aktar.excel_ekle(conn, a, args.excel, kuru=args.kuru, gorseller=args.gorseller or [])
    print(ice_aktar.rapor_metni(rapor))
    if args.rapor:
        _rapor_yaz(rapor, args.rapor)
    return 1 if rapor["hata"] else 0


def k_disa_aktar(args):
    from . import disa_aktar
    a = _ayar()
    conn = _baglan(a)
    cikti = args.cikti or os.path.join(a["YEDEK"], "kanit-" + datetime.now().strftime("%Y-%m-%d_%H%M") + ".xlsx")
    os.makedirs(os.path.dirname(os.path.abspath(cikti)), exist_ok=True)
    disa_aktar.tam_kitap(conn, cikti, projeler=args.proje or None, silinenler=args.silinenler, site_url=a.get("SITE_URL") or "", olusturan="komut satiri")
    print(f"Yazildi: {cikti}")
    return 0


def k_yedekle(args):
    from . import db
    a = _ayar()
    conn = _baglan(a)
    klasor = args.klasor or a["YEDEK"]
    hedef = os.path.join(klasor, "kanit-" + datetime.now().strftime("%Y-%m-%d_%H%M") + ".db")
    db.yedekle(conn, hedef)
    print(f"Veritabani yedegi: {hedef}")
    print(f"Gorseller klasoru (deploy betigi arsivler): {a['GORSELLER']}")
    return 0


def k_kullanici_ekle(args):
    from . import db
    a = _ayar()
    conn = _baglan(a)
    ad = args.kullanici_adi.strip().lower()
    if db.kullanici_bul(conn, ad):
        print(f"Kullanici zaten var: {ad}")
        return 1
    sifre = _gecici_sifre()
    try:
        u = db.kullanici_ekle(conn, ad, args.yetki, sifre, gorunen_ad=args.ad or ad, olusturan="komut satiri", sifre_degistir=True)
    except ValueError as e:
        print(f"Hata: {e}")
        return 1
    print(f"Kullanici eklendi: {u['kullanici_adi']}  yetki: {u['yetki'] or '(yok)'}  ad: {u['ad']}")
    print(f"Gecici sifre: {sifre}")
    print("Ilk giriste sifre degistirmesi istenir.")
    return 0


def k_sifre_sifirla(args):
    from . import db
    a = _ayar()
    conn = _baglan(a)
    ad = args.kullanici_adi.strip().lower()
    if not db.kullanici_bul(conn, ad):
        print(f"Kullanici yok: {ad}")
        return 1
    sifre = _gecici_sifre()
    db.kullanici_guncelle(conn, ad, kim="komut satiri", sifre=sifre, sifre_degistir=True, aktif=True)
    print(f"Sifre sifirlandi: {ad}")
    print(f"Gecici sifre: {sifre}")
    return 0


def k_saglik(args):
    from . import db
    a = _ayar()
    sorun = []
    print(f"VERI: {a['VERI']}")
    print(f"DB:   {a['DB']}  ({'var' if os.path.exists(a['DB']) else 'YOK'})")
    try:
        conn = _baglan(a)
        say = db.proje_sayaclari(conn)
        toplam = 0
        for p in db.projeler(conn, aktif=False):
            s = say.get(p["kod"], {"bekleyen": 0, "onayli": 0, "silinen": 0, "toplam": 0})
            toplam += s["toplam"]
            print(f"  {p['kod']:<8} toplam {s['toplam']:>6}  onayli {s['onayli']:>6}  bekleyen {s['bekleyen']:>6}  silinen {s['silinen']:>5}" + ("" if p["aktif"] else "  (pasif)"))
        print(f"  Kayit toplami: {toplam}   panel kullanicisi: {len(db.kullanicilar(conn))}   telegram uyesi: {conn.execute('SELECT COUNT(*) FROM tg_kullanicilari').fetchone()[0]}")
        nabiz = db.ayar_al(conn, "bot_nabiz")
        if nabiz:
            try:
                yas = int((datetime.now() - datetime.strptime(nabiz[:19], "%Y-%m-%d %H:%M:%S")).total_seconds())
                print(f"  Bot nabzi: {nabiz} ({yas} sn once)")
                if yas > NABIZ_SINIR_SN:
                    sorun.append(f"bot nabzi {yas} sn eski (sinir {NABIZ_SINIR_SN})")
            except ValueError:
                sorun.append(f"bot nabzi okunamadi: {nabiz}")
        else:
            print("  Bot nabzi: yok (bot hic calismamis)")
            sorun.append("bot nabzi yok")
        print(f"  Bakim modu: {'ACIK' if db.bakim_modu(conn) else 'kapali'}   son degisiklik: {db.ayar_al(conn, 'son_degisiklik') or '-'}")
    except Exception as e:
        sorun.append(f"veritabani acilamadi: {e}")
    if sorun:
        print("SORUN: " + "; ".join(sorun))
        return 1
    print("SAGLIKLI")
    return 0


def k_web(args):
    from .web import calistir
    calistir()
    return 0


def k_bot(args):
    from .bot import calistir
    calistir()
    return 0


def ana(argv=None):
    p = argparse.ArgumentParser(prog="python -m kanit", description="Kanit Merkezi komut satiri")
    alt = p.add_subparsers(dest="komut")
    alt.add_parser("web", help="web paneli").set_defaults(f=k_web)
    alt.add_parser("bot", help="telegram botu").set_defaults(f=k_bot)
    ia = alt.add_parser("ice-aktar", help="Windows surumunden gecis")
    ia.add_argument("--excel", help="telegrambot_gyazo.xlsx")
    ia.add_argument("--bot-klasor", dest="bot_klasor", help="bot klasoru (kullanicilar.json, onaylilar.txt, bot_log.txt, kayitlar.jsonl ...)")
    ia.add_argument("--panel-db", dest="panel_db", action="append", help="eski panel.db (birden fazla verilebilir)")
    ia.add_argument("--gorseller", action="append", help="gorsel klasoru (gorseller/, ekran_goruntuleri/, telegram_gorseller/; birden fazla)")
    g = ia.add_mutually_exclusive_group()
    g.add_argument("--kuru", action="store_true", help="deneme (varsayilan)")
    g.add_argument("--uygula", action="store_true", help="gercekten yaz")
    ia.add_argument("--rapor", help="tam raporun yazilacagi dosya")
    ia.set_defaults(f=k_ice_aktar)
    ee = alt.add_parser("excel-ekle", help="sonradan gelen kitap: yalniz yeni satir + KT")
    ee.add_argument("--excel", required=True)
    ee.add_argument("--gorseller", action="append")
    ee.add_argument("--kuru", action="store_true")
    ee.add_argument("--rapor")
    ee.set_defaults(f=k_excel_ekle)
    da = alt.add_parser("disa-aktar", help="tam kitap Excel")
    da.add_argument("--cikti", help="dosya.xlsx (varsayilan VERI/yedek/kanit-<zaman>.xlsx)")
    da.add_argument("--silinenler", action="store_true", help="SILINENLER sayfasi da")
    da.add_argument("--proje", action="append", help="yalniz bu proje(ler)")
    da.set_defaults(f=k_disa_aktar)
    y = alt.add_parser("yedekle", help="veritabani yedegi")
    y.add_argument("--klasor")
    y.set_defaults(f=k_yedekle)
    ke = alt.add_parser("kullanici-ekle", help="panel kullanicisi ekle")
    ke.add_argument("kullanici_adi")
    ke.add_argument("yetki", help="admin | * | OF | OF:oku,kt ...")
    ke.add_argument("--ad", help="gorunen ad")
    ke.set_defaults(f=k_kullanici_ekle)
    ss = alt.add_parser("sifre-sifirla", help="yeni gecici sifre")
    ss.add_argument("kullanici_adi")
    ss.set_defaults(f=k_sifre_sifirla)
    alt.add_parser("saglik", help="durum").set_defaults(f=k_saglik)
    args = p.parse_args(argv)
    if not args.komut:
        p.print_help()
        return 2
    return args.f(args)


if __name__ == "__main__":
    sys.exit(ana())

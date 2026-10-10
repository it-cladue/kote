# -*- coding: utf-8 -*-
"""Telegram kanit botu - web paneli (Flask).

Calistirma: KanitPaneli.exe (cift tik) ya da kaynaktan  python -m app.panel
Panel her bilgisayarda yerel calisir (127.0.0.1). Bot klasoru OneDrive ile esitlenen klasordur;
panel oradan Excel'i (kopyalayarak) okur, islemleri panel_kuyruk\\<bilgisayar>.jsonl'a yazar,
bot uygular. Excel'e yalnizca bot yazar.
"""
import os, sys, json, secrets, threading, time, functools, string, random, glob, webbrowser, urllib.request
from datetime import datetime, timedelta
from flask import Flask, g, request, session, redirect, url_for, render_template, jsonify, abort, send_file, flash
from werkzeug.datastructures import MultiDict

from . import db, yetki, excel_oku, ice_aktar, gorsel, kuyruk, bot_yonetim, log_oku, kullanicilar

SURUM = "1.1.0"
DONMUS = bool(getattr(sys, "frozen", False))
KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # kaynak kodu koku
KAYNAK_KOK = getattr(sys, "_MEIPASS", None) or KOK                            # sablon / statik (exe icinde)
EXE_KLASOR = os.path.dirname(os.path.abspath(sys.executable)) if DONMUS else KOK
VARSAYILAN_RENK = {"PP": "#A6A6A6", "PA": "#4472C4", "OF": "#FFFF00", "HI": "#FF0000", "VI": "#7030A0", "GA": "#00B050", "BETA": "#FFA500"}
EXCEL_ADI = "telegrambot_gyazo.xlsx"


def _veri_koku():
    k = os.environ.get("PANEL_VERI")
    if not k:
        if DONMUS:
            k = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "KanitPaneli")
        else:
            k = KOK
    os.makedirs(k, exist_ok=True)
    return k


VERI_KOK = _veri_koku()
AYAR_YOL = os.environ.get("PANEL_AYAR") or os.path.join(VERI_KOK, "panel_ayar.json")


def bot_klasoru_mu(k):
    try:
        return bool(k) and os.path.isfile(os.path.join(k, EXCEL_ADI))
    except Exception:
        return False


def bot_klasoru_adaylari(mevcut=None):
    """Exe'nin bulundugu klasor (OneDrive'daki bot klasorune konmussa), ust klasoru ve OneDrive altindaki klasorler."""
    adaylar = []

    def ekle(k):
        try:
            k = os.path.abspath(k)
        except Exception:
            return
        if bot_klasoru_mu(k) and k not in adaylar:
            adaylar.append(k)

    if mevcut:
        ekle(mevcut)
    ekle(EXE_KLASOR)
    ekle(os.path.dirname(EXE_KLASOR))
    home = os.path.expanduser("~")
    kokler = glob.glob(os.path.join(home, "OneDrive*")) + [os.path.join(home, "Desktop"), os.path.join(home, "Documents")]
    for od in kokler:
        if not os.path.isdir(od):
            continue
        derinlik0 = od.rstrip("\\/").count(os.sep)
        for root, dirs, files in os.walk(od):
            if root.count(os.sep) - derinlik0 >= 3:
                dirs[:] = []
            if EXCEL_ADI in files:
                ekle(root)
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("gorseller", "backups", "ekran_goruntuleri", "telegram_gorseller", "node_modules")]
    return adaylar


def ayar_yukle():
    ham = {}
    bozuk = False
    if os.path.exists(AYAR_YOL):
        try:
            with open(AYAR_YOL, encoding="utf-8-sig") as f:
                ham = json.load(f)
        except Exception as e:
            # Elle duzenlenirken bozulmus olabilir: ustune YAZMA, kenara al, varsayilanlarla devam et
            bozuk = True
            try:
                yedek = AYAR_YOL + ".bozuk-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                os.replace(AYAR_YOL, yedek)
                print(f"! panel_ayar.json okunamadi ({e}); dosya {yedek} olarak kenara alindi, varsayilan ayarlarla devam ediliyor.")
            except Exception:
                print("! panel_ayar.json okunamadi:", e)
    degisti = False
    if not ham.get("GIZLI_ANAHTAR"):
        ham["GIZLI_ANAHTAR"] = secrets.token_hex(32)
        degisti = True
    if not bot_klasoru_mu(ham.get("BOT_KLASOR")):
        adaylar = bot_klasoru_adaylari(ham.get("BOT_KLASOR"))
        if adaylar:
            ham["BOT_KLASOR"] = adaylar[0]
            degisti = True
    if degisti and not bozuk:
        ayar_dosyaya_yaz(ham)
    return ayar_turet(ham)


def ayar_dosyaya_yaz(ham):
    # Dosyaya yalnizca kullanicinin yazdigi alanlar + gizli anahtar yazilir; turetilen yollar (EXCEL vb.) yazilmaz.
    try:
        os.makedirs(os.path.dirname(AYAR_YOL), exist_ok=True)
        with open(AYAR_YOL, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in ham.items() if not k.startswith("_t_")}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("panel_ayar.json yazilamadi:", e)


def ayar_turet(ham):
    a = dict(ham)
    a.setdefault("BOT_KLASOR", "")
    bk = a["BOT_KLASOR"] or EXE_KLASOR
    a["EXCEL"] = ham.get("EXCEL") or os.path.join(bk, EXCEL_ADI)
    a["LOG_DOSYA"] = ham.get("LOG_DOSYA") or os.path.join(bk, "bot_log.txt")
    a["GORSEL_KLASOR"] = ham.get("GORSEL_KLASOR") or os.path.join(bk, "gorseller")
    a["DB"] = ham.get("DB") or os.path.join(VERI_KOK, "panel.db")
    a["ONBELLEK"] = ham.get("ONBELLEK") or os.path.join(VERI_KOK, "tmp")
    a.setdefault("YENILEME_SN", 30)       # kaynak degisti mi kontrolu (ucuz); Excel ancak degistiyse yeniden okunur
    a.setdefault("DINLE", "127.0.0.1")
    a.setdefault("PORT", 8080)
    a.setdefault("PROJE_RENK", VARSAYILAN_RENK)
    a.setdefault("SUTUN_HARITASI", {})
    a.setdefault("SAYFA_BOYU", 48)
    return a


AYAR = ayar_yukle()
_yerel = threading.local()


def ayar_degistir(**degisiklik):
    """Calisirken ayar degistir (kurulum sayfasi): dosyaya yaz, AYAR'i ve gorsel cozucuyu yenile."""
    ham = {}
    if os.path.exists(AYAR_YOL):
        try:
            with open(AYAR_YOL, encoding="utf-8-sig") as f:
                ham = json.load(f)
        except Exception:
            ham = {}
    ham["GIZLI_ANAHTAR"] = AYAR.get("GIZLI_ANAHTAR") or ham.get("GIZLI_ANAHTAR") or secrets.token_hex(32)
    ham.update(degisiklik)
    ayar_dosyaya_yaz(ham)
    yeni = ayar_turet(ham)
    AYAR.clear()
    AYAR.update(yeni)
    global COZUCU
    COZUCU = gorsel.GorselCozucu(AYAR, AYAR["ONBELLEK"])


def baglanti():
    c = getattr(_yerel, "conn", None)
    if c is None:
        c = db.baglan(AYAR["DB"])
        _yerel.conn = c
    return c


COZUCU = gorsel.GorselCozucu(AYAR, AYAR["ONBELLEK"])
app = Flask(__name__, template_folder=os.path.join(KAYNAK_KOK, "app", "templates"), static_folder=os.path.join(KAYNAK_KOK, "app", "static"))
app.secret_key = AYAR["GIZLI_ANAHTAR"]
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=4 * 1024 * 1024)
if str(AYAR.get("HTTPS", "0")).lower() in ("1", "true"):
    app.config["SESSION_COOKIE_SECURE"] = True


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ==================== yardimcilar ====================
def projeler():
    """Excel'de gorulen sayfalar (kayitlar tablosu) + ayar listesi; sirali"""
    c = baglanti()
    gorulen = [r["proje"] for r in c.execute("SELECT DISTINCT proje FROM kayitlar").fetchall()]
    sira = list(AYAR.get("PROJELER") or ["PP", "PA", "OF", "HI", "VI", "GA", "BETA"])
    return [p for p in sira if p in gorulen] + sorted(p for p in gorulen if p not in sira)


def renk(proje):
    return AYAR["PROJE_RENK"].get((proje or "").upper(), "#999999")


def metin_rengi(hex_renk):
    """Arka plan rengine gore okunur yazi rengi (OF sari -> siyah yazi)"""
    try:
        h = (hex_renk or "#999999").lstrip("#")
        r, gg, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#111111" if (0.299 * r + 0.587 * gg + 0.114 * b) > 150 else "#ffffff"
    except Exception:
        return "#ffffff"


def url_degistir(**kw):
    """Mevcut sorgu parametrelerini koruyarak bazilarini degistir (sayfa numarasi, s= verilmediyse sifirlanir)."""
    a = request.args.to_dict(flat=False)
    a.pop("s", None)
    for k, v in kw.items():
        if v is None or v == "":
            a.pop(k, None)
        elif isinstance(v, (list, tuple)):
            a[k] = [str(x) for x in v]
        else:
            a[k] = [str(v)]
    return url_for(request.endpoint or "kayitlar", **a)


def kullanici_yukle():
    kad = session.get("kad")
    if not kad:
        return None
    u = kullanicilar.bul(AYAR, kad)
    if not u or not u.get("aktif", True):
        return None
    return u


KURULUM_SERBEST = {"kurulum", "kurulum_admin", "static", "saglik", "cikis"}


@app.before_request
def _on():
    g.k = kullanici_yukle()
    g.yk = yetki.coz(g.k["yetki"]) if g.k else yetki.coz("")
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST" and request.endpoint not in ("giris",):
        tok = request.form.get("csrf") or request.headers.get("X-CSRF")
        if not tok or tok != session.get("csrf"):
            abort(400, "CSRF")
    ep = request.endpoint or ""
    if ep in KURULUM_SERBEST:
        return None
    if not bot_klasoru_mu(AYAR.get("BOT_KLASOR")):
        return redirect(url_for("kurulum"))
    if not kullanicilar.var_mi(AYAR):
        return redirect(url_for("kurulum_admin"))
    return None


@app.context_processor
def _ctx():
    return {"k": g.get("k"), "yk": g.get("yk"), "renk": renk, "metin_rengi": metin_rengi, "url_degistir": url_degistir, "csrf": session.get("csrf", ""),
            "projeler": projeler, "izin": lambda p, e: yetki.izin(g.yk, p, e), "AYAR": AYAR, "simdi": simdi, "SURUM": SURUM}


def giris_gerekli(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if not g.k:
            return redirect(url_for("giris", sonraki=request.path))
        return f(*a, **kw)
    return w


def admin_gerekli(f):
    @functools.wraps(f)
    def w(*a, **kw):
        if not g.k:
            return redirect(url_for("giris", sonraki=request.path))
        if not g.yk["admin"]:
            abort(403)
        return f(*a, **kw)
    return w


def ip():
    return request.headers.get("CF-Connecting-IP") or request.remote_addr


def kayit_izin(kayit, eylem):
    return yetki.izin(g.yk, kayit["proje"], eylem)


# ==================== kurulum (ilk calisma) ====================
@app.route("/kurulum", methods=["GET", "POST"])
def kurulum():
    gecerli = bot_klasoru_mu(AYAR.get("BOT_KLASOR"))
    if gecerli and not (g.k and g.yk["admin"]):
        return redirect(url_for("ana"))
    hata = None
    if request.method == "POST":
        k = (request.form.get("klasor") or "").strip().strip('"')
        if not bot_klasoru_mu(k):
            hata = f"Bu klasorde {EXCEL_ADI} bulunamadi: {k or '(bos)'}"
        else:
            ayar_degistir(BOT_KLASOR=os.path.abspath(k))
            threading.Thread(target=_ice_aktar_bir_kez, daemon=True).start()
            flash("Bot klasoru kaydedildi: " + AYAR["BOT_KLASOR"])
            return redirect(url_for("kurulum_admin") if not kullanicilar.var_mi(AYAR) else url_for("ana"))
    return render_template("kurulum.html", adaylar=bot_klasoru_adaylari(AYAR.get("BOT_KLASOR")), mevcut=AYAR.get("BOT_KLASOR") or "", hata=hata, excel_adi=EXCEL_ADI, veri_kok=VERI_KOK, ayar_yol=AYAR_YOL)


def kullanici_adi_gecerli(ad):
    return bool(ad) and len(ad) <= 40 and ad.replace("_", "").replace(".", "").isalnum()


@app.route("/kurulum/admin", methods=["GET", "POST"])
def kurulum_admin():
    if not bot_klasoru_mu(AYAR.get("BOT_KLASOR")):
        return redirect(url_for("kurulum"))
    if kullanicilar.var_mi(AYAR):
        return redirect(url_for("giris"))
    # Kullanici dosyasi yok ama klasorde panel daha once kullanilmis: buyuk olasilikla OneDrive dosyayi henuz
    # getirmedi (ya da biri sildi). Bot bilgisayari degilse yeni "ilk admin" olusturulmaz; botun admin sifresiyle
    # (config.json ADMIN_PASSWORD) acilabilir. Boylece iki bilgisayarin ayri ayri ilk admin yaratmasi onlenir.
    bekle = kullanicilar.once_kullanilmis(AYAR) and not bot_yonetim.yerel_bot_sureci()
    hata = None
    if request.method == "POST":
        ad = (request.form.get("kullanici") or "").strip().lower()
        s1, s2 = request.form.get("sifre") or "", request.form.get("sifre2") or ""
        if bekle and not bot_yonetim.admin_sifresi_dogru(AYAR, request.form.get("bot_admin_sifre")):
            hata = "Bot admin sifresi hatali. Kullanici dosyasi OneDrive ile gelene kadar bekleyin ya da botun ADMIN_PASSWORD degerini girin."
        elif not kullanici_adi_gecerli(ad):
            hata = "Kullanici adi harf/rakam olmali."
        elif len(s1) < 8:
            hata = "Sifre en az 8 karakter olmali."
        elif s1 != s2:
            hata = "Sifreler ayni degil."
        else:
            kullanicilar.ekle(AYAR, ad, "admin", s1, gorunen_ad=request.form.get("ad") or ad, olusturan="kurulum")
            kullanicilar.guncelle(AYAR, ad, sifre_degistir=False)
            db.denetim_yaz(baglanti(), ad, "ilk_admin", ip=ip())
            flash("Super admin olusturuldu. Simdi giris yapin.")
            return redirect(url_for("giris"))
    return render_template("kurulum_admin.html", hata=hata, bot_klasor=AYAR["BOT_KLASOR"], bekle=bekle, dosya=kullanicilar.yol(AYAR))


# ==================== giris ====================
@app.route("/giris", methods=["GET", "POST"])
def giris():
    hata = None
    if request.method == "POST":
        ad = (request.form.get("kullanici") or "").strip().lower()
        sifre = request.form.get("sifre") or ""
        u, hata = kullanicilar.dogrula(AYAR, ad, sifre)
        c = baglanti()
        if u:
            session.clear()
            session.permanent = True
            session["kad"] = u["kullanici_adi"]
            session["csrf"] = secrets.token_hex(16)
            db.denetim_yaz(c, u["kullanici_adi"], "giris", ip=ip())
            return redirect(request.args.get("sonraki") or url_for("ana"))
        db.denetim_yaz(c, ad, "giris_hata", ip=ip())
        time.sleep(0.8)
    return render_template("giris.html", hata=hata)


@app.route("/cikis")
def cikis():
    if g.get("k"):
        db.denetim_yaz(baglanti(), g.k["kullanici_adi"], "cikis", ip=ip())
    session.clear()
    return redirect(url_for("giris"))


@app.route("/sifre", methods=["GET", "POST"])
@giris_gerekli
def sifre_degistir():
    hata = None
    if request.method == "POST":
        eski, yeni, yeni2 = request.form.get("eski", ""), request.form.get("yeni", ""), request.form.get("yeni2", "")
        u, _ = kullanicilar.dogrula(AYAR, g.k["kullanici_adi"], eski)
        if not u:
            hata = "Eski sifre hatali."
        elif len(yeni) < 8:
            hata = "Yeni sifre en az 8 karakter olmali."
        elif yeni != yeni2:
            hata = "Yeni sifreler ayni degil."
        else:
            kullanicilar.guncelle(AYAR, g.k["kullanici_adi"], sifre=yeni, sifre_degistir=False)
            db.denetim_yaz(baglanti(), g.k["kullanici_adi"], "sifre_degisti", ip=ip())
            flash("Sifre degistirildi.")
            return redirect(url_for("ana"))
    return render_template("sifre.html", hata=hata)


# ==================== ana sayfa ====================
def durum_bilgisi():
    c = baglanti()
    son = db.ayar_al(c, "son_ice_aktarim")
    son = json.loads(son) if son else None
    excel_mtime = None
    try:
        excel_mtime = datetime.fromtimestamp(os.path.getmtime(AYAR["EXCEL"])).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return {"son_ice_aktarim": son, "excel_mtime": excel_mtime, "log_son": log_oku.son_satir_zamani(AYAR["LOG_DOSYA"]),
            "bot": bot_yonetim.bot_calisiyor_mu(AYAR), "kuyruk_bekleyen": kuyruk.bekleyen_sayisi(c),
            "bekleyen_islem": c.execute("SELECT COUNT(*) FROM kayitlar WHERE bekleyen_islem IS NOT NULL").fetchone()[0],
            "istemci": kuyruk.istemci_adi(AYAR), "bot_klasor": AYAR["BOT_KLASOR"], "surum": SURUM}


@app.route("/")
@giris_gerekli
def ana():
    c = baglanti()
    izinli = yetki.izinli_projeler(g.yk, projeler())
    kartlar = []
    for p in izinli:
        r = c.execute("""SELECT SUM(CASE WHEN kt=0 AND silindi=0 AND excel_durum='var' THEN 1 ELSE 0 END) bekleyen,
                                SUM(CASE WHEN kt=1 AND silindi=0 AND excel_durum='var' THEN 1 ELSE 0 END) onayli,
                                SUM(CASE WHEN silindi=1 OR excel_durum='silinmis' THEN 1 ELSE 0 END) silinen,
                                SUM(CASE WHEN date(tarih)=date('now','localtime') AND silindi=0 THEN 1 ELSE 0 END) bugun,
                                COUNT(*) toplam FROM kayitlar WHERE proje=?""", (p,)).fetchone()
        kartlar.append({"proje": p, **{k: r[k] or 0 for k in r.keys()}})
    return render_template("ana.html", kartlar=kartlar, durum=durum_bilgisi())


# ==================== kayit listesi ====================
def _filtre_sql(args, izinli):
    where, par = ["1=1"], []
    projeler_sec = [p for p in args.getlist("proje") if p in izinli] or izinli
    if not projeler_sec:
        return "1=0", [], {}
    where.append("proje IN (%s)" % ",".join("?" * len(projeler_sec)))
    par += projeler_sec
    durum = args.get("durum", "bekleyen")
    if durum == "bekleyen":
        where.append("kt=0 AND silindi=0 AND excel_durum='var'")
    elif durum == "onayli":
        where.append("kt=1 AND silindi=0 AND excel_durum='var'")
    elif durum == "silinen":
        where.append("(silindi=1 OR excel_durum='silinmis')")
    elif durum == "hepsi":
        pass
    kat = (args.get("kategori") or "").strip()
    if kat:
        where.append("upper(kategori)=?")
        par.append(kat.upper())
    q = (args.get("q") or "").strip()
    if q:
        where.append("(personel=? OR uye_id=? OR ana_uye_id=? OR uye_id LIKE ? OR ana_uye_id LIKE ? OR link LIKE ?)")
        par += [q, q, q, f"%{q}%", f"%{q}%", f"%{q}%"]
    ekleyen = (args.get("ekleyen") or "").strip()
    if ekleyen:
        where.append("(ekleyen_ad LIKE ? OR ekleyen_id=?)")
        par += [f"%{ekleyen}%", ekleyen]
    t1, t2 = (args.get("tarih1") or "").strip(), (args.get("tarih2") or "").strip()
    if t1:
        where.append("tarih >= ?")
        par.append(t1 + " 00:00:00")
    if t2:
        where.append("tarih <= ?")
        par.append(t2 + " 23:59:59")
    if args.get("tarihsiz") == "1":
        where.append("tarih IS NULL")
    return " AND ".join(where), par, {"proje": projeler_sec, "durum": durum, "kategori": kat, "q": q, "ekleyen": ekleyen, "tarih1": t1, "tarih2": t2}


def kayit_sozluk(r):
    d = dict(r)
    d["gorsel_var"] = bool(d.get("gorsel_dosya")) or d.get("link_turu") in ("gyazo", "onedrive", "snappark", "teamzone", "diger")
    d["renk"] = renk(d["proje"])
    d["izin_kt"] = kayit_izin(d, "kt")
    d["izin_duzenle"] = kayit_izin(d, "duzenle")
    d["izin_sil"] = kayit_izin(d, "sil")
    d["geri_al_olur"] = bool(d.get("silindi")) and d.get("bekleyen_islem") != "sil"
    d["dis_link"] = d["link"] if (d.get("link") or "").startswith("http") else None
    return d


@app.route("/kayitlar")
@giris_gerekli
def kayitlar():
    c = baglanti()
    izinli = yetki.izinli_projeler(g.yk, projeler())
    where, par, f = _filtre_sql(request.args, izinli)
    gorunum = request.args.get("gorunum", "kart")
    sayfa = max(1, int(request.args.get("s", 1) or 1))
    boy = int(AYAR["SAYFA_BOYU"])
    toplam = c.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {where}", par).fetchone()[0]
    rows = c.execute(f"SELECT * FROM kayitlar WHERE {where} ORDER BY COALESCE(tarih,'0000') DESC, id DESC LIMIT ? OFFSET ?", (*par, boy, (sayfa - 1) * boy)).fetchall()
    kategoriler = [r[0] for r in c.execute("SELECT DISTINCT upper(kategori) FROM kayitlar WHERE kategori<>'' ORDER BY 1").fetchall()]
    sayac = {}
    for d in ("bekleyen", "onayli", "silinen", "hepsi"):
        a = request.args.to_dict(flat=False); a["durum"] = [d]
        w2, p2, _ = _filtre_sql(MultiDict(a), izinli)
        sayac[d] = c.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {w2}", p2).fetchone()[0]
    return render_template("kayitlar.html", kayitlar=[kayit_sozluk(r) for r in rows], toplam=toplam, sayfa=sayfa, sayfa_sayisi=max(1, (toplam + boy - 1) // boy),
                           f=f, izinli=izinli, kategoriler=kategoriler, gorunum=gorunum, sayac=sayac)


@app.route("/kayit/<int:kid>")
@giris_gerekli
def kayit_json(kid):
    r = baglanti().execute("SELECT * FROM kayitlar WHERE id=?", (kid,)).fetchone()
    if not r or not kayit_izin(r, "oku"):
        abort(404)
    d = kayit_sozluk(r)
    d["gorsel_url"] = url_for("gorsel_goster", kid=kid) if kayit_izin(r, "gorsel") else None
    d["kucuk_url"] = url_for("kucuk_goster", kid=kid) if kayit_izin(r, "gorsel") else None
    yol, kaynak = COZUCU.yerel_dosya(d)
    d["gorsel_kaynak"] = kaynak if yol else ("gyazo_dis" if d["link_turu"] == "gyazo" else ("dis_link" if d["dis_link"] else "yok"))
    d["gecmis"] = [dict(x) for x in baglanti().execute("SELECT zaman,kullanici,islem,eski,yeni FROM denetim WHERE anahtar=? ORDER BY id DESC LIMIT 30", (r["anahtar"],)).fetchall()]
    return jsonify(d)


def _kayit_al(kid, eylem):
    r = baglanti().execute("SELECT * FROM kayitlar WHERE id=?", (kid,)).fetchone()
    if not r or not kayit_izin(r, eylem):
        abort(403)
    return r


def _parmak(r):
    return {"personel": r["personel"] or "", "uye": r["uye_id"] or "", "ana": r["ana_uye_id"] or "", "tip": r["tip"] or "", "kategori": r["kategori"] or "", "tarih": r["tarih_ham"] or r["tarih"] or ""}


@app.route("/kayit/<int:kid>/kt", methods=["POST"])
@giris_gerekli
def kayit_kt(kid):
    r = _kayit_al(kid, "kt")
    yeni = 1 if request.form.get("deger", "1") == "1" else 0
    c = baglanti()
    qid = kuyruk.ekle(AYAR, "kt", r["proje"], r["link"], _parmak(r), {"kt": bool(yeni), "satir": r["excel_satir"]}, g.k["kullanici_adi"], r["anahtar"])
    c.execute("UPDATE kayitlar SET kt=?, kt_kaynak='panel', kt_kim=?, kt_zaman=?, bekleyen_islem='kt', bekleyen_id=?, bekleyen_hata=NULL, guncelleme=? WHERE id=?",
              (yeni, g.k["kullanici_adi"], simdi(), qid, simdi(), kid))
    db.denetim_yaz(c, g.k["kullanici_adi"], "onayla" if yeni else "onay_kaldir", r["proje"], r["anahtar"], r["kt"], yeni, ip())
    return jsonify({"ok": True, "kt": yeni})


@app.route("/kayit/<int:kid>/duzenle", methods=["POST"])
@giris_gerekli
def kayit_duzenle(kid):
    r = _kayit_al(kid, "duzenle")
    alanlar = {}
    for k, kolon in (("personel", "personel"), ("uye_id", "uye_id"), ("ana_uye_id", "ana_uye_id"), ("tip", "tip"), ("kategori", "kategori"), ("aciklama", "aciklama")):
        if k in request.form:
            alanlar[kolon] = (request.form.get(k) or "").strip()[:200]
    if not alanlar:
        return jsonify({"ok": False, "hata": "degisiklik yok"})
    if "kategori" in alanlar:
        alanlar["kategori"] = alanlar["kategori"].upper()   # bot Excel'e buyuk harfle yazar
    eski = {k: r[k] for k in alanlar}
    alanlar = {k: v for k, v in alanlar.items() if (eski[k] or "") != v}   # yalnizca DEGISEN alanlar gider (baska adminin duzeltmesi ezilmez)
    if not alanlar:
        return jsonify({"ok": True, "degisiklik": False})
    eski = {k: eski[k] for k in alanlar}
    c = baglanti()
    ad_haritasi = {"personel": "personel", "uye_id": "uye", "ana_uye_id": "ana", "tip": "tip", "kategori": "kategori", "aciklama": "aciklama"}
    deger = {ad_haritasi[k]: v for k, v in alanlar.items()}
    deger["satir"] = r["excel_satir"]
    qid = kuyruk.ekle(AYAR, "duzenle", r["proje"], r["link"], _parmak(r), deger, g.k["kullanici_adi"], r["anahtar"])
    sets = ", ".join(f"{k}=?" for k in alanlar)
    c.execute(f"UPDATE kayitlar SET {sets}, bekleyen_islem='duzenle', bekleyen_id=?, bekleyen_hata=NULL, guncelleme=? WHERE id=?", (*alanlar.values(), qid, simdi(), kid))
    db.denetim_yaz(c, g.k["kullanici_adi"], "duzenle", r["proje"], r["anahtar"], json.dumps(eski, ensure_ascii=False), json.dumps(alanlar, ensure_ascii=False), ip())
    return jsonify({"ok": True})


@app.route("/kayit/<int:kid>/sil", methods=["POST"])
@giris_gerekli
def kayit_sil(kid):
    r = _kayit_al(kid, "sil")
    c = baglanti()
    qid = kuyruk.ekle(AYAR, "sil", r["proje"], r["link"], _parmak(r), {"satir": r["excel_satir"]}, g.k["kullanici_adi"], r["anahtar"])
    c.execute("UPDATE kayitlar SET silindi=1, silen=?, silme_zamani=?, bekleyen_islem='sil', bekleyen_id=?, bekleyen_hata=NULL, guncelleme=? WHERE id=?",
              (g.k["kullanici_adi"], simdi(), qid, simdi(), kid))
    db.denetim_yaz(c, g.k["kullanici_adi"], "sil", r["proje"], r["anahtar"], json.dumps(_parmak(r), ensure_ascii=False), None, ip())
    return jsonify({"ok": True})


@app.route("/kayit/<int:kid>/geri-al", methods=["POST"])
@giris_gerekli
def kayit_geri_al(kid):
    r = _kayit_al(kid, "sil")
    if r["bekleyen_islem"] == "sil":
        return jsonify({"ok": False, "hata": "Silme islemi henuz bota ulasmadi; bot cevaplayinca geri alabilirsiniz."})
    c = baglanti()
    degerler = [r["personel"] or "", r["uye_id"] or "", r["ana_uye_id"] or "", r["tip"] or "", r["link"] or "", (r["kategori"] or "").upper(), r["tarih_ham"] or r["tarih"] or ""]
    qid = kuyruk.ekle(AYAR, "ekle", r["proje"], r["link"], _parmak(r), {"degerler": degerler, "kt": bool(r["kt"]), "gorsel2": r["gorsel2"] or "", "aciklama": r["aciklama"] or ""}, g.k["kullanici_adi"], r["anahtar"])
    c.execute("UPDATE kayitlar SET silindi=0, silen=NULL, silme_zamani=NULL, bekleyen_islem='geri_al', bekleyen_id=?, bekleyen_hata=NULL, guncelleme=? WHERE id=?", (qid, simdi(), kid))
    db.denetim_yaz(c, g.k["kullanici_adi"], "geri_al", r["proje"], r["anahtar"], None, json.dumps(degerler, ensure_ascii=False), ip())
    return jsonify({"ok": True})


# ==================== gorsel ====================
def _gorsel_yolu(kid, kucuk=False):
    r = baglanti().execute("SELECT * FROM kayitlar WHERE id=?", (kid,)).fetchone()
    if not r or not kayit_izin(r, "gorsel"):
        abort(404)
    d = dict(r)
    yol, kaynak = COZUCU.yerel_dosya(d)
    if not yol and d["link_turu"] == "gyazo":
        yol = COZUCU.gyazo_indir(d)
    if not yol:
        return None, d
    if kucuk:
        yol = COZUCU.kucuk(d, yol)
    return yol, d


@app.route("/gorsel/<int:kid>")
@giris_gerekli
def gorsel_goster(kid):
    yol, d = _gorsel_yolu(kid)
    if not yol:
        if (d.get("link") or "").startswith("http"):
            return redirect(d["link"])
        abort(404)
    db.denetim_yaz(baglanti(), g.k["kullanici_adi"], "gorsel_ac", d["proje"], d["anahtar"], ip=ip())
    resp = send_file(yol, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@app.route("/kucuk/<int:kid>")
@giris_gerekli
def kucuk_goster(kid):
    yol, d = _gorsel_yolu(kid, kucuk=True)
    if not yol:
        abort(404)
    resp = send_file(yol, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


# ==================== yonetim: kullanicilar ====================
def _rastgele_sifre(n=10):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


@app.route("/yonetim/kullanicilar", methods=["GET", "POST"])
@admin_gerekli
def yonetim_kullanicilar():
    c = baglanti()
    mesaj = None
    if request.method == "POST":
        islem = request.form.get("islem")
        try:
            if islem == "ekle":
                ad = (request.form.get("kullanici") or "").strip().lower()
                yk = (request.form.get("yetki") or "").strip()
                if not kullanici_adi_gecerli(ad):
                    raise ValueError("Kullanici adi harf/rakam olmali (en fazla 40 karakter).")
                sifre = request.form.get("sifre") or _rastgele_sifre()
                kullanicilar.ekle(AYAR, ad, yk, sifre, gorunen_ad=request.form.get("ad") or ad, olusturan=g.k["kullanici_adi"])
                db.denetim_yaz(c, g.k["kullanici_adi"], "kullanici_ekle", yeni=f"{ad} [{yk}]", ip=ip())
                mesaj = f"Kullanici acildi: {ad}  gecici sifre: {sifre}"
            else:
                ad = (request.form.get("kullanici_adi") or "").strip().lower()
                u = kullanicilar.bul(AYAR, ad)
                if not u:
                    mesaj = "Kullanici bulunamadi."
                elif islem == "yetki":
                    yk = (request.form.get("yetki") or "").strip()
                    kullanicilar.guncelle(AYAR, ad, yetki=yk)
                    db.denetim_yaz(c, g.k["kullanici_adi"], "yetki_degisti", eski=f"{ad} [{u['yetki']}]", yeni=yk, ip=ip())
                    mesaj = "Yetki guncellendi."
                elif islem == "sifre":
                    sifre = _rastgele_sifre()
                    kullanicilar.guncelle(AYAR, ad, sifre=sifre, sifre_degistir=True)
                    db.denetim_yaz(c, g.k["kullanici_adi"], "sifre_sifirla", yeni=ad, ip=ip())
                    mesaj = f"{ad} icin gecici sifre: {sifre}"
                elif islem == "pasif":
                    if ad == g.k["kullanici_adi"]:
                        mesaj = "Kendi hesabinizi pasife alamazsiniz."
                    else:
                        yeni = not u.get("aktif", True)
                        kullanicilar.guncelle(AYAR, ad, aktif=yeni)
                        db.denetim_yaz(c, g.k["kullanici_adi"], "kullanici_aktif" if yeni else "kullanici_pasif", yeni=ad, ip=ip())
                        mesaj = "Hesap " + ("aktif." if yeni else "pasif.")
        except (ValueError, IOError) as e:
            mesaj = f"Hata: {e}"
    liste = [dict(u) | {"ozet": yetki.ozet(u.get("yetki", ""))} for u in kullanicilar.hepsi(AYAR)]
    return render_template("kullanicilar.html", kullanicilar=liste, mesaj=mesaj, tum_projeler=projeler(), dosya=kullanicilar.yol(AYAR))


# ==================== yonetim: bot ====================
@app.route("/bot", methods=["GET", "POST"])
@admin_gerekli
def bot_sayfasi():
    c = baglanti()
    mesaj = None
    if request.method == "POST":
        islem = request.form.get("islem")
        tg = (request.form.get("tg_id") or "").strip()
        ad = (request.form.get("ad") or "").strip()
        kim = g.k["kullanici_adi"]
        try:
            kuyrukta = True
            if islem == "onayla":
                bot_yonetim.onayla(AYAR, c, tg, ad or tg, kim)
            elif islem == "onay_kaldir":
                bot_yonetim.onay_kaldir(AYAR, c, tg, kim)
            elif islem == "engelle":
                bot_yonetim.engelle(AYAR, c, tg, ad, request.form.get("sebep") or "panel", kim)
            elif islem == "engel_kaldir":
                bot_yonetim.engel_kaldir(AYAR, c, tg, kim)
            elif islem == "bakim_ac":
                bot_yonetim.bakim_modu_ayarla(AYAR, c, True, kim)
            elif islem == "bakim_kapat":
                bot_yonetim.bakim_modu_ayarla(AYAR, c, False, kim)
            elif islem == "gyazo_bakim_ac":
                bot_yonetim.gyazo_bakim_ayarla(AYAR, c, True, kim)
            elif islem == "gyazo_bakim_kapat":
                bot_yonetim.gyazo_bakim_ayarla(AYAR, c, False, kim)
            elif islem == "oturum_temizle":
                bot_yonetim.oturum_temizle(AYAR, c, tg or None, kim)
            elif islem == "kategori_ekle":
                bot_yonetim.kategori_kaydet(AYAR, c, (request.form.get("code") or "").strip().lower(), (request.form.get("label") or "").strip(), request.form.get("mode") or "tek_uye", kim)
            elif islem == "kategori_sil":
                bot_yonetim.kategori_sil(AYAR, c, request.form.get("code") or "", kim)
            elif islem == "yedek":
                bot_yonetim.yedek_al(AYAR, c, kim)
            elif islem == "yenile":
                kuyrukta = False
                rapor = ice_aktar.calistir(AYAR, c, AYAR["ONBELLEK"], COZUCU, zorla=True)
                mesaj = f"Excel yeniden okundu: {rapor.get('sayfalar')} yeni={rapor.get('yeni')} degisen={rapor.get('degisen')} {('HATA: ' + rapor['hata']) if rapor.get('hata') else ''}"
            else:
                kuyrukta = False
                mesaj = "Bilinmeyen islem."
            if kuyrukta:
                mesaj = "Islem bota iletildi; bot uygulayinca asagidaki 'Son islemler' listesinde 'ok' olur (bot acikken birkac saniye, OneDrive uzerinden 1-2 dakika)."
            db.denetim_yaz(c, kim, f"bot_{islem}", yeni=f"{tg} {ad}".strip() or None, ip=ip())
        except Exception as e:
            mesaj = f"Hata: {e}"
    return render_template("bot.html", mesaj=mesaj, durum=durum_bilgisi(), tg_kullanicilar=bot_yonetim.telegram_kullanicilari(AYAR),
                           kategoriler=bot_yonetim.kategoriler(AYAR), bakim=bot_yonetim.bakim_modu(AYAR), gyazo_bakim=bot_yonetim.gyazo_bakim(AYAR),
                           oturumlar=bot_yonetim.oturumlar(AYAR), log=bot_yonetim.son_log(AYAR, 150), hatalar=bot_yonetim.son_log(AYAR, 40, True),
                           cfg=bot_yonetim.config(AYAR), islemler=bot_yonetim.son_islemler(c))


@app.route("/bot/islemler.json")
@admin_gerekli
def bot_islemler_json():
    return jsonify({"islemler": bot_yonetim.son_islemler(baglanti()), "bekleyen": kuyruk.bekleyen_sayisi(baglanti())})


@app.route("/denetim")
@admin_gerekli
def denetim():
    c = baglanti()
    q = (request.args.get("q") or "").strip()
    rows = c.execute("SELECT * FROM denetim WHERE (? = '' OR kullanici LIKE ? OR islem LIKE ? OR anahtar LIKE ?) ORDER BY id DESC LIMIT 500", (q, f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    return render_template("denetim.html", kayitlar=[dict(r) for r in rows], q=q)


@app.route("/durum.json")
@giris_gerekli
def durum_json():
    return jsonify(durum_bilgisi())


@app.route("/bildirim.json")
@giris_gerekli
def bildirim_json():
    """Canli yenileme: son goruldugunden beri eklenen kayitlar (kullanicinin yetkili oldugu projeler) + guncel sayaclar + degisiklik damgasi."""
    c = baglanti()
    izinli = yetki.izinli_projeler(g.yk, projeler())
    try:
        son = int(request.args.get("son", -1))
    except ValueError:
        son = -1
    maks = c.execute("SELECT COALESCE(MAX(id),0) FROM kayitlar").fetchone()[0]
    yeni = []
    if son >= 0 and izinli and maks > son:
        q = f"""SELECT id, proje, personel, kategori, tarih, ekleyen_ad, kt FROM kayitlar
                WHERE id > ? AND proje IN ({",".join("?" * len(izinli))}) AND silindi=0 AND excel_durum='var'
                  AND COALESCE(tarih, ilk_gorulme) > datetime('now','localtime','-2 days')
                ORDER BY id DESC LIMIT 20"""
        yeni = [dict(r) for r in c.execute(q, (son, *izinli)).fetchall()]
    sayac = {}
    for r in c.execute("""SELECT proje, SUM(CASE WHEN kt=0 AND silindi=0 AND excel_durum='var' THEN 1 ELSE 0 END) bekleyen,
                                 SUM(CASE WHEN kt=1 AND silindi=0 AND excel_durum='var' THEN 1 ELSE 0 END) onayli,
                                 SUM(CASE WHEN silindi=1 OR excel_durum='silinmis' THEN 1 ELSE 0 END) silinen, COUNT(*) toplam
                          FROM kayitlar GROUP BY proje""").fetchall():
        if r["proje"] in izinli:
            sayac[r["proje"]] = {"bekleyen": r["bekleyen"] or 0, "onayli": r["onayli"] or 0, "silinen": r["silinen"] or 0, "toplam": r["toplam"]}
    return jsonify({"maks": maks, "yeni": yeni, "sayac": sayac, "degisiklik": db.ayar_al(c, "son_degisiklik"), "kuyruk_bekleyen": kuyruk.bekleyen_sayisi(c),
                    "bot": bot_yonetim.bot_calisiyor_mu(AYAR).get("canli")})


@app.route("/saglik")
def saglik():
    resp = app.make_response("OK")
    resp.headers["X-Kanit-Paneli"] = SURUM
    return resp


@app.errorhandler(403)
def _403(e):
    return render_template("hata.html", kod=403, mesaj="Bu islem icin yetkiniz yok."), 403


@app.errorhandler(404)
def _404(e):
    return render_template("hata.html", kod=404, mesaj="Bulunamadi."), 404


# ==================== arka plan ice aktarim ====================
def _ice_aktar_bir_kez():
    try:
        conn = db.baglan(AYAR["DB"])
        ice_aktar.calistir(AYAR, conn, AYAR["ONBELLEK"], COZUCU)
    except Exception as e:
        print("ice aktarim hatasi:", e)


def _arka_plan():
    conn = db.baglan(AYAR["DB"])
    while True:
        if bot_klasoru_mu(AYAR.get("BOT_KLASOR")):
            try:
                ice_aktar.calistir(AYAR, conn, AYAR["ONBELLEK"], COZUCU)
            except Exception as e:
                print("ice aktarim hatasi:", e)
            time.sleep(max(10, int(float(AYAR.get("YENILEME_SN", 30)))))
        else:
            time.sleep(10)


# ==================== komut satiri ====================
def komut(argv):
    if not argv or argv[0] in ("--ac",):
        return False
    if argv[0] == "--surum":
        print("KanitPaneli", SURUM)
        return True
    if not bot_klasoru_mu(AYAR.get("BOT_KLASOR")):
        print(f"Bot klasoru bulunamadi ({AYAR.get('BOT_KLASOR') or '-'}). Once paneli acip kurulum sayfasindan klasoru secin ya da {AYAR_YOL} icine BOT_KLASOR yazin.")
        return True
    if argv[0] == "kullanici-ekle" and len(argv) >= 3:
        ad, yk = argv[1].strip().lower(), argv[2]
        sifre = argv[3] if len(argv) > 3 else _rastgele_sifre()
        if kullanicilar.bul(AYAR, ad):
            kullanicilar.guncelle(AYAR, ad, yetki=yk, aktif=True)
            print(f"Kullanici zaten vardi; yetkisi guncellendi: {ad} [{yk}]")
        else:
            kullanicilar.ekle(AYAR, ad, yk, sifre, olusturan="komut")
            print(f"Kullanici acildi: {ad}   yetki: {yk}   gecici sifre: {sifre}")
        return True
    if argv[0] == "sifre-sifirla" and len(argv) >= 2:
        ad = argv[1].strip().lower()
        sifre = argv[2] if len(argv) > 2 else _rastgele_sifre()
        if kullanicilar.bul(AYAR, ad):
            kullanicilar.guncelle(AYAR, ad, sifre=sifre, sifre_degistir=True, aktif=True)
            print(f"Yeni gecici sifre ({ad}): {sifre}")
        else:
            print(f"Kullanici bulunamadi: {ad}")
        return True
    if argv[0] == "ice-aktar":
        c = db.baglan(AYAR["DB"])
        r = ice_aktar.calistir(AYAR, c, AYAR["ONBELLEK"], COZUCU)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return True
    if argv[0] == "kullanicilar":
        for u in kullanicilar.hepsi(AYAR):
            print(f"{u['kullanici_adi']:20} {('aktif' if u.get('aktif', True) else 'PASIF'):6} {u.get('yetki', '')}")
        return True
    return False


def panel_calisiyor_mu(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/saglik", timeout=2) as r:
            return r.headers.get("X-Kanit-Paneli") is not None
    except Exception:
        return False


def calistir():
    if sys.stdout is None or sys.stderr is None:
        # pythonw / gorev zamanlayici: konsol yok, ciktiyi dosyaya yaz
        try:
            f = open(os.path.join(VERI_KOK, "panel.log"), "a", encoding="utf-8")
            sys.stdout = sys.stdout or f
            sys.stderr = sys.stderr or f
        except Exception:
            pass
    if len(sys.argv) > 1 and komut(sys.argv[1:]):
        return
    port = int(AYAR["PORT"])
    url = f"http://127.0.0.1:{port}/"
    if panel_calisiyor_mu(port):
        print(f"Panel zaten acik: {url}  (tarayici aciliyor)")
        webbrowser.open(url)
        return
    conn = db.baglan(AYAR["DB"])
    if bot_klasoru_mu(AYAR.get("BOT_KLASOR")):
        try:
            n = kullanicilar.sqlite_tasi(AYAR, conn)
            if n:
                print(f"{n} kullanici ortak dosyaya tasindi: {kullanicilar.yol(AYAR)}")
        except Exception as e:
            print("kullanici tasima hatasi:", e)
    threading.Thread(target=_arka_plan, daemon=True).start()
    print("=" * 60)
    print(f"  KANIT PANELI {SURUM}")
    print(f"  Adres      : {url}")
    print(f"  Bot klasoru: {AYAR.get('BOT_KLASOR') or '(bulunamadi - tarayicida secilecek)'}")
    print(f"  Veri       : {VERI_KOK}")
    print("  Bu pencere acik kaldigi surece panel calisir. Kapatmak icin pencereyi kapatin.")
    print("=" * 60)
    if DONMUS or "--ac" in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=AYAR["DINLE"], port=port, threads=8)
    except ImportError:
        app.run(host=AYAR["DINLE"], port=port)
    except OSError as e:
        print(f"! Port {port} kullanilamiyor ({e}). Baska bir program kullaniyor olabilir; {AYAR_YOL} icinde PORT degistirin.")
        if DONMUS:
            input("Kapatmak icin Enter...")


if __name__ == "__main__":
    calistir()

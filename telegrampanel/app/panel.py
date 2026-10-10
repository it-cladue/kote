# -*- coding: utf-8 -*-
"""Telegram kanit botu - web paneli (Flask). Calistirma: python -m app.panel  (ya da BASLAT.bat)"""
import os, sys, json, secrets, threading, time, functools, string, random
from datetime import datetime, timedelta
from flask import Flask, g, request, session, redirect, url_for, render_template, jsonify, abort, send_file, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.datastructures import MultiDict

from . import db, yetki, excel_oku, ice_aktar, gorsel, kuyruk, bot_yonetim, log_oku

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AYAR_YOL = os.environ.get("PANEL_AYAR", os.path.join(KOK, "panel_ayar.json"))
VARSAYILAN_RENK = {"PP": "#A6A6A6", "PA": "#4472C4", "OF": "#FFFF00", "HI": "#FF0000", "VI": "#7030A0", "GA": "#00B050", "BETA": "#FFA500"}


def ayar_yukle():
    ham = {}
    if os.path.exists(AYAR_YOL):
        with open(AYAR_YOL, encoding="utf-8-sig") as f:
            ham = json.load(f)
    if not ham.get("GIZLI_ANAHTAR"):
        # Dosyaya yalnizca kullanicinin yazdigi alanlar + gizli anahtar yazilir; turetilen yollar (EXCEL vb.) yazilmaz,
        # yoksa BOT_KLASOR sonradan degistirilince eski turetilmis yollar dosyada kalir.
        ham["GIZLI_ANAHTAR"] = secrets.token_hex(32)
        try:
            with open(AYAR_YOL, "w", encoding="utf-8") as f:
                json.dump(ham, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    a = dict(ham)
    a.setdefault("BOT_KLASOR", os.path.dirname(KOK))
    a.setdefault("EXCEL", os.path.join(a["BOT_KLASOR"], "telegrambot_gyazo.xlsx"))
    a.setdefault("LOG_DOSYA", os.path.join(a["BOT_KLASOR"], "bot_log.txt"))
    a.setdefault("GORSEL_KLASOR", os.path.join(a["BOT_KLASOR"], "gorseller"))
    a.setdefault("DB", os.path.join(KOK, "panel.db"))
    a.setdefault("ONBELLEK", os.path.join(KOK, "tmp"))
    a.setdefault("YENILEME_DK", 3)
    a.setdefault("DINLE", "127.0.0.1")
    a.setdefault("PORT", 8080)
    a.setdefault("PROJE_RENK", VARSAYILAN_RENK)
    a.setdefault("SUTUN_HARITASI", {})
    a.setdefault("SAYFA_BOYU", 48)
    return a


AYAR = ayar_yukle()
_yerel = threading.local()


def baglanti():
    c = getattr(_yerel, "conn", None)
    if c is None:
        c = db.baglan(AYAR["DB"])
        _yerel.conn = c
    return c


COZUCU = gorsel.GorselCozucu(AYAR, AYAR["ONBELLEK"])
app = Flask(__name__, template_folder=os.path.join(KOK, "app", "templates"), static_folder=os.path.join(KOK, "app", "static"))
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


def kullanici_yukle():
    kid = session.get("kid")
    if not kid:
        return None
    r = baglanti().execute("SELECT * FROM panel_kullanicilari WHERE id=? AND aktif=1", (kid,)).fetchone()
    return dict(r) if r else None


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


def metin_rengi(hex_renk):
    """Arka plan rengine gore okunur yazi rengi (OF sari -> siyah yazi)"""
    try:
        h = (hex_renk or "#999999").lstrip("#")
        r, gg, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return "#111111" if (0.299 * r + 0.587 * gg + 0.114 * b) > 150 else "#ffffff"
    except Exception:
        return "#ffffff"


def url_degistir(**kw):
    """Mevcut sorgu parametrelerini koruyarak bazilarini degistir (sayfa numarasi sifirlanir)."""
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


@app.context_processor
def _ctx():
    return {"k": g.get("k"), "yk": g.get("yk"), "renk": renk, "metin_rengi": metin_rengi, "url_degistir": url_degistir, "csrf": session.get("csrf", ""),
            "projeler": projeler, "izin": lambda p, e: yetki.izin(g.yk, p, e), "AYAR": AYAR, "simdi": simdi}


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


# ==================== giris ====================
@app.route("/giris", methods=["GET", "POST"])
def giris():
    hata = None
    if request.method == "POST":
        ad = (request.form.get("kullanici") or "").strip().lower()
        sifre = request.form.get("sifre") or ""
        c = baglanti()
        u = c.execute("SELECT * FROM panel_kullanicilari WHERE lower(kullanici_adi)=?", (ad,)).fetchone()
        kilitli = u and u["kilit_bitis"] and u["kilit_bitis"] > simdi()
        if u and u["aktif"] and not kilitli and check_password_hash(u["sifre_hash"], sifre):
            session.clear()
            session.permanent = True
            session["kid"] = u["id"]
            session["csrf"] = secrets.token_hex(16)
            c.execute("UPDATE panel_kullanicilari SET hatali_giris=0, kilit_bitis=NULL, son_giris=? WHERE id=?", (simdi(), u["id"]))
            db.denetim_yaz(c, u["kullanici_adi"], "giris", ip=ip())
            return redirect(request.args.get("sonraki") or url_for("ana"))
        hata = "Kullanici adi veya sifre hatali."
        if u:
            n = (u["hatali_giris"] or 0) + 1
            kb = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S") if n >= 5 else u["kilit_bitis"]
            c.execute("UPDATE panel_kullanicilari SET hatali_giris=?, kilit_bitis=? WHERE id=?", (0 if n >= 5 else n, kb, u["id"]))
            db.denetim_yaz(c, u["kullanici_adi"], "giris_hata", ip=ip())
        time.sleep(0.8)
    return render_template("giris.html", hata=hata)


@app.route("/cikis")
def cikis():
    if g.k:
        db.denetim_yaz(baglanti(), g.k["kullanici_adi"], "cikis", ip=ip())
    session.clear()
    return redirect(url_for("giris"))


@app.route("/sifre", methods=["GET", "POST"])
@giris_gerekli
def sifre_degistir():
    hata = None
    if request.method == "POST":
        eski, yeni, yeni2 = request.form.get("eski", ""), request.form.get("yeni", ""), request.form.get("yeni2", "")
        c = baglanti()
        u = c.execute("SELECT * FROM panel_kullanicilari WHERE id=?", (g.k["id"],)).fetchone()
        if not check_password_hash(u["sifre_hash"], eski):
            hata = "Eski sifre hatali."
        elif len(yeni) < 8:
            hata = "Yeni sifre en az 8 karakter olmali."
        elif yeni != yeni2:
            hata = "Yeni sifreler ayni degil."
        else:
            c.execute("UPDATE panel_kullanicilari SET sifre_hash=?, sifre_degistir=0 WHERE id=?", (generate_password_hash(yeni), g.k["id"]))
            db.denetim_yaz(c, g.k["kullanici_adi"], "sifre_degisti", ip=ip())
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
            "bot": bot_yonetim.bot_calisiyor_mu(AYAR), "kuyruk_bekleyen": kuyruk.bekleyen_sayisi(AYAR),
            "bekleyen_islem": c.execute("SELECT COUNT(*) FROM kayitlar WHERE bekleyen_islem IS NOT NULL").fetchone()[0]}


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
    eski = {k: r[k] for k in alanlar}
    if all((eski[k] or "") == alanlar[k] for k in alanlar):
        return jsonify({"ok": True, "degisiklik": False})
    c = baglanti()
    qid = kuyruk.ekle(AYAR, "duzenle", r["proje"], r["link"], _parmak(r),
                      {"personel": alanlar.get("personel", r["personel"]), "uye": alanlar.get("uye_id", r["uye_id"]), "ana": alanlar.get("ana_uye_id", r["ana_uye_id"]),
                       "tip": alanlar.get("tip", r["tip"]), "kategori": alanlar.get("kategori", r["kategori"]), "aciklama": alanlar.get("aciklama", r["aciklama"]), "satir": r["excel_satir"]},
                      g.k["kullanici_adi"], r["anahtar"])
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
    c = baglanti()
    degerler = [r["personel"] or "", r["uye_id"] or "", r["ana_uye_id"] or "", r["tip"] or "", r["link"] or "", (r["kategori"] or "").upper(), r["tarih"] or r["tarih_ham"] or ""]
    qid = kuyruk.ekle(AYAR, "ekle", r["proje"], r["link"], _parmak(r), {"degerler": degerler, "kt": bool(r["kt"])}, g.k["kullanici_adi"], r["anahtar"])
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
        if d.get("link", "").startswith("http"):
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
        if islem == "ekle":
            ad = (request.form.get("kullanici") or "").strip().lower()
            yk = (request.form.get("yetki") or "").strip()
            if not ad or not yk:
                mesaj = "Kullanici adi ve yetki gerekli."
            elif c.execute("SELECT 1 FROM panel_kullanicilari WHERE lower(kullanici_adi)=?", (ad,)).fetchone():
                mesaj = "Bu kullanici adi zaten var."
            else:
                sifre = request.form.get("sifre") or _rastgele_sifre()
                c.execute("INSERT INTO panel_kullanicilari(kullanici_adi,ad,sifre_hash,yetki,aktif,sifre_degistir,olusturma) VALUES(?,?,?,?,1,1,?)",
                          (ad, request.form.get("ad") or ad, generate_password_hash(sifre), yk, simdi()))
                db.denetim_yaz(c, g.k["kullanici_adi"], "kullanici_ekle", yeni=f"{ad} [{yk}]", ip=ip())
                mesaj = f"Kullanici acildi: {ad}  gecici sifre: {sifre}"
        else:
            uid = int(request.form.get("id") or 0)
            u = c.execute("SELECT * FROM panel_kullanicilari WHERE id=?", (uid,)).fetchone()
            if u:
                if islem == "yetki":
                    yk = (request.form.get("yetki") or "").strip()
                    c.execute("UPDATE panel_kullanicilari SET yetki=? WHERE id=?", (yk, uid))
                    db.denetim_yaz(c, g.k["kullanici_adi"], "yetki_degisti", eski=f"{u['kullanici_adi']} [{u['yetki']}]", yeni=yk, ip=ip())
                    mesaj = "Yetki guncellendi."
                elif islem == "sifre":
                    sifre = _rastgele_sifre()
                    c.execute("UPDATE panel_kullanicilari SET sifre_hash=?, sifre_degistir=1, hatali_giris=0, kilit_bitis=NULL WHERE id=?", (generate_password_hash(sifre), uid))
                    db.denetim_yaz(c, g.k["kullanici_adi"], "sifre_sifirla", yeni=u["kullanici_adi"], ip=ip())
                    mesaj = f"{u['kullanici_adi']} icin gecici sifre: {sifre}"
                elif islem == "pasif":
                    yeni = 0 if u["aktif"] else 1
                    if uid == g.k["id"]:
                        mesaj = "Kendi hesabinizi pasife alamazsiniz."
                    else:
                        c.execute("UPDATE panel_kullanicilari SET aktif=? WHERE id=?", (yeni, uid))
                        db.denetim_yaz(c, g.k["kullanici_adi"], "kullanici_aktif" if yeni else "kullanici_pasif", yeni=u["kullanici_adi"], ip=ip())
                        mesaj = "Hesap " + ("aktif." if yeni else "pasif.")
    kullanicilar = [dict(r) | {"ozet": yetki.ozet(r["yetki"])} for r in c.execute("SELECT * FROM panel_kullanicilari ORDER BY kullanici_adi").fetchall()]
    return render_template("kullanicilar.html", kullanicilar=kullanicilar, mesaj=mesaj, tum_projeler=projeler())


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
        try:
            if islem == "onayla":
                bot_yonetim.onayla(AYAR, tg, ad or tg); mesaj = f"{tg} onaylandi."
            elif islem == "onay_kaldir":
                bot_yonetim.onay_kaldir(AYAR, tg); mesaj = f"{tg} onaylilardan cikarildi."
            elif islem == "engelle":
                bot_yonetim.engelle(AYAR, tg, ad, request.form.get("sebep") or "panel", g.k["kullanici_adi"]); mesaj = f"{tg} engellendi."
            elif islem == "engel_kaldir":
                bot_yonetim.engel_kaldir(AYAR, tg); mesaj = f"{tg} engeli kaldirildi."
            elif islem == "bakim_ac":
                bot_yonetim.bakim_modu_ayarla(AYAR, True); mesaj = "Bakim modu ACILDI."
            elif islem == "bakim_kapat":
                bot_yonetim.bakim_modu_ayarla(AYAR, False); mesaj = "Bakim modu kapatildi."
            elif islem == "gyazo_bakim_ac":
                bot_yonetim.gyazo_bakim_ayarla(AYAR, True); mesaj = "Gyazo bakim modu ACILDI (gorseller diske kaydedilir)."
            elif islem == "gyazo_bakim_kapat":
                bot_yonetim.gyazo_bakim_ayarla(AYAR, False); mesaj = "Gyazo bakim modu kapatildi (Gyazo acik)."
            elif islem == "oturum_temizle":
                bot_yonetim.oturum_temizle(AYAR, tg or None); mesaj = "Oturum temizlendi."
            elif islem == "kategori_ekle":
                liste = [k for k in bot_yonetim.kategoriler(AYAR) if k.get("code") != request.form.get("code")]
                liste.append({"code": (request.form.get("code") or "").strip().lower(), "label": (request.form.get("label") or "").strip(), "mode": request.form.get("mode") or "tek_uye"})
                bot_yonetim.kategorileri_yaz(AYAR, liste); mesaj = "Kategori kaydedildi."
            elif islem == "kategori_sil":
                bot_yonetim.kategorileri_yaz(AYAR, [k for k in bot_yonetim.kategoriler(AYAR) if k.get("code") != request.form.get("code")]); mesaj = "Kategori silindi."
            elif islem == "yedek":
                hedef, kop = bot_yonetim.yedek_al(AYAR); mesaj = f"Yedek alindi: {hedef} ({len(kop)} dosya)"
            elif islem == "yenile":
                rapor = ice_aktar.calistir(AYAR, c, AYAR["ONBELLEK"], COZUCU); mesaj = f"Excel yeniden okundu: {rapor.get('sayfalar')} yeni={rapor.get('yeni')} degisen={rapor.get('degisen')} {('HATA: ' + rapor['hata']) if rapor.get('hata') else ''}"
            db.denetim_yaz(c, g.k["kullanici_adi"], f"bot_{islem}", yeni=f"{tg} {ad}".strip() or None, ip=ip())
        except Exception as e:
            mesaj = f"Hata: {e}"
    return render_template("bot.html", mesaj=mesaj, durum=durum_bilgisi(), tg_kullanicilar=bot_yonetim.telegram_kullanicilari(AYAR),
                           kategoriler=bot_yonetim.kategoriler(AYAR), bakim=bot_yonetim.bakim_modu(AYAR), gyazo_bakim=bot_yonetim.gyazo_bakim(AYAR),
                           oturumlar=bot_yonetim.oturumlar(AYAR), log=bot_yonetim.son_log(AYAR, 150), hatalar=bot_yonetim.son_log(AYAR, 40, True),
                           cfg=bot_yonetim.config(AYAR))


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


@app.route("/saglik")
def saglik():
    return "OK"


@app.errorhandler(403)
def _403(e):
    return render_template("hata.html", kod=403, mesaj="Bu islem icin yetkiniz yok."), 403


@app.errorhandler(404)
def _404(e):
    return render_template("hata.html", kod=404, mesaj="Bulunamadi."), 404


# ==================== arka plan ice aktarim ====================
def _arka_plan():
    conn = db.baglan(AYAR["DB"])
    while True:
        try:
            ice_aktar.calistir(AYAR, conn, AYAR["ONBELLEK"], COZUCU)
        except Exception as e:
            print("ice aktarim hatasi:", e)
        time.sleep(max(30, int(float(AYAR.get("YENILEME_DK", 3)) * 60)))


# ==================== komut satiri ====================
def komut(argv):
    c = db.baglan(AYAR["DB"])
    if not argv:
        return False
    if argv[0] == "kullanici-ekle" and len(argv) >= 3:
        ad, yk = argv[1].strip().lower(), argv[2]
        sifre = argv[3] if len(argv) > 3 else _rastgele_sifre()
        if c.execute("SELECT 1 FROM panel_kullanicilari WHERE lower(kullanici_adi)=?", (ad,)).fetchone():
            c.execute("UPDATE panel_kullanicilari SET yetki=?, aktif=1 WHERE lower(kullanici_adi)=?", (yk, ad))
            print(f"Kullanici zaten vardi; yetkisi guncellendi: {ad} [{yk}]")
        else:
            c.execute("INSERT INTO panel_kullanicilari(kullanici_adi,ad,sifre_hash,yetki,aktif,sifre_degistir,olusturma) VALUES(?,?,?,?,1,1,?)", (ad, ad, generate_password_hash(sifre), yk, simdi()))
            print(f"Kullanici acildi: {ad}   yetki: {yk}   gecici sifre: {sifre}")
        return True
    if argv[0] == "sifre-sifirla" and len(argv) >= 2:
        ad = argv[1].strip().lower()
        sifre = argv[2] if len(argv) > 2 else _rastgele_sifre()
        n = c.execute("UPDATE panel_kullanicilari SET sifre_hash=?, sifre_degistir=1, hatali_giris=0, kilit_bitis=NULL, aktif=1 WHERE lower(kullanici_adi)=?", (generate_password_hash(sifre), ad)).rowcount
        print(f"Yeni gecici sifre ({ad}): {sifre}" if n else f"Kullanici bulunamadi: {ad}")
        return True
    if argv[0] == "ice-aktar":
        r = ice_aktar.calistir(AYAR, c, AYAR["ONBELLEK"], COZUCU)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return True
    if argv[0] == "kullanicilar":
        for r in c.execute("SELECT kullanici_adi, yetki, aktif, son_giris FROM panel_kullanicilari ORDER BY 1"):
            print(f"{r['kullanici_adi']:20} {('aktif' if r['aktif'] else 'PASIF'):6} {r['son_giris'] or '-':20} {r['yetki']}")
        return True
    return False


def calistir():
    if len(sys.argv) > 1 and komut(sys.argv[1:]):
        return
    db.baglan(AYAR["DB"])
    t = threading.Thread(target=_arka_plan, daemon=True)
    t.start()
    print(f"Panel: http://{AYAR['DINLE']}:{AYAR['PORT']}/   bot klasoru: {AYAR['BOT_KLASOR']}")
    try:
        from waitress import serve
        serve(app, host=AYAR["DINLE"], port=int(AYAR["PORT"]), threads=8)
    except ImportError:
        app.run(host=AYAR["DINLE"], port=int(AYAR["PORT"]))


if __name__ == "__main__":
    calistir()

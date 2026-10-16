# -*- coding: utf-8 -*-
"""Ilk admin kurulumu, giris / cikis, sifre degistirme."""
import time, secrets
from flask import g, request, session, redirect, url_for, render_template, flash, current_app
from .. import db
from .ortak import bp, ayar, conn, ip, yerel_istek, giris_gerekli, guvenli_sonraki


def _anahtar_uyuyor(verilen):
    beklenen = ayar().get("ILK_ADMIN_ANAHTAR") or ""
    return bool(beklenen) and bool(verilen) and secrets.compare_digest(str(beklenen), str(verilen))


@bp.route("/kurulum/admin", methods=["GET", "POST"])
def kurulum_admin():
    c = conn()
    if c.execute("SELECT 1 FROM panel_kullanicilari LIMIT 1").fetchone():
        return redirect(url_for("panel.giris"))
    anahtar = request.values.get("anahtar") or ""
    serbest = yerel_istek() or _anahtar_uyuyor(anahtar)
    if not serbest:
        # uzaktan ilk admin: yalnizca konsola yazilan tek kullanimlik anahtarla
        return render_template("kurulum_admin.html", hata=None, kilitli=True, anahtar_girildi=bool(anahtar)), 403
    hata = None
    if request.method == "POST":
        ad = (request.form.get("kullanici") or "").strip().lower()
        s1, s2 = request.form.get("sifre") or "", request.form.get("sifre2") or ""
        if not db.kullanici_adi_gecerli(ad):
            hata = "Kullan\u0131c\u0131 ad\u0131 harf/rakam olmal\u0131."
        elif len(s1) < 8:
            hata = "\u015eifre en az 8 karakter olmal\u0131."
        elif s1 != s2:
            hata = "\u015eifreler ayn\u0131 de\u011fil."
        else:
            db.kullanici_ekle(c, ad, "admin", s1, gorunen_ad=request.form.get("ad") or ad, olusturan="kurulum", sifre_degistir=False)
            db.denetim_yaz(c, ad, "ilk_admin", ip=ip())
            ayar()["ILK_ADMIN_ANAHTAR"] = ""   # tek kullanimlik
            flash("S\u00fcper admin olu\u015fturuldu. \u015eimdi giri\u015f yap\u0131n.")
            return redirect(url_for("panel.giris"))
    return render_template("kurulum_admin.html", hata=hata, kilitli=False, anahtar=anahtar)


@bp.route("/giris", methods=["GET", "POST"])
def giris():
    hata = None
    if request.method == "POST":
        ad = (request.form.get("kullanici") or "").strip().lower()
        sifre = request.form.get("sifre") or ""
        c = conn()
        u, hata = db.kullanici_dogrula(c, ad, sifre, ip())
        if u:
            session.clear()
            session.permanent = True
            session["kad"] = u["kullanici_adi"]
            session["csrf"] = secrets.token_hex(16)
            db.denetim_yaz(c, u["kullanici_adi"], "giris", ip=ip())
            return redirect(guvenli_sonraki(request.args.get("sonraki")) or url_for("panel.ana"))
        db.denetim_yaz(c, ad[:40], "giris_hata", ip=ip())
        bekle = current_app.config.get("GIRIS_BEKLEME") or 0
        if bekle:
            time.sleep(bekle)
    elif g.get("k"):
        return redirect(url_for("panel.ana"))
    return render_template("giris.html", hata=hata)


@bp.route("/cikis")
def cikis():
    if g.get("k"):
        db.denetim_yaz(conn(), g.k["kullanici_adi"], "cikis", ip=ip())
    session.clear()
    return redirect(url_for("panel.giris"))


@bp.route("/sifre", methods=["GET", "POST"])
@giris_gerekli
def sifre_degistir():
    hata = None
    if request.method == "POST":
        eski, yeni, yeni2 = request.form.get("eski", ""), request.form.get("yeni", ""), request.form.get("yeni2", "")
        c = conn()
        u, _ = db.kullanici_dogrula(c, g.k["kullanici_adi"], eski, ip())
        if not u:
            hata = "Eski \u015fifre hatal\u0131."
        elif len(yeni) < 8:
            hata = "Yeni \u015fifre en az 8 karakter olmal\u0131."
        elif yeni != yeni2:
            hata = "Yeni \u015fifreler ayn\u0131 de\u011fil."
        else:
            db.kullanici_guncelle(c, g.k["kullanici_adi"], kim=g.k["kullanici_adi"], sifre=yeni, sifre_degistir=False)
            db.denetim_yaz(c, g.k["kullanici_adi"], "sifre_degisti", ip=ip())
            flash("\u015eifre de\u011fi\u015ftirildi.")
            return redirect(url_for("panel.ana"))
    return render_template("sifre.html", hata=hata)


@bp.route("/saglik")
def saglik():
    resp = current_app.make_response("OK")
    if yerel_istek():
        from .. import SURUM
        resp.headers["X-Kanit-Paneli"] = SURUM
    return resp

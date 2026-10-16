# -*- coding: utf-8 -*-
"""Kanit Merkezi web paneli (Flask).

create_app(ayar=None, conn=None) -> Flask uygulamasi. conn verilirse (testler) her istekte o baglanti kullanilir;
verilmezse her is parcacigi kendi SQLite baglantisini acar (WAL). calistir() waitress ile ayar DINLE:PORT'ta dinler.
"""
import os, secrets, threading
from datetime import timedelta
from flask import Flask, g, request, session, redirect, url_for, render_template, abort, flash, jsonify
from .. import db, yetki, SURUM
from . import ortak

KOK = os.path.dirname(os.path.abspath(__file__))
# giris / ilk kurulum / saglik: kullanici gerekmez
SERBEST = {"panel.giris", "panel.kurulum_admin", "panel.saglik", "panel.cikis", "static"}
_yerel = threading.local()
FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="4" y="3" width="24" height="26" rx="4" fill="#111827"/>'
               '<rect x="10" y="1" width="12" height="6" rx="2" fill="#2563eb"/><path d="M9 17l5 5 9-10" stroke="#16a34a" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def create_app(ayar=None, conn=None):
    if ayar is None:
        from .. import ayar as A
        ayar = A.yukle()
    app = Flask("kanit.web", template_folder=os.path.join(KOK, "templates"), static_folder=os.path.join(KOK, "static"))
    app.config["KANIT"] = ayar
    app.config["KANIT_CONN"] = conn
    app.config["GIRIS_BEKLEME"] = float(ayar.get("GIRIS_BEKLEME", 0.8) or 0)
    app.config["SAYFA_BOYU"] = int(ayar.get("SAYFA_BOYU", 48) or 48)
    app.secret_key = ayar.get("SECRET_KEY") or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
                      MAX_CONTENT_LENGTH=4 * 1024 * 1024, JSON_AS_ASCII=False)
    if str(ayar.get("HTTPS", "0")).lower() in ("1", "true"):
        app.config["SESSION_COOKIE_SECURE"] = True

    from . import giris, kayitlar, cikti, yonetim, bildirim  # noqa: F401  (rotalar bp'ye yazilir)
    app.register_blueprint(ortak.bp)

    def baglanti():
        c = app.config.get("KANIT_CONN")
        if c is not None:
            return c
        c = getattr(_yerel, "conn", None)
        if c is None:
            c = db.baglan(ayar["DB"])
            _yerel.conn = c
        return c

    @app.before_request
    def _on():
        g.conn = baglanti()
        g.k = None
        kad = session.get("kad")
        if kad:
            u = db.kullanici_bul(g.conn, kad)
            if u and u["aktif"]:
                g.k = u
        g.yk = yetki.coz(g.k["yetki"]) if g.k else yetki.coz("")
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        ep = request.endpoint or ""
        if request.method == "POST":
            tok = request.form.get("csrf") or request.headers.get("X-CSRF")
            if not tok or tok != session.get("csrf"):
                if ep == "panel.giris":
                    return render_template("giris.html", hata="Sayfa zaman a\u015f\u0131m\u0131na u\u011frad\u0131; l\u00fctfen tekrar deneyin."), 400
                abort(400, "CSRF")
        if ep in SERBEST or not ep:
            return None
        if not _kullanici_var(g.conn):
            return redirect(url_for("panel.kurulum_admin"))
        return None

    @app.after_request
    def _basliklar(r):
        r.headers.setdefault("X-Frame-Options", "DENY")
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("Referrer-Policy", "same-origin")
        r.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        if request.path.endswith(".json") or request.path.startswith(("/kayit/", "/bildirim", "/bot/")):
            r.headers.setdefault("Cache-Control", "no-store")
        return r

    @app.context_processor
    def _ctx():
        ep = (request.endpoint or "").split(".")[-1]
        return {"k": g.get("k"), "yk": g.get("yk"), "renk": ortak.renk, "metin_rengi": ortak.metin_rengi, "url_degistir": ortak.url_degistir,
                "csrf": session.get("csrf", ""), "projeler": ortak.izinli_projeler, "tum_projeler": ortak.tum_projeler,
                "izin": lambda p, e: yetki.izin(g.yk, p, e), "AYAR": ayar, "SURUM": SURUM, "ep": ep,
                "u": lambda ad, **kw: url_for("panel." + ad, **kw), "DURUM_ADLARI": ortak.DURUM_ADLARI, "proje_renkleri": ortak.renkler,
                "okunmamis_bildirim": (lambda: db.okunmamis_bildirim_sayisi(g.conn, g.k["kullanici_adi"]) if g.get("k") else 0)}

    @app.route("/favicon.ico")
    def favicon():
        from flask import Response
        r = Response(FAVICON_SVG, mimetype="image/svg+xml")
        r.headers["Cache-Control"] = "public, max-age=86400"
        return r

    @app.errorhandler(400)
    def _400(e):
        return render_template("hata.html", kod=400, mesaj="Ge\u00e7ersiz istek (" + str(getattr(e, "description", "") or "") + ")."), 400

    @app.errorhandler(401)
    def _401(e):
        if request.path.endswith(".json") or request.method == "POST":
            return jsonify({"ok": False, "hata": "giris gerekli"}), 401
        return redirect(url_for("panel.giris"))

    @app.errorhandler(403)
    def _403(e):
        if request.path.endswith(".json") or request.method == "POST":
            return jsonify({"ok": False, "hata": "yetki yok"}), 403
        return render_template("hata.html", kod=403, mesaj="Bu i\u015flem i\u00e7in yetkiniz yok."), 403

    @app.errorhandler(404)
    def _404(e):
        if request.path.endswith(".json"):
            return jsonify({"ok": False, "hata": "bulunamadi"}), 404
        return render_template("hata.html", kod=404, mesaj="Bulunamad\u0131."), 404

    @app.errorhandler(413)
    def _413(e):
        flash(f"Dosya \u00e7ok b\u00fcy\u00fck: en fazla {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB y\u00fcklenebilir.")
        return redirect(url_for("panel.disa_aktar_sayfasi"))

    return app


def _kullanici_var(conn):
    return conn.execute("SELECT 1 FROM panel_kullanicilari LIMIT 1").fetchone() is not None


def calistir(ayar=None):
    """waitress ile DINLE:PORT. Panel kullanicisi yoksa tek kullanimlik ILK_ADMIN_ANAHTAR konsola yazilir."""
    if ayar is None:
        from .. import ayar as A
        ayar = A.yukle()
    conn = db.baglan(ayar["DB"])
    if not _kullanici_var(conn):
        ayar["ILK_ADMIN_ANAHTAR"] = ayar.get("ILK_ADMIN_ANAHTAR") or secrets.token_urlsafe(12)
    conn.close()
    app = create_app(ayar)
    host, port = str(ayar.get("DINLE") or "0.0.0.0"), int(ayar.get("PORT") or 8080)
    print("=" * 60)
    print(f"  KANIT MERKEZI PANELI {SURUM}")
    print(f"  Adres   : http://127.0.0.1:{port}/")
    if host not in ("127.0.0.1", "localhost"):
        try:
            import socket
            for ip_ in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not ip_.startswith("127."):
                    print(f"            http://{ip_}:{port}/")
        except Exception:
            pass
    print(f"  Veri    : {ayar['VERI']}")
    if ayar.get("ILK_ADMIN_ANAHTAR"):
        print("  Panel kullanicisi yok. Ilk super admin icin /kurulum/admin sayfasini acin.")
        print(f"  Uzaktan aciyorsaniz tek kullanimlik anahtar: {ayar['ILK_ADMIN_ANAHTAR']}")
        print("  (ya da: python -m kanit kullanici-ekle <ad> admin)")
    print("=" * 60)
    from waitress import serve
    serve(app, host=host, port=port, threads=8)

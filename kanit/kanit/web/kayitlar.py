# -*- coding: utf-8 -*-
"""Ana sayfa, Kayitlar (kart/galeri/tablo), proje Tablo sayfasi, kayit penceresi (json), KT / duzenle / sil / geri al,
yorumlar, gecmis, arsiv kopyalari, gorsel / kucuk resim (Gyazo vekili dahil)."""
import os, re, io, json, time, urllib.request, urllib.error
from datetime import datetime
from urllib.parse import urlparse
from flask import g, request, redirect, url_for, render_template, jsonify, abort, send_file, Response
from werkzeug.datastructures import MultiDict
from .. import db, gorsel as G, normalle as N
from .ortak import (bp, ayar, conn, ip, giris_gerekli, admin_gerekli, izinli_projeler, renk, kategori_listesi, filtre_sql, siralama_sql,
                    kayit_sozluk, kayit_izin, gorsel_var, sayi, simdi, tarih_kisa, ALAN_ADLARI, DURUMLAR)

DUZENLENEBILIR_FORM = ("personel", "uye_id", "ana_uye_id", "tip", "kategori", "aciklama", "gorsel2", "link")
TABLO_BOYLAR = (200, 500, 0)   # 0 = hepsi
_GYAZO_HOSTLAR = ("gyazo.com", "i.gyazo.com", "www.gyazo.com")
GYAZO_SINIR = 20 * 1024 * 1024
_gyazo_basarisiz = {}   # kimlik -> zaman (10 dk boyunca yeniden denenmez)
PLACEHOLDER_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="260" viewBox="0 0 400 260">'
                   '<rect width="400" height="260" fill="#e5e7eb"/><text x="200" y="125" font-family="Segoe UI, Arial, sans-serif" font-size="16" '
                   'fill="#6b7280" text-anchor="middle">g\u00f6rsel yok</text><text x="200" y="150" font-family="Segoe UI, Arial, sans-serif" '
                   'font-size="13" fill="#9ca3af" text-anchor="middle">(eski Gyazo linki)</text></svg>')


# ==================== ana sayfa ====================
@bp.route("/")
@giris_gerekli
def ana():
    c = conn()
    izinli = izinli_projeler()
    sayac = db.proje_sayaclari(c, izinli)
    bugun = {r["proje"]: r["n"] for r in c.execute("SELECT proje, COUNT(*) n FROM kayitlar WHERE date(tarih)=date('now','localtime') AND silindi=0 GROUP BY proje").fetchall()}
    kartlar = []
    for p in izinli:
        s = sayac.get(p, {"bekleyen": 0, "onayli": 0, "silinen": 0, "toplam": 0})
        kartlar.append({"proje": p, "bugun": bugun.get(p, 0), **s})
    return render_template("ana.html", kartlar=kartlar, durum=_bot_durumu(c))


def _bot_durumu(c):
    """ayarlar.bot_nabiz yasi (<180 sn canli) + son_hata"""
    nabiz = db.ayar_al(c, "bot_nabiz")
    yas = None
    try:
        yas = int((datetime.now() - datetime.strptime(nabiz[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()) if nabiz else None
    except Exception:
        yas = None
    return {"nabiz": nabiz, "yas_sn": yas, "canli": (yas is not None and 0 <= yas < 180) if nabiz else None, "son_hata": db.ayar_al(c, "son_hata") or "",
            "bakim": db.bakim_modu(c), "gyazo_bakim": db.gyazo_bakim(c)}


# ==================== kayit listesi ====================
def _sayaclar(c, args, izinli, proje_sabit=None):
    out = {}
    for d in DURUMLAR:
        a = args.to_dict(flat=False)
        a["durum"] = [d]
        w, p, _ = filtre_sql(MultiDict(a), izinli, proje_sabit)
        out[d] = c.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {w}", p).fetchone()[0]
    return out


@bp.route("/kayitlar")
@giris_gerekli
def kayitlar():
    from flask import current_app
    c = conn()
    izinli = izinli_projeler()
    where, par, f = filtre_sql(request.args, izinli)
    gorunum = request.args.get("gorunum") or "kart"
    if gorunum not in ("kart", "galeri", "tablo"):
        gorunum = "kart"
    sayfa = max(1, sayi(request.args.get("s"), 1))
    boy = int(current_app.config["SAYFA_BOYU"])
    toplam = c.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {where}", par).fetchone()[0]
    rows = c.execute(f"SELECT * FROM kayitlar WHERE {where} ORDER BY COALESCE(tarih,'0000') DESC, id DESC LIMIT ? OFFSET ?", (*par, boy, (sayfa - 1) * boy)).fetchall()
    liste = [kayit_sozluk(r) for r in rows]
    okunmamis = db.okunmamis_yorumlar(c, g.k["kullanici_adi"], [k["id"] for k in liste])
    for k in liste:
        k["okunmamis_yorum"] = okunmamis.get(k["id"], 0)
    return render_template("kayitlar.html", kayitlar=liste, toplam=toplam, sayfa=sayfa, sayfa_sayisi=max(1, (toplam + boy - 1) // boy),
                           f=f, izinli=izinli, kategoriler=kategori_listesi(), gorunum=gorunum, sayac=_sayaclar(c, request.args, izinli))


@bp.route("/proje/<proje>/tablo")
@giris_gerekli
def tablo(proje):
    c = conn()
    proje = (proje or "").upper()
    izinli = izinli_projeler()
    if proje not in izinli:
        abort(403 if g.get("k") else 404)
    where, par, f = filtre_sql(request.args, izinli, proje_sabit=proje)
    order, sirala, yon = siralama_sql(request.args)
    boy = sayi(request.args.get("boy"), 200)
    if boy not in TABLO_BOYLAR:
        boy = 200
    sayfa = max(1, sayi(request.args.get("s"), 1))
    toplam = c.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {where}", par).fetchone()[0]
    if boy:
        rows = c.execute(f"SELECT * FROM kayitlar WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?", (*par, boy, (sayfa - 1) * boy)).fetchall()
    else:
        rows = c.execute(f"SELECT * FROM kayitlar WHERE {where} ORDER BY {order}", par).fetchall()
    liste = [kayit_sozluk(r) for r in rows]
    okunmamis = db.okunmamis_yorumlar(c, g.k["kullanici_adi"], [k["id"] for k in liste])
    # son ziyaret: ayarlar 'ziyaret:<kullanici>:<proje>' -> bu ziyaretten sonra eklenenler ince mavi cizgiyle
    anahtar = f"ziyaret:{g.k['kullanici_adi']}:{proje}"
    son_ziyaret = db.ayar_al(c, anahtar) or ""
    db.ayar_yaz(c, anahtar, simdi())
    for k in liste:
        k["okunmamis_yorum"] = okunmamis.get(k["id"], 0)
        k["yeni"] = bool(son_ziyaret) and (k.get("olusturma") or "") > son_ziyaret
    sayfa_sayisi = max(1, (toplam + boy - 1) // boy) if boy else 1
    return render_template("tablo.html", proje=proje, kayitlar=liste, toplam=toplam, sayfa=sayfa, sayfa_sayisi=sayfa_sayisi, boy=boy, boylar=TABLO_BOYLAR,
                           f=f, izinli=izinli, kategoriler=kategori_listesi(), sayac=_sayaclar(c, request.args, izinli, proje), sirala=sirala, yon=yon,
                           son_ziyaret=son_ziyaret, izin_kt=kayit_izin({"proje": proje}, "kt"))


# ==================== kayit penceresi ====================
def _kayit(kid, eylem, kod=404):
    r = db.kayit_al(conn(), kid)
    if not r or not kayit_izin(r, eylem):
        abort(kod)
    return r


@bp.route("/kayit/<int:kid>.json")
@giris_gerekli
def kayit_json(kid):
    c = conn()
    r = _kayit(kid, "oku")
    d = kayit_sozluk(r)
    d["gorsel_url"] = url_for("panel.gorsel_goster", kid=kid) if d["izin_gorsel"] and d["gorsel_var"] else None
    d["kucuk_url"] = url_for("panel.kucuk_goster", kid=kid) if d["izin_gorsel"] and d["gorsel_var"] else None
    if d.get("gorsel_dosya") and G.tam_yol(ayar()["GORSELLER"], d["gorsel_dosya"]):
        d["gorsel_kaynak"] = "yerel"
    elif d.get("link_turu") == "gyazo":
        d["gorsel_kaynak"] = "gyazo"
    else:
        d["gorsel_kaynak"] = "yok"
    d["okunmamis_yorum"] = db.okunmamis_yorumlar(c, g.k["kullanici_adi"], [kid]).get(kid, 0)
    d["arsiv_sayisi"] = c.execute("SELECT COUNT(*) FROM arsiv WHERE kayit_id=?", (kid,)).fetchone()[0]
    d["admin"] = bool(g.yk["admin"])
    return jsonify(d)


@bp.route("/kayit/<int:kid>/kt", methods=["POST"])
@giris_gerekli
def kayit_kt(kid):
    r = _kayit(kid, "kt", 403)
    if r["silindi"]:
        return jsonify({"ok": False, "hata": "silinmi\u015f kayda KT verilemez"}), 400
    yeni = 1 if (request.form.get("deger", "1") in ("1", "true", "on")) else 0
    k = db.kt_ayarla(conn(), kid, yeni, g.k["kullanici_adi"], kaynak="panel", ip=ip())
    return jsonify({"ok": True, "kt": k["kt"], "kt_kim": k["kt_kim"], "kt_zaman": k["kt_zaman"], "surum": k["surum"]})


def _son_degistiren(c, kid):
    r = c.execute("SELECT kullanici FROM denetim WHERE kayit_id=? AND islem IN ('duzenle','kt','kt_kaldir','sil','geri_al') ORDER BY id DESC LIMIT 1", (kid,)).fetchone()
    return r["kullanici"] if r else ""


@bp.route("/kayit/<int:kid>/duzenle", methods=["POST"])
@giris_gerekli
def kayit_duzenle(kid):
    r = _kayit(kid, "duzenle", 403)
    if r["silindi"]:
        return jsonify({"ok": False, "hata": "silinmi\u015f kay\u0131t d\u00fczenlenemez; \u00f6nce geri al\u0131n"}), 400
    alanlar = {k: (request.form.get(k) or "").strip() for k in DUZENLENEBILIR_FORM if k in request.form}
    if not alanlar:
        return jsonify({"ok": False, "hata": "de\u011fi\u015fiklik yok"}), 400
    surum = request.form.get("surum")
    surum = sayi(surum, None) if surum not in (None, "") else None
    okk, k, hata = db.kayit_guncelle(conn(), kid, alanlar, g.k["kullanici_adi"], surum=surum, ip=ip())
    if hata == "catisma":
        return jsonify({"ok": False, "catisma": True, "kim": _son_degistiren(conn(), kid), "surum": k["surum"], "kayit": kayit_sozluk(k)}), 409
    if not okk:
        return jsonify({"ok": False, "hata": hata}), 400
    return jsonify({"ok": True, "surum": k["surum"], "kayit": kayit_sozluk(k)})


@bp.route("/kayit/<int:kid>/sil", methods=["POST"])
@giris_gerekli
def kayit_sil(kid):
    r = _kayit(kid, "sil", 403)
    neden = (request.form.get("neden") or "").strip()
    if not neden:
        return jsonify({"ok": False, "hata": "silme nedeni gerekli"}), 400
    if r["silindi"]:
        return jsonify({"ok": True, "zaten": True})
    k = db.kayit_sil(conn(), kid, g.k["kullanici_adi"], neden=neden, ip=ip())
    return jsonify({"ok": True, "surum": k["surum"]})


@bp.route("/kayit/<int:kid>/geri-al", methods=["POST"])
@giris_gerekli
def kayit_geri_al(kid):
    r = _kayit(kid, "sil", 403)
    if not r["silindi"]:
        return jsonify({"ok": True, "zaten": True})
    k = db.kayit_geri_al(conn(), kid, g.k["kullanici_adi"], ip=ip())
    return jsonify({"ok": True, "surum": k["surum"]})


# ==================== yorumlar ====================
def _yorum_sozluk(y):
    d = dict(y)
    d["duzenlenebilir"] = (not d["silindi"]) and d["kullanici"] == g.k["kullanici_adi"] and _dakika_gecti(d["zaman"]) < db.YORUM_DUZENLEME_DK
    d["silinebilir"] = (not d["silindi"]) and (d["kullanici"] == g.k["kullanici_adi"] or bool(g.yk["admin"]))
    if d["silindi"]:
        d["metin"] = ""
    return d


def _dakika_gecti(zaman):
    try:
        return (datetime.now() - datetime.strptime(zaman[:19], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
    except Exception:
        return 10 ** 6


@bp.route("/kayit/<int:kid>/yorumlar.json")
@giris_gerekli
def yorumlar_json(kid):
    """Yorum sekmesi acilinca: liste + okundu isareti."""
    _kayit(kid, "oku")
    c = conn()
    liste = [_yorum_sozluk(y) for y in db.yorumlar(c, kid)]
    db.yorum_okundu(c, g.k["kullanici_adi"], kid)
    return jsonify({"ok": True, "yorumlar": liste, "sayi": sum(1 for y in liste if not y["silindi"]), "ben": g.k["kullanici_adi"], "admin": bool(g.yk["admin"])})


@bp.route("/kayit/<int:kid>/yorum", methods=["POST"])
@giris_gerekli
def yorum_ekle(kid):
    _kayit(kid, "oku", 403)
    metin = (request.form.get("metin") or "").strip()
    if not metin:
        return jsonify({"ok": False, "hata": "yorum bo\u015f"}), 400
    y = db.yorum_ekle(conn(), kid, g.k["kullanici_adi"], metin, ip=ip())
    return jsonify({"ok": True, "yorum": _yorum_sozluk(y)})


def _yorum_al(yid):
    y = conn().execute("SELECT * FROM yorumlar WHERE id=?", (yid,)).fetchone()
    if not y:
        abort(404)
    _kayit(y["kayit_id"], "oku", 403)
    return dict(y)


@bp.route("/yorum/<int:yid>/duzenle", methods=["POST"])
@giris_gerekli
def yorum_duzenle(yid):
    _yorum_al(yid)
    okk, hata = db.yorum_duzenle(conn(), yid, g.k["kullanici_adi"], request.form.get("metin") or "", admin=bool(g.yk["admin"]), ip=ip())
    if not okk:
        return jsonify({"ok": False, "hata": hata}), 403 if "yazar" in (hata or "") else 400
    return jsonify({"ok": True})


@bp.route("/yorum/<int:yid>/sil", methods=["POST"])
@giris_gerekli
def yorum_sil(yid):
    _yorum_al(yid)
    okk, hata = db.yorum_sil(conn(), yid, g.k["kullanici_adi"], admin=bool(g.yk["admin"]), ip=ip())
    if not okk:
        return jsonify({"ok": False, "hata": hata}), 403 if "yazar" in (hata or "") else 400
    return jsonify({"ok": True})


# ==================== gecmis / arsiv ====================
_TIRE, _OK_ISARETI = "\u2014", "\u2192"


def _fark_cumlesi(eski, yeni):
    parcalar = []
    if isinstance(yeni, dict):
        for k, v in yeni.items():
            e = (eski or {}).get(k, "") if isinstance(eski, dict) else ""
            parcalar.append(f"{ALAN_ADLARI.get(k, k)} {e or _TIRE} {_OK_ISARETI} {v or _TIRE}")
    return ", ".join(parcalar)


def gecmis_cumlesi(r):
    """Denetim satiri -> insan cumlesi. '14.10 09:12 ayse \u00b7 D\u00fczenle: \u00dcye ID 490241 \u2192 490214'"""
    i, e, y = r.get("islem"), r.get("eski"), r.get("yeni")
    if i == "ekle":
        m = "Eklendi"
        if isinstance(y, dict):
            m += ": " + " ".join(str(v) for v in (y.get("personel"), y.get("kategori")) if v)
    elif i == "duzenle":
        m = "D\u00fczenle: " + (_fark_cumlesi(e, y) or "(de\u011fi\u015fiklik)")
    elif i == "kt":
        m = "KT \u2714"
    elif i == "kt_kaldir":
        m = "KT kald\u0131r\u0131ld\u0131"
    elif i == "sil":
        m = "Silindi" + (f" (neden: {y})" if y else "")
    elif i == "geri_al":
        m = "Geri al\u0131nd\u0131"
    elif i == "yorum":
        m = "Yorum: " + str(y or "")
    elif i == "yorum_duzenle":
        m = "Yorum d\u00fczeltildi: " + str(y or "")
    elif i == "yorum_sil":
        m = "Yorum silindi: " + str(e or "")
    elif i == "gorsel_ac":
        m = "G\u00f6rseli a\u00e7t\u0131"
    else:
        m = str(i)
    return f"{tarih_kisa(r.get('zaman'))} {r.get('kullanici') or 'bot'} \u00b7 {m}"


@bp.route("/kayit/<int:kid>/gecmis.json")
@giris_gerekli
def gecmis_json(kid):
    _kayit(kid, "oku")
    c = conn()
    rows = db.kayit_gecmisi(c, kid)
    liste = [{"zaman": r["zaman"], "kullanici": r["kullanici"], "islem": r["islem"], "metin": gecmis_cumlesi(r)} for r in rows]
    return jsonify({"ok": True, "gecmis": liste, "arsiv_sayisi": c.execute("SELECT COUNT(*) FROM arsiv WHERE kayit_id=?", (kid,)).fetchone()[0],
                    "arsiv_url": url_for("panel.arsiv_json", kid=kid) if g.yk["admin"] else None})


@bp.route("/kayit/<int:kid>/arsiv.json")
@admin_gerekli
def arsiv_json(kid):
    return jsonify({"ok": True, "kayit_id": kid, "kopyalar": db.arsiv_kayitlari(conn(), kid)})


# ==================== gorsel ====================
class _GyazoYonlendirme(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if (urlparse(newurl).hostname or "").lower() not in _GYAZO_HOSTLAR:
            raise urllib.error.HTTPError(newurl, code, "gyazo disina yonlendirme", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def gyazo_indir(url, hedef, zaman_asimi=10):
    """i.gyazo.com'dan indir (yalnizca gyazo.com'a yonlendirme, 20 MB sinir). -> hedef | None"""
    if (urlparse(url).hostname or "").lower() not in _GYAZO_HOSTLAR:
        return None
    opener = urllib.request.build_opener(_GyazoYonlendirme())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KanitMerkezi"})
    try:
        with opener.open(req, timeout=zaman_asimi) as r:
            if r.status != 200:
                return None
            veri = r.read(GYAZO_SINIR + 1)
    except Exception:
        return None
    if len(veri) > GYAZO_SINIR or not G.gorsel_mi(veri):
        return None
    os.makedirs(os.path.dirname(hedef), exist_ok=True)
    tmp = hedef + ".tmp"
    with open(tmp, "wb") as f:
        f.write(veri)
    os.replace(tmp, hedef)
    return hedef


def _gyazo_yerel(d):
    """Gyazo kaydi icin onbellek yolu; yoksa (vekil acikken) indirir."""
    tur, kimlik = G.link_turu_ve_kimlik(d.get("link"))
    if tur != "gyazo" or not re.fullmatch(r"[0-9a-f]{32}", kimlik or ""):
        return None
    hedef = os.path.join(ayar()["ONBELLEK"], "gyazo", kimlik + ".jpg")
    if os.path.isfile(hedef):
        return hedef
    if str(ayar().get("GYAZO_PROXY", "1")) == "0":
        return None
    if _gyazo_basarisiz.get(kimlik, 0) > time.time() - 600:
        return None
    y = gyazo_indir(G.gyazo_url(d.get("link"), kimlik), hedef)
    if not y:
        _gyazo_basarisiz[kimlik] = time.time()
        if len(_gyazo_basarisiz) > 5000:
            _gyazo_basarisiz.clear()
    return y


def _gorsel_yolu(kid, kucuk=False):
    r = db.kayit_al(conn(), kid)
    if not r or not kayit_izin(r, "gorsel"):
        abort(404)
    yol = G.tam_yol(ayar()["GORSELLER"], r.get("gorsel_dosya"))
    if not yol:
        yol = _gyazo_yerel(r)
    if yol and kucuk:
        yol = G.kucuk(ayar()["ONBELLEK"], yol) or yol
    return yol, r


def _placeholder():
    resp = Response(PLACEHOLDER_SVG, mimetype="image/svg+xml")
    resp.headers["X-Gorsel"] = "yok"
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


@bp.route("/kayit/<int:kid>/gorsel")
@giris_gerekli
def gorsel_goster(kid):
    yol, d = _gorsel_yolu(kid)
    if not yol:
        return _placeholder()
    db.denetim_yaz(conn(), g.k["kullanici_adi"], "gorsel_ac", d["proje"], kid, ip=ip())
    resp = send_file(yol, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.route("/kucuk/<int:kid>")
@giris_gerekli
def kucuk_goster(kid):
    yol, d = _gorsel_yolu(kid, kucuk=True)
    if not yol:
        return _placeholder()
    resp = send_file(yol, conditional=True)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp

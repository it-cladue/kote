# -*- coding: utf-8 -*-
"""Bildirimler (sunucu tarafli): zil sayisi, liste, okundu/okunmadi, 20 sn'de bir yoklama."""
from flask import g, request, jsonify, url_for
from .. import db
from .ortak import bp, conn, giris_gerekli, izinli_projeler, renk, sayi
from .kayitlar import _bot_durumu


def _link(b):
    durum = "bekleyen" if b["tur"] == "yeni_kayit" else "hepsi"
    if not b.get("kayit_id"):
        return url_for("panel.kayitlar", proje=b["proje"], durum=durum)
    return url_for("panel.kayitlar", proje=b["proje"], durum=durum, ac=b["kayit_id"])


def _sozluk(b):
    d = dict(b)
    d["link"] = _link(b)
    d["renk"] = renk(b["proje"])
    return d


@bp.route("/bildirim.json")
@giris_gerekli
def bildirim_json():
    """?son=<id>: bu id'den sonra gelen okunmamis bildirimler 'yeni' olarak doner (kucuk uyari icin)."""
    c = conn()
    kim = g.k["kullanici_adi"]
    son = sayi(request.args.get("son"), -1)
    liste = [_sozluk(b) for b in db.bildirimler(c, kim, 50)]
    maks = c.execute("SELECT COALESCE(MAX(id),0) FROM bildirimler WHERE kullanici=?", (kim,)).fetchone()[0]
    yeni = [b for b in liste if son >= 0 and b["id"] > son and not b["okundu"]] if son >= 0 else []
    izinli = izinli_projeler()
    return jsonify({"sayi": db.okunmamis_bildirim_sayisi(c, kim), "liste": liste, "maks": maks, "yeni": yeni,
                    "sayac": db.proje_sayaclari(c, izinli), "bot": _bot_durumu(c)["canli"]})


@bp.route("/bildirim/okundu", methods=["POST"])
@giris_gerekli
def bildirim_okundu():
    c = conn()
    kim = g.k["kullanici_adi"]
    bid = sayi(request.form.get("id"), 0)
    if not bid:
        return jsonify({"ok": False, "hata": "id"}), 400
    okundu = request.form.get("okundu", "1") != "0"
    db.bildirim_okundu(c, kim, [bid], okundu=okundu)
    return jsonify({"ok": True, "sayi": db.okunmamis_bildirim_sayisi(c, kim)})


@bp.route("/bildirim/tumu-okundu", methods=["POST"])
@giris_gerekli
def bildirim_tumu_okundu():
    c = conn()
    kim = g.k["kullanici_adi"]
    db.bildirim_okundu(c, kim)
    return jsonify({"ok": True, "sayi": 0})

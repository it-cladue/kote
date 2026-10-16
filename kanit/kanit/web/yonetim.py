# -*- coding: utf-8 -*-
"""Yonetim: panel kullanicilari, bot sayfasi (Telegram uyeleri, kategoriler, bakim), denetim, arsiv, yedek."""
import os, json, string, secrets
from datetime import datetime, timedelta
from flask import g, request, redirect, url_for, render_template, jsonify, abort, send_file
from .. import db, yetki, normalle as N
from .ortak import bp, ayar, conn, ip, admin_gerekli, tum_projeler, renk, sayi, simdi, filtre_sql
from .kayitlar import _bot_durumu


def _rastgele_sifre(n=10):
    alfabe = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabe) for _ in range(n))


# ==================== panel kullanicilari ====================
@bp.route("/yonetim/kullanicilar", methods=["GET", "POST"])
@admin_gerekli
def yonetim_kullanicilar():
    c = conn()
    mesaj = None
    kim = g.k["kullanici_adi"]
    if request.method == "POST":
        islem = request.form.get("islem")
        try:
            if islem == "ekle":
                ad = N.kucuk(request.form.get("kullanici") or "").strip()
                yk = (request.form.get("yetki") or "").strip()
                if not db.kullanici_adi_gecerli(ad):
                    raise ValueError("Kullan\u0131c\u0131 ad\u0131 harf/rakam olmal\u0131 (en fazla 40 karakter).")
                if not yk:
                    raise ValueError("Yetki bo\u015f olamaz.")
                if db.kullanici_bul(c, ad):
                    raise ValueError("Bu kullan\u0131c\u0131 ad\u0131 zaten var.")
                sifre = request.form.get("sifre") or _rastgele_sifre()
                db.kullanici_ekle(c, ad, yk, sifre, gorunen_ad=request.form.get("ad") or ad, olusturan=kim, sifre_degistir=True)
                db.denetim_yaz(c, kim, "kullanici_ekle_panel", yeni=f"{ad} [{yk}]", ip=ip())
                mesaj = f"Kullan\u0131c\u0131 a\u00e7\u0131ld\u0131: {ad}  ge\u00e7ici \u015fifre: {sifre}"
            else:
                ad = N.kucuk(request.form.get("kullanici_adi") or "").strip()
                u = db.kullanici_bul(c, ad)
                if not u:
                    mesaj = "Kullan\u0131c\u0131 bulunamad\u0131."
                elif islem == "yetki":
                    yk = (request.form.get("yetki") or "").strip()
                    if ad == kim and not yetki.coz(yk)["admin"]:
                        raise ValueError("Kendi admin yetkinizi kald\u0131ramazs\u0131n\u0131z.")
                    db.kullanici_guncelle(c, ad, kim=kim, yetki=yk)
                    db.denetim_yaz(c, kim, "yetki_degisti", eski=f"{ad} [{u['yetki']}]", yeni=yk, ip=ip())
                    mesaj = "Yetki g\u00fcncellendi."
                elif islem == "sifre":
                    sifre = _rastgele_sifre()
                    db.kullanici_guncelle(c, ad, kim=kim, sifre=sifre, sifre_degistir=True)
                    db.denetim_yaz(c, kim, "sifre_sifirla", yeni=ad, ip=ip())
                    mesaj = f"{ad} i\u00e7in ge\u00e7ici \u015fifre: {sifre}"
                elif islem == "pasif":
                    if ad == kim:
                        mesaj = "Kendi hesab\u0131n\u0131z\u0131 pasife alamazs\u0131n\u0131z."
                    else:
                        yeni = not u["aktif"]
                        db.kullanici_guncelle(c, ad, kim=kim, aktif=yeni)
                        db.denetim_yaz(c, kim, "kullanici_aktif" if yeni else "kullanici_pasif", yeni=ad, ip=ip())
                        mesaj = "Hesap " + ("aktif." if yeni else "pasif.")
                else:
                    mesaj = "Bilinmeyen i\u015flem."
        except ValueError as e:
            mesaj = f"Hata: {e}"
    liste = [dict(u, ozet=yetki.ozet(u.get("yetki", ""))) for u in db.kullanicilar(c)]
    return render_template("kullanicilar.html", kullanicilar=liste, mesaj=mesaj, tum_projeler=tum_projeler())


# ==================== bot ====================
def son_log(yol, n=150, sadece_hata=False):
    if not yol or not os.path.exists(yol):
        return []
    with open(yol, "rb") as f:
        f.seek(0, 2)
        boy = f.tell()
        f.seek(max(0, boy - 400000))
        satirlar = f.read().decode("utf-8", errors="replace").splitlines()
    if sadece_hata:
        satirlar = [s for s in satirlar if " ! " in s or "] !" in s or "ERROR" in s or "HATA" in s or "Hata" in s or "hatasi" in s]
    return satirlar[-n:]


def _tg_oturum_ozet(o):
    if not o:
        return None
    return {"adim": o.get("adim") or o.get("step") or "", "proje": o.get("proje") or "", "kategori": o.get("kategori") or ""}


def tg_listesi(c):
    ots = {o["id"]: o for o in db.oturumlar(c)}
    out = []
    for u in db.tg_listesi(c):
        u = dict(u)
        u["id"] = u["tg_id"]
        u["oturum"] = _tg_oturum_ozet(ots.get(u["tg_id"]))
        out.append(u)
    # oturumu olup defterde olmayanlar
    for tid, o in ots.items():
        if not any(u["tg_id"] == tid for u in out):
            out.append({"tg_id": tid, "id": tid, "username": "", "first_name": "", "last_seen": o.get("guncelleme"), "kayit_sayisi": 0, "status": "",
                        "onayli": 0, "onay_tarihi": "", "engelli": 0, "engel_sebep": "", "deneme": 0, "oturum": _tg_oturum_ozet(o)})
    return out


def tg_filtrele(liste, q="", sure_saat=0, durum="", adet=0):
    q = N.kucuk(q or "").strip()
    out = []
    esik = (datetime.now() - timedelta(hours=int(sure_saat))).strftime("%Y-%m-%d %H:%M:%S") if sure_saat and int(sure_saat) > 0 else None
    for u in liste:
        if q and q not in N.kucuk(f"{u['tg_id']} {u.get('username') or ''} {u.get('first_name') or ''}"):
            continue
        if esik and (u.get("last_seen") or "") < esik:
            continue
        if durum == "onayli" and not (u["onayli"] and not u["engelli"]):
            continue
        if durum == "engelli" and not u["engelli"]:
            continue
        if durum == "onaysiz" and (u["onayli"] or u["engelli"]):
            continue
        if durum == "oturum" and not u.get("oturum"):
            continue
        out.append(u)
    if esik or q or durum:
        out.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    if adet and int(adet) > 0:
        out = out[:int(adet)]
    return out


def _bot_istatistik(c, tum):
    db_proje = {r[0]: r[1] for r in c.execute("SELECT proje, COUNT(*) FROM kayitlar WHERE silindi=0 GROUP BY proje").fetchall()}
    db_kt = c.execute("SELECT SUM(kt=1), SUM(kt=0) FROM kayitlar WHERE silindi=0").fetchone()
    sayacli = [u for u in tum if u.get("kayit_sayisi")]
    rapor = sorted(sayacli, key=lambda u: -int(u.get("kayit_sayisi") or 0))[:15]
    return {"defter": len(tum), "onayli": sum(1 for u in tum if u["onayli"] and not u["engelli"]), "engelli": sum(1 for u in tum if u["engelli"]),
            "oturum": sum(1 for u in tum if u.get("oturum")), "sayacli": len(sayacli), "db_proje": db_proje, "db_toplam": sum(db_proje.values()),
            "db_onayli": int(db_kt[0] or 0), "db_bekleyen": int(db_kt[1] or 0),
            "kayit_raporu": [{"id": u["tg_id"], "ad": " / ".join(x for x in (u.get("username"), u.get("first_name")) if x), "kayit": u.get("kayit_sayisi") or 0,
                              "son": u.get("son_kayit_tarihi") or "", "proje": u.get("son_kayit_proje") or "", "kategori": u.get("son_kayit_kategori") or ""} for u in rapor]}


@bp.route("/bot", methods=["GET", "POST"])
@admin_gerekli
def bot_sayfasi():
    c = conn()
    mesaj = None
    kim = g.k["kullanici_adi"]
    if request.method == "POST":
        islem = request.form.get("islem") or ""
        tg = (request.form.get("tg_id") or "").strip()
        ad = (request.form.get("ad") or "").strip()[:80]
        try:
            if islem in ("onayla", "onay_kaldir", "engelle", "engel_kaldir", "tam_sifirla") and not (tg.isdigit() and len(tg) <= 20):
                raise ValueError("Telegram ID rakamlardan olu\u015fmal\u0131.")
            if islem == "onayla":
                db.tg_onayla(c, tg, ad or tg, kim=kim, ip=ip()); mesaj = f"{tg} onayland\u0131."
            elif islem == "onay_kaldir":
                db.tg_onay_kaldir(c, tg, kim=kim, ip=ip()); mesaj = f"{tg} onay\u0131 kald\u0131r\u0131ld\u0131; yeniden \u015fifre yazacak."
            elif islem == "engelle":
                db.tg_engelle(c, tg, (request.form.get("sebep") or "panel").strip()[:200], kim=kim, ip=ip()); mesaj = f"{tg} engellendi."
            elif islem == "engel_kaldir":
                vardi = db.tg_engel_kaldir(c, tg, kim=kim, ip=ip()); mesaj = f"{tg} engeli kald\u0131r\u0131ld\u0131." if vardi else f"{tg} zaten engelli de\u011fildi; deneme ve oturum temizlendi."
            elif islem == "tam_sifirla":
                r = db.tg_tam_sifirla(c, tg, kim=kim, ip=ip()); mesaj = f"{tg} tam s\u0131f\u0131rland\u0131 (engel: {'silindi' if r['engel_silindi'] else 'yoktu'}, onay: {'silindi' if r['onay_silindi'] else 'yoktu'})."
            elif islem == "oturum_temizle":
                db.oturum_sil(c, tg or None); db.denetim_yaz(c, kim, "bot_oturum_temizle", yeni=tg or "(hepsi)", ip=ip()); mesaj = "Oturum temizlendi." if tg else "T\u00fcm oturumlar temizlendi."
            elif islem == "bakim_ac" or islem == "bakim_kapat":
                db.ayar_yaz(c, "bakim_modu", "1" if islem == "bakim_ac" else "0"); db.denetim_yaz(c, kim, "bot_" + islem, ip=ip()); mesaj = "Bak\u0131m modu " + ("a\u00e7\u0131ld\u0131." if islem == "bakim_ac" else "kapat\u0131ld\u0131.")
            elif islem == "gyazo_bakim_ac" or islem == "gyazo_bakim_kapat":
                db.ayar_yaz(c, "gyazo_bakim", "1" if islem == "gyazo_bakim_ac" else "0"); db.denetim_yaz(c, kim, "bot_" + islem, ip=ip()); mesaj = "Gyazo bak\u0131m\u0131 " + ("a\u00e7\u0131ld\u0131." if islem == "gyazo_bakim_ac" else "kapat\u0131ld\u0131.")
            elif islem == "kategori_ekle":
                hata = db.kategori_kaydet(c, request.form.get("code") or "", request.form.get("label") or "", request.form.get("mode") or "tek_uye", kim)
                if hata:
                    raise ValueError(hata)
                mesaj = "Kategori kaydedildi."
            elif islem == "kategori_sil":
                mesaj = "Kategori pasife al\u0131nd\u0131." if db.kategori_sil(c, request.form.get("code") or "", kim) else "Kategori bulunamad\u0131."
            elif islem == "yedek":
                return _yedek_indir(c, kim)
            else:
                mesaj = "Bilinmeyen i\u015flem."
        except ValueError as e:
            mesaj = f"Hata: {e}"
    tg_f = {"q": (request.args.get("tg_q") or "").strip()[:60], "sure": sayi(request.args.get("tg_sure"), 0), "durum": request.args.get("tg_durum") or "",
            "adet": sayi(request.args.get("tg_adet"), 0)}
    tum = tg_listesi(c)
    log_yol = os.path.join(ayar()["LOG"], "bot.log")
    return render_template("bot.html", mesaj=mesaj, durum=_bot_durumu(c), tg_kullanicilar=tg_filtrele(tum, tg_f["q"], tg_f["sure"], tg_f["durum"], tg_f["adet"]),
                           tg_toplam=len(tum), tg_f=tg_f, kategoriler=db.kategoriler(c), akis_alanlari=db.AKIS_ALANLARI, bakim=db.bakim_modu(c), gyazo_bakim=db.gyazo_bakim(c),
                           oturumlar=db.oturumlar(c), log=son_log(log_yol, 150), hatalar=son_log(log_yol, 40, True), ist=_bot_istatistik(c, tum),
                           ac_tg=(request.args.get("tg") or "").strip()[:20], yedekler=_yedekler())


def _yedekler():
    out = []
    try:
        for ad in sorted(os.listdir(ayar()["YEDEK"]), reverse=True)[:10]:
            y = os.path.join(ayar()["YEDEK"], ad)
            if ad.endswith(".db"):
                out.append({"ad": ad, "boyut_kb": os.path.getsize(y) // 1024, "zaman": datetime.fromtimestamp(os.path.getmtime(y)).strftime("%Y-%m-%d %H:%M:%S")})
    except OSError:
        pass
    return out


def _yedek_indir(c, kim):
    ad = f"kanit-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    hedef = db.yedekle(c, os.path.join(ayar()["YEDEK"], ad))
    db.denetim_yaz(c, kim, "yedek", yeni=ad, ip=ip())
    return send_file(hedef, as_attachment=True, download_name=ad, mimetype="application/octet-stream")


@bp.route("/bot/kullanici/<tg_id>.json")
@admin_gerekli
def bot_kullanici_json(tg_id):
    tg_id = tg_id.strip()
    if not tg_id.isdigit() or len(tg_id) > 20:
        abort(404)
    c = conn()
    u = db.tg_al(c, tg_id) or {}
    ot = db.oturum_al(c, tg_id)
    if ot:
        ot = {k: v for k, v in ot.items() if k != "fileId"}
        ot["gorsel_var"] = bool(ot.get("gorsel_var") or ot.get("gorsel_dosya") or ot.get("dosya"))
    rows = c.execute("SELECT id, proje, kategori, personel, uye_id, ana_uye_id, tarih, kt, silindi FROM kayitlar WHERE ekleyen_tg_id=? ORDER BY COALESCE(tarih,'0000') DESC, id DESC", (tg_id,)).fetchall()
    proje, kategori, capraz = {}, {}, {}
    onayli = bekleyen = silinen = 0
    for r in rows:
        if r["silindi"]:
            silinen += 1
            continue
        proje[r["proje"]] = proje.get(r["proje"], 0) + 1
        k = (r["kategori"] or "").upper() or "-"
        kategori[k] = kategori.get(k, 0) + 1
        cp = capraz.setdefault(r["proje"], {})
        cp[k] = cp.get(k, 0) + 1
        if r["kt"]:
            onayli += 1
        else:
            bekleyen += 1
    son = [{"id": r["id"], "proje": r["proje"], "kategori": r["kategori"] or "", "personel": r["personel"] or "", "uye_id": r["uye_id"] or "",
            "ana_uye_id": r["ana_uye_id"] or "", "tarih": r["tarih"] or "", "kt": bool(r["kt"]), "silindi": bool(r["silindi"])} for r in rows[:25]]
    return jsonify({"id": tg_id, "username": u.get("username") or u.get("onay_adi") or "", "first_name": u.get("first_name") or "",
                    "last_seen": u.get("last_seen") or "", "status": u.get("status") or "",
                    "onayli": bool(u.get("onayli")), "onay_tarihi": u.get("onay_tarihi") or "",
                    "engelli": bool(u.get("engelli")), "engel_sebep": u.get("engel_sebep") or "", "engel_tarihi": u.get("engel_tarihi") or "",
                    "deneme": u.get("deneme") or 0, "oturum": ot,
                    "bot_sayac": {"kayit": u.get("kayit_sayisi") or 0, "son_tarih": u.get("son_kayit_tarihi") or "", "son_proje": u.get("son_kayit_proje") or "",
                                  "son_kategori": u.get("son_kayit_kategori") or "", "proje": u.get("proje_sayilari") or {}, "kategori": u.get("kategori_sayilari") or {}},
                    "panel": {"toplam": onayli + bekleyen, "onayli": onayli, "bekleyen": bekleyen, "silinen": silinen, "proje": proje, "kategori": kategori, "capraz": capraz, "son": son},
                    "zaman": simdi()})


# ==================== denetim ====================
@bp.route("/denetim")
@admin_gerekli
def denetim():
    c = conn()
    q = (request.args.get("q") or "").strip()[:80]
    islem = (request.args.get("islem") or "").strip()[:40]
    kullanici = (request.args.get("kullanici") or "").strip()[:40]
    proje = (request.args.get("proje") or "").strip().upper()[:20]
    t1, t2 = (request.args.get("tarih1") or "")[:10], (request.args.get("tarih2") or "")[:10]
    where, par = ["1=1"], []
    if q:
        where.append("(kullanici LIKE ? OR islem LIKE ? OR CAST(kayit_id AS TEXT)=? OR eski LIKE ? OR yeni LIKE ?)")
        par += [f"%{q}%", f"%{q}%", q, f"%{q}%", f"%{q}%"]
    if islem:
        where.append("islem=?"); par.append(islem)
    if kullanici:
        where.append("kullanici=?"); par.append(kullanici)
    if proje:
        where.append("proje=?"); par.append(proje)
    if t1:
        where.append("zaman >= ?"); par.append(t1 + " 00:00:00")
    if t2:
        where.append("zaman <= ?"); par.append(t2 + " 23:59:59")
    rows = c.execute(f"SELECT * FROM denetim WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT 500", par).fetchall()
    islemler = [r[0] for r in c.execute("SELECT DISTINCT islem FROM denetim ORDER BY 1").fetchall()]
    kullanicilar = [r[0] for r in c.execute("SELECT DISTINCT kullanici FROM denetim WHERE kullanici<>'' ORDER BY 1").fetchall()]
    return render_template("denetim.html", kayitlar=[dict(r) for r in rows], q=q, f={"islem": islem, "kullanici": kullanici, "proje": proje, "tarih1": t1, "tarih2": t2},
                           islemler=islemler, kullanicilar=kullanicilar)


# ==================== arsiv (dokunulmaz kopya) ====================
@bp.route("/arsiv")
@admin_gerekli
def arsiv_sayfasi():
    c = conn()
    proje = (request.args.get("proje") or "").strip().upper()[:20]
    q = N.normalle(request.args.get("q") or "")[:100]
    boy = sayi(request.args.get("boy"), 200)
    if boy not in (200, 500, 0):
        boy = 200
    sayfa = max(1, sayi(request.args.get("s"), 1))
    where, par = ["a.olay IN ('olustur','ice_aktar')"], []
    if proje:
        where.append("k.proje=?"); par.append(proje)
    if q:
        # simdiki hali ya da ilk kopyasi (arsiv JSON'u) uyanlar
        where.append("(k.personel_norm=? OR k.uye_norm=? OR k.ana_norm=? OR k.link_norm LIKE ? OR a.veri LIKE ?)"); par += [q, q, q, f"%{q}%", f"%{q}%"]
    w = " AND ".join(where)
    toplam = c.execute(f"SELECT COUNT(*) FROM arsiv a JOIN kayitlar k ON k.id=a.kayit_id WHERE {w}", par).fetchone()[0]
    limit = f" LIMIT {int(boy)} OFFSET {int((sayfa - 1) * boy)}" if boy else ""
    rows = c.execute(f"""SELECT a.id arsiv_id, a.kayit_id, a.zaman, a.olay, a.kim, a.veri, k.proje, k.kt, k.silindi, k.surum, k.personel, k.uye_id, k.ana_uye_id, k.kategori, k.guncelleme,
                         (SELECT COUNT(*) FROM arsiv b WHERE b.kayit_id=a.kayit_id) kopya
                         FROM arsiv a JOIN kayitlar k ON k.id=a.kayit_id WHERE {w} ORDER BY a.id DESC{limit}""", par).fetchall()
    liste = []
    for r in rows:
        d = dict(r)
        try:
            d["ilk"] = json.loads(d.pop("veri"))
        except Exception:
            d["ilk"] = {}
        d["durum"] = "silindi" if d["silindi"] else ("onayli" if d["kt"] else "bekliyor")
        liste.append(d)
    return render_template("arsiv.html", kayitlar=liste, toplam=toplam, sayfa=sayfa, sayfa_sayisi=(max(1, (toplam + boy - 1) // boy) if boy else 1), boy=boy,
                           proje=proje, q=request.args.get("q") or "", yedekler=_yedekler(), arsiv_toplam=c.execute("SELECT COUNT(*) FROM arsiv").fetchone()[0])


@bp.route("/arsiv/yedek", methods=["POST"])
@admin_gerekli
def arsiv_yedek():
    return _yedek_indir(conn(), g.k["kullanici_adi"])

# -*- coding: utf-8 -*-
"""Excel kopyasi + bot logu -> panel.db. Panel YENILEME_SN saniyede bir kaynak degisti mi diye bakar; degistiyse yeniden okur.

Kurallar:
  - Excel'e asla yazilmaz; kaynak = bot klasoru (salt okunur).
  - Kayit anahtari = sayfa + link kimligi (gyazo id / OneDrive dosya adi); linksiz satirda A-G parmak izi.
  - Panelden yapilmis ve bot tarafindan henuz Excel'e islenmemis degisiklikler (bekleyen_islem) Excel'den ezilmez.
  - Excel'de artik gorunmeyen anahtar silinmez, excel_durum='silinmis' olur (elle silinmis olabilir).
"""
import os, json, time, threading
from datetime import datetime, timedelta
from . import excel_oku, log_oku, kuyruk, db

_kilit = threading.Lock()


def _simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _imza(yol):
    try:
        st = os.stat(yol)
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return "yok"


def calistir(ayar, conn, onbellek_klasor, gorsel_cozucu=None, zorla=False):
    if not _kilit.acquire(blocking=False):
        return {"atlandi": True}
    t0 = time.time()
    rapor = {"zaman": _simdi(), "sayfalar": {}, "yeni": 0, "degisen": 0, "silinen": 0, "hata": None, "uyari": None}
    try:
        # Excel (ve bot logu) degismediyse yeniden okumaya gerek yok: sadece bot sonuclarini isle (30 sn'de bir ucuz kontrol)
        bot_kopya = os.path.join(ayar["BOT_KLASOR"], excel_oku.BOT_KOPYA_ADI)
        imza = _imza(ayar["EXCEL"]) + "|" + _imza(bot_kopya) + "|" + _imza(ayar.get("LOG_DOSYA") or "") + "|" + _imza(os.path.join(ayar["BOT_KLASOR"], "kayitlar.jsonl"))
        if not zorla and db.ayar_al(conn, "kaynak_imza") == imza and conn.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] > 0:
            islenen = sonuc_isle(ayar, conn)
            if islenen:
                db.ayar_yaz(conn, "son_degisiklik", _simdi())
            rapor.update({"atlandi": True, "sebep": "kaynak degismedi", "sonuc": islenen})
            return rapor
        kopya, uyari = excel_oku.kopyala(ayar["EXCEL"], onbellek_klasor)
        rapor["uyari"] = uyari
        # Kaynak Excel'in yazilma zamani (OneDrive bot bilgisayarinin saatini korur). Bot bir panel islemini
        # uyguladiktan sonra sonuc dosyasi (kucuk) Excel'den (buyuk) once gelir; o arada eski kopya panelin
        # degisikligini ezmesin: panel_uygulama'dan eski kopyada o kaydin alanlarina dokunulmaz.
        try:
            excel_zaman = datetime.fromtimestamp(os.path.getmtime(ayar["EXCEL"]))
        except OSError:
            excel_zaman = datetime.now()
        if uyari is None and os.path.exists(bot_kopya) and os.path.getmtime(bot_kopya) >= os.path.getmtime(ayar["EXCEL"]) - 1:
            pass  # ana dosya kopyalanabildi ya da bot kopyasi guncel; excel_zaman ana dosyanin zamani kalir
        korunan = set()
        sayfalar = excel_oku.oku(kopya, ayar.get("SUTUN_HARITASI") or {})
        # ekleyen eslemesi
        bot_kl = ayar["BOT_KLASOR"]
        log_kayitlar = log_oku.eslestir(ayar.get("LOG_DOSYA") or os.path.join(bot_kl, "bot_log.txt"),
                                        os.path.join(bot_kl, "kullanicilar.json"), os.path.join(bot_kl, "backups"))
        jsonl = log_oku.kayitlar_jsonl(os.path.join(bot_kl, "kayitlar.jsonl"))
        harita = log_oku.link_haritasi(log_kayitlar, jsonl)

        gorulen = set()
        tum_anahtarlar = {s["anahtar"] for satirlar in sayfalar.values() for s in satirlar}
        for sayfa, satirlar in sayfalar.items():
            rapor["sayfalar"][sayfa] = len(satirlar)
            for s in satirlar:
                gorulen.add(s["anahtar"])
                tur, kimlik = excel_oku.link_turu_ve_kimlik(s["link"])
                ek = harita.get(f"{tur}:{kimlik}") if kimlik else None
                tarih = s["tarih"] or (ek["zaman"] if ek else None)
                gorsel_dosya = None
                if gorsel_cozucu:
                    yol, _ = gorsel_cozucu.yerel_dosya({"link": s["link"], "proje": sayfa, "gorsel_dosya": None, "anahtar": s["anahtar"]})
                    gorsel_dosya = yol
                mevcut = conn.execute("SELECT * FROM kayitlar WHERE anahtar=?", (s["anahtar"],)).fetchone()
                if mevcut is None:
                    # Eski Excel kopyasi: panelden duzenlenmis (anahtari degismis) bir kaydin ayni satirdaki ESKI hali
                    # "yeni kayit" diye eklenmesin; bot uygulamasindan eski kopyada ayni satir numarali korunan kayit varsa atla.
                    es = conn.execute("SELECT id, panel_uygulama FROM kayitlar WHERE proje=? AND excel_satir=? AND panel_uygulama IS NOT NULL AND silindi=0 ORDER BY panel_uygulama DESC", (sayfa, s["satir"])).fetchone()
                    if es and _eski_kopya(excel_zaman, es["panel_uygulama"]):
                        korunan.add(es["id"])
                        continue
                    # Anahtari degismis ayni kayit olabilir (ayni linkin ikizi silindi/eklendi, linksiz satir elle duzeltildi):
                    # bu okumada hic gorulmeyen eski kaydi ayni link / ayni satir uzerinden yeniden bagla, kimligi korunsun.
                    mevcut = _yeniden_bagla(conn, sayfa, s, kimlik, tum_anahtarlar, excel_zaman)
                if mevcut is None:
                    conn.execute("""INSERT INTO kayitlar(anahtar,proje,kategori,personel,uye_id,ana_uye_id,tip,link,link_turu,gorsel_dosya,tarih,tarih_ham,excel_satir,excel_durum,
                                    kt,kt_kaynak,aciklama,gorsel2,ek_not,ekleyen_id,ekleyen_ad,ekleyen_guven,ilk_gorulme,son_gorulme,guncelleme)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'var',?,'excel',?,?,?,?,?,?,?,?,?)""",
                                 (s["anahtar"], sayfa, s["kategori"], s["personel"], s["uye"], s["ana"], s["tip"], s["link"], tur, gorsel_dosya, tarih, s["tarih_ham"], s["satir"],
                                  s["kt"], s["aciklama"], s["gorsel2"], s["ek_not"],
                                  ek["ekleyen_id"] if ek else None, ek["ekleyen_ad"] if ek else None, ek["guven"] if ek else None, _simdi(), _simdi(), _simdi()))
                    rapor["yeni"] += 1
                else:
                    degisti = False
                    guncel = {"proje": sayfa, "kategori": s["kategori"], "personel": s["personel"], "uye_id": s["uye"], "ana_uye_id": s["ana"], "tip": s["tip"],
                              "link": s["link"], "link_turu": tur, "tarih": tarih, "tarih_ham": s["tarih_ham"], "excel_satir": s["satir"], "excel_durum": "var",
                              "aciklama": s["aciklama"], "gorsel2": s["gorsel2"], "ek_not": s["ek_not"]}
                    if gorsel_dosya:
                        guncel["gorsel_dosya"] = gorsel_dosya
                    if ek and (not mevcut["ekleyen_id"] or mevcut["ekleyen_guven"] != "kesin"):
                        guncel.update({"ekleyen_id": ek["ekleyen_id"], "ekleyen_ad": ek["ekleyen_ad"], "ekleyen_guven": ek["guven"]})
                    # bekleyen panel islemi varsa, o alanlari Excel'den ezme
                    bekleyen = mevcut["bekleyen_islem"]
                    if _eski_kopya(excel_zaman, mevcut["panel_uygulama"]):
                        bekleyen = bekleyen or "eski_kopya"   # Excel kopyasi botun uygulamasindan eski
                        korunan.add(mevcut["id"])
                    if bekleyen in ("duzenle", "eski_kopya"):
                        for k in ("kategori", "personel", "uye_id", "ana_uye_id", "tip", "aciklama"):
                            guncel.pop(k, None)
                    if bekleyen in ("kt",):
                        pass  # kt asagida ayri
                    if bekleyen in ("sil", "eski_kopya") or mevcut["silindi"]:
                        guncel.pop("excel_durum", None)
                    # KT: panelden isaretlendiyse ve bot henuz islemediyse Excel ezmesin
                    if bekleyen not in ("kt", "eski_kopya"):
                        if mevcut["kt_kaynak"] == "panel" and mevcut["kt"] != s["kt"] and mevcut["kt_zaman"] and (datetime.now() - datetime.strptime(mevcut["kt_zaman"], "%Y-%m-%d %H:%M:%S")).total_seconds() < 600:
                            pass  # 10 dk icinde panelden degisti; Excel daha eski kopya olabilir
                        else:
                            guncel["kt"] = s["kt"]
                            if mevcut["kt"] != s["kt"]:
                                guncel["kt_kaynak"] = "excel"
                    for k, v in guncel.items():
                        if (mevcut[k] or "") != (v or "") and not (k == "kt" and int(mevcut[k] or 0) == int(v or 0)):
                            degisti = True
                            break
                    guncel["son_gorulme"] = _simdi()
                    if degisti:
                        guncel["guncelleme"] = _simdi()
                        rapor["degisen"] += 1
                    sets = ", ".join(f"{k}=?" for k in guncel)
                    conn.execute(f"UPDATE kayitlar SET {sets} WHERE id=?", (*guncel.values(), mevcut["id"]))
        # Excel'de artik olmayanlar
        if gorulen:
            for r in conn.execute("SELECT id, anahtar, bekleyen_islem FROM kayitlar WHERE excel_durum='var'").fetchall():
                if r["anahtar"] not in gorulen and r["bekleyen_islem"] != "sil" and r["id"] not in korunan:
                    conn.execute("UPDATE kayitlar SET excel_durum='silinmis', guncelleme=? WHERE id=?", (_simdi(), r["id"]))
                    rapor["silinen"] += 1
        # bot sonuclari
        islenen = sonuc_isle(ayar, conn)
        db.ayar_yaz(conn, "kaynak_imza", imza)
        if rapor["yeni"] or rapor["degisen"] or rapor["silinen"] or islenen:
            db.ayar_yaz(conn, "son_degisiklik", _simdi())
    except Exception as e:
        import traceback
        rapor["hata"] = f"{type(e).__name__}: {e}"
        rapor["iz"] = traceback.format_exc()[-1500:]
    finally:
        rapor["sure_ms"] = int((time.time() - t0) * 1000)
        if not rapor.get("atlandi"):
            try:
                conn.execute("INSERT INTO ice_aktarim(zaman,sure_ms,sayfalar,yeni,degisen,silinen,hata) VALUES(?,?,?,?,?,?,?)",
                             (rapor["zaman"], rapor["sure_ms"], json.dumps(rapor["sayfalar"], ensure_ascii=False), rapor["yeni"], rapor["degisen"], rapor["silinen"], rapor["hata"] or rapor["uyari"]))
                db.ayar_yaz(conn, "son_ice_aktarim", json.dumps(rapor, ensure_ascii=False))
            except Exception:
                pass
        _kilit.release()
    return rapor


def _eski_kopya(excel_zaman, panel_uygulama):
    """Excel kopyasi, panel isleminin bot tarafindan uygulanmasindan eski mi?"""
    try:
        return bool(panel_uygulama) and excel_zaman < datetime.strptime(panel_uygulama, "%Y-%m-%d %H:%M:%S") - timedelta(seconds=2)
    except ValueError:
        return False


def _yeniden_bagla(conn, sayfa, s, kimlik, tum_anahtarlar, excel_zaman):
    """Bu okumada anahtari bulunmayan satir icin, bu okumada hic gorulmeyecek eski bir kayit ara:
    linkli satirda ayni link (uye/personel uyani tercih), linksiz satirda ayni satir numarasi. Bulunursa anahtari guncellenir."""
    if kimlik:
        adaylar = conn.execute("SELECT * FROM kayitlar WHERE proje=? AND link=? ORDER BY silindi, id", (sayfa, s["link"])).fetchall()
    else:
        adaylar = conn.execute("SELECT * FROM kayitlar WHERE proje=? AND excel_satir=? AND link_turu IN ('bos','metin') AND silindi=0 ORDER BY id", (sayfa, s["satir"])).fetchall()
    # bu okumada gorulecek anahtarlar ve bu kopyadan daha yeni panel degisikligi tasiyan kayitlar aday degil
    adaylar = [a for a in adaylar if a["anahtar"] not in tum_anahtarlar and not _eski_kopya(excel_zaman, a["panel_uygulama"])]
    if not adaylar:
        return None
    def puan(a):
        return ((a["uye_id"] or "") == (s["uye"] or ""), (a["personel"] or "") == (s["personel"] or ""), not a["silindi"], -abs((a["excel_satir"] or 0) - s["satir"]))
    secilen = max(adaylar, key=puan)
    if kimlik and not ((secilen["uye_id"] or "") == (s["uye"] or "") or (secilen["personel"] or "") == (s["personel"] or "")) and len(adaylar) > 1:
        return None   # ayni linkli birden fazla eski kayit var ama hicbiri uymuyor: tahmin etme
    eski = secilen["anahtar"]
    conn.execute("UPDATE kayitlar SET anahtar=? WHERE id=?", (s["anahtar"], secilen["id"]))
    conn.execute("UPDATE denetim SET anahtar=? WHERE anahtar=?", (s["anahtar"], eski))
    tum_anahtarlar.add(s["anahtar"])
    return conn.execute("SELECT * FROM kayitlar WHERE id=?", (secilen["id"],)).fetchone()


def _anahtar_yenile(conn, kid):
    """Linksiz (parmak izi anahtarli) kayit panelden duzenlenince Excel'deki satirin parmak izi degisir;
    kaydin anahtarini yeni degerlerle hesapla ki sonraki okumada 'yeni kayit + silinmis' diye ikiye bolunmesin."""
    r = conn.execute("SELECT * FROM kayitlar WHERE id=?", (kid,)).fetchone()
    if not r or "|h:" not in (r["anahtar"] or ""):
        return
    degerler = {"personel": r["personel"], "uye": r["uye_id"], "ana": r["ana_uye_id"], "tip": r["tip"], "kategori": r["kategori"], "tarih_ham": r["tarih_ham"], "link": r["link"]}
    tur, kimlik = excel_oku.link_turu_ve_kimlik(r["link"] or "")
    if kimlik and r["anahtar"].startswith(f"{r['proje']}|{tur}:{kimlik}|h:"):
        yeni = f"{r['proje']}|{tur}:{kimlik}|h:" + excel_oku.parmak_ozeti(degerler, 8)
    elif not kimlik:
        yeni = f"{r['proje']}|h:" + excel_oku.parmak_ozeti(degerler)
    else:
        return
    if yeni == r["anahtar"]:
        return
    aday, n = yeni, 1
    while conn.execute("SELECT 1 FROM kayitlar WHERE anahtar=? AND id<>?", (aday, kid)).fetchone():
        n += 1
        aday = f"{yeni}#{n}"
    conn.execute("UPDATE kayitlar SET anahtar=? WHERE id=?", (aday, kid))
    conn.execute("UPDATE denetim SET anahtar=? WHERE anahtar=?", (aday, r["anahtar"]))


def sonuc_isle(ayar, conn):
    """panel_kuyruk_sonuc.jsonl -> bekleyen islemleri kapat. -> islenen (bu panele ait) sonuc sayisi"""
    offset = int(db.ayar_al(conn, "kuyruk_sonuc_offset", "0") or 0)
    son_id = db.ayar_al(conn, "kuyruk_sonuc_son_id")
    sonuclar, yeni_offset, yeni_son_id = kuyruk.sonuclari_oku(ayar, offset, son_id)
    islenen = 0
    for s in sonuclar:
        kid = s.get("id")
        if not kid:
            continue
        r = conn.execute("SELECT id, bekleyen_islem FROM kayitlar WHERE bekleyen_id=?", (kid,)).fetchone()
        if not r:
            # bot yonetim islemi (onayla/engelle/bakim ...) sonucu
            islenen += conn.execute("UPDATE islem_sonuclari SET durum=?, mesaj=?, sonuc_zaman=? WHERE id=?",
                                    ("ok" if s.get("durum") == "ok" else "hata", str(s.get("mesaj") or s.get("durum") or "")[:500], _simdi(), kid)).rowcount
            continue
        islenen += 1
        if s.get("durum") == "ok":
            uygulama = str(s.get("zaman") or _simdi())[:19]
            conn.execute("UPDATE kayitlar SET bekleyen_islem=NULL, bekleyen_id=NULL, bekleyen_hata=NULL, excel_satir=COALESCE(?, excel_satir), panel_uygulama=?, guncelleme=? WHERE id=?",
                         (s.get("satir"), uygulama, _simdi(), r["id"]))
            if r["bekleyen_islem"] == "sil":
                conn.execute("UPDATE kayitlar SET excel_durum='silinmis' WHERE id=?", (r["id"],))
            if r["bekleyen_islem"] == "geri_al":
                conn.execute("UPDATE kayitlar SET excel_durum='var' WHERE id=?", (r["id"],))
            if r["bekleyen_islem"] == "duzenle":
                _anahtar_yenile(conn, r["id"])
        else:
            mesaj = str(s.get("mesaj") or s.get("durum") or "hata")[:500]
            if r["bekleyen_islem"] == "sil":
                # silme uygulanamadi: kayit silinmis gorunmesin (geri al dugmesi de gereksiz)
                conn.execute("UPDATE kayitlar SET silindi=0, silen=NULL, silme_zamani=NULL, bekleyen_islem=NULL, bekleyen_id=NULL, bekleyen_hata=?, guncelleme=? WHERE id=?", ("silinemedi: " + mesaj, _simdi(), r["id"]))
            else:
                conn.execute("UPDATE kayitlar SET bekleyen_hata=?, guncelleme=? WHERE id=?", (mesaj, _simdi(), r["id"]))
    if yeni_offset != offset or yeni_son_id != son_id:
        db.ayar_yaz(conn, "kuyruk_sonuc_offset", yeni_offset)
        db.ayar_yaz(conn, "kuyruk_sonuc_son_id", yeni_son_id or "")
    # 15 dakikadir bot cevap vermediyse kullaniciya soyle (islem kuyrukta durur; bot acilinca yine uygulanir)
    conn.execute("""UPDATE kayitlar SET bekleyen_hata='bot 15 dakikadir yanit vermedi (bot kapali olabilir); islem kuyrukta bekliyor'
                    WHERE bekleyen_islem IS NOT NULL AND bekleyen_hata IS NULL AND guncelleme < datetime('now','localtime','-15 minutes')""")
    conn.execute("""UPDATE islem_sonuclari SET mesaj='bot 15 dakikadir yanit vermedi (bot kapali veya OneDrive esitleme bekliyor)'
                    WHERE durum='bekliyor' AND mesaj IS NULL AND zaman < datetime('now','localtime','-15 minutes')""")
    return islenen

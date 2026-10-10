# -*- coding: utf-8 -*-
"""Excel kopyasi + bot logu -> panel.db. Panel bu islemi arka planda YENILEME_DK dakikada bir yapar.

Kurallar:
  - Excel'e asla yazilmaz; kaynak = bot klasoru (salt okunur).
  - Kayit anahtari = sayfa + link kimligi (gyazo id / OneDrive dosya adi); linksiz satirda A-G parmak izi.
  - Panelden yapilmis ve bot tarafindan henuz Excel'e islenmemis degisiklikler (bekleyen_islem) Excel'den ezilmez.
  - Excel'de artik gorunmeyen anahtar silinmez, excel_durum='silinmis' olur (elle silinmis olabilir).
"""
import os, json, time, threading
from datetime import datetime
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
        imza = _imza(ayar["EXCEL"]) + "|" + _imza(ayar.get("LOG_DOSYA") or "") + "|" + _imza(os.path.join(ayar["BOT_KLASOR"], "kayitlar.jsonl"))
        if not zorla and db.ayar_al(conn, "kaynak_imza") == imza and conn.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] > 0:
            islenen = sonuc_isle(ayar, conn)
            if islenen:
                db.ayar_yaz(conn, "son_degisiklik", _simdi())
            rapor.update({"atlandi": True, "sebep": "kaynak degismedi", "sonuc": islenen})
            return rapor
        kopya, uyari = excel_oku.kopyala(ayar["EXCEL"], onbellek_klasor)
        rapor["uyari"] = uyari
        sayfalar = excel_oku.oku(kopya, ayar.get("SUTUN_HARITASI") or {})
        # ekleyen eslemesi
        bot_kl = ayar["BOT_KLASOR"]
        log_kayitlar = log_oku.eslestir(ayar.get("LOG_DOSYA") or os.path.join(bot_kl, "bot_log.txt"),
                                        os.path.join(bot_kl, "kullanicilar.json"), os.path.join(bot_kl, "backups"))
        jsonl = log_oku.kayitlar_jsonl(os.path.join(bot_kl, "kayitlar.jsonl"))
        harita = log_oku.link_haritasi(log_kayitlar, jsonl)

        gorulen = set()
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
                    if bekleyen == "duzenle":
                        for k in ("kategori", "personel", "uye_id", "ana_uye_id", "tip", "aciklama"):
                            guncel.pop(k, None)
                    if bekleyen in ("kt",):
                        pass  # kt asagida ayri
                    if bekleyen == "sil" or mevcut["silindi"]:
                        guncel.pop("excel_durum", None)
                    # KT: panelden isaretlendiyse ve bot henuz islemediyse Excel ezmesin
                    if bekleyen != "kt":
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
                if r["anahtar"] not in gorulen and r["bekleyen_islem"] != "sil":
                    conn.execute("UPDATE kayitlar SET excel_durum='silinmis', guncelleme=? WHERE id=?", (_simdi(), r["id"]))
                    rapor["silinen"] += 1
        # bot sonuclari
        islenen = sonuc_isle(ayar, conn)
        db.ayar_yaz(conn, "kaynak_imza", imza)
        if rapor["yeni"] or rapor["degisen"] or rapor["silinen"] or islenen:
            db.ayar_yaz(conn, "son_degisiklik", _simdi())
    except Exception as e:
        rapor["hata"] = f"{type(e).__name__}: {e}"
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


def sonuc_isle(ayar, conn):
    """panel_kuyruk_sonuc.jsonl -> bekleyen islemleri kapat. -> islenen (bu panele ait) sonuc sayisi"""
    offset = int(db.ayar_al(conn, "kuyruk_sonuc_offset", "0") or 0)
    sonuclar, yeni_offset = kuyruk.sonuclari_oku(ayar, offset)
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
            conn.execute("UPDATE kayitlar SET bekleyen_islem=NULL, bekleyen_id=NULL, bekleyen_hata=NULL, excel_satir=COALESCE(?, excel_satir), guncelleme=? WHERE id=?",
                         (s.get("satir"), _simdi(), r["id"]))
            if r["bekleyen_islem"] == "sil":
                conn.execute("UPDATE kayitlar SET excel_durum='silinmis' WHERE id=?", (r["id"],))
            if r["bekleyen_islem"] == "geri_al":
                conn.execute("UPDATE kayitlar SET excel_durum='var' WHERE id=?", (r["id"],))
        else:
            conn.execute("UPDATE kayitlar SET bekleyen_hata=?, guncelleme=? WHERE id=?", (str(s.get("mesaj") or s.get("durum") or "hata")[:500], _simdi(), r["id"]))
    if yeni_offset != offset:
        db.ayar_yaz(conn, "kuyruk_sonuc_offset", yeni_offset)
    # 15 dakikadir bot cevap vermediyse kullaniciya soyle (islem kuyrukta durur; bot acilinca yine uygulanir)
    conn.execute("""UPDATE kayitlar SET bekleyen_hata='bot 15 dakikadir yanit vermedi (bot kapali olabilir); islem kuyrukta bekliyor'
                    WHERE bekleyen_islem IS NOT NULL AND bekleyen_hata IS NULL AND guncelleme < datetime('now','localtime','-15 minutes')""")
    conn.execute("""UPDATE islem_sonuclari SET mesaj='bot 15 dakikadir yanit vermedi (bot kapali veya OneDrive esitleme bekliyor)'
                    WHERE durum='bekliyor' AND mesaj IS NULL AND zaman < datetime('now','localtime','-15 minutes')""")
    return islenen

# -*- coding: utf-8 -*-
"""Eski Telegram/Excel verisini **bir kez, açıkça** içe aktarma.

Bu modül canlı Excel eşitlemesi yapmaz, kuyruk/OneDrive kullanmaz ve hiçbir
kaynağı kendiliğinden izlemez. Çağıran CLI ya da yönetim işlemi bir ``kaynak``
vermelidir (veya açıkça LEGACY_SOURCE ayarı/ortamı tanımlanmış olmalıdır).
"""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from . import db, excel_oku, log_oku

_kilit = threading.Lock()
_KIMLIK = re.compile(r"\d+")


def _simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _calisma_kitabi(kaynak, ayar):
    """Açık legacy kaynak yolundan tek, güvenli çalışma kitabını seçer.

    Yedek ağacı otomatik taranmaz: hangi yedeğin aktarılacağı operatörün açık
    seçimidir. Bu, aynı satırları farklı tarihli yedeklerden yanlışlıkla
    birleştirmeyi önler.
    """
    kaynak = kaynak or ayar.get("LEGACY_SOURCE") or os.environ.get("LEGACY_SOURCE")
    if not kaynak:
        raise ValueError("Eski veri kaynağı gerekli: --kaynak / LEGACY_SOURCE belirtilmedi.")
    p = Path(str(kaynak)).expanduser()
    if not p.exists():
        raise ValueError(f"Eski veri kaynağı bulunamadı: {p}")
    if p.is_file():
        if p.suffix.lower() not in (".xlsx", ".xlsm"):
            raise ValueError(f"Eski kaynak bir Excel çalışma kitabı olmalı: {p}")
        return p.resolve(), p.resolve().parent
    if not p.is_dir():
        raise ValueError(f"Eski kaynak geçersiz: {p}")
    p = p.resolve()
    tercih = [p / "telegrambot_gyazo.xlsx", p / "panel_excel_kopya.xlsx"]
    for aday in tercih:
        if aday.is_file():
            return aday, p
    adaylar = sorted(x for x in p.iterdir() if x.is_file() and x.suffix.lower() in (".xlsx", ".xlsm") and not x.name.startswith("~$"))
    if len(adaylar) == 1:
        return adaylar[0].resolve(), p
    if not adaylar:
        raise ValueError(f"{p} içinde aktarılacak .xlsx bulunamadı.")
    raise ValueError(f"{p} içinde birden fazla Excel var; çalışma kitabı yolunu açıkça verin.")


def _dosya_ozeti(yol):
    h = hashlib.sha256()
    with open(yol, "rb") as f:
        for parca in iter(lambda: f.read(1024 * 1024), b""):
            h.update(parca)
    return h.hexdigest()


def _kaynak_kimligi(calisma_kitabi, ayar):
    """İçeriğe değil, sabit kaynak kimliğine dayalı satır anahtarı bileşeni.

    Excel satırı kullanıcı tarafından düzenlendiğinde dosya içerik özeti değişir;
    onu anahtara katmak yeniden aktarımda kopya üretirdi. Operatör farklı konuma
    taşıyacaksa ``LEGACY_SOURCE_ID`` ile aynı mantıksal kaynak kimliğini açıkça
    koruyabilir.
    """
    ham = str(ayar.get("LEGACY_SOURCE_ID") or Path(calisma_kitabi).name).strip()
    if not ham:
        ham = "legacy-workbook"
    normal = re.sub(r"\s+", " ", ham.replace("\\", "/")).casefold()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()[:20]


def _legacy_anahtar(kaynak_id, proje, satir):
    # Proje + fiziksel satır numarası değişmez; satır içeriği asla anahtarı değiştirmez.
    return f"legacy:{kaynak_id}:{proje_normalize(proje)}:{int(satir)}"


def proje_normalize(proje):
    return excel_oku.proje_normalize(proje)


def _bool(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("1", "true", "evet", "yes", "onayli", "approved")


def _idleri_oku(yol):
    """Eski onay/engel listelerinden yalnız kimlikleri alır; sır/şifre okumaz."""
    sonuc = set()
    if not yol or not os.path.isfile(yol):
        return sonuc
    try:
        with open(yol, encoding="utf-8-sig", errors="replace") as f:
            for satir in f:
                # Satırın tamamı bir ID ise en güvenilir biçimdir; açıklamalı eski
                # biçimlerde ilk sayısal parça Telegram kimliği olarak alınır.
                m = _KIMLIK.search(satir)
                if m:
                    sonuc.add(m.group(0))
    except OSError:
        pass
    return sonuc


def _eski_kullanicilar(kok, conn):
    """Eski Telegram kullanıcı listelerini açık importta tg_kullanicilar'a ekler.

    Panel hesabı, parola, oturum, Telegram offset/file-id ve config dosyası
    bilinçli olarak hiç okunmaz/taşınmaz. Mevcut yeni bot kullanıcıları
    ``INSERT OR IGNORE`` ile korunur.
    """
    onayli = _idleri_oku(os.path.join(kok, "onaylilar.txt"))
    engelli = _idleri_oku(os.path.join(kok, "engellenenler.txt"))
    adaylar = {}
    # Bu *sadece* eski Telegram kullanıcı veri dosyasıdır; config.json değildir.
    y = os.path.join(kok, "kullanicilar.json")
    if os.path.isfile(y):
        try:
            with open(y, encoding="utf-8-sig") as f:
                veri = json.load(f)
            if isinstance(veri, dict):
                # Yaygın eski biçim: {"telegram_id": {username, first_name, ...}}
                items = veri.items()
            elif isinstance(veri, list):
                items = ((x.get("id") or x.get("tg_id"), x) for x in veri if isinstance(x, dict))
            else:
                items = ()
            for uid, bilgi in items:
                if not isinstance(bilgi, dict) or uid in (None, ""):
                    continue
                uid = str(uid)
                adaylar[uid] = {
                    "username": str(bilgi.get("username") or ""),
                    "first_name": str(bilgi.get("first_name") or bilgi.get("ad") or ""),
                    "onayli": uid in onayli or _bool(bilgi.get("onayli")),
                    "engelli": uid in engelli or _bool(bilgi.get("engelli")),
                }
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    for uid in onayli | engelli:
        adaylar.setdefault(uid, {"username": "", "first_name": "", "onayli": uid in onayli, "engelli": uid in engelli})
    yeni = 0
    for uid, u in adaylar.items():
        cur = conn.execute(
            """INSERT OR IGNORE INTO tg_kullanicilar
               (id,username,first_name,onayli,engelli,onay_tarihi,last_seen)
               VALUES(?,?,?,?,?,?,?)""",
            (uid, u["username"][:200], u["first_name"][:200], int(u["onayli"]), int(u["engelli"]), _simdi() if u["onayli"] else None, None),
        )
        yeni += max(0, cur.rowcount)
    return {"aday": len(adaylar), "yeni": yeni, "onayli": len(onayli), "engelli": len(engelli)}


def _eski_kategoriler(kok,conn,kaynak_id):
    """Sadece ilk açık kaynak aktarımı; sonradan sitede düzenleneni ezmez."""
    key='kategori_aktarildi:'+kaynak_id
    if db.ayar_al(conn,key):return 0
    path=Path(kok)/'kategoriler.json'
    if not path.exists():return 0
    try:items=json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError,OSError):return 0
    if isinstance(items,dict):items=items.get('kategoriler',[])
    if not isinstance(items,list):return 0
    count=0
    for item in items:
        if not isinstance(item,dict):continue
        code=str(item.get('code','')).lower();label=str(item.get('label',''))[:80];mode=item.get('mode')
        if not re.fullmatch('[a-z0-9_]{1,48}',code) or not label or mode not in ('tek_uye','ark_ana','ana_only','sessiz_tip'):continue
        # Yalnız hiç yönetici müdahalesi olmayan varsayılanı taşı.
        edited=conn.execute("SELECT 1 FROM islem_sonuclari WHERE op IN ('kategori_kaydet','kategori_sil') AND ozet LIKE ? LIMIT 1",('%'+code+'%',)).fetchone()
        if edited:continue
        conn.execute('INSERT INTO kategoriler(code,label,mode) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET label=excluded.label,mode=excluded.mode',(code,label,mode));count+=1
    db.ayar_yaz(conn,key,'1');return count


def _log_haritasi(kok):
    """Ekleyen bilgisini mümkünse logdan alır; tahmini güven seviyesini korur."""
    log = os.path.join(kok, "bot_log.txt")
    kullanicilar = os.path.join(kok, "kullanicilar.json")
    # Yedek kullanıcı JSON'ları ancak eski log eşleme bilgisi için kullanılır;
    # config/oturum/offset dosyaları log_oku tarafından okunmaz.
    yedekler = os.path.join(kok, "backups")
    kayitlar = log_oku.eslestir(log, kullanicilar, yedekler)
    jsonl = log_oku.kayitlar_jsonl(os.path.join(kok, "kayitlar.jsonl"))
    return log_oku.link_haritasi(kayitlar, jsonl)


def _ekleyen(harita, link):
    tur, kimlik = excel_oku.link_turu_ve_kimlik(link)
    return (harita.get(f"{tur}:{kimlik}") if kimlik else None), tur


def _gorselleri_coz(s, proje, cozucu):
    if not cozucu:
        return None, None
    ana = {"link": s["link"], "gorsel_dosya": None, "proje": proje, "anahtar": s["anahtar"]}
    ana_yol, _ = cozucu.yerel_dosya(ana)
    iki_yol = None
    if s.get("gorsel2"):
        iki = {"link": s["link"], "gorsel2": s["gorsel2"], "gorsel2_dosya": None, "proje": proje, "anahtar": s["anahtar"]}
        if hasattr(cozucu, "ikinci_dosya"):
            iki_yol, _ = cozucu.ikinci_dosya(iki)
        else:
            iki["_gorsel2"] = True
            iki_yol, _ = cozucu.yerel_dosya(iki)
    return ana_yol, iki_yol


def calistir(ayar, conn, onbellek_klasor, gorsel_cozucu=None, zorla=False, kaynak=None):
    """Eski kaynağı açıkça içe aktarır ve rapor döndürür.

    ``zorla`` uyumluluk parametresidir; bu modül canlı eşitleme yapmadığından
    önceki importu güncellemez. Aynı kaynak tekrar çağrılabilir: satır anahtarı
    nedeniyle yalnızca ``INSERT OR IGNORE`` çalışır ve canlı/panel düzenlemeleri
    hiçbir zaman ezilmez.
    """
    if not _kilit.acquire(blocking=False):
        return {"atlandi": True, "sebep": "başka legacy import çalışıyor"}
    t0 = time.monotonic()
    try:
        kitap, kok = _calisma_kitabi(kaynak, ayar)
        kaynak_id = _kaynak_kimligi(kitap, ayar)
        rapor = {
            "zaman": _simdi(), "mod": "explicit_legacy_import", "kaynak": str(kitap),
            "kaynak_id": kaynak_id, "icerik_sha256": _dosya_ozeti(kitap),
            "sayfalar": {}, "yeni": 0, "yinelenen": 0, "degisen": 0,
            "silinen": 0, "kullanicilar": {}, "belirsizlik": [], "hata": None,
        }
        sayfalar = excel_oku.oku(str(kitap), ayar.get("SUTUN_HARITASI") or {})
        harita = _log_haritasi(str(kok))
        with db.transaction(conn):
            for ham_proje, satirlar in sayfalar.items():
                proje = proje_normalize(ham_proje)
                rapor["sayfalar"][proje] = len(satirlar)
                for s in satirlar:
                    anahtar = _legacy_anahtar(kaynak_id, proje, s["satir"])
                    ek, tur = _ekleyen(harita, s["link"])
                    gorsel_dosya, gorsel2_dosya = _gorselleri_coz(s, proje, gorsel_cozucu)
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO kayitlar(
                           anahtar,proje,kategori,personel,uye_id,ana_uye_id,tip,link,link_turu,
                           gorsel_dosya,tarih,tarih_ham,excel_satir,excel_durum,kt,kt_kaynak,
                           aciklama,gorsel2,gorsel2_dosya,ek_not,ekleyen_id,ekleyen_ad,ekleyen_guven,
                           ilk_gorulme,son_gorulme,guncelleme,kaynak,giris_tipi)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'var',?,'excel',?,?,?,?,?,?,?,?,?,?, 'legacy_excel',?)""",
                        (
                            anahtar, proje, s["kategori"], s["personel"], s["uye"], s["ana"], s["tip"],
                            s["link"], tur, gorsel_dosya, s["tarih"], s["tarih_ham"], s["satir"], s["kt"],
                            s["aciklama"], s.get("gorsel2") or "", gorsel2_dosya, s.get("ek_not") or "",
                            ek.get("ekleyen_id") if ek else None, ek.get("ekleyen_ad") if ek else None,
                            ek.get("guven") if ek else None, _simdi(), _simdi(), _simdi(),
                            "resim" if s["link"] else "yazili",
                        ),
                    )
                    if cur.rowcount:
                        rapor["yeni"] += 1
                    else:
                        rapor["yinelenen"] += 1
            rapor["kullanicilar"] = _eski_kullanicilar(str(kok), conn)
            rapor["kategoriler"] = _eski_kategoriler(str(kok),conn,kaynak_id)
            if rapor["yeni"] or rapor["kullanicilar"].get("yeni"):
                db.degisti(conn)
            # Eski gerçek kaynakta kullanıcı-log ilişkileri birden fazla aynı link
            # taşıyabiliyorsa log_oku ilk kaydı kullanır; bu bilgi kaynağı satırın
            # sahibi değil yalnız ekleyen metadatasıdır.
            if any(s.get("link") for ss in sayfalar.values() for s in ss) and not harita:
                rapor["belirsizlik"].append("Eski log/kesin ekleyen eşlemesi bulunamadı; ekleyen alanları boş bırakıldı.")
            db.ayar_yaz(conn, "son_legacy_import", json.dumps(rapor, ensure_ascii=False))
        rapor["sure_ms"] = int((time.monotonic() - t0) * 1000)
        # Rapor DB'ye süreden sonra tekrar yazılır; veri satırları asla güncellenmez.
        conn.execute(
            "INSERT INTO ice_aktarim(zaman,sure_ms,sayfalar,yeni,degisen,silinen,hata) VALUES(?,?,?,?,?,?,?)",
            (rapor["zaman"], rapor["sure_ms"], json.dumps(rapor["sayfalar"], ensure_ascii=False), rapor["yeni"], 0, 0, None),
        )
        db.ayar_yaz(conn, "son_legacy_import", json.dumps(rapor, ensure_ascii=False))
        return rapor
    except Exception as e:
        # Eksik kaynak hatası çağırana net olarak verilir; diğer okuma hataları da
        # raporda görünür ve ice_aktarim geçmişine yazılmaya çalışılır.
        if isinstance(e, ValueError) and ("kaynak" in str(e).lower() or "Excel" in str(e)):
            raise
        rapor = {
            "zaman": _simdi(), "mod": "explicit_legacy_import", "sayfalar": {}, "yeni": 0,
            "yinelenen": 0, "degisen": 0, "silinen": 0, "hata": f"{type(e).__name__}: {e}",
            "sure_ms": int((time.monotonic() - t0) * 1000),
        }
        try:
            conn.execute(
                "INSERT INTO ice_aktarim(zaman,sure_ms,sayfalar,yeni,degisen,silinen,hata) VALUES(?,?,?,?,?,?,?)",
                (rapor["zaman"], rapor["sure_ms"], "{}", 0, 0, 0, rapor["hata"]),
            )
        except Exception:
            pass
        return rapor
    finally:
        _kilit.release()

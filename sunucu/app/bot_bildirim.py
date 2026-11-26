# -*- coding: utf-8 -*-
"""2.4.0 — Panelden Telegram'a giden bildirim kuyruğu (bot_giden) ve mükerrer kanıt denetimi.

Web süreci Telegram'a hiç bağlanmaz: onay, silme ve "Ekleyene sor" olayları aynı
DB transaction'ında ``bot_giden`` tablosuna yazılır; bot süreci her poll turunda
bu kuyruğu boşaltır (yeniden deneme + üst sınır, hatalar botun günlüğüne yazılır).

Kurallar:
- Yalnız Telegram botuyla eklenmiş kayıtların ekleyenine gider (anahtar ``tg:``,
  ekleyen_id rakam, chat_id dolu). Eski Excel aktarımı ve panel kayıtları hariçtir.
- 30 günden eski kayıtlar için onay/silme bildirimi gönderilmez (toplu temizlikte
  gürültü olmasın).
- Aynı ekleyene giden ve henüz gönderilmemiş onay bildirimleri tek mesajda birleşir
  (toplu onay ve art arda tek tek onaylar).
- Onay kaldırma mesaj üretmez; gönderilmemiş onay bildiriminden o kayıt çıkarılır.

Ayarlar (.env): BOT_ONAY_BILDIRIMI, BOT_SILME_BILDIRIMI, BOT_SORU_BILDIRIMI (varsayılan 1),
BOT_ONAY_TOPLAMA_SN (varsayılan 20), BOT_BILDIRIM_MAX_DENEME (varsayılan 5).
"""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from . import db

LOG = logging.getLogger("kanit.bot_bildirim")

SEMA = """
CREATE TABLE IF NOT EXISTS bot_giden (
 id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, metin TEXT NOT NULL, keyboard_json TEXT,
 kayit_id INTEGER, tur TEXT NOT NULL, olusturma TEXT NOT NULL, gonderildi INTEGER NOT NULL DEFAULT 0,
 deneme INTEGER NOT NULL DEFAULT 0, hata TEXT,
 bot_id TEXT, durum TEXT NOT NULL DEFAULT 'bekliyor', sonraki_deneme TEXT, gonderim_zamani TEXT,
 message_id INTEGER, yorum_id INTEGER, kayit_idler TEXT, projeler TEXT
);
CREATE INDEX IF NOT EXISTS ix_bot_giden_bekleyen ON bot_giden(durum,sonraki_deneme,id);
CREATE INDEX IF NOT EXISTS ix_bot_giden_mesaj ON bot_giden(chat_id,message_id);
CREATE INDEX IF NOT EXISTS ix_bot_giden_kayit ON bot_giden(kayit_id,tur);
CREATE TABLE IF NOT EXISTS tg_tercihler (
 user_id TEXT PRIMARY KEY, gyazo INTEGER NOT NULL DEFAULT 0, guncelleme TEXT
)
"""

YAS_SINIRI_GUN = 30
LISTE_SINIRI = 10
_GECIKMELER = (30, 120, 600, 1800, 3600)
_TAKILI_SANIYE = 600
_KAPALI = {"0", "false", "hayir", "hayır", "kapali", "kapalı", "off", "no"}


# ---- ayarlar ------------------------------------------------------------------------------
def _ayar(ad: str, varsayilan: str) -> str:
    """Önce (varsa) ortak ayar katmanı, yoksa ortam/.env."""
    try:
        from . import ayarlar  # type: ignore[attr-defined]
        deger = ayarlar.deger(ad, varsayilan)
        if deger is not None:
            return str(deger)
    except Exception:
        pass
    return str(os.getenv(ad, varsayilan) or varsayilan)


def acik(ad: str, varsayilan: str = "1") -> bool:
    return _ayar(ad, varsayilan).strip().lower() not in _KAPALI


def _tam_sayi(ad: str, varsayilan: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(str(_ayar(ad, str(varsayilan))).strip())))
    except (TypeError, ValueError):
        return varsayilan


def onay_acik() -> bool:
    return acik("BOT_ONAY_BILDIRIMI")


def silme_acik() -> bool:
    return acik("BOT_SILME_BILDIRIMI")


def soru_acik() -> bool:
    return acik("BOT_SORU_BILDIRIMI")


def gyazo_sor() -> bool:
    """BOT_GYAZO_SOR=1: eski davranış, her görselde saklama yöntemi sorulur (varsayılan 0)."""
    return acik("BOT_GYAZO_SOR", "0")


def toplama_saniye() -> int:
    return _tam_sayi("BOT_ONAY_TOPLAMA_SN", 20, 0, 600)


def max_deneme() -> int:
    return _tam_sayi("BOT_BILDIRIM_MAX_DENEME", 5, 1, 20)


# ---- şema ve yardımcılar ------------------------------------------------------------------
def ensure_schema(conn) -> None:
    rows = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('bot_giden','tg_tercihler')")}
    if rows == {"bot_giden", "tg_tercihler"}:
        return
    for statement in SEMA.split(";"):
        if statement.strip():
            conn.execute(statement)


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=False)


def _zaman(saniye: int = 0) -> str:
    return (datetime.now() + timedelta(seconds=int(saniye))).strftime("%Y-%m-%d %H:%M:%S")


def _sozluk(record: Any) -> dict:
    if record is None:
        return {}
    try:
        return dict(record)
    except (TypeError, ValueError):
        return {}


def tg_hedef(record: Any) -> Optional[tuple[str, Optional[str]]]:
    """Telegram botuyla eklenmiş kaydın (chat_id, bot_id) hedefi; değilse None."""
    r = _sozluk(record)
    anahtar = str(r.get("anahtar") or "")
    ekleyen = str(r.get("ekleyen_id") or "")
    chat = str(r.get("chat_id") or "").strip()
    if not anahtar.startswith("tg:") or not ekleyen.isdigit() or not chat or not chat.lstrip("-").isdigit():
        return None
    return chat, (str(r.get("telegram_bot_id")) if r.get("telegram_bot_id") else None)


def yeni_mi(record: Any, gun: int = YAS_SINIRI_GUN) -> bool:
    tarih = str(_sozluk(record).get("tarih") or "")
    if not tarih:
        return False
    sinir = (datetime.now() - timedelta(days=gun)).strftime("%Y-%m-%d %H:%M:%S")
    return tarih[:19] >= sinir


def tarih_kisa(tarih: Any) -> str:
    """'2026-11-12 10:00:00' -> '12.11'."""
    text = str(tarih or "")
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d.%m")
    except ValueError:
        return text[:10]


class _Koruma:
    """Bildirim yazımı hiçbir zaman asıl panel işlemini (onay/silme/soru) geri aldırmaz."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("SAVEPOINT bot_bildirim")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("RELEASE SAVEPOINT bot_bildirim")
            return False
        try:
            self.conn.execute("ROLLBACK TO SAVEPOINT bot_bildirim")
            self.conn.execute("RELEASE SAVEPOINT bot_bildirim")
        except Exception:
            pass
        LOG.warning("Telegram bildirimi kuyruğa yazılamadı: %s", type(exc).__name__ if exc else "?")
        return isinstance(exc, Exception)


def kuyruga(conn, chat_id: Any, metin: str, tur: str, kayit_id: Optional[int] = None,
            keyboard: Optional[list] = None, *, bot_id: Optional[str] = None, yorum_id: Optional[int] = None,
            gecikme: int = 0, kayit_idler: Optional[list] = None, projeler: Optional[list] = None) -> int:
    """Telegram'a gidecek bir mesajı kalıcı kuyruğa ekler (ağ yok). Dönüş: bot_giden.id."""
    ensure_schema(conn)
    now = db.simdi()
    cur = conn.execute(
        "INSERT INTO bot_giden(chat_id,metin,keyboard_json,kayit_id,tur,olusturma,gonderildi,deneme,hata,bot_id,durum,"
        "sonraki_deneme,yorum_id,kayit_idler,projeler) VALUES(?,?,?,?,?,?,0,0,NULL,?,'bekliyor',?,?,?,?)",
        (str(chat_id), str(metin or "")[:4000],
         json.dumps(keyboard, ensure_ascii=False, separators=(",", ":")) if keyboard is not None else None,
         int(kayit_id) if kayit_id is not None else None, str(tur), now, bot_id, _zaman(gecikme) if gecikme else now,
         int(yorum_id) if yorum_id is not None else None,
         json.dumps(kayit_idler, ensure_ascii=False) if kayit_idler is not None else None,
         json.dumps(projeler, ensure_ascii=False) if projeler is not None else None),
    )
    return int(cur.lastrowid)


# ---- onay / silme -------------------------------------------------------------------------
def onay_metni(ids: list, projeler: list) -> str:
    gosterilen = ", ".join(f"#{int(i)}" for i in ids[:LISTE_SINIRI])
    if len(ids) > LISTE_SINIRI:
        gosterilen += " …"
    proje = ", ".join(_h(p) for p in projeler if p)
    return f"✅ {len(ids)} kanıtın onaylandı: {gosterilen}" + (f" ({proje})" if proje else "")


def _bekleyen_onay(conn, chat_id: str):
    return conn.execute(
        "SELECT * FROM bot_giden WHERE tur='onay' AND chat_id=? AND durum='bekliyor' ORDER BY id DESC LIMIT 1",
        (str(chat_id),),
    ).fetchone()


def _onaydan_cikar(conn, chat_id: str, kayit_id: int) -> None:
    for row in conn.execute(
        "SELECT * FROM bot_giden WHERE tur='onay' AND chat_id=? AND durum='bekliyor'", (str(chat_id),)
    ).fetchall():
        ids = [int(x) for x in json.loads(row["kayit_idler"] or "[]")]
        if int(kayit_id) not in ids:
            continue
        ids = [x for x in ids if x != int(kayit_id)]
        if not ids:
            conn.execute("DELETE FROM bot_giden WHERE id=?", (row["id"],))
            continue
        kalan = {int(r["id"]): str(r["proje"] or "") for r in conn.execute(
            f"SELECT id,proje FROM kayitlar WHERE id IN ({','.join('?' for _ in ids)})", ids)}
        projeler = list(dict.fromkeys(kalan[i] for i in ids if kalan.get(i)))
        conn.execute("UPDATE bot_giden SET kayit_idler=?,kayit_id=?,projeler=?,metin=? WHERE id=?",
                     (json.dumps(ids), ids[0], json.dumps(projeler, ensure_ascii=False), onay_metni(ids, projeler), row["id"]))


def onay_kuyruga(conn, record: Any, deger: Any) -> None:
    """Panel _kt_uygula kancası: onayda ekleyene (birleşik) bildirim, onay kaldırmada sessiz."""
    with _Koruma(conn):
        ensure_schema(conn)
        r = _sozluk(record)
        hedef = tg_hedef(r)
        if not hedef or r.get("id") is None:
            return
        chat_id, bot_id = hedef
        kid = int(r["id"])
        if not deger:
            _onaydan_cikar(conn, chat_id, kid)
            return
        if not onay_acik() or not yeni_mi(r):
            return
        proje = str(r.get("proje") or "")
        row = _bekleyen_onay(conn, chat_id)
        if row:
            ids = [int(x) for x in json.loads(row["kayit_idler"] or "[]")]
            projeler = [str(x) for x in json.loads(row["projeler"] or "[]")]
            if kid not in ids:
                ids.append(kid)
            if proje and proje not in projeler:
                projeler.append(proje)
            conn.execute("UPDATE bot_giden SET kayit_idler=?,projeler=?,metin=? WHERE id=?",
                         (json.dumps(ids), json.dumps(projeler, ensure_ascii=False), onay_metni(ids, projeler), row["id"]))
            return
        kuyruga(conn, chat_id, onay_metni([kid], [proje]), "onay", kid, bot_id=bot_id,
                gecikme=toplama_saniye(), kayit_idler=[kid], projeler=[proje] if proje else [])


def silme_kuyruga(conn, record: Any, sebep: Any = None) -> None:
    """Panel silme kancası: '❌ #N kaydın silindi. Neden: …' (neden isteğe bağlı)."""
    with _Koruma(conn):
        ensure_schema(conn)
        r = _sozluk(record)
        hedef = tg_hedef(r)
        if not hedef or r.get("id") is None:
            return
        chat_id, bot_id = hedef
        kid = int(r["id"])
        _onaydan_cikar(conn, chat_id, kid)
        if not silme_acik() or not yeni_mi(r):
            return
        sebep = db.metin_temizle(sebep or "", 300).strip()
        metin = f"❌ #{kid} kaydın silindi." + (f" Neden: {_h(sebep)}" if sebep else "")
        kuyruga(conn, chat_id, metin, "silme", kid, bot_id=bot_id)


# ---- ekleyene soru ------------------------------------------------------------------------
SORU_GOVDE_SINIRI = 3400


def soru_metni(record: Any, soru: str) -> str:
    r = _sozluk(record)
    kid = int(r.get("id") or 0)
    ozet = " / ".join(_h(x) for x in (r.get("proje"), r.get("kategori")) if x)
    uye = r.get("uye_id") or r.get("ana_uye_id") or r.get("lead_id")
    if uye:
        ozet += f" · {_h(uye)}"
    # Kaçışlı metin Telegram sınırını (4096) aşıp bir varlığın/etiketin ortasından kesilmesin:
    # ham metin kaçıştan önce kısaltılır, altbilgi her zaman bütün kalır.
    soru = str(soru or "")
    govde = _h(soru)
    if len(govde) > SORU_GOVDE_SINIRI:
        while len(_h(soru)) > SORU_GOVDE_SINIRI - 1:
            soru = soru[:len(soru) - max(1, (len(_h(soru)) - SORU_GOVDE_SINIRI + 1) // 6)]
        govde = _h(soru) + "…"
    return (f"❓ <b>#{kid}</b> için takım liderinin sorusu" + (f" ({ozet})" if ozet else "") + ":\n"
            f"{govde}\n\n"
            f"— Yanıtlamak için bu mesaja yanıt verin (Reply) ya da <code>/yanit {kid} metniniz</code> yazın.")


def soru_kuyruga(conn, record: Any, yorum_id: int, soru: str) -> int:
    hedef = tg_hedef(record)
    if not hedef:
        raise ValueError("Bu kaydı Telegram botuyla ekleyen biri yok; soruyu panel kullanıcısına yöneltin.")
    chat_id, bot_id = hedef
    return kuyruga(conn, chat_id, soru_metni(record, soru), "soru", int(_sozluk(record)["id"]),
                   bot_id=bot_id, yorum_id=int(yorum_id))


def soru_bul(conn, chat_id: Any, message_id: Any):
    """Telegram'da yanıtlanan (Reply) mesaj bir panel sorusuysa bot_giden satırı."""
    ensure_schema(conn)
    try:
        mid = int(message_id)
    except (TypeError, ValueError):
        return None
    return conn.execute(
        "SELECT * FROM bot_giden WHERE tur='soru' AND chat_id=? AND message_id=? ORDER BY id DESC LIMIT 1",
        (str(chat_id), mid),
    ).fetchone()


def son_soru(conn, chat_id: Any, kayit_id: int):
    """/yanit N için: bu sohbete bu kayıt hakkında yöneltilmiş en son soru."""
    ensure_schema(conn)
    return conn.execute(
        "SELECT * FROM bot_giden WHERE tur='soru' AND chat_id=? AND kayit_id=? ORDER BY id DESC LIMIT 1",
        (str(chat_id), int(kayit_id)),
    ).fetchone()


# ---- bot tarafı: kuyruğu boşaltma ---------------------------------------------------------
def talep_et(conn, bot_id: str, limit: int = 30) -> list[dict]:
    """Zamanı gelmiş satırları 'gonderiliyor' olarak işaretleyip döndürür (kısa transaction)."""
    ensure_schema(conn)
    now = db.simdi()
    eski = _zaman(-_TAKILI_SANIYE)
    with db.transaction(conn):
        # Gönderim ortasında çöken sürecin satırları 10 dk sonra yeniden sıraya döner.
        conn.execute("UPDATE bot_giden SET durum='bekliyor' WHERE durum='gonderiliyor' AND gonderim_zamani<?", (eski,))
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bot_giden WHERE durum='bekliyor' AND (bot_id IS NULL OR bot_id=?) "
            "AND COALESCE(sonraki_deneme,olusturma)<=? ORDER BY id LIMIT ?",
            (str(bot_id), now, max(1, min(int(limit), 200))),
        )]
        for row in rows:
            conn.execute("UPDATE bot_giden SET durum='gonderiliyor',gonderim_zamani=? WHERE id=?", (now, row["id"]))
    return rows


def sonuclandir(conn, row: dict, message_id: Optional[int] = None, hata: Optional[str] = None,
                kalici: bool = False, bekle: Optional[int] = None) -> str:
    """Teslim sonucunu yazar; dönüş 'tamam', 'tekrar' (yeniden denenecek) ya da 'olu'."""
    with db.transaction(conn):
        if hata is None:
            conn.execute("UPDATE bot_giden SET durum='tamam',gonderildi=1,hata=NULL,message_id=?,gonderim_zamani=? WHERE id=?",
                         (message_id, db.simdi(), row["id"]))
            return "tamam"
        if bekle is not None:  # 429: deneme sayılmaz
            conn.execute("UPDATE bot_giden SET durum='bekliyor',hata=?,sonraki_deneme=? WHERE id=?",
                         (str(hata)[:1000], _zaman(bekle), row["id"]))
            return "tekrar"
        deneme = int(row.get("deneme") or 0) + 1
        if kalici or deneme >= max_deneme():
            conn.execute("UPDATE bot_giden SET durum='olu',deneme=?,hata=? WHERE id=?", (deneme, str(hata)[:1000], row["id"]))
            _soru_iletilemedi(conn, row)
            return "olu"
        gecikme = _GECIKMELER[min(deneme - 1, len(_GECIKMELER) - 1)]
        conn.execute("UPDATE bot_giden SET durum='bekliyor',deneme=?,hata=?,sonraki_deneme=? WHERE id=?",
                     (deneme, str(hata)[:1000], _zaman(gecikme), row["id"]))
        return "tekrar"


def _soru_iletilemedi(conn, row: dict) -> None:
    """Teslim edilemeyen 'soru' satırı için soran takım liderine panel bildirimi (yanıt beklemesin)."""
    if row.get("tur") != "soru" or not row.get("yorum_id"):
        return
    try:
        yorum = conn.execute("SELECT kayit_id,kullanici FROM yorumlar WHERE id=?", (int(row["yorum_id"]),)).fetchone()
        if yorum and not str(yorum["kullanici"]).startswith("Telegram: "):
            db.mesaj_bildir(conn, yorum["kayit_id"], yorum["kullanici"], "yanit", "Telegram botu",
                            f"#{int(yorum['kayit_id'])} için sorunuz Telegram'da ekleyene iletilemedi "
                            "(bot engellenmiş ya da sohbet kapalı olabilir). Lütfen başka yoldan ulaşın.",
                            "tg_iletilemedi:" + str(int(row["id"])))
    except Exception as exc:  # bildirim yardımcıdır; kuyruğu durdurmaz
        LOG.warning("İletilemeyen soru bildirimi yazılamadı: %s", type(exc).__name__)


# ---- kullanıcı tercihi (/gyazo) -----------------------------------------------------------
def gyazo_tercihi(conn, user_id: Any) -> bool:
    ensure_schema(conn)
    row = conn.execute("SELECT gyazo FROM tg_tercihler WHERE user_id=?", (str(user_id),)).fetchone()
    return bool(row and row["gyazo"])


def gyazo_tercihi_yaz(conn, user_id: Any, acik_mi: bool) -> None:
    ensure_schema(conn)
    conn.execute("INSERT INTO tg_tercihler(user_id,gyazo,guncelleme) VALUES(?,?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET gyazo=excluded.gyazo,guncelleme=excluded.guncelleme",
                 (str(user_id), 1 if acik_mi else 0, db.simdi()))


# ---- mükerrer kanıt -----------------------------------------------------------------------
def mukerrer_bul(conn, proje: Any, kategori_code: Any = None, uye_id: Any = None, ana_uye_id: Any = None,
                 file_unique_id: Any = None, link_kimlik: Any = None, gun: int = YAS_SINIRI_GUN,
                 proje_icinde: bool = False) -> Optional[dict]:
    """Son ``gun`` gündeki silinmemiş benzer kayıt: aynı proje+kategori+üye ID, aynı görsel ya da aynı bağlantı.

    ``proje_icinde`` açıkken görsel/bağlantı eşleşmesi de yalnız aynı projede aranır (panel: kullanıcı
    okuma yetkisi olmayan projelerdeki kaydın numarasını ve tarihini görmemeli)."""
    sinir = (datetime.now() - timedelta(days=gun)).strftime("%Y-%m-%d %H:%M:%S")
    adaylar: list[tuple[str, str, list]] = []
    proje = str(proje or "").upper()
    kod = str(kategori_code or "").lower()
    on_kosul, on_param = ("proje=? AND ", [proje]) if proje_icinde else ("", [])
    if proje_icinde and not proje:
        return None
    if file_unique_id:
        adaylar.append(("gorsel", on_kosul + "file_unique_id=?", [*on_param, str(file_unique_id)]))
    if link_kimlik:
        kim = str(link_kimlik)
        adaylar.append(("link", on_kosul + "(instr(COALESCE(link,''),?)>0 OR instr(COALESCE(gorsel2,''),?)>0)",
                        [*on_param, kim, kim]))
    if proje and uye_id:
        adaylar.append(("uye", "proje=? AND LOWER(COALESCE(kategori_code,''))=? AND uye_id=?", [proje, kod, str(uye_id).strip()]))
    if proje and ana_uye_id and not uye_id:
        adaylar.append(("uye", "proje=? AND LOWER(COALESCE(kategori_code,''))=? AND ana_uye_id=?", [proje, kod, str(ana_uye_id).strip()]))
    for neden, kosul, params in adaylar:
        row = conn.execute(
            f"SELECT id,tarih FROM kayitlar WHERE COALESCE(silindi,0)=0 AND tarih>=? AND {kosul} ORDER BY id DESC LIMIT 1",
            [sinir, *params],
        ).fetchone()
        if row:
            return {"id": int(row["id"]), "tarih": row["tarih"], "neden": neden}
    return None


def mukerrer_metni(bulunan: dict) -> str:
    konu = {"uye": "Bu üye ID", "gorsel": "Bu görsel", "link": "Bu bağlantı"}.get(bulunan.get("neden"), "Bu kanıt")
    return f"{konu} {tarih_kisa(bulunan.get('tarih'))}'de #{int(bulunan['id'])} olarak kaydedilmiş."


def panel_mukerrer(conn, proje: Any, kategori_code: Any, degerler: dict) -> Optional[str]:
    """Panel 'kanıt ekle' için yumuşak uyarı metni (yoksa None)."""
    try:
        from .excel_oku import link_turu_ve_kimlik
        kimlikler = []
        for ad in ("link", "gorsel2"):
            link = str(degerler.get(ad) or "").strip()
            if link:
                kimlik = link_turu_ve_kimlik(link)[1]
                kimlikler.append(str(kimlik) if kimlik and len(str(kimlik)) >= 8 else link)
        bulunan = None
        for kimlik in kimlikler:
            bulunan = mukerrer_bul(conn, proje, link_kimlik=kimlik, proje_icinde=True)
            if bulunan:
                break
        if not bulunan:
            bulunan = mukerrer_bul(conn, proje, kategori_code, uye_id=degerler.get("uye_id") or None,
                                   ana_uye_id=degerler.get("ana_uye_id") or None)
    except Exception as exc:  # uyarı yardımcıdır; ekleme akışını bozmaz
        LOG.warning("Mükerrer denetimi yapılamadı: %s", type(exc).__name__)
        return None
    if not bulunan:
        return None
    return "⚠️ " + mukerrer_metni(bulunan) + " Yine de kaydetmek için yeniden gönderin."

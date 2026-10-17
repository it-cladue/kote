# -*- coding: utf-8 -*-
"""Telegram botu için panel yönetim işlevleri.

Bu modül eski dosya/kuyruk köprüsünü kullanmaz. Panel ve bot aynı SQLite
veritabanını kullandığı için değişiklikler kısa transaction'larla hemen görünür.
Gizli ortam değişkenleri burada okunmaz veya gösterilmez.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from . import db

_GECERLI_MODLAR = {"tek_uye", "ark_ana", "ana_only", "sessiz_tip"}
_KOD = re.compile(r"^[a-z0-9_]{1,48}$")


def _simdi() -> str:
    return db.simdi()


def _baglan(ayar):
    return db.baglan(ayar["DB"])


def _id(tg_id) -> str:
    value = str(tg_id or "").strip()
    if not value or len(value) > 64:
        raise ValueError("Telegram ID geçersiz.")
    return value


def _islem(conn, op: str, kim: str, ozet: str, mesaj: str = "tamamlandı") -> str:
    iid = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO islem_sonuclari(id,zaman,op,ozet,kullanici,durum,mesaj,sonuc_zaman) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (iid, _simdi(), op, ozet[:300], kim or "panel", "ok", mesaj[:1000], _simdi()),
    )
    return iid


def _denetle(conn, kim, islem, eski=None, yeni=None):
    db.denetim_yaz(conn, kim or "panel", islem, eski=eski, yeni=yeni)
    db.degisti(conn)


def onaylilar(ayar):
    conn = _baglan(ayar)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, COALESCE(username,first_name,'') ad, onay_tarihi tarih "
            "FROM tg_kullanicilar WHERE onayli=1 ORDER BY onay_tarihi DESC, id"
        )]
    finally:
        conn.close()


def engellenenler(ayar):
    conn = _baglan(ayar)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, COALESCE(username,first_name,'') kim, onay_tarihi tarih, "
            "COALESCE(engel_sebep,'') sebep FROM tg_kullanicilar WHERE engelli=1 ORDER BY id"
        )]
    finally:
        conn.close()


# CONTRACT.md'deki imzalar korunur.
def onayla(ayar, conn, tg_id, ad, kim="panel"):
    tg_id = _id(tg_id)
    ad = (ad or "")[:120]
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO tg_kullanicilar(id,username,first_name,onayli,engelli,onay_tarihi,last_seen,deneme) "
            "VALUES(?,?,?,1,0,?,?,0) "
            "ON CONFLICT(id) DO UPDATE SET username=CASE WHEN excluded.username<>'' THEN excluded.username ELSE tg_kullanicilar.username END, "
            "first_name=CASE WHEN excluded.first_name<>'' THEN excluded.first_name ELSE tg_kullanicilar.first_name END, "
            "onayli=1,engelli=0,engel_sebep=NULL,onay_tarihi=excluded.onay_tarihi,deneme=0",
            (tg_id, ad, ad, _simdi(), _simdi()),
        )
        conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (tg_id,))
        conn.execute("DELETE FROM tg_girisler WHERE user_id=?", (tg_id,))
        iid = _islem(conn, "onayla", kim, f"Onayla {tg_id}")
        _denetle(conn, kim, "bot_onayla", yeni=tg_id)
    return iid


def onay_kaldir(ayar, conn, tg_id, kim="panel"):
    tg_id = _id(tg_id)
    with db.transaction(conn):
        conn.execute("UPDATE tg_kullanicilar SET onayli=0,deneme=0 WHERE id=?", (tg_id,))
        conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (tg_id,))
        conn.execute("DELETE FROM tg_girisler WHERE user_id=?", (tg_id,))
        iid = _islem(conn, "onay_kaldir", kim, f"Onayı kaldır {tg_id}")
        _denetle(conn, kim, "bot_onay_kaldir", yeni=tg_id)
    return iid


def engelle(ayar, conn, tg_id, ad, sebep, kim="panel"):
    tg_id = _id(tg_id)
    ad, sebep = (ad or "")[:120], (sebep or "panel")[:300]
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO tg_kullanicilar(id,username,first_name,onayli,engelli,engel_sebep,last_seen,deneme) "
            "VALUES(?,?,?,0,1,?,?,3) "
            "ON CONFLICT(id) DO UPDATE SET username=CASE WHEN excluded.username<>'' THEN excluded.username ELSE tg_kullanicilar.username END, "
            "first_name=CASE WHEN excluded.first_name<>'' THEN excluded.first_name ELSE tg_kullanicilar.first_name END, "
            "engelli=1,engel_sebep=excluded.engel_sebep,deneme=3",
            (tg_id, ad, ad, sebep, _simdi()),
        )
        conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (tg_id,))
        conn.execute("DELETE FROM tg_girisler WHERE user_id=?", (tg_id,))
        iid = _islem(conn, "engelle", kim, f"Engelle {tg_id}")
        _denetle(conn, kim, "bot_engelle", yeni=json.dumps({"id": tg_id, "sebep": sebep}, ensure_ascii=False))
    return iid


def engel_kaldir(ayar, conn, tg_id, kim="panel"):
    tg_id = _id(tg_id)
    with db.transaction(conn):
        conn.execute("UPDATE tg_kullanicilar SET engelli=0,engel_sebep=NULL,deneme=0 WHERE id=?", (tg_id,))
        conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (tg_id,))
        conn.execute("DELETE FROM tg_girisler WHERE user_id=?", (tg_id,))
        iid = _islem(conn, "engel_kaldir", kim, f"Engel kaldır {tg_id}")
        _denetle(conn, kim, "bot_engel_kaldir", yeni=tg_id)
    return iid


def bakim_modu_ayarla(ayar, conn, acik, kim="panel"):
    acik = bool(acik)
    with db.transaction(conn):
        db.ayar_yaz(conn, "bakim_modu", "1" if acik else "0")
        iid = _islem(conn, "bakim", kim, "Bakım modu " + ("AÇ" if acik else "KAPAT"))
        _denetle(conn, kim, "bot_bakim", yeni="1" if acik else "0")
    return iid


def oturum_temizle(ayar, conn, tg_id=None, kim="panel"):
    target = str(tg_id or "").strip()
    with db.transaction(conn):
        if target:
            conn.execute("DELETE FROM tg_oturumlar WHERE user_id=?", (target,))
        else:
            conn.execute("DELETE FROM tg_oturumlar")
        iid = _islem(conn, "oturum_temizle", kim, f"Oturum temizle {target or '(hepsi)'}")
        _denetle(conn, kim, "bot_oturum_temizle", yeni=target or "hepsi")
    return iid


def kategori_kaydet(ayar, conn, code, label, mode, kim="panel"):
    code = str(code or "").strip().lower()
    label, mode = str(label or "").strip()[:80], str(mode or "").strip()
    if not _KOD.fullmatch(code):
        raise ValueError("Kategori kodu yalnızca küçük harf, rakam ve _ içerebilir.")
    if not label:
        raise ValueError("Kategori etiketi zorunludur.")
    if mode not in _GECERLI_MODLAR:
        raise ValueError("Geçersiz kategori modu.")
    with db.transaction(conn):
        conn.execute(
            "INSERT INTO kategoriler(code,label,mode,aktif) VALUES(?,?,?,1) "
            "ON CONFLICT(code) DO UPDATE SET label=excluded.label,mode=excluded.mode,aktif=1",
            (code, label, mode),
        )
        iid = _islem(conn, "kategori_kaydet", kim, f"Kategori {code}")
        _denetle(conn, kim, "bot_kategori_kaydet", yeni=json.dumps({"code": code, "label": label, "mode": mode}, ensure_ascii=False))
    return iid


def kategori_sil(ayar, conn, code, kim="panel"):
    code = str(code or "").strip().lower()
    if not _KOD.fullmatch(code):
        raise ValueError("Kategori kodu geçersiz.")
    with db.transaction(conn):
        # Pasife al: başlangıç varsayılanları sonraki bağlantıda yeniden eklemesin.
        # Geçmiş kayıt ve devam eden akışın kategori anlık görüntüsü korunur.
        conn.execute("UPDATE kategoriler SET aktif=0 WHERE code=?", (code,))
        iid = _islem(conn, "kategori_sil", kim, f"Kategori sil {code}")
        _denetle(conn, kim, "bot_kategori_sil", yeni=code)
    return iid


def yedek_al(ayar, conn, kim="panel"):
    """Yalnız SQLite veritabanını yedekler; medya yedeği işletme rehberindedir."""
    backup_dir = Path(ayar["BOT_KLASOR"]) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / ("panel-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".sqlite3")
    # sqlite backup API WAL durumunda tutarlı bir anlık görüntü üretir.
    dest = sqlite3.connect(target)
    # Telegram olayının açık yazma işlemi varsa aynı bağlantıyla backup bekler.
    # Ayrı salt-okuma kaynağı son commit edilmiş, tutarlı WAL görüntüsünü alır.
    source = sqlite3.connect(ayar['DB'], timeout=30) if conn.in_transaction else conn
    try:
        source.backup(dest)
    finally:
        if source is not conn:
            source.close()
        dest.close()
    with db.transaction(conn):
        iid = _islem(conn, "yedek", kim, "SQLite yedeği", target.name)
        _denetle(conn, kim, "bot_yedek", yeni=target.name)
    return iid


def son_islemler(conn, n=30):
    return [dict(r) for r in conn.execute("SELECT * FROM islem_sonuclari ORDER BY zaman DESC, rowid DESC LIMIT ?", (max(1, min(int(n), 200)),)).fetchall()]


def telegram_kullanicilari(ayar):
    conn = _baglan(ayar)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id,username,first_name,last_seen,kayit_sayisi,onayli,onay_tarihi,engelli,engel_sebep "
            "FROM tg_kullanicilar ORDER BY engelli DESC,onayli DESC,last_seen DESC,id LIMIT 1000"
        )]
    finally:
        conn.close()


def kategoriler(ayar):
    conn = _baglan(ayar)
    try:
        return [dict(r) for r in conn.execute("SELECT code,label,mode,aktif FROM kategoriler WHERE aktif=1 ORDER BY label COLLATE NOCASE")]
    finally:
        conn.close()


def bakim_modu(ayar):
    conn = _baglan(ayar)
    try:
        return db.ayar_al(conn, "bakim_modu", "0") == "1"
    finally:
        conn.close()


def oturumlar(ayar):
    conn = _baglan(ayar)
    try:
        out = []
        for row in conn.execute("SELECT bot_id,user_id,veri,guncelleme FROM tg_oturumlar ORDER BY guncelleme DESC LIMIT 500"):
            try:
                veri = json.loads(row["veri"])
            except (TypeError, ValueError):
                veri = {"step": "bozuk"}
            # Medya yolunu, file_id'yi ve olası admin parolası bekleme işaretini panele taşımayın.
            for key in ("pending_path", "file_id", "file_unique_id", "admin_prompt"):
                veri.pop(key, None)
            out.append({"id": row["user_id"], "bot_id": row["bot_id"], "guncelleme": row["guncelleme"], **veri})
        return out
    finally:
        conn.close()


def _redact(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"(bot)[0-9]+:[A-Za-z0-9_-]+", r"\1***", text)
    text = re.sub(r"(TELEGRAM_TOKEN|BOT_PASSWORD|ADMIN_PASSWORD)\s*[=:]\s*\S+", r"\1=***", text, flags=re.I)
    return text


def son_log(ayar, n=200, sadece_hata=False):
    yol = Path(ayar.get("LOG_DOSYA") or Path(ayar["BOT_KLASOR"]) / "bot_log.txt")
    if not yol.is_file():
        return []
    with yol.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 400_000))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    if sadece_hata:
        lines = [s for s in lines if any(x in s.lower() for x in (" hata", "error", "!"))]
    return [_redact(s) for s in lines[-max(1, min(int(n), 500)):]]


def _katalog_proje_kodlari(conn, ayar):
    """Aktif katalog projeleri; katalog okunamazsa eski sabit liste."""
    try:
        from . import katalog
        return [row["code"] for row in katalog.list_projects(conn, active_only=True)]
    except Exception:
        return list(ayar.get("PROJELER", []))


def config(ayar):
    """Sadece sır içermeyen çalışma görünümü; config/.env dosyaları okunmaz."""
    conn = _baglan(ayar)
    try:
        dead = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE durum='olu'").fetchone()[0]
        retry = conn.execute("SELECT COUNT(*) FROM tg_gelen WHERE durum='tekrar'").fetchone()[0]
        return {
            "Veritabanı": os.path.basename(ayar["DB"]),
            "Medya kökü": os.path.basename(str(ayar.get("GORSEL_KLASOR", ""))) or "gorseller",
            "Azami görsel": f"{int(ayar.get('MAX_GORSEL_BYTES', 0)) // (1024 * 1024)} MiB",
            "Projeler": ", ".join(_katalog_proje_kodlari(conn, ayar)),
            "Tekrar bekliyor": retry,
            "Ölü mektup": dead,
        }
    finally:
        conn.close()


def bot_calisiyor_mu(ayar):
    conn = _baglan(ayar)
    try:
        row = conn.execute("SELECT bot_id,heartbeat,hata FROM tg_durum WHERE heartbeat IS NOT NULL ORDER BY heartbeat DESC LIMIT 1").fetchone()
        if not row:
            return {"kaynak": "veritabanı", "yas_sn": None, "canli": None}
        try:
            age = max(0, int((datetime.now() - datetime.strptime(row["heartbeat"], "%Y-%m-%d %H:%M:%S")).total_seconds()))
        except (TypeError, ValueError):
            age = None
        return {"kaynak": "veritabanı", "yas_sn": age, "canli": age is not None and age < 180, "hata": _redact(row["hata"] or "")}
    finally:
        conn.close()


# Eski panel çağrıları için zararsız uyumluluk katmanı. Gyazo/OneDrive özelliği kaldırılmıştır.
def gyazo_bakim(ayar):
    return False


def gyazo_bakim_ayarla(ayar, conn, acik, kim="panel"):
    raise ValueError("Gyazo bakımı bu sunucu sürümünde yoktur; görseller yerelde tutulur.")


def yerel_bot_sureci():
    return False


def admin_sifresi_dogru(ayar, sifre):
    expected = os.environ.get("ADMIN_PASSWORD")
    return bool(expected and sifre) and hmac.compare_digest(str(expected), str(sifre))


def istatistik(conn):
    u=conn.execute('SELECT COUNT(*) toplam,SUM(onayli=1) onayli,SUM(engelli=1) engelli,SUM(onayli=0 AND engelli=0) onaysiz FROM tg_kullanicilar').fetchone()
    return {'kullanicilar':{k:u[k] or 0 for k in u.keys()},
            'projeler':[dict(r) for r in conn.execute('SELECT proje,COUNT(*) toplam,SUM(kt=0 AND silindi=0) bekleyen,SUM(kt=1 AND silindi=0) onayli,SUM(silindi=1) silinen FROM kayitlar GROUP BY proje ORDER BY proje')],
            'ekleyenler':[dict(r) for r in conn.execute("SELECT COALESCE(ekleyen_id,'') id,COALESCE(ekleyen_ad,'bilinmiyor') ad,COUNT(*) adet FROM kayitlar WHERE silindi=0 GROUP BY ekleyen_id,ekleyen_ad ORDER BY adet DESC LIMIT 50")],
            'oturum':conn.execute('SELECT COUNT(*) FROM tg_oturumlar').fetchone()[0],
            'inbox':[dict(r) for r in conn.execute('SELECT bot_id,durum,COUNT(*) adet FROM tg_gelen GROUP BY bot_id,durum')],
            'duraklatildi':db.ayar_al(conn,'bot_durdur','0')=='1'}


def kullanicilari_ara(conn,q='',durum='hepsi',sure='',limit=200):
    from datetime import timedelta
    where=['1=1'];p=[]
    if q:
        where.append('(id LIKE ? OR username LIKE ? OR first_name LIKE ?)');p.extend(['%'+q[:100]+'%']*3)
    if durum=='engelli':where.append('engelli=1')
    elif durum=='onayli':where.append('onayli=1 AND engelli=0')
    elif durum=='onaysiz':where.append('onayli=0 AND engelli=0')
    if sure:
        hours={'1saat':1,'2saat':2,'24saat':24,'7gun':168,'30gun':720}.get(sure)
        if not hours:raise ValueError('Geçersiz zaman filtresi.')
        where.append('last_seen>=?');p.append((datetime.now()-timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S'))
    return [dict(r) for r in conn.execute('SELECT * FROM tg_kullanicilar WHERE '+' AND '.join(where)+' ORDER BY last_seen DESC LIMIT ?',(*p,max(1,min(int(limit),1000))))]


def kullanici_durum(conn,tg_id):
    tg_id=_id(tg_id)
    r=conn.execute('SELECT * FROM tg_kullanicilar WHERE id=?',(tg_id,)).fetchone()
    if not r:raise ValueError('Telegram kullanıcısı bulunamadı.')
    d=dict(r);d['oturumlar']=[]
    for s in conn.execute('SELECT bot_id,veri,guncelleme FROM tg_oturumlar WHERE user_id=?',(tg_id,)):
        try:session=json.loads(s['veri'])
        except ValueError:session={}
        d['oturumlar'].append({'bot_id':s['bot_id'],'step':session.get('step'),'proje':session.get('project'),'guncelleme':s['guncelleme']})
    return d


def tam_sifirla(ayar,conn,tg_id,kim='panel'):
    tg_id=_id(tg_id)
    with db.transaction(conn):
        conn.execute('UPDATE tg_kullanicilar SET onayli=0,engelli=0,engel_sebep=NULL,deneme=0 WHERE id=?',(tg_id,))
        conn.execute('DELETE FROM tg_oturumlar WHERE user_id=?',(tg_id,))
        conn.execute('DELETE FROM tg_girisler WHERE user_id=?',(tg_id,))
        iid=_islem(conn,'tam_sifirla',kim,'Kullanıcı tam sıfırlandı: '+tg_id)
        _denetle(conn,kim,'bot_tam_sifirla',yeni=tg_id)
    return iid


def bot_kontrol(ayar,conn,duraklat,kim='panel'):
    with db.transaction(conn):
        db.ayar_yaz(conn,'bot_durdur','1' if duraklat else '0')
        iid=_islem(conn,'bot_duraklat' if duraklat else 'bot_surdur',kim,'Bot duraklatıldı' if duraklat else 'Bot sürdürülüyor')
        _denetle(conn,kim,'bot_kontrol',yeni='duraklat' if duraklat else 'surdur')
    return iid


def tekrar_dene(ayar,conn,update_id=None,kim='panel'):
    with db.transaction(conn):
        if update_id is not None:
            changed=conn.execute("UPDATE tg_gelen SET durum='bekliyor',deneme=0,hata=NULL,guncelleme=? WHERE update_id=? AND durum='olu'",(_simdi(),int(update_id))).rowcount
        else:
            changed=conn.execute("UPDATE tg_gelen SET durum='bekliyor',deneme=0,hata=NULL,guncelleme=? WHERE durum='olu'",(_simdi(),)).rowcount
        _islem(conn,'inbox_tekrar',kim,f'{changed} başarısız güncelleme tekrar kuyruğuna alındı')
        _denetle(conn,kim,'bot_inbox_tekrar',yeni=str(changed))
    return changed


def kategori_yayinla(ayar,conn,kim='panel'):
    with db.transaction(conn):
        _islem(conn,'kategori_yayinla',kim,'Kategoriler yeni seçimlerde anında geçerli')
        _denetle(conn,kim,'bot_kategori_yayinla')

"""Kayıt üzerinde görünen admin konuşması; alıcı yetkisi her olayda doğrulanır."""
from . import db,yetki

# 2.4.0: Telegram'dan gelen yanıtların yazar öneki ("Telegram: <ad>") ve soru alıcısı biçimi ("tg:<chat_id>").
TG_YAZAR='Telegram: '


def recipients(conn,project,exclude=''):
    result=[]
    for u in conn.execute('SELECT kullanici_adi,ad,yetki FROM panel_kullanicilari WHERE aktif=1 ORDER BY kullanici_adi'):
        role=yetki.coz(u['yetki'])
        if u['kullanici_adi']!=exclude and yetki.izin(role,project,'oku') and yetki.izin(role,project,'kt'):
            result.append({'kullanici_adi':u['kullanici_adi'],'ad':u['ad'] or u['kullanici_adi']})
    return result


def add(conn,kid,author,text,recipient='',parent_id=None):
    text=db.metin_temizle(text).strip();recipient=(recipient or '').strip()  # NUL/kontrol karakteri yorum metnine girmez
    if not text or len(text)>5000:raise ValueError('Yorum 1–5000 karakter olmalı.')
    record=conn.execute('SELECT * FROM kayitlar WHERE id=?',(kid,)).fetchone()
    sender=conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=? AND aktif=1',(author,)).fetchone()
    if not record or not sender or not yetki.izin(yetki.coz(sender['yetki']),record['proje'],'oku') or not yetki.izin(yetki.coz(sender['yetki']),record['proje'],'kt'):
        raise PermissionError('Bu kayıtta yorum yetkiniz yok.')
    valid={u['kullanici_adi'] for u in recipients(conn,record['proje'],author)}
    kind='soru' if recipient else 'yorum';pid=None
    if parent_id:
        try:pid=int(parent_id)
        except (TypeError,ValueError):raise ValueError('Yanıtın bağlı olduğu yorum geçersiz.')
        parent=conn.execute('SELECT * FROM yorumlar WHERE id=? AND kayit_id=?',(pid,kid)).fetchone()
        if not parent:raise ValueError('Yanıtın bağlı olduğu yorum bu kayıtta değil.')
        recipient=parent['kullanici'] if parent['kullanici']!=author else (parent['alici'] or '')
        # 2.4.0: Telegram'daki ekleyenle süren konuşmada yanıt yine Telegram'a gider.
        if str(parent['kullanici']).startswith(TG_YAZAR) or (parent['kullanici']==author and str(parent['alici'] or '').startswith('tg:')):
            from . import bot_bildirim
            # Telegram kapalıysa ya da hedef yoksa yanıt panelde kalır (konuşma kilitlenmez).
            if bot_bildirim.tg_hedef(record) and bot_bildirim.soru_acik():recipient='tg'
            else:recipient=parent['alici'] if str(parent['kullanici']).startswith(TG_YAZAR) and parent['alici'] in valid else ''
        kind='yanit'
    if recipient=='tg' or recipient.startswith('tg:'):return _telegrama_sor(conn,record,author,text,pid,kind)
    if recipient and recipient not in valid:raise ValueError('Alıcı aktif olmalı ve aynı projenin kontrol yetkisine sahip olmalı.')
    with db.transaction(conn):
        cid=conn.execute('INSERT INTO yorumlar(kayit_id,kullanici,metin,zaman,yanit_id,alici,tur) VALUES(?,?,?,?,?,?,?)',(kid,author,text,db.simdi(),pid,recipient or None,kind)).lastrowid
        targets=[recipient] if recipient else sorted(valid)
        for target in targets:db.mesaj_bildir(conn,kid,target,kind,author,text,'yorum:'+str(cid))
        db.denetim_yaz(conn,author,'soru_yonelt' if kind=='soru' else 'yanit_ekle' if kind=='yanit' else 'yorum_ekle',record['proje'],record['anahtar'],yeni=text)
        db.degisti(conn)
    return cid


def approval_notice(conn,record,author,value,version):
    text='Kanıt onaylandı.' if value else 'Kanıtın onayı kaldırıldı.'
    for recipient in recipients(conn,record['proje'],author):
        db.mesaj_bildir(conn,record['id'],recipient['kullanici_adi'],'onay',author,text,'onay:'+str(record['id'])+':'+str(version))


def _telegrama_sor(conn,record,author,text,pid,kind):
    """'Ekleyene sor (Telegram)': yorum alici='tg:<chat_id>' ile saklanır, bot kuyruğuna (bot_giden) yazılır."""
    from . import bot_bildirim
    hedef=bot_bildirim.tg_hedef(record)
    if not hedef:raise ValueError('Bu kaydı Telegram botuyla ekleyen biri yok; soruyu panel kullanıcısına yöneltin.')
    if not bot_bildirim.soru_acik():raise ValueError('Telegram üzerinden soru gönderimi kapalı (BOT_SORU_BILDIRIMI=0).')
    if len(text)>3000:raise ValueError('Telegram sorusu en çok 3000 karakter olabilir.')
    with db.transaction(conn):
        cid=conn.execute('INSERT INTO yorumlar(kayit_id,kullanici,metin,zaman,yanit_id,alici,tur) VALUES(?,?,?,?,?,?,?)',(record['id'],author,text,db.simdi(),pid,'tg:'+hedef[0],kind)).lastrowid
        bot_bildirim.soru_kuyruga(conn,record,cid,text)
        db.denetim_yaz(conn,author,'soru_yonelt' if kind=='soru' else 'yanit_ekle',record['proje'],record['anahtar'],yeni=text,aciklama='Telegram ile ekleyene iletildi.')
        db.degisti(conn)
    return cid


def telegram_yanit(conn,soru_id,ad,text):
    """Ekleyenin Telegram yanıtı: soruya bağlı 'yanit' yorumu (yazar 'Telegram: <ad>'), soran lidere bildirim.
    Çağıran (bot) transaction'ı açıktır; dönüş (yorum_id, kayit_id)."""
    text=db.metin_temizle(text).strip()
    if not text or len(text)>3000:raise ValueError('Yanıt 1–3000 karakter olmalı.')
    soru=conn.execute('SELECT * FROM yorumlar WHERE id=?',(int(soru_id),)).fetchone()
    if not soru:raise ValueError('Yanıtlanan soru bulunamadı.')
    record=conn.execute('SELECT * FROM kayitlar WHERE id=?',(soru['kayit_id'],)).fetchone()
    if not record:raise ValueError('Kayıt bulunamadı.')
    yazar=(TG_YAZAR+(db.metin_temizle(ad,80).strip() or 'ekleyen'))[:120]
    lider=soru['kullanici'] if not str(soru['kullanici']).startswith(TG_YAZAR) else (soru['alici'] or '')
    with db.transaction(conn):
        cid=conn.execute('INSERT INTO yorumlar(kayit_id,kullanici,metin,zaman,yanit_id,alici,tur) VALUES(?,?,?,?,?,?,?)',(record['id'],yazar,text,db.simdi(),soru['id'],lider or None,'yanit')).lastrowid
        if lider:db.mesaj_bildir(conn,record['id'],lider,'yanit',yazar,text,'yorum:'+str(cid))
        db.denetim_yaz(conn,yazar,'yanit_ekle',record['proje'],record['anahtar'],yeni=text,aciklama='Telegram yanıtı.')
        db.degisti(conn)
    return cid,int(record['id'])

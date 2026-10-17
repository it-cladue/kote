"""Kayıt üzerinde görünen admin konuşması; alıcı yetkisi her olayda doğrulanır."""
from . import db,yetki


def recipients(conn,project,exclude=''):
    result=[]
    for u in conn.execute('SELECT kullanici_adi,ad,yetki FROM panel_kullanicilari WHERE aktif=1 ORDER BY kullanici_adi'):
        role=yetki.coz(u['yetki'])
        if u['kullanici_adi']!=exclude and yetki.izin(role,project,'oku') and yetki.izin(role,project,'kt'):
            result.append({'kullanici_adi':u['kullanici_adi'],'ad':u['ad'] or u['kullanici_adi']})
    return result


def add(conn,kid,author,text,recipient='',parent_id=None):
    text=(text or '').strip();recipient=(recipient or '').strip()
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
        kind='yanit'
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

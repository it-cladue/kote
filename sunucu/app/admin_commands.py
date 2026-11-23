"""Eski admin komutlarının yeni DB tabanlı karşılıkları; site aynı servisleri kullanır."""
import html
import re
from . import db,bot_yonetim as service

# Hedef Telegram kimliği: yalnız rakam, 5-15 hane. Serbest metin tg_kullanicilar'a yazılmaz.
_TG_ID=re.compile(r'[1-9][0-9]{4,14}')
# Uzun listeler Telegram'ın 4096 sınırını aşmasın; bot._say zaten HTML güvenli böler.
SON_KULLANICI_SINIRI=100
SON_HATA_SATIRI=25
SON_HATA_SATIR_UZUNLUGU=300


def _hedef_id(value,ornek):
    value=str(value or '').strip()
    if not _TG_ID.fullmatch(value):raise ValueError(f'Telegram ID yalnız rakamlardan oluşmalı (5-15 hane). Örnek: {ornek}')
    return value


def _sayi(value,varsayilan,alt,ust,kullanim):
    value=str(value or '').strip()
    if not value:return varsayilan
    if not value.isdigit():raise ValueError(kullanim)
    return max(alt,min(int(value),ust))

HELP = '''<b>ADMIN KOMUTLARI</b>
/durum /istatistik /kayit_raporu
/son_kullanicilar [adet] [1saat|2saat|24saat|7gun|30gun]
/kullanici_ara kelime /kullanici_durum ID /engelliler
/engelle ID sebep /engel_kaldir ID /engel_kaldir_sifirla ID
/onayli_sil ID /oturumlar /oturum_temizle ID
/kategori_liste /kategori_bilgi KOD /kategori_akislari
Kategori/proje ve soru değişiklikleri yalnız web süperadmin panelindedir.
/yedekle /bakim_ac /bakim_kapat /son_hatalar
/kapat (kalıcı duraklat) /bot_surdur /admin_cikis
Excel yazma modu/satır komutları emekli; sitede ayrı Excel Kontrol vardır.'''

COMMANDS={'/yardim_admin','/istatistik','/son_kullanicilar','/kullanici_ara','/engelle','/engel_kaldir','/engel_kaldir_sifirla','/engelliler','/oturum_temizle','/kullanici_durum','/onayli_sil','/kategori_bilgi','/kategori_akislari','/kategori_ekle','/kategori_sil','/kategori_yayinla','/excel_son_satir','/excel_mod','/kayit_raporu','/yedekle','/son_hatalar','/kapat','/bot_surdur','/onayla','/vazgec'}
FLOWS={'tek_uye':'Personel + Üye ID','ark_ana':'Personel + Arkadaş Üye ID + Ana Üye ID','ana_only':'Personel + Ana Üye ID','sessiz_tip':'Personel + Üye ID + Sessiz/Telesekreter'}

def esc(x):return html.escape(str(x or ''))

def process(bot,conn,chat_id,user,text,session):
    cmd,_,arg=text.partition(' ');cmd=cmd.lower();arg=arg.strip()
    if cmd not in COMMANDS:return False
    uid=str(user['id'])
    if not bot._is_allowed_admin(uid) or not bot._admin_active(session):
        bot._say(chat_id,'Bu komut için önce /admin ile giriş yapın.');return True
    try:
        if cmd=='/yardim_admin':bot._say(chat_id,HELP)
        elif cmd=='/istatistik':
            r=service.istatistik(conn);u=r['kullanicilar'];bot._say(chat_id,f"<b>İSTATİSTİK</b>\nKullanıcı: {u['toplam']}\nOnaylı: {u['onayli']}\nEngelli: {u['engelli']}\nOturum: {r['oturum']}\nKayıt: {sum(x['toplam'] for x in r['projeler'])}")
        elif cmd=='/kayit_raporu':
            n=_sayi(arg,10,1,50,'Kullanım: /kayit_raporu [adet 1-50]');rows=service.istatistik(conn)['ekleyenler'][:n];bot._say(chat_id,'<b>KAYIT RAPORU</b>\n'+'\n'.join(f"{esc(x['ad'])} ({esc(x['id'])}): {x['adet']}" for x in rows))
        elif cmd in ('/son_kullanicilar','/kullanici_ara','/engelliler'):
            args=arg.split()
            limit=_sayi(args[0],30,1,SON_KULLANICI_SINIRI,f'Kullanım: /son_kullanicilar [adet 1-{SON_KULLANICI_SINIRI}] [1saat|2saat|24saat|7gun|30gun]') if args and cmd=='/son_kullanicilar' else min(30,SON_KULLANICI_SINIRI)
            sure=args[1] if len(args)>1 and cmd=='/son_kullanicilar' else ''
            rows=service.kullanicilari_ara(conn,q=arg if cmd=='/kullanici_ara' else '',durum='engelli' if cmd=='/engelliler' else 'hepsi',sure=sure,limit=limit if cmd=='/son_kullanicilar' else 30)
            bot._say(chat_id,'<b>KULLANICILAR</b>\n'+('\n'.join(f"{esc(x['id'])} {esc(x['username'] or x['first_name'])} · {esc(x['last_seen'])}" for x in rows) or 'Kayıt yok.'))
        elif cmd=='/kullanici_durum':
            d=service.kullanici_durum(conn,_hedef_id(arg,'/kullanici_durum 123456789'));bot._say(chat_id,f"<b>KULLANICI DURUMU</b>\nID: {esc(d['id'])}\nOnaylı: {d['onayli']}\nEngelli: {d['engelli']}\nDeneme: {d['deneme']}\nOturum: {len(d['oturumlar'])}")
        elif cmd in ('/engelle','/kapat'):
            if cmd=='/engelle':
                target,_,reason=arg.partition(' ')
                if not target:raise ValueError('Kullanım: /engelle ID sebep')
                target=_hedef_id(target,'/engelle 123456789 sebep')
                if target==uid:raise ValueError('Kendi hesabınızı engelleyemezsiniz.')
                pending={'type':'engelle','id':target,'reason':reason.strip()[:300] or 'Yönetici engeli'}
            else:pending={'type':'kapat'}
            session=session or {'step':'idle'};session['admin_confirm']=pending;bot._save_session(conn,uid,session)
            bot._say(chat_id,'İşlem için onay gerekli. /onayla ile uygula, /vazgec ile iptal et.')
        elif cmd in ('/onayla','/vazgec'):
            pending=(session or {}).pop('admin_confirm',None)
            if not pending:raise ValueError('Bekleyen onay yok.')
            bot._save_session(conn,uid,session)
            if cmd=='/onayla':
                if pending['type']=='kapat':service.bot_kontrol(bot.ayar,conn,True,uid)
                else:service.engelle(bot.ayar,conn,pending['id'],'',pending['reason'],uid)
            bot._say(chat_id,'İşlem uygulandı.' if cmd=='/onayla' else 'İptal edildi.')
        elif cmd=='/bot_surdur':service.bot_kontrol(bot.ayar,conn,False,uid);bot._say(chat_id,'Bot sürdürülüyor. Duraklatılmış polling varsa siteden sürdür düğmesini kullanın.')
        elif cmd=='/engel_kaldir':service.engel_kaldir(bot.ayar,conn,_hedef_id(arg,'/engel_kaldir 123456789'),uid);bot._say(chat_id,'Engel, deneme ve oturum temizlendi; mevcut onay korundu.')
        elif cmd=='/engel_kaldir_sifirla':service.tam_sifirla(bot.ayar,conn,_hedef_id(arg,'/engel_kaldir_sifirla 123456789'),uid);bot._say(chat_id,'Kullanıcı tam sıfırlandı.')
        elif cmd=='/onayli_sil':service.onay_kaldir(bot.ayar,conn,_hedef_id(arg,'/onayli_sil 123456789'),uid);bot._say(chat_id,'Onay, deneme ve oturum temizlendi.')
        elif cmd=='/oturum_temizle':service.oturum_temizle(bot.ayar,conn,_hedef_id(arg,'/oturum_temizle 123456789') if arg else None,uid);bot._say(chat_id,'Oturum temizlendi.' if arg else 'Tüm oturumlar temizlendi.')
        elif cmd=='/kategori_akislari':bot._say(chat_id,'<b>KATEGORİ AKIŞLARI</b>\n'+'\n'.join(f'{esc(k)}: {esc(v)}' for k,v in FLOWS.items()))
        elif cmd=='/kategori_bilgi':
            r=conn.execute('SELECT code,label,mode,aktif FROM kategoriler WHERE code=?',(arg.lower(),)).fetchone()
            if not r:raise ValueError('Kategori bulunamadı.')
            bot._say(chat_id,f"{esc(r['label'])}: {esc(FLOWS[r['mode']])} · aktif: {r['aktif']}")
        elif cmd in ('/kategori_ekle','/kategori_sil','/kategori_yayinla'):
            # Telegram'da eski mutasyon komutları kalan bot oturumlarını ve
            # katalog revision kontrolünü atlayabiliyordu. Web süperadmin ekranı
            # expected_revision + proje üyeliği doğrulamasının tek sahibidir.
            bot._say(chat_id,'Kategori ve proje değişiklikleri için Panelde Proje ve kategoriler bölümünü kullanın.')
        elif cmd in ('/excel_son_satir','/excel_mod'):bot._say(chat_id,'Canlı Excel kaldırıldı. Kanıtlar DB’ye yazılır; sitedeki Excel Kontrol dosya karşılaştırması içindir.')
        elif cmd=='/yedekle':
            service.yedek_al(bot.ayar,conn,uid);bot._say(chat_id,'DB yedeği alındı. Görseller ayrıca yedeklenmeli.')
        elif cmd=='/son_hatalar':
            lines=[s[:SON_HATA_SATIR_UZUNLUGU] for s in service.son_log(bot.ayar,SON_HATA_SATIRI,True)]
            bot._say(chat_id,'<b>SON HATALAR</b>\n'+esc('\n'.join(lines) or 'Hata yok.'))
    except (ValueError,OSError) as e:bot._say(chat_id,'Hata: '+esc(e))
    return True

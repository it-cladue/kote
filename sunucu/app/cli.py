"""Sunucu işletim komutları. python -m app.cli --help"""
import argparse
import getpass
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from . import db, kullanicilar
from .settings import AYAR, ROOT

class _TurkceParser(argparse.ArgumentParser):
    """argparse'ın İngilizce metinlerini Türkçeleştirir."""
    def __init__(self,*a,**k):
        k.setdefault('add_help',False)
        super().__init__(*a,**k)
        self.add_argument('-h','--help',action='help',help='Bu yardımı göster ve çık')
        self._positionals.title='Zorunlu değerler'; self._optionals.title='Seçenekler'
    def error(self,message):
        if 'invalid choice' in message:
            secim=message.split("'")[1] if "'" in message else ''
            message="bilinmeyen komut '"+secim+"'. Komutlar: "+', '.join(self._subparsers._group_actions[0].choices.keys()) if self._subparsers else message
        elif 'required' in message: message='eksik değer: '+message.split(':')[-1].strip()
        self.print_usage(sys.stderr); raise SystemExit('Hata: '+message+" ('--help' ile kullanım bilgisi)")

def _alt(sub,ad,aciklama):
    return sub.add_parser(ad,help=aciklama,description=aciklama)

def main():
    parser=_TurkceParser(prog='python -m app.cli',description='Kanıt Paneli sunucu araçları',epilog='Örnek: KANIT_PW=GucluParola1 python -m app.cli sifre-sifirla admin --password-env KANIT_PW --kalici')
    sub=parser.add_subparsers(dest='command',required=True,title='Komutlar',metavar='KOMUT')
    admin=_alt(sub,'admin-ekle','İlk veya ek panel hesabını oluştur')
    admin.add_argument('ad',nargs='?',default='admin',help='Kullanıcı adı (varsayılan: admin)'); admin.add_argument('--yetki',default='admin',help="Yetki: admin (süperadmin) veya 'OF:oku,kt' gibi proje kapsamı")
    reset=_alt(sub,'sifre-sifirla','Mevcut hesabın parolasını sıfırla ve hesabı aktif et');reset.add_argument('ad',help='Kullanıcı adı')
    for command in (admin,reset):
        command.add_argument('--password-env',metavar='DEGISKEN',help='Parolanın okunacağı ortam değişkeninin adı; parolayı komut satırına yazmayın')
        command.add_argument('--kalici',action='store_true',help='Parola kalıcıdır; ilk girişte değiştirme zorunluluğu konmaz')
    old=_alt(sub,'ice-aktar','Eski klasörü/Exceli bir kez aktar; canlı Excel bağlantısı kurmaz')
    old.add_argument('kaynak',help='Eski Excel dosyası veya bot klasörü yolu')
    _alt(sub,'arsiv-tara','Sunucuya taşınmış telegram_gorseller klasörünü indeksle')
    topla=_alt(sub,'gyazo-onbellekle','Kayıtlardaki Gyazo/Snappark/Teamzone görsellerini sunucuya bir kez indir; açılamayanları raporla (yeniden çalıştırılabilir)')
    topla.add_argument('--en-cok',type=int,default=0,metavar='N',help='Yalnız ilk N bağlantıyı dene (deneme için)')
    topla.add_argument('--bekleme',type=float,default=0.15,metavar='SN',help='İki indirme arasındaki bekleme, saniye (varsayılan 0.15)')
    topla.add_argument('--rapor',metavar='DOSYA',help='Açılamayan bağlantı listesi; varsayılan veri klasöründe gyazo-acilamayan.csv')
    topla.add_argument('--yeni-en-cok',type=int,default=0,metavar='N',help='Bu çalıştırmada en çok N yeni indirme (gece planı); kalanı sonraki çalıştırmaya')
    topla.add_argument('--pencere',metavar='BAS-BIT',help='Yalnız bu saat aralığında çalış ve bitişte dur, örn. 22:30-07:30 (gece yarısını aşabilir)')
    topla.add_argument('--saat-dilimi',default='Europe/Istanbul',metavar='BOLGE',help='--pencere için saat dilimi (varsayılan Europe/Istanbul)')
    topla.add_argument('--ayrintili',action='store_true',help='Her bağlantı için satır yaz (--en-cok 100 ve altında kendiliğinden açık)')
    topla.add_argument('--on-kontrol-atla',action='store_true',help='Başlangıçtaki Gyazo erişim denemesini atla')
    backup=_alt(sub,'yedekle','Tutarlı SQLite yedeği ve isteğe bağlı görsel kopyası')
    backup.add_argument('hedef',help='Yedeklerin yazılacağı klasör (altına tarihli klasör açılır)');backup.add_argument('--gorseller',action='store_true',help='Görsel ve arşiv klasörlerini de kopyala')
    hat=_alt(sub,'hatirlatma-uret','Onay bekleyen kayıtlar için hatırlatma bildirimlerini hemen üret (JSON rapor). Günlük kullanıcı sınırı ve günde bir kuralı nedeniyle aynı gün tekrar çalıştırmak yeni satır eklemez')
    hat.add_argument('--tarih',metavar='YYYY-AA-GG',help='3 gün kuralını bugün yerine bu (geçmiş) güne göre üret; ileri tarih kabul edilmez (gerçek günleri susturur). 2 saat ve gün sonu adımları her zaman şimdiki saate göre çalışır')
    hat.add_argument('--gun-sonu-zorla',action='store_true',help='Bugünün gün sonu özetini 18:00 beklenmeden hemen üret (sunucuda deneme için; yine günde bir kez)')
    hat.add_argument('--bekleyen-ozet-zorla',action='store_true',help='Şu anki dilimin bekleyen özetini ("Onay bekleyen N kayıt var") pencere dışında da hemen üret (sunucuda deneme için; yine dilim başına bir kez)')
    kat=_alt(sub,'kategori-temizle','Kayıtlardaki kategori yazımlarını listele ve katalog adlarında birleştir (2.3.5). Çıkış kodu: 0 başarı (değişiklik olmasa da), 1 hata (hiçbir şey yazılmaz)')
    kat.add_argument('--listele',action='store_true',help='Kayıtlardaki bütün kategori değerlerini grupla ve say (yazmaz)')
    kat.add_argument('--donustur',action='append',default=[],metavar='"ESKI=YENI"',help='ESKI değerini (harf duyarsız, baş/son boşluksuz) YENI katalog kategorisine (kod ya da görünen ad) çevir; (boş) yapmak için YENI yerine (boş). Birden çok kez verilebilir')
    kat.add_argument('--onizle',action='store_true',help='Yalnız kaç kaydın değişeceğini göster, hiçbir şey yazma')
    kat.add_argument('--kim',default='sunucu-cli',metavar='AD',help='İşlem Geçmişi\'ne yazılacak kullanıcı adı (varsayılan sunucu-cli)')
    _alt(sub,'durum','Kayıt sayısı, dosya yolları ve bot gelen kutusu özeti');_alt(sub,'veritabani-kur','Veritabanı dosyasını ve şemayı oluştur')
    args=parser.parse_args()
    if args.command in ('admin-ekle','sifre-sifirla'):
        env=getattr(args,'password_env',None)
        if env and not os.getenv(env,''): raise SystemExit('Ortam değişkeni boş: '+env)
        if env: password=os.getenv(env,'')
        else:
            if not sys.stdin.isatty(): raise SystemExit('Parola sorulamıyor (terminal yok). Parolayı ortam değişkeniyle verin: KANIT_PW=... python -m app.cli '+args.command+' '+args.ad+' --password-env KANIT_PW')
            try:
                password=getpass.getpass('En az 8 karakter parola: ')
                if password!=getpass.getpass('Parola tekrar: '): raise SystemExit('Parolalar aynı değil.')
            except (EOFError,KeyboardInterrupt): raise SystemExit('\nParola girişi iptal edildi.')
        try:
            if args.command=='admin-ekle':
                # admin-ekle ile verilen parola sunucu operatörüne aittir; kalıcıdır.
                kullanicilar.ekle(AYAR,args.ad,args.yetki,password,olusturan='sunucu-cli')
                kullanicilar.guncelle(AYAR,args.ad,sifre_degistir=0)
            else:
                kullanicilar.guncelle(AYAR,args.ad,sifre=password,sifre_degistir=0 if args.kalici else 1,aktif=1,islem_yapan='sunucu-cli')
        except ValueError as e: raise SystemExit('Hata: '+str(e))
        print('Panel hesabı hazır:',args.ad,'(parola kalıcı)' if args.kalici or args.command=='admin-ekle' else '(ilk girişte parola değiştirilecek)');return
    c=db.baglan(AYAR['DB'])
    try:
        if args.command=='ice-aktar':
            from . import ice_aktar,gorsel
            report=ice_aktar.calistir(AYAR,c,AYAR['ONBELLEK'],gorsel.GorselCozucu(AYAR,AYAR['ONBELLEK']),kaynak=args.kaynak)
            print(json.dumps(report,ensure_ascii=False,indent=2))
            if report.get('hata'): raise SystemExit(1)
        elif args.command=='gyazo-onbellekle':
            from . import gorsel
            def ilerleme(i,n,s): print(f"{i}/{n} · indirilen {s['indirilen']} · zaten var {s['zaten_var']} · açılamayan {s['acilamayan']}",flush=True)
            def log(metin): print(metin,flush=True)
            bitis=None
            if args.pencere:
                try: icinde,bitis,aciklama=gorsel.gyazo_pencere(args.pencere,args.saat_dilimi)
                except ValueError as e: raise SystemExit('Hata: '+str(e))
                if not icinde:
                    print('GYAZO_ONBELLEK_PENCERE_DISI: '+aciklama+' ('+args.saat_dilimi+'); hiçbir şey yapılmadı.');return
                print('Pencere: '+aciklama+'; bitiş '+bitis.strftime('%H:%M')+' ('+args.saat_dilimi+')',flush=True)
            ayrintili=args.ayrintili or (0<args.en_cok<=100)
            try:
                r=gorsel.gyazo_toplu_indir(c,gorsel.GorselCozucu(AYAR,AYAR['ONBELLEK']),AYAR,en_cok=args.en_cok,yeni_en_cok=args.yeni_en_cok,bitis=bitis,
                                           bekleme_sn=args.bekleme,rapor_yolu=args.rapor,ilerleme=ilerleme,log=log if ayrintili else (lambda m: print(m,flush=True) if ('bekleniyor' in m or 'ulaşılamıyor' in m or 'sınırı' in m or 'Bitiş' in m or 'Gyazo erişimi:' in m or 'taranıyor' in m or 'muhtemelen' in m or 'bir kez daha denenmeden' in m or 'ulaşılamadı; kalan' in m) else None),
                                           on_kontrol=not args.on_kontrol_atla)
            except ValueError as e: raise SystemExit('Hata: '+str(e))
            print(json.dumps(r,ensure_ascii=False,indent=2))
            turler=r.get('turler') or {}
            if turler:
                print('Türler: '+' · '.join(f"{ad} {t.get('baglanti',0)} bağlantı (indirilen {t.get('indirilen',0)}, zaten var {t.get('zaten_var',0)}, açılamayan {t.get('acilamayan',0)}"+(f", tanınmayan {t['taninmayan']}" if t.get('taninmayan') else '')+')' for ad,t in (('Gyazo',turler.get('gyazo',{})),('Snappark',turler.get('snappark',{})),('Teamzone',turler.get('teamzone',{})))),flush=True)
            if r.get('ariza'):
                denenmedi=r.get('ariza_denenmedi') or {}
                parcalar=[]
                for servis in r['ariza']:
                    d=int(denenmedi.get(servis,0) or 0);acil=max(0,int((turler.get(str(servis).lower()) or {}).get('acilamayan',0) or 0)-d)
                    parcalar.append(f"{servis} yanıt vermiyor (muhtemelen {servis} arızası); {acil} bağlantı açılamadı"+(f", {d} bağlantı denenmedi" if d else ''))
                print('ARIZA: '+' · '.join(parcalar)+'. Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir.',flush=True)
            neden=r.get('bitis_nedeni','tamam')
            if neden=='tamam': print('GYAZO_ONBELLEK_TAMAM')
            elif neden in ('sinir','sure'): print(f"GYAZO_ONBELLEK_DEVAM: kalan {r.get('kalan',0)} bağlantı sonraki çalıştırmada sürer.")
            elif neden=='erisim': print('GYAZO_ONBELLEK_YARIM: '+str(r.get('durduruldu') or ''));raise SystemExit(1)
            else: print('GYAZO_ONBELLEK_YARIM: '+str(r.get('durduruldu') or ''))
        elif args.command=='arsiv-tara':
            from . import gorsel
            print(json.dumps(gorsel.arsiv_tara(AYAR,c,gorsel.GorselCozucu(AYAR,AYAR['ONBELLEK'])),ensure_ascii=False,indent=2))
        elif args.command=='yedekle':
            target=Path(args.hedef).resolve()/datetime.now().strftime('%Y%m%d-%H%M%S-%f');target.mkdir(parents=True,exist_ok=False)
            dest=sqlite3.connect(target/'panel.db');c.backup(dest);dest.close()
            if args.gorseller:
                for name,key in [('gorseller','GORSEL_KLASOR'),('telegram_gorseller','ARSIV_KLASOR')]:
                    source=Path(AYAR[key]).resolve()
                    if target.is_relative_to(source): raise SystemExit('Yedek hedefi görsel klasörü içinde olamaz.')
                    if source.exists(): shutil.copytree(source,target/name)
            (target/'YEDEK_NOTU.txt').write_text('Veritabanı SQLite backup API ile alınmıştır. Dosya yollarını koruyarak geri yükleyin. Tam medya tutarlılığı için bot+web kapalıyken --gorseller ile alın. .env/anahtarlar ayrıca özel olarak yedeklenmelidir.\n')
            print('Yedek oluşturuldu:',target)
        elif args.command=='durum':
            print('Kayıt:',c.execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0]);print('DB:',AYAR['DB'])
            print('Görseller:',AYAR['GORSEL_KLASOR']);print('Arşiv:',AYAR['ARSIV_KLASOR'])
            print('Gelen kutusu:',[dict(r) for r in c.execute('SELECT bot_id,durum,COUNT(*) adet FROM tg_gelen GROUP BY bot_id,durum')])
            try:
                from . import gorsel
                d=gorsel.onbellek_durumu(AYAR)
                print('Görsel önbelleği:',f"{d.get('toplam_mb',0)} MB toplam;"," ".join(f"{ad}: {v.get('dosya',0)} dosya / {v.get('mb',0)} MB (sınır {v.get('sinir_mb',0) or 'yok'} MB)" for ad,v in d.items() if isinstance(v,dict) and 'dosya' in v))
            except Exception as hata:
                print('Görsel önbelleği: okunamadı:',hata)
        elif args.command=='hatirlatma-uret':
            from . import hatirlatma
            bugun=None
            if args.tarih:
                try: bugun=datetime.strptime(args.tarih,'%Y-%m-%d').date()
                except ValueError: raise SystemExit('Hata: tarih YYYY-AA-GG biçiminde olmalı.')
                if bugun>datetime.now().date(): raise SystemExit('Hata: --tarih bugünden ileri olamaz; ileri tarihli hatırlatma gerçek günleri susturur.')
            rapor=hatirlatma.uret(c,AYAR,bugun=bugun,gun_sonu_zorla=args.gun_sonu_zorla,bekleyen_ozet_zorla=args.bekleyen_ozet_zorla)
            print(json.dumps(rapor,ensure_ascii=False,indent=2))
            # Kısa Türkçe özet stderr'e: stdout saf JSON kalır (betikler okuyabilsin).
            print(hatirlatma.rapor_metni(rapor),file=sys.stderr)
        elif args.command=='kategori-temizle': _kategori_temizle(c,args)
        elif args.command=='veritabani-kur': print('Veritabanı hazır:',AYAR['DB'])
    finally:c.close()

def _kategori_temizle(c,args):
    """stdout: JSON (betikler okuyabilsin); stderr: kısa Türkçe özet/tablo. Hata: 'Hata: …' ve çıkış kodu 1."""
    from . import kategori_temizlik as kt
    if not args.listele and not args.donustur: raise SystemExit("Hata: --listele ya da en az bir --donustur \"ESKI=YENI\" verin ('--help' ile kullanım bilgisi)")
    if args.listele and args.donustur: raise SystemExit('Hata: --listele ile --donustur birlikte kullanılamaz.')
    if args.listele:
        gruplar=kt.gruplar(c)
        print(json.dumps(dict(gruplar=gruplar,hedefler=kt.hedefler(c)),ensure_ascii=False,indent=2))
        print(kt.tablo_metni(gruplar),file=sys.stderr)
        print('%d farklı değer, %d kayıt. Etkin katalog kategorileri: %s' % (len(gruplar),sum(g['hepsi'] for g in gruplar),', '.join(h['label'] for h in kt.hedefler(c)) or '—'),file=sys.stderr)
        return
    ciftler=[]
    for d in args.donustur:
        if '=' not in d: raise SystemExit('Hata: --donustur "ESKI=YENI" biçiminde olmalı: '+d)
        eski,yeni=d.rsplit('=',1)
        if not eski.strip(): raise SystemExit('Hata: eski değer boş ('+d+'). Boş kategorideki kayıtları dönüştürmek için ESKI yerine (boş) yazın.')
        if not yeni.strip(): raise SystemExit('Hata: hedef boş ('+d+'). Kategoriyi boşaltmak için YENI yerine (boş) yazın.')
        ciftler.append((eski,yeni.strip()))
    try:
        donusum=kt.donusum_coz(ciftler)
        sonuc=kt.plan(c,donusum) if args.onizle else kt.uygula(c,donusum,args.kim)
    except ValueError as e: raise SystemExit('Hata: '+str(e))
    print(json.dumps(dict(kt.disa(sonuc),onizleme=bool(args.onizle)),ensure_ascii=False,indent=2))
    for k in sonuc['kalemler']:
        print('  %s → %s: %d kayıt %s (%d silinmiş)' % (k['gorunen'] or kt.BOS_AD,k['hedef_gorunen'],k['degisecek'],'değişecek' if args.onizle else 'değişti',k['degisecek_silinen']),file=sys.stderr)
    if args.onizle: print('ÖNİZLEME: toplam %d kayıt değişecek; hiçbir şey yazılmadı. Uygulamak için aynı komutu --onizle olmadan çalıştırın.' % sonuc['toplam_degisecek'],file=sys.stderr)
    else: print('UYGULANDI: %d kayıt güncellendi; İşlem Geçmişi\'ne %d satır yazıldı.' % (sonuc['uygulanan'],sum(1 for k in sonuc['kalemler'] if k['degisecek'])),file=sys.stderr)

if __name__=='__main__':main()

"""Sunucu işletim komutları. python -m app.cli --help"""
import argparse
import getpass
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from . import db, kullanicilar
from .settings import AYAR, ROOT

def main():
    parser=argparse.ArgumentParser(description='Kanıt Paneli sunucu araçları')
    sub=parser.add_subparsers(dest='command',required=True)
    admin=sub.add_parser('admin-ekle',help='İlk veya ek panel hesabını oluştur')
    admin.add_argument('ad',nargs='?',default='admin'); admin.add_argument('--yetki',default='admin')
    reset=sub.add_parser('sifre-sifirla',help='Mevcut hesabın parolasını sıfırla ve hesabı aktif et');reset.add_argument('ad')
    for command in (admin,reset):
        command.add_argument('--password-env',help='Parolanın mevcut ortam değişkeni adı; değeri komut satırına yazmayın')
        command.add_argument('--kalici',action='store_true',help='Parola kalıcıdır; ilk girişte değiştirme zorunluluğu konmaz')
    old=sub.add_parser('ice-aktar',help='Eski klasörü/Exceli bir kez aktar; canlı Excel bağlantısı kurmaz')
    old.add_argument('kaynak')
    sub.add_parser('arsiv-tara',help='Sunucuya taşınmış telegram_gorseller klasörünü indeksle')
    backup=sub.add_parser('yedekle',help='Tutarlı SQLite yedeği ve isteğe bağlı görsel kopyası')
    backup.add_argument('hedef');backup.add_argument('--gorseller',action='store_true')
    sub.add_parser('durum');sub.add_parser('veritabani-kur')
    args=parser.parse_args()
    if args.command in ('admin-ekle','sifre-sifirla'):
        env=getattr(args,'password_env',None)
        if env and not os.getenv(env,''): raise SystemExit('Ortam değişkeni boş: '+env)
        password=os.getenv(env,'') if env else getpass.getpass('En az 8 karakter parola: ')
        if not env and password!=getpass.getpass('Parola tekrar: '): raise SystemExit('Parolalar aynı değil.')
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
        elif args.command=='veritabani-kur': print('Veritabanı hazır:',AYAR['DB'])
    finally:c.close()

if __name__=='__main__':main()

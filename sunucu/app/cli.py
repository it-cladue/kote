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
    admin.add_argument('ad',nargs='?',default='admin',help='Kullanıcı adı (varsayılan: admin)'); admin.add_argument('--yetki',default='admin',help="Yetki: admin, superadmin veya 'OF:oku,kt' gibi proje kapsamı")
    reset=_alt(sub,'sifre-sifirla','Mevcut hesabın parolasını sıfırla ve hesabı aktif et');reset.add_argument('ad',help='Kullanıcı adı')
    for command in (admin,reset):
        command.add_argument('--password-env',metavar='DEGISKEN',help='Parolanın okunacağı ortam değişkeninin adı; parolayı komut satırına yazmayın')
        command.add_argument('--kalici',action='store_true',help='Parola kalıcıdır; ilk girişte değiştirme zorunluluğu konmaz')
    old=_alt(sub,'ice-aktar','Eski klasörü/Exceli bir kez aktar; canlı Excel bağlantısı kurmaz')
    old.add_argument('kaynak',help='Eski Excel dosyası veya bot klasörü yolu')
    _alt(sub,'arsiv-tara','Sunucuya taşınmış telegram_gorseller klasörünü indeksle')
    backup=_alt(sub,'yedekle','Tutarlı SQLite yedeği ve isteğe bağlı görsel kopyası')
    backup.add_argument('hedef',help='Yedeklerin yazılacağı klasör (altına tarihli klasör açılır)');backup.add_argument('--gorseller',action='store_true',help='Görsel ve arşiv klasörlerini de kopyala')
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

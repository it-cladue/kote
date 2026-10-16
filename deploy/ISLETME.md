KANIT MERKEZI - SUNUCU KURULUMU VE ISLETME (Ubuntu 24.04 + Plesk)
=====================================================================

Bu belge, Windows'ta calisan Telegram botu (telebot.ps1) + Excel + OneDrive paneli duzeninin
yerine gecen SUNUCU surumunun kurulumunu ve gunluk isletmesini anlatir. Yonetici (root SSH'i
olan kisi) icindir. Komutlar sunucuda root ile yazilir; panel kullanicilarinin bunlarla isi yoktur.

Kisa ozet:
- Tek sunucu, tek veritabani (SQLite, /opt/kanit/veri/kanit.db). Excel artik veri degil, RAPORDUR
  (panelden "Cikti" ya da 'python -m kanit disa-aktar' ile uretilir).
- Iki servis: kanit-web (panel, port 8080) ve kanit-bot (Telegram botu). Ikisi de ayni veritabanini
  kullanir; panelde yapilan onay aninda botta, bottan gelen kayit aninda panelde gorunur.
  Kuyruk, OneDrive, "Excel'e yaziliyor..." bekleme yoktur.
- Gorseller sunucuda /opt/kanit/veri/gorseller/<PROJE>/ altinda durur; panel ve Excel ciktisi
  oradan link verir.
- Her gece 03:15 yedek alinir (veritabani + gorseller), 30 gun saklanir; istenirse disariya da kopyalanir.


0) NE NEREDE CALISIR
--------------------
  /opt/kanit/src/                 kaynak kod (git clone ya da kopya). Uygulama: src/kanit/, betikler: src/deploy/
  /opt/kanit/venv/                Python 3.12 sanal ortami (python3.12 + flask, waitress, openpyxl, pillow, requests)
  /opt/kanit/veri/                TUM VERI (sahibi kanit kullanicisi, 0750):
      kanit.db                    veritabani (WAL modu; yaninda kanit.db-wal / -shm olabilir, SILMEYIN)
      gorseller/<PROJE>/...       kanit gorselleri (gorsel_dosya alani buraya goreli yoldur)
      onbellek/thumbs/            kucuk resimler (silinebilir, yeniden uretilir)
      yedek/<yyyy-MM-dd>/         gece yedekleri (kanit.db.gz, gorseller.tar.gz, env.600, SHA256SUMS)
      log/web.log, bot.log, yedek.log   uygulama loglari (haftalik dondurulur, 12 hafta tutulur)
      gelen -> /opt/kanit/gelen   Windows'tan yuklenen dosyalar (ice-aktar buradan okur)
      gizli_anahtar.txt           oturum cerezi imza anahtari (kendiliginden uretilir)
  /opt/kanit/.env                 TOKENLAR ve ayarlar (0600, sahibi kanit). Depoda yoktur.
  /opt/kanit/kaynak.txt           guncelle.sh'in kaynagi: "git <url> [dal]" ya da "kopya <klasor>"
  /etc/systemd/system/kanit-web.service, kanit-bot.service   servisler (User=kanit, Restart=always)
  /etc/cron.d/kanit-yedek         03:15 gece yedegi (deploy/yedekle.sh)
  /etc/logrotate.d/kanit          log dondurme
  Plesk                           nginx (alan adi istenince one konur; bkz. nginx-plesk.md), guvenlik duvari, Let's Encrypt

Servisler 'kanit' adli sistem kullanicisi ile calisir (giris yapamaz, kabugu yok). Veri klasoru
disinda hicbir yere yazamazlar (systemd ProtectSystem). Panel root degil, kanit olarak kosar.

Komut satiri (hepsi /opt/kanit/src/kanit icinde, kanit kullanicisi olarak):
  cd /opt/kanit/src/kanit
  runuser -u kanit -- /opt/kanit/venv/bin/python -m kanit <komut>
     web                       paneli elle baslat (normalde systemd yapar)
     bot                       botu elle baslat (normalde systemd yapar)
     saglik                    veritabani, klasorler, token var mi, bot nabzi; 0 = iyi
     ice-aktar --kuru          Windows verisini (gelen/) okur, NE YAPACAGINI raporlar, yazmaz
     ice-aktar --uygula        gercekten aktarir
     excel-ekle                Excel'de olup veritabaninda olmayan satirlari ekler (gecis gunu son eklemeler)
     disa-aktar                tam kitap Excel ciktisi (proje basina sayfa)
     yedekle [hedef]           SQLite tutarli kopyasi
     kullanici-ekle AD YETKI   panel kullanicisi (YETKI: admin | * | OF | OF:oku,kt ...); gecici sifreyi yazar
     sifre-sifirla AD          yeni gecici sifre uretir
Kisaltma olarak su takma adi kullanabilirsiniz (root'un ~/.bashrc'sine):
  alias kanit='cd /opt/kanit/src/kanit && runuser -u kanit -- env HOME=/opt/kanit /opt/kanit/venv/bin/python -m kanit'
  sonra:  kanit saglik   /   kanit kullanici-ekle ayse OF


1) ILK KURULUM (adim adim)
--------------------------
Gerekenler: Ubuntu 24.04 + Plesk Obsidian sunucu, root SSH, sunucunun IP'si. Elinizde: test botu
token'i (BotFather'dan yeni bir bot acin, ornek @kanit_test_bot), Gyazo token'i, uyelerin ortak
sifresi (Windows config.json icindeki BOT_PASSWORD), admin Telegram ID'leri (config.json ADMIN_IDS).

a) Kaynak kodu sunucuya alin. Iki yol:
   - git ile (onerilen):   ssh root@SUNUCU
                           apt-get install -y git
                           git clone https://github.com/it-cladue/kote.git /root/kote
   - ya da kopyayla: bilgisayarinizdan   scp -r kote/kanit kote/deploy kote/README.md root@SUNUCU:/root/kote/

b) Kurulumu calistirin (root):
     bash /root/kote/deploy/kur.sh                      # kaynak: /root/kote klasoru kopyalanir
   ya da dogrudan git'ten:
     bash /root/kote/deploy/kur.sh --repo https://github.com/it-cladue/kote.git --dal main
   Betik sirayla: paketler, 'kanit' kullanicisi, klasorler, kaynak -> /opt/kanit/src, venv + pip,
   /opt/kanit/.env (TELEGRAM_TOKEN, GYAZO_TOKEN, BOT_PASSWORD, ADMIN_IDS'i ekranda sorar; TEST
   botunun token'ini verin), systemd birimleri, kanit-web'i baslatir (BOTU BASLATMAZ), cron ve
   logrotate, Plesk guvenlik duvarinda 8080'i acar, ilk super admini olusturur ve GECICI SIFREYI
   ekrana yazar, en sonda kontrol listesi.
   Betik tekrar calistirilabilir; var olan .env'e ve veriye dokunmaz.
   Once ne yapacagini gormek icin:  KANIT_KUR_DRY=1 bash /root/kote/deploy/kur.sh
   Sorulari gecmek icin:            bash kur.sh --sessiz   (sonra nano /opt/kanit/.env)

c) Tarayicida http://SUNUCU-IP:8080 acin, 'admin' ve gecici sifreyle girin, sifrenizi degistirin.
   Panel acilmiyorsa:  /opt/kanit/src/deploy/kontrol.sh   ve   tail -50 /opt/kanit/veri/log/web.log

d) Diger panel kullanicilarini ekleyin (panelden Kullanicilar sayfasi ya da komut satiri):
     kanit kullanici-ekle ayse OF            # OF takim admini
     kanit kullanici-ekle mehmet "OF:oku,kt PA"   # OF'ye bakar+onaylar, PA'da tam yetki
   Yetki kisaltmalari: admin (super admin) | * (tum projeler) | OF | OF:oku | OF:oku,kt | OF,PP:oku GA

e) Saat dilimi: zaman damgalari .env icindeki TZ'ye (Europe/Istanbul) gore yazilir; sunucunun
   kendi saatini de ayni yapmak isterseniz:  timedatectl set-timezone Europe/Istanbul


2) VERIYI WINDOWS'TAN TASIMA
----------------------------
Windows bot klasorunde (OneDrive - Get Mails\telegramkant) su dosyalar vardir:
   telegrambot_gyazo.xlsx      ana Excel (tum kayitlar; config.json EXCEL_DOSYA degeri farkli olabilir)
   onaylilar.txt, engellenenler.txt, kullanicilar.json, oturumlar.json, kategoriler.json
   bakim_modu.txt, gyazo_bakim.txt, kayitlar.jsonl, bot_log.txt
   panel_kullanicilar.json     panel kullanicilari (OneDrive paneli)
   gorseller\<PROJE>\...       ve   ekran_goruntuleri\   (toplam ~2 GB)

a) Windows'ta hazirlik (bot ACIKKEN olabilir, ama Excel'i kapatin):
   - gorseller ve ekran_goruntuleri klasorlerini tek zip yapin: sag tik > Sikistir > gorseller.zip
     (PowerShell:  Compress-Archive -Path gorseller,ekran_goruntuleri -DestinationPath gorseller.zip)
   - Excel'i ve durum dosyalarini bir klasore toplayin (ornek: C:\aktar\): xlsx + yukaridaki txt/json'lar.
     config.json'u KOYMAYIN (token iceriyor; zaten .env'de yazili).

b) Sunucuya yukleme (Windows'ta PowerShell ya da WinSCP; /opt/kanit/gelen klasorune):
     scp C:\aktar\*  root@SUNUCU:/opt/kanit/gelen/
     scp C:\yol\gorseller.zip  root@SUNUCU:/opt/kanit/gelen/
   2 GB zip 10-30 dakika surer; kopuyorsa WinSCP (yeniden baslatabilir) kullanin.
   Sunucuda acin ve sahipligi verin:
     cd /opt/kanit/gelen && unzip -q gorseller.zip && rm gorseller.zip
     chown -R kanit:kanit /opt/kanit/gelen
     ls /opt/kanit/gelen     # xlsx, txt/json dosyalari, gorseller/, ekran_goruntuleri/ gorunmeli

c) Deneme aktarimi (hicbir sey yazmaz, rapor verir):
     kanit ice-aktar --kuru
   Rapor: kac proje, kac satir, kac gorsel eslesti, eslesmeyen/bozuk satirlar, onayli/engelli uye
   sayilari. Excel'deki satir sayisiyla karsilastirin. Sorunlu satirlar varsa once Windows'ta
   duzeltip dosyayi yeniden yukleyin (ya da sonra panelden duzeltin).

d) Gercek aktarim:
     kanit ice-aktar --uygula
   Bitince panelde proje kartlarindaki sayilara bakin; birkac kaydi acip gorselin geldigini gorun.
   Aktarim tekrar calistirilabilir (ayni satiri ikinci kez eklemez); gerekirse veritabanini sifirlayip
   bastan: systemctl stop kanit-web; mv /opt/kanit/veri/kanit.db /opt/kanit/veri/kanit.db.eski; systemctl start kanit-web
   (sonra ilk admini yeniden olusturun: kanit kullanici-ekle admin admin).

e) Gelen klasorunu bir sure saklayin (gecis bitince silebilirsiniz; gorseller zaten veri/gorseller'e
   kopyalandi):  du -sh /opt/kanit/gelen


3) TEST BOTU, PARALEL HAFTA VE GECIS SIRASI
-------------------------------------------
Telegram'da AYNI token'la iki bot ayni anda calisamaz (getUpdates cakisir, ikisi de bozulur).
Bu yuzden once TEST botuyla calisilir, gercek token en sonda tasinir.

a) .env'de TELEGRAM_TOKEN test botunun token'i olsun (kur.sh sirasinda yazdiniz; kontrol:
   grep TELEGRAM_TOKEN /opt/kanit/.env). Botu acin:
     systemctl enable --now kanit-bot
     tail -f /opt/kanit/veri/log/bot.log        # "getMe ... @kanit_test_bot" satiri gelmeli
b) Telegram'da test botuna yazin: sifre, proje, kategori, personel kodu, gorsel... kayit panelde
   aninda gorunmeli. Panelden onaylayin; bot tarafindaki sayaclar da ayni veritabanindan okunur.
   Admin komutlari (/durum, /bakim_ac, /istatistik ...) ADMIN_IDS'teki kisiler icin calisir.
c) PARALEL HAFTA: eski Windows botu gercek uyelere hizmet vermeye devam eder; takim adminleri
   yeni paneli (http://SUNUCU-IP:8080) ve test botunu bir hafta kullanir. Bu surede Windows'ta
   eklenen kayitlar sunucuda YOKTUR; gecis gunu 'excel-ekle' ile tamamlanir (asagida).
   Takim adminlerinin paneli sorunsuz kullanabildigi, Excel ciktisinin eski Excel ile ayni
   duzende oldugu (Cikti sayfasi) ve gorsellerin acildigi dogrulanir.

d) GECIS GUNU (sira onemlidir; 30-60 dakika, uyelere "bot bakimda" mesaji gider):
   1. Windows'ta eski bota admin olarak  /bakim_ac  yazin (uyelere bakim mesaji, yeni kayit alinmaz).
   2. Windows'ta son Excel'in kapali oldugundan emin olun; eski botu durdurun (PowerShell penceresini
      kapatin ya da bota /kapat). Botun artik getUpdates cagirmadigindan emin olun (bot_log.txt).
   3. Son Excel'i (telegrambot_gyazo.xlsx) ve paralel haftada eklenen gorselleri (gorseller\ klasorunun
      son hafta eklenen dosyalari; zip yapmak en kolayi) sunucuya /opt/kanit/gelen'e yeniden yukleyin
      (2b'deki gibi; onceki dosyalarin ustune yazin), chown -R kanit:kanit /opt/kanit/gelen.
   4. Sunucuda:  kanit excel-ekle            # Excel'de olup veritabaninda olmayan satirlari ekler
      Ciktiyi okuyun: kac satir eklendi. Panelde sayilari Excel'in son satiriyla karsilastirin.
   5. Eski token'i IPTAL edin: Telegram'da @BotFather > /mybots > gercek bot > API Token > Revoke
      current token. Yeni token verilir; eski Windows botu artik bu bota baglanamaz (yanlislikla
      acilsa bile). YENI token'i kopyalayin.
   6. Sunucuda .env'e gercek botun YENI token'ini yazin:
        nano /opt/kanit/.env      ->  TELEGRAM_TOKEN=<yeni token>
        systemctl restart kanit-bot
        tail -f /opt/kanit/veri/log/bot.log     # getMe'de gercek botun adi gorunmeli
   7. Sunucudaki bota admin olarak /durum ve gerekirse /bakim_kapat (bakim modu veritabanindan
      okunur; Windows'taki bakim_modu.txt ice-aktar ile gelmis olabilir, kapatin).
   8. Bir uyeden deneme kaydi isteyin; panelde gorun, onaylayin. Gecis bitti.
   9. Windows'ta: telebot.ps1'i zamanlanmis gorevden/baslangictan kaldirin (bir daha acilmasin);
      klasoru en az 1 ay arsiv olarak saklayin. OneDrive panel exe'si artik kullanilmaz.
   Geri donus (ilk saatlerde ciddi sorun cikarsa): sunucuda systemctl stop kanit-bot; BotFather'dan
   token'i bir kez daha yenileyip Windows config.json'a yazin; Windows botunu acin. Sunucudaki
   paneldeki kayitlar yerinde kalir; sonra tekrar denenir.


4) GUNLUK ISLETME
-----------------
Hizli bakis (hepsini bir arada gosterir, sorun varsa SORUN satiri ve cikis kodu 1):
    /opt/kanit/src/deploy/kontrol.sh

Servisler:
    systemctl status kanit-web kanit-bot
    systemctl restart kanit-web          # ayar degisince
    systemctl restart kanit-bot
    journalctl -u kanit-bot -n 50        # systemd tarafindaki cokme/yeniden baslatma kayitlari

Loglar (uygulama):
    tail -f /opt/kanit/veri/log/web.log
    tail -f /opt/kanit/veri/log/bot.log
    grep -i "hata\|error\|traceback" /opt/kanit/veri/log/bot.log | tail -20
    cat /opt/kanit/veri/log/yedek.log    # gece yedegi
  Loglar haftalik dondurulur (web.log.1, web.log.2.gz ...), 12 hafta saklanir.

Guncelleme (yeni surum):
    /opt/kanit/src/deploy/guncelle.sh            # git pull (ya da kopya), pip, restart, saglik, son 20 log satiri
  Kopya modunda once yeni dosyalari /opt/kanit/kaynak.txt'deki klasore koyun (ornek /root/kote).
  Guncelleme oncesi ara yedek: /opt/kanit/src/deploy/yedekle.sh --sadece-db  (saniyeler surer).

Yedek:
    /opt/kanit/src/deploy/yedekle.sh             # elle; cron zaten her gece 03:15 calistirir
    ls -la /opt/kanit/veri/yedek/                # tarih klasorleri; SON dosyasinda son tarih
  Her klasorde: kanit.db.gz (veritabani), gorseller.tar.gz (tum gorseller, ~2 GB), env.600 (.env
  kopyasi, tokenlar!), SHA256SUMS. 30 gunden eskiler silinir (yedekle.sh --gun 60 ile degisir).
  Yer hesabi: 30 x ~2 GB = ~60 GB; disk kucukse /etc/cron.d/kanit-yedek satirina --gun 14 ekleyin.
  UZAK KOPYA (sunucu olurse): rclone kurun, uzak hedefi tanimlayin, dosya /opt/kanit/rclone.conf olsun:
      apt-get install -y rclone
      rclone --config /opt/kanit/rclone.conf config      # ad: kanit-yedek; tur: drive / s3 / b2 / sftp ...
      chmod 600 /opt/kanit/rclone.conf
  Artik her gece yedek klasoru "kanit-yedek:kanit" hedefine esitlenir (KANIT_RCLONE_HEDEF ile degisir).
  env.600 tokenlari tasidigi icin uzak hedef sifreli (rclone crypt) olsun ya da KANIT_YEDEK_ENV=0
  ile env kopyasi kapatilsin (cron satirina ortam degiskeni olarak eklenir).
  Panelden "Yedekle" (bot sayfasi, /yedekle komutu) yalnizca veritabani kopyasi alir; gece yedeginin
  yerine gecmez.

Geri yukleme (yedekten donme):
    /opt/kanit/src/deploy/geri-yukle.sh                  # eldeki yedekleri listeler
    /opt/kanit/src/deploy/geri-yukle.sh 2026-03-14       # o gunun yedegine doner (EVET yazarak onaylanir)
    /opt/kanit/src/deploy/geri-yukle.sh 2026-03-14 --sadece-db     # gorsellere dokunmaz (hizli)
    /opt/kanit/src/deploy/geri-yukle.sh /root/indirilen-yedek      # rclone ile baska yerden indirilen klasor
  Betik servisleri durdurur, SIMDIKI veriyi veri/yedek/geri-yukleme-oncesi-<zaman>/ altina kenara alir,
  yedegi acar, servisleri baslatir, saglik kontrolu yapar. Yedek tarihinden sonraki kayitlar gider;
  kenara alinan klasorde dururlar (gerekirse oradaki kanit.db'den elle bakilir).
  Yalnizca TEK KAYIT ya da bir yorum geri alinacaksa yedege gerek yok: panelde kaydin penceresinde
  GERI AL (silinen kayit) ve Gecmis (onceki surumler) vardir; arsiv tablosu her degisikligi tutar.

Panel kullanicisi ekleme / sifre sifirlama:
    panelden: Kullanicilar sayfasi (super admin)
    komutla:  kanit kullanici-ekle ad "OF:oku,kt"      # gecici sifreyi yazar, ilk giriste degistirilir
              kanit sifre-sifirla ad                   # yeni gecici sifre
  Super admin sifresini unutursaniz:  kanit sifre-sifirla admin
  5 yanlis denemede 15 dakika kilit vardir (IP ve kullanici bazli); beklemek yeter.

Bot yanit vermiyor:
    1. systemctl status kanit-bot  -> calismiyorsa  systemctl start kanit-bot; journalctl -u kanit-bot -n 50
    2. tail -50 /opt/kanit/veri/log/bot.log
       "401 Unauthorized"  -> token yanlis/iptal edilmis; .env'i duzeltin, restart
       "409 Conflict"      -> AYNI token'la baska bir bot calisiyor (Windows'taki eski bot acik kaldi!)
                              Windows'takini kapatin ya da BotFather'dan token yenileyin
       "Bakim modu"        -> bota /bakim_kapat (admin) ya da panel Bot sayfasi
       baglanti hatalari   -> curl -sI https://api.telegram.org  (sunucunun disari cikisi, Plesk guvenlik duvari)
    3. kontrol.sh "bot nabzi" satirina bakin: bot 60 saniyede bir nabiz yazar; eskiyse bot donmustur:
       systemctl restart kanit-bot
    4. Uyenin kendisi engelli olabilir: panel Bot sayfasi > engelliler / kullanici ara.

Panel acilmiyor / 502:
    systemctl status kanit-web; tail -50 /opt/kanit/veri/log/web.log; ss -ltnp | grep 8080
    Alan adi arkasindaysa nginx-plesk.md'deki sorun giderme tablosu.

Disk doldu:
    df -h /opt/kanit ; du -sh /opt/kanit/veri/* | sort -h
    - En buyuk sey yedeklerdir: eski yedek klasorlerini silin (rm -rf /opt/kanit/veri/yedek/2026-01-*),
      cron satirina --gun 14 ekleyin, uzak kopya acin.
    - onbellek/thumbs silinebilir (yeniden uretilir). /opt/kanit/gelen gecis bitince silinebilir.
    - Loglar: logrotate haftalik sikistirir; cok buyudu ise  : > /opt/kanit/veri/log/web.log
    - Disk %90'i gecince kontrol.sh SORUN verir. SQLite yazamazsa bot "disk full" hatasi verir;
      yer acip systemctl restart kanit-bot.
    Kayitlar ve gorseller SILINMEZ; yer gorsellerden dolayi yetmiyorsa diski buyutun (bkz. 5).

Token sizdi (Telegram ya da Gyazo):
    1. Telegram: BotFather > /mybots > bot > API Token > Revoke. Gyazo: gyazo.com/oauth/applications >
       token'i sil, yeni uret.
    2. nano /opt/kanit/.env -> yeni degerleri yazin;  systemctl restart kanit-bot kanit-web
    3. Eski yedeklerdeki env.600 dosyalarinda eski token durur; artik gecersiz olduklari icin zararsiz,
       yine de uzak kopyada da yenilenmis olurlar (bir sonraki gece).
    4. .env izni hep 600 ve sahibi kanit olmali (kontrol.sh bakar). Sifre (BOT_PASSWORD) sizdiysa
       .env'de degistirin; uyeler bir sonraki girislerinde yeni sifreyi yazar.
    Panel kullanicisinin sifresi sizdiysa: sifre-sifirla ya da Kullanicilar sayfasindan kapatin.

Port ya da alan adi degistirme:
    Port: nano /opt/kanit/.env -> PORT=8090; Plesk guvenlik duvarinda yeni portu acin
          (plesk ext firewall --add -name 'Kanit paneli' -direction input -action allow -ports 8090/tcp;
           plesk ext firewall --apply && plesk ext firewall --confirm), eskisini kaldirin;
          systemctl restart kanit-web
    Alan adi + HTTPS: deploy/nginx-plesk.md (Plesk'te alan adi > Apache & nginx Ayarlari > ek yonergeler;
          .env'de DINLE=127.0.0.1, GUVENILIR_PROXY=1, HTTPS=1, SITE_URL=https://...; restart).

Sunucu yeniden baslayinca: iki servis de kendiliginden kalkar (enable edilmis). Bot ilk kurulumda
bilerek kapalidir; 'systemctl enable --now kanit-bot' dendikten sonra o da kalkar.

Bakim modu (uyelere "bot bakimda" deyip kayit almamak): bota /bakim_ac ve /bakim_kapat (admin)
ya da panel Bot sayfasi. Gyazo bakimi (/gyazo_bakim_ac) Gyazo secenegini kapatir, gorsel dosya olarak
alinir. Ikisi de veritabanindaki ayarlar tablosunda durur; servis yeniden baslasa da kalir.

Sunucu kaynaklari: 4 cekirdek / 7.6 GB RAM bu yuk icin fazlasiyla yeter (panel + bot ~200 MB).
Takas alani yoksa 2 GB eklemek guvenli taraftir (fallocate -l 2G /swapfile; chmod 600; mkswap; swapon;
/etc/fstab satiri). Veritabani yuz binlerce kayitta bile tek dosya olarak kalir.


5) VERI SAKLAMA (kurum ici bildirim)
------------------------------------
- Kayitlar HICBIR ZAMAN silinmez/temizlenmez. Panelden "silinen" kayit yalnizca durum olarak silinmis
  isaretlenir; arsivde (arsiv tablosu) ve "Silinen" filtresinde gorunmeye, GERI AL ile geri gelmeye
  devam eder. Her duzenleme/onay/silme arsive eski ve yeni haliyle, kim ve ne zaman bilgisiyle yazilir;
  arsiv tablosu uygulama tarafindan asla degistirilmez ya da budanmaz.
- Gorseller veri/gorseller altinda kalici olarak durur; kayit silinse de gorsel silinmez.
- Denetim kaydi (kim neyi ne zaman hangi IP'den yapti) panel ve bot icin tutulur, budanmaz.
  Yalnizca "bildirimler" (zil) 90 gun sonra temizlenir; bunlar veri degil, uyari kayitlaridir.
- Yedekler: her gece 03:15, sunucuda 30 gun (veri/yedek), istenirse uzak kopya (rclone) ile
  sunucu disinda da. Yedekten geri donus deploy/geri-yukle.sh ile dakikalar icinde yapilir.
- Tokenlar ve sifreler yalnizca /opt/kanit/.env (0600) ve yedeklerdeki env.600 kopyasinda durur;
  depoya (git) girmez. Panel sifreleri karma (hash) olarak saklanir; geri cevrilemez.
- Veriye erisim: sunucuda root ve kanit kullanicisi; panelde yetki kisaltmalarina gore
  (OF takim admini yalnizca OF'yi gorur). Excel/CSV cikti indirmeleri denetime yazilir.


6) SIK KULLANILAN KOMUTLAR (ozet)
---------------------------------
  /opt/kanit/src/deploy/kontrol.sh                 durum, saglik, disk, son hatalar
  /opt/kanit/src/deploy/guncelle.sh                yeni surum
  /opt/kanit/src/deploy/yedekle.sh [--sadece-db]   yedek al
  /opt/kanit/src/deploy/geri-yukle.sh <tarih>      yedekten don
  systemctl restart kanit-web kanit-bot            ayar degisince
  tail -f /opt/kanit/veri/log/bot.log              bot logu
  nano /opt/kanit/.env                             tokenlar / port / proxy ayarlari
  kanit saglik | kullanici-ekle AD YETKI | sifre-sifirla AD | ice-aktar --kuru|--uygula | excel-ekle | disa-aktar | yedekle
  (kanit = cd /opt/kanit/src/kanit && runuser -u kanit -- env HOME=/opt/kanit /opt/kanit/venv/bin/python -m kanit)

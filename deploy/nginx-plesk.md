# Alan adi ve HTTPS: Plesk nginx'in arkasina alma

Panel ilk kurulumda `http://SUNUCU-IP:8080` adresinde, dogrudan waitress ile calisir.
Bir alan adi (ornek `kanit.sirket.com`) ve HTTPS isteniyorsa Plesk'in kendi nginx'i one konur.
**Plesk'in nginx dosyalarina elle DOKUNULMAZ** (`/etc/nginx/plesk.conf.d/...` Plesk tarafindan
yeniden uretilir, elle yapilan degisiklik silinir). Her sey Plesk arayuzunden yapilir.

## 1) Alan adi

Iki secenek:

- **Kendi alan adiniz**: DNS'te `kanit.sirket.com` icin sunucunun IP'sine A kaydi acin
  (Cloudflare kullaniyorsaniz asagiya bakin). Plesk > *Web Siteleri ve Alan Adlari* >
  *Alan Adi Ekle* (ya da *Alt Alan Adi Ekle*) > `kanit.sirket.com`, hosting turu "Web sitesi".
  Belge koku bos kalabilir; nginx dogrudan panele yonlendirecek.
- **Plesk'in hazir adi**: Plesk sunucuya `<ad>.plesk.page` gibi bir ad vermis olabilir
  (*Araclar ve Ayarlar* > *Sunucu Ayarlari* > tam sunucu adi). DNS ugrastirmadan onu
  kullanabilirsiniz; sertifika da Plesk'ten alinir.

## 2) nginx yonlendirmesi (Plesk arayuzu)

Alan adi > **Apache & nginx Ayarlari** (Apache & nginx Settings):

1. **Proxy mode** (nginx'i Apache'ye vekil olarak kullan) kutusunun isaretini KALDIRIN.
   Boylece istek Apache'ye degil, asagidaki `location /` blogu ile panele gider.
2. "Statik dosyalari dogrudan nginx ile sun" acik kalabilir, zarari yok (belge koku bos).
3. **Ek nginx yonergeleri** (Additional nginx directives) kutusuna su blogu yapistirin:

```nginx
# Kanit Merkezi paneli (waitress, 127.0.0.1:8080)
client_max_body_size 25m;

location / {
    proxy_pass         http://127.0.0.1:8080;
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-Host  $host;
    proxy_read_timeout 120s;
    proxy_redirect     off;
}

# Gorsel ve onbellek yanitlari buyuk olabilir; tamponu artir
proxy_buffers 16 32k;
proxy_buffer_size 64k;
```

4. **Tamam / Uygula**. Plesk nginx'i kendisi yeniden yukler. Hata verirse genellikle
   `client_max_body_size` Plesk'in kendi ayariyla cakismistir; o satiri silip
   degeri *Apache & nginx Ayarlari* > "Maksimum istek govdesi" alanindan verin.

Not: `.well-known/acme-challenge` (Let's Encrypt dogrulamasi) Plesk tarafindan `location /`
ustunde ayri tanimlanir, bizim blok onu etkilemez.

## 3) Uygulama ayari

`/opt/kanit/.env` icinde:

```
DINLE=127.0.0.1        # artik disaridan 8080'e dogrudan girilmesin; yalnizca nginx ulassin
GUVENILIR_PROXY=1      # gercek istemci IP'si X-Forwarded-For'dan okunsun (denetim, IP kilidi)
HTTPS=1                # oturum cerezi yalnizca https ile tasinsin (sertifikadan SONRA 1 yapin)
SITE_URL=https://kanit.sirket.com
```

Sonra:

```
systemctl restart kanit-web
/opt/kanit/src/deploy/kontrol.sh
```

8080 portunu disaridan kapatin (artik gerek yok):

```
plesk ext firewall --list                      # 'Kanit paneli' kuralinin id'sini bulun
plesk ext firewall --remove -id <ID>  (ya da arayuzden silin)
plesk ext firewall --apply && plesk ext firewall --confirm
# ufw kullaniliyorsa:  ufw delete allow 8080/tcp
```

`DINLE=127.0.0.1` oldugu icin port acik kalsa bile disaridan erisilemez; kapatmak
yine de temizdir.

## 4) Let's Encrypt (Plesk)

Alan adi > **SSL/TLS Sertifikalari** > *Let's Encrypt* > e-posta girin, "alan adini ve www'yi
koru" > Al. Ardindan ayni sayfada **"HTTP'den HTTPS'ye kalici SEO-guvenli 301 yonlendirme"**
(Permanent SEO-safe redirect) anahtarini acin. Yenileme Plesk tarafindan otomatiktir.
Sertifika geldikten sonra `.env` icinde `HTTPS=1` yapip `systemctl restart kanit-web`.

HSTS istenirse: SSL/TLS sayfasindaki "HSTS" anahtari (once https'in calistigindan emin olun).

## 5) Cloudflare (istege bagli)

Alan adi Cloudflare'da ise ve kayit "turuncu bulut" (proxied) ise:

- Cloudflare SSL/TLS modu **Full (strict)** olsun; Plesk'te Let's Encrypt sertifikasi dursun
  (ya da Cloudflare Origin sertifikasi Plesk'e yuklenir).
- Gercek istemci IP'si `CF-Connecting-IP` basligindan gelir; uygulama `GUVENILIR_PROXY=1`
  iken once bu basliga, yoksa `X-Forwarded-For`a bakar; ek ayar gerekmez.
- Cloudflare'in 100 MB yukleme siniri panel icin yeterlidir (gorsel ust siniri 8 MB).
- Isterseniz Cloudflare Access ile e-posta/Microsoft hesabi dogrulamasi eklenir
  (panelin kendi girisi yine kalir).

## 6) Sorun giderme

| Belirti | Bakilacak yer |
|---|---|
| 502 Bad Gateway | `systemctl status kanit-web`; `.env` DINLE 127.0.0.1 ve PORT 8080 mi; `ss -ltnp | grep 8080` |
| Giris yapinca tekrar giris ekrani | `HTTPS=1` ama site http ile aciliyor -> https'e yonlendirmeyi acin ya da HTTPS=0 |
| Denetimde tum IP'ler 127.0.0.1 | `GUVENILIR_PROXY=1` degil ya da X-Forwarded-For satiri eksik |
| Gorsel yuklerken 413 | `client_max_body_size` uygulanmamis; Plesk "Maksimum istek govdesi" alani |
| Plesk "nginx yapilandirmasi gecersiz" | yonergeyi satir satir deneyin; `nginx -t` ciktisini Plesk gosterir |
| Sayfa yavas, log'da timeout | `proxy_read_timeout` artirin; disa aktarma (Excel) uzun surebilir |

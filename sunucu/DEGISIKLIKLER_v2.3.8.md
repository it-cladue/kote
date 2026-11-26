# Kanıt Paneli 2.3.8 — Bekleyen özeti: "Onay bekleyen N kayıt var" (2 saatte bir)

Önceki sürüm üzerine `deploy/apply-update.sh` ile uygulanır (KURULUM §13, güncelleme yolu değişmedi). Veritabanı şeması değişmez, `.env` dosyasına bir şey yazmak gerekmez (varsayılanlar aşağıda). Değişen dosyalar: `app/hatirlatma.py`, `app/settings.py`, `app/bildirim_gecmisi.py`, `app/panel.py` (yalnız bildirim bağlantısı), `app/cli.py`, `app/static/panel.js`, `.env.example`.

## Ne değişti?

Şimdiye kadar onaylanmayan **her kayıt** 2 saati doldurunca ayrı ayrı bildirim üretiyordu ("Kayıt #… 2 saattir onay bekliyor."). Kalabalık günlerde zil bu satırlarla doluyordu. 2.3.8 ile bunun yerine **2 saatte bir tek bir özet** gelir:

> Onay bekleyen 18 kayıt var (GA 12, OF 6); en eskisi 3 gündür bekliyor. Son 2 saatte 4 yeni kayıt geldi.

- Parantez içinde proje başına bekleyen sayısı (en kalabalık proje önce; 8'den fazla proje varsa kalanı "diğer N proje" olarak toplanır).
- "En eskisi …" en uzun süredir bekleyen kaydın yaşıdır: 24 saatten azsa "5 saattir", fazlaysa "3 gündür".
- "Son 2 saatte N yeni kayıt geldi" o aralıkta eklenen kayıt sayısıdır (o sırada onaylanmış olanlar da sayılır); hiç yeni kayıt yoksa bu cümle yazılmaz.

## Ne zaman gelir?

- İstanbul saatiyle **08:00, 10:00, 12:00, 14:00, 16:00, 18:00 ve 20:00**'de (varsayılan: 08:00–20:00 arası, 2 saatte bir). Panel 10 dakikada bir kontrol ettiği için bildirim en geç ~10 dakika gecikmeyle düşer.
- Her saat diliminde kişi başına **bir** bildirim. Panel bir süre kapalı kaldıysa kaçan saatler sonradan tek tek gönderilmez; açılınca yalnız içinde bulunulan saatin özeti gider. Pencere bitişinden (20:00) 1 saatten sonra o günün özeti artık gönderilmez.
- O anda kişinin bakması gereken **bekleyen kayıt yoksa bildirim gelmez.**

## Kime gelir?

- Bir projede **onay (takım lideri) yetkisi** olan her aktif kullanıcıya; sayılar yalnız **onaylayabildiği projelerin** kayıtlarıdır. Yalnız görüntüleme yetkisi olan projeler sayılmaz.
- **Süperadmin**lere de gelir (tüm projeler). İstemiyorsanız `BEKLEYEN_OZET_YONETICI=0`.
- `ONAYSIZ_GORUNUM=gizle` kullanılıyorsa da aynı kural geçerlidir (özet zaten yalnız onay yetkili projeleri sayar).

## Zilde ne görünür?

- Yeni özet gelince **bir öncekisi kendiliğinden okundu sayılır**: zilde her zaman yalnız **en son** özet durur, eskileri birikmez. Bekleyen kalmadıysa önceki özet de zilden düşer. Eski özetler **Bildirimler** sayfasında "okundu" olarak durur.
- Özet diğer hatırlatmalar gibi sağ üstte kart olarak çıkar (kart kendiliğinden kapanmaz, **Okundu** ya da **×** ile kapanır), hatırlatma sesini çalar ve zile düşer.
- **Ortadaki "Bekleyen kontroller hatırlatması" penceresini kendiliğinden açmaz** (2 saatte bir pencere açılması çalışmayı bölerdi). Pencere başka bir hatırlatma için açıldığında ya da zil listesindeki **Hatırlatmalar (N)** düğmesiyle açıldığında özet de "**Bekleyen özeti**" başlığıyla listelenir.
- **Bekleyenleri aç** düğmesi Kayıtlar sayfasında onay bekleyen listeyi açar: onay yetkiniz olan projelerle süzülmüş olarak (süperadminde ya da görebildiği bütün projelerde onay yetkisi olan kullanıcıda süzgeçsiz).

## Kayıt başına 2 saat bildirimi artık varsayılan kapalı

Özet onun yerini aldığı için `HATIRLATMA_SAAT` varsayılanı **0 (kapalı)** oldu. Eski davranışı (her kayıt için ayrı "2 saattir onay bekliyor" bildirimi) geri istiyorsanız `.env`'e `HATIRLATMA_SAAT=2` yazın. Değişmeyenler: 3 gün hatırlatmaları (`HATIRLATMA_GUN`) ve 18:00 **gün sonu özeti** aynen sürer; gün sonu özetindeki "2 saatten uzun bekleyen" sayısı da aynı kalır.

## Ayarlar (isteğe bağlı, `/opt/kanit-paneli/.env`; değiştirince `systemctl restart kanit-web`)

| Anahtar | Varsayılan | Anlamı |
|---|---|---|
| `BEKLEYEN_OZET_SAAT` | `2` | Kaç saatte bir. `0` = özet kapalı. En çok 24. Geçersiz değer → 2. |
| `BEKLEYEN_OZET_PENCERE` | `08:00-20:00` | İstanbul saatiyle hangi saatler arasında. Saatler pencere başından itibaren sayılır: `08:00-20:00` ve 3 saat → 08, 11, 14, 17, 20. Boş bırakılırsa bütün gün (00:00'dan itibaren). `08-20`, `8.30-19.30` yazımları da kabul edilir. Geçersizse (ör. `20:00-08:00`) varsayılan kullanılır ve günlüğe bir kez "BEKLEYEN_OZET_PENCERE geçersiz" yazılır. |
| `BEKLEYEN_OZET_YONETICI` | `1` | `0` = süperadminler özet almaz. |
| `HATIRLATMA_SAAT` | `0` (2.3.8) | Kayıt başına 2 saat bildirimi; `2` = eski davranış. |

Örnekler: 3 saatte bir ve 09:00–18:00 arası → `BEKLEYEN_OZET_SAAT=3`, `BEKLEYEN_OZET_PENCERE=09:00-18:00` (09, 12, 15, 18). Özeti tamamen kapatmak → `BEKLEYEN_OZET_SAAT=0`.

## Sunucuda deneme

```bash
cd /opt/kanit-paneli && runuser -u kanit -- /opt/kanit-paneli/.venv/bin/python -m app.cli hatirlatma-uret --bekleyen-ozet-zorla
```

`--bekleyen-ozet-zorla` içinde bulunulan saatin özetini pencere dışında da hemen üretir (yine saat dilimi başına bir kez; ikinci çalıştırma yeni satır eklemez). Kısa Türkçe rapor ekrana yazılır, ör. `Bekleyen özeti (2026-11-26 10:00): 3 alıcıya gönderildi, 3 önceki özet okundu sayıldı, 0 alıcının bekleyeni yok; durum: gönderildi.` Pencere dışındaysanız ve bayrak yoksa: `Bekleyen özeti: pencere dışında (İstanbul saati 07:40, pencere 08:00-20:00, 2 saatte bir).`

## Teknik notlar

- Bildirim satırı: `tur='hatirlatma'`, `kim='sistem'`, olay anahtarı `bekleyen-ozet:<YYYY-AA-GG SS:DD>` (İstanbul saat dilimi). Aynı kişiye aynı dilim için ikinci satır yazılmaz (mevcut tekillik kuralı).
- Satırın kayıt numarası, en kalabalık projenin en eski bekleyen kaydıdır (bildirim satırı bir kayda bağlı olmak zorunda; gün sonu özetiyle aynı yöntem). Rozet de bu projeyi gösterir.
- Sunucu saati UTC olsa da dilimler İstanbul saatine göre hesaplanır.

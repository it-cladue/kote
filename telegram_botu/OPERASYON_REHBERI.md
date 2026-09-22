# 📖 OPERASYON REHBERİ — "Ne yapmak istiyorum → Nasıl yaparım"

Bu rehber günlük kullanım içindir: her işin **tam tıklama sırası**, ekranda
**ne göreceğin** ve **bir şey ters giderse ne anlama geldiği** yazar.
Kurulum ve teknik detaylar için `KULLANIM_KILAVUZU.md`'ye bak.

---

## 0) İLK KURULUM — 5 dakikada yayına hazır

1. Klasörü aç → `config.txt` → `### DOLDUR:` yazan satırları kendi
   linklerinle doldur (kayıt, giriş, destek; varsa mini app, yatır/çek,
   3 destek kanalı). **Kaydet.**
2. `BASLAT.bat`'a çift tıkla (Linux: `./baslat.sh`).
3. Telegram'da botuna `/start` yaz → karşılama + görsel + ANA MENÜ + alt
   klavye gelmeli.
4. `/admin` yaz → **ADMIN PANELİ** açılmalı (başlıkta parantez içinde sürüm
   YOK; eski bir kopya çalışıyorsa "(v8...)" görürsün — o pencereyi kapat).
5. Bir kez BotFather'da `/setcommands` yap (liste `KULLANIM_KILAVUZU.md`
   bölüm 3.2'de hazır) — PLAY modunda ⌘ listesinin görünmesi için şarttır.

Bu kadar. Aşağısı günlük işlerin.

---

## 1) DUYURU YAYINLAMAK (📢)

**Ne işe yarar:** Duyuru iki yerde yaşar → (a) kullanıcının Ana Menü →
📢 Duyurular listesinde kalıcı durur, (b) istersen ayrıca herkese anında
mesaj olarak gönderilir.

**Adım adım:**
1. `/admin` → **📢 Duyurular** → **➕ Yeni Duyuru**
   (veya kısayol: `/duyuruekle`)
2. **Başlık** yaz → gönder. (örn: `Hafta Sonu %50 Bonus`)
3. **Metin** yaz → gönder. Vurgu istersen: `**kalın**`, `__italik__`,
   `||gizli||`, tıklanabilir yazı: `[[TIKLA|https://site.com]]`
4. **Foto/video** gönder **veya** medyasız için `/atla` yaz.
5. "DUYURU KAYDEDİLDİ ✅" gelir → altındaki
   **📣 Tüm Kullanıcılara Gönder** butonuna bas.
6. Sonuç raporu gelir: `#3 • ✅ 45 | ❌ 2 | 👥 47`

**Raporu nasıl okurum?**
| Gördüğün | Anlamı | Ne yapmalı |
|---|---|---|
| ✅ 45 | 45 kişiye ulaştı | Hiçbir şey — tamam |
| 🚫 2 kişi botu engellemiş ya da hiç başlatmamış | O 2 kişi ya botu engelledi ya da bu bota hiç Start basmadı (eski token döneminden kalma kayıt olabilir) | Normaldir; yapılacak bir şey yok |
| ⚠️ X gönderimde içerik hatası | Mesajın kendisi Telegram'a takıldı | `bot.log` son satırlarına bak, `[GONDERIM]` satırı tam nedeni yazar |
| "Bu kaydın içeriği BOŞ" | Çok eski/bozuk kayıt | Duyuruyu sil, yeniden oluştur |

**Duyuru silmek:** Panel → Duyurular → duyuruya dokun → 🗑 Sil.
Silinen duyuru kullanıcı menüsünden anında kalkar; eski listede butona
basan kullanıcı "Bu duyuru kaldırıldı" ekranı görür (hata almaz).

**Sık yapılan hata:** Gönder butonuna iki kez basmak — merak etme,
ikinci basış engellenir, kimseye çift gitmez.

---

## 2) BİLDİRİM GÖNDERMEK (📣) — 4 farklı yol

### Yol A — Serbest toplu mesaj (en esnek)
`/bildirim` yaz (veya Panel → 📣 Toplu Mesaj → Oluştur):
1. **Tip seç:** Sadece Metin / Foto+Metin / Foto+Metin+Buton /
   Metin+Promo Kod+Buton / 🧩 Tam Paket (medya+kod+buton)
2. Sırayla istenenleri gönder (her adımda `/atla` ve `/iptal` çalışır):
   başlık → metin → (kod/kodlar) → (foto/video) → (buton yazı + link,
   2. buton sorulur) → **hedef kitle**
3. Hedef kitle: **Herkes** / **Son 24s aktif** / segment
   (🏆 Platin, 🥇 Altın, 🥈 Gümüş, 🥉 Bronz)
4. Önizleme gelir → **✅ Onayla ve Gönder**.
   İstersen önce **📋 Şablon Olarak Kaydet** — bir dahaki sefere
   Panel → Şablonlar'dan tek tıkla gönderirsin.

### Yol B — Kampanya bildirimi (tek tık)
Yeni kampanya oluşturduğunda çıkan
**📣 'Yeni Kampanya Başladı' Bildirimi Gönder** butonuna bas.
Kampanyanın görseli + detayı + butonuyla, kampanyanın **hedef segmentine**
gider (turnuva kategorisindeyse başlık "🏆 TURNUVA BAŞLADI!" olur).
Sonradan göndermek istersen: Panel → Kampanyalar → kampanyaya dokun →
aynı buton oradadır.

### Yol C — Link değişti bildirimi (tek tık)
Panel → Linkler → **Giriş**'i değiştir → kaydedince
**📣 'Giriş Adresi Değişti' Bildirimi Gönder** butonu çıkar → bas.
Herkese yeni adres butonuyla duyuru gider. Mini App linki için de aynısı.

### Yol D — Otomatik bildirimler (sen hiçbir şey yapmazsın)
- Süreli kampanyada **son gün (24 saat kala)** ve **son 2 saat kala**
  hedef kitleye otomatik hatırlatma gider.
- Süresi dolan kampanya menüden otomatik kaldırılır.

---

## 3) ZAMANLI MESAJ (📅) — "yarın 20:30'da gitsin"

1. Panel → **📅 Zamanlı Mesaj** → Oluştur (Yol A'daki sihirbazın aynısı).
2. Hedef seçtikten sonra **zaman** sorar: `15.08.2026 20:30` biçiminde yaz.
3. "KURULDU ✅" gelir. Gönderimden **5 dk önce** sana önizlemeli hatırlatma
   düşer; altında **▶️ Şimdi Gönder** / **🕐 Zamanı Değiştir** / **🗑 İptal Et**
   butonları vardır.
4. Vakti gelince kendisi gönderir ve sana sonucu raporlar.

Güvenlik: "Şimdi Gönder"e bastıysan zamanlayıcı aynı mesajı **bir daha
göndermez** (atomik kilit); iptal ettiğini de göndermez.
Komutla iptal: `/zamanliiptal 3` (yalnızca hâlâ bekleyen kaydı iptal eder).

---

## 4) KAMPANYA EKLEMEK (🎯) — kullanıcı menüsündeki 6 kategori

`/kampanyaekle` (veya Panel → 🎯 Kampanyalar → ➕ Yeni Kampanya):
1. **Kategori seç:** 🎁 Güncel Bonuslar / 🆕 Yeni Üye / 🎰 Slot /
   ⚽ Spor / ⭐ Bana Özel / 🏆 Turnuvalar
2. **Başlık** → **açıklama** (`/atla`nabilir) → **foto/video** (`/atla`) →
   **buton** (`Katıl|https://site.com/turnuva` biçiminde; `/atla`) →
   **ödül havuzu** (`/atla`) → **katılım şartları** (`/atla`) →
   **bitiş tarihi** `20.08.2026 23:59` (`/atla` = süresiz)
3. "KAMPANYA OLUŞTURULDU ✅" + tek tık bildirim butonu gelir.

**Kime görünür?** Varsayılan: herkese. Kampanya detayında
**🏷 Segment** ile kısıtlayabilirsin: manuel kademeler (Platin/Altın/
Gümüş/Bronz) + otomatik **🆕 Yeni Üyeler** (ilk 7 gün) ve
**🕓 Aktif Kullanıcılar** (son 48 saat).

**Düzenleme/söndürme:** Panel → Kampanyalar → kategoriye → kampanyaya
dokun → ✏️ alan düzenle / ⏸ pasife al / 🗑 sil.
İşaretler: ✅ aktif, ⏸ pasif, ⌛ süresi dolmuş.

**Turnuva eklemek = Kampanya eklemek**, sadece kategori olarak
🏆 Turnuvalar'ı seç; ödül havuzu ve katılım şartları alanlarını doldur.

---

## 5) SSS EKLEMEK (❓)

Panel → **❓ SSS Yönetimi** → **➕ Yeni Soru** → soruyu yaz → cevabı yaz.
Kullanıcı Ana Menü → ❓ Sık Sorulan Sorular'da **sorunun tam metnini**
butonda görür; dokununca cevap açılır. Silme: soruya dokun → 🗑.

---

## 6) GÖRSEL / BANNER YÖNETİMİ (🎬)

- **En kolay yol:** admin olarak bota bir **video** gönder → otomatik kütüphaneye
  eklenir ve açılış görseli olur. **Foto** gönderince iki seçenek çıkar:
  **🗂 Kampanya Medyası Yap** (kütüphaneye ekler, aktif yapar) veya
  **📸 Ekran Görüntüsü Olarak Kaydet** (bölüm 15). Fotoya yazdığın açıklama
  kütüphane kaydının adı olur.
  (Bir sihirbaz açıkken gönderirsen eklemez, seni uyarır — önce sihirbazı bitir.)
- Panel → **🎬 Banner & Medya**: kütüphanede sayfa sayfa gez (sayfada 5),
  birine dokun → **aktif yap** / sil.
- Karşılama görselini kampanya görselinden ayrı yapmak istersen:
  Panel → Banner & Medya → Karşılama Medyası (veya `config.txt` →
  `WELCOME_MEDIA_URL`).
- Botun PROFİL fotoğrafı Telegram kuralı gereği yalnızca BotFather'dan
  değişir: `/setuserpic`.

---

## 7) KULLANICI / SEGMENT / BAN (👥)

- **Segment atama:** Panel → 🏷 Kategoriler → kullanıcı seç → kademe ver
  (veya `/setseg ID platin`). Listele: `/seglist platin`.
- **Ban:** `/ban ID sebep` — kullanıcı tabloda yoksa bile çalışır.
  Kaldır: `/unban ID`. Liste: `/banlist`. Panelden: 🚫 Ban bölümü.
- **Bilgi:** `/userinfo ID`, arama `/usersearch isim`, son gelenler
  `/userlist`, en aktifler `/topusers`, dışa aktar `/export`.
- Spam koruması otomatik: aynı komutu 5 sn içinde 5+ kez basan 30 dk
  engellenir; 3 kez tekrarlayan kalıcı banlanır ve sana kritik uyarı düşer.

---

## 8) ŞİKAYET / DESTEK AKIŞI (💬)

- Kullanıcı `/sikayet` ile metin(+foto) iletir → sana anında bildirim düşer.
  Görüntüle: `/sikayetler`, detay `/sikayetler 3`, kapat `/sikayetkapatildi 3`.
  Günde kullanıcı başına 3 şikayet sınırı vardır.
- Kullanıcı serbest bir dert yazarsa **akıllı yönlendirme** devreye girer:
  "param gelmedi" → Çekim kanalı, "yatıramıyorum" → Ödeme kanalı,
  "bonus alamadım" → Bonus kanalı, "canlı destek" → Destek Merkezi.
  Kanal linklerini `config.txt`'te veya Panel → Linkler'de doldur.

---

## 9) SORUN GİDERME — hızlı teşhis

| Belirti | Neden | Çözüm |
|---|---|---|
| Panel başlığında "(v8...)" görüyorum | ESKİ kopya çalışıyor | O süreci kapat, bu klasördeki BASLAT.bat ile başlat |
| "ÇAKIŞMA: bu token ile başka bot çalışıyor" | Aynı token iki yerde | Diğer pencereyi/sunucuyu kapat |
| ⌘ simgesi yok | PLAY modu ⌘'yi gizler (Telegram kuralı) | "/" yaz → liste geliyorsa sorun yok; simge şartsa `MENU_BUTTON_MODE=menu` |
| Menü/komut listesi eski görünüyor | Telegram önbelleği | Sohbeti kapat-aç; webde Ctrl+F5; telefonda uygulamayı tamamen kapat |
| Gönderim raporunda ❌ var | Rapor altındaki satır nedeni söyler | Bölüm 1'deki tabloya bak |
| "SİHİRBAZ AÇIK" uyarısı | Yarım kalan sihirbaz var | `/iptal` yaz, temizlenir |
| Butona bastım "buton eski" dedi | Mesaj eski, oturum/işlem süresi geçmiş | İlgili menüyü yeniden aç (/admin veya /menu) |
| Hiçbir şeye cevap yok | Bot kapalı | BASLAT.bat; pencerede hata varsa bot.log'un son satırlarını gönder |

**Altın kural:** bir hata görürsen `bot.py` klasöründeki `bot.log`
dosyasının son 20 satırını kopyala — kesin neden orada yazar.

---

## 10) YERLEŞİK ASİSTAN (🤖) — kullanıcı elle ne yazarsa yazsın

Bot, kullanıcının **serbestçe yazdığı her mesajı** kendi içinde analiz eder —
**dışarıya hiçbir servis (OpenAI vb.) bağlanmaz**, her şey çevrimdışı çalışır:

1. **Niyet analizi:** Mesaj normalize edilir (büyük/küçük, Türkçe karakter),
   yazım hatalarına toleranslıdır ("çekimm gelmedi", "GIREMIYORUMM" de anlaşılır).
   11 konu tanır: çekim, yatırım, bonus, giriş, üyelik, turnuva, kampanya,
   Site ID, Mini App, selamlaşma, şikayet. Eşleşince konuya özel cevap +
   doğru linkin butonu gider (örn. çekim → 💸 Çekim Destek kanalın).
2. **SSS taraması:** Niyet bulunamazsa mesaj, senin panelden eklediğin
   SSS sorularıyla karşılaştırılır; en iyi eşleşen sorunun **cevabı otomatik
   gönderilir**. Yani SSS'e ne kadar soru eklersen asistan o kadar akıllanır —
   kendi bilgi bankan.
3. **Hiçbiri değilse:** "Seni tam anlayamadım" + örnek kalıplar + Destek
   Merkezi butonları gönderilir. Kullanıcı asla cevapsız kalmaz.

Örnekler (birebir böyle çalışır):
- "param gelmedii ne zaman yatacak" → PARA ÇEKİM cevabı + Çekim Destek butonu
- "kart gecmiyor yatiramiyorum" → PARA YATIRMA + Ödeme Destek + Para Yatır sayfası
- "cevrim sarti nedir acaba" → (SSS'e eklediysen) çevrim şartı cevabı
- "merhaba" → karşılama + yönlendirme örnekleri

Ayarı yoktur; kutudan çıktığı gibi çalışır. Beslemek istersen:
Panel → ❓ SSS Yönetimi'ne bol soru-cevap ekle ve Panel → Linkler'de
3 destek kanalını doldur. Her yönlendirme /dailylog kayıtlarında görünür.

---

## 11) "DOSYA NEDEN KÜÇÜK?" — boyut hakkında

Sana gönderilen ZIP **kaynak koddur** (saf metin): 5.700+ satır Python ≈
300 KB'tır ve botun TÜM özellikleri bu koddadır. 60+ MB'lık botlar,
Python yorumlayıcısını ve kütüphaneleri **içine gömülü** tek EXE olarak
dağıtıldığı için büyüktür — kod fazla olduğundan değil. Aynısını istersen:
`EXE_OLUSTUR.bat`'a çift tıkla → `dist\TelegramKampanyaBotu.exe`
(~40-70 MB) üretilir. İçerik birebir aynıdır; sadece paketleme farkıdır.
Ayrıca kurulumda `pip install -r requirements.txt` zaten diske ~50 MB
kütüphane indirir — botun gerçek "toplam ağırlığı" budur.

---

## 12) YENİ: PANEL İÇİ YARDIM + HAZIR BİLGİ BANKASI

- **📖 YARDIM butonu:** Panelin altında artık "YARDIM — Nasıl Kullanılır?"
  butonu var. 11 konu başlığı (Nereden Başlarım, Kampanya, Duyuru, Bildirim,
  Zamanlı, Banner, Linkler, Segment, SSS, Asistan, Rapor Okuma) — her biri
  "bu buton ne yapar, basınca ne olur" dilinde, hiç bilmeyen biri için
  yazıldı. Telefondan bile okunur; hiçbir dosya açman gerekmez.
- **Hazır bilgi bankası:** İlk çalıştırmada SSS boşsa **15 hazır soru-cevap**
  otomatik yüklenir (çevrim şartı, çekim süresi, deneme bonusu, FreeSpin,
  kayıp bonusu, Site ID, şifre, doğrulama, Mini App, turnuva katılımı...).
  Hepsini panelden düzenleyebilir/silebilirsin; sildiklerin geri gelmez.
  Asistan, serbest soruları BU bankadan cevaplar — doldurdukça akıllanır.

---

## 13) SİTE ID İLE HEDEFLİ YÖNETİM (🆔) — yatırımcı üyeler için

Kullanım amacın: sitendeki üye ID'sini Telegram'a bağlayıp hedefli mesaj atmak.

**Üye tarafı (bağlama):** Üye botta 🤴 Profil → Site ID Değiştir'e dokunur,
sitedeki ID'sini yazar, Evet ile onaylar. (İstersen `config.txt` →
`SITE_ID_ON_START=1` yap: bota ilk giren herkesten açılışta Site ID istenir.)

**Senin tarafın:**
- **Kim bu ID?** → `/kim 12345` — o Site ID hangi Telegram hesabına bağlı,
  banlı mı, hangi segmentte, ne zaman bağlamış gösterir.
- **ID'ye tekil mesaj** → `/dmid 12345 Bonusun tanımlandı! 🎁` — Telegram
  ID'sini bilmene gerek yok; sitedeki ID yeter.
- **ID listesine grup atama** → `/siteseg platin 12345 67890 24680` —
  verdiğin Site ID'lere bağlı üyeleri tek komutla 💎 Platin yapar
  (altin/gumus/bronz da olur). Bota bağlı olmayan ID'leri raporlar.
- **Duyuru hedef seçmeli:** Duyuru → 📣 Gönder (hedef seç) →
  🌍 Herkes / 🆔 Site ID bağlı üyeler / 💎🥇🥈🥉 segmentler / 🆕 Yeni / 🕓 Aktif.
- **Toplu mesajda iki yeni hedef:** "🆔 Site ID bağlı üyeler" ve
  "🎯 Belirli Site ID listesi" — ID'leri yapıştırırsın, kaç üye eşleşti
  söyler, yalnız onlara gönderir; eşleşmeyenleri raporlar.
- **Dışa aktarım:** Site ID kayıtları `data/` klasöründe CSV+Excel olarak
  her değişiklikte güncel tutulur.

Örnek akış — "bu hafta yatıranlara özel bonus":
1. Sitenden yatıran üyelerin ID listesini al.
2. `/siteseg platin 111 222 333` (veya direkt 3. adımda 🎯 ID listesi seç)
3. `/bildirim` → Tam Paket → içerik → hedef: 💎 Platin.
4. Rapor: hedef + ulaşan + ulaşamayan (nedeniyle).

---

## 14) GÖNDERİM GEÇMİŞİ (📜) + DUYURU DÜZENLEME (✏️) + TEKRAR GÖNDER (🔁)

**Gönderim Geçmişi:** Panel → **📜 Gönderim Geçmişi** — son 10 toplu
gönderim (duyuru, toplu mesaj, zamanlı, şablon, tekrar) tek listede:
tür → ✅ ulaşan ❌ ulaşamayan (tarih). Bir kayda dokun:
- hedef, sayılar, tarih ve **içeriğin önizlemesi** görünür,
- **🔁 Aynı Hedefe Tekrar Gönder** ile aynı içeriği aynı kitleye bir tıkla
  yeniden yollarsın (çift tıklama korumalı; tekrar da geçmişe işlenir).
"Dün attığım duyuru neydi, kaça ulaştı?" sorusunun cevabı artık hep burada.

**Duyuru Düzenleme:** Panel → Duyurular → duyuruya dokun →
**✏️ Başlık / ✏️ Metin / 🖼 Medya** — silmeden değiştir; kullanıcının
listesinde ANINDA yeni haliyle görünür. Medyayı kaldırmak için medya
düzenlemede `/temizle` yaz.

---

## 15) EKRAN GÖRÜNTÜSÜ KAYDI (📸) — "attığı görsel, girdiği bilgilerle adlansın"

**Ne işe yarar:** Kullanıcı (ya da sen) bota bir ekran görüntüsü atınca bot **seçenek
sunar**; seçilen kategori, gönderilme tarihi ve kullanıcının yazdığı bilgiler dosyanın
**ADI** olur ve görsel `screenshots/` klasörüne kaydedilir. Klasörü açtığında hangi
görselin kimden, ne için ve hangi ID'lerle geldiğini dosya adından okursun.

**Yol 1 — önce fotoğraf (kullanıcı ne yapar):**
1. Bota ekran görüntüsünü atar.
2. Bot sorar: *"Bu ekran görüntüsü ne için?"* → 👥 Arkadaşını Getir / 💰 Para Yatırma /
   💸 Para Çekme / 🎁 Bonus Talebi / 📄 Diğer / ❌ Vazgeç.
3. Seçtiği kategoriye göre bilgiler sırayla sorulur: örn. **Site ID** → **Arkadaş ID**.
   (Profilinde kayıtlı Site ID varsa tek tuşla kullanır.)
4. Son bilgiyle birlikte görsel kaydedilir; kullanıcı dosya adını görür:
   `Arkadasini-Getir_2026-09-22_14-30-05_ABC123_XYZ789_123456789.jpg`
5. Sana anında **görsel + bilgiler + dosya adı** bildirimi düşer.

**Yol 2 — önce bilgiler, sonra fotoğraf:** kullanıcı `/ekran` yazar (veya ana menü /
alt klavyedeki 📸 tuşu) → kategori → bilgiler → *"Şimdi ekran görüntüsünü gönder"* →
fotoğraf gelir gelmez **doğrudan** kaydedilir, ek onay sorulmaz.

**Sen foto atınca:** admin oturumun açıksa ek bir seçenek görürsün: 🗂 Kampanya
Medyası Yap (eski davranış) ya da 📸 Ekran Görüntüsü Kaydet (aynı akış).

**Kayıtları görmek:**
- `/ekranlar` → son 30 kayıt (🔴 yeni, 🟡 okundu, 🟢 kapatıldı); `/ekranlar yeni`;
  `/ekranlar arkadas` (kategori anahtarı).
- `/ekranlar 12` → görselin kendisi + kategori + girilen bilgiler + dosya adı.
- `/ekrankapat 12` → kaydı kapat. `/ekrandosya` → tüm kayıtların CSV'si (Excel'de açılır).
- Panel → **📸 Ekran Görüntüleri** → Son Kayıtlar.

**Ayarlamak (Panel → 📸 Ekran Görüntüleri):**
- **Aktif Et / Pasif Yap** — kapalıyken kullanıcı fotoları eskisi gibi yanıtsız kalır.
- **🏷 Kategoriler** — hangi seçenekler çıksın, her seçenekte hangi bilgiler sorulsun:
  `arkadas:👥 Arkadaşını Getir:Site ID|Arkadaş ID, yatirim:💰 Para Yatırma:Site ID|Tutar`
  (virgül = yeni kategori, `|` = yeni bilgi). Bilgi istemeyen kategori: `diger:📄 Diğer`.
- **📝 Dosya Adı Şablonu** — varsayılan `{kategori}_{tarih}_{saat}_{alanlar}_{tgid}`.
  Yalnız ID'ler istersen: `{kategori}_{tarih}_{alanlar}`; alan adıyla: `{site_id}_{arkadas_id}_{tarih}`.
- **💬 Seçenek Mesajı** — kullanıcıya sorulan cümle.
- Aynı ayarlar `config.txt` içinde `SCREENSHOT_...` satırlarında da vardır (panel önceliklidir).

**Sorun giderme:**
| Belirti | Neden | Çözüm |
|---|---|---|
| Kullanıcı foto attı, seçenek çıkmadı | Özellik pasif ya da kullanıcı o an Site ID/şikayet akışında | Panel → 📸 Ekran Görüntüleri → Aktif Et; kullanıcı `/iptal` yazsın |
| "LİMİT" mesajı | Günlük kota doldu (`SCREENSHOT_DAILY_LIMIT`) | Kota sayısını artır veya yarını bekle |
| "KAYDEDİLEMEDİ" | Görsel indirilemedi (20 MB üstü veya Telegram hatası) | Kullanıcı fotoyu foto olarak (dosya değil) yeniden atsın; `bot.log` `[EKRAN]` satırı |
| Dosya adında Türkçe harf yok | Bilinçli: her işletim sisteminde açılsın diye ç→c, ş→s… | — |

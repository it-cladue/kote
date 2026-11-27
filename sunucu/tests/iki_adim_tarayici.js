/* 2.4.1: iki adımlı doğrulama uçtan uca tarayıcı senaryosu (tests/test_v241_iki_adim.py çalıştırır; Node + Playwright yoksa atlanır).
   Kurulum sayfasındaki anahtar sayfadan okunur, kod bu betikte aynı algoritmayla (RFC 6238, HMAC-SHA1) hesaplanır.
   Ortam: PANEL_URL, EKRAN_KLASORU (ekran görüntüleri; varsayılan /tmp/kanit-ekran/p241), EKRAN_KLASORU_242 (2.4.2 adımları;
   varsayılan /tmp/kanit-ekran/p242). Hesaplar: testadmin (sahip), okur (hesap ayarı yok = politikaya göre).
   2.4.2: politika 'kapali' iken formdan açılan hesap (kutu varsayılan işaretli) ilk girişte kuruluma zorlanır; sahip
   "Zorunlu değil" seçince bir sonraki istekte ana sayfa açılır. Kutu kaldırılarak açılan hesap zorunlu değildir. */
'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASORU || '/tmp/kanit-ekran/p241';
const EKRAN242 = process.env.EKRAN_KLASORU_242 || '/tmp/kanit-ekran/p242';
const SIFRE = 'Test-Password-123!';
fs.mkdirSync(EKRAN242, { recursive: true });

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function ekran(page, ad) { await page.screenshot({ path: path.join(EKRAN, ad + '.png'), fullPage: true }); }
async function ekran242(page, ad) { await page.screenshot({ path: path.join(EKRAN242, ad + '.png'), fullPage: true }); }

function base32(s) {
  const harfler = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bit = '';
  for (const ch of s.replace(/[\s=-]/g, '').toUpperCase()) bit += harfler.indexOf(ch).toString(2).padStart(5, '0');
  const bayt = [];
  for (let i = 0; i + 8 <= bit.length; i += 8) bayt.push(parseInt(bit.slice(i, i + 8), 2));
  return Buffer.from(bayt);
}
function hotp(anahtar, sayac) {
  const b = Buffer.alloc(8); b.writeBigUInt64BE(BigInt(sayac));
  const h = crypto.createHmac('sha1', anahtar).update(b).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, '0');
}
// Sunucu ±1 adım kabul eder ve aynı/eski sayacı reddeder: her kullanımda (son+1) ile (şimdi-1) arasından en büyüğü seçilir.
let sonSayac = 0;
async function kodUret(sir) {
  for (;;) {
    const simdi = Math.floor(Date.now() / 30000);
    const aday = Math.max(sonSayac + 1, simdi - 1);
    if (aday <= simdi + 1) { sonSayac = aday; return hotp(base32(sir), aday); }
    await new Promise((r) => setTimeout(r, 1000));
  }
}
async function telefonSigiyor(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}
// Konsol hataları da toplanır (CSP ihlali, başarısız istek). Bilerek hatalı gönderilen formların 400 yanıtı beklenir;
// o adımlarda beklenenHata açılır ve yalnız "Failed to load resource" iletisi hoş görülür.
const hatalar = [];
let beklenenHata = false;
function izle(page) {
  page.on('pageerror', (e) => hatalar.push(String(e)));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (beklenenHata && /Failed to load resource: the server responded with a status of 400/.test(m.text())) return;
    hatalar.push('konsol: ' + m.text() + ' @ ' + page.url());
  });
}
async function parolaGir(page, ad) {
  await page.goto(PANEL + '/giris');
  await page.fill('input[name="kullanici"]', ad);
  await page.fill('input[name="sifre"]', SIFRE);
  await Promise.all([page.waitForNavigation(), page.click('button[type="submit"]')]);
}
async function cikisYap(page) {
  await Promise.all([page.waitForNavigation(), page.click('.kullanici form button, .kilit-eylemler form button')]);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'tr-TR' });
  const page = await context.newPage();
  izle(page);
  page.on('dialog', (d) => d.accept());
  try {
    adim('parolayla giriş (iki adım kapalı) ve kurulum sayfası');
    await parolaGir(page, 'testadmin');
    dogrula((await page.textContent('a[data-iki-adim-menu].iki-adim-baglanti')).includes('2FA: kapalı'), 'başlıkta 2FA: kapalı');
    await page.goto(PANEL + '/profil/iki-adim');
    await ekran(page, '01-iki-adim-baslangic');
    await Promise.all([page.waitForNavigation(), page.click('#iki-adim-ac')]);
    dogrula(await page.isVisible('#qr-kodu svg.qr-svg'), 'QR SVG görünür');
    const qrYol = await page.getAttribute('#qr-kodu svg path', 'd');
    dogrula(qrYol && qrYol.length > 500, 'QR modülleri çizildi');
    const kutu = await page.$eval('#qr-kodu svg', (e) => { const r = e.getBoundingClientRect(); return [r.width, r.height]; });
    dogrula(kutu[0] >= 180 && Math.abs(kutu[0] - kutu[1]) < 1, 'QR kare ve okunur boyutta: ' + kutu);
    const sir = await page.getAttribute('#kurulum-anahtari', 'data-anahtar');
    dogrula(/^[A-Z2-7]{32}$/.test(sir), 'anahtar 32 karakter base32');
    const href = await page.getAttribute('#otpauth-baglanti', 'href');
    dogrula(href.startsWith('otpauth://totp/Kan%C4%B1t%20Paneli:testadmin?secret=' + sir + '&issuer='), 'otpauth bağlantısı');
    dogrula((await page.textContent('#kurulum-anahtari')).trim().split(' ').every((g) => g.length === 4), 'anahtar 4\'lü gruplar');
    dogrula(/\d\d:\d\d:\d\d/.test(await page.textContent('#sunucu-saati')), 'sunucu saati gösteriliyor');
    await ekran(page, '02-iki-adim-kurulum-qr');

    adim('telefon (390 px) ve koyu tema görünümü');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    dogrula(await telefonSigiyor(page), 'kurulum sayfası 390 px\'te yatay kaymıyor');
    await ekran(page, '03-iki-adim-kurulum-telefon');
    await page.evaluate(() => localStorage.setItem('kanit-panel-tema', 'dark'));
    await page.reload();
    dogrula((await page.getAttribute('html', 'data-theme')) === 'dark', 'koyu tema');
    dogrula(await page.$eval('#qr-kodu', (e) => getComputedStyle(e).backgroundColor) === 'rgb(255, 255, 255)', 'QR koyu temada beyaz zeminde');
    await ekran(page, '04-iki-adim-kurulum-telefon-koyu');
    await page.evaluate(() => localStorage.setItem('kanit-panel-tema', 'light'));
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.reload();

    adim('yanlış kod reddedilir, doğru kodla açılır, 8 kurtarma kodu bir kez');
    await page.fill('#etkinlestir-kod', '000000');
    beklenenHata = true;
    await Promise.all([page.waitForNavigation(), page.click('#etkinlestir-formu button')]);
    beklenenHata = false;
    dogrula((await page.textContent('#iki-adim-hata')).includes('Kod doğrulanamadı'), 'yanlış kod mesajı');
    await page.fill('#etkinlestir-kod', await kodUret(sir));
    await Promise.all([page.waitForNavigation(), page.click('#etkinlestir-formu button')]);
    const kurtarma = await page.$$eval('#kurtarma-kodlari li code', (l) => l.map((x) => x.textContent.trim()));
    dogrula(kurtarma.length === 8 && kurtarma.every((k) => /^[a-z0-9]{5}-[a-z0-9]{5}$/.test(k)), '8 kurtarma kodu');
    await ekran(page, '05-kurtarma-kodlari');
    await Promise.all([page.waitForNavigation(), page.click('#kurtarma-kodlari a.btn')]);
    dogrula((await page.getAttribute('#iki-adim-durum', 'data-durum')) === 'acik', 'durum açık');
    dogrula((await page.textContent('a[data-iki-adim-menu].iki-adim-baglanti')).includes('2FA: açık'), 'başlıkta 2FA: açık');
    dogrula(!(await page.$('#kurtarma-kodlari')), 'kodlar ikinci kez gösterilmez');

    adim('çıkış → parola → kod adımı (güvenilen cihaz işaretli) → panel');
    await cikisYap(page);
    await parolaGir(page, 'testadmin');
    dogrula(page.url().endsWith('/giris/dogrulama'), 'kod adımına yönlendi');
    dogrula(await page.isVisible('input[name="guven"]'), '"Bu cihazda 30 gün sorma" kutusu');
    await ekran(page, '06-giris-kod-adimi');
    const telefon = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'tr-TR', colorScheme: 'dark' });
    const tp = await telefon.newPage();
    izle(tp);
    await parolaGir(tp, 'testadmin');
    dogrula(tp.url().endsWith('/giris/dogrulama') && await telefonSigiyor(tp), 'telefonda kod adımı sığıyor');
    await ekran(tp, '07-giris-kod-adimi-telefon-koyu');
    adim('telefonda (390 px) kurtarma koduyla giriş: alan harf klavyesi açar');
    dogrula((await tp.getAttribute('#dogrulama-kodu', 'inputmode')) === 'text', 'kod alanı inputmode=text (kurtarma kodu harf içerir)');
    await tp.fill('#dogrulama-kodu', kurtarma[0]);
    await Promise.all([tp.waitForNavigation(), tp.click('#kod-formu button[type="submit"]')]);
    dogrula(new URL(tp.url()).pathname === '/', 'telefonda kurtarma koduyla girildi');
    dogrula((await tp.textContent('body')).includes('7 kod kaldı'), 'kalan kurtarma kodu bildirildi');
    await ekran(tp, '07b-kurtarma-koduyla-giris-telefon-koyu');
    await telefon.close();
    await page.goto(PANEL + '/');
    dogrula(page.url().includes('/giris'), 'kod girilmeden panel açılmaz');
    await parolaGir(page, 'testadmin');
    await page.fill('input[name="kod"]', await kodUret(sir));
    await page.check('input[name="guven"]');
    await Promise.all([page.waitForNavigation(), page.click('#kod-formu button[type="submit"]')]);
    dogrula(new URL(page.url()).pathname === '/', 'ana sayfa açıldı');
    const cerezler = await context.cookies();
    const cihaz = cerezler.find((c) => c.name === 'kanit_cihaz');
    dogrula(cihaz && cihaz.httpOnly && cihaz.expires > Date.now() / 1000 + 29 * 86400, 'güvenilen cihaz çerezi (HttpOnly, 30 gün)');

    adim('güvenilen cihaz: parolayla doğrudan giriş');
    await cikisYap(page);
    await parolaGir(page, 'testadmin');
    dogrula(new URL(page.url()).pathname === '/', 'kod sorulmadan girildi');

    adim('cihazı kaldır → kod yeniden istenir');
    await page.goto(PANEL + '/profil/iki-adim');
    dogrula((await page.$$('.cihaz-liste li')).length === 1, 'bir güvenilen cihaz listeleniyor');
    await ekran(page, '08-guvenilen-cihazlar');
    await Promise.all([page.waitForNavigation(), page.click('.cihaz-liste li form button')]);
    dogrula(await page.isVisible('#cihaz-yok'), 'cihaz listesi boş');
    await cikisYap(page);
    await parolaGir(page, 'testadmin');
    dogrula(page.url().endsWith('/giris/dogrulama'), 'kod yeniden soruldu');
    await page.fill('input[name="kod"]', await kodUret(sir));
    await Promise.all([page.waitForNavigation(), page.click('#kod-formu button[type="submit"]')]);
    dogrula(new URL(page.url()).pathname === '/', 'kodla girildi');

    adim('Çalışma ayarları: zorunlu kılma (herkes) ve Kullanıcılar sütunu');
    await page.goto(PANEL + '/yonetim/ayarlar#ayar-IKI_ADIM_ZORUNLU');
    await page.selectOption('#deger-IKI_ADIM_ZORUNLU', 'hepsi');
    await Promise.all([page.waitForNavigation(), page.click('#ayar-IKI_ADIM_ZORUNLU form.ay-form button')]);
    dogrula((await page.textContent('#ayar-IKI_ADIM_ZORUNLU [data-gecerli]')).includes('Herkes'), 'politika kaydedildi');
    await page.$eval('#ayar-IKI_ADIM_ZORUNLU', (e) => e.scrollIntoView());
    await page.screenshot({ path: path.join(EKRAN, '09-calisma-ayarlari-guvenlik.png') });
    await page.goto(PANEL + '/yonetim/kullanicilar');
    dogrula((await page.getAttribute('#kullanici-testadmin td.iki-adim-hucre', 'data-iki-adim')) === 'acik', 'testadmin: açık');
    dogrula((await page.getAttribute('#kullanici-okur td.iki-adim-hucre', 'data-iki-adim')) === 'zorunlu_bekliyor', 'okur: zorunlu-bekliyor');
    dogrula((await page.getAttribute('#kullanici-okur td.iki-adim-hucre [data-iki-adim-hesap]', 'data-iki-adim-hesap')) === 'politika', 'okur: hesap ayarı politikaya göre (2.4.2)');
    dogrula((await page.textContent('#iki-adim-bekleyen')).includes('okur'), 'henüz kurmayanlar listesi');
    await ekran(page, '10-kullanicilar-2fa-sutunu');
    adim('Kullanıcılar sayfası telefonda (390 px): 2FA durumu Durum hücresinde, tablo sığıyor');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    dogrula(!(await page.isVisible('#kullanici-testadmin td.iki-adim-hucre')), 'telefonda ayrı 2FA sütunu gizli');
    dogrula((await page.textContent('#kullanici-testadmin [data-iki-adim-telefon]')).includes('açık'), 'telefonda testadmin 2FA: açık');
    dogrula((await page.textContent('#kullanici-okur [data-iki-adim-telefon]')).includes('zorunlu, bekliyor'), 'telefonda okur 2FA: zorunlu, bekliyor');
    dogrula(await page.$eval('.kullanici-listesi .tablo-sarici', (e) => e.scrollWidth <= e.clientWidth + 1), 'kullanıcı tablosu 390 px\'te yana taşmıyor');
    const tekSatir = (e) => e.getBoundingClientRect().height < parseFloat(getComputedStyle(e).fontSize) * 2.2;
    for (const secici of ['#kullanici-testadmin [data-iki-adim-telefon] .durum-etiket', '#kullanici-testadmin td:nth-child(3) .durum-etiket', '#kullanici-testadmin .kullanici-satir-ad b', '#kullanici-testadmin .kullanici-satir-ad small']) {
      dogrula(await page.$eval(secici, tekSatir), 'tek satırda (kelime ortasından bölünmüyor): ' + secici);
    }
    dogrula(await page.$eval('.kullanici-listesi .tablo-sarici', (s) => [...s.querySelectorAll('[data-iki-adim-telefon] .durum-etiket')].every((e) => e.getBoundingClientRect().right <= s.getBoundingClientRect().right + 1)), '2FA etiketleri kesilmeden görünüyor');
    dogrula(await telefonSigiyor(page), 'kullanıcılar sayfası 390 px\'te yatay kaymıyor');
    await ekran(page, '10b-kullanicilar-2fa-telefon');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.reload();
    await page.click('td.islem-hucre button[data-ac="duzenle-testadmin"]');
    dogrula(await page.isVisible('#duzenle-testadmin [data-iki-adim-sifirla]'), 'sahip için sıfırlama formu');
    await page.$eval('#duzenle-testadmin [data-iki-adim-yonetim]', (e) => e.scrollIntoView());
    await page.screenshot({ path: path.join(EKRAN, '11-kullanicilar-2fa-sifirla.png') });

    adim('zorunlu ve kurmamış kullanıcı: yalnız kurulum sayfası (telefon)');
    const okurBaglam = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'tr-TR' });
    const op = await okurBaglam.newPage();
    izle(op);
    await parolaGir(op, 'okur');
    dogrula(op.url().endsWith('/profil/iki-adim'), 'kurulum sayfasına yönlendi');
    dogrula(await op.isVisible('#iki-adim-zorunlu') && !(await op.$('#ana-menu')), 'zorunlu açıklaması, menü yok');
    await op.goto(PANEL + '/kayitlar');
    dogrula(op.url().endsWith('/profil/iki-adim'), 'başka sayfa açılmıyor');
    dogrula(await telefonSigiyor(op), 'telefonda sığıyor');
    await ekran(op, '12-zorunlu-kurulum-telefon');
    await okurBaglam.close();

    adim('politikayı geri al (kapalı)');
    await page.goto(PANEL + '/yonetim/ayarlar');
    await page.selectOption('#deger-IKI_ADIM_ZORUNLU', 'kapali');
    await Promise.all([page.waitForNavigation(), page.click('#ayar-IKI_ADIM_ZORUNLU form.ay-form button')]);

    adim('2.4.2: politika kapalı; formdan yeni kullanıcı, 2FA kutusu varsayılan işaretli → zorunlu');
    await page.goto(PANEL + '/yonetim/kullanicilar#yeni-kullanici');
    dogrula(await page.isChecked('#yeni-kullanici input[name="iki_adim_zorunlu"]'), 'yeni kullanıcı formunda 2FA kutusu işaretli');
    dogrula((await page.textContent('#yeni-iki-adim-not')).includes('kaldırmak yalnız süperadmin ve sahibe açıktır'), 'kutunun altındaki açıklama');
    dogrula((await page.textContent('#kullanici-listesi-baslik + p')).includes('yeni hesaplar varsayılan olarak zorunlu; hesap ayarı politikadan önce gelir'), 'başlıkta 2.4.2 notu');
    await page.fill('#yeni-kullanici input[name="ad"]', 'yeni_kisi');
    await page.fill('#yeni-kullanici input[name="gorunen_ad"]', 'Yeni Kişi');
    await page.check('#yeni-kullanici input[name="projeler"][value="OF"]');
    await page.$eval('#yeni-kullanici', (e) => e.scrollIntoView());
    await page.screenshot({ path: path.join(EKRAN242, '01-yeni-kullanici-2fa-kutusu-isaretli.png') });
    await Promise.all([page.waitForNavigation(), page.click('#yeni-kullanici button.birincil')]);
    const geciciSifre = (await page.textContent('#gecici-sifre-deger')).trim();
    dogrula(geciciSifre.length >= 12, 'geçici şifre gösterildi');
    dogrula((await page.getAttribute('#kullanici-yeni_kisi td.iki-adim-hucre', 'data-iki-adim')) === 'zorunlu_bekliyor', 'yeni_kisi: zorunlu, bekliyor');
    dogrula((await page.getAttribute('#kullanici-yeni_kisi td.iki-adim-hucre [data-iki-adim-hesap]', 'data-iki-adim-hesap')) === 'zorunlu', 'yeni_kisi: hesap ayarı zorunlu');
    dogrula((await page.textContent('#kullanici-yeni_kisi td.iki-adim-hucre')).includes('hesap ayarı: zorunlu'), 'hesap ayarı notu');
    dogrula((await page.getAttribute('#kullanici-okur td.iki-adim-hucre', 'data-iki-adim')) === 'yok', 'okur (politikaya göre) kapalı politikada: yok');
    dogrula((await page.textContent('#iki-adim-bekleyen')).includes('yeni_kisi'), 'yeni_kisi "Henüz kurmayan" listesinde');
    await ekran242(page, '02-kullanicilar-hesap-ayari-zorunlu');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    dogrula((await page.textContent('#kullanici-yeni_kisi [data-iki-adim-telefon]')).includes('zorunlu, bekliyor'), 'telefonda: zorunlu, bekliyor');
    dogrula((await page.textContent('#kullanici-yeni_kisi [data-iki-adim-telefon]')).includes('hesap ayarı: zorunlu'), 'telefonda hesap ayarı notu');
    dogrula(await telefonSigiyor(page), 'kullanıcılar sayfası 390 px\'te yatay kaymıyor (2.4.2)');
    await ekran242(page, '03-kullanicilar-hesap-ayari-telefon');
    await page.setViewportSize({ width: 1280, height: 900 });

    adim('2.4.2: yeni kullanıcı geçici şifreyle girer → şifre değiştirir → zorunlu kurulum sayfası');
    const yeniBaglam = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'tr-TR' });
    const yp = await yeniBaglam.newPage();
    izle(yp);
    await yp.goto(PANEL + '/giris');
    await yp.fill('input[name="kullanici"]', 'yeni_kisi');
    await yp.fill('input[name="sifre"]', geciciSifre);
    await Promise.all([yp.waitForNavigation(), yp.click('button[type="submit"]')]);
    if (!yp.url().endsWith('/sifre')) await yp.goto(PANEL + '/');
    dogrula(yp.url().endsWith('/sifre'), 'ilk girişte şifre değiştirme sayfası: ' + yp.url());
    await yp.fill('#sifre-eski', geciciSifre);
    await yp.fill('#sifre-yeni', 'Yeni-Kisi-Parola-42!');
    await yp.fill('#sifre-yeni2', 'Yeni-Kisi-Parola-42!');
    await Promise.all([yp.waitForNavigation(), yp.click('form:has(#sifre-yeni) button[type="submit"]')]);
    await yp.goto(PANEL + '/kayitlar');
    dogrula(yp.url().endsWith('/profil/iki-adim'), 'şifre değişince yalnız kurulum sayfası: ' + yp.url());
    dogrula(await yp.isVisible('#iki-adim-zorunlu') && !(await yp.$('#ana-menu')), 'zorunlu açıklaması, menü yok');
    dogrula(await telefonSigiyor(yp), 'kurulum sayfası telefonda sığıyor');
    await ekran242(yp, '04-yeni-kullanici-zorunlu-kurulum-telefon');

    adim('2.4.2: sahip "Zorunlu değil" seçer → yeni_kisi bir sonraki istekte ana sayfayı açar');
    await page.goto(PANEL + '/yonetim/kullanicilar');
    await page.click('td.islem-hucre button[data-ac="duzenle-yeni_kisi"]');
    const secici = '#duzenle-yeni_kisi form[data-iki-adim-zorunluluk] select[name="iki_adim_zorunlu"]';
    dogrula((await page.$eval(secici, (e) => e.value)) === '1', 'zorunluluk formunda "Zorunlu" seçili');
    dogrula((await page.textContent(secici + ' option[value="politika"]')).includes('Politikaya göre (şu an: isteğe bağlı)'), 'politika seçeneği metni');
    await page.selectOption(secici, '0');
    await page.$eval(secici, (e) => e.scrollIntoView({ block: 'center' }));
    await page.screenshot({ path: path.join(EKRAN242, '05-zorunlulugu-kaldir.png') });
    await Promise.all([page.waitForNavigation(), page.click('#duzenle-yeni_kisi form[data-iki-adim-zorunluluk] button')]);
    dogrula((await page.getAttribute('#kullanici-yeni_kisi td.iki-adim-hucre', 'data-iki-adim')) === 'yok', 'yeni_kisi: yok');
    dogrula((await page.getAttribute('#kullanici-yeni_kisi td.iki-adim-hucre [data-iki-adim-hesap]', 'data-iki-adim-hesap')) === 'degil', 'yeni_kisi: hesap ayarı zorunlu değil');
    const bekleyen = await page.$('#iki-adim-bekleyen');
    dogrula(!bekleyen || !(await bekleyen.textContent()).includes('yeni_kisi'), 'yeni_kisi "Henüz kurmayan" listesinden çıktı');
    await ekran242(page, '06-kullanicilar-zorunlu-degil');
    await yp.goto(PANEL + '/');
    dogrula(new URL(yp.url()).pathname === '/', 'açık oturum bir sonraki istekte ana sayfayı açtı: ' + yp.url());
    dogrula(!(await yp.$('#iki-adim-zorunlu')) && (await yp.$('#ana-menu')) !== null, 'menü var, zorunlu kurulum uyarısı yok');
    await ekran242(yp, '07-zorunlu-degil-ana-sayfa-telefon');
    await yeniBaglam.close();

    adim('2.4.2: kutu kaldırılarak açılan hesap: yok + hesap ayarı zorunlu değil');
    await page.goto(PANEL + '/yonetim/kullanicilar#yeni-kullanici');
    await page.fill('#yeni-kullanici input[name="ad"]', 'serbest_kisi');
    await page.check('#yeni-kullanici input[name="projeler"][value="OF"]');
    await page.uncheck('#yeni-kullanici input[name="iki_adim_zorunlu"]');
    await Promise.all([page.waitForNavigation(), page.click('#yeni-kullanici button.birincil')]);
    dogrula((await page.getAttribute('#kullanici-serbest_kisi td.iki-adim-hucre', 'data-iki-adim')) === 'yok', 'serbest_kisi: yok');
    dogrula((await page.getAttribute('#kullanici-serbest_kisi td.iki-adim-hucre [data-iki-adim-hesap]', 'data-iki-adim-hesap')) === 'degil', 'serbest_kisi: hesap ayarı zorunlu değil');
    dogrula((await page.textContent('#kullanici-serbest_kisi td.iki-adim-hucre')).includes('hesap ayarı: zorunlu değil'), 'serbest_kisi notu');
    await ekran242(page, '08-kutusuz-hesap');

    dogrula(hatalar.length === 0, 'sayfa ya da konsol hatası yok: ' + hatalar.join(' | '));
    process.stdout.write('TAMAM\n');
  } catch (e) {
    try { await ekran(page, 'hata'); } catch (_) {}
    process.stdout.write('HATA ' + (e && e.stack || e) + '\nURL ' + page.url() + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

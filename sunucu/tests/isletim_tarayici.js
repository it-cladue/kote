/* 2.4.0 (B2): Sistem durumu kartı, Çalışma ayarları ve Yedekler sayfası için tarayıcı senaryosu
   (tests/test_v240_isletim.py çalıştırır; Node + Playwright yoksa atlanır).
   Ortam: PANEL_URL (waitress), EKRAN_KLASORU (isteğe bağlı: ekran görüntüleri buraya yazılır). */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASORU || '';
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function ekran(page, ad, secici) {
  if (!EKRAN) return;
  const hedef = path.join(EKRAN, ad + '.png');
  if (secici) await page.locator(secici).screenshot({ path: hedef });
  else await page.screenshot({ path: hedef, fullPage: true });
  process.stdout.write('EKRAN ' + hedef + '\n');
}
async function yatayTasma(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  page.on('dialog', (d) => d.accept());
  try {
    adim('giriş');
    await page.goto(PANEL + '/giris');
    await page.fill('#giris-kullanici', 'testadmin');
    await page.fill('#giris-sifre', SIFRE);
    await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);

    adim('ana sayfa: Sistem durumu kartı');
    const kart = page.locator('#sistem-durumu');
    await kart.waitFor();
    dogrula(await kart.isVisible(), 'kart görünmeli');
    const satirlar = await page.locator('#sistem-durumu .sd-satir').count();
    dogrula(satirlar === 8, '8 satır beklenirdi: ' + satirlar);
    const yedekRenk = await page.locator('[data-sd-kod="yedek"]').getAttribute('data-sd-renk');
    dogrula(yedekRenk === 'kirmizi', 'yalnız panel yedeği var, gece yedeği yok: son yedek kırmızı kalmalı: ' + yedekRenk);
    const yedekMetin = await page.locator('[data-sd-kod="yedek"]').innerText();
    dogrula(yedekMetin.includes('panelden alınan') && yedekMetin.includes('setup-backup.sh'), 'panel yedeği ek bilgi + kurulum komutu: ' + yedekMetin);
    const webMetin = await page.locator('[data-sd-kod="web"]').innerText();
    dogrula(webMetin.includes('çalışma süresi') && !webMetin.includes("'dır"), 'web satırı: ' + webMetin);
    const botRenk = await page.locator('[data-sd-kod="bot"]').getAttribute('data-sd-renk');
    dogrula(botRenk === 'kirmizi', 'bot sinyali yok: kırmızı: ' + botRenk);
    const kenar = await page.locator('[data-sd-kod="bot"]').evaluate((e) => getComputedStyle(e).borderLeftColor);
    const yesilKenar = await page.locator('[data-sd-kod="web"]').evaluate((e) => getComputedStyle(e).borderLeftColor);
    dogrula(kenar !== yesilKenar, 'kırmızı ve yeşil satırların renkleri farklı olmalı');
    dogrula(await page.locator('[data-sd-kod="bot"] .sd-komut code').innerText().then((t) => t.includes('kanit-bot')), 'kırmızı satırda komut');
    dogrula(await page.locator('[data-sd-kod="web"] .sd-komut').count() === 0, 'yeşil satırda komut yok');
    await kart.scrollIntoViewIfNeeded();
    await ekran(page, 'sistem-durumu-karti', '#sistem-durumu');

    adim('Sistem bildirimi: proje rozeti yok, düğme "Sistem durumunu aç"');
    await page.click('#zil');
    const zilSatir = page.locator('#bildirim-liste li', { hasText: 'Sistem' }).first();
    await zilSatir.waitFor();
    dogrula(await zilSatir.locator('.rozet').count() === 0, 'zilde Sistem bildiriminde proje rozeti olmamalı');
    dogrula((await zilSatir.innerText()).includes('Sistem durumunu aç'), 'zil düğmesi: ' + await zilSatir.innerText());
    await page.click('#zil');
    await page.goto(PANEL + '/bildirimler?tur=sistem');
    const bSatir = page.locator('article.bildirim-satir').first();
    dogrula(await bSatir.locator('.rozet').count() === 0, 'Bildirimler sayfasında proje rozeti olmamalı');
    dogrula((await bSatir.innerText()).includes('Sistem durumunu aç') && !(await bSatir.innerText()).includes('Bekleyenleri aç'), 'sayfa düğmesi');
    await page.goto(PANEL + '/');

    adim('çalışma ayarları: hatalı değer → Türkçe hata, alan işaretli');
    await page.click('#sistem-durumu a:has-text("Çalışma ayarları")');
    await page.waitForURL(/\/yonetim\/ayarlar/);
    dogrula((await page.locator('h2').allInnerTexts()).join('|').includes('Hatırlatmalar'), 'grup başlıkları');
    await page.fill('#deger-BEKLEYEN_OZET_PENCERE', '20:00-08:00');
    await Promise.all([page.waitForLoadState('load'), page.click('#ayar-BEKLEYEN_OZET_PENCERE button:has-text("Kaydet")')]);
    const hata = await page.locator('#hata-BEKLEYEN_OZET_PENCERE').innerText();
    dogrula(hata.includes('başlangıç bitişten önce'), 'hata metni: ' + hata);
    dogrula(await page.locator('#deger-BEKLEYEN_OZET_PENCERE').getAttribute('aria-invalid') === 'true', 'aria-invalid');
    dogrula(await page.locator('#deger-BEKLEYEN_OZET_PENCERE').inputValue() === '20:00-08:00', 'girilen değer korunmalı');
    await page.locator('#ayar-BEKLEYEN_OZET_PENCERE').scrollIntoViewIfNeeded();
    await ekran(page, 'ayarlar-hata', '#ayar-BEKLEYEN_OZET_PENCERE');

    adim('geçerli değer → DB kaynağı, Varsayılana dön');
    await page.fill('#deger-BEKLEYEN_OZET_PENCERE', '9-18');
    await Promise.all([page.waitForURL(/#ayar-BEKLEYEN_OZET_PENCERE/), page.click('#ayar-BEKLEYEN_OZET_PENCERE button:has-text("Kaydet")')]);
    const satir = page.locator('#ayar-BEKLEYEN_OZET_PENCERE');
    dogrula(await satir.getAttribute('data-kaynak') === 'DB', 'kaynak DB olmalı');
    dogrula((await satir.locator('[data-gecerli]').innerText()) === '09:00-18:00', 'kanonik değer');
    dogrula((await page.locator('.bilgi-serit').innerText()).includes('Kaydedildi'), 'bilgi şeridi');
    await page.selectOption('#deger-API_ACIK', '0');
    await Promise.all([page.waitForURL(/#ayar-API_ACIK/), page.click('#ayar-API_ACIK button:has-text("Kaydet")')]);
    dogrula((await page.locator('.bilgi-serit').innerText()).includes('= Kapalı'), 'evet/hayır alanı metinle: ' + await page.locator('.bilgi-serit').innerText());
    await page.selectOption('#deger-API_ACIK', '1');
    await Promise.all([page.waitForURL(/#ayar-API_ACIK/), page.click('#ayar-API_ACIK button:has-text("Kaydet")')]);
    await page.selectOption('#deger-ONAYSIZ_GORUNUM', 'gizle');
    await Promise.all([page.waitForURL(/#ayar-ONAYSIZ_GORUNUM/), page.click('#ayar-ONAYSIZ_GORUNUM button:has-text("Kaydet")')]);
    await page.locator('#ayar-BEKLEYEN_OZET_PENCERE').scrollIntoViewIfNeeded();
    await ekran(page, 'ayarlar-sayfasi');
    await Promise.all([page.waitForLoadState('load'), page.click('#ayar-BEKLEYEN_OZET_PENCERE button:has-text("Varsayılana dön")')]);
    dogrula(await page.locator('#ayar-BEKLEYEN_OZET_PENCERE').getAttribute('data-kaynak') !== 'DB', 'varsayılana dönmeli');

    adim('yedekler: düğme → yeni yedek listede, komut kopyalanabilir');
    await page.goto(PANEL + '/yonetim/yedekler');
    const once = await page.locator('tr[data-yedek]').count();
    await page.waitForTimeout(1100);
    await Promise.all([page.waitForLoadState('load'), page.click('button:has-text("Yedek al (geri yüklenebilir)")')]);
    dogrula((await page.locator('.bilgi-serit').innerText()).includes('Yedek alındı'), 'yedek mesajı');
    dogrula((await page.locator('tr[data-yedek]').count()) === once + 1, 'listeye bir yedek eklenmeli');
    await ekran(page, 'yedekler-sayfasi');

    adim('telefon genişliği: yatay taşma yok');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(PANEL + '/');
    await page.locator('#sistem-durumu').scrollIntoViewIfNeeded();
    dogrula((await yatayTasma(page)) <= 1, 'ana sayfa yatay taşmamalı');
    await ekran(page, 'sistem-durumu-telefon', '#sistem-durumu');
    await page.goto(PANEL + '/yonetim/ayarlar');
    dogrula((await yatayTasma(page)) <= 1, 'ayarlar sayfası yatay taşmamalı');
    await page.goto(PANEL + '/yonetim/yedekler');
    dogrula((await yatayTasma(page)) <= 1, 'yedekler sayfası yatay taşmamalı');
    const kutu = await page.locator('.yd-tablo').first().evaluate((e) => e.scrollWidth - e.clientWidth);
    dogrula(kutu <= 1, 'telefonda yedek tablosu yan kaydırma istememeli: ' + kutu);
    dogrula(await page.locator('tr[data-yedek] .komut-kutu').first().isVisible(), 'geri yükleme komutu görünür');
    await ekran(page, 'yedekler-telefon');

    adim('koyu tema');
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(PANEL + '/');
    await page.locator('#sistem-durumu').scrollIntoViewIfNeeded();
    await ekran(page, 'sistem-durumu-koyu', '#sistem-durumu');

    dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

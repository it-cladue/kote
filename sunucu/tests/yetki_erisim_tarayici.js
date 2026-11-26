/* 2.4.0 (B1): sahip / yazılı onay / erişim sınırı / İşlem Geçmişi araması için uçtan uca tarayıcı senaryosu
   (tests/test_v240_yetki_erisim.py çalıştırır; Node + Playwright yoksa atlanır).
   Ortam: PANEL_URL (waitress, güvenilen vekil 127.0.0.1 — X-Forwarded-For başlığı gerçek adres sayılır), EKRAN_KLASORU (ekran görüntüleri). */
'use strict';
const path = require('path');
const { chromium } = require('playwright');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASORU || '.';
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function ekran(page, ad) { await page.screenshot({ path: path.join(EKRAN, ad + '.png'), fullPage: true }); }

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: 'tr-TR' });
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  page.on('dialog', (d) => d.accept());
  try {
    adim('giriş (süperadmin, henüz sahip yok)');
    await page.goto(PANEL + '/giris');
    await page.fill('input[name="kullanici"]', 'testadmin');
    await page.fill('input[name="sifre"]', SIFRE);
    await Promise.all([page.waitForNavigation(), page.click('button[type="submit"], form button')]);
    dogrula((await page.getAttribute('.kullanici .kullanici-rol', 'data-rol')) === 'Süperadmin', 'başlık rolü Süperadmin');
    dogrula(!(await page.$('a[href="/yonetim/api-anahtarlari"]')), 'süperadmin menüsünde API anahtarları yok');

    adim('ilk sahip ataması: yanlış ad tarayıcıda durdurulur, doğru adla atanır');
    await page.goto(PANEL + '/yonetim/kullanicilar');
    dogrula(await page.isVisible('#sahip-ata'), 'sahip atama kartı görünür');
    await ekran(page, '01-kullanicilar-sahip-ata');
    await page.fill('#sahip-ata input[name="onay"]', 'baskasi');
    await page.click('#sahip-ata button');
    await page.waitForTimeout(300);
    dogrula(page.url().endsWith('/yonetim/kullanicilar') && await page.isVisible('#sahip-ata'), 'yanlış onayla gönderilmedi');
    await page.fill('#sahip-ata input[name="onay"]', 'testadmin');
    await Promise.all([page.waitForNavigation(), page.click('#sahip-ata button')]);
    dogrula((await page.textContent('.bilgi-serit')).includes('artık sahip'), 'sahip atandı mesajı');
    dogrula((await page.getAttribute('.kullanici .kullanici-rol', 'data-rol')) === 'Sahip', 'başlık rolü Sahip');
    dogrula(!!(await page.$('a[href="/yonetim/erisim"]')), 'sahip menüsünde Erişim sınırı var');

    adim('proje kullanıcısını süperadmin yapma: onay alanı açılır, boşken gönderilmez, adla kaydedilir');
    await page.click('td.islem-hucre button[data-ac="duzenle-okur"]');
    const form = '#duzenle-okur form[data-kullanici-form]';
    dogrula(await page.isHidden(form + ' [data-onay-alani]'), 'onay alanı başta gizli');
    await page.check(form + ' input[name="rol"][value="superadmin"]');
    dogrula(await page.isVisible(form + ' [data-onay-alani]'), 'onay alanı açıldı');
    dogrula((await page.textContent(form + ' [data-onay-neden]')).includes('Proje kullanıcısı → Süperadmin'), 'gerekçe metni');
    await ekran(page, '02-kullanicilar-onay-alani');
    await page.click(form + ' button.birincil');
    await page.waitForTimeout(300);
    dogrula(await page.isVisible(form), 'onaysız gönderilmedi');
    await page.fill(form + ' input[name="onay"]', 'okur');
    await Promise.all([page.waitForNavigation(), page.click(form + ' button.birincil')]);
    dogrula((await page.textContent('.bilgi-serit')).includes('kaydedildi'), 'kaydedildi mesajı');
    dogrula((await page.textContent('#kullanici-okur')).includes('Süperadmin'), 'okur artık süperadmin');

    adim('erişim sınırı sayfası: şu anki adres, Ekle, kaydet');
    await page.goto(PANEL + '/yonetim/erisim');
    dogrula((await page.textContent('#su-anki-ip')).trim() === '127.0.0.1', 'şu anki adres');
    await page.click('button[data-hedef="erisim-panel"]');
    dogrula((await page.inputValue('#erisim-panel')).includes('127.0.0.1'), 'Ekle kutuya yazdı');
    await page.fill('#erisim-panel', (await page.inputValue('#erisim-panel')) + '\n85.0.0.0/8');
    await page.fill('#erisim-api', '203.0.113.0/24');
    await ekran(page, '03-erisim-siniri-form');
    await Promise.all([page.waitForNavigation(), page.click('form[data-erisim-form] button.birincil')]);
    dogrula((await page.textContent('.bilgi-serit')).includes('Erişim sınırı kaydedildi'), 'kaydedildi');
    dogrula((await page.inputValue('#erisim-panel')) === '127.0.0.1\n85.0.0.0/8', 'kanonik liste');

    adim('izinsiz adresten (X-Forwarded-For 9.9.9.9) giriş sayfası 403, izinli adresten (85.1.2.3) açık');
    const disari = await browser.newContext({ locale: 'tr-TR', extraHTTPHeaders: { 'X-Forwarded-For': '9.9.9.9' } });
    const p2 = await disari.newPage();
    const r2 = await p2.goto(PANEL + '/giris');
    dogrula(r2.status() === 403 && (await p2.textContent('h1')).includes('IP: 9.9.9.9'), '403 sayfası');
    await ekran(p2, '04-erisim-engeli-403');
    await disari.close();
    const ofis = await browser.newContext({ locale: 'tr-TR', extraHTTPHeaders: { 'X-Forwarded-For': '85.1.2.3' } });
    const p3 = await ofis.newPage();
    dogrula((await p3.goto(PANEL + '/giris')).status() === 200, 'izinli adres açık');
    await ofis.close();

    adim('İşlem Geçmişi: serbest arama, IP sütunu, okunur rol ayrıntısı, Ham, hızlı tarih, CSV');
    await page.goto(PANEL + '/denetim');
    await page.fill('#denetim-ara', 'okur');
    await Promise.all([page.waitForNavigation(), page.click('form.filtre button.birincil')]);
    const tablo = await page.textContent('table.denetim-tablo');
    dogrula(tablo.includes('Rol: OF: oku, gorsel → Süperadmin'), 'okunur rol satırı: ' + tablo.slice(0, 400));
    dogrula(await page.isVisible('th:has-text("IP")'), 'IP sütunu');
    dogrula(!!(await page.$('details.denetim-ham summary')), 'Ham düğmesi');
    await page.click('details.denetim-ham summary');
    await ekran(page, '05-islem-gecmisi-arama');
    await Promise.all([page.waitForNavigation(), page.click('.hizli-tarih a:has-text("Bugün")')]);
    dogrula(page.url().includes('tarih1=') && page.url().includes('q=okur'), 'hızlı tarih filtreyi korur');
    const csvHref = await page.getAttribute('a[data-denetim-csv]', 'href');
    dogrula(csvHref.startsWith('/denetim.csv?') && csvHref.includes('q=okur'), 'CSV bağlantısı filtreli');
    const csv = await page.request.get(PANEL + csvHref);
    const govde = await csv.text();
    dogrula(csv.status() === 200 && govde.charCodeAt(0) === 0xfeff && govde.includes(';'), 'CSV BOM + ;');
    await page.fill('#denetim-ara', 'erisim');
    await Promise.all([page.waitForNavigation(), page.click('form.filtre button.birincil')]);
    dogrula((await page.textContent('table.denetim-tablo')).includes('Erişim engeli (IP)'), 'erişim engeli satırı');

    adim('telefon genişliği: kullanıcılar ve erişim sayfası yatay kaydırma yapmaz');
    await page.setViewportSize({ width: 390, height: 844 });
    for (const yol of ['/yonetim/erisim', '/yonetim/kullanicilar', '/denetim']) {
      await page.goto(PANEL + yol);
      const tasma = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      dogrula(tasma <= 2, yol + ' yatay taşma ' + tasma);
    }
    await page.goto(PANEL + '/yonetim/erisim');
    await ekran(page, '06-erisim-telefon');
    dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    try { await ekran(page, 'hata'); } catch (_) { /* yok */ }
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

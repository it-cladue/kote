/* 2.3.7: personel raporunda "Durumlar" bölümü için tarayıcı senaryosu.
   tests/test_rapor_durumlar_237.py tarafından çalıştırılır (Node + Playwright yoksa test atlanır).
   Ortam: PANEL_URL (waitress), EKRAN_KLASOR (ekran görüntüleri). */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASOR || '';
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function ekran(page, ad, secici) {
  if (!EKRAN) return;
  const dosya = path.join(EKRAN, ad + '.png');
  if (secici) {
    await page.addStyleTag({ content: '.ust{position:static !important}' });
    await page.locator(secici).first().screenshot({ path: dosya });
  } else await page.screenshot({ path: dosya, fullPage: true });
  process.stdout.write('EKRAN ' + dosya + '\n');
}
async function tasmaYok(page, ad) {
  const t = await page.evaluate(() => ({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth }));
  dogrula(t.s <= t.c + 1, ad + ': yatay taşma ' + t.s + ' > ' + t.c);
}
async function oturum(browser, ayar) {
  const context = await browser.newContext(Object.assign({ deviceScaleFactor: 1, locale: 'tr-TR' }, ayar.context));
  await context.addInitScript((tema) => {
    try { localStorage.setItem('kanit-panel-tema', tema); } catch (_) {}
    window.KP_YOKLAMA_MS = 600000;
  }, ayar.tema || 'light');
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  await page.goto(PANEL + '/giris');
  await page.fill('#giris-kullanici', 'testadmin');
  await page.fill('#giris-sifre', SIFRE);
  await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);
  return { context, page, hatalar };
}
async function rozet(page, kod) {
  const el = page.locator('.po-durum-' + kod + ' .po-rozet');
  return (await el.count()) ? +(await el.textContent()) : 0;
}
const ALTI = '.po-durum-ortalama_alti';
// #durumlar atlamasından sonra bölümün başlığı ve eşik düğmeleri yapışkan üst çubuğun altında kalmamalı.
async function basinAltinda(page, ne) {
  await page.waitForTimeout(150);
  const o = await page.evaluate(() => {
    const ust = document.querySelector('.ust').getBoundingClientRect().bottom;
    const b = document.getElementById('durumlar');
    const h2 = b.querySelector('h2'), esik = b.querySelector('.po-esik');
    return { ust, bolum: b.getBoundingClientRect().top, h2: h2 ? h2.getBoundingClientRect().top : null, esik: esik ? esik.getBoundingClientRect().top : null };
  });
  dogrula(o.bolum >= o.ust - 1 && (o.h2 === null || o.h2 >= o.ust) && (o.esik === null || o.esik >= o.ust), ne + ': Durumlar üst çubuğun altında kaldı ' + JSON.stringify(o));
}

async function masaustu(browser) {
  adim('masaustu');
  const { context, page, hatalar } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 } } });
  // Ana sayfa: tek satırlık özet ve rapora bağlantı.
  const ozet = page.locator('[data-po-durum-ozet]');
  dogrula(await ozet.isVisible(), 'ana sayfada Durumlar satırı yok');
  const ozetMetin = (await ozet.textContent()).replace(/\s+/g, ' ');
  dogrula(/Durumlar: \d+ kişi ortalamanın altında/.test(ozetMetin), 'özet metni: ' + ozetMetin);
  await ekran(page, 'ana-ozet-satiri', '#personel-ozet');
  await Promise.all([page.waitForURL(/\/rapor\/personel\?.*#durumlar$/), ozet.locator('a').click()]);
  const bolum = page.locator('#durumlar');
  dogrula(await bolum.isVisible(), 'Durumlar bölümü görünmüyor');
  const ust = await page.evaluate(() => Math.round(document.getElementById('durumlar').getBoundingClientRect().top));
  dogrula(ust < 200, '#durumlar adrese kaydırılmadı: ' + ust);
  await basinAltinda(page, 'ana sayfa bağlantısı');
  // Yerleşim: özet çipleri → Durumlar → kişi kartları.
  const sira = await page.evaluate(() => ['.po-ozet', '#durumlar', '#po-kartlar'].map((s) => document.querySelector(s).getBoundingClientRect().top));
  dogrula(sira[0] < sira[1] && sira[1] < sira[2], 'sıra yanlış: ' + sira);
  const gruplar = await page.locator('[data-po-durum-grup]').count();
  dogrula(gruplar >= 4, 'grup sayısı az: ' + gruplar);
  const n50 = await rozet(page, 'ortalama_alti');
  dogrula(n50 > 8, 'ortalamanın altında satırı 8\'den az: ' + n50);
  dogrula(await page.locator(ALTI + ' [data-po-durum-oge]:visible').count() === 8, 'ilk 8 satır görünmüyor');
  const ilkMetin = (await page.locator(ALTI + ' [data-po-durum-oge] a').first().textContent()).replace(/\s+/g, ' ').trim();
  process.stdout.write('ILK ' + ilkMetin + '\n');
  dogrula(/^\S.*(kategorisinde ortalamanın yarısından az kayıt ekledi|toplamda ortalamanın yarısından az kayıt ekledi) \(\d+ \/ ort\. \d+,\d · %\d+\)$/.test(ilkMetin), 'cümle biçimi: ' + ilkMetin);
  await page.evaluate(() => window.scrollTo(0, 0));
  await ekran(page, 'acik-1280-durumlar', '#durumlar');
  // "Daha fazla göster": hepsi açılır, odak 9. satırda; "Daha az göster" 8'e döner (sayfa yenilenmez).
  const fazla = page.locator(ALTI + ' [data-po-durum-fazla]'), az = page.locator(ALTI + ' [data-po-durum-az]');
  dogrula((await fazla.textContent()).trim() === 'Daha fazla göster (' + (n50 - 8) + ' satır daha)', 'düğme: ' + await fazla.textContent());
  await fazla.focus();
  await page.keyboard.press('Enter');
  dogrula(await page.locator(ALTI + ' [data-po-durum-oge]:visible').count() === n50, 'hepsi açılmadı');
  dogrula(await fazla.isHidden() && await az.isVisible(), 'düğmeler yer değiştirmedi');
  const odak = await page.evaluate((s) => { const a = document.activeElement, li = a && a.closest('[data-po-durum-oge]'); return li ? [...document.querySelectorAll(s + ' [data-po-durum-oge]')].indexOf(li) : -1; }, ALTI);
  dogrula(odak === 8, 'odak 9. satırda değil: ' + odak);
  await az.click();
  dogrula(await page.locator(ALTI + ' [data-po-durum-oge]:visible').count() === 8, 'daha az 8\'e dönmedi');
  // Satır bağlantısı: Kayıtlar listesi açılır, sayı cümledeki ilk sayıyla aynı (sıfır değilse).
  const hucre = page.locator(ALTI + ' [data-po-durum-oge] a[href*="kategori="]').first();
  const hucreMetin = await hucre.textContent();
  const beklenen = +hucreMetin.match(/\((\d+) \//)[1];
  await Promise.all([page.waitForURL(/\/kayitlar\?/), hucre.click()]);
  const bulunan = +(await page.locator('.sonuc-ozeti b').first().textContent());
  dogrula(bulunan === beklenen, 'bağlantı ' + bulunan + ' kayıt açtı, beklenen ' + beklenen);
  await page.goBack();
  // Eşik %75: fare ile; adres esik=75 ve #durumlar, satır sayısı artar ya da aynı kalır.
  await Promise.all([page.waitForURL(/esik=75.*#durumlar$/), page.locator('#durumlar .po-esik label:has-text("%75")').click()]);
  await basinAltinda(page, 'eşik %75');
  const n75 = await rozet(page, 'ortalama_alti');
  dogrula(n75 >= n50 && await page.locator('input[name=esik][value="75"]').isChecked(), 'eşik %75: ' + n75 + ' < ' + n50);
  dogrula((await page.locator(ALTI + ' [data-po-durum-oge] a').first().textContent()).indexOf('dörtte üçünden az') > 0, '%75 metni yok');
  dogrula((await page.locator('.rapor-alt-baslik').textContent()).indexOf('Durumlar eşiği: %75') >= 0, 'alt başlıkta eşik yok');
  // Klavye: ok tuşu → ~600 ms sonra %100.
  await page.locator('input[name=esik][value="75"]').focus();
  await Promise.all([page.waitForURL(/esik=100/, { timeout: 5000 }), page.keyboard.press('ArrowRight')]);
  const n100 = await rozet(page, 'ortalama_alti');
  dogrula(n100 >= n75, 'eşik %100: ' + n100 + ' < ' + n75);
  process.stdout.write('ESIK ' + n50 + ' ' + n75 + ' ' + n100 + '\n');
  // Eşik diğer süzgeçlerle hatırlanır: yalın adres → esik=100 ile açılır.
  await page.goto(PANEL + '/rapor/personel');
  await page.waitForURL(/esik=100.*hatirlanan=1/);
  dogrula(await page.locator('input[name=esik][value="100"]').isChecked(), 'hatırlanan eşik uygulanmadı');
  // Yazdırma görünümü: bölüm basılır, eşik düğmeleri ve "Daha fazla" gizli, kalan satır notu görünür.
  await page.goto(PANEL + '/rapor/personel?donem=ay');
  await page.emulateMedia({ media: 'print' });
  dogrula(await page.locator('#durumlar').isVisible(), 'baskıda Durumlar yok');
  dogrula(await page.locator('#durumlar .po-esik').isHidden(), 'baskıda eşik düğmeleri görünüyor');
  dogrula(await page.locator(ALTI + ' .po-durum-baski-not').isVisible(), 'baskıda kalan satır notu yok');
  dogrula(await page.locator('#po-kartlar').isHidden(), 'baskıda kartlar görünüyor');
  await ekran(page, 'baski-durumlar');
  if (EKRAN) { await page.pdf({ path: path.join(EKRAN, 'baski-durumlar.pdf'), format: 'A4', landscape: true }); process.stdout.write('EKRAN ' + path.join(EKRAN, 'baski-durumlar.pdf') + '\n'); }
  await page.emulateMedia({ media: 'screen' });
  dogrula(!hatalar.length, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

async function koyu(browser) {
  adim('koyu');
  const { context, page, hatalar } = await oturum(browser, { tema: 'dark', context: { viewport: { width: 1280, height: 900 } } });
  await page.goto(PANEL + '/rapor/personel?donem=ay&sifirla=1');
  dogrula(await page.evaluate(() => document.documentElement.getAttribute('data-theme')) === 'dark', 'koyu tema yok');
  const renk = await page.evaluate(() => getComputedStyle(document.querySelector('.po-durum-liste a')).color);
  dogrula(renk !== 'rgb(0, 0, 0)', 'koyu temada yazı siyah');
  await ekran(page, 'koyu-1280-durumlar', '#durumlar');
  dogrula(!hatalar.length, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

async function telefon(browser) {
  adim('telefon');
  for (const tema of ['light', 'dark']) {
    const { context, page, hatalar } = await oturum(browser, { tema, context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } });
    await page.goto(PANEL + '/rapor/personel?donem=ay&sifirla=1');
    await tasmaYok(page, 'telefon ' + tema);
    const g = await page.$$eval('[data-po-durum-grup]', (x) => x.map((e) => Math.round(e.getBoundingClientRect().width)));
    dogrula(g.length && g.every((w) => w <= 390 - 16), 'telefonda grup genişliği: ' + g);
    const sol = await page.$$eval('[data-po-durum-grup]', (x) => new Set(x.map((e) => Math.round(e.getBoundingClientRect().left))).size);
    dogrula(sol === 1, 'telefonda gruplar alt alta değil');
    await ekran(page, 'telefon-390-' + tema + '-durumlar', '#durumlar');
    await page.goto(PANEL + '/rapor/personel?donem=ay#durumlar');
    await basinAltinda(page, 'telefon ' + tema);
    await page.goto(PANEL + '/');
    await tasmaYok(page, 'telefon ana ' + tema);
    if (tema === 'light') await ekran(page, 'telefon-390-ana-ozet', '#personel-ozet .po-ozet + .po-durum-ozet');
    dogrula(!hatalar.length, 'sayfa hataları: ' + hatalar.join(' | '));
    await context.close();
  }
}

async function jsYok(browser) {
  adim('jsyok');
  const { context, page } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 }, javaScriptEnabled: false } });
  await page.goto(PANEL + '/rapor/personel?donem=ay&sifirla=1');
  const t = await page.locator(ALTI + ' [data-po-durum-oge]').count();
  const g = await page.locator(ALTI + ' [data-po-durum-oge]:visible').count();
  dogrula(t > 8 && g === t, 'JavaScript yokken satırlar gizli kaldı: ' + g + ' / ' + t);
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await masaustu(browser);
    await koyu(browser);
    await telefon(browser);
    await jsYok(browser);
    process.stdout.write('TAMAM\n');
  } finally {
    await browser.close();
  }
})().catch((e) => { process.stdout.write('HATA ' + (e && e.stack || e) + '\n'); process.exit(1); });

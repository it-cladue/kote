/* 2.3.5: kişi kartları, kategori kutuları, "Daha fazla göster" ve hatırlanan süzgeçler için tarayıcı senaryosu.
   tests/test_personel_kartlari_235.py tarafından çalıştırılır (Node + Playwright yoksa test atlanır).
   Ortam: PANEL_URL (waitress), EKRAN_KLASOR (ekran görüntüleri). */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASOR || '';
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function bekle(ms) { await new Promise((r) => setTimeout(r, ms)); }
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
  await page.fill('#giris-kullanici', ayar.kullanici || 'testadmin');
  await page.fill('#giris-sifre', SIFRE);
  await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);
  return { context, page, hatalar };
}
async function gorunenKart(page, kok) {
  return page.locator((kok || '') + ' [data-po-kart]:visible').count();
}

async function kartIzgarasi(browser) {
  adim('kart-izgarasi');
  const { context, page, hatalar } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 } } });
  await page.goto(PANEL + '/rapor/personel?donem=hepsi');
  const toplam = await page.locator('[data-po-kart]').count();
  dogrula(toplam > 30, 'kart sayısı az: ' + toplam);
  dogrula(await gorunenKart(page) === 6, 'ilk 6 kart görünmüyor');
  // 1280 px: satırda 3 kart, iki satır.
  const konum = await page.$$eval('[data-po-kart]:not([hidden])', (k) => k.map((x) => { const r = x.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.width)]; }));
  process.stdout.write('KONUM ' + JSON.stringify(konum) + '\n');
  dogrula(new Set(konum.map((x) => x[1])).size === 2 && new Set(konum.map((x) => x[0])).size === 3, '1280 px: 3x2 ızgara değil');
  const fazla = page.locator('[data-po-daha-fazla]'), az = page.locator('[data-po-daha-az]');
  dogrula(await fazla.isVisible() && !(await az.isVisible()), 'düğmeler yanlış');
  dogrula((await fazla.textContent()).trim() === 'Daha fazla göster (' + (toplam - 6) + ' kişi daha)', 'düğme metni: ' + await fazla.textContent());
  await ekran(page, 'acik-1280-kartlar', '#po-kartlar');
  // Klavye ile: düğmeye odaklanıp Enter → 12 kart daha, odak 7. kartın bağlantısında.
  await fazla.focus();
  await page.keyboard.press('Enter');
  dogrula(await gorunenKart(page) === 18, '12 kart açılmadı');
  const odak = await page.evaluate(() => { const a = document.activeElement, k = a && a.closest('[data-po-kart]'); return k ? [...document.querySelectorAll('[data-po-kart]')].indexOf(k) + ':' + a.tagName : 'yok'; });
  dogrula(odak === '6:A', 'odak ilk yeni kartta değil: ' + odak);
  dogrula((await fazla.textContent()).trim() === 'Daha fazla göster (' + (toplam - 18) + ' kişi daha)', 'düğme metni güncellenmedi');
  dogrula(await az.isVisible(), '"Daha az göster" görünmüyor');
  let tur = 0;
  while (await fazla.isVisible() && tur++ < 20) await fazla.click();
  dogrula(await gorunenKart(page) === toplam, 'hepsi açılmadı');
  await az.click();
  dogrula(await gorunenKart(page) === 6 && !(await az.isVisible()), 'daha az göster 6\'ya dönmedi');
  dogrula(await page.evaluate(() => document.activeElement && document.activeElement.hasAttribute('data-po-daha-fazla')), 'odak "Daha fazla" düğmesine dönmedi');
  dogrula(page.url().indexOf('/rapor/personel?donem=hepsi') > 0, 'sayfa yenilendi');
  // Kutu tıklanınca o kişinin o kategorideki kayıtları açılır (sayı birebir).
  const kutu = page.locator('[data-po-kart] a.po-kat-kutu').first();
  const n = +(await kutu.locator('b').textContent());
  await Promise.all([page.waitForURL(/\/kayitlar\?/), kutu.click()]);
  const bulunan = +(await page.locator('.sonuc-ozeti b').first().textContent());
  dogrula(bulunan === n, 'kutu bağlantısı ' + n + ' yerine ' + bulunan + ' kayıt açtı');
  dogrula(/personel=/.test(page.url()) && /kategori=/.test(page.url()), 'kutu bağlantısı süzgeçsiz');
  // Kategori süzgeci: tablo tek sütun, kartlarda tek kutu.
  await page.goto(PANEL + '/rapor/personel?donem=hepsi');
  await Promise.all([page.waitForURL(/kategori=CVPS/), page.selectOption('select[name=kategori]', 'CVPS')]);
  dogrula(await page.locator('table.po-tablo thead th.po-kat').count() === 1, 'kategori seçiliyken tabloda tek sütun yok');
  const kutular = await page.$$eval('[data-po-kart]:not([hidden])', (k) => k.map((x) => x.querySelectorAll('.po-kat-kutu').length));
  dogrula(kutular.every((x) => x === 1), 'kartlarda tek kutu yok');
  dogrula((await page.locator('.rapor-alt-baslik').textContent()).indexOf('Kategori: CVPS') >= 0, 'alt başlıkta kategori yok');
  await tasmaYok(page, 'kategori');
  await ekran(page, 'acik-1280-rapor-cvps');
  // Ana sayfa kartı.
  await page.goto(PANEL + '/?donem=hepsi');
  dogrula(await gorunenKart(page, '#personel-ozet') === 6, 'ana sayfada 6 kart yok');
  await page.locator('#personel-ozet').scrollIntoViewIfNeeded();
  await ekran(page, 'acik-1280-ana-kart', '#personel-ozet');
  dogrula(hatalar.length === 0, 'sayfa hatası ' + hatalar.join(' | '));
  await context.close();
}

async function betiksiz(browser) {
  adim('betiksiz');
  const { context, page } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 } } });
  const ctx2 = await browser.newContext({ javaScriptEnabled: false, storageState: await context.storageState(), viewport: { width: 1280, height: 900 } });
  const p2 = await ctx2.newPage();
  await p2.goto(PANEL + '/rapor/personel?donem=hepsi');
  dogrula(await gorunenKart(p2) === 6, 'betiksiz: ilk 6 yok');
  dogrula(!(await p2.locator('[data-po-daha-fazla]').isVisible()), 'betiksiz: işlevsiz düğme görünüyor');
  const hepsiBag = p2.locator('noscript a, a[href*="kartlar=hepsi"]').first();
  dogrula(await hepsiBag.isVisible(), 'betiksiz: "Tümünü göster" bağlantısı yok');
  await p2.goto(PANEL + '/rapor/personel?donem=hepsi&kartlar=hepsi');
  const toplam = await p2.locator('[data-po-kart]').count();
  dogrula(await gorunenKart(p2) === toplam, 'betiksiz: ?kartlar=hepsi hepsini göstermiyor');
  await ctx2.close();
  await context.close();
}

async function hatirlanan(browser) {
  adim('hatirlanan');
  const { context, page, hatalar } = await oturum(browser, { kullanici: 'lider', context: { viewport: { width: 1280, height: 900 } } });
  const ANAHTAR = 'kp.raporSuzgec.lider';
  await page.goto(PANEL + '/rapor/personel');
  dogrula(page.url() === PANEL + '/rapor/personel', 'ilk açılışta yönlendirme olmamalı');
  await Promise.all([page.waitForURL(/proje=PA/), page.selectOption('select[name=proje]', 'PA')]);
  dogrula(/donem=ay/.test(page.url()), 'dönem "Bu ay" değil');  // "Bu ay" varsayılan: formla birlikte gönderilir
  await Promise.all([page.waitForURL(/kategori=CVPS/), page.selectOption('select[name=kategori]', 'CVPS')]);
  const saklanan = await page.evaluate((k) => localStorage.getItem(k), ANAHTAR);
  process.stdout.write('SAKLANAN ' + saklanan + '\n');
  dogrula(/proje=PA/.test(saklanan) && /donem=ay/.test(saklanan) && /kategori=CVPS/.test(saklanan), 'süzgeç saklanmadı: ' + saklanan);
  // Yalın adres → bir kez yönlendirilir, not görünür.
  let gezinti = 0;
  const say = (f) => { if (f === page.mainFrame()) gezinti++; };
  page.on('framenavigated', say);
  await page.goto(PANEL + '/rapor/personel');
  await page.waitForURL(/hatirlanan=1/);
  await bekle(400);
  page.off('framenavigated', say);
  dogrula(gezinti === 2, 'yönlendirme sayısı ' + gezinti);
  const url = page.url();
  dogrula(/proje=PA/.test(url) && /donem=ay/.test(url) && /kategori=CVPS/.test(url), 'süzgeçler uygulanmadı ' + url);
  const not = page.locator('[data-po-hatirlanan-not]');
  dogrula(await not.isVisible() && (await not.textContent()).indexOf('Son kullandığınız süzgeçler uygulandı.') >= 0, 'not görünmüyor');
  dogrula(await page.locator('select[name=kategori]').inputValue() === 'CVPS', 'kategori seçili değil');
  await ekran(page, 'lider-hatirlanan', '.rapor-ust');
  await page.locator('[data-po-not-kapat]').click();
  dogrula(!(await not.isVisible()), 'not kapanmadı');
  // Varsayılana dön → saklanan silinir, yalın adres yönlendirmez.
  await page.goto(url);
  await Promise.all([page.waitForURL(/\/rapor\/personel$/), page.locator('[data-po-hatirlanan-not] a').click()]);
  dogrula(await page.evaluate((k) => localStorage.getItem(k), ANAHTAR) === null, 'sıfırla saklananı silmedi');
  await page.goto(PANEL + '/rapor/personel');
  await bekle(400);
  dogrula(page.url() === PANEL + '/rapor/personel', 'sıfırladıktan sonra yine yönlendirdi');
  // Yetkisi kalkmış proje saklıysa: 403'e gidilmez, varsayılan açılır, saklanan silinir.
  await page.evaluate((k) => localStorage.setItem(k, 'proje=OF&donem=hepsi'), ANAHTAR);
  await page.goto(PANEL + '/rapor/personel');
  await bekle(400);
  dogrula(page.url() === PANEL + '/rapor/personel' && await page.locator('h1').textContent() === 'Personel bazında kanıtlar', 'yetkisiz proje: varsayılana dönmedi ' + page.url());
  dogrula(await page.evaluate((k) => localStorage.getItem(k), ANAHTAR) === null, 'yetkisiz proje saklı kaldı');
  // Döngü koruması: önceki yönlendirme hedefe ulaşmadıysa (bayrak kalmış) yeniden yönlendirilmez.
  await page.evaluate((k) => { localStorage.setItem(k, 'proje=PA&donem=hepsi'); sessionStorage.setItem('kp.raporSuzgec.yonlendirme', '1'); }, ANAHTAR);
  await page.goto(PANEL + '/rapor/personel');
  await bekle(400);
  dogrula(page.url() === PANEL + '/rapor/personel', 'bayrak varken yönlendirdi');
  // Bir parametre varsa asla yönlendirilmez.
  await page.evaluate((k) => localStorage.setItem(k, 'proje=PA&donem=hepsi'), ANAHTAR);
  await page.goto(PANEL + '/rapor/personel?donem=bugun');
  await bekle(400);
  dogrula(page.url() === PANEL + '/rapor/personel?donem=bugun', 'parametreli adreste yönlendirdi');
  dogrula(hatalar.length === 0, 'sayfa hatası ' + hatalar.join(' | '));
  await context.close();
}

async function gorunum(browser, ad, ayar) {
  adim(ad);
  const { context, page, hatalar } = await oturum(browser, ayar);
  const telefon = ayar.context.viewport.width <= 640;
  for (const [yol, kok, isim] of [['/?donem=hepsi', '#personel-ozet', 'ana'], ['/rapor/personel?donem=hepsi', '#rapor-personel', 'rapor']]) {
    await page.goto(PANEL + yol);
    dogrula(await gorunenKart(page, kok) === 6, ad + ' ' + isim + ': 6 kart yok');
    await page.locator(kok + ' [data-po-daha-fazla]').click();
    await tasmaYok(page, ad + ' ' + isim);
    const sol = await page.$$eval(kok + ' [data-po-kart]:not([hidden])', (k) => k.map((x) => Math.round(x.getBoundingClientRect().left)));
    if (telefon) dogrula(new Set(sol).size === 1, ad + ': telefonda satırda birden çok kart');
    else dogrula(new Set(sol).size === 3, ad + ': 3 sütun değil');
    await page.locator(kok + ' [data-po-daha-az]').click();
    await ekran(page, ad + '-' + isim, telefon ? null : '#po-kartlar');
  }
  dogrula(hatalar.length === 0, ad + ': sayfa hatası ' + hatalar.join(' | '));
  await context.close();
}

async function baski(browser) {
  adim('baski');
  const { context, page } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 } } });
  await context.addInitScript(() => { window.print = function () {}; });
  await page.goto(PANEL + '/rapor/personel?donem=hepsi');
  await page.emulateMedia({ media: 'print' });
  dogrula(!(await page.locator('#po-kartlar').isVisible()), 'baskıda kartlar görünüyor');
  await page.goto(PANEL + '/rapor/personel?donem=hepsi&yazdir=1&kartlar=1');
  dogrula(await page.locator('#po-kartlar').isVisible(), '?kartlar=1 ile baskıda kartlar yok');
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await kartIzgarasi(browser);
    await betiksiz(browser);
    await hatirlanan(browser);
    await baski(browser);
    await gorunum(browser, 'koyu-1280', { tema: 'dark', context: { viewport: { width: 1280, height: 900 } } });
    await gorunum(browser, 'telefon-390', { tema: 'light', context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } });
    await gorunum(browser, 'telefon-390-koyu', { tema: 'dark', context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } });
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

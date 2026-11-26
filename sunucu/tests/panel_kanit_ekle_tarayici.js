/* 2.3.6: panelden kanıt ekleme için tarayıcı senaryosu (Kayıtlar penceresi masaüstü açık/koyu, telefon, ana sayfa düğmesi).
   tests/test_panel_kanit_ekle_236.py tarafından çalıştırılır (Node + Playwright yoksa test atlanır).
   Ortam: PANEL_URL (waitress), EKRAN_KLASOR (ekran görüntüleri). Dış görsel sitelerine çıkış yok: önizleme yer tutucu gösterir. */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const EKRAN = process.env.EKRAN_KLASOR || '';
const SIFRE = 'Test-Password-123!';
const GYAZO = 'https://gyazo.com/0123456789abcdef0123456789abcdef';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function ekran(page, ad, secici) {
  if (!EKRAN) return;
  const dosya = path.join(EKRAN, ad + '.png');
  if (secici) await page.locator(secici).first().screenshot({ path: dosya });
  else await page.screenshot({ path: dosya, fullPage: false });
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
async function pencereAcik(page) { return page.evaluate(() => { const m = document.getElementById('ekle-modal'); return !!m && !m.classList.contains('gizli'); }); }
async function jetonHazir(page) { await page.waitForFunction(() => { const j = document.querySelector('#ekle-form [name=jeton]'); return j && /^[0-9a-f]{32}$/.test(j.value); }); }
async function toastBekle(page, rx) {
  await page.waitForFunction((k) => { const t = document.getElementById('toast'); return t && !t.classList.contains('gizli') && new RegExp(k).test(t.textContent); }, rx.source);
  return page.locator('#toast').textContent();
}

async function masaustu(browser) {
  adim('masaustu-acik');
  const { context, page, hatalar } = await oturum(browser, { kullanici: 'lider', context: { viewport: { width: 1280, height: 900 } } });
  await page.goto(PANEL + '/kayitlar?durum=hepsi');
  const dugme = page.locator('#kanit-ekle-dugme');
  dogrula(await dugme.isVisible(), '"Kanıt ekle" düğmesi görünmüyor');
  await dugme.click();
  await page.waitForSelector('#ekle-modal:not(.gizli)');
  await jetonHazir(page);
  dogrula(await page.evaluate(() => document.activeElement && document.activeElement.id) === 'ekle-link', 'odak bağlantı alanında değil (tek proje ön seçili olmalı)');
  dogrula(await page.inputValue('#ekle-proje') === 'OF', 'proje ön seçili değil');
  dogrula((await page.locator('[data-ekle-kategori]').textContent()).trim() === 'SMS', 'SMS rozeti yok');
  dogrula(await page.locator('[data-ekle-onay]').isVisible() && await page.isChecked('#ekle-onayli'), 'onay kutusu görünür ve işaretli değil');
  const genislik = await page.locator('#ekle-modal .modal-icerik').evaluate((e) => e.getBoundingClientRect().width);
  dogrula(genislik <= 790 && genislik >= 600, 'pencere genişliği: ' + genislik);
  await ekran(page, 'ekle-masaustu-acik');
  // Boş gönderim: satır içi hatalar, kayıt yok.
  await page.click('[data-ekle-gonder]');
  dogrula(/zorunludur/.test(await page.locator('#ekle-link-hata').textContent()), 'bağlantı hatası yok');
  dogrula(/zorunludur/.test(await page.locator('#ekle-personel-hata').textContent()), 'personel hatası yok');
  dogrula(await page.evaluate(() => document.activeElement && document.activeElement.id) === 'ekle-link', 'odak ilk hatalı alana gitmedi');
  await page.fill('#ekle-link', 'http://gyazo.com/0123456789abcdef0123456789abcdef');
  await page.click('[data-ekle-gonder]');
  dogrula(/https:\/\//.test(await page.locator('#ekle-link-hata').textContent()), 'http hatası yok');
  // Sunucu hatası (kimliksiz Gyazo bağlantısı) da satır içinde gösterilir.
  await page.fill('#ekle-link', 'https://gyazo.com/kisa');
  await page.fill('#ekle-personel', 'TARAYICI.MASAUSTU');
  await page.click('[data-ekle-gonder]');
  await page.waitForFunction(() => /görsel kimliği/.test(document.getElementById('ekle-link-hata').textContent));
  await ekran(page, 'ekle-masaustu-hatalar', '#ekle-modal .modal-icerik');
  // Geçerli gönderim; çift tıklama tek kayıt üretir.
  await page.fill('#ekle-link', GYAZO);
  await page.fill('#ekle-uye_id', '445566');
  await page.selectOption('#ekle-tip', 'sessiz');
  await page.fill('#ekle-aciklama', 'SMS ile dönüş alındı.');
  await page.dblclick('[data-ekle-gonder]');
  const t = await toastBekle(page, /Kayıt #\d+ eklendi/);
  process.stdout.write('TOAST ' + t + '\n');
  dogrula(!(await pencereAcik(page)), 'ekleme penceresi kapanmadı');
  await page.waitForSelector('#modal:not(.gizli)');
  await page.waitForFunction(() => /Kayıt #\d+/.test(document.getElementById('modal-baslik').textContent) && document.getElementById('m-kategori').textContent === 'SMS');
  const kid = +(t.match(/#(\d+)/)[1]);
  dogrula((await page.locator('#modal-baslik').textContent()).trim() === 'Kayıt #' + kid, 'açılan kayıt yeni kayıt değil');
  dogrula(await page.locator('#m-kategori.kategori-rozet').count() === 1, 'SMS rozeti ayrıntıda yok');
  const alanlar = await page.locator('#m-alanlar').textContent();
  dogrula(alanlar.indexOf('lider (panel)') >= 0 && alanlar.indexOf('Panel') >= 0, 'ekleyen/kaynak yok: ' + alanlar);
  dogrula(await page.locator('#m-alanlar a[href*="/telegram/kullanici/"]').count() === 0, 'panel ekleyeni Telegram profiline bağlanmış');
  dogrula(await page.locator('#m-kt:not(.gizli)').count() === 1, 'onaylı rozeti yok');
  await page.waitForFunction((id) => !!document.querySelector('#kayit-sonuclari .kayit[data-id="' + id + '"]'), kid);
  await ekran(page, 'ekle-masaustu-basari');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#modal.gizli', { state: 'attached' });
  dogrula(await page.evaluate(() => document.activeElement && document.activeElement.id) === 'kanit-ekle-dugme', 'odak "Kanıt ekle" düğmesine dönmedi');
  const satir = await page.locator('#kayit-sonuclari .kayit[data-id="' + kid + '"]').textContent();
  dogrula(satir.indexOf('SMS') >= 0 && satir.indexOf('(panel)') >= 0, 'liste satırı: ' + satir);
  dogrula(await page.locator('#kayit-sonuclari .kayit[data-id]').count() === 4, 'çift tıklama iki kayıt üretti');
  // Yeniden açınca form temiz, jeton yeni.
  await dugme.click();
  await jetonHazir(page);
  dogrula(await page.inputValue('#ekle-personel') === '' && await page.inputValue('#ekle-proje') === 'OF', 'form sıfırlanmadı');
  // Esc kapatır, Tab pencere içinde kalır.
  for (let i = 0; i < 25; i++) await page.keyboard.press('Tab');
  dogrula(await page.evaluate(() => document.getElementById('ekle-modal').contains(document.activeElement)), 'odak pencereden çıktı');
  await page.keyboard.press('Escape');
  dogrula(!(await pencereAcik(page)), 'Esc pencereyi kapatmadı');
  dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

async function masaustuKoyu(browser) {
  adim('masaustu-koyu');
  const { context, page, hatalar } = await oturum(browser, { kullanici: 'lider', tema: 'dark', context: { viewport: { width: 1280, height: 900 }, colorScheme: 'dark' } });
  await page.goto(PANEL + '/kayitlar');
  dogrula(await page.evaluate(() => document.documentElement.getAttribute('data-theme')) === 'dark', 'koyu tema yok');
  await page.click('#kanit-ekle-dugme');
  await jetonHazir(page);
  await page.fill('#ekle-link', 'https://evil.example.com/x');
  await page.click('[data-ekle-gonder]');
  dogrula(/Yalnız şu adreslerin/.test(await page.locator('#ekle-link-hata').textContent()), 'host hatası yok');
  await ekran(page, 'ekle-masaustu-koyu');
  await page.keyboard.press('Escape');
  dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

async function telefon(browser) {
  adim('telefon');
  const { context, page, hatalar } = await oturum(browser, { context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } });
  await page.goto(PANEL + '/kayitlar');
  await tasmaYok(page, 'telefon liste');
  await page.click('#kanit-ekle-dugme');
  await jetonHazir(page);
  const kutu = await page.locator('#ekle-modal .modal-icerik').boundingBox();
  dogrula(Math.abs(kutu.width - 390) <= 1 && kutu.x <= 0.5, 'telefonda tam genişlik değil: ' + JSON.stringify(kutu));
  dogrula(await page.inputValue('#ekle-proje') === '', 'çok projeli hesapta proje ön seçilmemeli');
  dogrula(await page.locator('[data-ekle-onay]').isVisible(), 'onay kutusu (kt yetkisi var) görünmüyor');
  await ekran(page, 'ekle-telefon-ust');
  await page.selectOption('#ekle-proje', 'OF');
  await page.fill('#ekle-link', GYAZO);
  await page.fill('#ekle-personel', 'TARAYICI.TELEFON');
  await page.uncheck('#ekle-onayli');
  await tasmaYok(page, 'telefon pencere');
  await ekran(page, 'ekle-telefon');
  await page.tap('[data-ekle-gonder]');
  const t = await toastBekle(page, /Kayıt #\d+ eklendi; onay bekliyor/);
  process.stdout.write('TOAST ' + t + '\n');
  await page.waitForSelector('#modal:not(.gizli)');
  await page.waitForFunction(() => document.getElementById('m-kategori').textContent === 'SMS');
  dogrula(await page.locator('#m-bekliyor:not(.gizli)').count() === 1, 'bekliyor rozeti yok');
  await ekran(page, 'ekle-telefon-basari');
  dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

async function anaSayfa(browser) {
  adim('ana-sayfa');
  const { context, page, hatalar } = await oturum(browser, { context: { viewport: { width: 1280, height: 900 } } });
  const dugme = page.locator('#ana-kanit-ekle');
  dogrula(await dugme.isVisible(), 'ana sayfada "Kanıt ekle" yok');
  dogrula(/Telegram botundan ya da buradan/.test(await page.locator('.hero').first().textContent()), 'hero metni güncellenmedi');
  await ekran(page, 'ana-kanit-ekle', '.hero');
  await Promise.all([page.waitForURL(/\/kayit\/yeni/), dugme.click()]);
  await page.selectOption('#ekle-proje', 'OF');
  await page.fill('#ekle-link', 'https://img.snappark.net/s/AbC_12-x/raw/');
  await page.fill('#ekle-personel', 'ANA.SAYFA');
  await ekran(page, 'kayit-yeni-sayfa');
  await Promise.all([page.waitForURL(/\/kayitlar\?.*ac=\d+/), page.click('[data-ekle-gonder]')]);
  await page.waitForSelector('#modal:not(.gizli)');
  dogrula(/Kayıt #\d+ eklendi/.test(await page.locator('.bilgi-serit').textContent()), 'yönlendirme sonrası bilgi şeridi yok');
  dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await masaustu(browser);
    await masaustuKoyu(browser);
    await telefon(browser);
    await anaSayfa(browser);
    process.stdout.write('TAMAM\n');
  } finally {
    await browser.close();
  }
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + '\n'); process.exit(1); });

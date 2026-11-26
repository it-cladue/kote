/* 2.3.8: "Bekleyen özeti" için uçtan uca tarayıcı senaryosu (tests/test_bekleyen_ozet_238.py çalıştırır; Node + Playwright yoksa atlanır).
   Beklenen: yeni özet kart + ses + zil olarak gelir ama hatırlatma penceresini kendiliğinden AÇMAZ; zilden açılan pencerede
   "Bekleyen özeti" etiketi ve "Bekleyenleri aç" düğmesiyle listelenir; yeni özet gelince öncekinin kartı kalkar.
   Ortam: PANEL_URL (waitress), YARDIMCI_URL (testin veritabanı yardımcısı). */
'use strict';
const { chromium } = require('playwright');

const PANEL = process.env.PANEL_URL;
const YARDIMCI = process.env.YARDIMCI_URL;
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function islem(ad, veri) {
  const r = await fetch(YARDIMCI + '/' + ad, { method: 'POST', body: JSON.stringify(veri || {}) });
  if (!r.ok) throw new Error('yardımcı ' + ad + ' ' + r.status + ' ' + await r.text());
  return r.json();
}
async function bekle(ms) { await new Promise((r) => setTimeout(r, ms)); }

const SES_SAHTE = `
  window.KP_YOKLAMA_MS = 500;
  window.__ses = { tonlar: [] };
  function SahteAC() { this.state = 'suspended'; this.currentTime = 0; this.destination = {}; }
  SahteAC.prototype.resume = function () { this.state = 'running'; return Promise.resolve(); };
  SahteAC.prototype.createOscillator = function () { return { type: '', frequency: { setValueAtTime: function (v) { window.__ses.tonlar.push(v); } }, connect: function () {}, start: function () {}, stop: function () {} }; };
  SahteAC.prototype.createGain = function () { return { gain: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {} }; };
  window.AudioContext = SahteAC; window.webkitAudioContext = SahteAC;
`;
async function tonlar(page) { return page.evaluate(() => window.__ses.tonlar.length); }
async function popupAcik(page) { return page.evaluate(() => { const h = document.getElementById('hatirlatma-popup'); return !!h && !h.classList.contains('gizli'); }); }

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'tr-TR' });
  await context.addInitScript(SES_SAHTE);
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  try {
    adim('giriş');
    await page.goto(PANEL + '/giris');
    await page.fill('#giris-kullanici', 'testadmin');
    await page.fill('#giris-sifre', SIFRE);
    await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);
    await page.waitForSelector('#zil');
    await bekle(1200);
    await page.mouse.click(4, 400);

    adim('yeni bekleyen özeti: kart + ses, pencere açılmaz');
    let once = await tonlar(page);
    const oz1 = await islem('ozet');
    const kart1 = page.locator('.bp-kart.hatirlatma[data-bp-key="mesaj:' + oz1.id + '"]');
    await kart1.waitFor({ timeout: 3000 });
    dogrula((await kart1.innerText()).includes('Onay bekleyen 1 kayıt var'), 'kart metni: ' + await kart1.innerText());
    await bekle(1500);
    dogrula(!(await popupAcik(page)), 'bekleyen özeti hatırlatma penceresini kendiliğinden açmamalı');
    dogrula((await tonlar(page)) - once === 3, 'bekleyen özeti hatırlatma sesi (üç ton) çalmalı');
    dogrula(await kart1.isVisible(), 'hatırlatma kartı kalıcı olmalı');

    adim('zil listesi ve zilden açılan pencere');
    await page.click('#zil');
    const zil = await page.locator('#bildirim-liste').innerText();
    dogrula(zil.includes('Onay bekleyen 1 kayıt var') && zil.includes('Bekleyenleri aç'), 'zil listesi: ' + zil);
    const hpDugme = page.locator('#bildirim-hp-ac');
    dogrula(await hpDugme.isVisible() && (await hpDugme.innerText()).includes('Hatırlatmalar (1)'), 'zil başlığında Hatırlatmalar (1)');
    await hpDugme.click();
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    const hp = await page.locator('#hp-liste').innerText();
    dogrula(hp.includes('Bekleyen özeti') && hp.includes('Bekleyenleri aç') && !hp.includes('Proje özeti') && !hp.includes('Kayıt #'), 'pencere satırı: ' + hp);
    dogrula((await page.locator('#hp-liste [data-hp-ac="mesaj:' + oz1.id + '"]').getAttribute('href')) === '/kayitlar?durum=bekleyen', 'derin bağlantı bekleyen listesi olmalı');
    await page.keyboard.press('Escape');
    dogrula(!(await popupAcik(page)), 'Esc pencereyi kapatmalı');

    adim('sayfa yüklenince (gösterildi kaydı yokken de) özet pencereyi açmaz');
    await page.evaluate(() => Object.keys(localStorage).filter((k) => k.indexOf('kp.hpGosterildi.') === 0 || k.indexOf('kanit-hatirlatma-sonra:') === 0).forEach((k) => localStorage.removeItem(k)));
    await page.reload(); await bekle(1500);
    dogrula(!(await popupAcik(page)), 'yalnız bekleyen özeti varken ilk yüklemede pencere açılmamalı');
    await page.mouse.click(4, 400);

    adim('yeni özet öncekinin yerini alır');
    const oz2 = await islem('ozet');
    await page.locator('.bp-kart.hatirlatma[data-bp-key="mesaj:' + oz2.id + '"]').waitFor({ timeout: 3000 });
    dogrula((await islem('okundu', { id: oz1.id })).okundu === 1, 'önceki özet okundu sayılmalı');
    await bekle(1200);
    dogrula((await page.locator('.bp-kart[data-bp-key="mesaj:' + oz1.id + '"]:not(.cikiyor)').count()) === 0, 'önceki özetin kartı kalkmalı');
    dogrula(!(await popupAcik(page)), 'ikinci özet de pencereyi açmamalı');
    await page.click('#zil');
    dogrula((await page.locator('#bildirim-hp-ac').innerText()).includes('Hatırlatmalar (1)'), 'zilde yalnız son özet kalmalı');
    await page.keyboard.press('Escape');

    adim('kayıt hatırlatması pencereyi açar; özet de listede');
    const hat = await islem('hatirlatma');
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 3000 });
    const hp2 = await page.locator('#hp-liste').innerText();
    dogrula(hp2.includes('Kayıt #' + hat.kayit_id) && hp2.includes('Bekleyen özeti'), 'pencere iki satırı listelemeli: ' + hp2);
    dogrula((await page.locator('#hp-liste li').count()) === 2, 'pencerede 2 satır');
    await page.keyboard.press('Escape');

    dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

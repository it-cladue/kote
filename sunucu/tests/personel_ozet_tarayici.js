/* 2.3.4: personel bazında kanıt özeti — ana sayfa kartı ve /rapor/personel için tarayıcı senaryosu.
   tests/test_personel_ozet_234.py tarafından çalıştırılır (Node + Playwright yoksa test atlanır).
   Ortam: PANEL_URL (waitress), EKRAN_KLASOR (ekran görüntüleri). Açık / koyu tema ve 390 px telefon genişliği denenir. */
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
    // Yapışkan üst menü öğe görüntüsünün üstünü örtmesin diye yalnız çekim sırasında akışa alınır.
    await page.addStyleTag({ content: '.ust{position:static !important}' });
    await page.locator(secici).first().screenshot({ path: dosya });
  }
  else await page.screenshot({ path: dosya, fullPage: true });
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
    window.__yazdir = 0; window.print = function () { window.__yazdir++; };
    window.KP_YOKLAMA_MS = 600000;
  }, ayar.tema);
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  await page.goto(PANEL + '/giris');
  await page.fill('#giris-kullanici', 'testadmin');
  await page.fill('#giris-sifre', SIFRE);
  await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);
  return { context, page, hatalar };
}

async function senaryo(browser, ad, ayar) {
  adim(ad);
  const { context, page, hatalar } = await oturum(browser, ayar);
  const telefon = ayar.context.viewport.width <= 900;
  await page.goto(PANEL + '/?donem=hepsi');
  await page.waitForSelector('#personel-ozet');
  // 2.3.5: "İlk 3" şeridi yerine kişi kartları (ilk 6 görünür); ilk üçte madalya.
  dogrula(await page.locator('#personel-ozet .po-kisi-kart:visible').count() === 6, ad + ': ilk 6 kişi kartı görünmüyor');
  dogrula(await page.locator('#personel-ozet .po-kisi-kart.sira-3').count() === 1, ad + ': madalyalı ilk 3 yok');
  dogrula(await page.locator('#personel-ozet table.po-tablo tbody tr').count() === 10, ad + ': kart tablosu 10 satır değil');
  const masaustuGorunur = await page.locator('#personel-ozet .po-masaustu').isVisible();
  dogrula(telefon ? !masaustuGorunur : masaustuGorunur, ad + ': telefon/masaüstü görünümü yanlış');
  await tasmaYok(page, ad + ' ana sayfa');
  if (telefon) {
    // İlk 3 kartları dar ekranda alt alta dizilir; uzun adlar kısaltılmadan sığar.
    const lider = await page.$$eval('#personel-ozet .po-kisi-kart.sira-1, #personel-ozet .po-kisi-kart.sira-2, #personel-ozet .po-kisi-kart.sira-3', (k) => k.map((x) => {
      const a = x.querySelector('.po-lider-ad'), r = x.getBoundingClientRect();
      return { ad: a.textContent, s: a.scrollWidth, c: a.clientWidth, to: getComputedStyle(a).textOverflow, sol: Math.round(r.left), ust: Math.round(r.top) };
    }));
    process.stdout.write('LIDER ' + JSON.stringify(lider) + '\n');
    dogrula(new Set(lider.map((x) => x.sol)).size === 1 && new Set(lider.map((x) => x.ust)).size === 3, ad + ': ilk 3 kartları alt alta değil');
    lider.forEach((x) => dogrula(x.s <= x.c + 1 && x.to !== 'ellipsis', ad + ': ilk 3 adı kısaltılmış ' + x.ad));
  }
  await page.locator('#personel-ozet').scrollIntoViewIfNeeded();
  await bekle(150);
  await ekran(page, ad + '-ana-kart', '#personel-ozet');
  if (!telefon) {
    // Klavye: ok tuşu dönem seçimini değiştirir ama her basışta sayfayı yenilemez; Enter ile gönderilir.
    const ilkAdres = page.url();
    await page.locator('#personel-ozet input[name=donem]:checked').focus();
    let gitti = false;
    const dinle = (f) => { if (f === page.mainFrame()) gitti = true; };
    page.on('framenavigated', dinle);
    await page.keyboard.press('ArrowRight');
    await bekle(300);
    page.off('framenavigated', dinle);
    dogrula(!gitti && page.url() === ilkAdres, ad + ': ok tuşu 300 ms içinde sayfayı yeniledi');
    const secili = await page.locator('#personel-ozet input[name=donem]:checked').getAttribute('value');
    dogrula(secili !== 'hepsi', ad + ': ok tuşu seçimi değiştirmedi');
    dogrula(await page.evaluate(() => document.activeElement && document.activeElement.name === 'donem'), ad + ': odak dönem düğmesinde kalmadı');
    await Promise.all([page.waitForURL(new RegExp('donem=' + secili)), page.keyboard.press('Enter')]);
  }
  // Süzgeç değişince form kendiliğinden gönderilir ve durum adreste kalır.
  await Promise.all([page.waitForURL(/donem=hafta/), page.locator('#personel-ozet label.po-segment:has(input[value=hafta])').click()]);
  dogrula(await page.locator('#personel-ozet input[name=donem][value=hafta]').isChecked(), ad + ': dönem seçimi korunmadı');

  await page.goto(PANEL + '/rapor/personel?donem=hepsi');
  await page.waitForSelector('table.po-tablo');
  dogrula(await page.locator('.po-kisi-kart:visible').count() === 6, ad + ': raporda ilk 6 kart yok');
  dogrula(await page.locator('table.po-tablo tbody tr').count() >= 12, ad + ': rapor tablosu eksik');
  dogrula(await page.locator('table.po-tablo tfoot').count() === 1, ad + ': toplam satırı yok');
  await tasmaYok(page, ad + ' rapor');
  await ekran(page, ad + '-rapor');
  if (!telefon) {
    // Sıralama: Toplam başlığı → artan; ilk satır en küçük olur. Personel başlığı → A'dan Z'ye.
    const toplamDugme = page.locator('table.po-tablo thead th.po-toplam button');
    await toplamDugme.click();
    dogrula(await page.locator('table.po-tablo thead th.po-toplam').getAttribute('aria-sort') === 'ascending', ad + ': sıralama yönü');
    const degerler = await page.$$eval('table.po-tablo tbody td.po-toplam', (td) => td.map((x) => +x.getAttribute('data-deger')));
    dogrula(degerler.every((v, i) => i === 0 || degerler[i - 1] <= v), ad + ': artan sıralama bozuk ' + degerler.join(','));
    await page.locator('table.po-tablo thead th.po-ad-sutun button').click();
    const adlar = await page.$$eval('table.po-tablo tbody th.po-ad-sutun', (th) => th.map((x) => x.getAttribute('data-deger')));
    dogrula(adlar.slice().sort((a, b) => a.localeCompare(b, 'tr', { sensitivity: 'base', numeric: true })).join('|') === adlar.join('|'), ad + ': ad sıralaması bozuk');
    // Özel aralık seçilince tarih alanları açılır, gönderim Uygula ile.
    await page.locator('label.po-segment:has(input[value=ozel])').click();
    dogrula(await page.locator('[data-po-tarihler]').isVisible(), ad + ': özel tarih alanları açılmadı');
    await page.fill('input[name=tarih1]', '2020-01-01');
    await page.fill('input[name=tarih2]', '2030-12-31');
    await Promise.all([page.waitForURL(/donem=ozel/), page.click('.po-uygula button')]);
    dogrula(/tarih1=2020-01-01/.test(page.url()), ad + ': özel aralık adrese yazılmadı');
    // Yazdırma: ?yazdir=1 sayfası yazdırma penceresini açar; baskı stili menüyü ve süzgeçleri gizler.
    await page.goto(PANEL + '/rapor/personel?donem=hepsi&yazdir=1');
    await page.waitForFunction(() => window.__yazdir >= 1, null, { timeout: 5000 });
    await page.emulateMedia({ media: 'print' });
    dogrula(!(await page.locator('header.ust').isVisible()) && !(await page.locator('.po-filtre').isVisible()), ad + ': baskıda menü/süzgeç görünüyor');
    // Baskıda başlık etiketleri düz metin olarak görünür (form düğmeleri tekrarlanan başlıkta basılmaz), tablo kartı bölünebilir.
    const baski = await page.evaluate(() => {
      const ths = [...document.querySelectorAll('table.po-tablo thead th')];
      const etiket = ths.map((th) => {
        const e = th.querySelector('.po-baski-etiket'), d = th.querySelector('button'), cs = e && getComputedStyle(e);
        return { m: e ? e.textContent.trim() : '', gorunur: !!cs && cs.display !== 'none' && cs.visibility === 'visible' && cs.color !== 'rgba(0, 0, 0, 0)' && e.getBoundingClientRect().width > 0,
                 dugme: d ? getComputedStyle(d).display : '' };
      });
      const kart = document.querySelector('.po-rapor-tablo'), ad = document.querySelector('table.po-tablo tbody th.po-ad-sutun');
      return { etiket, kirilma: getComputedStyle(kart).breakInside, thead: getComputedStyle(document.querySelector('table.po-tablo thead')).display,
               adTasma: getComputedStyle(ad).textOverflow, adSar: getComputedStyle(ad).whiteSpace };
    });
    process.stdout.write('BASKI ' + JSON.stringify(baski) + '\n');
    dogrula(baski.etiket.length > 4 && baski.etiket.every((x) => x.m && x.gorunur && x.dugme === 'none'), ad + ': baskıda başlık etiketleri görünmüyor');
    dogrula(baski.kirilma === 'auto' && baski.thead === 'table-header-group', ad + ': baskıda tablo kartı bölünemiyor / başlık tekrarlanmıyor');
    dogrula(baski.adTasma !== 'ellipsis' && baski.adSar === 'normal', ad + ': baskıda personel adları kısaltılıyor');
    await ekran(page, ad + '-rapor-baski');
    if (EKRAN) {
      const pdf = path.join(EKRAN, ad + '-rapor.pdf');
      await page.pdf({ path: pdf, format: 'A4', landscape: true, printBackground: true });
      process.stdout.write('PDF ' + pdf + '\n');
    }
    await page.emulateMedia({ media: 'screen' });
  }
  dogrula(hatalar.length === 0, ad + ': sayfa hatası ' + hatalar.join(' | '));
  await context.close();
}

async function menuSigiyor(browser) {
  // 2.3.4: "Rapor" menü öğesi yaygın dizüstü genişliklerinde üst menüyü yeni satıra taşırmamalı.
  adim('menu');
  const { context, page } = await oturum(browser, { tema: 'light', context: { viewport: { width: 1280, height: 900 } } });
  for (const w of [1440, 1366, 1280, 1100, 1024]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.goto(PANEL + '/');
    const olcum = await page.evaluate(() => {
      const ust = document.querySelector('.ust');
      const ile = ust.getBoundingClientRect().height;
      [...ust.querySelectorAll('.menu a')].filter((x) => x.textContent.trim() === 'Rapor').forEach((x) => x.remove());
      return { ile, olmadan: ust.getBoundingClientRect().height };
    });
    process.stdout.write('MENU ' + w + ' ' + olcum.ile + ' ' + olcum.olmadan + '\n');
    dogrula(Math.abs(olcum.ile - olcum.olmadan) < 1, w + ' px: Rapor öğesi menüyü büyüttü ' + olcum.olmadan + ' -> ' + olcum.ile);
    if (w >= 1280) dogrula(olcum.ile <= 61, w + ' px: üst menü tek satıra sığmıyor (' + olcum.ile + ')');
  }
  // Süzgeç çubuğu: Proje/Durum etiketleri ile Dönem/Grupla başlıkları ve alan yükseklikleri aynı hizada olmalı.
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto(PANEL + '/rapor/personel?donem=hepsi');
  const hiza = await page.evaluate(() => {
    const bas = [...document.querySelectorAll('.po-filtre .po-alan')].map((a) => {
      const e = a.querySelector(':scope > span, :scope > legend');
      return e ? Math.round(e.getBoundingClientRect().top) : null;
    }).filter((x) => x !== null);
    const sec = document.querySelector('.po-filtre select').getBoundingClientRect();
    const seg = document.querySelector('.po-filtre .po-segment-grup').getBoundingClientRect();
    return { bas, secUst: Math.round(sec.top), secY: Math.round(sec.height), segUst: Math.round(seg.top), segY: Math.round(seg.height) };
  });
  process.stdout.write('HIZA ' + JSON.stringify(hiza) + '\n');
  // 2.3.5: Kategori seçimiyle çubuk iki satıra sarabilir; her satırdaki başlıklar kendi içinde aynı hizada olmalı.
  const ustler = hiza.bas.slice().sort((x, y) => x - y);
  dogrula(ustler.every((v, i) => i === 0 || v - ustler[i - 1] <= 1 || v - ustler[i - 1] >= 40), 'süzgeç başlıkları hizasız ' + hiza.bas.join(','));
  dogrula(Math.abs(hiza.secUst - hiza.segUst) <= 1 && Math.abs(hiza.secY - hiza.segY) <= 1, 'seçim kutusu ile dönem düğmeleri hizasız ' + JSON.stringify(hiza));
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await menuSigiyor(browser);
    await senaryo(browser, 'acik', { tema: 'light', context: { viewport: { width: 1366, height: 900 } } });
    await senaryo(browser, 'koyu', { tema: 'dark', context: { viewport: { width: 1366, height: 900 } } });
    await senaryo(browser, 'telefon', { tema: 'light', context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } });
    await senaryo(browser, 'telefon-koyu', { tema: 'dark', context: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } });
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

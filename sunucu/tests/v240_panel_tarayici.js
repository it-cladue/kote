/* 2.4.0 (A): Kayıtlar paneli tarayıcı senaryosu — tests/test_v240_panel.py çalıştırır (Node + Playwright yoksa test atlanır).
   Kapsam: bekleyen sırası ve "Bekleme" rozetleri, "+N görüntüleyebildiğiniz projelerde" notu, hızlı önizleme (fare/odak/Esc),
   "Onayla ve sonraki" + 5 sn "Geri al" + liste sonu (ikinci O tostu silmez; "Hepsi"de yalnız onaylanabilir sıradaki), klavye kısayolları ve yazı alanı koruması, Gyazo düğmesinin gizlenmesi,
   hızlı tarih düğmeleri (saat sabit, İstanbul takvimi), telefonda kapalı süzgeç paneli ve tür başına bildirim sesi.
   Ortam: PANEL_URL, YARDIMCI_URL (bildirim ekleyen yerel yardımcı), KAYITLAR (JSON: a,b,c,d kayıt numaraları), EKRAN_KLASOR. */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const YARDIMCI = process.env.YARDIMCI_URL;
const EKRAN = process.env.EKRAN_KLASOR || '';
const IDS = JSON.parse(process.env.KAYITLAR || '{}');
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function bekle(ms) { await new Promise((r) => setTimeout(r, ms)); }
async function ekran(page, ad, secici) {
  if (!EKRAN) return;
  await bekle(250);
  const dosya = path.join(EKRAN, ad + '.png');
  if (secici) await page.locator(secici).first().screenshot({ path: dosya });
  else await page.screenshot({ path: dosya });
  process.stdout.write('EKRAN ' + dosya + '\n');
}
async function islem(ad, veri) {
  const r = await fetch(YARDIMCI + '/' + ad, { method: 'POST', body: JSON.stringify(veri || {}) });
  if (!r.ok) throw new Error('yardımcı ' + ad + ' ' + r.status);
  return r.json();
}
async function tasmaYok(page, ad) {
  const t = await page.evaluate(() => ({ s: document.documentElement.scrollWidth, c: document.documentElement.clientWidth }));
  dogrula(t.s <= t.c + 1, ad + ': yatay taşma ' + t.s + ' > ' + t.c);
}
const SES_SAHTE = `
  window.KP_YOKLAMA_MS = 400;
  window.__ses = { kurulum: 0, resume: 0, tonlar: [] };
  function SahteAC() { window.__ses.kurulum++; this.state = 'suspended'; this.currentTime = 0; this.destination = {}; }
  SahteAC.prototype.resume = function () { window.__ses.resume++; this.state = 'running'; return Promise.resolve(); };
  SahteAC.prototype.createOscillator = function () { return { type: '', frequency: { setValueAtTime: function (v) { window.__ses.tonlar.push(v); } }, connect: function () {}, start: function () {}, stop: function () {} }; };
  SahteAC.prototype.createGain = function () { return { gain: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function () {} }, connect: function () {} }; };
  window.AudioContext = SahteAC; window.webkitAudioContext = SahteAC;
`;
async function oturum(browser, kullanici, ctx, ek) {
  const context = await browser.newContext(Object.assign({ deviceScaleFactor: 1, locale: 'tr-TR', viewport: { width: 1280, height: 900 } }, ctx || {}));
  await context.addInitScript(() => { try { localStorage.setItem('kanit-panel-tema', 'light'); } catch (_) {} window.KP_YOKLAMA_MS = window.KP_YOKLAMA_MS || 600000; });
  if (ek) await context.addInitScript(ek);
  const page = await context.newPage();
  const hatalar = [];
  page.on('pageerror', (e) => hatalar.push(String(e)));
  await page.goto(PANEL + '/giris');
  await page.fill('#giris-kullanici', kullanici);
  await page.fill('#giris-sifre', SIFRE);
  await Promise.all([page.waitForURL(PANEL + '/'), page.click('button[type=submit]')]);
  return { context, page, hatalar };
}
async function kayitDurumu(page, id) { return page.evaluate(async (k) => (await (await fetch('/kayit/' + k, { headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' } })).json()).kt, id); }
async function baslikBekle(page, id) { await page.waitForFunction((k) => document.getElementById('modal-baslik').textContent === 'Kayıt #' + k, id, { timeout: 8000 }); }
async function toastMetni(page) { return page.evaluate(() => { const t = document.getElementById('toast'); return t && !t.classList.contains('gizli') ? t.textContent : ''; }); }

async function bekleyenler(browser) {
  adim('bekleyen-sirasi-ve-rozetler');
  const { context, page, hatalar } = await oturum(browser, 'lider');
  await page.goto(PANEL + '/kayitlar?durum=bekleyen');
  const sira = await page.$$eval('#kayit-sonuclari .kayit[data-id]', (els) => els.map((e) => +e.getAttribute('data-id')));
  dogrula(JSON.stringify(sira) === JSON.stringify([IDS.a, IDS.b, IDS.c, IDS.d]), 'en eski önce değil: ' + sira);
  dogrula((await page.textContent('#sayac-bekleyen')).trim() === '4', 'sekme sayısı yalnız onay projelerini saymalı');
  dogrula((await page.textContent('#bekleyen-disi-not')).indexOf('+1 görüntüleyebildiğiniz projelerde') >= 0, '+N notu yok');
  const rozet = await page.$$eval('#kayit-sonuclari .kayit .bekleme-rozet', (els) => els.map((e) => e.className.replace('bekleme-rozet', '').trim() + ':' + e.textContent.trim()));
  dogrula(rozet.join('|') === 'kirmizi:4 gün|turuncu:5 sa|normal:30 dk|normal:10 dk', 'bekleme rozetleri: ' + rozet.join('|'));
  dogrula((await page.inputValue('#siralama')).indexOf('sirala=eski') >= 0, 'sıralama seçicisi eski önce göstermeli');
  await ekran(page, 'v240-bekleyen-tablo');

  adim('hizli-onizleme');
  const mini = page.locator('.kayit[data-id="' + IDS.b + '"] [data-onizleme]');
  await mini.hover();
  await page.waitForSelector('#onizleme:not(.gizli)', { timeout: 4000 });
  await page.waitForFunction(() => { const i = document.querySelector('#onizleme img'); return i && i.complete && i.naturalWidth > 0; });
  await ekran(page, 'v240-hizli-onizleme');
  await page.keyboard.press('Escape');
  dogrula(await page.locator('#onizleme').evaluate((e) => e.classList.contains('gizli')), 'Esc önizlemeyi kapatmalı');
  await page.mouse.move(1270, 20);
  await page.locator('.kayit[data-id="' + IDS.c + '"] [data-onizleme]').focus();
  dogrula(await page.locator('#onizleme').evaluate((e) => !e.classList.contains('gizli')), 'odakla önizleme açılmalı (klavye)');
  await page.keyboard.press('Escape');
  dogrula(await page.locator('#onizleme').evaluate((e) => e.classList.contains('gizli')), 'Esc odaktaki önizlemeyi kapatmalı');

  adim('pencere-dugmeleri');
  await page.locator('.kayit[data-id="' + IDS.a + '"] .detay-dugme').click();
  await baslikBekle(page, IDS.a);
  await page.waitForSelector('#m-butonlar button');
  const dugmeler = await page.$$eval('#m-butonlar button', (b) => b.map((x) => x.getAttribute('data-islem') + ':' + x.textContent.trim()));
  dogrula(dugmeler[0] === 'kt-sonraki:Onayla ve sonraki' && dugmeler[1] === 'kt:Onayla', 'onay düğmeleri: ' + dugmeler.join(', '));
  dogrula(!dugmeler.some((d) => d.indexOf('gyazo') === 0), 'Gyazo anahtarı yokken dönüştürme düğmesi görünmemeli');
  const mb = await page.locator('#m-bekleme').evaluate((e) => e.className + ':' + e.textContent);
  dogrula(mb === 'bekleme-rozet kirmizi:4 gün', 'pencere bekleme rozeti: ' + mb);
  dogrula((await page.textContent('#m-kisayol-ipucu')).indexOf('O onayla ve sonraki') >= 0, 'kısayol ipucu yok');
  await ekran(page, 'v240-pencere');

  adim('kisayollar-ve-yazi-alani-korumasi');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('?');
  dogrula(await page.locator('#m-kisayollar').isVisible(), '? yardımı açmalı');
  await ekran(page, 'v240-kisayol-yardimi', '.modal-icerik');
  await page.keyboard.press('?');
  dogrula(!(await page.locator('#m-kisayollar').isVisible()), '? yardımı kapatmalı');
  await page.keyboard.press('s');
  dogrula(await page.evaluate(() => document.activeElement && document.activeElement.id) === 'm-yorum', 'S soru kutusuna odaklanmalı');
  await page.keyboard.type('od');
  await bekle(600);
  dogrula(await page.inputValue('#m-yorum') === 'od', 'yazı alanında harfler yazılmalı');
  dogrula(await kayitDurumu(page, IDS.a) === 0, 'yazı alanında O onaylamamalı');
  dogrula(await page.locator('#m-duzenle').evaluate((e) => e.classList.contains('gizli')), 'yazı alanında D düzenlemeyi açmamalı');
  await page.fill('#m-yorum', '');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('d');
  dogrula(await page.locator('#m-duzenle').isVisible(), 'D düzenleme formunu açmalı');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('o');
  await bekle(500);
  dogrula(await kayitDurumu(page, IDS.a) === 0, 'düzenleme formu açıkken O onaylamamalı');
  await page.click('#m-duzenle-iptal');
  let sorulan = '';
  page.once('dialog', async (d) => { sorulan = d.message(); await d.dismiss(); });
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('Delete');
  await page.waitForFunction(() => true);
  await bekle(300);
  dogrula(sorulan.indexOf('silinenlere') >= 0, 'Delete silme onayını açmalı: ' + sorulan);
  dogrula(await kayitDurumu(page, IDS.a) === 0, 'vazgeçilen silme kaydı değiştirmemeli');

  adim('onayla-ve-sonraki-geri-al');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('o');
  await baslikBekle(page, IDS.b);
  let t = await toastMetni(page);
  dogrula(t.indexOf('Kayıt #' + IDS.a + ' onaylandı') >= 0 && t.indexOf('Geri al') >= 0, 'geri al tostu: ' + t);
  dogrula(await kayitDurumu(page, IDS.a) === 1, 'O onaylamalı');
  dogrula((await page.textContent('#sayac-bekleyen')).trim() === '3', 'sayaç düşmeli');
  await ekran(page, 'v240-geri-al-tostu');
  await page.click('#toast [data-toast-geri]');
  await baslikBekle(page, IDS.a);
  await page.waitForFunction(() => { const t = document.getElementById('toast'); return t && /geri alındı/.test(t.textContent); });
  dogrula(await kayitDurumu(page, IDS.a) === 0, 'Geri al onayı kaldırmalı');
  dogrula(!(await page.locator('.kayit[data-id="' + IDS.a + '"]').evaluate((e) => e.classList.contains('cikarildi'))), 'geri alınan satır listeye dönmeli');
  dogrula((await page.textContent('#sayac-bekleyen')).trim() === '4', 'sayaç geri gelmeli');

  adim('yuklenirken-kisayollar-eski-kayda-islemez');
  // Sıradaki kaydın ayrıntısı geç gelirken (Cloudflare gecikmesi) eski kaydın düğmeleri ekranda kalır: O/D/Delete ona işlememeli.
  const gecikmeli = /\/kayit\/\d+(\?.*)?$/;
  await page.route(gecikmeli, async (route) => { if (route.request().method() === 'GET') await bekle(1200); await route.continue(); });
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('o');
  await page.keyboard.press('d');
  await bekle(150);
  dogrula(await page.locator('#m-butonlar button:not([disabled])').count() === 0, 'yüklenirken eski düğmeler tıklanamaz olmalı');
  await baslikBekle(page, IDS.b);
  await bekle(300);
  dogrula(await kayitDurumu(page, IDS.a) === 0, 'yüklenirken O atlanan kaydı onaylamamalı');
  dogrula(await kayitDurumu(page, IDS.b) === 0, 'yüklenirken basılan O yeni kaydı da onaylamamalı');
  dogrula(await page.locator('#m-duzenle').evaluate((e) => e.classList.contains('gizli')), 'yüklenirken D düzenleme açmamalı');
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('o');
  await page.waitForFunction(() => /onaylandı/.test(document.getElementById('toast').textContent));
  await page.keyboard.press('o');
  await bekle(200);
  t = await toastMetni(page);
  dogrula(t.indexOf('Kayıt #' + IDS.b + ' onaylandı') >= 0 && t.indexOf('Geri al') >= 0, 'ikinci O geri al tostunu silmemeli: ' + t);
  await baslikBekle(page, IDS.c);
  dogrula(await kayitDurumu(page, IDS.c) === 0, 'yüklenirken ikinci O sıradakini onaylamamalı');
  await page.unroute(gecikmeli);
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('u');  // U: "Geri al" (odak kapanı tosttaki düğmeye Tab ile izin vermez)
  await baslikBekle(page, IDS.b);
  await page.waitForFunction(() => /geri alındı/.test(document.getElementById('toast').textContent));
  dogrula(await kayitDurumu(page, IDS.b) === 0, 'U onayı geri almalı');
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('ArrowLeft');
  await baslikBekle(page, IDS.a);

  dogrula(await page.locator('.kayit[data-id="' + IDS.b + '"] .bekleme-rozet').evaluate((e) => !e.classList.contains('gizli')), 'geri alınan kaydın bekleme rozeti görünmeli');

  adim('liste-sonuna-kadar');
  for (const [simdiki, sonraki] of [[IDS.a, IDS.b], [IDS.b, IDS.c], [IDS.c, IDS.d]]) {
    await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
    await page.click('#m-butonlar button[data-islem="kt-sonraki"]');
    await baslikBekle(page, sonraki);
    dogrula(await kayitDurumu(page, simdiki) === 1, simdiki + ' onaylanmalı');
    dogrula(await page.locator('.kayit[data-id="' + simdiki + '"] .bekleme-rozet').evaluate((e) => e.classList.contains('gizli')), 'onaylanan kaydın bekleme rozeti gizlenmeli');
  }
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.click('#m-butonlar button[data-islem="kt-sonraki"]');
  await page.waitForFunction(() => /Bu sayfadaki bekleyenler bitti/.test(document.getElementById('m-eylem-notu').textContent));
  await baslikBekle(page, IDS.d);
  t = await toastMetni(page);
  dogrula(t.indexOf('Bu sayfadaki bekleyenler bitti') >= 0, 'liste sonu tostu: ' + t);
  dogrula(await kayitDurumu(page, IDS.d) === 1, 'son kayıt onaylanmalı');
  dogrula((await page.textContent('#sayac-bekleyen')).trim() === '0', 'bekleyen kalmamalı');
  await ekran(page, 'v240-liste-sonu');

  adim('liste-sonunda-ikinci-o-geri-al-tostunu-silmez');
  // Liste sonunda aynı kayıt yeniden açılır: ikinci O "zaten onaylı" bilgisiyle "Geri al" tostunu silmemeli, U çalışmalı.
  await page.waitForFunction(() => !!document.querySelector('#m-butonlar button[data-islem="kt"]:not([disabled])'));
  await page.locator('#modal .modal-kapat').focus();
  await page.keyboard.press('o');
  await bekle(300);
  t = await toastMetni(page);
  dogrula(t.indexOf('Kayıt #' + IDS.d + ' onaylandı') >= 0 && t.indexOf('Geri al') >= 0, 'liste sonunda ikinci O geri al tostunu silmemeli: ' + t);
  await page.keyboard.press('u');
  await page.waitForFunction(() => /geri alındı/.test(document.getElementById('toast').textContent));
  dogrula(await kayitDurumu(page, IDS.d) === 0, 'liste sonunda U onayı geri almalı');
  dogrula((await page.textContent('#sayac-bekleyen')).trim() === '1', 'geri alınca sayaç 1 olmalı');
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.click('#m-butonlar button[data-islem="kt-sonraki"]');
  await page.waitForFunction(() => /Bu sayfadaki bekleyenler bitti/.test(document.getElementById('m-eylem-notu').textContent));
  dogrula(await kayitDurumu(page, IDS.d) === 1, 'son kayıt yeniden onaylanmalı');
  await bekle(5400);
  dogrula(await toastMetni(page) === '', 'geri al tostu 5 sn sonra kapanmalı');
  await page.keyboard.press('Escape');
  dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
  await context.close();
}

async function hepsiKarmaYetki(browser) {
  adim('hepsi-sekmesinde-sonraki-yalniz-onaylanabilir');
  // lider: OF onaylar, PA yalnız okur. "Hepsi" (yeni önce): d, c, PA-OKU, b, a. c'den sonra PA kaydı atlanıp b açılmalı.
  const { context, page, hatalar } = await oturum(browser, 'lider');
  await page.goto(PANEL + '/kayitlar?durum=hepsi');
  const sira = await page.$$eval('#kayit-sonuclari .kayit[data-id]', (els) => els.map((e) => +e.getAttribute('data-id') + ':' + e.getAttribute('data-izin-kt')));
  const pa = sira.map((x) => x.split(':')).filter((x) => x[1] === '0').map((x) => +x[0]);
  dogrula(pa.length === 1, 'yalnız okunan kayıt data-izin-kt="0" olmalı: ' + sira);
  const ids = sira.map((x) => +x.split(':')[0]);
  dogrula(ids.indexOf(IDS.c) < ids.indexOf(pa[0]) && ids.indexOf(pa[0]) < ids.indexOf(IDS.b), 'sıra beklenen değil: ' + sira);
  for (const id of [IDS.b, IDS.c]) {  // b ve c'nin onayını kaldır
    await page.locator('.kayit[data-id="' + id + '"] .detay-dugme').click();
    await baslikBekle(page, id);
    await page.waitForSelector('#m-butonlar button[data-islem="kt"][data-deger="0"]:not([disabled])');
    await page.click('#m-butonlar button[data-islem="kt"][data-deger="0"]');
    await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
    dogrula(await kayitDurumu(page, id) === 0, id + ' onayı kaldırılmalı');
    await page.keyboard.press('Escape');
  }
  await page.locator('.kayit[data-id="' + IDS.c + '"] .detay-dugme').click();
  await baslikBekle(page, IDS.c);
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.click('#m-butonlar button[data-islem="kt-sonraki"]');
  await page.waitForFunction(() => /onaylandı/.test(document.getElementById('toast').textContent));
  await bekle(800);
  dogrula((await page.textContent('#modal-baslik')) === 'Kayıt #' + IDS.b, 'yalnız okunan PA kaydı atlanıp b açılmalı: ' + (await page.textContent('#modal-baslik')));
  await page.waitForSelector('#m-butonlar button[data-islem="kt-sonraki"]:not([disabled])');
  await page.click('#m-butonlar button[data-islem="kt-sonraki"]');
  await page.waitForFunction(() => /Bu sayfadaki bekleyenler bitti/.test(document.getElementById('m-eylem-notu').textContent));
  await baslikBekle(page, IDS.b);
  const t = await toastMetni(page);
  dogrula(t.indexOf('Bu sayfadaki bekleyenler bitti') >= 0, 'onaylanabilir bekleyen kalmayınca liste sonu tostu: ' + t);
  dogrula(await kayitDurumu(page, IDS.b) === 1 && await kayitDurumu(page, IDS.c) === 1, 'b ve c yeniden onaylanmalı');
  await page.keyboard.press('Escape');
  dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
  await context.close();
}

async function donemler(browser) {
  adim('hizli-tarih-dugmeleri');
  // 24.11.2026 22:30 UTC = 25.11.2026 01:30 İstanbul (çarşamba): UTC takvimi 24'ü, İstanbul 25'i gösterir.
  const { context, page, hatalar } = await oturum(browser, 'lider', null, () => { window.KP_SIMDI = Date.UTC(2026, 10, 24, 22, 30); });
  await page.goto(PANEL + '/kayitlar?durum=hepsi');
  const sonuc = await page.evaluate(() => [Panel.istanbulBugun()].concat(['bugun', 'bu_hafta', 'gecen_hafta', 'bu_ay', 'gecen_ay'].map((k) => Panel.donemAraligi(k, Panel.istanbulBugun()).join('_'))));
  dogrula(JSON.stringify(sonuc) === JSON.stringify(['2026-11-25', '2026-11-25_2026-11-25', '2026-11-23_2026-11-25', '2026-11-16_2026-11-22', '2026-11-01_2026-11-25', '2026-10-01_2026-10-31']), 'dönem aralıkları: ' + sonuc);
  const ocak = await page.evaluate(() => [Panel.donemAraligi('gecen_ay', '2026-01-10').join('_'), Panel.donemAraligi('gecen_hafta', '2026-01-04').join('_'), Panel.donemAraligi('bu_hafta', '2026-11-23').join('_')]);
  dogrula(ocak.join('|') === '2025-12-01_2025-12-31|2025-12-22_2025-12-28|2026-11-23_2026-11-23', 'yıl dönümü / pazar / pazartesi: ' + ocak);
  await page.click('.gelismis-filtre summary');
  await ekran(page, 'v240-gelismis-suzgec', '#filtre-form');
  await Promise.all([page.waitForURL(/tarih1=2026-11-16/), page.click('[data-hizli-donem] [data-donem="gecen_hafta"]')]);
  dogrula(page.url().indexOf('tarih2=2026-11-22') >= 0, 'geçen hafta bitişi: ' + page.url());
  dogrula(await page.locator('[data-donem="gecen_hafta"]').evaluate((e) => e.classList.contains('secili') && e.getAttribute('aria-pressed') === 'true'), 'seçili dönem işaretlenmeli');
  await page.selectOption('#filtre-tarih-alani', 'onay');
  await Promise.all([page.waitForURL(/tarih_alani=onay/), page.click('#filtre-form button[type=submit]')]);
  dogrula(await page.inputValue('#filtre-tarih-alani') === 'onay', 'tarih ölçütü korunmalı');
  await page.goto(PANEL + '/disa-aktar');
  await page.click('[data-hizli-donem] [data-donem="gecen_ay"]');
  dogrula(await page.inputValue('#cikti-tarih1') === '2026-10-01' && await page.inputValue('#cikti-tarih2') === '2026-10-31', 'Çıktı: geçen ay');
  await page.click('#cikti-tarihsiz');
  await page.click('[data-hizli-donem] [data-donem="bu_ay"]');
  dogrula(!(await page.isChecked('#cikti-tarihsiz')) && await page.inputValue('#cikti-tarih1') === '2026-11-01' && !(await page.locator('#cikti-tarih1').isDisabled()), 'Çıktı: hızlı düğme tarihsizi kaldırmalı');
  await ekran(page, 'v240-cikti-donemler', '#cikti-form');
  dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
  await context.close();
}

async function telefon(browser) {
  adim('telefon-suzgecler');
  const { context, page, hatalar } = await oturum(browser, 'lider', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await page.goto(PANEL + '/kayitlar?durum=hepsi&q=P-');
  dogrula(!(await page.locator('#filtre-form').isVisible()), 'telefonda süzgeç paneli varsayılan kapalı olmalı');
  const dugme = page.locator('#suzgec-ac');
  dogrula(await dugme.isVisible() && (await dugme.textContent()).trim() === 'Süzgeçler (1 etkin)' && await dugme.getAttribute('aria-expanded') === 'false', 'süzgeç düğmesi: ' + (await dugme.textContent()));
  const ust = await page.evaluate(() => document.querySelector('#kayit-sonuclari .kayit').getBoundingClientRect().top + window.scrollY);
  dogrula(ust < 620, 'ilk kayıt çok aşağıda: ' + ust);
  const satirlar = await page.$$eval('.sekmeler .sekme', (els) => Array.from(new Set(els.map((e) => Math.round(e.getBoundingClientRect().top)))).length);
  dogrula(satirlar === 1, 'sekmeler tek satırda olmalı: ' + satirlar);
  await tasmaYok(page, 'telefon kapalı');
  await ekran(page, 'v240-telefon-kapali');
  await dugme.click();
  dogrula(await page.locator('#filtre-form').isVisible() && await dugme.getAttribute('aria-expanded') === 'true', 'düğme paneli açmalı');
  await tasmaYok(page, 'telefon açık');
  await ekran(page, 'v240-telefon-acik');
  await page.reload();
  dogrula(await page.locator('#filtre-form').isVisible(), 'açık tercih hatırlanmalı');
  await page.locator('#suzgec-ac').click();
  await page.reload();
  dogrula(!(await page.locator('#filtre-form').isVisible()), 'kapalı tercih hatırlanmalı');
  dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
  await context.close();
  // Masaüstünde düğme görünmez, panel hep açık.
  const m = await oturum(browser, 'lider');
  await m.page.goto(PANEL + '/kayitlar');
  dogrula(await m.page.locator('#filtre-form').isVisible() && !(await m.page.locator('#suzgec-ac').isVisible()), 'masaüstünde süzgeçler açık, düğme gizli');
  await m.context.close();
}

async function sesler(browser) {
  adim('tur-basina-ses');
  const { context, page, hatalar } = await oturum(browser, 'testadmin', null, SES_SAHTE);
  const ses = async () => page.evaluate(() => window.__ses.tonlar.length);
  await bekle(1200);
  await page.mouse.click(4, 400);
  let n = await ses();
  await islem('kanit');
  await page.waitForFunction((k) => window.__ses.tonlar.length > k, n, { timeout: 8000 });
  n = await ses();
  await islem('onay');
  await page.waitForFunction(() => Array.from(document.querySelectorAll('.bp-kart')).some((k) => /Onay/.test(k.textContent)), null, { timeout: 8000 });
  await bekle(400);
  dogrula(await ses() === n, 'onay bildirimi ses çalmamalı');
  await page.click('#zil');
  await page.waitForSelector('#bildirim-ses-turleri');
  const durum = await page.$$eval('#bildirim-ses-turleri [data-ses-turu]', (els) => els.map((e) => e.getAttribute('data-ses-turu') + ':' + e.checked));
  dogrula(durum.join(',') === 'kanit:true,konusma:true,hatirlatma:true', 'varsayılan tür anahtarları: ' + durum);
  await ekran(page, 'v240-zil-ses-turleri', '#bildirim-kutu');
  await page.click('#bildirim-ses-kanit');
  dogrula(await page.evaluate(() => localStorage.getItem('kanit-bildirim-ses:kanit')) === '0', 'tür tercihi saklanmalı');
  await page.keyboard.press('Escape');
  n = await ses();
  await islem('kanit');
  await page.waitForFunction(() => document.querySelectorAll('.bp-kart').length >= 1, null, { timeout: 8000 });
  await bekle(1500);
  dogrula(await ses() === n, 'kapatılan "Yeni kanıt" sesi çalmamalı');
  await islem('soru');
  await page.waitForFunction((k) => window.__ses.tonlar.length > k, n, { timeout: 8000 });
  await page.reload();
  await page.waitForSelector('#bildirim-ses-turleri', { state: 'attached' });
  const sonra = await page.$$eval('#bildirim-ses-turleri [data-ses-turu]', (els) => els.map((e) => e.getAttribute('data-ses-turu') + ':' + e.checked));
  dogrula(sonra.join(',') === 'kanit:false,konusma:true,hatirlatma:true', 'yenilemeden sonra tercih: ' + sonra);
  await bekle(800);
  await page.mouse.click(4, 400);
  await page.click('#zil');
  await page.click('#bildirim-ses');
  dogrula(await page.evaluate(() => Array.from(document.querySelectorAll('[data-ses-turu]')).every((x) => x.disabled)), 'ana Ses kapalıyken tür anahtarları pasif');
  await page.keyboard.press('Escape');
  n = await ses();
  await islem('soru');
  await bekle(2000);
  dogrula(await ses() === n, 'ana Ses kapalıyken hiç ses çalmamalı');
  dogrula(hatalar.length === 0, 'sayfa hatası: ' + hatalar.join(' | '));
  await context.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    await bekleyenler(browser);
    await hepsiKarmaYetki(browser);
    await donemler(browser);
    await telefon(browser);
    await sesler(browser);
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

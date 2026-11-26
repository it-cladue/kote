/* 2.3.3: bildirim pop-up kartları / ses / hatırlatma penceresi için uçtan uca tarayıcı senaryosu.
   tests/test_bildirim_popup_233.py tarafından çalıştırılır (Node + Playwright yoksa test atlanır).
   Ortam: PANEL_URL (waitress), YARDIMCI_URL (testin veritabanı yardımcısı), EKRAN_KLASOR (isteğe bağlı ekran görüntüleri). */
'use strict';
const { chromium } = require('playwright');
const path = require('path');

const PANEL = process.env.PANEL_URL;
const YARDIMCI = process.env.YARDIMCI_URL;
const EKRAN = process.env.EKRAN_KLASOR || '';
const SIFRE = 'Test-Password-123!';

function adim(m) { process.stdout.write('ADIM ' + m + '\n'); }
function dogrula(kosul, mesaj) { if (!kosul) throw new Error('DOĞRULAMA: ' + mesaj); }
async function islem(ad, veri) {
  const r = await fetch(YARDIMCI + '/' + ad, { method: 'POST', body: JSON.stringify(veri || {}) });
  if (!r.ok) throw new Error('yardımcı ' + ad + ' ' + r.status);
  return r.json();
}
async function ekran(page, ad, secici) {
  if (!EKRAN) return;
  await bekle(450); // giriş animasyonu bitsin
  const dosya = path.join(EKRAN, ad + '.png');
  if (secici) await page.locator(secici).first().screenshot({ path: dosya });
  else await page.screenshot({ path: dosya });
  process.stdout.write('EKRAN ' + dosya + '\n');
}

/* AudioContext sahtesi: hangi tonların istendiğini kaydeder; gerçek ses çalınmaz. */
const SES_SAHTE = `
  window.KP_YOKLAMA_MS = 500;
  window.__ses = { kurulum: 0, resume: 0, tonlar: [], enYuksekKazanc: 0 };
  function SahteAC() { window.__ses.kurulum++; this.state = 'suspended'; this.currentTime = 0; this.destination = {}; }
  SahteAC.prototype.resume = function () { window.__ses.resume++; this.state = 'running'; return Promise.resolve(); };
  SahteAC.prototype.createOscillator = function () { return { type: '', frequency: { setValueAtTime: function (v) { window.__ses.tonlar.push(v); } }, connect: function () {}, start: function () {}, stop: function () {} }; };
  SahteAC.prototype.createGain = function () { return { gain: { setValueAtTime: function () {}, exponentialRampToValueAtTime: function (v) { if (v > window.__ses.enYuksekKazanc) window.__ses.enYuksekKazanc = v; } }, connect: function () {} }; };
  window.AudioContext = SahteAC; window.webkitAudioContext = SahteAC;
`;

async function sesDurumu(page) { return page.evaluate(() => JSON.parse(JSON.stringify(window.__ses))); }
async function hareket(page) { await page.mouse.click(4, 400); }
async function popupAcik(page) { return page.evaluate(() => { const h = document.getElementById('hatirlatma-popup'); return !!h && !h.classList.contains('gizli'); }); }
async function bekle(ms) { await new Promise((r) => setTimeout(r, ms)); }

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, locale: 'tr-TR' });
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
    await bekle(1500);
    let ses = await sesDurumu(page);
    dogrula(ses.tonlar.length === 0, 'ilk yüklemede ses çalınmamalı');
    dogrula(await page.locator('.bp-kart').count() === 0, 'ilk yoklamada kart çıkmamalı');

    adim('tek kart + ses');
    await hareket(page);
    ses = await sesDurumu(page);
    dogrula(ses.kurulum === 1 && ses.resume >= 1, 'AudioContext ilk harekette kurulmalı: ' + JSON.stringify(ses));
    const bir = await islem('kanit');
    const t0 = Date.now();
    const kart = page.locator('.bp-kart[data-bp-key="kayit:' + bir.bildirim_id + '"]');
    await kart.waitFor({ timeout: 2500 });
    dogrula(Date.now() - t0 < 2500, 'kart 2 sn içinde çıkmalı');
    const metin = await kart.innerText();
    dogrula(metin.includes('#' + bir.kayit_id) && metin.includes('Yeni kanıt') && metin.includes('OF'), 'kart içeriği: ' + metin);
    await bekle(100);
    ses = await sesDurumu(page);
    dogrula(ses.tonlar.length === 2 && ses.tonlar[0] === 880, 'normal bildirim iki tonlu olmalı: ' + JSON.stringify(ses.tonlar));
    dogrula(ses.enYuksekKazanc > 0 && ses.enYuksekKazanc <= 0.15, 'ses kazancı ≤ 0,15: ' + ses.enYuksekKazanc);
    dogrula(await page.locator('#toast:not(.gizli)').count() === 0, 'yeni bildirim alttaki tostu kullanmamalı');
    await ekran(page, 'kart_acik', '#bildirim-popuplar');
    await ekran(page, 'kart_acik_sayfa');

    adim('klavye: kart düğmeleri sekme sırasında başlığın hemen ardında');
    await page.evaluate(() => { window.scrollTo(0, 0); document.getElementById('zil').focus(); });
    let tabSayisi = -1;
    for (let i = 1; i <= 10; i++) {
      await page.keyboard.press('Tab');
      const ne = await page.evaluate(() => { const a = document.activeElement; return a ? (a.closest('.bp-kart') ? 'KART' : a.tagName + '#' + a.id + '.' + a.className + ' ' + (a.textContent || '').slice(0, 20)) : '-'; });
      if (process.env.TAB_IZ) console.log('TAB', i, ne);
      if (ne === 'KART') { tabSayisi = i; break; }
    }
    dogrula(tabSayisi > 0, 'zilden sonra birkaç Tab ile kart düğmesine ulaşılmalı: ' + tabSayisi);
    dogrula(await page.evaluate(() => !!document.querySelector('main') && (document.querySelector('#bildirim-popuplar').compareDocumentPosition(document.querySelector('main')) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0), 'kartlar DOM\'da ana içerikten önce olmalı');
    console.log('LOG zilden karta Tab: ' + tabSayisi);

    adim('Aç → derin bağlantı');
    await Promise.all([page.waitForURL(/ac=/), kart.locator('[data-bp-ac]').click()]);
    dogrula(page.url().includes('ac=' + bir.kayit_id), 'Aç derin bağlantıya gitmeli: ' + page.url());
    dogrula((await islem('okunmamis', { key: 'kayit:' + bir.bildirim_id })).okunmamis === 0, 'Aç bildirimi okundu yapmalı');

    adim('3 bildirim → özet kart');
    await page.goto(PANEL + '/');
    await bekle(800);
    await hareket(page);
    await islem('kanit', { adet: 3 });
    const ozet = page.locator('.bp-kart.ozet');
    await ozet.waitFor({ timeout: 2500 });
    const ozetMetin = await ozet.innerText();
    dogrula(ozetMetin.includes('3 yeni bildirim') && ozetMetin.includes('Bildirimleri aç') && ozetMetin.includes('Tümünü gör'), 'özet kart: ' + ozetMetin);
    dogrula(await page.locator('.bp-kart').count() === 1, 'yalnız bir özet kart olmalı');
    await ekran(page, 'ozet_kart_acik', '#bildirim-popuplar');
    await ozet.locator('[data-bp-kutu]').click();
    dogrula(!(await page.locator('#bildirim-kutu').getAttribute('class')).includes('gizli'), 'Bildirimleri aç açılır listeyi açmalı');
    await page.keyboard.press('Escape');

    adim('hatırlatma penceresi');
    let tonOnce = (await sesDurumu(page)).tonlar.length;
    const hat = await islem('hatirlatma', { adet: 2, ozet: true });
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    const hpMetin = await page.locator('#hatirlatma-popup .hp-pencere').innerText();
    dogrula(hpMetin.includes('Bekleyen kontroller hatırlatması') && hpMetin.includes('Kayıt #' + hat.kayit_idler[0]) && hpMetin.includes('Proje özeti'), 'pencere içeriği: ' + hpMetin);
    await bekle(50);
    dogrula(await page.evaluate(() => document.activeElement && !!document.activeElement.closest('#hatirlatma-popup')), 'odak pencereye taşınmalı: ' + await page.evaluate(() => document.activeElement && document.activeElement.outerHTML.slice(0, 120)));
    for (let i = 0; i < 12; i++) await page.keyboard.press('Tab');
    dogrula(await page.evaluate(() => !!document.activeElement.closest('#hatirlatma-popup')), 'odak pencerede kalmalı (tuzak)');
    ses = await sesDurumu(page);
    dogrula(ses.tonlar.slice(tonOnce).length === 3 && ses.tonlar[tonOnce] === 659.25, 'hatırlatma üç tonlu olmalı: ' + JSON.stringify(ses.tonlar.slice(tonOnce)));
    await ekran(page, 'hatirlatma_popup_acik');

    adim('sayfa yüklenince bekleyen hatırlatma penceresi açılır (koyu tema)');
    await page.evaluate(() => localStorage.setItem('kanit-panel-tema', 'dark'));
    await page.reload();
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    await ekran(page, 'hatirlatma_popup_koyu');
    await page.evaluate(() => localStorage.setItem('kanit-panel-tema', 'light'));
    await page.reload();
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });

    adim('Daha sonra');
    await page.click('#hatirlatma-popup [data-hp-sonra]');
    dogrula(!(await popupAcik(page)), 'Daha sonra pencereyi kapatmalı');
    await bekle(1600);
    dogrula(!(await popupAcik(page)), 'sonraki yoklamada yeniden açılmamalı');
    await page.reload(); await bekle(1500);
    dogrula(!(await popupAcik(page)), 'aynı gün sayfa yenilenince açılmamalı');

    adim('yeni hatırlatma yeniden açar + Esc');
    await hareket(page);
    const hat2 = await islem('hatirlatma', { adet: 1 });
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    dogrula((await page.locator('#hp-liste li').count()) === 4, 'pencere tüm okunmamış hatırlatmaları listelemeli');
    dogrula(await page.locator('.bp-kart.hatirlatma[data-bp-key="mesaj:' + hat2.idler[0] + '"]').count() === 1, 'hatırlatma kartı da çıkmalı');
    await page.keyboard.press('Escape');
    dogrula(!(await popupAcik(page)), 'Esc pencereyi kapatmalı');
    await page.reload(); await bekle(1200);
    dogrula(await popupAcik(page), 'Kapat/Esc gün boyu ertelemez; yeni sayfada pencere yine açılır');

    adim('Tümünü okundu say (özet hatırlatma kartı da kalkar)');
    await islem('hatirlatma', { adet: 3 });
    await page.locator('.bp-kart.ozet.hatirlatma').waitFor({ timeout: 2500 });
    dogrula((await page.locator('#hp-liste li').count()) === 7, 'pencere yeni gelen hatırlatmaları da listelemeli');
    await page.click('#hatirlatma-popup [data-hp-okundu]');
    await page.waitForSelector('#hatirlatma-popup.gizli', { state: 'attached', timeout: 2500 });
    await bekle(300);
    dogrula((await islem('okunmamis', { tur: 'hatirlatma' })).okunmamis === 0, 'tüm hatırlatmalar okundu olmalı');
    dogrula((await page.locator('.bp-kart.ozet.hatirlatma:not(.cikiyor)').count()) === 0, 'okunan hatırlatmaların özet kartı kalkmalı');
    await bekle(1200);
    dogrula((await page.locator('.bp-kart').count()) === 0, 'okunmuş bildirimlerin kartı ekranda kalmamalı');

    adim('Ses anahtarı');
    await page.click('#zil');
    const sesKutu = page.locator('#bildirim-ses');
    dogrula(await sesKutu.isChecked(), 'ses varsayılan açık');
    await sesKutu.uncheck();
    dogrula(await page.evaluate(() => localStorage.getItem('kanit-bildirim-ses')) === '0', 'tercih localStorage\'a yazılmalı');
    await page.reload(); await bekle(800);
    dogrula(!(await page.locator('#bildirim-ses').isChecked()), 'tercih yenilemeden sonra korunmalı');
    await hareket(page);
    tonOnce = (await sesDurumu(page)).tonlar.length;
    const sessiz = await islem('kanit');
    await page.locator('.bp-kart[data-bp-key="kayit:' + sessiz.bildirim_id + '"]').waitFor({ timeout: 2500 });
    dogrula((await sesDurumu(page)).tonlar.length === tonOnce, 'ses kapalıyken ton istenmemeli');
    await page.evaluate(() => localStorage.setItem('kanit-bildirim-ses', '1'));

    adim('kayıt penceresi açıkken hatırlatma ertelenir');
    await page.goto(PANEL + '/kayitlar?durum=hepsi&ac=' + bir.kayit_id);
    await page.waitForSelector('#modal:not(.gizli)');
    await bekle(800);
    await islem('hatirlatma', { adet: 1 });
    await bekle(1800);
    dogrula(!(await popupAcik(page)), 'kayıt penceresi açıkken hatırlatma penceresi açılmamalı');
    await page.click('#modal .modal-kapat');
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    await page.click('#hatirlatma-popup [data-hp-okundu]');
    await page.waitForSelector('#hatirlatma-popup.gizli', { state: 'attached', timeout: 2500 });

    adim('hatırlatma satırı derin bağlantıya gider');
    const hat3 = await islem('hatirlatma', { adet: 1 });
    await page.waitForSelector('#hatirlatma-popup:not(.gizli)', { timeout: 2500 });
    await Promise.all([page.waitForURL(/ac=/), page.click('#hp-liste [data-hp-ac="mesaj:' + hat3.idler[0] + '"]')]);
    dogrula(page.url().includes('ac=' + hat3.kayit_idler[0]), 'hatırlatma satırı kayda gitmeli: ' + page.url());
    await page.waitForSelector('#modal:not(.gizli)');

    adim('koyu tema ekran görüntüleri');
    await page.evaluate(() => localStorage.setItem('kanit-panel-tema', 'dark'));
    await page.goto(PANEL + '/'); await bekle(800);
    const koyu = await islem('kanit');
    await page.locator('.bp-kart[data-bp-key="kayit:' + koyu.bildirim_id + '"]').waitFor({ timeout: 2500 });
    await ekran(page, 'kart_koyu', '#bildirim-popuplar');
    await page.evaluate(() => document.querySelectorAll('.bp-kart').forEach((k) => k.remove()));
    await islem('kanit', { adet: 3 });
    await page.locator('.bp-kart.ozet').waitFor({ timeout: 2500 });
    await ekran(page, 'ozet_kart_koyu', '#bildirim-popuplar');
    await ekran(page, 'ozet_kart_koyu_sayfa');

    if (EKRAN) {
      adim('telefon görünümü');
      const tel = await browser.newContext({ viewport: { width: 390, height: 780 }, deviceScaleFactor: 1, storageState: await context.storageState() });
      await tel.addInitScript(SES_SAHTE);
      const tp = await tel.newPage();
      await tp.goto(PANEL + '/'); await bekle(800);
      await islem('kanit');
      await tp.locator('.bp-kart').first().waitFor({ timeout: 2500 });
      await ekran(tp, 'kart_telefon');
      await tel.close();
    }
    dogrula(hatalar.length === 0, 'sayfa hataları: ' + hatalar.join(' | '));
    process.stdout.write('TAMAM\n');
  } catch (e) {
    process.stdout.write('HATA ' + (e && e.stack || e) + '\n');
    if (EKRAN) { try { await page.screenshot({ path: path.join(EKRAN, 'hata.png') }); } catch (_) {} }
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();

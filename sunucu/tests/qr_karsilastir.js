/* 2.4.1: app/qr_svg.py'nin ürettiği QR matrisini bağımsız bir uygulamayla (Kazuhiko Arase'nin MIT lisanslı QRCode for
   JavaScript kodu; npm ile gelen qrcode-terminal paketinin vendor/QRCode kopyası) karşılaştırmak için yardımcı.
   tests/test_v241_iki_adim.py çalıştırır; paket bulunamazsa test atlanır. Girdi: argv[2] = vendor/QRCode klasörü,
   stdin = JSON [[metin, sürüm, maske], ...]. Çıktı: JSON [["0101…", …], …] (satır başına bir dizgi, 1 = koyu). */
'use strict';
const QRCode = require(process.argv[2]);
const QRErrorCorrectLevel = require(require('path').join(process.argv[2], 'QRErrorCorrectLevel'));
let girdi = '';
process.stdin.on('data', (d) => { girdi += d; });
process.stdin.on('end', () => {
  const sonuc = JSON.parse(girdi).map(([metin, surum, maske]) => {
    const qr = new QRCode(surum, QRErrorCorrectLevel.M);
    qr.addData(metin);
    qr.makeImpl(false, maske);
    const satirlar = [];
    for (let r = 0; r < qr.getModuleCount(); r++) {
      let s = '';
      for (let c = 0; c < qr.getModuleCount(); c++) s += qr.isDark(r, c) ? '1' : '0';
      satirlar.push(s);
    }
    return satirlar;
  });
  process.stdout.write(JSON.stringify(sonuc));
});

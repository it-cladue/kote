/* 2.3.4: personel bazında kanıt özeti — süzgeç çubuğu (değişince gönder), tablo sıralama ve yazdırma. Bağımlılık yok. */
(function () {
  'use strict';
  function hepsi(sec, kok) { return Array.prototype.slice.call((kok || document).querySelectorAll(sec)); }

  /* 2.3.4: süzgeç değişince form gönderilir; "Özel aralık" seçilince önce tarih alanları açılır (Uygula ile gönderilir).
     Klavye: dönem/grup düğmelerinde ok tuşları her basışta sayfayı yenilemez; Enter/Boşluk, gruptan çıkış ya da
     son ok tuşundan ~600 ms sonra gönderilir. Fare/dokunma ile seçim hemen gönderilir. */
  var OK_TUSLARI = { ArrowLeft: 1, ArrowRight: 1, ArrowUp: 1, ArrowDown: 1 };
  hepsi('[data-po-form]').forEach(function (form) {
    var tarihler = form.querySelector('[data-po-tarihler]');
    var okIle = false, bekleyen = null;
    function gonder() {
      if (bekleyen) { clearTimeout(bekleyen); bekleyen = null; }
      form.classList.add('po-yukleniyor');
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    }
    function radyoMu(t) { return t && t.type === 'radio' && t.hasAttribute('data-po-degisim'); }
    form.addEventListener('keydown', function (e) {
      if (!radyoMu(e.target)) return;
      if (OK_TUSLARI[e.key]) { okIle = true; return; }
      if (e.key === 'Enter' || ((e.key === ' ' || e.key === 'Spacebar') && e.target.checked)) {
        e.preventDefault();
        if (bekleyen) gonder();
        else if (e.key === 'Enter' && !(e.target.name === 'donem' && e.target.value === 'ozel')) gonder();
      }
    });
    form.addEventListener('pointerdown', function () { okIle = false; });
    form.addEventListener('focusout', function (e) {
      if (!bekleyen || !radyoMu(e.target)) return;
      var grup = e.target.closest('.po-segment-grup');
      if (!e.relatedTarget || !grup || !grup.contains(e.relatedTarget)) gonder();
    });
    form.addEventListener('change', function (e) {
      var t = e.target, klavye = okIle;
      okIle = false;
      if (!t || !t.hasAttribute || !t.hasAttribute('data-po-degisim')) return;
      if (bekleyen) { clearTimeout(bekleyen); bekleyen = null; }
      if (t.name === 'donem' && tarihler) {
        var ozel = t.value === 'ozel';
        tarihler.hidden = !ozel;
        if (ozel) { var ilk = tarihler.querySelector('input'); if (ilk && !klavye) ilk.focus(); return; }
        hepsi('input', tarihler).forEach(function (i) { i.value = ''; });
      }
      if (klavye && radyoMu(t)) { bekleyen = setTimeout(gonder, 600); return; }
      gonder();
    });
    form.addEventListener('submit', function () {
      if (tarihler && tarihler.hidden) hepsi('input', tarihler).forEach(function (i) { i.disabled = true; });
    });
  });

  /* 2.3.4: sütun başlığına tıklayınca istemci tarafında sıralama (toplam satırı tfoot'ta kalır). */
  hepsi('table[data-po-sirala]').forEach(function (tablo) {
    var govde = tablo.tBodies[0]; if (!govde) return;
    var basliklar = hepsi('thead th', tablo);
    basliklar.forEach(function (th, sira) {
      var dugme = th.querySelector('[data-po-sirala-dugme]'); if (!dugme) return;
      dugme.addEventListener('click', function () {
        var sayi = th.getAttribute('data-tur') === 'sayi';
        var simdiki = th.getAttribute('aria-sort');
        var yon = simdiki ? (simdiki === 'descending' ? 'ascending' : 'descending') : (sayi ? 'descending' : 'ascending');
        basliklar.forEach(function (b) { b.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', yon);
        var satirlar = hepsi(':scope > tr', govde).filter(function (tr) { return tr.cells.length > sira; });
        satirlar.sort(function (a, b) {
          var x = a.cells[sira].getAttribute('data-deger') || '', y = b.cells[sira].getAttribute('data-deger') || '';
          var f = sayi ? (parseFloat(x) || 0) - (parseFloat(y) || 0) : x.localeCompare(y, 'tr', { sensitivity: 'base', numeric: true });
          if (f === 0) f = (a.cells[0].getAttribute('data-deger') || '').localeCompare(b.cells[0].getAttribute('data-deger') || '', 'tr', { numeric: true }) * (yon === 'descending' ? -1 : 1);
          return yon === 'descending' ? -f : f;
        });
        satirlar.forEach(function (tr) { govde.appendChild(tr); });
      });
    });
  });

  /* 2.3.4: Yazdır düğmesi doğrudan yazdırma penceresini açar; ?yazdir=1 ile açılan sayfa da kendiliğinden açar. */
  hepsi('[data-po-yazdir-dugme]').forEach(function (a) {
    a.addEventListener('click', function (e) { if (window.print) { e.preventDefault(); window.print(); } });
  });
  if (document.querySelector('[data-po-yazdir]') && window.print) {
    window.addEventListener('load', function () { setTimeout(function () { window.print(); }, 300); });
  }
})();

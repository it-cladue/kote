/* 2.3.4: personel bazında kanıt özeti — süzgeç çubuğu (değişince gönder), tablo sıralama ve yazdırma. Bağımlılık yok.
   2.3.5: kişi kartları ("Daha fazla göster" / "Daha az göster") ve rapor sayfasında hatırlanan süzgeçler. */
(function () {
  'use strict';
  function hepsi(sec, kok) { return Array.prototype.slice.call((kok || document).querySelectorAll(sec)); }

  /* 2.3.5: hatırlanan süzgeçler. Rapor sayfasında Uygula / otomatik gönderimde süzgeçler bu kullanıcıya özel anahtarla
     (kp.raporSuzgec.<kullanıcı>) tarayıcıda saklanır. Adres hiç parametre taşımadan açılırsa saklanan süzgeçlerle aynı
     sayfaya bir kez yönlendirilir (&hatirlanan=1 notu gösterir). Döngü koruması: yönlendirmeden önce sessionStorage bayrağı
     konur, hedef sayfa bayrağı kaldırır; bayrak kalmışsa (hedefe ulaşılamadı) saklanan süzgeç silinir ve varsayılan kalır.
     Artık yetkisi olmayan proje saklanmışsa yönlendirilmez (sunucu 403 verirdi): varsayılan görünüm açılır. */
  var HATIRLA_ADLAR = ['proje', 'donem', 'tarih1', 'tarih2', 'durum', 'grup', 'sutun', 'kategori'];
  var BAYRAK = 'kp.raporSuzgec.yonlendirme';
  function depo(ad) { try { return window[ad] || null; } catch (_) { return null; } }
  function oku(d, k) { try { return d ? d.getItem(k) : null; } catch (_) { return null; } }
  function yaz(d, k, v) { try { if (d) { if (v === null) d.removeItem(k); else d.setItem(k, v); } } catch (_) {} }
  function formSuzgeci(form) {
    var p = new URLSearchParams();
    if (!form) return p;
    new FormData(form).forEach(function (v, k) { if (HATIRLA_ADLAR.indexOf(k) >= 0 && v && !p.has(k)) p.set(k, v); });
    return p;
  }
  function secenekVar(form, ad, deger) {
    return hepsi('[name="' + ad + '"]', form).some(function (el) {
      if (el.tagName === 'SELECT') return !el.disabled && hepsi('option', el).some(function (o) { return o.value === deger; });
      return el.type === 'radio' && el.value === deger;
    });
  }
  /* Saklanan metni bu sayfadaki seçeneklerle doğrular; kullanılabilir sorgu metni ya da '' döndürür. */
  function gecerliSuzgec(metin, form) {
    if (!metin || !form) return '';
    var gelen; try { gelen = new URLSearchParams(metin); } catch (_) { return ''; }
    var p = gelen.get('proje');
    if (p && !secenekVar(form, 'proje', p)) return null;  // yetkisi kalkmış proje: varsayılana dön
    var out = new URLSearchParams();
    HATIRLA_ADLAR.forEach(function (ad) {
      var v = gelen.get(ad);
      if (!v) return;
      if (ad === 'tarih1' || ad === 'tarih2') { if (/^\d{4}-\d{2}-\d{2}$/.test(v) && gelen.get('donem') === 'ozel') out.set(ad, v); return; }
      if (secenekVar(form, ad, v)) out.set(ad, v);
    });
    var simdiki = formSuzgeci(form); simdiki.sort(); out.sort();
    return out.toString() === simdiki.toString() ? '' : out.toString();  // varsayılanla aynıysa yönlendirmeye gerek yok
  }
  var raporSayfa = document.getElementById('rapor-personel');
  var hatirlaAnahtar = raporSayfa && raporSayfa.getAttribute('data-po-hatirla');
  if (hatirlaAnahtar) {
    var ls = depo('localStorage'), ss = depo('sessionStorage');
    var raporForm = raporSayfa.querySelector('[data-po-form]');
    if (raporSayfa.hasAttribute('data-po-sifirla')) {
      yaz(ls, hatirlaAnahtar, null); yaz(ss, BAYRAK, null);
      try { history.replaceState(null, '', location.pathname); } catch (_) {}
    } else if (!location.search || location.search === '?') {
      if (oku(ss, BAYRAK)) { yaz(ss, BAYRAK, null); yaz(ls, hatirlaAnahtar, null); }
      else if (ss) {
        var sorgu = gecerliSuzgec(oku(ls, hatirlaAnahtar), raporForm);
        if (sorgu === null) yaz(ls, hatirlaAnahtar, null);
        else if (sorgu) {
          yaz(ss, BAYRAK, '1');
          location.replace(location.pathname + '?' + sorgu + '&hatirlanan=1');
          return;
        }
      }
    } else yaz(ss, BAYRAK, null);
    if (raporForm) raporForm.addEventListener('submit', function () {
      // Boş alanlar (ör. özel aralık dışındaki tarih kutuları) saklanmaz.
      var p = formSuzgeci(raporForm);
      yaz(ls, hatirlaAnahtar, p.toString() || null);
    });
    hepsi('[data-po-not-kapat]').forEach(function (b) {
      b.addEventListener('click', function () { var n = b.closest('[data-po-hatirlanan-not]'); if (n) n.hidden = true; });
    });
  }

  /* 2.3.5: kişi kartları — ilk 6 görünür; "Daha fazla göster" her basışta 12 kart daha açar ve odağı ilk yeni kartın
     bağlantısına taşır; "Daha az göster" ilk 6'ya döner. Kartların hepsi HTML'dedir (gizliler hidden), sayfa yenilenmez. */
  hepsi('[data-po-kartlar]').forEach(function (kutu) {
    var kartlar = hepsi('[data-po-kart]', kutu);
    var dugmeler = kutu.querySelector('[data-po-kart-dugmeler]');
    if (!dugmeler) return;
    var fazla = dugmeler.querySelector('[data-po-daha-fazla]'), az = dugmeler.querySelector('[data-po-daha-az]');
    var sayac = dugmeler.querySelector('[data-po-kart-sayac]');
    var ilk = parseInt(kutu.getAttribute('data-ilk'), 10) || 6, adim = parseInt(kutu.getAttribute('data-adim'), 10) || 12;
    function gorunen() { var n = 0; while (n < kartlar.length && !kartlar[n].hidden) n++; return n; }
    function guncelle() {
      var n = gorunen(), kalan = kartlar.length - n;
      fazla.hidden = kalan <= 0;
      fazla.textContent = 'Daha fazla göster (' + kalan + ' kişi daha)';
      az.hidden = n <= ilk;
      if (sayac) sayac.textContent = n + ' / ' + kartlar.length + ' kişi gösteriliyor';
    }
    fazla.addEventListener('click', function () {
      var n = gorunen(), yeni = kartlar.slice(n, n + adim);
      yeni.forEach(function (k) { k.hidden = false; });
      guncelle();
      if (yeni[0]) {
        var hedef = yeni[0].querySelector('a[href]');
        if (!hedef) { yeni[0].setAttribute('tabindex', '-1'); hedef = yeni[0]; }
        hedef.focus();
      }
    });
    az.addEventListener('click', function () {
      kartlar.forEach(function (k, i) { k.hidden = i >= ilk; });
      guncelle();
      fazla.focus();
    });
    dugmeler.hidden = false;
    guncelle();
  });

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

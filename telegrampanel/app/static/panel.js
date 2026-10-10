/* Kanit paneli - sayfa ici islemler (modal, onay, duzenle, sil). Kutuphane yok. */
window.Panel = (function () {
  var csrf = (document.querySelector('meta[name=csrf]') || {}).content || '';
  var toastZaman = null;

  function toast(mesaj, hata) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = mesaj;
    t.className = 'toast' + (hata ? ' hata' : '');
    clearTimeout(toastZaman);
    toastZaman = setTimeout(function () { t.className = 'toast gizli'; }, hata ? 5000 : 2500);
  }

  function post(url, veri) {
    var fd = new URLSearchParams();
    Object.keys(veri || {}).forEach(function (k) { fd.append(k, veri[k]); });
    return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRF': csrf } })
      .then(function (r) {
        if (r.status === 403) throw new Error('Bu işlem için yetkiniz yok.');
        if (!r.ok) throw new Error('Sunucu hatası (' + r.status + ')');
        return r.json();
      });
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  // ---------------- kayit sayfasi ----------------
  function kayitSayfasi(durumFiltresi) {
    var modal = document.getElementById('modal');
    if (!modal) return;
    var kartlar = Array.prototype.slice.call(document.querySelectorAll('.kayit[data-id]'));
    var idler = kartlar.map(function (e) { return parseInt(e.getAttribute('data-id'), 10); });
    var acikId = null, acikKayit = null;

    kartlar.forEach(function (e) { e.addEventListener('click', function () { ac(parseInt(e.getAttribute('data-id'), 10)); }); });
    modal.querySelector('.modal-kapat').addEventListener('click', kapat);
    modal.querySelector('.modal-onceki').addEventListener('click', function () { adim(-1); });
    modal.querySelector('.modal-sonraki').addEventListener('click', function () { adim(1); });
    modal.addEventListener('click', function (ev) { if (ev.target === modal) kapat(); });
    document.addEventListener('keydown', function (ev) {
      if (modal.classList.contains('gizli')) return;
      if (ev.key === 'Escape') kapat();
      if (ev.key === 'ArrowLeft' && !duzenleAcik()) adim(-1);
      if (ev.key === 'ArrowRight' && !duzenleAcik()) adim(1);
    });
    var form = document.getElementById('m-duzenle');
    form.addEventListener('submit', function (ev) { ev.preventDefault(); duzenleKaydet(); });
    document.getElementById('m-duzenle-iptal').addEventListener('click', function () { form.classList.add('gizli'); });

    function duzenleAcik() { return !form.classList.contains('gizli'); }
    // Excel'de degisiklik: pencere kapaliysa listeyi sessizce yenile, acik ise serit goster ve pencere kapaninca yenile
    var yenileBekliyor = false, serit = document.getElementById('degisiklik-serit');
    document.addEventListener('kp:degisti', function () {
      if (modal.classList.contains('gizli')) { location.reload(); return; }
      yenileBekliyor = true; if (serit) serit.classList.remove('gizli');
    });
    if (serit) document.getElementById('degisiklik-yenile').addEventListener('click', function (ev) { ev.preventDefault(); location.reload(); });
    function adim(d) {
      var i = idler.indexOf(acikId);
      if (i < 0) return;
      var j = i + d;
      if (j >= 0 && j < idler.length) ac(idler[j]);
    }
    function kapat() {
      modal.classList.add('gizli'); modal.setAttribute('aria-hidden', 'true'); acikId = null;
      if (yenileBekliyor) setTimeout(function () { location.reload(); }, 300);
    }
    // Bildirimden gelen ?ac=<id>: pencereyi hemen ac, adresi temizle (yenilemede tekrar acilmasin)
    var acParam = new URLSearchParams(location.search).get('ac');
    if (acParam) {
      var u = new URL(location.href); u.searchParams.delete('ac'); history.replaceState(null, '', u.pathname + u.search);
      ac(parseInt(acParam, 10));
    }

    function ac(id) {
      acikId = id;
      modal.classList.remove('gizli'); modal.setAttribute('aria-hidden', 'false');
      form.classList.add('gizli');
      document.getElementById('m-alanlar').innerHTML = '<dt>Yükleniyor…</dt><dd></dd>';
      document.getElementById('m-butonlar').innerHTML = '';
      fetch('/kayit/' + id, { credentials: 'same-origin' })
        .then(function (r) { if (!r.ok) throw new Error('Kayıt okunamadı (' + r.status + ')'); return r.json(); })
        .then(function (k) { if (acikId === id) goster(k); })
        .catch(function (e) { toast(e.message, true); });
    }

    function goster(k) {
      acikKayit = k;
      var proje = document.getElementById('m-proje');
      proje.textContent = k.proje; proje.style.background = k.renk; proje.style.color = yaziRengi(k.renk);
      document.getElementById('m-kategori').textContent = k.kategori || '';
      document.getElementById('m-kt').classList.toggle('gizli', !k.kt);
      var durum = [];
      if (k.silindi) durum.push('<span class="etiket-kucuk kirmizi-arka">silindi' + (k.silen ? ' (' + esc(k.silen) + ')' : '') + '</span>');
      else if (k.excel_durum === 'silinmis') durum.push('<span class="etiket-kucuk gri-arka">Excel\'de yok</span>');
      if (k.bekleyen_hata) durum.push('<span class="etiket-kucuk kirmizi-arka" title="' + esc(k.bekleyen_hata) + '">Excel hatası: ' + esc(k.bekleyen_hata) + '</span>');
      else if (k.bekleyen_islem) durum.push('<span class="etiket-kucuk turuncu-arka">Excel\'e yazılıyor…</span>');
      document.getElementById('m-durum').innerHTML = durum.join(' ');

      var img = document.getElementById('m-gorsel'), yok = document.getElementById('m-gorsel-yok'), lnk = document.getElementById('m-gorsel-link');
      img.removeAttribute('src');
      if (k.gorsel_url && (k.gorsel_kaynak === 'yerel' || k.gorsel_kaynak === 'gyazo_onbellek' || k.gorsel_kaynak === 'gyazo_dis')) {
        img.src = k.gorsel_url + '?v=' + (k.guncelleme || '');
        img.classList.remove('gizli'); yok.classList.add('gizli');
        lnk.href = k.dis_link || k.gorsel_url;
        img.onerror = function () { img.classList.add('gizli'); yok.classList.remove('gizli'); yok.innerHTML = 'Görsel şu an açılamadı.' + (k.dis_link ? '<br><a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">Linki yeni sekmede aç</a>' : ''); };
      } else {
        img.classList.add('gizli'); yok.classList.remove('gizli');
        yok.innerHTML = k.dis_link ? 'Bu kayıtta yerel görsel yok.<br><a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">' + esc(k.dis_link) + '</a>' : 'Görsel yok';
        lnk.removeAttribute('href');
      }

      var alanlar = [
        ['Personel kodu', k.personel, 'buyuk'], ['Üye ID', k.uye_id], ['Ana üye ID', k.ana_uye_id], ['Tür', k.tip],
        ['Tarih', k.tarih || k.tarih_ham], ['Ekleyen', k.ekleyen_ad ? (k.ekleyen_ad + (k.ekleyen_id ? ' (' + k.ekleyen_id + ')' : '') + (k.ekleyen_guven === 'tahmini' ? ' ~' : '')) : (k.ekleyen_id || '')],
        ['Açıklama', k.aciklama], ['Excel satırı', k.excel_satir ? (k.proje + ' / ' + k.excel_satir) : ''],
        ['Onay', k.kt ? ('✔ ' + (k.kt_kaynak === 'panel' ? (k.kt_kim || 'panel') + (k.kt_zaman ? ' · ' + k.kt_zaman : '') : 'Excel')) : 'bekliyor']
      ];
      document.getElementById('m-alanlar').innerHTML = alanlar.filter(function (a) { return a[1] !== null && a[1] !== undefined && a[1] !== ''; })
        .map(function (a) { return '<dt>' + esc(a[0]) + '</dt><dd class="' + (a[2] || '') + '">' + esc(a[1]) + '</dd>'; }).join('');
      document.getElementById('m-link').innerHTML = k.dis_link
        ? 'Link: <a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">' + esc(k.dis_link) + '</a> <button class="btn kucuk" type="button" data-kopyala="' + esc(k.dis_link) + '">kopyala</button>'
        : (k.link ? 'Link alanı: ' + esc(k.link) : '');

      var b = [];
      if (!k.silindi) {
        if (k.izin_kt) b.push(k.kt ? '<button class="btn" data-islem="kt" data-deger="0">Onayı kaldır</button>' : '<button class="btn basari" data-islem="kt" data-deger="1">✔ Onayla</button>');
        if (k.izin_duzenle) b.push('<button class="btn" data-islem="duzenle">✎ Düzenle</button>');
        if (k.izin_sil) b.push('<button class="btn tehlike" data-islem="sil">🗑 Sil</button>');
      } else if (k.izin_sil && k.geri_al_olur) {
        b.push('<button class="btn" data-islem="geri_al">↩ Geri al (Excel\'e yeniden ekle)</button>');
      } else if (k.izin_sil) {
        b.push('<span class="kucukyazi">Silme işlemi bota ulaşınca geri alınabilir.</span>');
      }
      var kutu = document.getElementById('m-butonlar');
      kutu.innerHTML = b.join('');
      Array.prototype.forEach.call(kutu.querySelectorAll('button'), function (btn) { btn.addEventListener('click', function () { islem(btn.getAttribute('data-islem'), btn); }); });

      var g = document.getElementById('m-gecmis');
      g.innerHTML = (k.gecmis || []).map(function (h) { return '<li><b>' + esc(h.zaman) + '</b> ' + esc(h.kullanici) + ' · ' + esc(h.islem) + (h.yeni ? ' → ' + esc(h.yeni) : '') + '</li>'; }).join('') || '<li>Kayıt yok</li>';
    }

    function islem(ad, btn) {
      var k = acikKayit;
      if (!k) return;
      if (ad === 'duzenle') {
        ['personel', 'uye_id', 'ana_uye_id', 'tip', 'kategori', 'aciklama'].forEach(function (f) { form.elements[f].value = k[f] || ''; });
        form.classList.remove('gizli'); form.elements.personel.focus();
        return;
      }
      if (ad === 'sil' && !confirm('Bu kayıt Excel\'den SİLİNECEK (' + (k.personel || '') + ' / ' + (k.proje) + '). Emin misiniz?')) return;
      if (ad === 'geri_al' && !confirm('Kayıt Excel\'e yeniden eklenecek. Emin misiniz?')) return;
      var url = '/kayit/' + k.id + '/' + (ad === 'geri_al' ? 'geri-al' : ad);
      var veri = ad === 'kt' ? { deger: btn.getAttribute('data-deger') } : {};
      btn.disabled = true;
      post(url, veri).then(function (r) {
        if (!r.ok) throw new Error(r.hata || 'işlem yapılamadı');
        toast(ad === 'kt' ? (r.kt ? 'Onaylandı ✔ (Excel\'e yazılıyor)' : 'Onay kaldırıldı') : ad === 'sil' ? 'Silindi (Excel\'den kaldırılıyor)' : 'Geri alındı');
        kartGuncelle(k.id, ad, r);
        ac(k.id);
      }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
    }

    function duzenleKaydet() {
      var k = acikKayit; if (!k) return;
      var veri = {};
      ['personel', 'uye_id', 'ana_uye_id', 'tip', 'kategori', 'aciklama'].forEach(function (f) { veri[f] = form.elements[f].value.trim(); });
      post('/kayit/' + k.id + '/duzenle', veri).then(function (r) {
        if (!r.ok) throw new Error(r.hata || 'kaydedilemedi');
        toast(r.degisiklik === false ? 'Değişiklik yok' : 'Kaydedildi (Excel\'e yazılıyor)');
        form.classList.add('gizli');
        var kart = document.querySelector('.kayit[data-id="' + k.id + '"]');
        if (kart) { var p = kart.querySelector('.satir1 b, figcaption b, td:nth-child(4) b'); if (p) p.textContent = veri.personel || '—'; }
        ac(k.id);
      }).catch(function (e) { toast(e.message, true); });
    }

    function kartGuncelle(id, ad, r) {
      var kart = document.querySelector('.kayit[data-id="' + id + '"]');
      if (!kart) return;
      var listedenCikar = (ad === 'kt' && durumFiltresi === 'bekleyen' && r.kt) || (ad === 'kt' && durumFiltresi === 'onayli' && !r.kt) ||
        (ad === 'sil' && durumFiltresi !== 'hepsi' && durumFiltresi !== 'silinen') || (ad === 'geri_al' && durumFiltresi === 'silinen');
      if (listedenCikar) { kart.style.opacity = '.35'; kart.classList.add('cikarildi'); }
      if (ad === 'kt') kart.classList.toggle('onayli', !!r.kt);
      if (ad === 'sil') kart.classList.add('silik');
      if (ad === 'geri_al') kart.classList.remove('silik');
    }
  }

  function yaziRengi(hex) {
    try { var h = (hex || '#999').replace('#', ''); if (h.length === 3) h = h.replace(/(.)/g, '$1$1'); var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16); return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#111' : '#fff'; } catch (e) { return '#fff'; }
  }

  function kopyala(metin) {
    if (navigator.clipboard) navigator.clipboard.writeText(metin).then(function () { toast('Kopyalandı'); });
    else { var i = document.createElement('input'); i.value = metin; document.body.appendChild(i); i.select(); document.execCommand('copy'); i.remove(); toast('Kopyalandı'); }
  }

  // ---------------- canli yenileme ve yeni kayit bildirimleri (her sayfada) ----------------
  var BILDIRIM_SN = 20;
  function bildirimler() {
    var zil = document.getElementById('zil'), kutu = document.getElementById('bildirim-kutu'), liste = document.getElementById('bildirim-liste'), sayi = document.getElementById('zil-sayi');
    if (!zil || !kutu) return;
    var son = parseInt(localStorage.getItem('kp_son_id') || '-1', 10), degisiklik = localStorage.getItem('kp_degisiklik'), okunmamis = 0, ilk = true;
    var izinKutu = document.getElementById('bildirim-izin');
    if (window.Notification && Notification.permission === 'default' && izinKutu) izinKutu.classList.remove('gizli');
    var izinBtn = document.getElementById('bildirim-izin-btn');
    if (izinBtn) izinBtn.addEventListener('click', function () { Notification.requestPermission().then(function () { izinKutu.classList.add('gizli'); }); });
    zil.addEventListener('click', function () { kutu.classList.toggle('gizli'); okunmamis = 0; sayi.classList.add('gizli'); });
    document.getElementById('bildirim-temizle').addEventListener('click', function () { liste.innerHTML = ''; kutu.classList.add('gizli'); try { localStorage.removeItem('kp_bildirimler'); } catch (e) {} });
    // onceki oturumdan kalan bildirimler
    try { var eski = JSON.parse(localStorage.getItem('kp_bildirimler') || '[]'); eski.slice(0, 20).forEach(function (k) { ekle(k, false); }); } catch (e) {}

    function link(k) { return '/kayitlar?proje=' + encodeURIComponent(k.proje) + '&durum=' + (k.kt ? 'hepsi' : 'bekleyen') + '&ac=' + k.id; }
    function ekle(k, yeni) {
      var li = document.createElement('li');
      if (yeni) li.className = 'yeni';
      li.innerHTML = '<span class="rozet" style="background:' + esc(k.renk || '#999') + ';color:' + yaziRengi(k.renk || '#999') + '">' + esc(k.proje) + '</span> <b>' + esc(k.personel || '—') + '</b> ' + esc(k.kategori || '') +
        ' <small>' + esc((k.tarih || '').slice(0, 16)) + (k.ekleyen_ad ? ' · ' + esc(k.ekleyen_ad) : '') + '</small><br><a class="kontrol" href="' + link(k) + '">Kontrol et →</a>';
      liste.insertBefore(li, liste.firstChild);
      while (liste.children.length > 30) liste.removeChild(liste.lastChild);
    }
    function goster(yeniler) {
      var sakla = [];
      try { sakla = JSON.parse(localStorage.getItem('kp_bildirimler') || '[]'); } catch (e) {}
      yeniler.slice().reverse().forEach(function (k) { ekle(k, true); sakla.unshift(k); });
      try { localStorage.setItem('kp_bildirimler', JSON.stringify(sakla.slice(0, 30))); } catch (e) {}
      okunmamis += yeniler.length; sayi.textContent = okunmamis; sayi.classList.remove('gizli');
      kutu.classList.remove('gizli');
      var ilkK = yeniler[0];
      toast(yeniler.length === 1 ? 'Yeni kayıt eklendi: ' + ilkK.proje + ' ' + (ilkK.personel || '') + ' ' + (ilkK.kategori || '') + ' — kontrol edin' : yeniler.length + ' yeni kayıt eklendi — kontrol edin');
      if (window.Notification && Notification.permission === 'granted') {
        try {
          var n = new Notification(yeniler.length === 1 ? 'Yeni kayıt: ' + ilkK.proje + ' ' + (ilkK.personel || '') + ' ' + (ilkK.kategori || '') : yeniler.length + ' yeni kayıt eklendi',
            { body: 'Kanıt Paneli — kontrol etmek için tıklayın', tag: 'kp-yeni-' + ilkK.id });
          n.onclick = function () { window.focus(); location.href = link(ilkK); n.close(); };
        } catch (e) {}
      }
    }
    function kontrol() {
      fetch('/bildirim.json?son=' + son, { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d) return;
        if (son < 0) { son = d.maks; try { localStorage.setItem('kp_son_id', son); } catch (e) {} }
        else if (d.yeni && d.yeni.length) {
          son = d.maks; try { localStorage.setItem('kp_son_id', son); } catch (e) {}
          d.yeni.forEach(function (k) { k.renk = (window.PROJE_RENK || {})[k.proje]; });
          goster(d.yeni);
        } else if (d.maks > son) { son = d.maks; try { localStorage.setItem('kp_son_id', son); } catch (e) {} }
        if (d.degisiklik && d.degisiklik !== degisiklik) {
          var ilkKez = (degisiklik === null);
          degisiklik = d.degisiklik; try { localStorage.setItem('kp_degisiklik', degisiklik); } catch (e) {}
          if (!ilkKez || !ilk) document.dispatchEvent(new CustomEvent('kp:degisti', { detail: d }));
        }
        sayaclariGuncelle(d.sayac);
        ilk = false;
      }).catch(function () {});
    }
    function sayaclariGuncelle(sayac) {
      if (!sayac) return;
      Array.prototype.forEach.call(document.querySelectorAll('[data-sayac]'), function (el) {
        var p = el.getAttribute('data-sayac').split(':'), v = sayac[p[0]] && sayac[p[0]][p[1]];
        if (v !== undefined && String(v) !== el.textContent) { el.textContent = v; el.classList.add('sayac-degisti'); setTimeout(function () { el.classList.remove('sayac-degisti'); }, 1500); }
      });
    }
    kontrol();
    setInterval(kontrol, BILDIRIM_SN * 1000);
  }

  // ---------------- bot sayfasi: son islemler tablosunu yenile ----------------
  function botSayfasi() {
    var tablo = document.getElementById('islemler-tablo');
    if (!tablo) return;
    var sonDurum = null;
    function yenile() {
      fetch('/bot/islemler.json', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d) return;
        var tb = tablo.querySelector('tbody');
        var imza = JSON.stringify(d.islemler.map(function (i) { return [i.id, i.durum]; }));
        if (imza === sonDurum) return;
        var degisti = sonDurum !== null;
        sonDurum = imza;
        tb.innerHTML = d.islemler.length ? d.islemler.map(function (i) {
          var durum = i.durum === 'ok' ? '<span class="yesil">ok</span>' : i.durum === 'hata' ? '<b class="kirmizi">hata</b>' : '<span class="turuncu">bekliyor…</span>';
          return '<tr><td class="nowrap">' + esc(i.zaman) + '</td><td>' + esc(i.ozet) + '</td><td>' + esc(i.kullanici) + '</td><td>' + durum + '</td><td class="kucukyazi">' + esc(i.mesaj || '') + (i.sonuc_zaman ? ' <small>(' + esc(i.sonuc_zaman) + ')</small>' : '') + '</td></tr>';
        }).join('') : '<tr><td colspan="5">Henüz işlem yok.</td></tr>';
        var b = document.getElementById('islem-bekleyen');
        if (b) { b.textContent = 'bekleyen: ' + d.bekleyen; b.classList.toggle('gizli', !d.bekleyen); }
        if (degisti && !d.bekleyen) { toast('Bot işlemleri uyguladı; sayfa yenileniyor'); setTimeout(function () { location.reload(); }, 1200); }
      }).catch(function () {});
    }
    setInterval(yenile, 10000);
  }

  // Satir ici JS kullanilmaz: onay sorulari data-onay, kopyalama data-kopyala ile
  document.addEventListener('submit', function (ev) { var f = ev.target; if (f && f.getAttribute && f.getAttribute('data-onay') && !confirm(f.getAttribute('data-onay'))) ev.preventDefault(); });
  document.addEventListener('click', function (ev) { var b = ev.target.closest ? ev.target.closest('[data-kopyala]') : null; if (b) { ev.preventDefault(); kopyala(b.getAttribute('data-kopyala')); } });

  return { kayitSayfasi: kayitSayfasi, botSayfasi: botSayfasi, bildirimler: bildirimler, toast: toast, kopyala: kopyala };
})();

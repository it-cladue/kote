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
        if (degisti && !d.bekleyen && modal.classList.contains('gizli')) { toast('Bot işlemleri uyguladı; sayfa yenileniyor'); setTimeout(function () { location.reload(); }, 1200); }
      }).catch(function () {});
    }
    setInterval(yenile, 10000);

    // ---- Telegram kullanici detayi: canli oturum + istatistik (botun /kullanici_durum komutunun genisi) ----
    var modal = document.getElementById('tg-modal'), icerik = document.getElementById('tg-icerik');
    var acikTg = null, sayac = null;
    var ADIMLAR = ['proje', 'kategori', 'personel', 'uyeid', 'anaid', 'tip', 'kayit_secim', 'ozet'];
    var ADIM_AD = { proje: 'Proje seçiyor', kategori: 'Kategori seçiyor', personel: 'Personel kodu yazması bekleniyor', uyeid: 'Üye ID yazması bekleniyor',
      anaid: 'Ana üye ID yazması bekleniyor', tip: 'Sessiz / Telesekreter seçimi bekleniyor', kayit_secim: 'Gyazo mu, dosya mı? seçimi bekleniyor',
      gyazo_bakim: 'Gyazo bakım uyarısında (dosyaya kaydet / iptal)', ozet: 'SON KONTROL ekranında: Onayla / İptal bekleniyor', lead_onay: 'Lead ID onayı bekleniyor (yazılı giriş)' };
    var ADIM_KISA = { proje: 'Proje', kategori: 'Kategori', personel: 'Personel', uyeid: 'Üye ID', anaid: 'Ana ID', tip: 'Tür', kayit_secim: 'Gyazo/dosya', ozet: 'Onay' };
    function cip(p) { var r = (window.PROJE_RENK || {})[p] || '#6b7280'; return '<span class="proje-cip" style="--renk:' + esc(r) + ';--cipyazi:' + (acik(r) ? '#111' : '#fff') + '">' + esc(p) + '</span>'; }
    function acik(hex) { var m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || ''); if (!m) return false; return (parseInt(m[1], 16) * 299 + parseInt(m[2], 16) * 587 + parseInt(m[3], 16) * 114) / 1000 > 150; }
    function sayiListe(obj) { var k = Object.keys(obj || {}); if (!k.length) return '<span class="gri">yok</span>'; return k.sort().map(function (x) { return '<b>' + esc(x) + '</b> ' + esc(obj[x]); }).join(' · '); }
    function form(islem, etiket, sinif, onay, ekstra) {
      return '<form method="post" class="satir-form"' + (onay ? ' data-onay="' + esc(onay) + '"' : '') + '><input type="hidden" name="csrf" value="' + esc(csrf) + '"><input type="hidden" name="islem" value="' + islem + '"><input type="hidden" name="tg_id" value="' + esc(acikTg) + '">' + (ekstra || '') + '<button class="btn kucuk ' + (sinif || '') + '">' + etiket + '</button></form>';
    }
    function ciz(d) {
      var ad = [d.username, d.first_name].filter(Boolean).join(' / ') || '(ad yok)';
      var h = '<div class="detay-baslik"><h3>' + esc(ad) + ' <code>' + esc(d.id) + '</code></h3>';
      h += d.engelli ? '<b class="kirmizi">ENGELLİ</b> <small>' + esc(d.engel_sebep) + ' ' + esc(d.engel_tarihi) + '</small>' : d.onayli ? '<span class="yesil">onaylı</span> <small>' + esc(d.onay_tarihi) + '</small>' : '<span class="gri">onaysız (şifre yazmadı)</span>';
      h += '<small class="kucukyazi"><span class="canli-nokta"></span>canlı · ' + esc(d.zaman) + '</small></div>';
      h += '<div class="modal-butonlar">';
      if (d.engelli) h += form('engel_kaldir', 'Engeli kaldır', '', 'Engel kaldırılsın mı? Deneme sayacı ve oturum da sıfırlanır.');
      else { h += d.onayli ? form('onay_kaldir', 'Onayı kaldır', '', 'Onay kaldırılsın mı? Kullanıcı yeniden şifre yazmak zorunda kalır (/onayli_sil).') : form('onayla', '✔ Onayla', 'basari', '', '<input type="hidden" name="ad" value="' + esc(d.username) + '">');
        h += form('engelle', 'Engelle', 'tehlike', 'Bu kullanıcı engellensin mi?', '<input type="hidden" name="ad" value="' + esc(d.username) + '"><input type="hidden" name="sebep" value="panel">'); }
      if (d.oturum) h += form('oturum_temizle', '🧹 Oturumu temizle', '', 'Yarım kalan oturum silinsin mi? Kullanıcı baştan başlar.');
      h += form('tam_sifirla', '♻ Tam sıfırla', 'tehlike', 'Engel + onay + deneme + oturum birlikte temizlenir, kullanıcı yeniden şifreye düşer (/engel_kaldir_sifirla). Emin misiniz?');
      h += '</div><div class="detay-izgara">';
      // oturum
      var o = d.oturum;
      h += '<div class="detay-kutu' + (o ? ' oturum-aktif' : '') + '"><h4>Şu an nerede? <small>(canlı oturum)</small></h4>';
      if (!o) { h += '<p class="kucukyazi" style="margin:0">Açık oturum yok: ya hiç başlamadı ya da son kaydı tamamladı.' + (d.status ? ' Bot durumu: <b>' + esc(d.status) + '</b>' : '') + '</p>'; }
      else {
        var adim = o.adim || o.step || '';
        h += '<div><span class="adim-rozet">' + esc(ADIM_AD[adim] || ('Adım: ' + adim)) + '</span></div>';
        var i = ADIMLAR.indexOf(adim);
        h += '<div class="adim-akis">' + ADIMLAR.map(function (a, j) { return '<span class="' + (i < 0 ? '' : j < i ? 'gecti' : j === i ? 'simdi' : '') + '">' + esc(ADIM_KISA[a]) + '</span>'; }).join('') + '</div>';
        var al = [['Proje', o.proje ? cip(String(o.proje).toUpperCase()) : ''], ['Kategori', o.kategori ? esc(String(o.kategori).toUpperCase()) : ''], ['Personel', esc(o.personel)], ['Üye ID', esc(o.uyeid)], ['Ana ID', esc(o.anaid)], ['Tür', esc(o.tip)],
          ['Giriş tipi', esc(o.girisTipi === 'yazili' ? 'yazılı (Lead ID ' + (o.leadId || '') + ')' : o.girisTipi || 'resim')], ['Görsel', o.gorsel_var ? '✔ alındı' + (o.kayitModu ? ' (' + esc(o.kayitModu) + ')' : '') : '<span class="gri">henüz yok</span>']];
        h += '<dl style="margin-top:8px">' + al.filter(function (a) { return a[1]; }).map(function (a) { return '<dt>' + a[0] + '</dt><dd>' + a[1] + '</dd>'; }).join('') + '</dl>';
      }
      h += '</div>';
      // bot sayaclari + durum
      h += '<div class="detay-kutu"><h4>Bot defteri <small>(kullanicilar.json)</small></h4><dl>';
      h += '<dt>Son görülme</dt><dd>' + esc(d.last_seen || '-') + '</dd><dt>Bot durumu</dt><dd>' + esc(d.status || '-') + '</dd><dt>Hatalı şifre denemesi</dt><dd>' + (d.deneme ? '<b class="turuncu">' + d.deneme + '</b>' : '0') + '</dd>';
      h += '<dt>Eklediği kayıt (bot)</dt><dd><b>' + d.bot_sayac.kayit + '</b></dd><dt>Son kayıt</dt><dd>' + esc([d.bot_sayac.son_tarih, d.bot_sayac.son_proje, d.bot_sayac.son_kategori].filter(Boolean).join(' / ') || '-') + '</dd>';
      h += '<dt>Proje dağılımı</dt><dd>' + sayiListe(d.bot_sayac.proje) + '</dd><dt>Kategori dağılımı</dt><dd>' + sayiListe(d.bot_sayac.kategori) + '</dd></dl></div>';
      // panel istatistigi
      var p = d.panel;
      h += '<div class="detay-kutu"><h4>Paneldeki kayıtları <small>(ekleyen = bu kullanıcı)</small></h4>';
      h += '<p style="margin:0 0 6px"><b>' + p.toplam + '</b> kayıt · <span class="yesil">' + p.onayli + ' onaylı</span> · <span class="turuncu">' + p.bekleyen + ' bekliyor</span>' + (p.silinen ? ' · <span class="kirmizi">' + p.silinen + ' silinmiş</span>' : '') + '</p>';
      var pr = Object.keys(p.capraz || {}).sort();
      if (pr.length) {
        h += '<table class="tablo kucuk"><thead><tr><th>Proje</th><th>Kategori</th><th>Adet</th></tr></thead><tbody>';
        pr.forEach(function (pp) { var ks = Object.keys(p.capraz[pp]).sort(); ks.forEach(function (kk, j) { h += '<tr><td>' + (j === 0 ? cip(pp) + ' <small>' + p.proje[pp] + '</small>' : '') + '</td><td>' + esc(kk) + '</td><td>' + p.capraz[pp][kk] + '</td></tr>'; }); });
        h += '</tbody></table>';
      } else h += '<p class="kucukyazi" style="margin:0">Bu kullanıcıya bağlı kayıt yok (eski kayıtlarda "ekleyen" bilgisi olmayabilir).</p>';
      h += '</div>';
      // son kayitlar
      h += '<div class="detay-kutu"><h4>Son kayıtları</h4>';
      if (p.son.length) {
        h += '<div class="kaydir" style="max-height:260px"><table class="tablo kucuk"><thead><tr><th>Tarih</th><th>Proje</th><th>Kategori</th><th>Personel</th><th>Üye</th><th>Onay</th></tr></thead><tbody>';
        p.son.forEach(function (k) { h += '<tr' + (k.silindi ? ' style="opacity:.5"' : '') + '><td class="nowrap"><a href="/kayitlar?proje=' + encodeURIComponent(k.proje) + '&durum=hepsi&ac=' + k.id + '">' + esc(k.tarih || '-') + '</a></td><td>' + cip(k.proje) + '</td><td>' + esc(k.kategori) + '</td><td>' + esc(k.personel) + '</td><td>' + esc(k.uye_id || k.ana_uye_id) + '</td><td>' + (k.silindi ? '<span class="kirmizi">silindi</span>' : k.kt ? '<span class="yesil">✔</span>' : '<span class="turuncu">bekliyor</span>') + '</td></tr>'; });
        h += '</tbody></table></div>';
      } else h += '<p class="kucukyazi" style="margin:0">Kayıt yok.</p>';
      h += '</div></div>';
      icerik.innerHTML = h;
    }
    function yukle() {
      if (!acikTg) return;
      fetch('/bot/kullanici/' + encodeURIComponent(acikTg) + '.json', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) { if (d && acikTg === d.id) ciz(d); else if (!d) icerik.innerHTML = '<p class="kirmizi">Kullanıcı bilgisi alınamadı.</p>'; }).catch(function () {});
    }
    function ac(id) {
      acikTg = String(id);
      modal.classList.remove('gizli'); modal.setAttribute('aria-hidden', 'false');
      icerik.innerHTML = '<p>Yükleniyor…</p>';
      yukle(); clearInterval(sayac); sayac = setInterval(yukle, 5000);
    }
    function kapat() { modal.classList.add('gizli'); modal.setAttribute('aria-hidden', 'true'); acikTg = null; clearInterval(sayac); }
    if (modal) {
      modal.querySelector('.modal-kapat').addEventListener('click', kapat);
      modal.addEventListener('click', function (ev) { if (ev.target === modal) kapat(); });
      document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && !modal.classList.contains('gizli')) kapat(); });
      document.addEventListener('click', function (ev) {
        var t = ev.target;
        if (t.closest && t.closest('form, a:not([data-tg-detay])') && !t.closest('[data-tg-detay]')) return;   // satirdaki butonlar / linkler
        var e = t.closest ? t.closest('[data-tg-detay]') : null;
        if (!e) return;
        if (e.tagName === 'TR' && t.closest('form')) return;
        ev.preventDefault(); ac(e.getAttribute('data-tg-detay'));
      });
      if (window.AC_TG) ac(window.AC_TG);
    }
  }

  // Satir ici JS kullanilmaz: onay sorulari data-onay, kopyalama data-kopyala ile
  document.addEventListener('submit', function (ev) { var f = ev.target, b = ev.submitter; var m = (b && b.getAttribute && b.getAttribute('data-onay')) || (f && f.getAttribute && f.getAttribute('data-onay')); if (m && !confirm(m)) ev.preventDefault(); });
  document.addEventListener('click', function (ev) { var b = ev.target.closest ? ev.target.closest('[data-kopyala]') : null; if (b) { ev.preventDefault(); kopyala(b.getAttribute('data-kopyala')); } });

  return { kayitSayfasi: kayitSayfasi, botSayfasi: botSayfasi, bildirimler: bildirimler, toast: toast, kopyala: kopyala };
})();

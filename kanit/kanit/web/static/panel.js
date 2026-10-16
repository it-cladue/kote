/* Kanıt Merkezi paneli - sayfa içi işlemler (kayıt penceresi, yorumlar, geçmiş, bildirimler, bot sayfası). Kütüphane yok, satır içi JS yok. */
(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name=csrf]') || {}).content || '';
  var toastZaman = null;
  var PROJE_RENK = {};
  try { PROJE_RENK = JSON.parse((document.getElementById('proje-renk') || {}).textContent || '{}'); } catch (e) { PROJE_RENK = {}; }

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
        return r.json().catch(function () { return {}; }).then(function (d) {
          if (r.status === 401) { location.href = '/giris'; throw new Error('Oturum kapandı'); }
          if (r.status === 409) { var e = new Error('çakışma'); e.catisma = d; throw e; }
          if (r.status === 403) throw new Error(d.hata && d.hata !== 'yetki yok' ? d.hata : 'Bu işlem için yetkiniz yok.');
          if (!r.ok) throw new Error(d.hata || ('Sunucu hatası (' + r.status + ')'));
          return d;
        });
      });
  }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (r.status === 401) { location.href = '/giris'; throw new Error('Oturum kapandı'); }
      if (!r.ok) throw new Error('Okunamadı (' + r.status + ')');
      return r.json();
    });
  }

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  function yaziRengi(hex) {
    try { var h = (hex || '#999').replace('#', ''); if (h.length === 3) h = h.replace(/(.)/g, '$1$1'); var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16); return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#111' : '#fff'; } catch (e) { return '#fff'; }
  }
  function rozet(proje, renk) { var r = renk || PROJE_RENK[proje] || '#999'; return '<span class="rozet" style="background:' + esc(r) + ';color:' + yaziRengi(r) + '">' + esc(proje) + '</span>'; }

  function kopyala(metin) {
    if (navigator.clipboard) navigator.clipboard.writeText(metin).then(function () { toast('Kopyalandı'); });
    else { var i = document.createElement('input'); i.value = metin; document.body.appendChild(i); i.select(); document.execCommand('copy'); i.remove(); toast('Kopyalandı'); }
  }

  // ---------------- kayıt penceresi (Kayıtlar + proje tablosu) ----------------
  function kayitSayfasi() {
    var modal = document.getElementById('modal');
    if (!modal) return;
    var durumFiltresi = document.body.getAttribute('data-durum') || 'bekleyen';
    var kartlar = Array.prototype.slice.call(document.querySelectorAll('.kayit[data-id]'));
    var idler = kartlar.map(function (e) { return parseInt(e.getAttribute('data-id'), 10); });
    var acikId = null, acikKayit = null, sekme = 'bilgi';

    kartlar.forEach(function (e) {
      e.addEventListener('click', function (ev) {
        if (ev.target.closest && ev.target.closest('a, input, button, form')) return;   // satırdaki link / KT kutusu
        ac(parseInt(e.getAttribute('data-id'), 10));
      });
    });
    modal.querySelector('.modal-kapat').addEventListener('click', kapat);
    modal.querySelector('.modal-onceki').addEventListener('click', function () { adim(-1); });
    modal.querySelector('.modal-sonraki').addEventListener('click', function () { adim(1); });
    modal.addEventListener('click', function (ev) { if (ev.target === modal) kapat(); });
    document.addEventListener('keydown', function (ev) {
      if (modal.classList.contains('gizli')) return;
      var yaziyor = /^(INPUT|TEXTAREA)$/.test((ev.target || {}).tagName || '');
      if (ev.key === 'Escape') kapat();
      if (ev.key === 'ArrowLeft' && !yaziyor) adim(-1);
      if (ev.key === 'ArrowRight' && !yaziyor) adim(1);
    });
    var form = document.getElementById('m-duzenle'), silForm = document.getElementById('m-sil'), yorumForm = document.getElementById('m-yorum-form');
    form.addEventListener('submit', function (ev) { ev.preventDefault(); duzenleKaydet(); });
    document.getElementById('m-duzenle-iptal').addEventListener('click', function () { form.classList.add('gizli'); });
    silForm.addEventListener('submit', function (ev) { ev.preventDefault(); silGonder(); });
    document.getElementById('m-sil-iptal').addEventListener('click', function () { silForm.classList.add('gizli'); });
    yorumForm.addEventListener('submit', function (ev) { ev.preventDefault(); yorumGonder(); });
    yorumForm.querySelector('textarea').addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); yorumGonder(); } });
    Array.prototype.forEach.call(modal.querySelectorAll('[data-sekme]'), function (b) { b.addEventListener('click', function () { sekmeAc(b.getAttribute('data-sekme')); }); });

    // satır içi KT (proje tablosu)
    Array.prototype.forEach.call(document.querySelectorAll('input[data-kt]'), function (kutu) {
      kutu.addEventListener('change', function () {
        var id = kutu.getAttribute('data-kt'), deger = kutu.checked ? '1' : '0';
        kutu.disabled = true;
        post('/kayit/' + id + '/kt', { deger: deger }).then(function (r) {
          kutu.checked = !!r.kt; kutu.disabled = false;
          kutu.title = r.kt ? (r.kt_kim + ' ' + (r.kt_zaman || '')) : 'KT ver';
          var tr = kutu.closest('tr'); if (tr) { tr.classList.toggle('onayli', !!r.kt); var d = tr.querySelector('td[data-b=Durum]'); if (d) d.innerHTML = r.kt ? '<span class="yesil">onaylı</span>' : '<span class="turuncu">bekliyor</span>'; }
          toast(r.kt ? 'KT verildi ✔' : 'KT kaldırıldı');
          kartGuncelle(parseInt(id, 10), 'kt', r);
        }).catch(function (e) { kutu.checked = !kutu.checked; kutu.disabled = false; toast(e.message, true); });
      });
    });

    function adim(d) {
      var i = idler.indexOf(acikId);
      if (i < 0) return;
      var j = i + d;
      if (j >= 0 && j < idler.length) ac(idler[j]);
    }
    function kapat() { modal.classList.add('gizli'); modal.setAttribute('aria-hidden', 'true'); acikId = null; }
    // Bildirimden gelen ?ac=<id>: pencereyi hemen aç, adresi temizle (yenilemede tekrar açılmasın)
    var acParam = new URLSearchParams(location.search).get('ac');
    if (acParam) {
      var u = new URL(location.href); u.searchParams.delete('ac'); history.replaceState(null, '', u.pathname + u.search);
      ac(parseInt(acParam, 10));
    }

    function sekmeAc(ad) {
      sekme = ad;
      Array.prototype.forEach.call(modal.querySelectorAll('[data-sekme]'), function (b) { b.classList.toggle('aktif', b.getAttribute('data-sekme') === ad); });
      Array.prototype.forEach.call(modal.querySelectorAll('.m-sekme'), function (s) { s.classList.toggle('gizli', s.id !== 'm-sekme-' + ad); });
      if (ad === 'yorumlar' && acikId) yorumlariYukle(acikId);
      if (ad === 'gecmis' && acikId) gecmisYukle(acikId);
    }

    function ac(id, sekmeAdi) {
      acikId = id;
      modal.classList.remove('gizli'); modal.setAttribute('aria-hidden', 'false');
      form.classList.add('gizli'); silForm.classList.add('gizli');
      document.getElementById('m-catisma').classList.add('gizli');
      document.getElementById('m-alanlar').innerHTML = '<dt>Yükleniyor…</dt><dd></dd>';
      document.getElementById('m-butonlar').innerHTML = '';
      getJson('/kayit/' + id + '.json')
        .then(function (k) { if (acikId === id) { goster(k); sekmeAc(sekmeAdi || sekme); } })
        .catch(function (e) { toast(e.message, true); });
    }

    function goster(k) {
      acikKayit = k;
      var proje = document.getElementById('m-proje');
      proje.textContent = k.proje; proje.style.background = k.renk; proje.style.color = yaziRengi(k.renk);
      document.getElementById('m-kategori').textContent = k.kategori || '';
      document.getElementById('m-kt').classList.toggle('gizli', !k.kt);
      document.getElementById('m-durum').innerHTML = k.silindi ? '<span class="etiket-kucuk kirmizi-arka">silindi' + (k.silen ? ' (' + esc(k.silen) + ')' : '') + '</span>' : '';
      document.getElementById('m-yorum-sayi').textContent = k.yorum_sayisi || 0;
      document.getElementById('m-yorum-sayi').style.fontWeight = k.okunmamis_yorum ? '800' : '';

      var img = document.getElementById('m-gorsel'), yok = document.getElementById('m-gorsel-yok'), lnk = document.getElementById('m-gorsel-link');
      img.removeAttribute('src');
      if (k.gorsel_url && k.gorsel_kaynak !== 'yok') {
        img.src = k.gorsel_url + '?v=' + encodeURIComponent(k.guncelleme || '');
        img.classList.remove('gizli'); yok.classList.add('gizli');
        lnk.href = k.dis_link || k.gorsel_url;
      } else {
        img.classList.add('gizli'); yok.classList.remove('gizli');
        yok.innerHTML = k.link_turu === 'gyazo' ? 'görsel yok (eski Gyazo linki)' + (k.dis_link ? '<br><a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">Linki yeni sekmede aç</a>' : '')
          : (k.dis_link ? 'Bu kayıtta yerel görsel yok.<br><a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">' + esc(k.dis_link) + '</a>' : 'Görsel yok');
        lnk.removeAttribute('href');
      }

      var alanlar = [
        ['Personel kodu', k.personel, 'buyuk'], ['Üye ID', k.uye_id], ['Ana üye ID', k.ana_uye_id], ['Tür', k.tip],
        ['Tarih', k.tarih || k.tarih_ham], ['Ekleyen', k.ekleyen_ad ? (k.ekleyen_ad + (k.ekleyen_tg_id ? ' (' + k.ekleyen_tg_id + ')' : '') + (k.ekleyen_guven === 'tahmini' ? ' ~' : '')) : (k.ekleyen_tg_id || '')],
        ['Görsel 2', k.gorsel2], ['Açıklama', k.aciklama], ['Ek not', k.ek_not], ['Lead ID', k.lead_id], ['Kaynak', k.kaynak + (k.eski_satir ? ' (Excel ' + k.eski_sayfa + ' / ' + k.eski_satir + ')' : '')],
        ['Onay', k.kt ? ('✔ ' + (k.kt_kim || k.kt_kaynak || '') + (k.kt_zaman ? ' · ' + k.kt_zaman : '')) : 'bekliyor'],
        ['Silinme', k.silindi ? ((k.silen || '') + (k.silme_zamani ? ' · ' + k.silme_zamani : '') + (k.silme_nedeni ? ' · neden: ' + k.silme_nedeni : '')) : ''],
        ['Sürüm', 'v' + k.surum + ' · ' + (k.guncelleme || '')]
      ];
      document.getElementById('m-alanlar').innerHTML = alanlar.filter(function (a) { return a[1] !== null && a[1] !== undefined && a[1] !== ''; })
        .map(function (a) { return '<dt>' + esc(a[0]) + '</dt><dd class="' + (a[2] || '') + '">' + esc(a[1]) + '</dd>'; }).join('');
      document.getElementById('m-link').innerHTML = k.dis_link
        ? 'Link: <a href="' + esc(k.dis_link) + '" target="_blank" rel="noopener">' + esc(k.dis_link) + '</a> <button class="btn kucuk" type="button" data-kopyala="' + esc(k.dis_link) + '">kopyala</button>'
        : (k.link ? 'Link alanı: ' + esc(k.link) : '');

      var b = [];
      if (!k.silindi) {
        if (k.izin_kt) b.push(k.kt ? '<button class="btn" data-islem="kt" data-deger="0">Onayı kaldır</button>' : '<button class="btn basari" data-islem="kt" data-deger="1">✔ Onayla (KT)</button>');
        if (k.izin_duzenle) b.push('<button class="btn" data-islem="duzenle">✎ Düzenle</button>');
        if (k.izin_sil) b.push('<button class="btn tehlike" data-islem="sil">🗑 Sil</button>');
      } else if (k.izin_sil) {
        b.push('<button class="btn" data-islem="geri_al">↩ Geri al</button>');
      }
      var kutu = document.getElementById('m-butonlar');
      kutu.innerHTML = b.join('');
      Array.prototype.forEach.call(kutu.querySelectorAll('button'), function (btn) { btn.addEventListener('click', function () { islem(btn.getAttribute('data-islem'), btn); }); });
    }

    function islem(ad, btn) {
      var k = acikKayit;
      if (!k) return;
      if (ad === 'duzenle') {
        ['personel', 'uye_id', 'ana_uye_id', 'tip', 'kategori', 'gorsel2', 'aciklama'].forEach(function (f) { form.elements[f].value = k[f] || ''; });
        form.elements.surum.value = k.surum;
        form.classList.remove('gizli'); silForm.classList.add('gizli'); form.elements.personel.focus();
        return;
      }
      if (ad === 'sil') { silForm.classList.remove('gizli'); form.classList.add('gizli'); silForm.elements.neden.value = ''; silForm.elements.neden.focus(); return; }
      if (ad === 'geri_al' && !confirm('Kayıt geri alınacak (silinmiş işareti kalkacak). Emin misiniz?')) return;
      var url = '/kayit/' + k.id + '/' + (ad === 'geri_al' ? 'geri-al' : ad);
      var veri = ad === 'kt' ? { deger: btn.getAttribute('data-deger') } : {};
      btn.disabled = true;
      post(url, veri).then(function (r) {
        if (!r.ok) throw new Error(r.hata || 'işlem yapılamadı');
        toast(ad === 'kt' ? (r.kt ? 'Onaylandı ✔' : 'Onay kaldırıldı') : 'Geri alındı');
        kartGuncelle(k.id, ad, r);
        ac(k.id);
      }).catch(function (e) { btn.disabled = false; toast(e.message, true); });
    }

    function silGonder() {
      var k = acikKayit; if (!k) return;
      var neden = silForm.elements.neden.value.trim();
      if (!neden) { toast('Silme nedeni gerekli', true); return; }
      post('/kayit/' + k.id + '/sil', { neden: neden }).then(function (r) {
        if (!r.ok) throw new Error(r.hata || 'silinemedi');
        toast('Silindi (arşivde ve geçmişte durur; geri alınabilir)');
        silForm.classList.add('gizli');
        kartGuncelle(k.id, 'sil', r);
        ac(k.id);
      }).catch(function (e) { toast(e.message, true); });
    }

    function duzenleKaydet() {
      var k = acikKayit; if (!k) return;
      var veri = { surum: form.elements.surum.value };
      ['personel', 'uye_id', 'ana_uye_id', 'tip', 'kategori', 'gorsel2', 'aciklama'].forEach(function (f) { veri[f] = form.elements[f].value.trim(); });
      post('/kayit/' + k.id + '/duzenle', veri).then(function (r) {
        if (!r.ok) throw new Error(r.hata || 'kaydedilemedi');
        toast('Kaydedildi');
        form.classList.add('gizli');
        var kart = document.querySelector('.kayit[data-id="' + k.id + '"]');
        if (kart) { var p = kart.querySelector('.satir1 b, figcaption b, td b'); if (p) p.textContent = veri.personel || '—'; }
        ac(k.id);
      }).catch(function (e) {
        if (e.catisma) {
          var c = document.getElementById('m-catisma');
          c.innerHTML = 'Bu kayıt az önce <b>' + esc(e.catisma.kim || 'başka biri') + '</b> tarafından değiştirildi — <button type="button" class="btn kucuk" id="m-yenile">Yenile</button> <small>(yenileyince güncel değerler gelir; değişikliğinizi yeniden yapın)</small>';
          c.classList.remove('gizli');
          document.getElementById('m-yenile').addEventListener('click', function () { ac(k.id); });
          return;
        }
        toast(e.message, true);
      });
    }

    function kartGuncelle(id, ad, r) {
      var kart = document.querySelector('.kayit[data-id="' + id + '"]');
      if (!kart) return;
      var listedenCikar = (ad === 'kt' && durumFiltresi === 'bekleyen' && r.kt) || (ad === 'kt' && durumFiltresi === 'onayli' && !r.kt) ||
        (ad === 'sil' && durumFiltresi !== 'hepsi' && durumFiltresi !== 'silinen') || (ad === 'geri_al' && durumFiltresi === 'silinen');
      if (listedenCikar) { kart.style.opacity = '.35'; kart.classList.add('cikarildi'); }
      if (ad === 'kt') { kart.classList.toggle('onayli', !!r.kt); var kutu = kart.querySelector('input[data-kt]'); if (kutu) kutu.checked = !!r.kt; }
      if (ad === 'sil') { kart.classList.add('silik'); kart.classList.add('silindi'); kart.classList.remove('onayli'); }
      if (ad === 'geri_al') { kart.classList.remove('silik'); kart.classList.remove('silindi'); }
    }

    // ---- yorumlar ----
    function yorumlariYukle(id) {
      var ul = document.getElementById('m-yorumlar');
      ul.innerHTML = '<li class="silik">Yükleniyor…</li>';
      getJson('/kayit/' + id + '/yorumlar.json').then(function (d) {
        if (acikId !== id) return;
        document.getElementById('m-yorum-sayi').textContent = d.sayi; document.getElementById('m-yorum-sayi').style.fontWeight = '';
        var kart = document.querySelector('.kayit[data-id="' + id + '"] .yorum-rozet'); if (kart) kart.classList.remove('okunmamis');
        ul.innerHTML = d.yorumlar.length ? d.yorumlar.map(function (y) {
          if (y.silindi) return '<li class="silik" data-yid="' + y.id + '">(silindi) <small>' + esc(y.kullanici) + ' · ' + esc(y.silme_zamani || '') + '</small></li>';
          var araclar = '';
          if (y.duzenlenebilir) araclar += '<button type="button" data-yorum-duzenle="' + y.id + '">düzenle</button>';
          if (y.silinebilir) araclar += '<button type="button" class="tehlike" data-yorum-sil="' + y.id + '">sil</button>';
          return '<li class="' + (y.kullanici === d.ben ? 'benim' : '') + '" data-yid="' + y.id + '"><div class="yorum-ust"><b>' + esc(y.kullanici) + '</b> <span>' + esc(y.zaman) + '</span>' +
            (y.duzenleme_zamani ? ' <span title="' + esc(y.duzenleme_zamani) + '">(düzenlendi)</span>' : '') + '<span class="yorum-araclar">' + araclar + '</span></div><div class="yorum-metin">' + esc(y.metin) + '</div></li>';
        }).join('') : '<li class="silik">Henüz yorum yok. İlk yorumu siz yazın.</li>';
        Array.prototype.forEach.call(ul.querySelectorAll('[data-yorum-sil]'), function (b) { b.addEventListener('click', function () { if (!confirm('Yorum silinsin mi?')) return; post('/yorum/' + b.getAttribute('data-yorum-sil') + '/sil', {}).then(function () { toast('Yorum silindi'); yorumlariYukle(id); }).catch(function (e) { toast(e.message, true); }); }); });
        Array.prototype.forEach.call(ul.querySelectorAll('[data-yorum-duzenle]'), function (b) {
          b.addEventListener('click', function () {
            var li = b.closest('li'), yid = b.getAttribute('data-yorum-duzenle'), metinEl = li.querySelector('.yorum-metin');
            if (li.querySelector('textarea')) return;
            var eski = metinEl.textContent;
            metinEl.innerHTML = '<textarea rows="3" maxlength="2000"></textarea><div><button type="button" class="btn kucuk birincil" data-kaydet>Kaydet</button> <button type="button" class="btn kucuk" data-vazgec>Vazgeç</button></div>';
            var ta = metinEl.querySelector('textarea'); ta.value = eski; ta.focus();
            metinEl.querySelector('[data-vazgec]').addEventListener('click', function () { metinEl.textContent = eski; });
            metinEl.querySelector('[data-kaydet]').addEventListener('click', function () { post('/yorum/' + yid + '/duzenle', { metin: ta.value.trim() }).then(function () { toast('Yorum düzeltildi'); yorumlariYukle(id); }).catch(function (e) { toast(e.message, true); }); });
            ta.addEventListener('keydown', function (ev) { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); metinEl.querySelector('[data-kaydet]').click(); } });
          });
        });
        ul.scrollTop = ul.scrollHeight;
      }).catch(function (e) { ul.innerHTML = '<li class="silik">' + esc(e.message) + '</li>'; });
    }
    function yorumGonder() {
      var k = acikKayit; if (!k) return;
      var ta = yorumForm.querySelector('textarea'), metin = ta.value.trim();
      if (!metin) { toast('Yorum boş', true); return; }
      post('/kayit/' + k.id + '/yorum', { metin: metin }).then(function () {
        ta.value = ''; toast('Yorum gönderildi');
        k.yorum_sayisi = (k.yorum_sayisi || 0) + 1;
        var kart = document.querySelector('.kayit[data-id="' + k.id + '"]'); if (kart) { var r = kart.querySelector('.yorum-rozet'); if (r) r.textContent = '💬 ' + k.yorum_sayisi; else { var td = kart.querySelector('td[data-b=Yorum], .satir4, figcaption'); if (td) td.insertAdjacentHTML('beforeend', ' <span class="yorum-rozet">💬 ' + k.yorum_sayisi + '</span>'); } }
        yorumlariYukle(k.id);
      }).catch(function (e) { toast(e.message, true); });
    }

    // ---- geçmiş ----
    function gecmisYukle(id) {
      var g = document.getElementById('m-gecmis'), a = document.getElementById('m-arsiv');
      g.innerHTML = '<li>Yükleniyor…</li>';
      getJson('/kayit/' + id + '/gecmis.json').then(function (d) {
        if (acikId !== id) return;
        g.innerHTML = d.gecmis.length ? d.gecmis.map(function (h) { return '<li class="' + (/^(sil|geri_al|duzenle)$/.test(h.islem) ? 'vurgu' : '') + '">' + esc(h.metin) + '</li>'; }).join('') : '<li>Kayıt yok</li>';
        a.innerHTML = 'Arşiv kopyaları: <b>' + d.arsiv_sayisi + '</b>' + (d.arsiv_url ? ' · <a href="' + esc(d.arsiv_url) + '" target="_blank" rel="noopener">JSON olarak gör</a>' : ' <small>(süper admin görebilir)</small>');
      }).catch(function (e) { g.innerHTML = '<li>' + esc(e.message) + '</li>'; });
    }
  }

  // ---------------- bildirimler (sunucu tarafli; her sayfada) ----------------
  var BILDIRIM_SN = 20;
  function bildirimler() {
    var zil = document.getElementById('zil'), kutu = document.getElementById('bildirim-kutu'), liste = document.getElementById('bildirim-liste'), sayi = document.getElementById('zil-sayi');
    var uyari = document.getElementById('bildirim-uyari'), bos = document.getElementById('bildirim-bos'), ozet = document.getElementById('bildirim-ozet');
    if (!zil || !kutu) return;
    var son = -1, uyariZaman = null, veri = { sayi: 0, liste: [] }, basTitle = document.title.replace(/^\(\d+\) /, '');
    var izinKutu = document.getElementById('bildirim-izin');
    if (window.Notification && Notification.permission === 'default' && izinKutu) izinKutu.classList.remove('gizli');
    var izinBtn = document.getElementById('bildirim-izin-btn');
    if (izinBtn) izinBtn.addEventListener('click', function () { Notification.requestPermission().then(function () { izinKutu.classList.add('gizli'); }); });

    var TUR = { yeni_kayit: 'yeni kayıt', kt: 'KT', degisti: 'düzenlendi', silindi: 'silindi', yorum: 'yorum' };
    function satir(b) {
      return '<li class="' + (b.okundu ? 'okundu' : 'okunmamis') + '" data-id="' + b.id + '"><span class="nokta" title="' + (b.okundu ? 'okundu' : 'okunmadı') + '"></span>' +
        '<div class="govde">' + rozet(b.proje, b.renk) + ' <span class="tur">' + esc(TUR[b.tur] || b.tur) + '</span> ' + esc(b.metin) + '<small>' + esc((b.zaman || '').slice(0, 16)) + '</small>' +
        '<a class="kontrol" href="' + esc(b.link) + '" data-okundu="' + b.id + '">Kontrol et →</a></div>' +
        '<button type="button" class="durum-dugme" data-durum="' + b.id + '" data-okundu-mu="' + (b.okundu ? '1' : '0') + '">' + (b.okundu ? 'okunmadı say' : 'okundu say') + '</button></li>';
    }
    function sayiYaz(n) {
      sayi.textContent = n; sayi.classList.toggle('gizli', !n);
      document.title = (n ? '(' + n + ') ' : '') + basTitle;
    }
    function ciz() {
      var l = veri.liste || [];
      liste.innerHTML = l.map(satir).join('');
      bos.classList.toggle('gizli', l.length > 0);
      sayiYaz(veri.sayi || 0);
      ozet.textContent = l.length ? (veri.sayi ? veri.sayi + ' okunmamış / ' + l.length : l.length + ' bildirim, hepsi okundu') : '';
    }
    function isaretle(id, okundu) {
      return post('/bildirim/okundu', { id: id, okundu: okundu ? '1' : '0' }).then(function (r) {
        (veri.liste || []).forEach(function (b) { if (String(b.id) === String(id)) b.okundu = okundu ? 1 : 0; });
        veri.sayi = r.sayi; ciz();
      }).catch(function () {});
    }
    function ac() { kutu.classList.remove('gizli'); kutu.setAttribute('aria-hidden', 'false'); }
    function kapat() { kutu.classList.add('gizli'); kutu.setAttribute('aria-hidden', 'true'); }
    zil.addEventListener('click', function (ev) { ev.stopPropagation(); if (kutu.classList.contains('gizli')) { kontrol(true); ac(); } else kapat(); });
    document.addEventListener('click', function (ev) { if (!kutu.classList.contains('gizli') && !kutu.contains(ev.target) && ev.target !== zil) kapat(); });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { kapat(); uyariKapat(); } });
    document.getElementById('bildirim-okundu').addEventListener('click', function () {
      post('/bildirim/tumu-okundu', {}).then(function () { (veri.liste || []).forEach(function (b) { b.okundu = 1; }); veri.sayi = 0; ciz(); }).catch(function () {});
    });
    kutu.addEventListener('click', function (ev) {
      ev.stopPropagation();
      var d = ev.target.closest ? ev.target.closest('[data-durum]') : null;
      if (d) { isaretle(d.getAttribute('data-durum'), d.getAttribute('data-okundu-mu') !== '1'); return; }
      var a = ev.target.closest ? ev.target.closest('[data-okundu]') : null;
      if (a) { ev.preventDefault(); var href = a.getAttribute('href'); isaretle(a.getAttribute('data-okundu'), true).then(function () { location.href = href; }); }
    });

    function uyariKapat() { uyari.classList.add('gizli'); clearTimeout(uyariZaman); }
    uyari.addEventListener('click', function (ev) {
      if (ev.target.closest && ev.target.closest('.kapat')) { uyariKapat(); return; }
      var a = ev.target.closest ? ev.target.closest('[data-okundu]') : null;
      if (a) { ev.preventDefault(); var href = a.getAttribute('href'); isaretle(a.getAttribute('data-okundu'), true).then(function () { location.href = href; }); }
      var za = ev.target.closest ? ev.target.closest('.zil-ac') : null;
      if (za) { ev.preventDefault(); uyariKapat(); ciz(); ac(); }
    });
    function uyariGoster(yeniler) {
      var b = yeniler[0];
      uyari.innerHTML = '<button type="button" class="kapat" title="Kapat">✕</button>' +
        (yeniler.length > 1 ? '<div><b>' + yeniler.length + ' yeni bildirim</b> · <a href="#" class="zil-ac" style="color:#93c5fd">listeyi aç</a></div>' : '<div>Yeni bildirim:</div>') +
        '<div style="margin-top:4px">' + rozet(b.proje, b.renk) + ' <span class="tur">' + esc(TUR[b.tur] || b.tur) + '</span> ' + esc(b.metin) + '</div><a class="kontrol" href="' + esc(b.link) + '" data-okundu="' + b.id + '">Kontrol et →</a>';
      uyari.classList.remove('gizli'); clearTimeout(uyariZaman); uyariZaman = setTimeout(uyariKapat, 8000);
      if (window.Notification && Notification.permission === 'granted') {
        try {
          var n = new Notification(yeniler.length === 1 ? b.proje + ': ' + (TUR[b.tur] || b.tur) : yeniler.length + ' yeni bildirim', { body: b.metin + ' — Kanıt Merkezi', tag: 'km-' + b.id });
          n.onclick = function () { window.focus(); isaretle(b.id, true).then(function () { location.href = b.link; }); n.close(); };
        } catch (e) {}
      }
    }
    function kontrol(sessiz) {
      getJson('/bildirim.json?son=' + son).then(function (d) {
        var ilk = son < 0;
        veri = d; son = d.maks;
        ciz();
        if (!ilk && !sessiz && d.yeni && d.yeni.length) uyariGoster(d.yeni);
        sayaclariGuncelle(d.sayac);
      }).catch(function () {});
    }
    function sayaclariGuncelle(sayac) {
      if (!sayac) return;
      Array.prototype.forEach.call(document.querySelectorAll('[data-sayac]'), function (el) {
        var p = el.getAttribute('data-sayac').split(':'), v = sayac[p[0]] && sayac[p[0]][p[1]];
        if (v !== undefined && String(v) !== el.textContent) { el.textContent = v; el.classList.add('sayac-degisti'); setTimeout(function () { el.classList.remove('sayac-degisti'); }, 1500); }
      });
    }
    kontrol(true);
    setInterval(function () { kontrol(false); }, BILDIRIM_SN * 1000);
  }

  // ---------------- bot sayfası: Telegram kullanıcı detayı (canlı) ----------------
  function botSayfasi() {
    var modal = document.getElementById('tg-modal'), icerik = document.getElementById('tg-icerik');
    if (!modal) return;
    var acikTg = null, sayac = null;
    var ADIMLAR = ['proje', 'kategori', 'personel', 'uyeid', 'anaid', 'tip', 'kayit_secim', 'ozet'];
    var ADIM_AD = { proje: 'Proje seçiyor', kategori: 'Kategori seçiyor', personel: 'Personel kodu yazması bekleniyor', uyeid: 'Üye ID yazması bekleniyor',
      anaid: 'Ana üye ID yazması bekleniyor', tip: 'Sessiz / Telesekreter seçimi bekleniyor', kayit_secim: 'Gyazo mu, dosya mı? seçimi bekleniyor',
      gyazo_bakim: 'Gyazo bakım uyarısında (dosyaya kaydet / iptal)', ozet: 'SON KONTROL ekranında: Onayla / İptal bekleniyor', lead_onay: 'Lead ID onayı bekleniyor (yazılı giriş)' };
    var ADIM_KISA = { proje: 'Proje', kategori: 'Kategori', personel: 'Personel', uyeid: 'Üye ID', anaid: 'Ana ID', tip: 'Tür', kayit_secim: 'Gyazo/dosya', ozet: 'Onay' };
    function cip(p) { var r = PROJE_RENK[p] || '#6b7280'; return '<span class="proje-cip" style="--renk:' + esc(r) + ';--cipyazi:' + yaziRengi(r) + '">' + esc(p) + '</span>'; }
    function sayiListe(obj) { var k = Object.keys(obj || {}); if (!k.length) return '<span class="gri">yok</span>'; return k.sort().map(function (x) { return '<b>' + esc(x) + '</b> ' + esc(obj[x]); }).join(' · '); }
    function form(islem, etiket, sinif, onay, ekstra) {
      return '<form method="post" action="/bot" class="satir-form"' + (onay ? ' data-onay="' + esc(onay) + '"' : '') + '><input type="hidden" name="csrf" value="' + esc(csrf) + '"><input type="hidden" name="islem" value="' + islem + '"><input type="hidden" name="tg_id" value="' + esc(acikTg) + '">' + (ekstra || '') + '<button class="btn kucuk ' + (sinif || '') + '">' + etiket + '</button></form>';
    }
    function ciz(d) {
      var ad = [d.username, d.first_name].filter(Boolean).join(' / ') || '(ad yok)';
      var h = '<div class="detay-baslik"><h3>' + esc(ad) + ' <code>' + esc(d.id) + '</code></h3>';
      h += d.engelli ? '<b class="kirmizi">ENGELLİ</b> <small>' + esc(d.engel_sebep) + ' ' + esc(d.engel_tarihi) + '</small>' : d.onayli ? '<span class="yesil">onaylı</span> <small>' + esc(d.onay_tarihi) + '</small>' : '<span class="gri">onaysız (şifre yazmadı)</span>';
      h += '<small class="kucukyazi"><span class="canli-nokta"></span>canlı · ' + esc(d.zaman) + '</small></div>';
      h += '<div class="modal-butonlar">';
      if (d.engelli) h += form('engel_kaldir', 'Engeli kaldır', '', 'Engel kaldırılsın mı? Deneme sayacı ve oturum da sıfırlanır.');
      else { h += d.onayli ? form('onay_kaldir', 'Onayı kaldır', '', 'Onay kaldırılsın mı? Kullanıcı yeniden şifre yazmak zorunda kalır.') : form('onayla', '✔ Onayla', 'basari', '', '<input type="hidden" name="ad" value="' + esc(d.username) + '">');
        h += form('engelle', 'Engelle', 'tehlike', 'Bu kullanıcı engellensin mi?', '<input type="hidden" name="ad" value="' + esc(d.username) + '"><input type="hidden" name="sebep" value="panel">'); }
      if (d.oturum) h += form('oturum_temizle', '🧹 Oturumu temizle', '', 'Yarım kalan oturum silinsin mi? Kullanıcı baştan başlar.');
      h += form('tam_sifirla', '♻ Tam sıfırla', 'tehlike', 'Engel + onay + deneme + oturum birlikte temizlenir, kullanıcı yeniden şifreye düşer. Emin misiniz?');
      h += '</div><div class="detay-izgara">';
      var o = d.oturum;
      h += '<div class="detay-kutu' + (o ? ' oturum-aktif' : '') + '"><h4>Şu an nerede? <small>(canlı oturum)</small></h4>';
      if (!o) { h += '<p class="kucukyazi" style="margin:0">Açık oturum yok: ya hiç başlamadı ya da son kaydı tamamladı.' + (d.status ? ' Bot durumu: <b>' + esc(d.status) + '</b>' : '') + '</p>'; }
      else {
        var adim = o.adim || o.step || '';
        h += '<div><span class="adim-rozet">' + esc(ADIM_AD[adim] || ('Adım: ' + adim)) + '</span></div>';
        var i = ADIMLAR.indexOf(adim);
        h += '<div class="adim-akis">' + ADIMLAR.map(function (a, j) { return '<span class="' + (i < 0 ? '' : j < i ? 'gecti' : j === i ? 'simdi' : '') + '">' + esc(ADIM_KISA[a]) + '</span>'; }).join('') + '</div>';
        var al = [['Proje', o.proje ? cip(String(o.proje).toUpperCase()) : ''], ['Kategori', o.kategori ? esc(String(o.kategori).toUpperCase()) : ''], ['Personel', esc(o.personel)], ['Üye ID', esc(o.uyeid || o.uye_id)], ['Ana ID', esc(o.anaid || o.ana_uye_id)], ['Tür', esc(o.tip)],
          ['Giriş tipi', esc(o.girisTipi === 'yazili' || o.giris_tipi === 'yazili' ? 'yazılı (Lead ID ' + (o.leadId || o.lead_id || '') + ')' : o.girisTipi || o.giris_tipi || 'resim')], ['Görsel', o.gorsel_var ? '✔ alındı' : '<span class="gri">henüz yok</span>']];
        h += '<dl style="margin-top:8px">' + al.filter(function (a) { return a[1]; }).map(function (a) { return '<dt>' + a[0] + '</dt><dd>' + a[1] + '</dd>'; }).join('') + '</dl>';
      }
      h += '</div>';
      h += '<div class="detay-kutu"><h4>Bot defteri</h4><dl>';
      h += '<dt>Son görülme</dt><dd>' + esc(d.last_seen || '-') + '</dd><dt>Bot durumu</dt><dd>' + esc(d.status || '-') + '</dd><dt>Hatalı şifre denemesi</dt><dd>' + (d.deneme ? '<b class="turuncu">' + d.deneme + '</b>' : '0') + '</dd>';
      h += '<dt>Eklediği kayıt (bot)</dt><dd><b>' + d.bot_sayac.kayit + '</b></dd><dt>Son kayıt</dt><dd>' + esc([d.bot_sayac.son_tarih, d.bot_sayac.son_proje, d.bot_sayac.son_kategori].filter(Boolean).join(' / ') || '-') + '</dd>';
      h += '<dt>Proje dağılımı</dt><dd>' + sayiListe(d.bot_sayac.proje) + '</dd><dt>Kategori dağılımı</dt><dd>' + sayiListe(d.bot_sayac.kategori) + '</dd></dl></div>';
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
      getJson('/bot/kullanici/' + encodeURIComponent(acikTg) + '.json')
        .then(function (d) { if (d && acikTg === d.id) ciz(d); })
        .catch(function () { icerik.innerHTML = '<p class="kirmizi">Kullanıcı bilgisi alınamadı.</p>'; });
    }
    function ac(id) {
      acikTg = String(id);
      modal.classList.remove('gizli'); modal.setAttribute('aria-hidden', 'false');
      icerik.innerHTML = '<p>Yükleniyor…</p>';
      yukle(); clearInterval(sayac); sayac = setInterval(yukle, 5000);
    }
    function kapat() { modal.classList.add('gizli'); modal.setAttribute('aria-hidden', 'true'); acikTg = null; clearInterval(sayac); }
    modal.querySelector('.modal-kapat').addEventListener('click', kapat);
    modal.addEventListener('click', function (ev) { if (ev.target === modal) kapat(); });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && !modal.classList.contains('gizli')) kapat(); });
    document.addEventListener('click', function (ev) {
      var t = ev.target;
      if (t.closest && t.closest('form, a:not([data-tg-detay])') && !t.closest('[data-tg-detay]')) return;
      var e = t.closest ? t.closest('[data-tg-detay]') : null;
      if (!e) return;
      if (e.tagName === 'TR' && t.closest('form')) return;
      ev.preventDefault(); ac(e.getAttribute('data-tg-detay'));
    });
    var acTg = document.body.getAttribute('data-ac-tg');
    if (acTg) ac(acTg);
  }

  // ---------------- liste kontrolü (2. adım): sayfa / başlık değişince önizlemeyi yenile ----------------
  function listeSayfasi() {
    var form = document.getElementById('esleme-form');
    if (!form) return;
    var onizle = form.querySelector('button[name=adim][value=onizle]');
    Array.prototype.forEach.call(form.querySelectorAll('[data-onizle]'), function (el) {
      el.addEventListener('change', function () { if (form.requestSubmit) form.requestSubmit(onizle); else onizle.click(); });
    });
  }

  // ---------------- her sayfada ----------------
  // onay soruları data-onay, kopyalama data-kopyala, dış link tıklaması satırı açmasın (data-dur)
  document.addEventListener('submit', function (ev) { var f = ev.target, b = ev.submitter; var m = (b && b.getAttribute && b.getAttribute('data-onay')) || (f && f.getAttribute && f.getAttribute('data-onay')); if (m && !confirm(m)) ev.preventDefault(); });
  document.addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('[data-kopyala]') : null; if (b) { ev.preventDefault(); kopyala(b.getAttribute('data-kopyala')); return; }
    var d = ev.target.closest ? ev.target.closest('[data-dur]') : null; if (d) ev.stopPropagation();
  });
  // yüklenemeyen küçük resimler: resmi gizle, kartı 'görsel yok' durumuna al
  document.addEventListener('error', function (ev) {
    var img = ev.target;
    if (!img || img.tagName !== 'IMG') return;
    if (img.classList.contains('mini')) { img.style.display = 'none'; return; }
    if (img.id === 'm-gorsel') { img.classList.add('gizli'); var yok = document.getElementById('m-gorsel-yok'); if (yok) { yok.classList.remove('gizli'); yok.textContent = 'Görsel şu an açılamadı.'; } return; }
    if (img.parentNode && img.parentNode.classList) img.parentNode.classList.add('gorsel-yok');
  }, true);
  // Projeler açılır menüsü: dışarı tıklayınca kapanır
  var pm = document.getElementById('projeler-menu');
  if (pm) document.addEventListener('click', function (ev) { if (pm.open && !pm.contains(ev.target)) pm.open = false; });

  var sayfa = document.body.getAttribute('data-sayfa') || '';
  if (document.getElementById('zil')) bildirimler();
  if (sayfa === 'kayitlar' || sayfa === 'tablo') kayitSayfasi();
  if (sayfa === 'bot_sayfasi') botSayfasi();
  if (sayfa === 'liste_kontrol_sayfasi') listeSayfasi();

  window.Panel = { toast: toast, kopyala: kopyala };
})();

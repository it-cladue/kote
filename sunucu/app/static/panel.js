/* Kanıt Paneli 2.2: bağımsız, erişilebilir panel davranışları. */
window.Panel = (function () {
  'use strict';
  var csrf = (document.querySelector('meta[name=csrf]') || {}).content || '';
  var toastTimer = null;
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function toast(message, error) { var t=document.getElementById('toast'); if(!t)return; t.textContent=message; t.className='toast'+(error?' hata':''); clearTimeout(toastTimer); toastTimer=setTimeout(function(){t.className='toast gizli';},error?6000:3200); }
  function post(url, data) { var fd=new URLSearchParams(); Object.keys(data||{}).forEach(function(k){ if(Array.isArray(data[k]))data[k].forEach(function(v){fd.append(k,v);}); else fd.append(k,data[k]); }); return fetch(url,{method:'POST',credentials:'same-origin',body:fd,headers:{'X-CSRF':csrf}}).then(parseResponse); }
  var oturumYonlendirildi=false;
  function oturumDustu(message,girisUrl){ if(oturumYonlendirildi)return; oturumYonlendirildi=true; var hedef=(girisUrl||'/giris?neden=oturum'); if(hedef.indexOf('sonraki=')<0)hedef+=(hedef.indexOf('?')<0?'?':'&')+'sonraki='+encodeURIComponent(window.location.pathname+window.location.search); toast(message||'Oturumunuz sona erdi, sayfayı yenileyin.',true); setTimeout(function(){window.location.href=hedef;},1500); }
  /* Oturum düşmesi belirtileri: 401, giriş sayfasına yönlendirme ya da eski sekmenin "Geçersiz CSRF" 400'ü → giriş sayfası (sonraki ile). */
  function parseResponse(r) { if(r.status===403)throw new Error('Bu işlem için yetkiniz yok.'); if(r.status===401||r.redirected){ return r.json().catch(function(){return {};}).then(function(d){ oturumDustu(d&&d.hata,d&&d.giris); throw new Error((d&&d.hata)||'Oturumunuz sona erdi, sayfayı yenileyin.'); }); } return r.json().catch(function(){return {};}).then(function(d){if(r.status===400&&/Geçersiz CSRF/i.test(d.hata||'')){oturumDustu('Oturumunuz sona erdi, sayfayı yenileyin.');throw new Error('Oturumunuz sona erdi, sayfayı yenileyin.');}if(!r.ok)throw new Error(d.hata||'İşlem yapılamadı ('+r.status+')'); return d;}); }
  function postBildirim(payload, legacy) { return fetch('/bildirimler/okundu',{method:'POST',credentials:'same-origin',headers:{'X-CSRF':csrf,'Content-Type':'application/json'},body:JSON.stringify(payload)}).then(parseResponse).catch(function(){ return post('/bildirimler/okundu',legacy || (payload.hepsi?{hepsi:'1'}:{id:(payload.ids||[])[0]})); }); }
  function editable(target) { if(!target)return false; var name=(target.tagName||'').toLowerCase(); return name==='input'||name==='textarea'||name==='select'||name==='button'||target.isContentEditable; }
  function setChangeStrip(show) { var s=document.getElementById('degisiklik-serit'); if(s)s.classList.toggle('gizli',!show); }
  function focusables(container) { return Array.prototype.slice.call(container.querySelectorAll('button:not([disabled]),[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')).filter(function(e){return e.offsetParent!==null;}); }

  /* ===== Kayıtlar sayfası (2.2): okunur hatalar, ayrıntı penceresi, lightbox, toplu onay ===== */
  var HATA_METIN={400:'Geçersiz işlem.',401:'Oturumunuz sona erdi; sayfayı yenileyip yeniden giriş yapın.',403:'Bu işlem için yetkiniz yok.',404:'Kayıt bulunamadı; silinmiş veya taşınmış olabilir.',409:'Bu kayıt az önce değiştirildi.',413:'Dosya boyutu sınırı aşıldı.',429:'Çok fazla istek gönderildi; biraz bekleyin.',500:'Sunucuda beklenmeyen bir hata oluştu; yöneticinize bildirin.',502:'Sunucuya ulaşılamıyor; biraz sonra tekrar deneyin.',503:'Sunucu şu an meşgul; biraz sonra tekrar deneyin.',504:'Sunucu zamanında yanıt vermedi; tekrar deneyin.'};
  function yaziAlani(t){if(!t)return false;var n=(t.tagName||'').toLowerCase();return n==='input'||n==='textarea'||n==='select'||!!t.isContentEditable;}
  function kayitHata(status,d){var e=new Error((d&&d.hata)||HATA_METIN[status]||('İşlem yapılamadı (hata kodu '+status+').'));e.status=status;e.veri=d||{};return e;}
  function kayitIstek(url,options){
    options=options||{};
    var init={method:options.method||'GET',credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}};
    if(options.data){var fd=new URLSearchParams();Object.keys(options.data).forEach(function(k){var v=options.data[k];if(v===undefined||v===null)return;if(Array.isArray(v))v.forEach(function(x){fd.append(k,x);});else fd.append(k,v);});init.body=fd;init.headers['X-CSRF']=csrf;}
    var controller=window.AbortController?new AbortController():null;
    if(controller){init.signal=controller.signal;setTimeout(function(){controller.abort();},options.timeout||30000);}
    return fetch(url,init).then(function(r){
      var type=r.headers.get('Content-Type')||'';
      if(r.redirected||(r.ok&&type.indexOf('json')<0))throw kayitHata(401);
      return r.json().catch(function(){return {};}).then(function(d){if(!r.ok)throw kayitHata(r.status,d);return d;});
    },function(err){var e=new Error(err&&err.name==='AbortError'?'Sunucu yanıt vermedi; bağlantınızı kontrol edip tekrar deneyin.':'Sunucuya bağlanılamadı; bağlantınızı kontrol edin.');e.status=0;throw e;});
  }
  function kayitPost(url,data){return kayitIstek(url,{method:'POST',data:data||{}});}
  function toastEylem(message,label,fn){
    var t=document.getElementById('toast');if(!t){toast(message,true);return;}
    t.innerHTML=esc(message)+' <button type="button" style="margin-left:10px;padding:4px 10px;border:1px solid rgba(255,255,255,.6);border-radius:6px;background:#fff;color:#991b1b;font:inherit;font-weight:700;cursor:pointer">'+esc(label)+'</button>';
    t.className='toast hata';clearTimeout(toastTimer);toastTimer=setTimeout(function(){t.className='toast gizli';t.textContent='';},12000);
    t.querySelector('button').addEventListener('click',function(){clearTimeout(toastTimer);t.className='toast gizli';t.textContent='';fn();});
  }
  var ISLEM_ADLARI={onayla:'Onaylandı',onay_kaldir:'Onay kaldırıldı',duzenle:'Düzenlendi',sil:'Silindi',geri_al:'Geri alındı',yorum_ekle:'Yorum eklendi',soru_yonelt:'Soru yöneltildi',yanit_ekle:'Yanıt eklendi',gyazo_istek:'Gyazo dönüşümü istendi',arsiv_esle:'Arşiv görseli eşlendi',ice_aktar:'İçe aktarıldı',telegram_kayit:'Telegram ile eklendi',bot_kayit:'Telegram ile eklendi'};
  function islemAdi(code){return ISLEM_ADLARI[code]||String(code||'').replace(/_/g,' ');}

  /* ---- Tam ekran görsel büyütme ---- */
  function lightboxKur(root){
    if(!root)return null;
    var sahne=root.querySelector('#lb-sahne'),img=root.querySelector('#lb-gorsel'),mesaj=root.querySelector('#lb-mesaj'),oran=root.querySelector('#lb-oran'),kucukler=root.querySelector('#lb-kucukler'),baslik=root.querySelector('#lb-baslik'),yeniSekme=root.querySelector('#lb-yeni-sekme'),indir=root.querySelector('#lb-indir');
    var onceki=root.querySelector('.lb-onceki'),sonraki=root.querySelector('.lb-sonraki');
    var scale=1,tx=0,ty=0,fit=1,natural={w:0,h:0},pointers={},pinch=null,drag=null,acik=false,items=[],index=0,stepFn=null,loadSerial=0,focusBefore=null;
    function apply(){img.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')';oran.textContent=Math.round(scale*100)+'%';}
    function clamp(){var W=sahne.clientWidth,H=sahne.clientHeight,w=natural.w*scale,h=natural.h*scale;if(w<=W)tx=(W-w)/2;else tx=Math.min(0,Math.max(W-w,tx));if(h<=H)ty=(H-h)/2;else ty=Math.min(0,Math.max(H-h,ty));}
    function fitImage(){var W=sahne.clientWidth,H=sahne.clientHeight;if(!natural.w||!W||!H)return;fit=Math.min(W/natural.w,H/natural.h,1);scale=fit;tx=(W-natural.w*scale)/2;ty=(H-natural.h*scale)/2;apply();}
    function zoomAt(factor,cx,cy){if(!natural.w)return;var ns=Math.max(fit*0.5,Math.min(scale*factor,Math.max(fit*12,6)));if(cx===undefined){cx=sahne.clientWidth/2;cy=sahne.clientHeight/2;}tx=cx-(cx-tx)*(ns/scale);ty=cy-(cy-ty)*(ns/scale);scale=ns;clamp();apply();}
    function pos(e){var r=sahne.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top};}
    sahne.addEventListener('wheel',function(e){e.preventDefault();var p=pos(e);zoomAt(e.deltaY<0?1.18:1/1.18,p.x,p.y);},{passive:false});
    sahne.addEventListener('dblclick',function(e){var p=pos(e);if(scale>fit*1.01)fitImage();else zoomAt(2.5,p.x,p.y);});
    sahne.addEventListener('pointerdown',function(e){if(e.button&&e.button!==0)return;pointers[e.pointerId]=pos(e);try{sahne.setPointerCapture(e.pointerId);}catch(_){}var ids=Object.keys(pointers);if(ids.length===1){drag={x:pointers[e.pointerId].x,y:pointers[e.pointerId].y,tx:tx,ty:ty};sahne.classList.add('surukle');}else if(ids.length===2){var a=pointers[ids[0]],b=pointers[ids[1]];pinch={d:Math.hypot(a.x-b.x,a.y-b.y),scale:scale,cx:(a.x+b.x)/2,cy:(a.y+b.y)/2};drag=null;}});
    sahne.addEventListener('pointermove',function(e){if(!pointers[e.pointerId])return;pointers[e.pointerId]=pos(e);var ids=Object.keys(pointers);if(pinch&&ids.length>=2){var a=pointers[ids[0]],b=pointers[ids[1]],d=Math.hypot(a.x-b.x,a.y-b.y);if(pinch.d>0){var target=Math.max(fit*0.5,Math.min(pinch.scale*(d/pinch.d),Math.max(fit*12,6)));var cx=(a.x+b.x)/2,cy=(a.y+b.y)/2;tx=cx-(cx-tx)*(target/scale);ty=cy-(cy-ty)*(target/scale);scale=target;clamp();apply();}}else if(drag){var p=pointers[e.pointerId];tx=drag.tx+(p.x-drag.x);ty=drag.ty+(p.y-drag.y);clamp();apply();}});
    function release(e){delete pointers[e.pointerId];if(!Object.keys(pointers).length){drag=null;pinch=null;sahne.classList.remove('surukle');}else if(Object.keys(pointers).length===1){pinch=null;var id=Object.keys(pointers)[0];drag={x:pointers[id].x,y:pointers[id].y,tx:tx,ty:ty};}}
    sahne.addEventListener('pointerup',release);sahne.addEventListener('pointercancel',release);sahne.addEventListener('pointerleave',function(e){if(pointers[e.pointerId])release(e);});
    window.addEventListener('resize',function(){if(acik&&Math.abs(scale-fit)<0.001)fitImage();else if(acik){clamp();apply();}});
    root.addEventListener('click',function(e){var b=e.target.closest('[data-lb]');if(!b)return;var op=b.getAttribute('data-lb');if(op==='kapat')close();else if(op==='buyut')zoomAt(1.3);else if(op==='kucult')zoomAt(1/1.3);else if(op==='sigdir')fitImage();else if(op==='onceki'&&stepFn)stepFn(-1);else if(op==='sonraki'&&stepFn)stepFn(1);});
    kucukler.addEventListener('click',function(e){var b=e.target.closest('[data-lb-idx]');if(b)show(+b.getAttribute('data-lb-idx'));});
    function renderThumbs(){kucukler.innerHTML=items.length>1?items.map(function(it,i){return '<button type="button" data-lb-idx="'+i+'" class="'+(i===index?'aktif':'')+'" aria-label="'+esc(it.etiket)+'" title="'+esc(it.etiket)+'"><img src="'+esc(it.kucuk||it.url)+'" alt=""></button>';}).join(''):'';}
    function show(i){index=Math.max(0,Math.min(i,items.length-1));var it=items[index];renderThumbs();var serial=++loadSerial;mesaj.classList.add('gizli');img.classList.remove('gizli');img.style.opacity='.35';
      if(!it){img.removeAttribute('src');img.classList.add('gizli');mesaj.classList.remove('gizli');mesaj.innerHTML='Bu kayıtta görüntülenecek görsel yok.';yeniSekme.setAttribute('aria-disabled','true');indir.setAttribute('aria-disabled','true');return;}
      yeniSekme.href=it.ham||it.url;yeniSekme.removeAttribute('aria-disabled');if(it.indir){indir.href=it.indir;indir.removeAttribute('aria-disabled');}else indir.setAttribute('aria-disabled','true');
      var probe=new Image();probe.onload=function(){if(serial!==loadSerial)return;natural={w:probe.naturalWidth,h:probe.naturalHeight};img.src=it.url;img.style.opacity='1';fitImage();};
      probe.onerror=function(){if(serial!==loadSerial)return;img.classList.add('gizli');img.removeAttribute('src');mesaj.classList.remove('gizli');mesaj.innerHTML=it.hataMetni||'Görsel şu an açılamadı.';};
      probe.src=it.url;}
    function open(list,i,meta){items=list||[];meta=meta||{};focusBefore=document.activeElement;baslik.textContent=meta.baslik||'';acik=true;root.classList.remove('gizli');root.setAttribute('aria-hidden','false');document.body.classList.add('lightbox-acik');onceki.disabled=!meta.oncekiVar;sonraki.disabled=!meta.sonrakiVar;show(i||0);var k=root.querySelector('.lb-kapat');if(k)k.focus();}
    function close(){if(!acik)return;acik=false;loadSerial++;root.classList.add('gizli');root.setAttribute('aria-hidden','true');document.body.classList.remove('lightbox-acik');img.removeAttribute('src');if(focusBefore&&typeof focusBefore.focus==='function')focusBefore.focus();}
    return {open:open,close:close,show:show,zoom:zoomAt,fit:fitImage,isOpen:function(){return acik;},onStep:function(fn){stepFn=fn;},setNav:function(prev,next){onceki.disabled=!prev;sonraki.disabled=!next;},index:function(){return index;}};
  }

  /* ---- Toplu onay / onay kaldırma ---- */
  /* Oturum düşmesi (yetki/şifre değişimi): 401 veya "Geçersiz CSRF" 400 → açıklamalı giriş sayfası, geri dönüş adresiyle. */
  function oturumKontrol(e){if(!e)return false;if(e.status===401||(e.status===400&&/csrf/i.test(e.message||''))){window.location='/giris?neden=oturum&sonraki='+encodeURIComponent(location.pathname+location.search);return true;}return false;}
  function topluKur(applied,tamamlandi){
    /* #toplu-arac ve kutular Yenile ile yeniden kurulduğu için her seferinde DOM'dan alınır; dinleyiciler document düzeyinde. */
    function arac(){return document.getElementById('toplu-arac');}
    function boxes(){return Array.prototype.slice.call(document.querySelectorAll('#kayit-sonuclari .kayit-sec'));}
    function selected(){return boxes().filter(function(b){return b.checked&&!b.disabled;}).map(function(b){return +b.value;});}
    function update(){var bar=arac(),n=selected().length;if(bar){bar.classList.toggle('gizli',!n);var s=document.getElementById('toplu-sayi');if(s)s.textContent=n+' seçili';Array.prototype.forEach.call(bar.querySelectorAll('[data-toplu-sayi]'),function(x){x.textContent=n;});}boxes().forEach(function(b){var row=b.closest('.kayit');if(row)row.classList.toggle('secili',b.checked&&!b.disabled);});var all=document.getElementById('sec-hepsi');if(all){var en=boxes().filter(function(b){return !b.disabled;});all.checked=en.length>0&&en.every(function(b){return b.checked;});all.indeterminate=n>0&&!all.checked;}}
    function clear(){boxes().forEach(function(x){x.checked=false;});update();}
    var last=null;
    document.addEventListener('change',function(e){var t=e.target;if(!t)return;if(t.id==='sec-hepsi'){boxes().forEach(function(b){if(!b.disabled)b.checked=t.checked;});update();}else if(t.classList&&t.classList.contains('kayit-sec')){update();}});
    document.addEventListener('click',function(e){var t=e.target;if(!t||!t.closest)return;
      var dugme=t.closest('#toplu-arac [data-toplu]');if(dugme){run(dugme.getAttribute('data-toplu'));return;}
      if(t.closest('#toplu-arac [data-toplu-temizle]')){clear();return;}
      if(!t.classList||!t.classList.contains('kayit-sec'))return;var all=boxes();if(e.shiftKey&&last&&all.indexOf(last)>=0){var a=all.indexOf(last),b=all.indexOf(t);all.slice(Math.min(a,b),Math.max(a,b)+1).forEach(function(x){if(!x.disabled)x.checked=t.checked;});update();}last=t;});
    function run(deger){var ids=selected();if(!ids.length){toast('Önce en az bir kayıt seçin.',true);return;}if(ids.length>300){toast('Tek seferde en çok 300 kayıt işlenebilir; seçimi daraltın.',true);return;}
      if(!confirm(ids.length+' kayıt '+(deger==='1'?'onaylanacak':'için onay kaldırılacak')+'. Devam edilsin mi?'))return;
      var bar=arac(),buttons=bar?Array.prototype.slice.call(bar.querySelectorAll('button')):[];buttons.forEach(function(x){x.disabled=true;});
      kayitPost('/kayitlar/toplu-kt',{ids:ids,deger:deger}).then(function(r){toast(r.mesaj||'Tamamlandı.',!r.degisen);(r.ids||[]).forEach(function(id){applied(id,deger==='1');});if(tamamlandi)tamamlandi(r);clear();}).catch(function(e){if(oturumKontrol(e))return;toast(e.message,true);}).then(function(){buttons.forEach(function(x){x.disabled=false;});});}
    return {update:update,selected:selected,clear:clear};
  }

  function kayitSayfasi(durumFiltresi) {
    var sayfa=document.getElementById('kayit-sayfa'),modal=document.getElementById('modal'); if(!modal)return;
    var dialog=modal.querySelector('.modal-icerik'),form=document.getElementById('m-duzenle'),yf=document.getElementById('m-yorum-form'),formHata=document.getElementById('m-duzenle-hata');
    var acikId=null,acikKayit=null,acan=null,refreshRunning=false,openSerial=0,gorseller=[],gorselIdx=0,lightboxBekliyor=false;
    /* 2.3.1 derin bağlantı: ?ac=<kayıt>&yorum=<yorum> → modal açılır, Konuşma bölümünde ilgili yorum kaydırılıp 3 sn vurgulanır (bir kez). */
    var ilkParam=new URLSearchParams(window.location.search),ilkAc=ilkParam.get('ac')||(sayfa&&sayfa.getAttribute('data-acik'))||'',yorumParam=ilkParam.get('yorum')||(sayfa&&sayfa.getAttribute('data-yorum'))||'',bekleyenYorum=/^\d{1,10}$/.test(yorumParam)?yorumParam:null;
    var lb=lightboxKur(document.getElementById('lightbox'));
    var ust=document.querySelector('header.ust');
    function ustYukseklik(){if(sayfa&&ust)sayfa.style.setProperty('--ust-h',ust.offsetHeight+'px');}
    ustYukseklik();window.addEventListener('resize',ustYukseklik);
    function resultRoot(){return document.getElementById('kayit-sonuclari');}
    function recordIds(){return Array.prototype.map.call((resultRoot()||document).querySelectorAll('.kayit[data-id]'),function(e){return +e.getAttribute('data-id');});}
    function cardOf(id){return document.querySelector('#kayit-sonuclari .kayit[data-id="'+id+'"]');}
    /* Kendi onay/silme/düzenleme/toplu işlemi "Yeni kayıt veya değişiklik var" şeridini tetiklemesin:
       sunucu yanıtındaki damga (veya Yenile sonrası sayfadaki damga) zil yoklamasının damgasıyla aynıysa şerit gösterilmez;
       damga yoksa bir sonraki yoklama sessiz sayılır. */
    function damgaOku(){var r=resultRoot();return (r&&r.getAttribute('data-damga'))||null;}
    var beklenenDamga=damgaOku(),sessizYoklama=false;
    function kendiIslem(r){if(r&&r.damga)beklenenDamga=r.damga;else sessizYoklama=true;}
    var toplu=topluKur(function(id,kt){var card=cardOf(id);if(card){sayacGuncelle(card,'kt',{kt:kt?1:0});applyCard(card,'kt',{kt:kt?1:0});}if(acikId===id)openRecord(id,acan);},kendiIslem);

    /* Satır / kart / düğme tıklamaları (yenileme sonrası da çalışır). */
    document.addEventListener('click',function(e){
      var t=e.target;if(!t||!t.closest)return;
      var detay=t.closest('.detay-dugme[data-kayit-id]');if(detay){e.preventDefault();openRecord(+detay.getAttribute('data-kayit-id'),detay);return;}
      var buyut=t.closest('[data-buyut]');if(buyut){e.preventDefault();e.stopPropagation();openRecord(+buyut.getAttribute('data-buyut'),buyut,true);return;}
      if(t.closest('a,button,input,select,textarea,label,summary'))return;
      var row=t.closest('.kayit[data-id]');var root=resultRoot();
      if(row&&root&&root.contains(row))openRecord(+row.getAttribute('data-id'),row);
    });
    document.addEventListener('keydown',function(e){
      if(e.key!=='Enter'&&e.key!==' ')return;var t=e.target;if(!t||!t.classList||!t.classList.contains('kayit')||!t.hasAttribute('data-id'))return;
      e.preventDefault();openRecord(+t.getAttribute('data-id'),t);
    });
    document.addEventListener('error',function(e){var img=e.target;if(!img||!img.matches||!img.matches('img[data-mini]'))return;var box=img.closest('.mini-kutu,.kart-gorsel,.galeri-gorsel');if(box)box.classList.add('hatali');},true);

    modal.querySelector('.modal-kapat').addEventListener('click',function(){closeRecord();});
    modal.querySelector('.modal-onceki').addEventListener('click',function(){step(-1);}); modal.querySelector('.modal-sonraki').addEventListener('click',function(){step(1);});
    modal.addEventListener('click',function(e){if(e.target===modal)closeRecord();});
    document.addEventListener('keydown',function(e){
      if(lb&&lb.isOpen()){
        if(yaziAlani(e.target))return;
        if(e.key==='Escape'){e.preventDefault();lb.close();}
        else if(e.key==='ArrowLeft'){e.preventDefault();step(-1);}
        else if(e.key==='ArrowRight'){e.preventDefault();step(1);}
        else if(e.key==='+'||e.key==='='){e.preventDefault();lb.zoom(1.3);}
        else if(e.key==='-'){e.preventDefault();lb.zoom(1/1.3);}
        else if(e.key==='0'){e.preventDefault();lb.fit();}
        return;
      }
      if(modal.classList.contains('gizli'))return;
      if(e.key==='Escape'){e.preventDefault();closeRecord();return;}
      if(e.key==='Tab'){var items=focusables(dialog),first=items[0],last=items[items.length-1];if(!items.length)return;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}return;}
      if((e.key==='ArrowLeft'||e.key==='ArrowRight')&&!yaziAlani(e.target)&&!formOpen()){e.preventDefault();step(e.key==='ArrowLeft'?-1:1);}
    });
    form.addEventListener('submit',function(e){e.preventDefault();saveEdit();});
    document.getElementById('m-duzenle-iptal').addEventListener('click',function(){form.classList.add('gizli');formHata.classList.add('gizli');});
    form.addEventListener('input',function(e){if(e.target&&e.target.classList)e.target.classList.remove('hatali');});
    yf.addEventListener('input',saveDraft); yf.addEventListener('change',saveDraft);
    yf.addEventListener('submit',function(e){e.preventDefault();if(!acikKayit)return;var text=yf.elements.yorum.value.trim();if(!text){toast('Göndermeden önce bir yorum yazın.',true);yf.elements.yorum.focus();return;}var btn=yf.querySelector('button[type=submit]');btn.disabled=true;kayitPost('/kayit/'+acikKayit.id+'/yorum',{yorum:text,alici:yf.elements.alici.value,yanit_id:yf.elements.yanit_id.value}).then(function(d){if(!d.ok)throw new Error(d.hata||'Yorum gönderilemedi');kendiIslem(d);clearDraft(acikKayit.id);yf.reset();toast('Gönderildi; ilgili alıcıya bildirildi.');openRecord(acikKayit.id,acan);}).catch(function(x){if(oturumKontrol(x))return;toast(x.message,true);}).then(function(){btn.disabled=false;});});
    document.getElementById('m-taslak-sil').addEventListener('click',function(){if(acikId){clearDraft(acikId);yf.reset();resetReply();toast('Taslak silindi.');}});
    function draftKey(id){return 'kanit-yorum-taslak:'+(window.PANEL_KULLANICI||'')+':'+id;}
    function saveDraft(){if(!acikId||yf.classList.contains('gizli'))return;try{sessionStorage.setItem(draftKey(acikId),JSON.stringify({yorum:yf.elements.yorum.value,alici:yf.elements.alici.value,yanit_id:yf.elements.yanit_id.value}));}catch(_){}}
    function clearDraft(id){try{sessionStorage.removeItem(draftKey(id));}catch(_){}}
    function loadDraft(id){var d;try{d=JSON.parse(sessionStorage.getItem(draftKey(id))||'null');}catch(_){d=null;}if(!d)return;yf.elements.yorum.value=d.yorum||'';yf.elements.yanit_id.value=d.yanit_id||'';if(d.alici)yf.elements.alici.value=d.alici;if(d.yanit_id){yf.elements.alici.disabled=true;document.getElementById('m-yanit-ozet').textContent='Yanıt taslağı korunuyor';document.getElementById('m-yanit-vazgec').classList.remove('gizli');}}
    function resetReply(){yf.elements.yanit_id.value='';yf.elements.alici.disabled=false;document.getElementById('m-yanit-ozet').textContent='';document.getElementById('m-yanit-vazgec').classList.add('gizli');saveDraft();}
    document.getElementById('m-yanit-vazgec').addEventListener('click',resetReply);
    document.getElementById('m-yorumlar').addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-yanit]');if(!b||!acikKayit||!acikKayit.izin_yorum)return;var item=(acikKayit.yorumlar||[]).filter(function(x){return String(x.id)===b.getAttribute('data-yanit');})[0];if(!item)return;yf.elements.yanit_id.value=item.id;yf.elements.alici.disabled=true;document.getElementById('m-yanit-ozet').textContent='#'+item.id+' — '+item.kullanici+' mesajına yanıt';document.getElementById('m-yanit-vazgec').classList.remove('gizli');saveDraft();yf.elements.yorum.focus();});
    document.addEventListener('kp:degisti',function(e){var d=(e&&e.detail)||{};if(d.degisiklik&&beklenenDamga&&d.degisiklik===beklenenDamga){sessizYoklama=false;return;}if(sessizYoklama){sessizYoklama=false;return;}setChangeStrip(true);});
    var refreshBtn=document.getElementById('sonuclari-yenile'),stripBtn=document.getElementById('degisiklik-yenile');
    if(refreshBtn)refreshBtn.addEventListener('click',refreshResults);if(stripBtn)stripBtn.addEventListener('click',refreshResults);
    function refreshResults(){if(refreshRunning)return;var old=resultRoot();if(!old)return;refreshRunning=true;old.setAttribute('aria-busy','true');if(refreshBtn)refreshBtn.disabled=true;
      fetch(window.location.href,{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}}).then(function(r){if(r.redirected)throw kayitHata(401);if(!r.ok)throw new Error('Sonuçlar yenilenemedi.');return r.text();}).then(function(html){var parsed=new DOMParser().parseFromString(html,'text/html'),fresh=parsed.getElementById('kayit-sonuclari');if(!fresh)throw new Error('Yenilenecek sonuç alanı bulunamadı.');old.replaceWith(fresh);var boy=document.getElementById('sayfa-boyu');if(boy)boy.addEventListener('change',function(){window.location.href=boy.value;});toplu.clear();beklenenDamga=damgaOku();if(!beklenenDamga)sessizYoklama=true;setChangeStrip(false);toast('Sonuçlar yenilendi. Filtreleriniz ve taslaklarınız korundu.');}).catch(function(e){if(oturumKontrol(e))return;toast(e.message,true);}).then(function(){refreshRunning=false;if(refreshBtn)refreshBtn.disabled=false;});}

    function formOpen(){return !form.classList.contains('gizli');}
    function neighbours(){var ids=recordIds(),i=ids.indexOf(acikId);return {ids:ids,i:i,prev:i>0,next:i>=0&&i<ids.length-1};}
    function step(delta){var n=neighbours();if(n.i<0){toast('Bu kayıt şu anki listede yok; ‹ › ile gezinmek için listeden bir kayıt açın.');return;}var next=n.i+delta;if(next<0||next>=n.ids.length){toast(delta<0?'Bu sayfadaki ilk kayıttasınız.':'Bu sayfadaki son kayıttasınız.');return;}if(!leaveOk())return;openRecord(n.ids[next],null,lb&&lb.isOpen());}
    function urlAc(id){try{var u=new URL(window.location.href);if(id)u.searchParams.set('ac',String(id));else u.searchParams.delete('ac');if(!(bekleyenYorum&&id&&String(id)===String(ilkAc)))u.searchParams.delete('yorum');history.replaceState(history.state,'',u.pathname+u.search+u.hash);}catch(_){}}
    function yorumVurgula(){if(!bekleyenYorum)return;var hedefId=bekleyenYorum;bekleyenYorum=null;var hedef=document.getElementById('yorum-'+hedefId);if(!hedef){toast('Bildirimdeki yorum bu kayıtta bulunamadı; silinmiş olabilir.',true);return;}var kutu=document.getElementById('m-konusma-kutu');if(kutu)kutu.open=true;hedef.classList.add('vurgu');function kaydir(){try{hedef.scrollIntoView({block:'center'});}catch(_){hedef.scrollIntoView();}}kaydir();setTimeout(kaydir,350);setTimeout(function(){hedef.classList.remove('vurgu');},3000);}
    /* 25: kaydedilmemis duzenleme varsa kapatmadan/gecmeden once sor */
    function editDirty(){if(!acikKayit||!formOpen())return false;return ['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].some(function(n){return String(form.elements[n].value||'').trim()!==String(acikKayit[n]||'').trim();});}
    function leaveOk(){return !editDirty()||confirm('Kaydedilmemiş düzenleme var. Kaydetmeden devam ederseniz değişiklikler kaybolur. Yine de devam edilsin mi?');}
    var gyazoWatchSerial=0;
    function closeRecord(force){if(!force&&!leaveOk())return;if(lb)lb.close();saveDraft();gyazoWatchSerial++;modal.classList.add('gizli');modal.setAttribute('aria-hidden','true');document.body.style.overflow='';var kapanan=acikId;acikId=null;acikKayit=null;urlAc(null);
      /* Bildirimden (derin bağlantı) açılan pencerede tetikleyici yok: odak kaybolmasın, ilgili satıra ya da sonuç alanına dönsün. */
      var hedef=(acan&&typeof acan.focus==='function')?acan:(cardOf(kapanan)||resultRoot()||document.querySelector('h1'));
      if(hedef){if(!acan&&!hedef.hasAttribute('tabindex'))hedef.setAttribute('tabindex','-1');try{hedef.focus({preventScroll:true});}catch(_){hedef.focus();}}}
    function openRecord(id,trigger,buyut){
      var serial=++openSerial;if(acikId&&acikId!==id){saveDraft();yf.reset();resetReply();}
      acikId=id;if(trigger)acan=trigger;lightboxBekliyor=!!buyut;urlAc(id);
      modal.classList.remove('gizli');modal.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';form.classList.add('gizli');formHata.classList.add('gizli');
      document.getElementById('m-alanlar').innerHTML='<div class="genis"><dt>Yükleniyor</dt><dd>Kayıt ayrıntısı getiriliyor…</dd></div>';
      if(!lb||!lb.isOpen())modal.querySelector('.modal-kapat').focus();
      kayitIstek('/kayit/'+id).then(function(k){if(acikId===id&&serial===openSerial)showRecord(k);}).catch(function(e){if(serial!==openSerial)return;if(oturumKontrol(e))return;modalHata(id,e);if(e.status===409)toastEylem(e.message,'Yenile',function(){openRecord(id,acan);});else toast(e.message,true);if(lb&&lb.isOpen())lb.open([],0,{baslik:'Kayıt #'+id,oncekiVar:neighbours().prev,sonrakiVar:neighbours().next});});
    }
    var MODAL_BOLUMLER=['m-onay-ozet','m-konusma-kutu','m-gecmis-kutu','m-gorsel-araclar','m-proje'];
    function modalBolumleriGoster(){MODAL_BOLUMLER.forEach(function(i){var x=document.getElementById(i);if(x)x.classList.remove('gizli');});}
    /* Kayıt açılamadı (yetki yok / bulunamadı / sunucu hatası): yalnız başlık + açıklama + Kapat kalır; şerit, düğmeler, görsel araçları ve bölümler temizlenip gizlenir. */
    function modalHata(id,e){
      acikKayit=null;gorseller=[];gorselIdx=0;gyazoWatchSerial++;
      var proje=e&&e.veri&&e.veri.proje?String(e.veri.proje):'';
      document.getElementById('modal-baslik').textContent='Kayıt açılamadı';
      var p=document.getElementById('m-proje');p.textContent='';p.style.background='';p.style.color='';p.classList.add('gizli');
      document.getElementById('m-kategori').textContent='';document.getElementById('m-kt').classList.add('gizli');document.getElementById('m-bekliyor').classList.add('gizli');document.getElementById('m-durum').innerHTML='';
      var n=neighbours();document.getElementById('m-konum').textContent=n.i>=0?(n.i+1)+' / '+n.ids.length:'';modal.querySelector('.modal-onceki').disabled=!n.prev;modal.querySelector('.modal-sonraki').disabled=!n.next;
      var onay=document.getElementById('m-onay-ozet');onay.textContent='';onay.classList.remove('onayli');
      document.getElementById('m-butonlar').innerHTML='';var notu=document.getElementById('m-eylem-notu');notu.textContent='';notu.classList.add('gizli');
      ['m-uyari','m-gorsel-kayip','m-gyazo','m-link','m-kucukler','m-yorumlar','m-gecmis'].forEach(function(i){var x=document.getElementById(i);if(x){x.innerHTML='';if(i!=='m-link'&&i!=='m-kucukler'&&i!=='m-yorumlar'&&i!=='m-gecmis')x.classList.add('gizli');}});
      document.getElementById('m-yorum-sayi').textContent='0';document.getElementById('m-gecmis-sayi').textContent='0';yf.classList.add('gizli');
      var image=document.getElementById('m-gorsel');image.onload=null;image.onerror=null;image.classList.add('gizli');image.removeAttribute('src');document.getElementById('m-gorsel-yukleniyor').classList.add('gizli');
      var yok=document.getElementById('m-gorsel-yok');yok.innerHTML='<b>Kayıt açılamadı</b>'+esc(e.message||'');yok.classList.remove('gizli');
      document.getElementById('m-buyut').disabled=true;var ys=document.getElementById('m-yeni-sekme'),ind=document.getElementById('m-indir');ys.setAttribute('aria-disabled','true');ys.href='#';ind.setAttribute('aria-disabled','true');ind.removeAttribute('href');
      MODAL_BOLUMLER.forEach(function(i){var x=document.getElementById(i);if(x)x.classList.add('gizli');});
      var onayYok=document.getElementById('m-onay-yok');if(onayYok)onayYok.classList.add('gizli');
      var baslik=e.status===403?'Bu kayıt için yetkiniz yok':e.status===404?'Kayıt bulunamadı':'Açılamadı';
      if(e.status===403&&e.veri&&e.veri.neden==='onay_yok')baslik='Bu kaydın onayı yok';
      if(e.status===403&&e.veri&&e.veri.neden==='silindi')baslik='Bu kayıt silinmiş';
      var mesaj=e.message||'Kayıt açılamadı.';if(proje&&mesaj.indexOf(proje)<0)mesaj+=' Kayıt '+proje+' projesine ait.';
      document.getElementById('m-alanlar').innerHTML='<div class="genis"><dt>'+esc(baslik)+'</dt><dd>'+esc(mesaj)+(e.status===403&&!(e.veri&&e.veri.neden==='onay_yok')?'<br><small>Gerekirse süperadminden bu proje için yetki isteyin.</small>':'')+'</dd></div>';
    }
    /* 2.3.2: yer tutucu, görselin geldiği dış siteyi söyler (link_kaynak: gyazo|snappark|teamzone|onedrive|dosya|diger) */
    var DIS_SITE={snappark:'Snappark',teamzone:'Teamzone',onedrive:'OneDrive'};
    function linkAc(k){return k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'';}
    function disHataMetni(k){var ad=DIS_SITE[k.link_kaynak];return ad?'Görsel dış sitede ('+ad+'); açılamadı.'+(k.dis_link?' <a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':''):null;}
    function gorselPlaceholder(k,hata){var yok=document.getElementById('m-gorsel-yok');var lk=k.link_kaynak;var gyazo=lk?lk==='gyazo':(/gyazo\.com/i.test(k.dis_link||'')&&!/teamzone\./i.test(k.dis_link||''));var dis=lk==='snappark'||lk==='teamzone';var html;
      if(k.gorsel_bozuk)html='<b>Görsel açılamadı</b>Dosya sunucuda var ama bozuk ya da okunamıyor. Dosyayı indirip bilgisayarınızda deneyebilir veya Arşiv sayfasından yeni görsel ilişkilendirebilirsiniz.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
      else if(hata&&k.gorsel_kaynak==='gyazo'||(!hata&&!k.gorsel_var&&gyazo))html='<b>Görsel yok (eski Gyazo linki açılamadı)</b>Bağlantı artık yanıt vermiyor ya da sunucudan erişilemiyor.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
      else if(dis&&(hata||(!k.gorsel_var&&!k.gorsel_kayip)))html='<b>Görsel dış sitede ('+DIS_SITE[lk]+'); açılamadı</b>Sunucu görseli getiremedi: bağlantı kaldırılmış ya da site oturum istiyor olabilir.'+linkAc(k);
      else if(hata)html='<b>Görsel şu an açılamadı</b>Dosya sunucuda bulunamadı ya da bozuk.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
      else if(k.gorsel_kayip)html='<b>Görsel dosyası sunucuda bulunamadı</b>Dosya silinmiş veya taşınmış olabilir'+(k.gorsel_dosya_adi?' ('+esc(k.gorsel_dosya_adi)+')':'')+'. Arşiv\'den yeniden ilişkilendirebilirsiniz.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
      else if(k.dis_link&&lk==='onedrive')html='<b>Görsel dış sitede (OneDrive)</b>Sunucuda kopyası yok; görmek için bağlantıyı açın.'+linkAc(k);
      else if(k.dis_link&&lk!=='dosya')html='<b>Görsel dış bağlantıda</b>Sunucuda kopyası yok; görmek için bağlantıyı açın.'+linkAc(k);
      else if(k.dis_link)html='<b>Yerel görsel yok</b><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>';
      else html='<b>Görsel yok</b>Bu kayıtla ilişkili bir kanıt görseli bulunmuyor.';
      yok.innerHTML=html;yok.classList.remove('gizli');}
    function gorselGoster(i){var image=document.getElementById('m-gorsel'),yok=document.getElementById('m-gorsel-yok'),loading=document.getElementById('m-gorsel-yukleniyor'),k=acikKayit;if(!k)return;gorselIdx=i;
      Array.prototype.forEach.call(document.querySelectorAll('#m-kucukler button'),function(b,j){b.classList.toggle('aktif',j===i);});
      var it=gorseller[i];image.onerror=null;image.onload=null;
      if(!it){image.classList.add('gizli');image.removeAttribute('src');loading.classList.add('gizli');gorselPlaceholder(k,false);return;}
      yok.classList.add('gizli');loading.classList.remove('gizli');image.classList.remove('gizli');image.style.opacity='.4';
      image.onload=function(){loading.classList.add('gizli');image.style.opacity='1';};
      image.onerror=function(){loading.classList.add('gizli');image.classList.add('gizli');image.removeAttribute('src');gorselPlaceholder(k,true);};
      image.src=it.url;
      document.getElementById('m-yeni-sekme').href=it.ham;document.getElementById('m-indir').href=it.indir;}
    function openLightbox(){if(!lb||!acikKayit)return;var n=neighbours();lb.open(gorseller,gorselIdx,{baslik:'Kayıt #'+acikKayit.id+' · '+(acikKayit.proje||'')+(acikKayit.personel?' · '+acikKayit.personel:''),oncekiVar:n.prev,sonrakiVar:n.next});}
    document.getElementById('m-buyut').addEventListener('click',openLightbox);
    document.getElementById('m-gorsel').addEventListener('click',openLightbox);
    document.getElementById('m-kucukler').addEventListener('click',function(e){var b=e.target.closest('[data-gorsel-idx]');if(b)gorselGoster(+b.getAttribute('data-gorsel-idx'));});
    if(lb)lb.onStep(function(delta){step(delta);});

    function showRecord(k){
      acikKayit=k;var n=neighbours();modalBolumleriGoster();
      document.getElementById('modal-baslik').textContent='Kayıt #'+k.id;
      document.getElementById('m-konum').textContent=n.i>=0?(n.i+1)+' / '+n.ids.length:'';
      modal.querySelector('.modal-onceki').disabled=!n.prev;modal.querySelector('.modal-sonraki').disabled=!n.next;
      yf.classList.toggle('gizli',!k.izin_yorum);yf.elements.alici.disabled=false;document.getElementById('m-yanit-ozet').textContent='';document.getElementById('m-yanit-vazgec').classList.add('gizli');
      yf.elements.alici.innerHTML='<option value="">Tüm ilgili proje sorumluları</option>'+(k.yorum_alicilari||[]).map(function(u){return '<option value="'+esc(u.kullanici_adi)+'">'+esc(u.ad)+' ('+esc(u.kullanici_adi)+')</option>';}).join('');loadDraft(k.id);
      var comments=k.yorumlar||[];document.getElementById('m-yorum-sayi').textContent=comments.length;
      document.getElementById('m-yorumlar').innerHTML=comments.map(function(x){var type={soru:'Soru',yanit:'Yanıt',yorum:'Yorum'}[x.tur]||'Yorum';return '<li id="yorum-'+x.id+'"><div class="yorum-baslik"><b>'+esc(x.kullanici)+'</b><span class="etiket-kucuk">'+type+'</span><small>'+esc(x.zaman)+(x.alici?' · Alıcı: '+esc(x.alici):'')+'</small></div>'+(x.yanit_id?'<small>Yanıt: <a href="#yorum-'+x.yanit_id+'">#'+x.yanit_id+'</a></small>':'')+'<p>'+esc(x.metin)+'</p>'+(k.izin_yorum?'<button class="btn kucuk" type="button" data-yanit="'+x.id+'">Yanıtla</button>':'')+'</li>';}).join('')||'<li class="bos">Henüz yorum yok.'+(k.izin_yorum?' İlk notu aşağıdan ekleyebilirsiniz.':'')+'</li>';
      var p=document.getElementById('m-proje');p.textContent=k.proje||'—';p.style.background=k.renk||'#64748b';p.style.color=yaziRengi(k.renk);
      document.getElementById('m-kategori').textContent=k.kategori||'';
      document.getElementById('m-kt').classList.toggle('gizli',!k.kt);document.getElementById('m-bekliyor').classList.toggle('gizli',!!k.kt||!!k.silindi);
      var onayYok=document.getElementById('m-onay-yok');if(onayYok)onayYok.classList.toggle('gizli',!k.onay_uyari);
      var onay=document.getElementById('m-onay-ozet');onay.textContent=k.kt?(k.kt_kim?'Onaylayan: '+k.kt_kim+(k.kt_zaman?' · '+k.kt_zaman:''):'Eski kaynaktan onaylı aktarıldı; onaylayan kişi bilgisi yok.'):(k.silindi?'Silinmiş kayıt'+(k.silen?' · silen: '+k.silen:'')+(k.silme_zamani?' · '+k.silme_zamani:''):'Onay bekliyor');onay.classList.toggle('onayli',!!k.kt);
      var state=[];if(k.silindi)state.push('<span class="etiket-kucuk kirmizi-arka">Silindi'+(k.silen?' ('+esc(k.silen)+')':'')+'</span>');else if(k.excel_durum==='silinmis')state.push('<span class="etiket-kucuk gri-arka">Eski kaynakta yok</span>');if(k.bekleyen_hata)state.push('<span class="etiket-kucuk kirmizi-arka">İşlem hatası</span>');else if(k.bekleyen_islem)state.push('<span class="etiket-kucuk turuncu-arka">İşleniyor</span>');document.getElementById('m-durum').innerHTML=state.join(' ');
      /* Görseller */
      gorseller=[];var v='?v='+encodeURIComponent(k.guncelleme||k.surum||'');
      if(k.gorsel_url&&!k.gorsel_bozuk)gorseller.push({url:k.gorsel_url+v,ham:k.gorsel_url,kucuk:k.kucuk_url,indir:k.indir_url,etiket:'Görsel 1',hataMetni:k.gorsel_kaynak==='gyazo'?'Görsel yok (eski Gyazo linki açılamadı).'+(k.dis_link?' <a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':''):(disHataMetni(k)||'Görsel şu an açılamadı.')});
      if(k.gorsel2_url)gorseller.push({url:k.gorsel2_url+v,ham:k.gorsel2_url,kucuk:k.kucuk2_url,indir:k.gorsel2_url+'&indir=1',etiket:'Görsel 2',hataMetni:'İkinci görsel şu an açılamadı.'});
      document.getElementById('m-kucukler').innerHTML=gorseller.length>1?gorseller.map(function(it,i){return '<button type="button" data-gorsel-idx="'+i+'" aria-label="'+esc(it.etiket)+'" title="'+esc(it.etiket)+'"><img src="'+esc(it.kucuk||it.url)+'" alt=""><span>'+esc(it.etiket)+'</span></button>';}).join(''):'';
      var buyutBtn=document.getElementById('m-buyut'),yeniSekme=document.getElementById('m-yeni-sekme'),indirBtn=document.getElementById('m-indir');
      buyutBtn.disabled=!gorseller.length;
      if(gorseller.length){yeniSekme.removeAttribute('aria-disabled');indirBtn.removeAttribute('aria-disabled');}
      else if(k.gorsel_bozuk&&k.indir_url){yeniSekme.setAttribute('aria-disabled','true');yeniSekme.href='#';indirBtn.href=k.indir_url;indirBtn.removeAttribute('aria-disabled');indirBtn.title='Bozuk dosyayı yine de indir';}
      else{yeniSekme.setAttribute('aria-disabled',k.dis_link?'false':'true');yeniSekme.href=k.dis_link||'#';indirBtn.setAttribute('aria-disabled','true');indirBtn.removeAttribute('href');}
      gorselGoster(0);
      /* Bilgi alanları */
      var fields=[['Personel kodu',k.personel,'buyuk'],['Kategori',k.kategori],['Üye ID',k.uye_id],['Ana üye ID',k.ana_uye_id],['Lead ID',k.lead_id],['Sessiz / Telesekreter',k.tip],['Tarih',k.tarih||k.tarih_ham],['Giriş tipi',k.giris_tipi_metni],['Kaynak',k.kaynak_metni||k.kaynak],['Ekleyen',k.ekleyen_ad?(k.ekleyen_ad+(k.ekleyen_id?' ('+k.ekleyen_id+')':'')+(k.ekleyen_guven==='tahmini'?' · tahmini eşleşme':'')):(k.ekleyen_id||'')],['Kayıt ID',k.id],['Görsel bağlantısı',k.dis_link,'genis'],['2. görsel bağlantısı',k.dis_link2,'genis'],['Görsel dosyası',k.gorsel_dosya_adi],['2. görsel dosyası',k.gorsel2_dosya_adi],['Eski Excel satırı',k.kaynak==='excel'||k.kaynak==='legacy_excel'?k.excel_satir:null],['Son güncelleme',k.guncelleme],['Açıklama',k.aciklama,'genis'],['Ek not',k.ek_not,'genis']];
      (k.soru_cevaplar||[]).filter(function(q){return !q.preset;}).forEach(function(q){fields.push([q.label,q.value]);});
      document.getElementById('m-alanlar').innerHTML=fields.filter(function(x){return x[1]!==null&&x[1]!==undefined&&x[1]!=='';}).map(function(x){var cls=x[2]||'';return '<div class="'+(cls==='genis'?'genis':'')+'"><dt>'+esc(x[0])+'</dt><dd class="'+(cls==='buyuk'?'buyuk':'')+'">'+esc(x[1])+'</dd></div>';}).join('')||'<div class="genis"><dt>Bilgi</dt><dd>Bu kayıtta doldurulmuş alan yok.</dd></div>';
      Array.prototype.forEach.call(document.querySelectorAll('#m-alanlar dt'),function(dt){if(/bağlantısı$/.test(dt.textContent)){var dd=dt.nextElementSibling,url=dd.textContent;if(/^https?:\/\//.test(url)){var a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.textContent=url;dd.textContent='';dd.appendChild(a);}}});
      if(k.ekleyen_id){Array.prototype.forEach.call(document.querySelectorAll('#m-alanlar dt'),function(dt){if(dt.textContent==='Ekleyen'){var dd=dt.nextElementSibling,a=document.createElement('a');a.href='/telegram/kullanici/'+encodeURIComponent(k.ekleyen_id)+'/kanitlar';a.textContent=dd.textContent+' — kanıt profili';dd.textContent='';dd.appendChild(a);}});}
      document.getElementById('m-link').innerHTML=(k.dis_link?'Link: <a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">'+esc(k.dis_link)+'</a> <button class="btn kucuk" type="button" data-kopyala="'+esc(k.dis_link)+'">Kopyala</button>':(k.link?'Link alanı: '+esc(k.link):''))+(k.dis_link2?'<br>İkinci link: <a href="'+esc(k.dis_link2)+'" target="_blank" rel="noopener">'+esc(k.dis_link2)+'</a>':'');
      /* Eylemler */
      var buttons=[],notlar=[],gy=k.gyazo_is||null,gyPending=!!(gy&&gy.pending)||!!k.gyazo_bekliyor;
      if(!k.silindi){
        if(k.izin_kt)buttons.push(k.kt?'<button class="btn" type="button" data-islem="kt" data-deger="0">Onayı kaldır</button>':'<button class="btn basari" type="button" data-islem="kt" data-deger="1">Onayla</button>');
        if(k.izin_duzenle)buttons.push('<button class="btn" type="button" data-islem="duzenle">Düzenle</button>');
        if(k.izin_gyazo&&!(gy&&gy.converted)){
          if(!k.gyazo_hazir){buttons.push('<button class="btn" type="button" data-islem="gyazo" disabled>Gyazo’ya dönüştür</button>');notlar.push('Gyazo dönüştürme kapalı: sunucuda Gyazo anahtarı tanımlı değil; süperadmin ekleyebilir.');}
          else if(gyPending)buttons.push('<button class="btn" type="button" data-islem="gyazo" disabled>Gyazo işlemi sürüyor</button>');
          else if(gy&&gy.tekrar_olur)buttons.push('<button class="btn" type="button" data-islem="gyazo" data-tekrar="1">Gyazo’yu tekrar dene</button>');
          else buttons.push('<button class="btn" type="button" data-islem="gyazo">Gyazo’ya dönüştür</button>');
        }
        if(k.izin_sil)buttons.push('<button class="btn tehlike" type="button" data-islem="sil">Sil</button>');
        if(!buttons.length)notlar.push('Bu projede yalnız görüntüleme yetkiniz var; onaylama, düzenleme ve silme için proje yetkisi gerekir.');
      }else{
        if(k.izin_sil&&k.geri_al_olur){buttons.push('<button class="btn birincil" type="button" data-islem="geri_al">Geri al</button>');notlar.push('Silinmiş kayıtta onaylama ve düzenleme yapılmaz; önce "Geri al" ile kaydı geri getirin.');}
        else notlar.push('Bu kayıt silinmiş'+(k.silen?' ('+k.silen+')':'')+'. Geri alma yetkiniz olmadığı için işlem yapılamıyor; gerekirse proje sorumlusuna veya süperadmine bildirin.');
      }
      var box=document.getElementById('m-butonlar');box.innerHTML=buttons.join('');Array.prototype.forEach.call(box.querySelectorAll('button'),function(b){b.addEventListener('click',function(){recordAction(b.getAttribute('data-islem'),b);});});
      var notu=document.getElementById('m-eylem-notu');notu.textContent=notlar.join(' ');notu.classList.toggle('gizli',!notlar.length);
      var uyari=document.getElementById('m-uyari');
      if(k.bekleyen_hata)uyari.innerHTML='<b>Son otomatik işlem başarısız oldu.</b> '+esc(k.bekleyen_hata)+' Yerel kanıt korunuyor; sorun sürerse yöneticinize bildirin.';
      else if(k.bekleyen_islem)uyari.innerHTML='<b>Arka planda işlem sürüyor:</b> '+esc(k.bekleyen_islem)+'. Tamamlanınca kayıt kendiliğinden güncellenir.';
      else uyari.innerHTML='';
      uyari.classList.toggle('gizli',!uyari.innerHTML);uyari.classList.toggle('bilgi',!k.bekleyen_hata&&!!k.bekleyen_islem);
      var kayip=document.getElementById('m-gorsel-kayip');
      if(k.gorsel_kayip){kayip.innerHTML='<b>Görsel dosyası sunucuda bulunamadı</b> (silinmiş veya taşınmış olabilir). Arşiv\'den yeniden ilişkilendirebilirsiniz.'+(k.gorsel_dosya_adi?' <span class="kucukyazi">Dosya: '+esc(k.gorsel_dosya_adi)+'</span>':'')+(k.gorsel_kaynak==='gyazo'?' <span class="kucukyazi">Şimdilik eski Gyazo bağlantısı gösteriliyor.</span>':'');kayip.classList.remove('gizli');}
      else{kayip.innerHTML='';kayip.classList.add('gizli');}
      renderGyazo(gy,k);if(gyPending)watchGyazo(k.id);
      var history=k.gecmis||[];document.getElementById('m-gecmis-sayi').textContent=history.length;
      document.getElementById('m-gecmis').innerHTML=history.map(function(h){var basit=h.islem==='onayla'||h.islem==='onay_kaldir'||h.islem==='sil'||h.islem==='geri_al';var detail=h.yeni&&!basit?'<small>'+esc(h.yeni)+'</small>':'';var sebep=h.aciklama?' · '+(h.islem==='sil'?'Sebep: ':'Not: ')+esc(h.aciklama):'';return '<li><time>'+esc(h.zaman)+'</time><div><span class="islem">'+esc(islemAdi(h.islem))+'</span> · '+esc(h.kullanici)+sebep+detail+'</div></li>';}).join('')||'<li><time>—</time><div>Henüz işlem yok.</div></li>';
      if(lightboxBekliyor){lightboxBekliyor=false;if(gorseller.length)openLightbox();else toast('Bu kayıtta büyütülecek görsel yok.');}
      else if(lb&&lb.isOpen())openLightbox();
      if(bekleyenYorum&&String(k.id)===String(ilkAc))yorumVurgula();
    }
    function kategoriSecenekleri(k){var sel=form.elements.kategori,ipucu=document.getElementById('m-kategori-ipucu'),mevcut=k.kategori||'';sel.classList.remove('hatali');
      function doldur(liste){var bulundu=false,html='<option value="">— Kategori yok —</option>';liste.forEach(function(x){var secili=x.toLowerCase()===mevcut.toLowerCase();if(secili)bulundu=true;html+='<option value="'+esc(x)+'"'+(secili?' selected':'')+'>'+esc(x)+'</option>';});
        if(mevcut&&!bulundu)html+='<option value="'+esc(mevcut)+'" selected>'+esc(mevcut)+' (bu projede tanımlı değil)</option>';
        sel.innerHTML=html;sel.disabled=false;
        if(ipucu)ipucu.textContent=liste.length?(k.proje+' projesine tanımlı '+liste.length+' kategori. Listede olmayan bir kategori gerekiyorsa Yönetim → Katalog bölümünden eklenir.'):('Bu projeye tanımlı kategori yok; Yönetim → Katalog bölümünden eklenebilir.');}
      sel.innerHTML='<option value="'+esc(mevcut)+'" selected>'+(mevcut?esc(mevcut):'— Kategori yok —')+'</option>';sel.disabled=true;if(ipucu)ipucu.textContent='Kategoriler yükleniyor…';
      kayitIstek('/kategoriler.json?proje='+encodeURIComponent(k.proje||'')).then(function(d){doldur(d.kategoriler||[]);}).catch(function(e){doldur(mevcut?[mevcut]:[]);if(ipucu)ipucu.textContent='Kategori listesi alınamadı ('+e.message+'); yalnız mevcut kategori korunabilir.';});}
    function validateEdit(d){var errors=[];['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].forEach(function(n){form.elements[n].classList.remove('hatali');if(d[n].length>500){errors.push('Alanlar en çok 500 karakter olabilir.');form.elements[n].classList.add('hatali');}if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(d[n])){errors.push('Alanlarda kontrol karakteri kullanılamaz.');form.elements[n].classList.add('hatali');}});
      if(!d.personel&&!d.uye_id&&!d.ana_uye_id&&!d.lead_id){errors.push('Personel kodu, üye ID, ana üye ID veya lead ID alanlarından en az biri dolu olmalı.');form.elements.personel.classList.add('hatali');}
      ['uye_id','ana_uye_id','lead_id'].forEach(function(n){if(d[n]&&/\s/.test(d[n])){errors.push((n==='uye_id'?'Üye ID':n==='ana_uye_id'?'Ana üye ID':'Lead ID')+' boşluk içeremez.');form.elements[n].classList.add('hatali');}});
      return errors.filter(function(x,i,a){return a.indexOf(x)===i;});}
    function recordAction(action,button){
      var k=acikKayit;if(!k)return;
      if(action==='duzenle'){['personel','uye_id','ana_uye_id','lead_id','tip','aciklama'].forEach(function(n){form.elements[n].value=k[n]||'';form.elements[n].classList.remove('hatali');});kategoriSecenekleri(k);formHata.classList.add('gizli');form.classList.remove('gizli');form.elements.personel.focus();return;}
      if(action==='gyazo'&&!confirm((button.getAttribute('data-tekrar')?'Dönüşüm yeniden denenecek. ':'')+'Görsel Gyazo dış servisine gönderilecek; yerel görsel korunur. Dönüştürülsün mü?'))return;
      var data=action==='kt'?{deger:button.getAttribute('data-deger')}:{};
      if(action==='gyazo'&&button.getAttribute('data-tekrar'))data.tekrar='1';
      if(action==='sil'){var sebep=prompt('Kayıt silinenlere taşınacak. Silme nedeni (isteğe bağlı):','');if(sebep===null)return;data.sebep=sebep.trim();}
      if(action==='geri_al'&&!confirm('Kayıt geri alınacak. Emin misiniz?'))return;
      var url='/kayit/'+k.id+'/'+(action==='geri_al'?'geri-al':action);data.surum=k.surum;button.disabled=true;
      kayitPost(url,data).then(function(r){if(!r.ok)throw new Error(r.hata||'İşlem yapılamadı');toast(r.mesaj||(action==='kt'?(r.kt?'Onaylandı.':'Onay kaldırıldı.'):(action==='sil'?'Silinenlere taşındı.':action==='geri_al'?'Geri alındı.':'Kaydedildi.')),action==='gyazo'&&!r.pending&&!r.converted);if(action!=='gyazo'&&r.degisiklik!==false)kendiIslem(r);if(action==='gyazo'&&r.pending)watchGyazo(k.id);updateCard(k.id,action,r);openRecord(k.id,acan);}).catch(function(e){button.disabled=false;if(oturumKontrol(e))return;if(e.status===409){toast(e.message,true);openRecord(k.id,acan);}else toast(e.message,true);});
    }
    function renderGyazo(gy,k){var box=document.getElementById('m-gyazo');if(!box)return;if(!gy||!gy.durum||(gy.converted&&k&&k.gorsel_kaynak!=='yerel')){box.innerHTML='';box.classList.add('gizli');return;}
      var sinif=gy.pending?'suruyor':(gy.converted?'tamam':'hata');
      var html='<b>Gyazo dönüşümü: '+esc(gy.durum_adi||gy.durum)+'</b>'+(gy.deneme?' <span class="kucukyazi">('+gy.deneme+' deneme)</span>':'')+'<div>'+esc(gy.mesaj||'')+'</div>';
      if(gy.hata&&!gy.pending&&(gy.mesaj||'').indexOf(gy.hata)<0)html+='<div class="gyazo-hata">Hata: '+esc(gy.hata)+'</div>';
      if(gy.url)html+='<div><a href="'+esc(gy.url)+'" target="_blank" rel="noopener">'+esc(gy.url)+'</a></div>';
      if(gy.pending)html+='<div class="kucukyazi">Bu pencere açıkken durum her birkaç saniyede bir yenilenir.</div>';
      box.innerHTML=html;box.className='gyazo-durum '+sinif;box.classList.remove('gizli');}
    function watchGyazo(id){var serial=++gyazoWatchSerial,tries=0;function check(){if(serial!==gyazoWatchSerial||acikId!==id||tries++>150)return;kayitIstek('/kayit/'+id+'/gyazo-durum').then(function(d){if(serial!==gyazoWatchSerial||acikId!==id)return;renderGyazo(d,acikKayit);if(d.pending){setTimeout(check,3000);return;}toast(d.mesaj||'Dönüşüm tamamlandı',!d.converted);if(form.classList.contains('gizli')&&!yf.elements.yorum.value.trim())openRecord(id,acan);else setChangeStrip(true);}).catch(function(){if(serial===gyazoWatchSerial&&acikId===id)setTimeout(check,6000);});}setTimeout(check,2500);}
    function saveEdit(){var k=acikKayit;if(!k)return;var d={};['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].forEach(function(n){d[n]=form.elements[n].value.trim();});
      var errors=validateEdit(d);if(errors.length){formHata.textContent=errors.join(' ');formHata.classList.remove('gizli');return;}formHata.classList.add('gizli');d.surum=k.surum;
      var btn=form.querySelector('button[type=submit]');btn.disabled=true;
      kayitPost('/kayit/'+k.id+'/duzenle',d).then(function(r){if(!r.ok)throw new Error(r.hata||'Kaydedilemedi');if(r.degisiklik!==false)kendiIslem(r);toast(r.degisiklik===false?'Değişiklik yok.':'Kaydedildi.');form.classList.add('gizli');var c=cardOf(k.id);if(c){var b=c.querySelector('.satir1 b, .galeri-bilgi b, td.k-personel b');if(b)b.textContent=d.personel||'—';var kt=c.querySelector('td.k-kategori, .satir1 .kat');if(kt)kt.textContent=d.kategori||'—';}openRecord(k.id,acan);}).catch(function(e){if(oturumKontrol(e))return;if(e.status===409){formHata.textContent=e.message;formHata.classList.remove('gizli');toastEylem(e.message,'Yenile',function(){openRecord(k.id,acan);});}else{formHata.textContent=e.message;formHata.classList.remove('gizli');toast(e.message,true);}}).then(function(){btn.disabled=false;});}
    function sayacGuncelle(card,action,r){
      function bump(name,delta){var el=document.getElementById('sayac-'+name);if(!el)return;el.textContent=Math.max(0,(parseInt(el.textContent,10)||0)+delta);}
      var kt=card.getAttribute('data-kt')==='1',silindi=card.getAttribute('data-silindi')==='1';
      if(action==='kt'&&!silindi&&!!r.kt!==kt){bump('bekleyen',r.kt?-1:1);bump('onayli',r.kt?1:-1);}
      if(action==='sil'&&!silindi){bump(kt?'onayli':'bekleyen',-1);bump('silinen',1);}
      if(action==='geri_al'&&silindi){bump(kt?'onayli':'bekleyen',1);bump('silinen',-1);}
    }
    function applyCard(card,action,r){
      if(action==='kt'){card.setAttribute('data-kt',r.kt?'1':'0');card.classList.toggle('onayli',!!r.kt);var rz=card.querySelector('.durum-rozet');if(rz){rz.className='durum-rozet '+(r.kt?'onayli':'bekliyor');rz.textContent=r.kt?'Onaylı':'Bekliyor';}}
      if(action==='sil'){card.setAttribute('data-silindi','1');card.classList.add('silik');}
      if(action==='geri_al'){card.setAttribute('data-silindi','0');card.classList.remove('silik');}
      var remove=(action==='kt'&&durumFiltresi==='bekleyen'&&r.kt)||(action==='kt'&&durumFiltresi==='onayli'&&!r.kt)||(action==='sil'&&durumFiltresi!=='hepsi'&&durumFiltresi!=='silinen')||(action==='geri_al'&&durumFiltresi==='silinen');
      if(remove)card.classList.add('cikarildi');
    }
    function updateCard(id,action,r){var card=cardOf(id);if(!card)return;sayacGuncelle(card,action,r);applyCard(card,action,r);}
    var acParam=new URLSearchParams(window.location.search).get('ac')||(sayfa&&sayfa.getAttribute('data-acik'));
    if(acParam&&+acParam>0)openRecord(+acParam,null);
    initRecordFilters();
  }
  function initRecordFilters(){
    var form=document.getElementById('filtre-form');if(!form)return;
    var tumu=document.getElementById('filtre-tumu'),checks=Array.prototype.slice.call(form.querySelectorAll('input[name="proje"]')),busy=false;
    function cleanEmpty(){Array.prototype.forEach.call(form.querySelectorAll('input,select'),function(el){if(el.type==='hidden'||el.type==='submit')return;if(el.type==='checkbox'){if(!el.checked)el.disabled=true;}else if(!String(el.value||'').trim())el.disabled=true;});}
    function submit(){if(busy)return;busy=true;form.setAttribute('aria-busy','true');form.classList.add('gonderiliyor');if(form.requestSubmit)form.requestSubmit();else{cleanEmpty();form.submit();}}
    function syncTumu(){var any=checks.some(function(c){return c.checked;});if(tumu){tumu.classList.toggle('aktif',!any);tumu.setAttribute('aria-pressed',String(!any));}}
    checks.forEach(function(x){x.addEventListener('change',function(){x.closest('.proje-cip').classList.toggle('aktif',x.checked);syncTumu();submit();});});
    if(tumu)tumu.addEventListener('click',function(){if(!checks.some(function(c){return c.checked;}))return;checks.forEach(function(c){c.checked=false;c.closest('.proje-cip').classList.remove('aktif');});syncTumu();submit();});
    Array.prototype.forEach.call(form.querySelectorAll('[data-otomatik-gonder]'),function(el){el.addEventListener('change',submit);});
    var tarihsiz=form.querySelector('input[name="tarihsiz"]');
    if(tarihsiz){tarihsiz.addEventListener('change',function(){if(tarihsiz.checked)['tarih1','tarih2'].forEach(function(n){if(form.elements[n])form.elements[n].value='';});});['tarih1','tarih2'].forEach(function(n){if(form.elements[n])form.elements[n].addEventListener('input',function(){if(form.elements[n].value)tarihsiz.checked=false;});});}
    form.addEventListener('submit',function(){cleanEmpty();});
    window.addEventListener('pageshow',function(){busy=false;form.classList.remove('gonderiliyor');form.removeAttribute('aria-busy');Array.prototype.forEach.call(form.querySelectorAll('input,select'),function(el){el.disabled=false;});});
    var boy=document.getElementById('sayfa-boyu');if(boy)boy.addEventListener('change',function(){window.location.href=boy.value;});
  }
  function yaziRengi(hex){try{var h=(hex||'#64748b').replace('#','');if(h.length===3)h=h.replace(/(.)/g,'$1$1');var n=.299*parseInt(h.slice(0,2),16)+.587*parseInt(h.slice(2,4),16)+.114*parseInt(h.slice(4,6),16);return n>150?'#111827':'#fff';}catch(_){return'#fff';}}
  function kopyala(value){if(navigator.clipboard){navigator.clipboard.writeText(value).then(function(){toast('Kopyalandı');}).catch(function(){toast('Kopyalanamadı',true);});}else{var i=document.createElement('input');i.value=value;document.body.appendChild(i);i.select();document.execCommand('copy');i.remove();toast('Kopyalandı');}}
  function profilFiltresi(){var sel=document.getElementById('profil-proje');if(!sel)return;sel.addEventListener('change',function(){var selected=sel.options[sel.selectedIndex];if(selected&&selected.disabled){sel.value='';toast('Ana proje dışı filtresinde beklenen ana proje seçilemez.');}});}
  function bildirimSayfasi(){var all=document.getElementById('bildirimler-tum-okundu');function mark(key,el){postBildirim({ids:[key]},{id:key}).then(function(){var row=el.closest('.bildirim-satir');if(row){row.classList.remove('okunmamis');var b=row.querySelector('[data-bildirim-okundu]');if(b)b.remove();}toast('Okundu işaretlendi.');}).catch(function(e){toast(e.message,true);});}document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-bildirim-okundu]');if(b){e.preventDefault();mark(b.getAttribute('data-bildirim-okundu'),b);}var a=e.target.closest&&e.target.closest('[data-bildirim-link]');if(a){e.preventDefault();git(a.href,a.getAttribute('data-bildirim-key'));return;}
    /* 2.3.1: satırın boş alanına tıklamak da (düğme/bağlantı dışı) okundu işaretleyip hedefe gider. */
    if(e.target.closest&&e.target.closest('a,button,input,select,textarea,label'))return;var satir=e.target.closest&&e.target.closest('.bildirim-satir[data-bildirim-hedef]');if(satir)git(satir.getAttribute('data-bildirim-hedef'),satir.getAttribute('data-bildirim-key'));});
    function git(target,key){if(!target)return;postBildirim({ids:[key]},{id:key}).then(function(){window.location.href=target;}).catch(function(){window.location.href=target;});}
    document.addEventListener('keydown',function(e){if(e.key!=='Enter'&&e.key!==' ')return;var t=e.target;if(!t||!t.classList||!t.classList.contains('bildirim-satir')||!t.getAttribute('data-bildirim-hedef'))return;e.preventDefault();git(t.getAttribute('data-bildirim-hedef'),t.getAttribute('data-bildirim-key'));});if(all)all.addEventListener('click',function(){all.disabled=true;postBildirim({hepsi:true},{hepsi:'1'}).then(function(){Array.prototype.forEach.call(document.querySelectorAll('.bildirim-satir.okunmamis'),function(row){row.classList.remove('okunmamis');var b=row.querySelector('[data-bildirim-okundu]');if(b)b.remove();});toast('Bildirimler okundu işaretlendi.');}).catch(function(e){toast(e.message,true);}).then(function(){all.disabled=false;});});}
  /* ===== 2.3.3: bildirim pop-up kartları, ses ve hatırlatma penceresi (başlangıç) =====
     Yeni bildirim sağ üstte kart olarak çıkar (zilin altında) ve kısa bir ses çalar; hatırlatmalar ayrıca ortada pencere açar.
     Ses Web Audio ile üretilir (dosya yok); tarayıcı kuralı gereği sayfaya bir kez tıklanmadan/tuşa basılmadan çalmaz. */
  var SES_ANAHTAR='kanit-bildirim-ses';
  function sesAcik(){try{return localStorage.getItem(SES_ANAHTAR)!=='0';}catch(_){return true;}}
  function sesAyarla(acik){try{localStorage.setItem(SES_ANAHTAR,acik?'1':'0');}catch(_){}}
  var sesBaglam=null;
  /* 2.3.3: AudioContext ilk kullanıcı hareketinde (tıklama/tuş/dokunma) bir kez kurulur ve resume() edilir. */
  function sesHazirla(){try{if(!sesBaglam){var AC=window.AudioContext||window.webkitAudioContext;if(!AC)return;sesBaglam=new AC();}if(sesBaglam.state!=='running'&&sesBaglam.resume){var p=sesBaglam.resume();if(p&&p.catch)p.catch(function(){});}}catch(_){sesBaglam=null;}}
  var ILK_HAREKET=['pointerdown','keydown','touchstart'];
  function ilkHareket(){ILK_HAREKET.forEach(function(ad){document.removeEventListener(ad,ilkHareket,true);});sesHazirla();}
  ILK_HAREKET.forEach(function(ad){document.addEventListener(ad,ilkHareket,{capture:true,passive:true});});
  /* 2.3.3: normal bildirim iki tonlu (~0,3 sn), hatırlatma üç tonlu yumuşak zil; ses kapalıysa ya da bağlam çalışmıyorsa sessizce atlanır. */
  function sesCal(hatirlatma){
    if(!sesAcik())return false;
    try{
      var c=sesBaglam;if(!c||c.state!=='running')return false;
      var notalar=hatirlatma?[[659.25,0,.2],[783.99,.15,.2],[1046.5,.3,.28]]:[[880,0,.14],[1318.5,.12,.18]];
      var t0=c.currentTime+.02;
      notalar.forEach(function(n){var o=c.createOscillator(),g=c.createGain(),s=t0+n[1],d=n[2];o.type='sine';o.frequency.setValueAtTime(n[0],s);g.gain.setValueAtTime(.0001,s);g.gain.exponentialRampToValueAtTime(.12,s+.015);g.gain.exponentialRampToValueAtTime(.0001,s+d);o.connect(g);g.connect(c.destination);o.start(s);o.stop(s+d+.03);});
      return true;
    }catch(_){return false;}
  }
  function hatirlatmaMi(n){return !!n&&n.tur==='hatirlatma';}
  function bildirimAnahtari(n){return n.key||n.bildirim_id||'';}
  /* 2.3.3: bugünün bildiriminde yalnız saat (10:14), eski günlerde tarih + saat. */
  function kisaZaman(z){z=String(z||'');if(z.length<16)return z;return z.slice(0,10)===bugunTarih()?z.slice(11,16):z.slice(0,16);}
  function bugunTarih(){var d=new Date();return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2);}
  /* 2.3.3: kullanıcı bir alana yazıyorsa (metin/arama/sayı/tarih, textarea, select, düzenlenebilir alan) odak çalınmaz. */
  function yaziyor(t){if(!t)return false;if(t.isContentEditable)return true;var n=(t.tagName||'').toLowerCase();if(n==='textarea'||n==='select')return true;if(n!=='input')return false;return !/^(checkbox|radio|button|submit|reset|range|file|color|image|hidden)$/i.test(t.type||'');}
  function acikPencereVar(){var m=document.getElementById('modal'),l=document.getElementById('lightbox');return !!((m&&!m.classList.contains('gizli'))||(l&&!l.classList.contains('gizli')));}

  function bildirimPopup(api){
    var kutu=document.getElementById('bildirim-popuplar'),hp=document.getElementById('hatirlatma-popup');
    var EN_COK=4,SURE=15000,sonListe=[],bekleyenKartlar=[],hpBekliyor=null,hpOnceki=null,izinGosterildi=false;
    var ertKey='kanit-hatirlatma-sonra:'+(window.PANEL_KULLANICI||''),gosKey='kp.hpGosterildi.'+(window.PANEL_KULLANICI||'');
    var TUR=api.turAdlari;
    function renk(n){return (window.PROJE_RENKLERI||{})[n.proje]||'#64748b';}
    function rozet(n){var c=renk(n);return '<span class="rozet" style="background:'+esc(c)+';color:'+yaziRengi(c)+'">'+esc(n.proje||'—')+'</span>';}
    function hedef(n){return n.url||api.recordURL(n);}
    function kayitSatiri(n){if(n.ozet)return '';var kid=n.kayit_id||n.id,p=[];if(kid)p.push('#'+esc(kid));if(n.personel)p.push(esc(n.personel));if(n.kategori)p.push(esc(n.kategori));return p.length?'<div class="bp-kayit"><b>'+p.join(' · ')+'</b></div>':'';}

    /* ---- kartlar: en çok 4; normal kart 15 sn sonra kapanır (üzerindeyken/odaktayken durur), hatırlatma kartı kendiliğinden kapanmaz ---- */
    function kartlar(){return kutu?Array.prototype.slice.call(kutu.querySelectorAll('.bp-kart')):[];}
    function kartKaldir(k){if(!k||!k.parentNode||k._gidiyor)return;k._gidiyor=true;clearTimeout(k._zaman);var odakta=k.contains(document.activeElement);k.classList.add('cikiyor');setTimeout(function(){if(k.parentNode)k.parentNode.removeChild(k);},180);if(odakta){var z=document.getElementById('zil');if(z)z.focus();}}
    function zamanla(k){clearTimeout(k._zaman);if(k._kalici)return;k._bas=Date.now();k._zaman=setTimeout(function(){kartKaldir(k);},k._kalan);}
    function durdur(k){if(k._kalici||!k._bas)return;clearTimeout(k._zaman);k._kalan=Math.max(2000,k._kalan-(Date.now()-k._bas));k._bas=0;}
    function kartEkle(html,sinif,etiket,kalici,anahtar){
      if(!kutu)return null;
      var k=document.createElement('div');k.className='bp-kart'+(sinif?' '+sinif:'');k.setAttribute('role','group');k.setAttribute('aria-label',etiket);k.tabIndex=-1;if(typeof anahtar==='string'&&anahtar)k.setAttribute('data-bp-key',anahtar);else if(anahtar&&anahtar.length)k.setAttribute('data-bp-keys',anahtar.join(' '));
      k.innerHTML=html;k._kalici=!!kalici;k._kalan=SURE;
      kutu.insertBefore(k,kutu.firstChild);
      var hepsi=kartlar().filter(function(x){return !x._gidiyor;});
      while(hepsi.length>EN_COK){var eski=hepsi.filter(function(x){return !x._kalici&&x!==k;}).pop()||hepsi[hepsi.length-1];clearTimeout(eski._zaman);if(eski.parentNode)eski.parentNode.removeChild(eski);hepsi=kartlar().filter(function(x){return !x._gidiyor;});}
      k.addEventListener('mouseenter',function(){durdur(k);});k.addEventListener('mouseleave',function(){if(!k.contains(document.activeElement))zamanla(k);});
      k.addEventListener('focusin',function(){durdur(k);});k.addEventListener('focusout',function(e){if(!k.contains(e.relatedTarget)&&!k.matches(':hover'))zamanla(k);});
      zamanla(k);return k;
    }
    function tekKart(n){
      var id=bildirimAnahtari(n),hat=hatirlatmaMi(n),etiket=TUR[n.tur]||n.etiket||'Yeni bildirim',kim=(n.kim&&n.kim!=='sistem')?' · '+esc(n.kim):'';
      var html='<div class="bp-ust">'+rozet(n)+'<b class="bp-tur">'+esc(etiket)+kim+'</b><small class="bp-zaman" title="'+esc(n.zaman||n.tarih||'')+'">'+esc(kisaZaman(n.zaman||n.tarih))+'</small><button type="button" class="bp-kapat" data-bp-kapat aria-label="Bildirimi kapat">×</button></div>'+
        kayitSatiri(n)+'<p class="bp-metin">'+esc(n.metin||'Kayıt hareketi')+'</p>'+
        '<div class="bp-eylem"><a class="btn kucuk birincil" href="'+esc(hedef(n))+'" data-bp-ac="'+esc(id)+'">Aç</a><button type="button" class="btn kucuk hayalet" data-bp-okundu="'+esc(id)+'">Okundu</button></div>';
      kartEkle(html,hat?'hatirlatma':'',(hat?'Hatırlatma':'Yeni bildirim')+': '+etiket+((n.kayit_id&&!n.ozet)?' · Kayıt #'+n.kayit_id:''),hat,id);
    }
    function ozetKart(liste){
      var hat=liste.filter(hatirlatmaMi).length,metin=liste.length+' yeni bildirim'+(hat?' ('+hat+' hatırlatma)':'');
      var izin=!izinGosterildi&&window.Notification&&Notification.permission==='default';if(izin)izinGosterildi=true;
      var html='<div class="bp-ust"><b class="bp-tur">'+esc(metin)+'</b><button type="button" class="bp-kapat" data-bp-kapat aria-label="Bildirimi kapat">×</button></div>'+
        '<p class="bp-metin">'+esc(liste.slice(0,3).map(function(n){return (n.proje||'')+' · '+(TUR[n.tur]||n.etiket||'Bildirim');}).join(', '))+(liste.length>3?' …':'')+'</p>'+
        '<div class="bp-eylem"><button type="button" class="btn kucuk birincil" data-bp-kutu>Bildirimleri aç</button><a class="btn kucuk ikincil" href="/bildirimler?okundu=0">Tümünü gör</a>'+(izin?'<button type="button" class="btn kucuk hayalet" data-bp-izin>Masaüstü bildirimlerini aç</button>':'')+'</div>';
      /* Özet kart kapsadığı anahtarları taşır; hepsi okununca (pencereden/zilden/başka sekmeden) kendiliğinden kalkar. */
      kartEkle(html,'ozet'+(hat?' hatirlatma':''),metin,hat>0,liste.map(bildirimAnahtari).filter(Boolean));
    }
    /* 1-2 yeni satır tek tek, 3 ve üzeri tek özet kart (hatırlatma partileri 20 ayrı kart üretmesin). */
    function kartGoster(liste){if(!liste.length)return;if(liste.length>=3)ozetKart(liste);else liste.forEach(tekKart);}
    if(kutu){
      kutu.addEventListener('click',function(e){
        var t=e.target,k=t.closest&&t.closest('.bp-kart');if(!k)return;
        var a=t.closest('[data-bp-ac]');if(a){e.preventDefault();kartKaldir(k);api.markRead(a.getAttribute('data-bp-ac'),a.href);return;}
        var o=t.closest('[data-bp-okundu]');if(o){e.preventDefault();o.disabled=true;kartKaldir(k);api.markRead(o.getAttribute('data-bp-okundu'),null);return;}
        if(t.closest('[data-bp-kapat]')){kartKaldir(k);return;}
        if(t.closest('[data-bp-kutu]')){kartKaldir(k);api.openBox(true);return;}
        var iz=t.closest('[data-bp-izin]');if(iz){iz.disabled=true;api.izinIste();}
      });
      kutu.addEventListener('keydown',function(e){if(e.key!=='Escape')return;var k=e.target.closest&&e.target.closest('.bp-kart');if(k){e.preventDefault();e.stopPropagation();kartKaldir(k);}});
    }
    /* Artık okunmamış listede olmayan bildirimlerin kartları (zilden/başka sekmeden okundu) kendiliğinden kalkar. */
    function kartAnahtarlari(k){var a=k.getAttribute('data-bp-key');if(a)return [a];return (k.getAttribute('data-bp-keys')||'').split(' ').filter(Boolean);}
    function kartTemizle(items){var var_={};items.forEach(function(n){if(!n.okundu)var_[bildirimAnahtari(n)]=1;});kartlar().forEach(function(k){var a=kartAnahtarlari(k);if(a.length&&!a.some(function(x){return var_[x];}))kartKaldir(k);});}

    /* ---- hatırlatma penceresi ---- */
    var hpListe=hp&&hp.querySelector('#hp-liste'),hpPencere=hp&&hp.querySelector('.hp-pencere');
    function hpAcik(){return !!hp&&!hp.classList.contains('gizli');}
    function hatirlatmalar(){return sonListe.filter(function(n){return hatirlatmaMi(n)&&!n.okundu;});}
    function gunlukOku(k){try{var d=JSON.parse(localStorage.getItem(k)||'null');return d&&d.gun===bugunTarih()?d:null;}catch(_){return null;}}
    /* 2.3.4: "Daha sonra" = bugün pencere bir daha kendiliğinden açılmaz (yeni hatırlatmalar kart, ses ve zil olarak gelir). */
    function ertelenmis(){return !!gunlukOku(ertKey);}
    /* 2.3.4: pencere her hatırlatma için günde en çok bir kez kendiliğinden açılır. Gösterilen anahtarlar kullanıcı ve gün
       başına localStorage'da tutulur; Kapat/Esc/Aç/okundu sonrası başka sayfaya geçince pencere yeniden açılmaz. Ertesi gün sıfırlanır. */
    function gosterilenler(){var d=gunlukOku(gosKey),b={};((d&&d.anahtarlar)||[]).forEach(function(x){b[x]=1;});return b;}
    function yeniHatirlatmaVar(){var b=gosterilenler();return hatirlatmalar().some(function(n){return !b[bildirimAnahtari(n)];});}
    function gosterildiIsaretle(liste){var b=gosterilenler(),a=Object.keys(b);liste.forEach(function(n){var k=bildirimAnahtari(n);if(k&&!b[k]){b[k]=1;a.push(k);}});try{localStorage.setItem(gosKey,JSON.stringify({gun:bugunTarih(),anahtarlar:a.slice(-500)}));}catch(_){}}
    /* 2.3.4: zil listesinin başlığındaki "Hatırlatmalar (N)" düğmesi pencereyi her zaman elle açar. */
    var hpDugme=document.getElementById('bildirim-hp-ac');
    function hpDugmeGuncelle(){if(!hpDugme)return;var n=hatirlatmalar().length;hpDugme.classList.toggle('gizli',!n||!hp);hpDugme.textContent='Hatırlatmalar ('+n+')';}
    var hpImza=null;
    function hpCiz(){
      var liste=hatirlatmalar(),imza=liste.map(bildirimAnahtari).join(',');
      /* Liste değişmediyse yeniden çizilmez (odaktaki düğme kaybolmasın); değiştiyse odak aynı satıra geri konur. */
      if(imza===hpImza&&hpListe.firstChild)return liste;hpImza=imza;
      var odak=document.activeElement,odakKey=odak&&hpListe.contains(odak)?odak.getAttribute('data-hp-ac'):null;
      hpListe.innerHTML=liste.map(function(n){var id=bildirimAnahtari(n),kid=n.kayit_id||n.id,bas=n.ozet?(String(n.olay||'').indexOf('gun-sonu:')===0?'Gün sonu özeti':esc(n.proje||'')+' · Proje özeti'):'Kayıt #'+esc(kid)+(n.personel?' · '+esc(n.personel):'');
        return '<li class="'+(n.ozet?'ozet':'')+'">'+rozet(n)+'<span class="hp-metin"><b>'+bas+'</b> <span>'+esc(n.metin||'')+'</span></span><a class="btn kucuk ikincil" href="'+esc(hedef(n))+'" data-hp-ac="'+esc(id)+'">'+(n.ozet?'Bekleyenleri aç':'Aç')+'</a></li>';}).join('')||'<li class="bos">Bekleyen hatırlatma kalmadı.</li>';
      var s=document.getElementById('hp-sayi');if(s)s.textContent=liste.length?liste.length+' hatırlatma':'';
      if(odakKey!==null){var geri=hpListe.querySelector('[data-hp-ac="'+odakKey+'"]')||hpListe.querySelector('[data-hp-ac]')||hp.querySelector('[data-hp-sonra]');if(geri)geri.focus();}
      return liste;
    }
    function hpKapat(ertele){
      if(!hpAcik())return;
      if(ertele){try{localStorage.setItem(ertKey,JSON.stringify({gun:bugunTarih(),hepsi:true}));}catch(_){}}
      hp.classList.add('gizli');hp.setAttribute('aria-hidden','true');document.body.classList.remove('hatirlatma-acik');
      var geri=hpOnceki;hpOnceki=null;if(geri&&geri.focus&&geri!==document.body&&document.contains(geri))geri.focus();
    }
    /* elle=true: kullanıcı zil başlığındaki düğmeyle açtı; "Daha sonra" ve "gösterildi" kaydı yok sayılır, erteleme yapılmaz. */
    function hpAc(sesli,elle){
      if(!hp)return;
      if(!hatirlatmalar().length){hpBekliyor=null;return;}
      if(!elle&&!hpAcik()&&(ertelenmis()||!yeniHatirlatmaVar())){hpBekliyor=null;return;}
      /* Kayıt penceresi/görsel büyütme açıkken, kullanıcı bir alana yazarken ya da sekme arka plandayken ertelenir
         (ertelenen ve henüz gösterilmeyen pencere "gösterildi" sayılmaz). */
      if(!elle&&(acikPencereVar()||yaziyor(document.activeElement)||document.hidden)){hpBekliyor={sesli:(hpBekliyor&&hpBekliyor.sesli)||!!sesli};return;}
      hpBekliyor=null;var liste=hpCiz();gosterildiIsaretle(liste);
      if(!hpAcik()){hpOnceki=document.activeElement;hp.classList.remove('gizli');hp.setAttribute('aria-hidden','false');document.body.classList.add('hatirlatma-acik');var ilk=hp.querySelector('[data-hp-ac]')||hp.querySelector('button');if(ilk)ilk.focus();}
      if(sesli)sesCal(true);
    }
    function bekleyeniDene(){if(hpBekliyor)hpAc(hpBekliyor.sesli);}
    if(hp){
      hp.addEventListener('click',function(e){
        var t=e.target;if(!t.closest)return;
        var a=t.closest('[data-hp-ac]');if(a){e.preventDefault();hpKapat(false);api.markRead(a.getAttribute('data-hp-ac'),a.href);return;}
        if(t.closest('[data-hp-sonra]')){hpKapat(true);return;}
        if(t.closest('[data-hp-kapat]')){hpKapat(false);return;}
        var o=t.closest('[data-hp-okundu]');if(o){var ids=hatirlatmalar().map(bildirimAnahtari);if(!ids.length){hpKapat(false);return;}o.disabled=true;
          postBildirim({ids:ids},{id:ids[0]}).then(function(){var b={};ids.forEach(function(x){b[x]=1;});sonListe=sonListe.filter(function(n){return !b[bildirimAnahtari(n)];});kartTemizle(sonListe);hpDugmeGuncelle();hpKapat(false);toast(ids.length+' hatırlatma okundu sayıldı.');api.poll(true);}).catch(function(err){toast(err.message,true);}).then(function(){o.disabled=false;});return;}
        if(t===hp)hpKapat(false);
      });
      /* Odak tuzağı: Tab pencere içinde döner, Esc kapatır; tuşlar alttaki sayfa kısayollarına ulaşmaz. */
      hp.addEventListener('keydown',function(e){
        if(e.key==='Escape'){e.preventDefault();e.stopPropagation();hpKapat(false);return;}
        if(e.key==='Tab'){var f=focusables(hpPencere),ilk=f[0],son=f[f.length-1];if(!f.length){e.preventDefault();return;}if(e.shiftKey&&(document.activeElement===ilk||!hpPencere.contains(document.activeElement))){e.preventDefault();son.focus();}else if(!e.shiftKey&&document.activeElement===son){e.preventDefault();ilk.focus();}}
        e.stopPropagation();
      });
      /* Kayıt penceresi ya da görsel büyütme kapanınca bekleyen hatırlatma penceresi açılır. */
      if(hpDugme)hpDugme.addEventListener('click',function(){api.openBox(false);var z=document.getElementById('zil');if(z)z.focus();hpAc(false,true);});
      if(window.MutationObserver)['modal','lightbox'].forEach(function(id){var el=document.getElementById(id);if(el)new MutationObserver(function(){if(hpBekliyor&&!acikPencereVar())setTimeout(bekleyeniDene,150);}).observe(el,{attributes:true,attributeFilter:['class']});});
    }

    /* ---- masaüstü bildirimi (izin verilmişse); tıklanınca sekmeye dönüp bağlantıyı açar ---- */
    function masaustu(baslik,govde,etiket,id,url){
      if(!(window.Notification&&Notification.permission==='granted'))return;
      try{var bn=new Notification(baslik,{body:govde,tag:'kanit-'+(window.PANEL_KULLANICI||'')+'-'+etiket});bn.onclick=function(){try{window.focus();}catch(_){}try{bn.close();}catch(_){}if(id)api.markRead(id,url);else window.location.href=url;};}catch(_){}
    }
    function masaustuBildir(liste){
      if(liste.length>=3){var hat=liste.filter(hatirlatmaMi).length;masaustu('Kanıt Paneli',liste.length+' yeni bildirim'+(hat?' ('+hat+' hatırlatma)':''),'toplu',null,'/bildirimler?okundu=0');return;}
      liste.forEach(function(n){var id=bildirimAnahtari(n),kid=n.kayit_id||n.id,ozet=(kid&&!n.ozet?'#'+kid+' · ':'')+(n.personel&&!n.ozet?n.personel+' · ':'')+(n.metin||n.kim||'');masaustu('Kanıt Paneli · '+(hatirlatmaMi(n)?'Hatırlatma · ':'')+(n.proje||''),ozet||'Yeni bildirim',id,id,hedef(n));});
    }

    /* Her yoklamada çağrılır. yeniler = bu oturumda ilk kez görülen satırlar (sayfanın ilk yoklamasında boş). */
    function yoklama(items,yeniler,ilk){
      sonListe=items.slice();kartTemizle(items);
      if(yeniler.length){
        var hatYeni=yeniler.some(hatirlatmaMi);
        /* Arka plan sekmesinde de ses ve masaüstü bildirimi hemen; kartlar sekme öne gelince. */
        sesCal(hatYeni);masaustuBildir(yeniler);
        if(document.hidden)bekleyenKartlar=bekleyenKartlar.concat(yeniler);else kartGoster(yeniler);
        if(hatYeni)hpAc(false);
      }
      /* Sayfa ilk yüklenişte: yalnız bugün henüz gösterilmemiş bir hatırlatma varsa (ve "Daha sonra" denmediyse) açılır. */
      if(ilk)hpAc(true);
      else if(hpAcik()){var acik=hpCiz();if(!acik.length)hpKapat(false);else gosterildiIsaretle(acik);}
      else bekleyeniDene();
      hpDugmeGuncelle();
    }
    /* Arka planda biriken kartlar sekme öne gelince gösterilir (düşürülmez; bu arada okunanlar atlanır). */
    function gorunur(){if(bekleyenKartlar.length){var b={};sonListe.forEach(function(n){b[bildirimAnahtari(n)]=1;});var liste=bekleyenKartlar.filter(function(n){return b[bildirimAnahtari(n)];});bekleyenKartlar=[];kartGoster(liste);}bekleyeniDene();}
    return {yoklama:yoklama,gorunur:gorunur};
  }
  /* ===== 2.3.3: bildirim pop-up bloğu (son) ===== */
  function bildirimler(){
    var zil=document.getElementById('zil'), box=document.getElementById('bildirim-kutu'), list=document.getElementById('bildirim-liste'), count=document.getElementById('zil-sayi'), boxCount=document.getElementById('bildirim-kutu-sayi');
    if(!zil||!box||!list)return;
    var initial=true,stamp=null,seen={},running=false,timer=null,key='kanit-notify-'+(window.PANEL_KULLANICI||''),last=null;
    try{seen=JSON.parse(sessionStorage.getItem(key)||'{}');}catch(_){}
    var permission=document.getElementById('bildirim-izin'), permissionBtn=document.getElementById('bildirim-izin-btn'), clean=document.getElementById('bildirim-temizle');
    if(window.Notification&&Notification.permission==='default'&&permission)permission.classList.remove('gizli');
    /* 2.3.3: izin düğmesi izin 'default' kaldıkça (pencere kapatıldıysa) görünür kalır. */
    function izinIste(){if(!window.Notification||!Notification.requestPermission)return;try{var p=Notification.requestPermission(function(){});if(p&&p.then)p.then(izinGuncelle,izinGuncelle);}catch(_){}}
    function izinGuncelle(){if(permission)permission.classList.toggle('gizli',!(window.Notification&&Notification.permission==='default'));}
    if(permissionBtn)permissionBtn.addEventListener('click',izinIste);
    /* 2.3.3: "Ses" anahtarı (tarayıcı başına, varsayılan açık); açılınca kısa bir örnek ses çalar. */
    var sesKutu=document.getElementById('bildirim-ses');
    if(sesKutu){sesKutu.checked=sesAcik();sesKutu.addEventListener('change',function(){sesAyarla(sesKutu.checked);if(sesKutu.checked){sesHazirla();setTimeout(function(){sesCal(false);},60);}toast(sesKutu.checked?'Bildirim sesi açıldı.':'Bildirim sesi kapatıldı.');});}
    function openBox(open){box.classList.toggle('gizli',!open);zil.setAttribute('aria-expanded',String(open));if(open){poll(true);var ilk=list.querySelector('li[tabindex]')||box.querySelector('a,button');if(ilk)setTimeout(function(){if(!box.classList.contains('gizli'))ilk.focus();},0);}}
    zil.addEventListener('click',function(){openBox(box.classList.contains('gizli'));});
    document.addEventListener('click',function(e){if(box.classList.contains('gizli'))return;if(box.contains(e.target)||zil.contains(e.target))return;/* 2.3.3: özet karttaki "Bildirimleri aç" listeyi hemen geri kapatmasın. */if(e.target.closest&&e.target.closest('#bildirim-popuplar'))return;openBox(false);});
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!box.classList.contains('gizli')){openBox(false);zil.focus();}});
    if(clean)clean.addEventListener('click',function(){clean.disabled=true;postBildirim({hepsi:true},{hepsi:'1'}).then(function(){last=null;render({bildirimler:[],okunmamis:0,sayac:null,degisiklik:stamp});toast('Tüm bildirimler okundu sayıldı.');openBox(false);}).catch(function(e){toast(e.message,true);}).then(function(){clean.disabled=false;});});
    var TUR_ADLARI={soru:'Soru',yanit:'Yanıt',yorum:'Yorum',onay:'Onay',onay_kaldir:'Onay kaldırıldı',kanit:'Yeni kanıt',hatirlatma:'Hatırlatma'};
    function recordURL(k){var id=k.kayit_id||k.id;return '/kayitlar?proje='+encodeURIComponent(k.proje||'')+'&durum=hepsi&ac='+encodeURIComponent(id||'');}
    function markRead(id,target){postBildirim({ids:[id]},{id:id}).then(function(){if(target)window.location.href=target;else poll(true);}).catch(function(e){if(target)window.location.href=target;else toast(e.message,true);});}
    function render(data){
      var unread=data.okunmamis||0;count.textContent=unread>99?'99+':unread;count.classList.toggle('gizli',!unread);zil.setAttribute('aria-label',unread?unread+' okunmamış bildirim':'Bildirimleri aç');if(boxCount)boxCount.textContent=unread?'· '+unread+' okunmamış':'';
      var items=data.bildirimler||[];var sig=JSON.stringify(items.map(function(n){return n.key||n.bildirim_id;}))+':'+unread;
      var LIMIT=15, shown=items.slice(0,LIMIT), kalan=Math.max(items.length,unread)-shown.length;
      if(sig!==last){last=sig;list.innerHTML=shown.map(function(n){var id=n.key||n.bildirim_id||'', label=TUR_ADLARI[n.tur]||n.etiket||'Yeni kayıt', color=(window.PROJE_RENKLERI||{})[n.proje]||'#64748b', kid=n.kayit_id||n.id, hedef=n.url||recordURL(n), kayit=n.ozet?'':(kid?'#'+esc(kid):'')+(n.personel?(kid?' · ':'')+esc(n.personel):''), kim=(n.kim&&n.kim!=='sistem')?' · '+esc(n.kim):'';return '<li class="tiklanir '+(n.okundu?'':'okunmamis')+(n.tur==='hatirlatma'?' hatirlatma':'')+'" data-notify-hedef="'+esc(hedef)+'" data-notify-id="'+esc(id)+'" tabindex="0" role="link" aria-label="'+esc(label)+(kid&&!n.ozet?' · Kayıt #'+esc(kid):'')+' — aç"><span class="rozet" style="background:'+esc(color)+';color:'+yaziRengi(color)+'">'+esc(n.proje||'—')+'</span> <b>'+esc(label)+kim+'</b>'+(kayit?'<span class="bildirim-kayit"><b>'+kayit+'</b>'+(n.kategori?' <small>'+esc(n.kategori)+'</small>':'')+'</span>':'')+'<p>'+esc(n.metin||'Kayıt hareketi')+'</p><div class="bildirim-eylem"><small>'+esc(n.zaman||n.tarih||'')+'</small><span><a class="btn kucuk ikincil" href="'+esc(hedef)+'" data-notify="'+esc(id)+'">'+(n.ozet?'Bekleyenleri aç':(n.yorum_id?'Yorumu aç':'Kaydı aç'))+'</a> <button type="button" class="btn kucuk hayalet" data-notify-okundu="'+esc(id)+'" aria-label="Okundu işaretle">Okundu</button></span></div></li>';}).join('')||'<li class="bos">Okunmamış bildirim yok.</li>';if(kalan>0)list.innerHTML+='<li class="tumu"><a class="btn kucuk hayalet" href="/bildirimler?okundu=0">'+kalan+' bildirim daha · Tümünü gör</a></li>';}
      /* 2.3.3: yeni satırlar artık alttaki tost yerine sağ üstte pop-up kart + ses (+ izin varsa masaüstü bildirimi) olarak gösterilir. */
      var yeniler=items.filter(function(n){var id=n.key||n.bildirim_id;if(seen[id])return false;seen[id]=true;return !initial;});
      if(yeniler.length)setChangeStrip(true);
      if(popup)popup.yoklama(items,yeniler,initial);
      try{sessionStorage.setItem(key,JSON.stringify(seen));}catch(_){}
      if(data.degisiklik&&stamp&&stamp!==data.degisiklik)document.dispatchEvent(new CustomEvent('kp:degisti',{detail:data}));
      if(data.degisiklik)stamp=data.degisiklik;initial=false;
      Array.prototype.forEach.call(document.querySelectorAll('[data-sayac]'),function(el){var p=el.getAttribute('data-sayac').split(':'),v=data.sayac&&data.sayac[p[0]]&&data.sayac[p[0]][p[1]];if(v!==undefined&&String(v)!==el.textContent){el.textContent=v;el.classList.add('sayac-degisti');setTimeout(function(){el.classList.remove('sayac-degisti');},1500);}});
    }
    list.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('[data-notify]');if(a){e.preventDefault();markRead(a.getAttribute('data-notify'),a.href);return;}var b=e.target.closest&&e.target.closest('[data-notify-okundu]');if(b){e.preventDefault();b.disabled=true;markRead(b.getAttribute('data-notify-okundu'),null);return;}
      /* 2.3.1: bildirimin kendisine (düğme dışı alan) tıklamak da okundu işaretleyip hedefe gider; telefonda geniş dokunma alanı. */
      if(e.target.closest&&e.target.closest('a,button'))return;var li=e.target.closest&&e.target.closest('li[data-notify-hedef]');if(li){e.preventDefault();markRead(li.getAttribute('data-notify-id'),li.getAttribute('data-notify-hedef'));}});
    list.addEventListener('keydown',function(e){if(e.key!=='Enter'&&e.key!==' ')return;var li=e.target;if(!li||!li.getAttribute||!li.getAttribute('data-notify-hedef'))return;e.preventDefault();markRead(li.getAttribute('data-notify-id'),li.getAttribute('data-notify-hedef'));});
    /* 2.3.3: arka plan sekmesi de yoklanır (10 sn yerine 30 sn); window.KP_YOKLAMA_MS testler için aralığı değiştirir. */
    var ARALIK=(+window.KP_YOKLAMA_MS>0)?+window.KP_YOKLAMA_MS:10000;
    function schedule(){clearTimeout(timer);timer=setTimeout(poll,document.hidden?ARALIK*3:ARALIK);}
    function poll(force){if(running)return;running=true;fetch('/bildirim.json',{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}}).then(function(r){if(r.status===401){return r.json().catch(function(){return {};}).then(function(d){oturumDustu(d&&d.hata,d&&d.giris);return null;});}return r.ok?r.json():null;}).then(function(d){if(d)render(d);}).catch(function(){}).then(function(){running=false;schedule();});}
    var popup=bildirimPopup({turAdlari:TUR_ADLARI,recordURL:recordURL,markRead:markRead,openBox:openBox,poll:poll,izinIste:izinIste});
    document.addEventListener('visibilitychange',function(){if(!document.hidden){clearTimeout(timer);if(popup)popup.gorunur();poll();}});poll();
  }
  function menu(){
    var header=document.getElementById('ust-menu');if(!header)return;
    var burger=header.querySelector('[data-menu-dugme]'), nav=document.getElementById('ana-menu'), aktifAcilirlar=[];
    function telefon(){return window.matchMedia('(max-width:900px)').matches;}
    if(burger&&nav){burger.addEventListener('click',function(){var open=!header.classList.contains('menu-acik');header.classList.toggle('menu-acik',open);burger.setAttribute('aria-expanded',String(open));burger.setAttribute('aria-label',open?'Menüyü kapat':'Menüyü aç');
      /* Yönetim sayfasındayken menü açılınca alt menü açık ve aktif sayfa vurgulu gelsin. */
      if(open&&telefon())aktifAcilirlar.forEach(function(ac){ac(true);});});}
    Array.prototype.forEach.call(header.querySelectorAll('[data-acilir]'),function(btn){
      var panel=document.getElementById(btn.getAttribute('data-acilir'));if(!panel)return;
      function set(open){panel.hidden=!open;btn.setAttribute('aria-expanded',String(open));}
      btn.addEventListener('click',function(e){e.preventDefault();set(panel.hidden);if(!panel.hidden){var first=panel.querySelector('a');if(first&&window.matchMedia('(min-width:901px)').matches)first.focus();}});
      /* Hamburger dokunuşu "dışarı tıklama" sayılmaz; alt menü yalnız gerçekten dışına tıklanınca kapanır. */
      document.addEventListener('click',function(e){if(panel.hidden)return;if(btn.contains(e.target)||panel.contains(e.target))return;if(burger&&(e.target===burger||burger.contains(e.target)))return;set(false);});
      document.addEventListener('keydown',function(e){if(e.key==='Escape'&&!panel.hidden){set(false);btn.focus();}});
      if(btn.classList.contains('aktif')){aktifAcilirlar.push(set);if(telefon())set(true);}
    });
    document.addEventListener('keydown',function(e){if(e.key==='Escape'&&header.classList.contains('menu-acik')&&burger){header.classList.remove('menu-acik');burger.setAttribute('aria-expanded','false');}});
  }
  function botSayfasi(){var table=document.getElementById('islemler-tablo');if(!table)return;var last=null,running=false,timer=null;function next(){clearTimeout(timer);timer=setTimeout(update,10000);}function update(){if(document.hidden||running){next();return;}running=true;fetch('/bot/islemler.json',{credentials:'same-origin'}).then(function(r){return r.ok?r.json():null;}).then(function(d){if(!d)return;var sig=JSON.stringify((d.islemler||[]).map(function(x){return[x.id,x.durum];}));if(sig===last)return;last=sig;var tb=table.querySelector('tbody');tb.innerHTML=(d.islemler||[]).map(function(i){return '<tr><td>'+esc(i.zaman)+'</td><td>'+esc(i.ozet)+'</td><td>'+esc(i.kullanici)+'</td><td>'+esc(i.durum)+'</td><td>'+esc(i.mesaj||'')+'</td></tr>';}).join('')||'<tr><td colspan="5">Henüz işlem yok.</td></tr>';}).catch(function(){}).then(function(){running=false;next();});}document.addEventListener('visibilitychange',function(){if(!document.hidden)update();});next();}
  /* Tarayıcının İngilizce "Please match the requested format" uyarısı yerine alanın data-gecersiz / data-bos metni. */
  document.addEventListener('invalid',function(e){var t=e.target;if(!t||!t.getAttribute||!t.setCustomValidity)return;var desen=t.getAttribute('data-gecersiz'),bos=t.getAttribute('data-bos');if(!desen&&!bos)return;var v=t.validity;if(v.valueMissing)t.setCustomValidity(bos||(t.type==='checkbox'?(desen||'Devam etmek için bu kutuyu işaretleyin.'):'Bu alan zorunludur.'));else if(v.patternMismatch||v.tooShort||v.tooLong||v.typeMismatch||v.rangeUnderflow||v.rangeOverflow||v.stepMismatch)t.setCustomValidity(desen||'Girilen değer beklenen biçimde değil.');},true);
  document.addEventListener('input',function(e){var t=e.target;if(t&&t.setCustomValidity&&t.getAttribute&&(t.getAttribute('data-gecersiz')||t.getAttribute('data-bos')))t.setCustomValidity('');},true);
  document.addEventListener('change',function(e){var t=e.target;if(t&&t.setCustomValidity&&t.getAttribute&&(t.getAttribute('data-gecersiz')||t.getAttribute('data-bos')))t.setCustomValidity('');},true);
  document.addEventListener('submit',function(e){var f=e.target;if(f&&f.getAttribute&&f.getAttribute('data-onay')&&!confirm(f.getAttribute('data-onay')))e.preventDefault();});document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-kopyala]');if(b){e.preventDefault();kopyala(b.getAttribute('data-kopyala'));return;}var t=e.target.closest&&e.target.closest('[data-ac]');if(t){var target=document.getElementById(t.getAttribute('data-ac'));if(target){e.preventDefault();var open=target.hidden;target.hidden=!open;Array.prototype.forEach.call(document.querySelectorAll('[data-ac="'+t.getAttribute('data-ac')+'"][aria-controls]'),function(x){x.setAttribute('aria-expanded',String(open));});if(open){var f=target.querySelector('input:not([type=hidden]),select,textarea,button');if(f)f.focus();}}return;}var g=e.target.closest&&e.target.closest('[data-geri]');if(g){if(window.history.length>1&&document.referrer&&document.referrer.indexOf(window.location.origin)===0){e.preventDefault();window.history.back();}}});
  return {kayitSayfasi:kayitSayfasi,bildirimler:bildirimler,menu:menu,bildirimSayfasi:bildirimSayfasi,botsayfasi:botSayfasi,botSayfasi:botSayfasi,profilFiltresi:profilFiltresi,toast:toast,kopyala:kopyala};
})();

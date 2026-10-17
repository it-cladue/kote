/* Kanıt Paneli 2.1: bağımsız, erişilebilir panel davranışları. */
window.Panel = (function () {
  'use strict';
  var csrf = (document.querySelector('meta[name=csrf]') || {}).content || '';
  var toastTimer = null;
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  function toast(message, error) { var t=document.getElementById('toast'); if(!t)return; t.textContent=message; t.className='toast'+(error?' hata':''); clearTimeout(toastTimer); toastTimer=setTimeout(function(){t.className='toast gizli';},error?6000:3200); }
  function post(url, data) { var fd=new URLSearchParams(); Object.keys(data||{}).forEach(function(k){ if(Array.isArray(data[k]))data[k].forEach(function(v){fd.append(k,v);}); else fd.append(k,data[k]); }); return fetch(url,{method:'POST',credentials:'same-origin',body:fd,headers:{'X-CSRF':csrf}}).then(parseResponse); }
  function parseResponse(r) { if(r.status===403)throw new Error('Bu işlem için yetkiniz yok.'); return r.json().catch(function(){return {};}).then(function(d){if(!r.ok)throw new Error(d.hata||'İşlem yapılamadı ('+r.status+')'); return d;}); }
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
  function topluKur(applied){
    var arac=document.getElementById('toplu-arac');
    if(!arac)return {update:function(){},selected:function(){return [];}};
    function boxes(){return Array.prototype.slice.call(document.querySelectorAll('#kayit-sonuclari .kayit-sec'));}
    function selected(){return boxes().filter(function(b){return b.checked&&!b.disabled;}).map(function(b){return +b.value;});}
    function update(){var n=selected().length;arac.classList.toggle('gizli',!n);var s=document.getElementById('toplu-sayi');if(s)s.textContent=n+' seçili';Array.prototype.forEach.call(arac.querySelectorAll('[data-toplu-sayi]'),function(x){x.textContent=n;});boxes().forEach(function(b){var row=b.closest('.kayit');if(row)row.classList.toggle('secili',b.checked&&!b.disabled);});var all=document.getElementById('sec-hepsi');if(all){var en=boxes().filter(function(b){return !b.disabled;});all.checked=en.length>0&&en.every(function(b){return b.checked;});all.indeterminate=n>0&&!all.checked;}}
    var last=null;
    document.addEventListener('change',function(e){var t=e.target;if(!t)return;if(t.id==='sec-hepsi'){boxes().forEach(function(b){if(!b.disabled)b.checked=t.checked;});update();}else if(t.classList&&t.classList.contains('kayit-sec')){update();}});
    document.addEventListener('click',function(e){var t=e.target;if(!t.classList||!t.classList.contains('kayit-sec'))return;var all=boxes();if(e.shiftKey&&last&&all.indexOf(last)>=0){var a=all.indexOf(last),b=all.indexOf(t);all.slice(Math.min(a,b),Math.max(a,b)+1).forEach(function(x){if(!x.disabled)x.checked=t.checked;});update();}last=t;});
    arac.addEventListener('click',function(e){var b=e.target.closest('[data-toplu]');if(b){run(b.getAttribute('data-toplu'));return;}if(e.target.closest('[data-toplu-temizle]')){boxes().forEach(function(x){x.checked=false;});update();}});
    function run(deger){var ids=selected();if(!ids.length){toast('Önce en az bir kayıt seçin.',true);return;}if(ids.length>300){toast('Tek seferde en çok 300 kayıt işlenebilir; seçimi daraltın.',true);return;}
      if(!confirm(ids.length+' kayıt '+(deger==='1'?'onaylanacak':'için onay kaldırılacak')+'. Devam edilsin mi?'))return;
      var buttons=Array.prototype.slice.call(arac.querySelectorAll('button'));buttons.forEach(function(x){x.disabled=true;});
      kayitPost('/kayitlar/toplu-kt',{ids:ids,deger:deger}).then(function(r){toast(r.mesaj||'Tamamlandı.',!r.degisen);(r.ids||[]).forEach(function(id){applied(id,deger==='1');});boxes().forEach(function(x){x.checked=false;});update();}).catch(function(e){toast(e.message,true);}).then(function(){buttons.forEach(function(x){x.disabled=false;});});}
    return {update:update,selected:selected};
  }

  function kayitSayfasi(durumFiltresi) {
    var sayfa=document.getElementById('kayit-sayfa'),modal=document.getElementById('modal'); if(!modal)return;
    var dialog=modal.querySelector('.modal-icerik'),form=document.getElementById('m-duzenle'),yf=document.getElementById('m-yorum-form'),formHata=document.getElementById('m-duzenle-hata');
    var acikId=null,acikKayit=null,acan=null,refreshRunning=false,openSerial=0,gorseller=[],gorselIdx=0,lightboxBekliyor=false;
    var lb=lightboxKur(document.getElementById('lightbox'));
    var ust=document.querySelector('header.ust');
    function ustYukseklik(){if(sayfa&&ust)sayfa.style.setProperty('--ust-h',ust.offsetHeight+'px');}
    ustYukseklik();window.addEventListener('resize',ustYukseklik);
    function resultRoot(){return document.getElementById('kayit-sonuclari');}
    function recordIds(){return Array.prototype.map.call((resultRoot()||document).querySelectorAll('.kayit[data-id]'),function(e){return +e.getAttribute('data-id');});}
    function cardOf(id){return document.querySelector('#kayit-sonuclari .kayit[data-id="'+id+'"]');}
    var toplu=topluKur(function(id,kt){var card=cardOf(id);if(card){sayacGuncelle(card,'kt',{kt:kt?1:0});applyCard(card,'kt',{kt:kt?1:0});}if(acikId===id)openRecord(id,acan);});

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

    modal.querySelector('.modal-kapat').addEventListener('click',closeRecord);
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
    yf.addEventListener('submit',function(e){e.preventDefault();if(!acikKayit)return;var text=yf.elements.yorum.value.trim();if(!text){toast('Göndermeden önce bir yorum yazın.',true);yf.elements.yorum.focus();return;}var btn=yf.querySelector('button[type=submit]');btn.disabled=true;kayitPost('/kayit/'+acikKayit.id+'/yorum',{yorum:text,alici:yf.elements.alici.value,yanit_id:yf.elements.yanit_id.value}).then(function(d){if(!d.ok)throw new Error(d.hata||'Yorum gönderilemedi');clearDraft(acikKayit.id);yf.reset();toast('Gönderildi; ilgili alıcıya bildirildi.');openRecord(acikKayit.id,acan);}).catch(function(x){toast(x.message,true);}).then(function(){btn.disabled=false;});});
    document.getElementById('m-taslak-sil').addEventListener('click',function(){if(acikId){clearDraft(acikId);yf.reset();resetReply();toast('Taslak silindi.');}});
    function draftKey(id){return 'kanit-yorum-taslak:'+(window.PANEL_KULLANICI||'')+':'+id;}
    function saveDraft(){if(!acikId||yf.classList.contains('gizli'))return;try{sessionStorage.setItem(draftKey(acikId),JSON.stringify({yorum:yf.elements.yorum.value,alici:yf.elements.alici.value,yanit_id:yf.elements.yanit_id.value}));}catch(_){}}
    function clearDraft(id){try{sessionStorage.removeItem(draftKey(id));}catch(_){}}
    function loadDraft(id){var d;try{d=JSON.parse(sessionStorage.getItem(draftKey(id))||'null');}catch(_){d=null;}if(!d)return;yf.elements.yorum.value=d.yorum||'';yf.elements.yanit_id.value=d.yanit_id||'';if(d.alici)yf.elements.alici.value=d.alici;if(d.yanit_id){yf.elements.alici.disabled=true;document.getElementById('m-yanit-ozet').textContent='Yanıt taslağı korunuyor';document.getElementById('m-yanit-vazgec').classList.remove('gizli');}}
    function resetReply(){yf.elements.yanit_id.value='';yf.elements.alici.disabled=false;document.getElementById('m-yanit-ozet').textContent='';document.getElementById('m-yanit-vazgec').classList.add('gizli');saveDraft();}
    document.getElementById('m-yanit-vazgec').addEventListener('click',resetReply);
    document.getElementById('m-yorumlar').addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-yanit]');if(!b||!acikKayit||!acikKayit.izin_yorum)return;var item=(acikKayit.yorumlar||[]).filter(function(x){return String(x.id)===b.getAttribute('data-yanit');})[0];if(!item)return;yf.elements.yanit_id.value=item.id;yf.elements.alici.disabled=true;document.getElementById('m-yanit-ozet').textContent='#'+item.id+' — '+item.kullanici+' mesajına yanıt';document.getElementById('m-yanit-vazgec').classList.remove('gizli');saveDraft();yf.elements.yorum.focus();});
    document.addEventListener('kp:degisti',function(){setChangeStrip(true);});
    var refreshBtn=document.getElementById('sonuclari-yenile'),stripBtn=document.getElementById('degisiklik-yenile');
    if(refreshBtn)refreshBtn.addEventListener('click',refreshResults);if(stripBtn)stripBtn.addEventListener('click',refreshResults);
    function refreshResults(){if(refreshRunning)return;var old=resultRoot();if(!old)return;refreshRunning=true;old.setAttribute('aria-busy','true');if(refreshBtn)refreshBtn.disabled=true;
      fetch(window.location.href,{credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}}).then(function(r){if(r.redirected)throw kayitHata(401);if(!r.ok)throw new Error('Sonuçlar yenilenemedi.');return r.text();}).then(function(html){var parsed=new DOMParser().parseFromString(html,'text/html'),fresh=parsed.getElementById('kayit-sonuclari');if(!fresh)throw new Error('Yenilenecek sonuç alanı bulunamadı.');old.replaceWith(fresh);var boy=document.getElementById('sayfa-boyu');if(boy)boy.addEventListener('change',function(){window.location.href=boy.value;});toplu.update();setChangeStrip(false);toast('Sonuçlar yenilendi. Filtreleriniz ve taslaklarınız korundu.');}).catch(function(e){toast(e.message,true);}).then(function(){refreshRunning=false;if(refreshBtn)refreshBtn.disabled=false;});}

    function formOpen(){return !form.classList.contains('gizli');}
    function neighbours(){var ids=recordIds(),i=ids.indexOf(acikId);return {ids:ids,i:i,prev:i>0,next:i>=0&&i<ids.length-1};}
    function step(delta){var n=neighbours();if(n.i<0)return;var next=n.i+delta;if(next<0||next>=n.ids.length){toast(delta<0?'Bu sayfadaki ilk kayıttasınız.':'Bu sayfadaki son kayıttasınız.');return;}openRecord(n.ids[next],null,lb&&lb.isOpen());}
    function closeRecord(){if(lb)lb.close();saveDraft();modal.classList.add('gizli');modal.setAttribute('aria-hidden','true');document.body.style.overflow='';acikId=null;acikKayit=null;if(acan&&typeof acan.focus==='function')acan.focus();}
    function openRecord(id,trigger,buyut){
      var serial=++openSerial;if(acikId&&acikId!==id){saveDraft();yf.reset();resetReply();}
      acikId=id;if(trigger)acan=trigger;lightboxBekliyor=!!buyut;
      modal.classList.remove('gizli');modal.setAttribute('aria-hidden','false');document.body.style.overflow='hidden';form.classList.add('gizli');formHata.classList.add('gizli');
      document.getElementById('m-alanlar').innerHTML='<div class="genis"><dt>Yükleniyor</dt><dd>Kayıt ayrıntısı getiriliyor…</dd></div>';
      if(!lb||!lb.isOpen())modal.querySelector('.modal-kapat').focus();
      kayitIstek('/kayit/'+id).then(function(k){if(acikId===id&&serial===openSerial)showRecord(k);}).catch(function(e){if(serial!==openSerial)return;document.getElementById('m-alanlar').innerHTML='<div class="genis"><dt>Açılamadı</dt><dd>'+esc(e.message)+'</dd></div>';if(e.status===409)toastEylem(e.message,'Yenile',function(){openRecord(id,acan);});else toast(e.message,true);if(lb&&lb.isOpen())lb.open([],0,{baslik:'Kayıt #'+id,oncekiVar:neighbours().prev,sonrakiVar:neighbours().next});});
    }
    function gorselPlaceholder(k,hata){var yok=document.getElementById('m-gorsel-yok');var gyazo=/gyazo\.com/i.test(k.dis_link||'');var html;
      if(hata&&k.gorsel_kaynak==='gyazo'||(!hata&&!k.gorsel_var&&gyazo))html='<b>Görsel yok (eski Gyazo linki açılamadı)</b>Bağlantı artık yanıt vermiyor ya da sunucudan erişilemiyor.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
      else if(hata)html='<b>Görsel şu an açılamadı</b>Dosya sunucuda bulunamadı ya da bozuk.'+(k.dis_link?'<br><a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':'');
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
      acikKayit=k;var n=neighbours();
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
      var onay=document.getElementById('m-onay-ozet');onay.textContent=k.kt?(k.kt_kim?'Onaylayan: '+k.kt_kim+(k.kt_zaman?' · '+k.kt_zaman:''):'Eski kaynaktan onaylı aktarıldı; onaylayan kişi bilgisi yok.'):(k.silindi?'Silinmiş kayıt'+(k.silen?' · silen: '+k.silen:'')+(k.silme_zamani?' · '+k.silme_zamani:''):'Onay bekliyor');onay.classList.toggle('onayli',!!k.kt);
      var state=[];if(k.silindi)state.push('<span class="etiket-kucuk kirmizi-arka">Silindi'+(k.silen?' ('+esc(k.silen)+')':'')+'</span>');else if(k.excel_durum==='silinmis')state.push('<span class="etiket-kucuk gri-arka">Eski kaynakta yok</span>');if(k.bekleyen_hata)state.push('<span class="etiket-kucuk kirmizi-arka">İşlem hatası</span>');else if(k.bekleyen_islem)state.push('<span class="etiket-kucuk turuncu-arka">İşleniyor</span>');document.getElementById('m-durum').innerHTML=state.join(' ');
      /* Görseller */
      gorseller=[];var v='?v='+encodeURIComponent(k.guncelleme||k.surum||'');
      if(k.gorsel_url)gorseller.push({url:k.gorsel_url+v,ham:k.gorsel_url,kucuk:k.kucuk_url,indir:k.indir_url,etiket:'Görsel 1',hataMetni:k.gorsel_kaynak==='gyazo'?'Görsel yok (eski Gyazo linki açılamadı).'+(k.dis_link?' <a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">Linki yeni sekmede aç</a>':''):'Görsel şu an açılamadı.'});
      if(k.gorsel2_url)gorseller.push({url:k.gorsel2_url+v,ham:k.gorsel2_url,kucuk:k.kucuk2_url,indir:k.gorsel2_url+'&indir=1',etiket:'Görsel 2',hataMetni:'İkinci görsel şu an açılamadı.'});
      document.getElementById('m-kucukler').innerHTML=gorseller.length>1?gorseller.map(function(it,i){return '<button type="button" data-gorsel-idx="'+i+'" aria-label="'+esc(it.etiket)+'" title="'+esc(it.etiket)+'"><img src="'+esc(it.kucuk||it.url)+'" alt=""><span>'+esc(it.etiket)+'</span></button>';}).join(''):'';
      var buyutBtn=document.getElementById('m-buyut'),yeniSekme=document.getElementById('m-yeni-sekme'),indirBtn=document.getElementById('m-indir');
      buyutBtn.disabled=!gorseller.length;
      if(gorseller.length){yeniSekme.removeAttribute('aria-disabled');indirBtn.removeAttribute('aria-disabled');}
      else{yeniSekme.setAttribute('aria-disabled',k.dis_link?'false':'true');yeniSekme.href=k.dis_link||'#';indirBtn.setAttribute('aria-disabled','true');indirBtn.removeAttribute('href');}
      gorselGoster(0);
      /* Bilgi alanları */
      var fields=[['Personel kodu',k.personel,'buyuk'],['Kategori',k.kategori],['Üye ID',k.uye_id],['Ana üye ID',k.ana_uye_id],['Lead ID',k.lead_id],['Tür',k.tip],['Tarih',k.tarih||k.tarih_ham],['Kaynak',{telegram:'Telegram',excel:'Eski Excel',panel:'Panel'}[k.kaynak]||k.kaynak],['Ekleyen',k.ekleyen_ad?(k.ekleyen_ad+(k.ekleyen_id?' ('+k.ekleyen_id+')':'')+(k.ekleyen_guven==='tahmini'?' · tahmini eşleşme':'')):(k.ekleyen_id||'')],['Kayıt ID',k.id],['Açıklama',k.aciklama,'genis'],['Ek not',k.ek_not,'genis']];
      (k.soru_cevaplar||[]).filter(function(q){return !q.preset;}).forEach(function(q){fields.push([q.label,q.value]);});
      document.getElementById('m-alanlar').innerHTML=fields.filter(function(x){return x[1]!==null&&x[1]!==undefined&&x[1]!=='';}).map(function(x){var cls=x[2]||'';return '<div class="'+(cls==='genis'?'genis':'')+'"><dt>'+esc(x[0])+'</dt><dd class="'+(cls==='buyuk'?'buyuk':'')+'">'+esc(x[1])+'</dd></div>';}).join('')||'<div class="genis"><dt>Bilgi</dt><dd>Bu kayıtta doldurulmuş alan yok.</dd></div>';
      if(k.ekleyen_id){Array.prototype.forEach.call(document.querySelectorAll('#m-alanlar dt'),function(dt){if(dt.textContent==='Ekleyen'){var dd=dt.nextElementSibling,a=document.createElement('a');a.href='/telegram/kullanici/'+encodeURIComponent(k.ekleyen_id)+'/kanitlar';a.textContent=dd.textContent+' — kanıt profili';dd.textContent='';dd.appendChild(a);}});}
      document.getElementById('m-link').innerHTML=(k.dis_link?'Link: <a href="'+esc(k.dis_link)+'" target="_blank" rel="noopener">'+esc(k.dis_link)+'</a> <button class="btn kucuk" type="button" data-kopyala="'+esc(k.dis_link)+'">Kopyala</button>':(k.link?'Link alanı: '+esc(k.link):''))+(k.dis_link2?'<br>İkinci link: <a href="'+esc(k.dis_link2)+'" target="_blank" rel="noopener">'+esc(k.dis_link2)+'</a>':'');
      /* Eylemler */
      var buttons=[];
      if(!k.silindi){
        if(k.izin_kt)buttons.push(k.kt?'<button class="btn" type="button" data-islem="kt" data-deger="0">Onayı kaldır</button>':'<button class="btn basari" type="button" data-islem="kt" data-deger="1">Onayla</button>');
        if(k.izin_duzenle)buttons.push('<button class="btn" type="button" data-islem="duzenle">Düzenle</button>');
        if(k.izin_gyazo)buttons.push('<button class="btn" type="button" data-islem="gyazo" '+((!k.gyazo_hazir||k.gyazo_bekliyor)?'disabled title="'+(k.gyazo_bekliyor?'Dönüşüm arka planda sürüyor':'Gyazo ayarı eksik; süperadmin sunucuda yapılandırmalı')+'"':'')+'>'+(k.gyazo_bekliyor?'Gyazo işlemi sürüyor':'Gyazo’ya dönüştür')+'</button>');
        if(k.izin_sil)buttons.push('<button class="btn tehlike" type="button" data-islem="sil">Sil</button>');
      }else if(k.izin_sil&&k.geri_al_olur)buttons.push('<button class="btn birincil" type="button" data-islem="geri_al">Geri al</button>');
      var box=document.getElementById('m-butonlar');box.innerHTML=buttons.join('');Array.prototype.forEach.call(box.querySelectorAll('button'),function(b){b.addEventListener('click',function(){recordAction(b.getAttribute('data-islem'),b);});});
      var history=k.gecmis||[];document.getElementById('m-gecmis-sayi').textContent=history.length;
      document.getElementById('m-gecmis').innerHTML=history.map(function(h){var detail=h.yeni&&h.islem!=='onayla'&&h.islem!=='onay_kaldir'&&h.islem!=='sil'&&h.islem!=='geri_al'?'<small>'+esc(h.yeni)+'</small>':'';return '<li><time>'+esc(h.zaman)+'</time><div><span class="islem">'+esc(islemAdi(h.islem))+'</span> · '+esc(h.kullanici)+detail+'</div></li>';}).join('')||'<li><time>—</time><div>Henüz işlem yok.</div></li>';
      if(lightboxBekliyor){lightboxBekliyor=false;if(gorseller.length)openLightbox();else toast('Bu kayıtta büyütülecek görsel yok.');}
      else if(lb&&lb.isOpen())openLightbox();
    }
    function validateEdit(d){var errors=[];['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].forEach(function(n){form.elements[n].classList.remove('hatali');if(d[n].length>500){errors.push('Alanlar en çok 500 karakter olabilir.');form.elements[n].classList.add('hatali');}if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(d[n])){errors.push('Alanlarda kontrol karakteri kullanılamaz.');form.elements[n].classList.add('hatali');}});
      if(!d.personel&&!d.uye_id&&!d.ana_uye_id&&!d.lead_id){errors.push('Personel kodu, üye ID, ana üye ID veya lead ID alanlarından en az biri dolu olmalı.');form.elements.personel.classList.add('hatali');}
      ['uye_id','ana_uye_id','lead_id'].forEach(function(n){if(d[n]&&/\s/.test(d[n])){errors.push((n==='uye_id'?'Üye ID':n==='ana_uye_id'?'Ana üye ID':'Lead ID')+' boşluk içeremez.');form.elements[n].classList.add('hatali');}});
      return errors.filter(function(x,i,a){return a.indexOf(x)===i;});}
    function recordAction(action,button){
      var k=acikKayit;if(!k)return;
      if(action==='duzenle'){['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].forEach(function(n){form.elements[n].value=k[n]||'';form.elements[n].classList.remove('hatali');});formHata.classList.add('gizli');form.classList.remove('gizli');form.elements.personel.focus();return;}
      if(action==='gyazo'&&!confirm('Görsel Gyazo dış servisine gönderilecek; yerel görsel korunur. Dönüştürülsün mü?'))return;
      var data=action==='kt'?{deger:button.getAttribute('data-deger')}:{};
      if(action==='sil'){var sebep=prompt('Kayıt silinenlere taşınacak. Silme nedeni (isteğe bağlı):','');if(sebep===null)return;data.sebep=sebep.trim();}
      if(action==='geri_al'&&!confirm('Kayıt geri alınacak. Emin misiniz?'))return;
      var url='/kayit/'+k.id+'/'+(action==='geri_al'?'geri-al':action);data.surum=k.surum;button.disabled=true;
      kayitPost(url,data).then(function(r){if(!r.ok)throw new Error(r.hata||'İşlem yapılamadı');toast(r.mesaj||(action==='kt'?(r.kt?'Onaylandı.':'Onay kaldırıldı.'):(action==='sil'?'Silinenlere taşındı.':action==='geri_al'?'Geri alındı.':'Kaydedildi.')),r.converted===false&&!r.pending);if(action==='gyazo'&&r.pending)watchGyazo(k.id);updateCard(k.id,action,r);openRecord(k.id,acan);}).catch(function(e){button.disabled=false;if(e.status===409)toastEylem(e.message,'Yenile',function(){openRecord(k.id,acan);});else toast(e.message,true);});
    }
    function watchGyazo(id){var tries=0;function check(){if(tries++>100)return;kayitIstek('/kayit/'+id+'/gyazo-durum').then(function(d){if(d.pending){setTimeout(check,2000);return;}toast(d.mesaj||'Dönüşüm tamamlandı',d.converted===false);if(acikId===id){if(form.classList.contains('gizli')&&!yf.elements.yorum.value.trim())openRecord(id,acan);else setChangeStrip(true);}}).catch(function(){});}setTimeout(check,2000);}
    function saveEdit(){var k=acikKayit;if(!k)return;var d={};['personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama'].forEach(function(n){d[n]=form.elements[n].value.trim();});
      var errors=validateEdit(d);if(errors.length){formHata.textContent=errors.join(' ');formHata.classList.remove('gizli');return;}formHata.classList.add('gizli');d.surum=k.surum;
      var btn=form.querySelector('button[type=submit]');btn.disabled=true;
      kayitPost('/kayit/'+k.id+'/duzenle',d).then(function(r){if(!r.ok)throw new Error(r.hata||'Kaydedilemedi');toast(r.degisiklik===false?'Değişiklik yok.':'Kaydedildi.');form.classList.add('gizli');var c=cardOf(k.id);if(c){var b=c.querySelector('.satir1 b, .galeri-bilgi b, td:nth-child(4) b, td:nth-child(5) b');if(b)b.textContent=d.personel||'—';}openRecord(k.id,acan);}).catch(function(e){if(e.status===409){formHata.textContent=e.message;formHata.classList.remove('gizli');toastEylem(e.message,'Yenile',function(){openRecord(k.id,acan);});}else{formHata.textContent=e.message;formHata.classList.remove('gizli');toast(e.message,true);}}).then(function(){btn.disabled=false;});}
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
    var acParam=new URLSearchParams(window.location.search).get('ac');
    if(acParam){var u=new URL(window.location.href);u.searchParams.delete('ac');history.replaceState(null,'',u.pathname+u.search);openRecord(+acParam,null);}
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
  function bildirimSayfasi(){var all=document.getElementById('bildirimler-tum-okundu');function mark(key,el){postBildirim({ids:[key]},{id:key}).then(function(){var row=el.closest('.bildirim-satir');if(row){row.classList.remove('okunmamis');var b=row.querySelector('[data-bildirim-okundu]');if(b)b.remove();}toast('Okundu işaretlendi.');}).catch(function(e){toast(e.message,true);});}document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-bildirim-okundu]');if(b){e.preventDefault();mark(b.getAttribute('data-bildirim-okundu'),b);}var a=e.target.closest&&e.target.closest('[data-bildirim-link]');if(a){e.preventDefault();var target=a.href,key=a.getAttribute('data-bildirim-key');postBildirim({ids:[key]},{id:key}).then(function(){window.location.href=target;}).catch(function(){window.location.href=target;});}});if(all)all.addEventListener('click',function(){all.disabled=true;postBildirim({hepsi:true},{hepsi:'1'}).then(function(){Array.prototype.forEach.call(document.querySelectorAll('.bildirim-satir.okunmamis'),function(row){row.classList.remove('okunmamis');var b=row.querySelector('[data-bildirim-okundu]');if(b)b.remove();});toast('Bildirimler okundu işaretlendi.');}).catch(function(e){toast(e.message,true);}).then(function(){all.disabled=false;});});}
  function bildirimler(){var zil=document.getElementById('zil'), box=document.getElementById('bildirim-kutu'), list=document.getElementById('bildirim-liste'), count=document.getElementById('zil-sayi');if(!zil||!box||!list)return;var initial=true,stamp=null,seen={},running=false,timer=null,key='kanit-notify-'+(window.PANEL_KULLANICI||'');try{seen=JSON.parse(sessionStorage.getItem(key)||'{}');}catch(_){}var permission=document.getElementById('bildirim-izin'), permissionBtn=document.getElementById('bildirim-izin-btn'), clean=document.getElementById('bildirim-temizle');if(window.Notification&&Notification.permission==='default'&&permission)permission.classList.remove('gizli');if(permissionBtn)permissionBtn.addEventListener('click',function(){window.Notification.requestPermission().then(function(){permission.classList.add('gizli');});});zil.addEventListener('click',function(){var hidden=box.classList.toggle('gizli');zil.setAttribute('aria-expanded',String(!hidden));});if(clean)clean.addEventListener('click',function(){postBildirim({hepsi:true},{hepsi:'1'}).then(function(){list.innerHTML='<li>Okunmamış bildirim yok.</li>';count.classList.add('gizli');box.classList.add('gizli');}).catch(function(e){toast(e.message,true);});});function recordURL(k){var id=k.kayit_id||k.id;return '/kayitlar?proje='+encodeURIComponent(k.proje||'')+'&durum=hepsi&ac='+encodeURIComponent(id||'');}function render(data){count.textContent=data.okunmamis||0;count.classList.toggle('gizli',!(data.okunmamis||0));list.innerHTML=(data.bildirimler||[]).map(function(n){var id=n.key||n.bildirim_id||'', label={soru:'Soru',yanit:'Yanıt',yorum:'Yorum',onay:'Onay'}[n.tur]||'Yeni kayıt', color=(window.PROJE_RENKLERI||{})[n.proje]||'#64748b';return '<li><span class="rozet" style="background:'+esc(color)+';color:'+yaziRengi(color)+'">'+esc(n.proje||'—')+'</span> <b>'+esc(label)+(n.kim?' · '+esc(n.kim):'')+'</b><p>'+esc(n.metin||n.personel||'')+'</p><small>'+esc(n.zaman||n.tarih||'')+'</small><br><a href="'+recordURL(n)+'" data-notify="'+esc(id)+'">Kaydı aç</a></li>';}).join('')||'<li>Okunmamış bildirim yok.</li>';Array.prototype.forEach.call(list.querySelectorAll('[data-notify]'),function(a){a.addEventListener('click',function(e){e.preventDefault();var target=a.href,id=a.getAttribute('data-notify');postBildirim({ids:[id]},{id:id}).then(function(){window.location.href=target;}).catch(function(){window.location.href=target;});});});(data.bildirimler||[]).forEach(function(n){var id=n.key||n.bildirim_id;if(!seen[id]){seen[id]=true;if(!initial){toast('Yeni bildirim: '+(n.proje||'')+' '+(n.personel||n.kim||''));if(window.Notification&&Notification.permission==='granted'){try{new Notification('Kanıt Paneli · '+(n.proje||''),{body:n.metin||n.personel||'Yeni bildirim',tag:'kanit-'+(window.PANEL_KULLANICI||'')+'-'+id});}catch(_){}}setChangeStrip(true);}}});try{sessionStorage.setItem(key,JSON.stringify(seen));}catch(_){}if(data.degisiklik&&stamp&&stamp!==data.degisiklik)document.dispatchEvent(new CustomEvent('kp:degisti',{detail:data}));stamp=data.degisiklik;initial=false;Array.prototype.forEach.call(document.querySelectorAll('[data-sayac]'),function(el){var p=el.getAttribute('data-sayac').split(':'),v=data.sayac&&data.sayac[p[0]]&&data.sayac[p[0]][p[1]];if(v!==undefined)el.textContent=v;});}
    function schedule(){clearTimeout(timer);timer=setTimeout(poll,10000);}function poll(){if(document.hidden){schedule();return;}if(running)return;running=true;fetch('/bildirim.json',{credentials:'same-origin'}).then(function(r){return r.ok?r.json():null;}).then(function(d){if(d)render(d);}).catch(function(){}).then(function(){running=false;schedule();});}document.addEventListener('visibilitychange',function(){if(!document.hidden){clearTimeout(timer);poll();}});poll();}
  function botSayfasi(){var table=document.getElementById('islemler-tablo');if(!table)return;var last=null,running=false,timer=null;function next(){clearTimeout(timer);timer=setTimeout(update,10000);}function update(){if(document.hidden||running){next();return;}running=true;fetch('/bot/islemler.json',{credentials:'same-origin'}).then(function(r){return r.ok?r.json():null;}).then(function(d){if(!d)return;var sig=JSON.stringify((d.islemler||[]).map(function(x){return[x.id,x.durum];}));if(sig===last)return;last=sig;var tb=table.querySelector('tbody');tb.innerHTML=(d.islemler||[]).map(function(i){return '<tr><td>'+esc(i.zaman)+'</td><td>'+esc(i.ozet)+'</td><td>'+esc(i.kullanici)+'</td><td>'+esc(i.durum)+'</td><td>'+esc(i.mesaj||'')+'</td></tr>';}).join('')||'<tr><td colspan="5">Henüz işlem yok.</td></tr>';}).catch(function(){}).then(function(){running=false;next();});}document.addEventListener('visibilitychange',function(){if(!document.hidden)update();});next();}
  document.addEventListener('submit',function(e){var f=e.target;if(f&&f.getAttribute&&f.getAttribute('data-onay')&&!confirm(f.getAttribute('data-onay')))e.preventDefault();});document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-kopyala]');if(b){e.preventDefault();kopyala(b.getAttribute('data-kopyala'));}});
  return {kayitSayfasi:kayitSayfasi,bildirimler:bildirimler,bildirimSayfasi:bildirimSayfasi,botsayfasi:botSayfasi,botSayfasi:botSayfasi,profilFiltresi:profilFiltresi,toast:toast,kopyala:kopyala};
})();

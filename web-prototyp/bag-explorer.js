(()=>{'use strict';
const BAG=[['saddle','Satteltasche'],['frame','Rahmentasche'],['top','Oberrohrtasche'],['bar','Lenkertasche'],['fork','Gabeltaschen'],['bottle','Flaschenhalter']];
const $=id=>document.getElementById(id);
function init(){
 const screen=$('screen-pack'),stage=$('packBikeStage'),svg=screen?.querySelector('.v152-pack-bike');if(!screen||!stage||!svg||$('roam-v1516-toolbar'))return;
 // Explorer edit mode owns setup visibility; retire the legacy nested accordion.
 $('roam-v1512-toggle-dock')?.remove();
 $('packBagDock')?.classList.remove('roam-v1512-collapsed');
 screen.querySelector('.v158-section-title')?.classList.remove('roam-v1512-collapsed');
 const toolbar=document.createElement('div');toolbar.id='roam-v1516-toolbar';const positions=document.createElement('div');positions.id='roam-v1516-positions';positions.hidden=true;const tip=document.createElement('p');tip.id='roam-v1516-tip';
 let mode='used',selected=null,returnFocus=null,previousOverflow='';
 const modal=document.createElement('div');modal.id='roam-v1516-modal';modal.hidden=true;modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-label','Taschen-Explorer');
 modal.innerHTML='<div id="roam-v1516-panel"><div id="roam-v1516-top"><div><div style="font-size:11px;letter-spacing:.12em;color:#73806e">BIKE & BAG EXPLORER</div><h2 id="roam-v1516-headline">Tasche</h2><div id="roam-v1516-stats"></div></div><button id="roam-v1516-close" aria-label="Zurück zum Fahrrad">×</button></div><div id="roam-v1516-content"><div id="roam-v1516-bag-hero"></div><div><h3 style="margin:0 0 10px">Was ist drin?</h3><div id="roam-v1516-gear"></div></div></div></div>';
 document.body.append(modal);
 function close(){const wasOpen=!modal.hidden;modal.hidden=true;selected=null;if(wasOpen){document.body.style.overflow=previousOverflow;if(returnFocus?.isConnected)returnFocus.focus()}$('packBagDetail').hidden=true;}
 $('roam-v1516-close').onclick=close;modal.addEventListener('click',e=>{if(e.target===modal)close()});document.addEventListener('keydown',e=>{if(modal.hidden)return;if(e.key==='Escape'){e.preventDefault();close()}else if(e.key==='Tab'){const controls=[...modal.querySelectorAll('button,select')].filter(el=>!el.disabled);const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}});
 const modeButtons={};[['empty','Ohne Taschen'],['used','Meine Taschen'],['edit','Taschen bearbeiten']].forEach(([id,label])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>{mode=id;close();paint()};toolbar.append(b);modeButtons[id]=b});
 const posButtons={};BAG.forEach(([id,label])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>toggle(id);positions.append(b);posButtons[id]=b});
 stage.parentNode.insertBefore(toolbar,stage);stage.parentNode.insertBefore(positions,stage);stage.parentNode.insertBefore(tip,stage);
 function paint(){
   screen.dataset.bagMode=mode;
   BAG.forEach(([id,label])=>{
     const state=ROAMPack.getBag(id),layer=svg.querySelector('[data-bike-layer="'+id+'"]');
     // The old fork artwork represents the two independent front cargo mounts.
     const bags=id==='fork'?[state,ROAMPack.getBag('frontL'),ROAMPack.getBag('frontR')].filter(Boolean):[state];
     const mounted=bags.some(b=>b.mounted),filled=bags.some(b=>b.mounted&&b.items.length);
     const on=mode==='used'?filled:mode==='edit'?mounted:false;
     posButtons[id].setAttribute('aria-pressed',String(mounted));
     if(!layer)return;
     layer.classList.toggle('roam-v1514-visible',on);layer.classList.toggle('roam-v1514-hidden',!on);
     layer.classList.remove('v152-hidden','v154-hidden','roam-bag-inactive','v158-bike-unmounted');
     layer.style.setProperty('display',on?'inline':'none','important');
     layer.style.setProperty('animation','none','important');
     layer.style.setProperty('transition','none','important');
     layer.style.setProperty('opacity',on?'1':'0','important');
     layer.style.setProperty('visibility',on?'visible':'hidden','important');
     layer.style.pointerEvents=on?'auto':'none';layer.style.cursor=on?'pointer':'default';
     layer.setAttribute('tabindex',on?'0':'-1');layer.setAttribute('role','button');layer.setAttribute('aria-label',label+' öffnen');
   });
   // Independent cargo buttons remain usable, and honor the same display modes.
   screen.querySelectorAll('.v1589-cargo-hotspot,.v1589-cargo-label').forEach(el=>{
     const id=['frontL','frontR','rearL','rearR'].find(id=>el.classList.contains(id)),b=ROAMPack.getBag(id);
     el.hidden=mode==='empty'||mode==='used'&&!(b?.mounted&&b.items.length);
   });
   Object.entries(modeButtons).forEach(([id,b])=>b.setAttribute('aria-pressed',String(mode===id)));
   positions.hidden=mode!=='edit';
   tip.textContent=mode==='empty'?'Fahrrad ohne Gepäck.':mode==='edit'?'Tippe eine Taschenposition an, um sie zu montieren oder zu entfernen.':'Nur befüllte Taschen werden am Fahrrad angezeigt. Leere Taschen bleiben unter „Taschen bearbeiten“ verfügbar.';
 }
 function toggle(id){
   const ids=id==='fork'?['frontL','frontR']: [id];
   const on=!ids.some(ROAMPack.isMounted);
   ids.forEach(key=>ROAMPack.setMounted(key,on));paint();
 }
 function renderContents(id){
   const bag=ROAMPack.getBag(id);if(!bag?.mounted){close();return}
   $('roam-v1516-headline').textContent=bag.name;
   $('roam-v1516-stats').textContent=`${formatLiters(bag.l)} / ${formatLiters(bag.cap)} L · ${bag.kg.toFixed(1).replace('.',',')} kg · ${bag.items.length} Teile${bag.preview?' · Vorschau':''}`;
   $('roam-v1516-bag-hero').innerHTML=bagIconSvg(id);
   const gear=$('roam-v1516-gear');gear.replaceChildren();
   if(!bag.items.length){const empty=document.createElement('div');empty.id='roam-v1516-empty';empty.textContent='Noch keine Gegenstände in dieser Tasche.';gear.append(empty)}
   bag.items.forEach(item=>{
     const row=document.createElement('div');row.className='v158-bag-item-row';row.dataset.itemId=item.id;
     const icon=document.createElement('span');icon.className='v158-bag-item-icon';icon.innerHTML=itemIcon(item.id,item.cat);
     const text=document.createElement('div'),name=document.createElement('b'),stats=document.createElement('small');
     name.textContent=item.name;stats.textContent=`${Number(item.kg||0).toFixed(2).replace('.',',')} kg · ${formatLiters(item.l)} L · ${item.access==='high'?'schnell erreichbar':item.access==='low'?'selten benötigt':'normaler Zugriff'}`;
     const select=document.createElement('select');select.setAttribute('aria-label',item.name+' verschieben');
     select.add(new Option('nicht zugewiesen',''));
     ROAMPack.bagIds().filter(ROAMPack.isMounted).forEach(id=>select.add(new Option(ROAMPack.getBag(id).name,id)));
     select.value=id;select.onchange=()=>{ROAMPack.moveItem(item.id,select.value);renderContents(id);paint()};
     text.append(name,stats,select);row.append(icon,text);gear.append(row);
   });
 }
 function open(id,contentsOnly=false){
   if(mode==='empty')return;
   if(mode==='edit'&&!contentsOnly){toggle(id);return}
   if(id==='fork'&&!ROAMPack.getBag(id)?.items.length){id=['frontL','frontR'].find(key=>ROAMPack.getBag(key)?.items.length)||id}
   if(!ROAMPack.getBag(id)?.mounted)return;
   returnFocus=document.activeElement;previousOverflow=document.body.style.overflow;selected=id;renderContents(id);modal.hidden=false;document.body.style.overflow='hidden';$('roam-v1516-close').focus();
 }
 window.ROAMFoundation03={snapshot:()=>({mode,bags:Object.fromEntries(ROAMPack.bagIds().map(id=>[id,ROAMPack.getBag(id)]))}),refresh:paint};
 // Keep the original detail in the DOM for ROAM's existing update code, but show only the Explorer.
 $('packBagDetail').hidden=true;
 // Render notifications replace the observer that repeatedly rewrote SVG styles.
 let scheduled=false;
 document.addEventListener('roam:pack-rendered',()=>{
   if(scheduled)return;scheduled=true;
   requestAnimationFrame(()=>{scheduled=false;paint();if(selected&&!modal.hidden)renderContents(selected)});
 });
 // Fill cards and cargo controls open the same contents, without scraping another view.
 function activate(event){
   if(event.type==='keydown'&&!['Enter',' '].includes(event.key))return;
   const dock=event.target.closest('[data-v158-open-bag]');
   const card=dock||event.target.closest('[data-bag-id],.v1589-cargo-hotspot,[data-bike-layer]');if(!card)return;
   // Native controls synthesize a click for Enter/Space. Handle that click only.
   if(event.type==='keydown'&&card.matches('button,input,select,a[href]'))return;
   const id=card.dataset.v158OpenBag||card.dataset.bagId||card.dataset.bikeLayer||['frontL','frontR','rearL','rearR'].find(id=>card.classList.contains(id));
   if(!ROAMPack.getBag(id))return;
   event.preventDefault();event.stopImmediatePropagation();if(event.repeat)return;
   if(dock&&!ROAMPack.isMounted(id))return;
   open(id,!!dock);
 }
 screen.addEventListener('click',activate,true);
 screen.addEventListener('keydown',activate,true);
 paint();
 document.querySelectorAll('body *').forEach(el=>{if(!el.children.length&&/^ROAM · Beta · V15\.\d+$/.test(el.textContent?.trim()||''))el.textContent='ROAM · Foundation 03'});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

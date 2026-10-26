(() => {
  const VERSION='15.8';
  const PACK_MOUNTED_KEY='roam-pack-mounted-v158';
  const bagGuide={
    saddle:{short:'Kleidung · Schlafsachen',why:'Leicht und voluminös – gut für Dinge, die unterwegs selten gebraucht werden.'},
    frame:{short:'Werkzeug · Essen · Powerbank',why:'Schwere, kompakte Ausrüstung sitzt hier zentral und fahrstabil.'},
    top:{short:'Snacks · Geld · Elektronik',why:'Für kleine Dinge, die du während der Fahrt schnell erreichen willst.'},
    bar:{short:'Jacke · Schlafsack · leichte Teile',why:'Ideal für leichte, voluminöse Ausrüstung an der Front.'},
    fork:{short:'Drybags · Camping',why:'Zusätzlicher Stauraum an der Gabel – möglichst links und rechts ausgewogen beladen.'},
    bottle:{short:'Wasser',why:'Wasser bleibt tief, zentral und jederzeit erreichbar.'}
  };

  // One mounted state for every renderer. Recover stale legacy flags without losing contents.
  let mountedV158={};
  try{const saved=JSON.parse(localStorage.getItem(PACK_MOUNTED_KEY)||'null');
    if(saved&&typeof saved==='object'&&!Array.isArray(saved))mountedV158=saved;
  }catch(e){}
  function persistMountedV158(){try{localStorage.setItem(PACK_MOUNTED_KEY,JSON.stringify(mountedV158))}catch(e){}}
  function reconcileMounted(){
    let changed=false;
    Object.keys(packBags).forEach(id=>{
      if(typeof mountedV158[id]!=='boolean'){mountedV158[id]=true;changed=true}
      if(packItems.some(x=>x.needed&&x.have&&x.bag===id)&&!mountedV158[id]){mountedV158[id]=true;changed=true}
    });
    if(changed)persistMountedV158();
  }
  function isMountedV158(id){reconcileMounted();return !!packBags[id]&&mountedV158[id]===true}
  function mountedIdsV158(){reconcileMounted();return Object.keys(packBags).filter(id=>mountedV158[id]===true)}
  function getBag(id){
    if(!packBags[id])return null;
    return {id,...packBags[id],...bagStats(id,packProposal?.items||packItems),mounted:isMountedV158(id),preview:!!packProposal};
  }
  window.ROAMPack={getBag,bagIds:()=>Object.keys(packBags),isMounted:isMountedV158,setMounted:setMountedV158,
    moveItem(itemId,bagId){
      const source=packProposal?.items||packItems,target=source.find(x=>x.id===itemId);
      if(!target||bagId&&!isMountedV158(bagId))return false;
      if(bagId){const st=getBag(bagId),existing=target.bag===bagId?Number(target.l):0;
        if(st.l-existing+Number(target.l)>st.cap+1e-6){packToast(`${st.name}: zu wenig Platz`);return false}}
      target.bag=bagId;
      if(packProposal)packProposal.unassigned=source.filter(i=>i.needed&&i.have&&!i.bag);
      else {invalidateAppliedPack();packPersist()}
      renderPackPrototype();renderOverviewDashboard();return true;
    }
  };
  // Compatibility entry points for existing cargo controls, backed by the same state.
  Object.assign(window,{isMountedV158,mountedIdsV158,setMountedV158});
  reconcileMounted();

  function setMountedV158(id,on){
    if(!packBags[id]||isMountedV158(id)===on)return;
    const assigned=packItems.filter(x=>x.bag===id);
    if(!on&&assigned.length&&typeof confirm==='function'&&!confirm(`${packBags[id].name} entfernen? ${assigned.length} Gegenstand/Gegenstände werden dadurch wieder ungepackt.`))return;
    mountedV158[id]=on;
    if(!on){packItems.forEach(x=>{if(x.bag===id)x.bag=''});if(selectedPackBagV15===id)selectedPackBagV15='';}
    packProposal=null;invalidateAppliedPack();persistMountedV158();packPersist();renderPackPrototype();renderOverviewDashboard();
    packToast(on?`${packBags[id].name} am Bike montiert`:`${packBags[id].name} entfernt${assigned.length?` · ${assigned.length} Teil(e) ohne Tasche`:''}`);
  }

  // Refined, consistent line icons.
  itemIcon=function(id,cat){
    const a='viewBox="0 0 24 24" aria-hidden="true"';
    const p=d=>`<svg ${a}><path d="${d}"/></svg>`;
    if(id==='sleep')return p('M7 3h8c2 0 3 1 3 3v15H6V7c0-2 1-4 1-4Zm2 4h6M9 10h6M9 13h6M9 16h5');
    if(id==='tent')return p('M3 20 12 4l9 16H3Zm9-16v16M7 20l5-8 5 8');
    if(id==='mat')return p('M6 5h10a3 3 0 0 1 0 6H8a3 3 0 0 0 0 6h10M6 5v14');
    if(['shirt','down','rain'].includes(id))return p('M8 4 4 6l2 5 2-1v10h8V10l2 1 2-5-4-2-2 2h-4L8 4Z');
    if(id==='shorts')return p('M7 4h10l-1 7 2 9h-5l-1-6-1 6H6l2-9-1-7Z');
    if(id==='under')return p('M6 6h12l-1 5-5 3-5-3-1-5Zm6 8v6');
    if(id==='socks')return p('M9 3h5v9l4 3-2 4H9c-2 0-3-1-3-3s1-3 3-3V3Z');
    if(id==='sandals')return p('M5 14c4 0 7 1 10 4l-2 3H6c-2 0-3-1-3-3 0-2 1-4 2-4Zm9-9c2 2 3 5 2 8M10 4c1 3 1 6 0 9');
    if(id==='water')return p('M9 3h6v3l2 3v12H7V9l2-3V3Zm0 7h8');
    if(id==='food')return p('M5 5h14l-1 15H6L5 5Zm3 0V3h8v2M8 10h8');
    if(id==='snacks')return p('M7 3h10l2 5-2 13H7L5 8l2-5Zm-1 5h12');
    if(id==='stove')return p('M7 11h10l2 8H5l2-8Zm2-3h6M10 5h4M12 2v3');
    if(id==='dishes')return p('M4 11h16c0 5-3 8-8 8s-8-3-8-8Zm8-7v5M8 6v3M16 6v3');
    if(id==='fuel')return p('M8 4h8v3l2 3v10H6V10l2-3V4Zm2 3h4');
    if(id==='tools')return p('M4 5l5 5m2 1 8 8M16 4a4 4 0 0 0-4 5L5 16l3 3 7-7a4 4 0 0 0 5-4l-3 2-3-3 2-3Z');
    if(id==='spares')return p('M5 12a7 7 0 1 0 14 0 7 7 0 1 0-14 0Zm7-3v6M9 12h6');
    if(id==='power')return p('M8 3h8v4h2v14H6V7h2V3Zm2 5h4M10 13h4');
    if(id==='electronics')return p('M8 3h8v18H8V3Zm2 3h4M11 18h2');
    if(id==='docs')return p('M6 3h9l3 3v15H6V3Zm8 0v4h4M9 11h6M9 15h6');
    if(id==='money')return p('M3 7h18v11H3V7Zm3 3h12M12 13a2 2 0 1 0 0 4 2 2 0 1 0 0-4Z');
    if(id==='hygiene')return p('M9 3h6v4l2 3v11H7V10l2-3V3Zm0 10h6M11 3h2');
    if(cat==='tools')return p('M4 5l5 5m2 1 8 8M15 4l5 5M5 19l6-6');
    if(cat==='electronics')return p('M13 2 6 13h5l-1 9 8-12h-5V2Z');
    if(cat==='food')return p('M5 3v7M3 3v4c0 2 4 2 4 0V3M5 10v11M14 3c4 3 4 9 0 11v7');
    if(cat==='sleep')return p('M5 4h14v16H5V4Zm3 3h8M8 10h8');
    return `<svg ${a}><circle cx="12" cy="12" r="8"/></svg>`;
  };

  bagIconSvg=function(id){
    const c=packBags[id]?.color||'#607057',stroke='#e8dfd1';
    if(id==='saddle')return `<svg viewBox="0 0 56 34"><path d="M4 11Q22 2 51 9l-6 20H11Q6 28 5 23Z" fill="${c}" stroke="${stroke}" stroke-width="1.6"/><path d="M13 10 38 27M24 7l-4 20" fill="none" stroke="#d9cebd" stroke-width="1.4"/></svg>`;
    if(id==='frame')return `<svg viewBox="0 0 56 34"><path d="M5 5h46L36 29H7Z" fill="${c}" stroke="${stroke}" stroke-width="1.6"/><path d="M12 9h30" fill="none" stroke="#efe5d8" stroke-width="1.3"/></svg>`;
    if(id==='top')return `<svg viewBox="0 0 56 34"><rect x="6" y="10" width="44" height="14" rx="7" fill="${c}" stroke="${stroke}" stroke-width="1.6"/><path d="M14 12h26" stroke="#efe5d8" stroke-width="1.2"/></svg>`;
    if(id==='bar')return `<svg viewBox="0 0 56 34"><path d="M6 9Q28 2 50 9v17Q28 32 6 25Z" fill="${c}" stroke="${stroke}" stroke-width="1.6"/><path d="M18 7q3 10 5 20M37 7q-2 10 0 20" fill="none" stroke="#405044" stroke-width="3"/></svg>`;
    if(id==='fork')return `<svg viewBox="0 0 56 34"><rect x="9" y="3" width="14" height="28" rx="6" fill="${c}" stroke="${stroke}" stroke-width="1.6"/><rect x="32" y="4" width="13" height="27" rx="6" fill="${c}" opacity=".78" stroke="${stroke}" stroke-width="1.4"/></svg>`;
    if(id==='bottle')return `<svg viewBox="0 0 56 34"><path d="M14 3h9v5l3 4v18H11V12l3-4V3Z" fill="#f7f8f2" stroke="#52604f" stroke-width="1.8"/><path d="M36 4h8v5l3 4v17H33V13l3-4V4Z" fill="#f7f8f2" stroke="#52604f" stroke-width="1.8"/><path d="M12 18h13M34 20h12" stroke="${c}" stroke-width="2.4"/></svg>`;
    return `<svg viewBox="0 0 56 34"><rect x="8" y="5" width="40" height="24" rx="8" fill="${c}" stroke="${stroke}" stroke-width="1.6"/></svg>`;
  };

  // Only mounted bags are valid pack destinations.
  bagOptions=function(selected){
    const ids=mountedIdsV158();
    return `<option value="">nicht zugewiesen</option>`+ids.map(id=>`<option value="${id}" ${selected===id?'selected':''}>${packBags[id].name}</option>`).join('');
  };
  packAlternative=function(item,current){for(const id of preferredBags(item)){if(id===current||!isMountedV158(id))continue;const st=bagStats(id);if(st.l+item.l<=st.cap+1e-6)return id}return ''};
  movePackItemDirect=function(itemId,bagId){return ROAMPack.moveItem(itemId,bagId)};
  buildPackProposal=function(){
    const items=packItems.map(x=>({...x})),ids=mountedIdsV158(),used=Object.fromEntries(ids.map(k=>[k,0])),unassigned=[];
    const ordered=relevantPackItems(items).sort((a,b)=>b.kg-a.kg||b.l-a.l);ordered.forEach(i=>i.bag='');
    for(const item of ordered){let best='',score=1e9;for(const id of ids){if(id==='bottle'&&item.id!=='water'&&!/wasser|water|bidon|flasche/i.test(item.name||''))continue;const cap=bagCapacity(id),after=(used[id]||0)+item.l;if(after>cap+1e-6)continue;let pref=preferredBags(item).indexOf(id);if(pref<0)pref=9;let sc=pref*12;if(!(used[id]||0))sc+=18;if(item.id==='water'&&id==='bottle')sc-=120;if(item.kg>=1&&packBags[id].zone!=='center')sc+=18;if(item.access==='high'&&!['top','bar','bottle'].includes(id))sc+=12;if(item.preferredBag===id)sc-=24;sc+=(after/Math.max(.1,cap))*3;if(sc<score){score=sc;best=id}}if(best){item.bag=best;used[best]=(used[best]||0)+item.l}else unassigned.push(item)}
    return {items,unassigned};
  };

  let itemFilterV158='all';
  function matchesFilterV158(i){if(itemFilterV158==='missing')return !i.have;if(itemFilterV158==='available')return i.have;if(itemFilterV158==='packed')return i.have&&!!i.bag;if(itemFilterV158==='unpacked')return i.have&&!i.bag;return true}
  function itemStatusV158(i,preview){if(!i.have)return ['Fehlt','missing',''];if(i.bag)return [preview?'Vorschau':'Gepackt',preview?'preview':'',packBags[i.bag]?.name||''];return ['Noch ohne Tasche','unpacked','']}

  renderPackNeeds=function(){
    applyLodgingPackRules();const box=document.getElementById('packNeedList');if(!box)return;
    box.innerHTML=visiblePackCategories().map(c=>{const arr=(typeof itemsForCategoryV152==='function'?itemsForCategoryV152(c):c.items.map(id=>packItems.find(x=>x.id===id)).filter(Boolean)).filter(x=>x.needed||x.cat!=='sleep'),needed=arr.filter(x=>x.needed).length;if(!arr.length)return '';return `<div class="pack-v12-category"><div class="pack-v12-cathead"><b>${c.name}</b><span>${needed}/${arr.length}</span></div>${arr.map(i=>`<div class="pack-v12-needrow"><button class="pack-v12-check ${i.needed?'':'off'}" data-need="${i.id}" type="button" aria-label="${i.name}: benötigt">✓</button><span class="v158-need-icon">${itemIcon(i.id,i.cat)}</span><span>${i.name}</span><span class="mini-badge">${i.needed?'benötigt':'optional'}</span></div>`).join('')}</div>`}).join('');
    box.querySelectorAll('[data-need]').forEach(b=>b.onclick=()=>{const i=packItems.find(x=>x.id===b.dataset.need);if(!i)return;i.needed=!i.needed;i.needOverride=true;if(!i.needed)i.bag='';packProposal=null;invalidateAppliedPack();packPersist();renderPackPrototype();renderOverviewDashboard()});
  };

  renderPackHave=function(){
    applyLodgingPackRules();const box=document.getElementById('packHaveList');if(!box)return;const q=(document.getElementById('packSearch')?.value||'').toLowerCase(),filter=document.getElementById('packCategoryFilter')?.value||'all',items=packProposal?.items||packItems,preview=!!packProposal;
    box.innerHTML=visiblePackCategories().filter(c=>filter==='all'||c.id===filter).map(c=>{const all=items.filter(x=>x.cat===c.id);const arr=all.filter(i=>i.needed&&matchesFilterV158(i)&&(!q||i.name.toLowerCase().includes(q)));if(!arr.length)return '';return `<div class="pack-v13-group"><div class="pack-v13-grouphead"><b>${c.name}</b><span>${arr.filter(x=>x.have).length}/${arr.length}</span></div>${arr.map(i=>{const [status,cls,statusBag]=itemStatusV158(i,preview);return `<div class="pack-v12-item ${preview?'v154-preview-item':''}"><button class="pack-v12-check ${i.have?'':'off'}" data-have="${i.id}" type="button">✓</button><div class="thumb">${itemIcon(i.id,i.cat)}</div><div><b>${i.name}</b><small>${Number(i.kg||0).toFixed(2).replace('.',',')} kg · ${formatLiters(i.l)} L${i.note?` · ${i.note}`:''}</small><span class="v158-item-status ${cls}"><span>${status}</span>${statusBag?`<span> · ${statusBag}</span>`:''}</span></div><select class="pack-v12-bagselect ${preview?'v154-preview-select':''}" data-bagitem="${i.id}" ${i.have?'':'disabled'}>${bagOptions(i.bag)}</select>${i.custom?`<button class="v152-custom-delete" data-delete-custom="${i.id}" type="button" title="Eigenen Gegenstand löschen">×</button>`:'<span class="menu-dots">⋮</span>'}</div>`}).join('')}</div>`}).join('')||'<div class="muted" style="font-size:11px;padding:12px">Keine Gegenstände in dieser Ansicht.</div>';
    box.querySelectorAll('[data-have]').forEach(b=>b.onclick=()=>{const base=packItems.find(x=>x.id===b.dataset.have);if(!base)return;base.have=!base.have;if(!base.have)base.bag='';packProposal=null;invalidateAppliedPack();packPersist();renderPackPrototype();renderOverviewDashboard()});
    box.querySelectorAll('[data-bagitem]').forEach(el=>el.onchange=()=>{const target=preview?packProposal?.items?.find(x=>x.id===el.dataset.bagitem):packItems.find(x=>x.id===el.dataset.bagitem);if(!target)return;if(el.value&&!isMountedV158(el.value)){renderPackPrototype();return}if(el.value){const src=preview?packProposal.items:packItems,st=bagStats(el.value,src),existing=target.bag===el.value?target.l:0;if(st.l-existing+target.l>st.cap+1e-6){packToast(`${packBags[el.value].name}: zu wenig Platz`);renderPackPrototype();return}}target.bag=el.value;if(preview){if(typeof v154RefreshProposalUnassigned==='function')v154RefreshProposalUnassigned();renderPackPrototype()}else{invalidateAppliedPack();packPersist();renderPackPrototype();renderOverviewDashboard()}});
    box.querySelectorAll('[data-delete-custom]').forEach(btn=>btn.onclick=()=>{const idx=packItems.findIndex(x=>x.id===btn.dataset.deleteCustom&&x.custom);if(idx<0)return;const name=packItems[idx].name;packItems.splice(idx,1);packProposal=null;packPersist();renderPackPrototype();renderOverviewDashboard();packToast(`${name} entfernt`)});
  };

  function renderBagDockV158(){
    const box=document.getElementById('packBagDock');if(!box)return;
    box.innerHTML=Object.entries(packBags).map(([id,b])=>{const on=isMountedV158(id),st=getBag(id),g=bagGuide[id]||{short:'Ausrüstung',why:''},sizes=b.sizes||[b.size];return `<div class="v158-bag-card ${on?'mounted':'unmounted'} ${selectedPackBagV15===id?'selected':''}" data-v158-bag-card="${id}"><button class="v158-bag-icon" type="button" data-v158-open-bag="${id}" aria-label="${b.name} öffnen">${bagIconSvg(id)}</button><div class="v158-bag-main"><button type="button" data-v158-open-bag="${id}"><b>${b.name}</b><small>${g.short}</small><strong>${on?(st.items.length?`${st.items.length} <span>Teile</span> · ${formatLiters(st.l)}/${formatLiters(st.cap)} L`:'montiert · leer'):'nicht montiert'}</strong></button></div><div class="v158-bag-actions"><select data-v158-size="${id}" ${on?'':'disabled'} aria-label="Größe ${b.name}">${sizes.map(v=>`<option value="${v}" ${Number(b.size)===Number(v)?'selected':''}>${formatLiters(v*(b.qty||1))} L</option>`).join('')}</select><button type="button" class="v158-bag-toggle" data-v158-toggle-bag="${id}">${on?'Entfernen':'+ Hinzufügen'}</button></div></div>`}).join('');
    box.querySelectorAll('[data-v158-toggle-bag]').forEach(btn=>btn.onclick=()=>setMountedV158(btn.dataset.v158ToggleBag,!isMountedV158(btn.dataset.v158ToggleBag)));
    box.querySelectorAll('[data-v158-open-bag]').forEach(btn=>btn.onclick=()=>{const id=btn.dataset.v158OpenBag;if(!isMountedV158(id)){setMountedV158(id,true)}selectedPackBagV15=id;renderPackBagDetailV15(id);renderBagDockV158()});
    box.querySelectorAll('[data-v158-size]').forEach(sel=>sel.onchange=()=>{const id=sel.dataset.v158Size,v=Number(sel.value);if(packBags[id]?.sizes?.includes(v)){packBags[id].size=v;packProposal=null;invalidateAppliedPack();packPersist();renderPackPrototype();renderOverviewDashboard();packToast(`${packBags[id].name}: ${formatLiters(bagCapacity(id))} L`)}});
  }

  renderPackFillGrid=function(){
    const box=document.getElementById('packFillGrid');if(!box)return;const items=packProposal?.items||packItems,ids=mountedIdsV158();
    box.innerHTML=ids.length?ids.map(id=>{const b=packBags[id],st=getBag(id),full=st.pct>=100;return `<div class="pack-v13-fillcard ${st.over?'pack-v12-over':''} ${full?'full':''} ${!st.items.length?'empty':''} ${selectedPackBagV15===id?'selected':''}" data-bag-id="${id}"><div class="bag-svg">${bagIconSvg(id)}</div><b>${b.name}</b><strong>${formatLiters(st.l)} / ${formatLiters(st.cap)} L</strong><div class="bar"><i style="width:${Math.min(100,st.pct)}%"></i></div><small>${st.items.length?`${st.pct}% · ${st.items.length} <span>Teile</span>`:'leer · bereit'}</small></div>`}).join(''):'<div class="v154-pack-empty-note">Noch keine Tasche am Bike montiert.</div>';
    const u=document.getElementById('packUnassigned'),ua=items.filter(x=>x.needed&&x.have&&!x.bag);if(u)u.innerHTML=ua.length?`<div class="pack-v13-unassigned-list">${ua.map(x=>`<span>${x.name}</span>`).join('')}</div>`:'<div class="muted" style="font-size:9px;margin-top:5px">Alles ist einer montierten Tasche zugewiesen.</div>';
    bindPackBagClicksV15();
  };

  function bindBikeV158(){
    Object.keys(packBags).forEach(id=>{const g=document.getElementById(`packBike-${id}`);if(g){g.style.cursor=isMountedV158(id)?'pointer':'default';g.onclick=isMountedV158(id)?()=>{selectedPackBagV15=id;renderPackBagDetailV15(id);renderBagDockV158()}:null}});
    document.querySelectorAll('[data-pack-bag]').forEach(x=>{const id=x.dataset.packBag;if(!id)return;x.onclick=()=>{if(isMountedV158(id)){selectedPackBagV15=id;renderPackBagDetailV15(id);renderBagDockV158()}}});
  }
  renderPackBike=function(){
    const items=packProposal?.items||packItems;Object.keys(packBags).forEach(id=>{const mounted=isMountedV158(id),st=getBag(id),layer=document.getElementById(`packBike-${id}`),lab=document.getElementById(`packBikeLabel-${id}`);if(layer){layer.classList.remove('v154-hidden');layer.classList.toggle('v158-bike-unmounted',!mounted);layer.classList.toggle('v158-empty-bag',mounted&&!st.items.length)}document.querySelectorAll(`[data-pack-bag="${id}"]`).forEach(el=>{el.removeAttribute('hidden');el.classList.toggle('v158-unmounted',!mounted);el.classList.toggle('selected',selectedPackBagV15===id)});if(lab)lab.textContent=st.items.length?`${formatLiters(st.l)} / ${formatLiters(st.cap)} L · ${st.pct}%`:`leer · ${formatLiters(st.cap)} L`});
    const mode=document.querySelector('.packBikeModeV154');if(mode){mode.textContent=packProposal?'Auto-Pack Vorschau':'Montierte Taschen';mode.classList.toggle('preview',!!packProposal)}bindBikeV158();
  };

  renderPackBagDetailV15=function(id){
    const el=document.getElementById('packBagDetail');if(!el)return;if(!id||!isMountedV158(id)){selectedPackBagV15='';el.hidden=true;return}selectedPackBagV15=id;el.hidden=false;const st=getBag(id),b=st,g=bagGuide[id]||{short:'Ausrüstung',why:''},pct=Math.min(100,st.pct);
    const rows=st.items.map(i=>{const access=i.access==='high'?'schnell erreichbar':i.access==='low'?'selten benötigt':'normaler Zugriff';return `<div class="v158-bag-item-row"><span class="v158-bag-item-icon">${itemIcon(i.id,i.cat)}</span><div><b>${i.name}</b><small>${Number(i.kg||0).toFixed(2).replace('.',',')} kg · ${formatLiters(i.l)} L · <span>${access}</span></small></div><select data-v158-detail-move="${i.id}">${bagOptions(id)}</select></div>`}).join('');
    el.innerHTML=`<div class="v158-bag-detail-head"><div class="v158-bag-detail-icon">${bagIconSvg(id)}</div><div><div class="eyebrow">Tascheninhalt</div><h3>${b.name}</h3><p>${g.why}</p></div><button class="v158-close" type="button" id="closeBagDetailV158" aria-label="Tascheninhalt schließen">×</button></div><div class="v158-bag-detail-kpis"><div><small>Volumen</small><b>${formatLiters(st.l)} / ${formatLiters(st.cap)} L</b></div><div><small>Gewicht</small><b>${st.kg.toFixed(1).replace('.',',')} kg</b></div><div><small>Inhalt</small><b>${st.items.length} <span>Teile</span></b></div></div><div class="v158-bag-detail-bar"><i style="width:${pct}%"></i></div><div class="v158-bag-detail-guide">Gut geeignet für: <b>${g.short}</b>${st.over?' · ⚠ Kapazität überschritten':''}</div><div class="v158-bag-content"><div class="v158-bag-content-title"><b>Was ist drin?</b><span>direkt verschiebbar</span></div>${rows||'<div class="v158-empty-content">Diese Tasche ist montiert, aber noch leer. Weise unten einen Gegenstand zu oder nutze Auto-Pack.</div>'}</div><div class="v158-bag-detail-actions"><button type="button" data-v158-scroll-items>Gegenstände anzeigen</button><button type="button" class="remove" data-v158-remove-detail="${id}">Tasche entfernen</button></div>`;
    document.getElementById('closeBagDetailV158')?.addEventListener('click',()=>{selectedPackBagV15='';el.hidden=true;renderBagDockV158();renderPackBike();renderPackFillGrid()});
    el.querySelectorAll('[data-v158-detail-move]').forEach(sel=>sel.onchange=()=>ROAMPack.moveItem(sel.dataset.v158DetailMove,sel.value));
    el.querySelector('[data-v158-remove-detail]')?.addEventListener('click',()=>setMountedV158(id,false));
    el.querySelector('[data-v158-scroll-items]')?.addEventListener('click',()=>document.querySelector('.v158-pack-have')?.scrollIntoView({behavior:'smooth',block:'start'}));
    document.querySelectorAll('[data-pack-bag]').forEach(x=>x.classList.toggle('selected',x.dataset.packBag===id));document.querySelectorAll('.pack-v13-fillcard').forEach(x=>x.classList.toggle('selected',x.dataset.bagId===id));
  };

  renderPackSummary=function(){
    const items=packProposal?.items||packItems,rel=relevantPackItems(items),assigned=rel.filter(x=>x.bag),total=rel.reduce((a,x)=>a+x.kg,0),assignedKg=assigned.reduce((a,x)=>a+x.kg,0),bal=packBalance(items),mounted=mountedIdsV158().length,cov=rel.length?Math.round(assigned.length/rel.length*100):0;const pw=document.getElementById('packWeight');if(pw)pw.textContent=`${assignedKg.toFixed(1).replace('.',',')} / ${total.toFixed(1).replace('.',',')} kg`;const fb=document.getElementById('frontBalance'),rb=document.getElementById('rearBalance'),bb=document.getElementById('balanceBar');if(fb)fb.textContent=`${bal.front}% vorne`;if(rb)rb.textContent=`${bal.rear}% hinten`;if(bb)bb.style.gridTemplateColumns=`${bal.front}fr ${bal.rear}fr`;const sb=document.getElementById('packStatBags'),si=document.getElementById('packStatItems'),sc=document.getElementById('packStatCoverage');if(sb)sb.textContent=mounted;if(si)si.textContent=assigned.length;if(sc)sc.textContent=`${cov}%`;const meta=document.getElementById('packMeta');if(meta)meta.textContent=`${assignedKg.toFixed(1).replace('.',',')} / ${total.toFixed(1).replace('.',',')} kg verteilt · ${mounted} Taschen montiert · Balance ${bal.front} / ${bal.rear}`;
  };

  function renderQuickStatsV158(){const items=packProposal?.items||packItems,need=items.filter(x=>x.needed).length,missing=items.filter(x=>x.needed&&!x.have).length,packed=items.filter(x=>x.needed&&x.have&&x.bag).length,total=items.filter(x=>x.needed&&x.have).reduce((s,x)=>s+(Number(x.kg)||0),0);const set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v};set('v158NeedKpi',need);set('v158MissingKpi',missing);set('v158PackedKpi',`${packed}/${items.filter(x=>x.needed&&x.have).length}`);set('v158WeightKpi',`${total.toFixed(1).replace('.',',')} kg`)}

  // Add exact translations for the new pack interface. Dynamic values are kept as separate text nodes where practical.
  if(typeof ROAM_V152_TRANSLATIONS==='object')Object.assign(ROAM_V152_TRANSLATIONS,{
    'Benötigt':['Required','Necesario'],'Fehlt':['Missing','Falta'],'Gepackt':['Packed','Empacado'],'Gewicht':['Weight','Peso'],'Alle':['All','Todo'],'Vorhanden':['Available','Disponible'],'Ohne Tasche':['No bag','Sin bolsa'],'Bike & Taschen':['Bike & bags','Bici y bolsas'],'Taschen-Setup':['Bag setup','Configuración de bolsas'],'Welche Taschen sind am Bike?':['Which bags are on the bike?','¿Qué bolsas están en la bici?'],'Hinzufügen, entfernen und Größe wählen':['Add, remove and choose size','Añadir, quitar y elegir tamaño'],'Entfernen':['Remove','Quitar'],'+ Hinzufügen':['+ Add','+ Añadir'],'Montierte Taschen':['Mounted bags','Bolsas montadas'],'Füllstand der montierten Taschen':['Mounted bag fill levels','Nivel de las bolsas montadas'],'Noch ohne Tasche':['Not packed yet','Aún sin bolsa'],'Tascheninhalt':['Bag contents','Contenido de la bolsa'],'Volumen':['Volume','Volumen'],'Inhalt':['Contents','Contenido'],'Was ist drin?':['What is inside?','¿Qué hay dentro?'],'direkt verschiebbar':['move directly','mover directamente'],'Gegenstände anzeigen':['Show items','Mostrar objetos'],'Tasche entfernen':['Remove bag','Quitar bolsa'],'Diese Tasche ist montiert, aber noch leer. Weise unten einen Gegenstand zu oder nutze Auto-Pack.':['This bag is mounted but still empty. Assign an item below or use Auto-Pack.','Esta bolsa está montada pero aún vacía. Asigna un objeto abajo o usa Auto-Pack.'],'Alles ist einer montierten Tasche zugewiesen.':['Everything is assigned to a mounted bag.','Todo está asignado a una bolsa montada.'],'Noch keine Tasche am Bike montiert.':['No bag is mounted on the bike yet.','Aún no hay ninguna bolsa montada en la bici.'],'nicht montiert':['not mounted','no montada'],'montiert · leer':['mounted · empty','montada · vacía'],'leer · bereit':['empty · ready','vacía · lista'],'Gut geeignet für:':['Well suited for:','Ideal para:'],'Keine Gegenstände in dieser Ansicht.':['No items in this view.','No hay objetos en esta vista.'],
    'Inhalte leeren':['Empty contents','Vaciar contenido'],'Vorschau':['Preview','Vista previa'],'Teile':['items','objetos'],'benötigt':['required','necesario'],'schnell erreichbar':['quick access','acceso rápido'],'selten benötigt':['rarely needed','uso poco frecuente'],'normaler Zugriff':['normal access','acceso normal'],'Kapazität überschritten':['over capacity','capacidad superada'],
    'Montiere zuerst deine Taschen. Tippe danach direkt am Bike oder auf eine Tasche, um Inhalt, Füllstand und Position zu prüfen.':['Mount your bags first. Then tap a bag on the bike or in the list to review contents, fill level and position.','Monta primero las bolsas. Después toca una bolsa en la bici o en la lista para revisar contenido, nivel de llenado y posición.'],
    'Tasche direkt am Bike antippen → Inhalt öffnen → Gegenstände verschieben':['Tap a bag on the bike → open contents → move items','Toca una bolsa en la bici → abre el contenido → mueve objetos'],
    'Kleidung · Schlafsachen':['Clothing · sleep gear','Ropa · equipo de dormir'],'Werkzeug · Essen · Powerbank':['Tools · food · power bank','Herramientas · comida · batería externa'],'Snacks · Geld · Elektronik':['Snacks · money · electronics','Snacks · dinero · electrónica'],'Jacke · Schlafsack · leichte Teile':['Jacket · sleeping bag · light gear','Chaqueta · saco de dormir · equipo ligero'],'Drybags · Camping':['Dry bags · camping','Bolsas estancas · camping'],
    'Leicht und voluminös – gut für Dinge, die unterwegs selten gebraucht werden.':['Light and bulky — good for items you rarely need while riding.','Ligero y voluminoso: ideal para cosas que necesitas poco durante la marcha.'],'Schwere, kompakte Ausrüstung sitzt hier zentral und fahrstabil.':['Heavy, compact gear stays central and stable here.','El equipo pesado y compacto queda aquí centrado y estable.'],'Für kleine Dinge, die du während der Fahrt schnell erreichen willst.':['For small items you want to reach quickly while riding.','Para objetos pequeños que quieres alcanzar rápidamente durante la marcha.'],'Ideal für leichte, voluminöse Ausrüstung an der Front.':['Ideal for light, bulky gear at the front.','Ideal para equipo ligero y voluminoso en la parte delantera.'],'Zusätzlicher Stauraum an der Gabel – möglichst links und rechts ausgewogen beladen.':['Extra fork storage — keep left and right loads balanced.','Espacio extra en la horquilla: reparte la carga entre izquierda y derecha.'],'Wasser bleibt tief, zentral und jederzeit erreichbar.':['Water stays low, central and easy to reach.','El agua queda baja, centrada y siempre accesible.'],
    'Schlafsack':['Sleeping bag','Saco de dormir'],'Zelt':['Tent','Tienda'],'Isomatte':['Sleeping mat','Esterilla'],'Trikot / Shirt':['Jersey / shirt','Maillot / camiseta'],'Shorts / Hose':['Shorts / trousers','Shorts / pantalón'],'Unterwäsche':['Underwear','Ropa interior'],'Socken':['Socks','Calcetines'],'Regenjacke':['Rain jacket','Chaqueta impermeable'],'Daunenjacke':['Down jacket','Chaqueta de plumas'],'Sandalen':['Sandals','Sandalias'],'Nahrung':['Food','Comida'],'Snacks':['Snacks','Snacks'],'Kocher':['Stove','Hornillo'],'Essgeschirr':['Cookware','Vajilla'],'Fuel':['Fuel','Combustible'],'Werkzeug-Set':['Tool kit','Kit de herramientas'],'Ersatzteile':['Spare parts','Repuestos'],'Powerbank':['Power bank','Batería externa'],'Elektronik':['Electronics','Electrónica'],'Dokumente':['Documents','Documentos'],'Geld / Karte':['Cash / card','Dinero / tarjeta'],'Hygiene-Set':['Toiletries','Kit de higiene']
  });

  const oldRenderPackPrototypeV158=renderPackPrototype;
  renderPackPrototype=function(){oldRenderPackPrototypeV158();renderBagDockV158();renderQuickStatsV158();renderPackBike();renderPackFillGrid();if(selectedPackBagV15&&isMountedV158(selectedPackBagV15))renderPackBagDetailV15(selectedPackBagV15);scheduleRoamTranslation?.();document.dispatchEvent(new Event('roam:pack-rendered'))};

  document.getElementById('packItemTabs')?.addEventListener('click',e=>{const b=e.target.closest('[data-v158-item-filter]');if(!b)return;itemFilterV158=b.dataset.v158ItemFilter;document.querySelectorAll('#packItemTabs [data-v158-item-filter]').forEach(x=>x.classList.toggle('active',x===b));renderPackHave();scheduleRoamTranslation?.()});

  // Existing reset means "empty contents", not remove physical bags. This is less destructive and matches its label.
  const reset=document.getElementById('resetPack');if(reset)reset.textContent='Inhalte leeren';
  const packTools=document.querySelector('#screen-pack .v15-bike-tools');if(packTools)packTools.innerHTML='<span class="v154-pack-mode" class="v154-pack-mode packBikeModeV154">Montierte Taschen</span><span class="muted">Tasche direkt am Bike antippen → Inhalt öffnen → Gegenstände verschieben</span>';

  renderPackPrototype();renderOverviewDashboard();
})();

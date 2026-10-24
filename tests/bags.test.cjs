const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const http=require('node:http');
const fs=require('node:fs/promises');
const path=require('node:path');
let server,browser,base;
before(async()=>{
  const root=path.resolve(process.env.TEST_ROOT||path.join(__dirname,'..'));
  server=http.createServer(async(req,res)=>{
    try{const file=path.resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://local').pathname));
      if(!file.startsWith(root+path.sep))throw Error('outside root');
      const body=await fs.readFile(file);
      res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(body);
    }catch{res.writeHead(404);res.end()}
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));base=`http://127.0.0.1:${server.address().port}`;
  browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE_PATH?{executablePath:process.env.BROWSER_EXECUTABLE_PATH,args:['--no-sandbox','--disable-dev-shm-usage','--no-zygote','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']}: {})});
});
after(async()=>{await browser?.close();await new Promise(r=>server?server.close(r):r())});
async function fixture(file,viewport){
  const context=await browser.newContext({viewport:viewport||{width:1280,height:900}}),p=await context.newPage(),errors=[];
  p.setDefaultTimeout(5000);p.setDefaultNavigationTimeout(10000);
  p.on('pageerror',e=>errors.push(e.message));
  // These packing tests run offline: external route/map services are outside their scope.
  await p.route('**/*',route=>route.request().url().startsWith(base)?route.continue():route.abort());
  await p.goto(base+'/web-prototyp/'+file);
  await p.evaluate(()=>{
    packItems.forEach(i=>Object.assign(i,{needed:false,needOverride:true,bag:''}));
    const add=(bag,volumes)=>volumes.forEach((l,i)=>packItems.push({id:`custom-${bag}-${i}`,name:`${bag} item ${i}`,bag,l,kg:.1,cat:'clothes',needed:true,have:true,custom:true,needOverride:true,access:'low'}));
    add('saddle',[1,1,1,2]);add('frame',[1,1,1,1,1,1,1,.9]);
    packPersist();
    // Reproduce legacy contradiction: packed items, but stale false mount flags.
    localStorage.setItem('roam-pack-mounted-v158',JSON.stringify({saddle:false,frame:false,bar:true,top:false,fork:false,bottle:true,frontL:false,frontR:false,rearL:false,rearR:false}));
  });
  await p.reload();await p.evaluate(()=>{activateStoredTrip({coords:[{lat:46.7,lon:11.6,d:0},{lat:46.71,lon:11.61,d:2}],km:2,start:'Brixen',destination:'Ziel'});showScreen('pack')});await p.waitForTimeout(150);
  return {p,errors,close:async()=>{await context.close();assert.deepEqual(errors,[], 'No browser script errors')}};
}
const mode=(p,name)=>p.locator('#roam-v1516-toolbar button').filter({hasText:name}).click();
const bag=(p,id)=>p.locator(`[data-bike-layer="${id}"]`);
const visible=(p,id)=>bag(p,id).evaluate(el=>getComputedStyle(el).display!=='none'&&getComputedStyle(el).visibility!=='hidden'&&getComputedStyle(el).opacity!=='0');
for(const file of ['index.html','ROAM_Foundation_02_Bike_Visibility_Test.html']){
  test(`${file}: saddle 4 items / 5 of 14 L is visible and mounted in every view`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      assert.equal(await visible(p,'saddle'),true);
      assert.match(await p.locator('[data-v158-bag-card="saddle"]').innerText(),/4.*Teile.*5\/14 L/s);
      await bag(p,'saddle').dispatchEvent('click');
      assert.equal(await p.locator('#roam-v1516-gear .v158-bag-item-row').count(),4);
      assert.match(await p.locator('#roam-v1516-stats').innerText(),/5 \/ 14 L.*4 Teile/);
      await p.locator('#roam-v1516-close').click();
      await mode(p,'Taschen bearbeiten');
      assert.equal(await p.locator('#roam-v1516-positions button').filter({hasText:'Satteltasche'}).getAttribute('aria-pressed'),'true');
      assert.equal(await visible(p,'saddle'),true);
      assert.deepEqual(f.errors,[]);
    }finally{await f.close()}
  });
  test(`${file}: frame details show all 8 items / 7.9 of 8 L repeatedly`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      for(let i=0;i<2;i++){
        await bag(p,'frame').dispatchEvent('click');
        assert.equal(await p.locator('#roam-v1516-gear .v158-bag-item-row').count(),8);
        assert.match(await p.locator('#roam-v1516-stats').innerText(),/7,9 \/ 8 L.*8 Teile/);
        assert.equal(await p.locator('#roam-v1516-empty').count(),0);
        await p.locator('#roam-v1516-close').click();
      }
    }finally{await f.close()}
  });
  test(`${file}: used/edit/empty modes preserve assignments and show empty mounted bags only in edit`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      const initial=await p.evaluate(()=>localStorage.getItem(PACK_STATE_KEY));
      assert.equal(await visible(p,'bar'),false);
      await mode(p,'Taschen bearbeiten');assert.equal(await visible(p,'bar'),true,JSON.stringify(await p.evaluate(()=>({mounted:ROAMPack.getBag('bar')?.mounted,bag:ROAMPack.getBag('bar'),layer:(()=>{const e=document.querySelector('[data-bike-layer="bar"]');return e?{class:e.getAttribute('class'),style:e.getAttribute('style'),display:getComputedStyle(e).display,visibility:getComputedStyle(e).visibility,opacity:getComputedStyle(e).opacity,outer:e.outerHTML.slice(0,400),parent:e.parentElement?.outerHTML.slice(0,450)}:null})()}))));
      await mode(p,'Ohne Taschen');
      for(const id of ['saddle','frame','bar','top','fork','bottle'])assert.equal(await visible(p,id),false);
      assert.equal(await p.locator('#roam-v1516-modal').isVisible(),false);
      await mode(p,'Meine Taschen');assert.equal(await visible(p,'saddle'),true);assert.equal(await visible(p,'bar'),false);
      assert.equal(await p.evaluate(()=>localStorage.getItem(PACK_STATE_KEY)),initial);
    }finally{await f.close()}
  });
  test(`${file}: moving an item updates detail, overview and persisted assignments`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      await bag(p,'frame').dispatchEvent('click');
      await p.locator('#roam-v1516-gear select').first().selectOption('bar');await p.waitForTimeout(100);
      assert.equal(await p.locator('#roam-v1516-gear .v158-bag-item-row').count(),7);
      assert.match(await p.locator('[data-v158-bag-card="frame"]').innerText(),/6,9\/8 L/);
      assert.equal(await visible(p,'bar'),true);
      await p.reload();assert.equal(await p.evaluate(()=>ROAMPack.getBag('bar').items.length),1);
    }finally{await f.close()}
  });
  test(`${file}: capacity rejection and proposal moves never change committed items`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      const result=await p.evaluate(()=>{
        const initial=JSON.stringify(packItems);
        const rejected=ROAMPack.moveItem('custom-saddle-0','frame');
        packProposal={items:packItems.map(i=>({...i})),unassigned:[]};
        const accepted=ROAMPack.moveItem('custom-frame-0','bar');
        return {rejected,accepted,unchanged:initial===JSON.stringify(packItems),frame:ROAMPack.getBag('frame').l,preview:ROAMPack.getBag('frame').preview};
      });
      assert.deepEqual(result,{rejected:false,accepted:true,unchanged:true,frame:6.9,preview:true});
    }finally{await f.close()}
  });
  test(`${file}: removing a filled bag supports cancel, unassigns on confirm, and survives reload`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      await mode(p,'Taschen bearbeiten');
      p.once('dialog',d=>d.dismiss());
      await p.locator('#roam-v1516-positions button').filter({hasText:'Satteltasche'}).click();
      assert.equal(await visible(p,'saddle'),true);
      p.once('dialog',d=>d.accept());
      await p.locator('#roam-v1516-positions button').filter({hasText:'Satteltasche'}).click();
      assert.equal(await visible(p,'saddle'),false);
      await p.reload();
      assert.deepEqual(await p.evaluate(()=>({mounted:ROAMPack.isMounted('saddle'),assigned:packItems.filter(i=>i.bag==='saddle').length})),{mounted:false,assigned:0});
    }finally{await f.close()}
  });
  test(`${file}: mobile detail fits viewport and Escape closes it`,async()=>{
    const f=await fixture(file,{width:390,height:844});try{const {p}=f;
      await bag(p,'frame').dispatchEvent('click');
      assert.equal(await p.locator('#roam-v1516-modal').isVisible(),true);
      assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      if(process.env.ROAM_SCREENSHOT_DIR){await fs.mkdir(process.env.ROAM_SCREENSHOT_DIR,{recursive:true});await p.screenshot({path:path.join(process.env.ROAM_SCREENSHOT_DIR,file+'.png')})}
      await p.keyboard.press('Escape');assert.equal(await p.locator('#roam-v1516-modal').isVisible(),false);
      assert.deepEqual(f.errors,[]);
    }finally{await f.close()}
  });
  test(`${file}: editing an SVG bag by keyboard toggles once and keeps contents intact on cancel`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      await mode(p,'Taschen bearbeiten');
      p.once('dialog',d=>d.dismiss());
      await bag(p,'saddle').focus();await p.keyboard.press('Enter');
      assert.equal(await p.evaluate(()=>ROAMPack.isMounted('saddle')),true);
      await bag(p,'bar').focus();await p.keyboard.press(' ');
      assert.equal(await p.evaluate(()=>ROAMPack.isMounted('bar')),false,JSON.stringify(await p.evaluate(()=>({mode:ROAMFoundation03.snapshot().mode,mounted:ROAMPack.isMounted('bar'),layer:(()=>{const e=document.querySelector('[data-bike-layer="bar"]');return e?{style:e.getAttribute('style'),tabindex:e.getAttribute('tabindex')}:null})()}))));
      assert.equal(await visible(p,'bar'),false);
      await p.locator('#roam-v1516-positions button').filter({hasText:'Lenkertasche'}).click();
      assert.equal(await visible(p,'bar'),true);
    }finally{await f.close()}
  });
  test(`${file}: cargo controls use the central mounted state and retain removal after reload`,async()=>{
    const f=await fixture(file);try{const {p}=f;
      await mode(p,'Taschen bearbeiten');
      await p.locator('.v1589-cargo-hotspot.rearL').click();
      assert.equal(await p.evaluate(()=>ROAMPack.isMounted('rearL')),true);
      await p.locator('.v1589-cargo-hotspot.rearL').click();
      assert.equal(await p.evaluate(()=>ROAMPack.isMounted('rearL')),false);
      await p.reload();assert.equal(await p.evaluate(()=>ROAMPack.isMounted('rearL')),false);
      await p.evaluate(()=>showScreen('pack'));await mode(p,'Taschen bearbeiten');
      await p.locator('#roam-v1516-positions button').filter({hasText:'Gabeltaschen'}).click();
      assert.deepEqual(await p.evaluate(()=>['frontL','frontR','fork'].map(ROAMPack.isMounted)),[true,true,false]);
      await p.locator('#roam-v1516-positions button').filter({hasText:'Gabeltaschen'}).click();
      assert.deepEqual(await p.evaluate(()=>['frontL','frontR','fork'].map(ROAMPack.isMounted)),[false,false,false]);
    }finally{await f.close()}
  });

}

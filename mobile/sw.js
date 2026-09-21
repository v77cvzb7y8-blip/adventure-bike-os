const C='abo-mobile-0-5-0-5-v1';
const APP_PREFIX='abo-mobile-';

self.addEventListener('install',event=>{
  self.skipWaiting();
  event.waitUntil(
    caches.open(C).then(cache=>cache.addAll([
      './manifest.webmanifest'
    ]))
  );
});

self.addEventListener('activate',event=>{
  event.waitUntil((async()=>{
    const keys=await caches.keys();
    await Promise.all(
      keys.filter(k=>k.startsWith(APP_PREFIX)&&k!==C).map(k=>caches.delete(k))
    );
    await self.clients.claim();
  })());
});

async function networkFirst(request){
  try{
    const fresh=await fetch(request,{cache:'no-store'});
    if(fresh && fresh.ok){
      const cache=await caches.open(C);
      cache.put(request,fresh.clone()).catch(()=>{});
    }
    return fresh;
  }catch(err){
    const cache=await caches.open(C);
    const cached=await cache.match(request);
    if(cached)return cached;
    throw err;
  }
}

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;

  const url=new URL(event.request.url);
  const sameOrigin=url.origin===self.location.origin;
  const isNavigation=event.request.mode==='navigate';
  const isAppShell=sameOrigin && (
    url.pathname.endsWith('/mobile/') ||
    url.pathname.endsWith('/mobile/index.html') ||
    url.pathname.endsWith('/mobile/sw.js')
  );

  if(isNavigation || isAppShell){
    event.respondWith(networkFirst(event.request));
    return;
  }

  if(sameOrigin){
    event.respondWith((async()=>{
      const cache=await caches.open(C);
      const hit=await cache.match(event.request);
      if(hit)return hit;
      try{
        const fresh=await fetch(event.request);
        if(fresh && fresh.ok)cache.put(event.request,fresh.clone()).catch(()=>{});
        return fresh;
      }catch(err){
        throw err;
      }
    })());
  }
});

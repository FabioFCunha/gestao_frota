const CACHE='transfrota-pwa-v1';
const ROOT='/api/driver/app/';
const ASSETS=['app.js','rules.mjs','style.css','manifest.webmanifest','icon-192.png','icon-512.png'].map(p=>ROOT+p);
self.addEventListener('install',event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)));
});
self.addEventListener('activate',event=>{
  event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('transfrota-pwa-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));
});
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin)return;
  if(url.pathname===ROOT){
    event.respondWith(fetch(event.request).then(async response=>{
      // Only the generic app shell: never cache a redirect, login form or API data.
      if(response.ok&&!response.redirected&&response.headers.get('Content-Type')?.includes('text/html')){
        const cache=await caches.open(CACHE);await cache.put(ROOT,response.clone());
      }
      return response;
    }).catch(async()=>await caches.match(ROOT)||new Response('Conecte à internet para abrir o aplicativo pela primeira vez.',{status:503,headers:{'Content-Type':'text/plain;charset=utf-8'}})));
  }else if(ASSETS.includes(url.pathname)){
    event.respondWith(fetch(event.request).then(async response=>{
      if(response.ok){const cache=await caches.open(CACHE);await cache.put(url.pathname,response.clone());}
      return response;
    }).catch(()=>caches.match(url.pathname)));
  }
});

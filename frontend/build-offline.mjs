// Cache only public application assets. API responses, accounts and GPS are excluded.
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const html=await readFile(new URL('./dist/index.html',import.meta.url),'utf8');
const assets=(await readdir(new URL('./dist/assets/',import.meta.url))).map(name=>'/assets/'+name);
const version=createHash('sha256').update(html+assets.join(',')).digest('hex').slice(0,16);
const urls=['/index.html','/manifest.webmanifest','/icon.svg',...assets];
const source=`const CACHE='metro-shell-${version}';
const ASSETS=${JSON.stringify(urls)};
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(ASSETS)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('metro-shell-')&&key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/')||url.pathname.startsWith('/ws/'))return;
  if(event.request.mode==='navigate'&&(url.pathname==='/'||url.pathname==='/index.html')){
    event.respondWith(fetch(event.request).catch(()=>caches.match('/index.html')));return;
  }
  if(ASSETS.includes(url.pathname))event.respondWith(caches.open(CACHE).then(cache=>cache.match(url.pathname)).then(saved=>saved||fetch(event.request)));
});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(windows=>windows[0]?windows[0].focus():self.clients.openWindow('/')));});
`;
await writeFile(new URL('./dist/sw.js',import.meta.url),source);
console.log('Offline shell generated:',version);

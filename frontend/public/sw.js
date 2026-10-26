// ASSETS and CACHE are injected by Vite. API data and authenticated responses are never cached.
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)))
})
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('lomba-radar-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()))
})
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url)
  if (event.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || !ASSETS.includes(url.pathname)) {
    if (event.request.mode === 'navigate' && url.origin === location.origin && !url.pathname.startsWith('/api/')) {
      event.respondWith(fetch(event.request).catch(() => caches.match('/index.html')))
    }
    return
  }
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)))
})

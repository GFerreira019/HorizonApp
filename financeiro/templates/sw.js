const CACHE_NAME = 'horizonapp-static-v4';

// Recursos estáticos fundamentais (Cache First / Precaching)
const STATIC_RESOURCES = [
  '/manifest.json',
];

// Instalação do Service Worker
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_RESOURCES);
    })
  );
});

// Ativação do Service Worker e limpeza de caches antigos
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// Estratégia de Fetch
self.addEventListener('fetch', (event) => {
  // Ignorar requisições com esquemas não suportados (ex: chrome-extension://)
  if (!event.request.url.startsWith('http')) {
    return;
  }

  // Somente lidar com requisições GET
  if (event.request.method !== 'GET') {
    return;
  }

  // Estratégia de Fetch:
  // - Recursos estáticos (/static/, CDNs): Network First com cache fallback
  // - Páginas HTML dinâmicas do Django: Network Only (sem cache)
  //   Cachear HTMLs do Django causa bugs graves: tags de template como
  //   {{ variavel }} são renderizadas no servidor e se tornam texto literal
  //   quando servidas a partir do cache do Service Worker.

  const url = new URL(event.request.url);
  const isStaticResource = url.pathname.startsWith('/static/')
    || url.pathname === '/manifest.json'
    || url.origin !== self.location.origin;  // CDNs externas

  if (!isStaticResource) {
    // Páginas dinâmicas: sempre buscar da rede, sem fallback de cache
    return;
  }

  // Recursos estáticos: Network First com fallback de cache (offline)
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        return caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, networkResponse.clone());
          return networkResponse;
        });
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});

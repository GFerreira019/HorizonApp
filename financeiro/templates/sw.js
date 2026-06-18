const CACHE_NAME = 'horizonapp-static-v2';
const DYNAMIC_CACHE_NAME = 'horizonapp-dynamic-v2';

// Recursos estáticos fundamentais (Cache First)
const STATIC_RESOURCES = [
  '/',
  '/manifest.json',
  // Arquivos estáticos do projeto poderão ser cacheados na requisição.
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
          .filter((name) => name !== CACHE_NAME && name !== DYNAMIC_CACHE_NAME)
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

  const url = new URL(event.request.url);

  // Somente lidar com requisições GET
  if (event.request.method !== 'GET') {
    return;
  }

  // Se a requisição for para o diretório de estáticos (/static/), aplica Cache First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then((cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }
        return fetch(event.request).then((networkResponse) => {
          return caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        });
      })
    );
  } else {
    // Para rotas do Django (dinâmicas), aplica Network First
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          return caches.open(DYNAMIC_CACHE_NAME).then((cache) => {
            cache.put(event.request, networkResponse.clone());
            return networkResponse;
          });
        })
        .catch(() => {
          // Fallback para o cache em caso de falha de rede
          return caches.match(event.request);
        })
    );
  }
});

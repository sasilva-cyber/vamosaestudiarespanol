(() => {
  'use strict';

  const track = document.querySelector('#popular-carousel-track');
  if (!track) return;

  const previous = document.querySelector('[data-carousel-prev]');
  const next = document.querySelector('[data-carousel-next]');
  const pause = document.querySelector('[data-carousel-pause]');
  const status = document.querySelector('#popular-carousel-status');
  const catalogNode = document.querySelector('#popular-carousel-catalog');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  let catalog = [];
  try {
    catalog = JSON.parse(catalogNode?.textContent || '[]');
  } catch (_) {
    catalog = [];
  }

  let current = 0;
  let timer = null;
  let userPaused = false;
  let interactionPaused = false;

  const normalizePath = (value) => {
    try {
      if (/^https?:\/\//i.test(value || '')) return new URL(value).pathname;
    } catch (_) {}
    return String(value || '').split('?')[0].split('#')[0];
  };

  const visibleCount = () => {
    if (window.innerWidth <= 520) return 1;
    if (window.innerWidth <= 780) return 2;
    if (window.innerWidth <= 1080) return 3;
    return 4;
  };

  const cards = () => Array.from(track.querySelectorAll('.popular-carousel__card'));

  function maxStart() {
    return Math.max(0, cards().length - visibleCount());
  }

  function goTo(index, smooth = true) {
    const items = cards();
    if (!items.length) return;
    current = Math.max(0, Math.min(index, maxStart()));
    const target = items[current];
    track.scrollTo({
      left: target.offsetLeft - track.offsetLeft,
      behavior: smooth && !reducedMotion.matches ? 'smooth' : 'auto'
    });
  }

  function stopTimer() {
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  function startTimer() {
    stopTimer();
    if (reducedMotion.matches || userPaused || interactionPaused || maxStart() === 0) return;
    timer = window.setInterval(() => {
      const nextIndex = current >= maxStart() ? 0 : current + 1;
      goTo(nextIndex);
    }, 4600);
  }

  function syncPauseButton() {
    if (!pause) return;
    pause.textContent = userPaused ? '▶' : '❚❚';
    pause.setAttribute('aria-label', userPaused ? 'Reproduzir carrossel' : 'Pausar carrossel');
    pause.setAttribute('aria-pressed', String(userPaused));
  }

  previous?.addEventListener('click', () => {
    goTo(current <= 0 ? maxStart() : current - 1);
    startTimer();
  });

  next?.addEventListener('click', () => {
    goTo(current >= maxStart() ? 0 : current + 1);
    startTimer();
  });

  pause?.addEventListener('click', () => {
    userPaused = !userPaused;
    syncPauseButton();
    startTimer();
  });

  track.addEventListener('mouseenter', () => {
    interactionPaused = true;
    startTimer();
  });
  track.addEventListener('mouseleave', () => {
    interactionPaused = false;
    startTimer();
  });
  track.addEventListener('focusin', () => {
    interactionPaused = true;
    startTimer();
  });
  track.addEventListener('focusout', () => {
    interactionPaused = false;
    startTimer();
  });

  window.addEventListener('resize', () => {
    goTo(Math.min(current, maxStart()), false);
    startTimer();
  });

  document.addEventListener('visibilitychange', () => {
    interactionPaused = document.hidden;
    startTimer();
  });

  reducedMotion.addEventListener?.('change', startTimer);

  function createCard(item, index) {
    const link = document.createElement('a');
    link.className = 'popular-carousel__card';
    link.href = item.href || item.path || '#';
    link.setAttribute('aria-label', `Ler ${item.title || 'postagem'}`);

    const media = document.createElement('span');
    media.className = 'popular-carousel__media';
    if (item.image) {
      const image = document.createElement('img');
      image.src = item.image;
      image.alt = '';
      image.loading = index < 4 ? 'eager' : 'lazy';
      image.decoding = 'async';
      media.appendChild(image);
    } else {
      const placeholder = document.createElement('span');
      placeholder.className = 'media-placeholder';
      placeholder.setAttribute('aria-hidden', 'true');
      placeholder.textContent = 'Ñ';
      media.appendChild(placeholder);
    }

    const caption = document.createElement('span');
    caption.className = 'popular-carousel__caption';

    const meta = document.createElement('span');
    meta.className = 'popular-carousel__meta';
    const category = document.createElement('span');
    category.textContent = item.category || 'Espanhol';
    const views = document.createElement('span');
    views.className = 'popular-carousel__views';
    views.textContent = Number(item.views || 0) > 0
      ? `${Number(item.views).toLocaleString('pt-BR')} visualizações`
      : 'Em destaque';
    meta.append(category, views);

    const title = document.createElement('h2');
    title.textContent = item.title || 'Postagem';
    caption.append(meta, title);
    link.append(media, caption);
    return link;
  }

  async function loadMostViewed() {
    const baseUrl = String(window.VAE_BLOG?.supabaseUrl || '').replace(/\/+$/, '');
    const key = String(window.VAE_BLOG?.supabaseKey || '');
    if (!baseUrl || !key || !catalog.length) return;

    try {
      const response = await fetch(`${baseUrl}/rest/v1/rpc/get_popular_blog_posts`, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          apikey: key
        },
        body: JSON.stringify({ p_limit: 10 }),
        cache: 'no-store'
      });
      if (!response.ok) throw new Error(`Supabase ${response.status}`);
      const data = await response.json();

      let popular = [];
      if (Array.isArray(data) && data.length === 1 && Array.isArray(data[0]?.posts)) {
        popular = data[0].posts;
      } else if (Array.isArray(data?.posts)) {
        popular = data.posts;
      } else if (Array.isArray(data)) {
        popular = data;
      }
      if (!popular.length) return;

      const byPath = new Map(catalog.map((item) => [normalizePath(item.path), item]));
      const selected = [];
      const used = new Set();

      popular.forEach((post) => {
        const path = normalizePath(post.path || post.url);
        const item = byPath.get(path);
        if (!item || used.has(path)) return;
        selected.push({ ...item, views: Number(post.views || 0) });
        used.add(path);
      });

      for (const item of catalog) {
        const path = normalizePath(item.path);
        if (selected.length >= 10) break;
        if (used.has(path)) continue;
        selected.push(item);
        used.add(path);
      }

      if (!selected.length) return;
      stopTimer();
      track.replaceChildren(...selected.map(createCard));
      current = 0;
      goTo(0, false);
      if (status) status.innerHTML = '<strong>Mais visualizadas</strong> · ordem atualizada automaticamente pelas leituras do site';
      startTimer();
    } catch (_) {
      if (status) status.textContent = 'Destaques editoriais · atualização automática disponível no domínio oficial';
    }
  }

  syncPauseButton();
  startTimer();
  loadMostViewed();
})();

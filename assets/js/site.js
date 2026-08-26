(() => {
  'use strict';

  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function toast(message) {
    const el = qs('#site-toast');
    if (!el) return;
    el.textContent = message;
    el.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove('show'), 2600);
  }

  const menuButton = qs('.menu-toggle');
  const menu = qs('#main-nav');
  if (menuButton && menu) {
    menuButton.addEventListener('click', () => {
      const open = menu.classList.toggle('open');
      menuButton.setAttribute('aria-expanded', String(open));
    });
    qsa('a', menu).forEach((link) => link.addEventListener('click', () => {
      menu.classList.remove('open');
      menuButton.setAttribute('aria-expanded', 'false');
    }));
  }

  const archive = qs('#archive-select');
  archive?.addEventListener('change', () => {
    if (archive.value) window.location.href = archive.value;
  });

  async function copyLink(url) {
    try {
      await navigator.clipboard.writeText(url);
      toast('Link copiado para a área de transferência.');
    } catch (_) {
      const field = document.createElement('textarea');
      field.value = url;
      field.setAttribute('readonly', '');
      field.style.position = 'fixed';
      field.style.opacity = '0';
      document.body.appendChild(field);
      field.select();
      document.execCommand('copy');
      field.remove();
      toast('Link copiado para a área de transferência.');
    }
  }

  function openShare(url) {
    window.open(url, '_blank', 'noopener,noreferrer,width=760,height=640');
  }

  qsa('[data-share]').forEach((button) => {
    button.addEventListener('click', async () => {
      const network = button.dataset.share;
      const url = window.location.href;
      const title = document.title;
      const encodedUrl = encodeURIComponent(url);
      const encodedTitle = encodeURIComponent(title);

      if (network === 'whatsapp') {
        openShare(`https://wa.me/?text=${encodedTitle}%20${encodedUrl}`);
      } else if (network === 'facebook') {
        openShare(`https://www.facebook.com/sharer/sharer.php?u=${encodedUrl}`);
      } else if (network === 'pinterest') {
        const image = encodeURIComponent(button.dataset.image || '');
        openShare(`https://pinterest.com/pin/create/button/?url=${encodedUrl}&description=${encodedTitle}${image ? `&media=${image}` : ''}`);
      } else if (network === 'instagram') {
        if (navigator.share) {
          try {
            await navigator.share({ title, text: title, url });
          } catch (error) {
            if (error?.name !== 'AbortError') await copyLink(url);
          }
        } else {
          await copyLink(url);
          toast('Link copiado. Abra o Instagram para compartilhar.');
        }
      }
    });
  });

  function youtubeCard(video) {
    const link = document.createElement('a');
    link.className = 'youtube-mini';
    link.href = video.url || window.VAE_BLOG?.youtubeChannel || '#';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';

    const img = document.createElement('img');
    img.src = video.thumbnail_url || '';
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';

    const copy = document.createElement('span');
    const title = document.createElement('strong');
    title.textContent = video.title || 'Vídeo do Vamos a Estudiar Español';
    const meta = document.createElement('small');
    meta.textContent = 'Assistir no YouTube →';
    copy.append(title, meta);
    link.append(img, copy);
    return link;
  }

  async function loadYoutube() {
    const root = qs('#sidebar-youtube');
    const endpoint = window.VAE_BLOG?.youtubeApi;
    if (!root || !endpoint) return;
    try {
      const response = await fetch(endpoint, { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`YouTube ${response.status}`);
      const data = await response.json();
      const videos = Array.isArray(data?.videos) ? data.videos.slice(0, 3) : [];
      root.replaceChildren();
      if (!videos.length) throw new Error('Sem vídeos');
      videos.forEach((video) => root.appendChild(youtubeCard(video)));
    } catch (_) {
      root.innerHTML = '<p class="sidebar-empty">Não foi possível carregar os vídeos agora. Use o link abaixo para abrir o canal.</p>';
    }
  }

  function popularCard(post, index) {
    const link = document.createElement('a');
    link.className = 'sidebar-post sidebar-post--ranked';
    link.href = post.url || post.path || '#';
    const rank = document.createElement('span');
    rank.className = 'rank';
    rank.textContent = String(index + 1);
    const copy = document.createElement('span');
    const title = document.createElement('strong');
    title.textContent = post.title || 'Postagem';
    const meta = document.createElement('small');
    meta.textContent = post.views ? `${Number(post.views).toLocaleString('pt-BR')} visualizações` : 'Em destaque';
    copy.append(title, meta);
    link.append(rank, copy);
    return link;
  }

  const POST_PATH = /^\/\d{4}\/\d{2}\/[^/?#]+\.html$/;
  const OFFICIAL_HOSTS = new Set([
    'vamosaestudiarespanol.com.br',
    'www.vamosaestudiarespanol.com.br'
  ]);

  function supabaseConfig() {
    const url = String(window.VAE_BLOG?.supabaseUrl || '').replace(/\/+$/, '');
    const key = String(window.VAE_BLOG?.supabaseKey || '');
    return url && key ? { url, key } : null;
  }

  async function supabaseRpc(name, payload) {
    const config = supabaseConfig();
    if (!config) throw new Error('Supabase não configurado');
    const response = await fetch(`${config.url}/rest/v1/rpc/${name}`, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        apikey: config.key
      },
      body: JSON.stringify(payload),
      cache: 'no-store'
    });
    if (!response.ok) throw new Error(`Supabase ${response.status}`);
    return response.json();
  }

  async function recordBlogPostView() {
    if (!OFFICIAL_HOSTS.has(window.location.hostname) || !POST_PATH.test(window.location.pathname)) return;
    if (!supabaseConfig()) return;

    const storageKey = `vae:blog-view:${window.location.pathname}`;
    try {
      if (window.sessionStorage.getItem(storageKey)) return;
    } catch (_) {
      // Alguns navegadores podem bloquear sessionStorage; a contagem continua sem identificador persistente.
    }

    const title = qs('.post-header h1')?.textContent?.trim()
      || document.title.replace(/\s*[|–—-]\s*Vamos a Estudiar Español.*$/i, '').trim()
      || 'Postagem';

    try {
      await supabaseRpc('record_blog_post_view', {
        p_path: window.location.pathname,
        p_title: title
      });
      try {
        window.sessionStorage.setItem(storageKey, '1');
      } catch (_) {
        // Sem impacto funcional.
      }
    } catch (_) {
      // Analytics nunca deve bloquear a leitura do artigo.
    }
  }

  async function loadPopularPosts() {
    const root = qs('#popular-posts-list');
    if (!root || !supabaseConfig()) return;
    try {
      const data = await supabaseRpc('get_popular_blog_posts', { p_limit: 5 });
      const payload = Array.isArray(data) && data.length === 1 ? data[0] : data;
      const posts = Array.isArray(payload?.posts) ? payload.posts.slice(0, 5) : [];
      if (!posts.length) return;
      root.replaceChildren(...posts.map(popularCard));
    } catch (_) {
      // Mantém o fallback editorial gerado pelo Jekyll.
    }
  }

  loadYoutube();
  recordBlogPostView().finally(loadPopularPosts);
})();

#!/usr/bin/env python3
'''Finaliza a migração do Blogger: SEO, navegação, Supabase e conteúdo responsivo.'''

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPING_FILE = ROOT / "migration" / "blogger-meta-descriptions.b64"
EXPECTED_MAPPING_SHA256 = "a46c17641cbba4c2516a81e3e3950d2496efd3d02abe5b57f664d749e08cf19a"
EXPECTED_META_DESCRIPTIONS = 168

SUPABASE_URL = "https://clfwoywzalttkvhstsgh.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_QylDT7fw_RktIiSApbHkLA_w6PHRjmH"

CONTENT_CSS = r'''
/* Camada de compatibilidade para HTML legado importado do Blogger. */
.post-body{overflow-wrap:anywhere}
.post-body iframe[src*="youtube.com"],.post-body iframe[src*="youtube-nocookie.com"],.post-body iframe[src*="youtu.be"]{display:block;width:100%;height:auto;aspect-ratio:16/9}
.post-body table{display:block;max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}
.post-body pre{max-width:100%;overflow-x:auto}
.post-body img{height:auto}
'''.lstrip()

POPULAR_BLOCK = r'''  const POST_PATH = /^\/\d{4}\/\d{2}\/[^/?#]+\.html$/;
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
})();'''


def require_replace(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Trecho esperado não encontrado em {label}")
    return text.replace(old, new)


def load_mapping() -> dict[str, str]:
    encoded = MAPPING_FILE.read_text(encoding="utf-8").strip()
    raw = gzip.decompress(base64.b64decode(encoded))
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != EXPECTED_MAPPING_SHA256:
        raise RuntimeError(f"Hash do mapa de meta descriptions inesperado: {actual_hash}")

    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        mapping = data
    elif isinstance(data, dict) and isinstance(data.get("descriptions"), dict):
        mapping = data["descriptions"]
    elif isinstance(data, list):
        mapping = {
            item["permalink"]: item["description"]
            for item in data
            if isinstance(item, dict) and "permalink" in item and "description" in item
        }
    else:
        raise RuntimeError("Formato inesperado do mapa de meta descriptions")

    if len(mapping) != EXPECTED_META_DESCRIPTIONS:
        raise RuntimeError(f"Esperadas {EXPECTED_META_DESCRIPTIONS} meta descriptions, encontradas {len(mapping)}")
    return mapping


def apply_meta_descriptions() -> tuple[int, int]:
    mapping = load_mapping()
    documents = sorted((ROOT / "_posts").glob("*.md")) + sorted((ROOT / "p").glob("*.md"))
    matched: set[str] = set()
    changed = 0

    for path in documents:
        text = path.read_text(encoding="utf-8")
        permalink_match = re.search(r'^permalink:\s*["\']([^"\']+)["\']\s*$', text, re.M)
        if not permalink_match:
            continue
        permalink = permalink_match.group(1)
        if permalink not in mapping:
            continue

        matched.add(permalink)
        replacement = "description: " + json.dumps(mapping[permalink], ensure_ascii=False)
        new_text, count = re.subn(r"^description:\s*.*$", lambda _: replacement, text, count=1, flags=re.M)
        if count != 1:
            raise RuntimeError(f"description ausente ou duplicada em {path.relative_to(ROOT)}")
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed += 1

    missing = sorted(set(mapping) - matched)
    if missing:
        raise RuntimeError("Permalinks do mapa não encontrados: " + ", ".join(missing[:10]))
    return len(matched), changed


def patch_config() -> None:
    path = ROOT / "_config.yml"
    text = path.read_text(encoding="utf-8")
    old = '''# Pode ser preenchido depois com um endpoint de analytics/Supabase.
popular_posts_api: ""
'''
    new = f'''# Credenciais públicas de baixo privilégio para os RPCs de popularidade.
# A chave publishable é própria para clientes web; nunca usar service_role aqui.
supabase_url: "{SUPABASE_URL}"
supabase_publishable_key: "{SUPABASE_PUBLISHABLE_KEY}"
'''
    text = require_replace(text, old, new, str(path.relative_to(ROOT)))
    path.write_text(text, encoding="utf-8")


def patch_layout() -> None:
    path = ROOT / "_layouts" / "default.html"
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text,
        '''  <link rel="stylesheet" href="{{ '/assets/css/style.css' | relative_url }}">''',
        '''  <link rel="stylesheet" href="{{ '/assets/css/style.css' | relative_url }}">
  <link rel="stylesheet" href="{{ '/assets/css/content.css' | relative_url }}">''',
        str(path.relative_to(ROOT)),
    )
    text = text.replace("{{ '/sobre/' | relative_url }}", "{{ '/p/sobre.html' | relative_url }}")
    text = require_replace(
        text,
        '''        <a href="{{ '/p/sobre.html' | relative_url }}">Sobre</a>
        <a href="{{ site.social.practice }}">Espaço de Prática</a>''',
        '''        <a href="{{ '/p/sobre.html' | relative_url }}">Sobre</a>
        <a href="{{ '/p/contato.html' | relative_url }}">Contato</a>
        <a href="{{ '/p/politica-de-privacidade.html' | relative_url }}">Privacidade</a>
        <a href="{{ '/p/termos-e-condicoes.html' | relative_url }}">Termos</a>
        <a href="{{ site.social.practice }}">Espaço de Prática</a>''',
        str(path.relative_to(ROOT)),
    )
    text = require_replace(
        text,
        '''<div class="sidebar-post-list" id="popular-posts-list" data-endpoint="{{ site.popular_posts_api }}">''',
        '''<div class="sidebar-post-list" id="popular-posts-list">''',
        str(path.relative_to(ROOT)),
    )
    text = require_replace(
        text,
        '''      youtubeChannel: {{ site.social.youtube | jsonify }},
      baseUrl: {{ site.url | jsonify }}''',
        '''      youtubeChannel: {{ site.social.youtube | jsonify }},
      supabaseUrl: {{ site.supabase_url | jsonify }},
      supabaseKey: {{ site.supabase_publishable_key | jsonify }},
      baseUrl: {{ site.url | jsonify }}''',
        str(path.relative_to(ROOT)),
    )
    path.write_text(text, encoding="utf-8")


def patch_javascript() -> None:
    path = ROOT / "assets" / "js" / "site.js"
    text = path.read_text(encoding="utf-8")
    text = require_replace(
        text,
        "    link.href = post.url || '#';",
        "    link.href = post.url || post.path || '#';",
        str(path.relative_to(ROOT)),
    )
    pattern = re.compile(
        r"  async function loadPopularPosts\(\) \{.*?\n  \}\n\n  loadYoutube\(\);\n  loadPopularPosts\(\);\n\}\)\(\);\s*$",
        re.S,
    )
    new_text, count = pattern.subn(lambda _: POPULAR_BLOCK, text, count=1)
    if count != 1:
        raise RuntimeError(f"Bloco de popularidade não localizado em {path.relative_to(ROOT)}")
    path.write_text(new_text + "\n", encoding="utf-8")


def write_content_css() -> None:
    path = ROOT / "assets" / "css" / "content.css"
    path.write_text(CONTENT_CSS, encoding="utf-8")


def remove_duplicate_about() -> None:
    path = ROOT / "sobre.html"
    if path.exists():
        path.unlink()


def audit_after_changes() -> None:
    documents = sorted((ROOT / "_posts").glob("*.md")) + sorted((ROOT / "p").glob("*.md"))
    if len(documents) != 194:
        raise RuntimeError(f"Esperados 194 conteúdos publicados, encontrados {len(documents)}")

    external_img = re.compile(r'<img\b[^>]*\bsrc=["\']https?://', re.I)
    bad_external: list[str] = []
    missing_media: list[str] = []
    local_src = re.compile(r'<img\b[^>]*\bsrc=["\'](/assets/media/[^"\']+)["\']', re.I)

    for path in documents:
        text = path.read_text(encoding="utf-8")
        if external_img.search(text):
            bad_external.append(str(path.relative_to(ROOT)))
        for src in local_src.findall(text):
            if not (ROOT / src.lstrip("/")).is_file():
                missing_media.append(f"{path.relative_to(ROOT)} -> {src}")
        image_match = re.search(r'^image:\s*["\']([^"\']*)["\']\s*$', text, re.M)
        if image_match:
            image = image_match.group(1)
            if image.startswith(("http://", "https://")):
                bad_external.append(f"{path.relative_to(ROOT)} (front matter)")
            elif image.startswith("/assets/media/") and not (ROOT / image.lstrip("/")).is_file():
                missing_media.append(f"{path.relative_to(ROOT)} -> {image}")

    if bad_external:
        raise RuntimeError("Ainda há imagens externas: " + ", ".join(bad_external[:12]))
    if missing_media:
        raise RuntimeError("Referências de mídia inexistentes: " + ", ".join(missing_media[:12]))

    mapping = load_mapping()
    verified = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        pm = re.search(r'^permalink:\s*["\']([^"\']+)["\']\s*$', text, re.M)
        dm = re.search(r'^description:\s*(.+)$', text, re.M)
        if not pm or pm.group(1) not in mapping:
            continue
        if not dm:
            raise RuntimeError(f"description ausente em {path.relative_to(ROOT)}")
        try:
            actual = json.loads(dm.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"description inválida em {path.relative_to(ROOT)}: {exc}") from exc
        if actual != mapping[pm.group(1)]:
            raise RuntimeError(f"Meta description divergente em {path.relative_to(ROOT)}")
        verified += 1

    if verified != EXPECTED_META_DESCRIPTIONS:
        raise RuntimeError(f"Esperadas {EXPECTED_META_DESCRIPTIONS} descrições verificadas, obtidas {verified}")
    if (ROOT / "sobre.html").exists():
        raise RuntimeError("sobre.html duplicado ainda existe")


def main() -> None:
    matched, changed = apply_meta_descriptions()
    patch_config()
    patch_layout()
    patch_javascript()
    write_content_css()
    remove_duplicate_about()
    audit_after_changes()
    print(f"SEO: {matched} descrições originais verificadas; {changed} arquivos atualizados.")
    print("Navegação, conteúdo responsivo e integração Supabase preparados.")
    print("Auditoria pós-migração concluída sem imagens externas ou mídias ausentes.")


if __name__ == "__main__":
    main()

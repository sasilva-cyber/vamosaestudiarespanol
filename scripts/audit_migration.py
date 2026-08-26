#!/usr/bin/env python3
'''Valida a migração Blogger -> Jekyll sem modificar arquivos.'''

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONTENT = 194
EXPECTED_PERMALINK_HASH = "699a67dd194ff2c929df8456f03f286068e101ba2c0650266709349cab13c65c"
EXPECTED_MAPPING_SHA256 = "a46c17641cbba4c2516a81e3e3950d2496efd3d02abe5b57f664d749e08cf19a"
EXPECTED_META_DESCRIPTIONS = 168


def documents() -> list[Path]:
    return sorted((ROOT / "_posts").glob("*.md")) + sorted((ROOT / "p").glob("*.md"))


def load_mapping() -> dict[str, str]:
    encoded = (ROOT / "migration" / "blogger-meta-descriptions.b64").read_text(encoding="utf-8").strip()
    raw = gzip.decompress(base64.b64decode(encoded))
    actual_hash = hashlib.sha256(raw).hexdigest()
    if actual_hash != EXPECTED_MAPPING_SHA256:
        raise SystemExit(f"Hash do mapa SEO divergente: {actual_hash}")
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
        raise SystemExit("Formato inesperado do mapa SEO")
    if len(mapping) != EXPECTED_META_DESCRIPTIONS:
        raise SystemExit(f"Esperadas {EXPECTED_META_DESCRIPTIONS} descrições no mapa; encontradas {len(mapping)}")
    return mapping


def main() -> None:
    docs = documents()
    if len(docs) != EXPECTED_CONTENT:
        raise SystemExit(f"Esperados {EXPECTED_CONTENT} conteúdos; encontrados {len(docs)}")

    permalinks: list[str] = []
    external_images: list[str] = []
    missing_media: list[str] = []
    local_image_refs = 0
    external_img_re = re.compile(r'<img\b[^>]*\bsrc=["\']https?://', re.I)
    local_img_re = re.compile(r'<img\b[^>]*\bsrc=["\'](/assets/media/[^"\']+)["\']', re.I)

    for path in docs:
        text = path.read_text(encoding="utf-8")
        pm = re.search(r'^permalink:\s*["\']([^"\']+)["\']\s*$', text, re.M)
        if not pm:
            raise SystemExit(f"Permalink ausente: {path.relative_to(ROOT)}")
        permalinks.append(pm.group(1))

        if external_img_re.search(text):
            external_images.append(str(path.relative_to(ROOT)))

        for src in local_img_re.findall(text):
            local_image_refs += 1
            if not (ROOT / src.lstrip("/")).is_file():
                missing_media.append(f"{path.relative_to(ROOT)} -> {src}")

        image_match = re.search(r'^image:\s*["\']([^"\']*)["\']\s*$', text, re.M)
        if image_match:
            image = image_match.group(1)
            if image.startswith(("http://", "https://")):
                external_images.append(f"{path.relative_to(ROOT)} (front matter)")
            elif image.startswith("/assets/media/") and not (ROOT / image.lstrip("/")).is_file():
                missing_media.append(f"{path.relative_to(ROOT)} -> {image}")

    if len(set(permalinks)) != EXPECTED_CONTENT:
        raise SystemExit("Há permalinks duplicados")
    actual_permalink_hash = hashlib.sha256("\n".join(sorted(permalinks)).encode()).hexdigest()
    if actual_permalink_hash != EXPECTED_PERMALINK_HASH:
        raise SystemExit(f"Conjunto de URLs divergente do Blogger: {actual_permalink_hash}")

    if external_images:
        raise SystemExit("Imagens externas remanescentes: " + ", ".join(external_images[:15]))
    if missing_media:
        raise SystemExit("Mídias locais ausentes: " + ", ".join(missing_media[:15]))

    media_files = list((ROOT / "assets" / "media").rglob("*.webp"))
    empty_media = [str(p.relative_to(ROOT)) for p in media_files if p.stat().st_size == 0]
    if empty_media:
        raise SystemExit("Arquivos WebP vazios: " + ", ".join(empty_media[:15]))

    mapping = load_mapping()
    verified = 0
    for path in docs:
        text = path.read_text(encoding="utf-8")
        pm = re.search(r'^permalink:\s*["\']([^"\']+)["\']\s*$', text, re.M)
        if not pm or pm.group(1) not in mapping:
            continue
        dm = re.search(r'^description:\s*(.+)$', text, re.M)
        if not dm:
            raise SystemExit(f"description ausente: {path.relative_to(ROOT)}")
        try:
            actual = json.loads(dm.group(1))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"description inválida em {path.relative_to(ROOT)}: {exc}") from exc
        if actual != mapping[pm.group(1)]:
            raise SystemExit(f"Meta description divergente: {path.relative_to(ROOT)}")
        verified += 1

    if verified != EXPECTED_META_DESCRIPTIONS:
        raise SystemExit(f"Esperadas {EXPECTED_META_DESCRIPTIONS} descrições originais verificadas; obtidas {verified}")

    if (ROOT / "sobre.html").exists():
        raise SystemExit("Página duplicada sobre.html ainda existe")
    if not (ROOT / "assets" / "css" / "content.css").is_file():
        raise SystemExit("CSS de compatibilidade do conteúdo legado ausente")

    config = (ROOT / "_config.yml").read_text(encoding="utf-8")
    if "supabase_publishable_key:" not in config or "supabase_url:" not in config:
        raise SystemExit("Configuração pública do Supabase ausente")

    layout = (ROOT / "_layouts" / "default.html").read_text(encoding="utf-8")
    for required in (
        "/p/sobre.html",
        "/p/contato.html",
        "/p/politica-de-privacidade.html",
        "/p/termos-e-condicoes.html",
        "site.supabase_publishable_key",
    ):
        if required not in layout:
            raise SystemExit(f"Layout final incompleto: {required}")

    print(f"Conteúdos: {EXPECTED_CONTENT}; URLs históricas preservadas; SHA-256 {actual_permalink_hash}")
    print(f"SEO: {verified} meta descriptions originais verificadas.")
    print(f"Mídia: {len(media_files)} arquivos WebP; {local_image_refs} referências locais no corpo; nenhuma imagem externa.")
    print("Estrutura: navegação histórica, páginas legais e integração Supabase presentes.")


if __name__ == "__main__":
    main()

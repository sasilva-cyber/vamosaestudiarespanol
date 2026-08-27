#!/usr/bin/env python3
"""Prepara e valida o HTML legado importado do Blogger.

O corpo dos conteúdos migrados já é HTML, apesar de os arquivos terem extensão
.md. Jekyll/Kramdown pode reinterpretar combinações antigas de tags e exibi-las
como texto. Durante o build, este script cria cópias temporárias .html dos
conteúdos Blogger e remove apenas as cópias .md do worktree efêmero do Actions.
Assim Jekyll aplica Liquid/front matter/layout, mas não passa o corpo pelo
conversor Markdown.

Quando a imagem usada como capa no front matter também aparece no HTML legado,
a primeira ocorrência idêntica é removida do corpo para evitar que a mesma capa
seja exibida duas vezes pelo layout do post.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
ROOT_ATTR_RE = re.compile(r"\b(?P<attr>href|src)=(?P<quote>['\"])/(?P<rest>(?!/)[^'\"]*)", re.I)
ESCAPED_STRUCTURAL_RE = re.compile(
    r"&lt;/?(?:div|span|iframe|img|ul|ol|li|table|tbody|thead|tr|td|th|"
    r"blockquote|h[1-6]|p|figure|figcaption)\b",
    re.I,
)
COVER_IMAGE_RE = re.compile(
    r'<figure\s+class=["\']post-cover["\'][^>]*>.*?<img\b[^>]*\bsrc=["\']([^"\']+)["\']',
    re.I | re.S,
)
BODY_IMAGE_SRC_RE = re.compile(r'<img\b[^>]*\bsrc=["\']([^"\']+)["\']', re.I)


def split_document(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise SystemExit(f"Front matter ausente ou inválido: {path}")
    return match.group(1), match.group(2)


def is_blogger(front_matter: str) -> bool:
    return bool(re.search(r"^blogger_id:\s*", front_matter, re.M))


def front_matter_image(front_matter: str) -> str | None:
    match = re.search(
        r'^image:\s*(?:"([^"]+)"|\'([^\']+)\'|(\S+))\s*$',
        front_matter,
        re.M,
    )
    if not match:
        return None
    return next((value for value in match.groups() if value is not None), None)


def strip_duplicate_featured_image(front_matter: str, body: str) -> tuple[str, bool]:
    """Remove do HTML legado a primeira imagem idêntica à capa do post.

    A remoção é deliberadamente conservadora: exige igualdade exata do ``src``
    com o campo ``image`` do front matter. Se a imagem estiver sozinha em um
    wrapper típico do Blogger, o wrapper vazio também é removido. Qualquer outra
    imagem permanece intocada.
    """
    image = front_matter_image(front_matter)
    if not image:
        return body, False

    escaped = re.escape(image)
    img_pattern = rf'<img\b[^>]*\bsrc=(?:"{escaped}"|\'{escaped}\')[^>]*\/?>'
    anchor_image_re = re.compile(rf'<a\b[^>]*>\s*{img_pattern}\s*</a>', re.I)
    image_re = re.compile(img_pattern, re.I)

    match = anchor_image_re.search(body) or image_re.search(body)
    if not match:
        return body, False

    sentinel = "__BLOGGER_FEATURED_IMAGE__"
    body = body[: match.start()] + sentinel + body[match.end() :]

    attrs = r'(?:\s+[^>]*)?'
    wrapper_patterns = (
        # Estrutura frequente do Blogger: div > div > imagem > /div > br > /div
        re.compile(
            rf'<div{attrs}>\s*<div{attrs}>\s*{sentinel}\s*</div>\s*'
            rf'(?:<span{attrs}>\s*<br\s*/?>\s*</span>\s*)?</div>',
            re.I,
        ),
        # Estrutura simples: div > imagem > /div
        re.compile(rf'<div{attrs}>\s*{sentinel}\s*</div>', re.I),
    )

    for pattern in wrapper_patterns:
        body, removed = pattern.subn("", body, count=1)
        if removed:
            break

    # Caso a imagem estivesse misturada a outros elementos, remove somente ela.
    body = body.replace(sentinel, "", 1)
    return body, True


def normalize_baseurl(value: str) -> str:
    value = (value or "").strip()
    if not value or value == "/":
        return ""
    return "/" + value.strip("/")


def prefix_root_urls(body: str, baseurl: str) -> str:
    if not baseurl:
        return body

    def replace(match: re.Match[str]) -> str:
        rest = match.group("rest")
        # Não duplica o prefixo caso o conteúdo já tenha sido preparado.
        if rest == baseurl.lstrip("/") or rest.startswith(baseurl.lstrip("/") + "/"):
            return match.group(0)
        return f'{match.group("attr")}={match.group("quote")}{baseurl}/{rest}'

    return ROOT_ATTR_RE.sub(replace, body)


def prepare(baseurl: str, expected: int | None) -> int:
    baseurl = normalize_baseurl(baseurl)
    candidates = list(Path("_posts").glob("*.md")) + list(Path("p").glob("*.md"))
    converted = 0
    duplicate_covers_removed = 0

    for source in candidates:
        front_matter, body = split_document(source)
        if not is_blogger(front_matter):
            continue

        destination = source.with_suffix(".html")
        if destination.exists():
            raise SystemExit(f"Destino já existe; abortando para evitar sobrescrita: {destination}")

        body, removed_cover = strip_duplicate_featured_image(front_matter, body)
        if removed_cover:
            duplicate_covers_removed += 1
        body = prefix_root_urls(body, baseurl)
        destination.write_text(f"---\n{front_matter}\n---\n{body}", encoding="utf-8")
        source.unlink()
        converted += 1

    if expected is not None and converted != expected:
        raise SystemExit(f"Esperados {expected} conteúdos Blogger; preparados {converted}")

    print(
        f"HTML Blogger preparado: {converted} conteúdos; "
        f"capas duplicadas removidas: {duplicate_covers_removed}; baseurl={baseurl or '/'}"
    )
    return converted


def extract_post_body(html: str) -> str | None:
    marker = '<div class="post-body">'
    start = html.find(marker)
    if start < 0:
        return None
    start += len(marker)

    boundaries = []
    for marker_end in ('<div class="post-tags"', '<section class="share-section"'):
        pos = html.find(marker_end, start)
        if pos >= 0:
            boundaries.append(pos)
    if not boundaries:
        return None
    return html[start : min(boundaries)]


def validate_site(site_dir: Path, expected_posts: int | None) -> int:
    if not site_dir.is_dir():
        raise SystemExit(f"Diretório do site não encontrado: {site_dir}")

    checked = 0
    escaped_failures: list[str] = []
    duplicate_cover_failures: list[str] = []

    for path in site_dir.rglob("*.html"):
        html = path.read_text(encoding="utf-8", errors="replace")
        body = extract_post_body(html)
        if body is None:
            continue
        checked += 1

        escaped_match = ESCAPED_STRUCTURAL_RE.search(body)
        if escaped_match:
            escaped_failures.append(f"{path}: {escaped_match.group(0)}")

        cover_match = COVER_IMAGE_RE.search(html)
        if cover_match:
            cover_src = cover_match.group(1)
            body_sources = BODY_IMAGE_SRC_RE.findall(body)
            if cover_src in body_sources:
                duplicate_cover_failures.append(f"{path}: {cover_src}")

    if expected_posts is not None and checked < expected_posts:
        raise SystemExit(f"Esperados ao menos {expected_posts} corpos de posts; encontrados {checked}")

    if escaped_failures:
        preview = "\n".join(escaped_failures[:20])
        raise SystemExit(
            f"HTML estrutural escapado encontrado em {len(escaped_failures)} post(s):\n{preview}"
        )

    if duplicate_cover_failures:
        preview = "\n".join(duplicate_cover_failures[:20])
        raise SystemExit(
            f"Imagem de capa duplicada no corpo de {len(duplicate_cover_failures)} post(s):\n{preview}"
        )

    print(
        f"HTML renderizado validado: {checked} corpos de posts sem tags estruturais "
        "escapadas e sem capas duplicadas"
    )
    return checked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseurl", default="", help="Prefixo temporário do GitHub Pages")
    parser.add_argument("--expect", type=int, default=None, help="Quantidade exata de conteúdos Blogger esperada")
    parser.add_argument("--validate-site", type=Path, default=None, help="Diretório _site a validar")
    parser.add_argument("--expect-posts", type=int, default=None, help="Quantidade mínima de post-bodies esperada")
    args = parser.parse_args()

    if args.validate_site is not None:
        validate_site(args.validate_site, args.expect_posts)
    else:
        prepare(args.baseurl, args.expect)


if __name__ == "__main__":
    main()

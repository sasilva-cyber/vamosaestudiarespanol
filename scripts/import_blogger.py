#!/usr/bin/env python3
"""Importa o Blogger público para Jekyll preservando os permalinks atuais.

O backup Atom exportado foi auditado antes desta rotina e estabelece os totais
esperados: 189 posts LIVE e 5 páginas LIVE. A importação falha se o feed público
não devolver exatamente esse acervo, evitando publicação parcial.
"""

from __future__ import annotations

import html
import json
import math
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

SITE = "https://www.vamosaestudiarespanol.com.br"
EXPECTED_POSTS = 189
EXPECTED_PAGES = 5
TZ = ZoneInfo("America/Sao_Paulo")
ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "_posts"
PAGES = ROOT / "p"
MIGRATION = ROOT / "migration"

ATOM = "http://www.w3.org/2005/Atom"
NS = {"a": ATOM}

INTERNAL_HOSTS = {
    "www.vamosaestudiarespanol.com.br",
    "vamosaestudiarespanol.com.br",
    "www.vamosaestudiarespanol.com",
    "vamosaestudiarespanol.com",
    "vamosaestudarespanol.blogspot.com",
    "www.vamosaestudarespanol.blogspot.com",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; VAE-Blogger-Migration/1.0)",
            "Accept": "application/atom+xml,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        return response.read()


def load_feed(kind: str) -> list[ET.Element]:
    # Blogger aceita max-results no feed Atom público. O redirect=false evita
    # que o Blogger troque o endpoint por páginas HTML em alguns templates.
    url = f"{SITE}/feeds/{kind}/default?alt=atom&max-results=500&redirect=false"
    data = fetch(url)
    root = ET.fromstring(data)
    entries = root.findall("a:entry", NS)
    print(f"{kind}: {len(entries)} entradas recebidas de {url}")
    return entries


def text(entry: ET.Element, name: str) -> str:
    return (entry.findtext(f"a:{name}", default="", namespaces=NS) or "").strip()


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)


def json_scalar(value: str) -> str:
    # JSON entre aspas é um escalar YAML válido e lida bem com Unicode/pontuação.
    return json.dumps(value or "", ensure_ascii=False)


def alternate_path(entry: ET.Element) -> str:
    for link in entry.findall("a:link", NS):
        if link.attrib.get("rel") == "alternate" and link.attrib.get("href"):
            parsed = urlparse(link.attrib["href"])
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            return path
    raise ValueError(f"Entrada sem URL alternativa: {text(entry, 'title')}")


def categories(entry: ET.Element) -> list[str]:
    values: list[str] = []
    for category in entry.findall("a:category", NS):
        term = (category.attrib.get("term") or "").strip()
        # Ignora categorias técnicas do Blogger/GData, se houver.
        if term and not term.startswith("http://schemas.google.com/blogger/"):
            values.append(term)
    return list(dict.fromkeys(values))


def normalize_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("https://href.li/?") or url.startswith("http://href.li/?"):
        return unquote(url.split("?", 1)[1])
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if (parsed.hostname or "").lower() in INTERNAL_HOSTS:
        result = parsed.path or "/"
        if parsed.query:
            result += "?" + parsed.query
        if parsed.fragment:
            result += "#" + parsed.fragment
        return result
    return url


def plain_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def description(raw_html: str) -> str:
    value = plain_text(raw_html)
    if len(value) <= 165:
        return value
    value = value[:165].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return value + "…"


def first_image(raw_html: str, title: str) -> tuple[str, str]:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    image = soup.find("img")
    if not image:
        return "", ""
    parent = image.parent if getattr(image.parent, "name", None) == "a" else None
    source = image.get("src", "")
    if parent and "blogger.googleusercontent.com" in parent.get("href", ""):
        source = parent.get("href", source)
    alt = (image.get("alt") or image.get("title") or title).strip()
    return normalize_url(source), alt


def clean_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")

    # Não migra código executável inserido em posts antigos.
    for tag in soup.find_all(["script", "noscript"]):
        tag.decompose()

    for tag in soup.find_all(True):
        # O tema novo assume tipografia, cores e espaçamento.
        for attr in (
            "style",
            "border",
            "width",
            "height",
            "data-original-height",
            "data-original-width",
        ):
            tag.attrs.pop(attr, None)

        if tag.name == "a" and tag.get("href"):
            tag["href"] = normalize_url(tag["href"])
            if tag["href"].startswith("http"):
                tag["rel"] = "noopener noreferrer"

        if tag.name == "img":
            parent = tag.parent if getattr(tag.parent, "name", None) == "a" else None
            if parent and "blogger.googleusercontent.com" in parent.get("href", ""):
                tag["src"] = parent["href"]
            if tag.get("src"):
                tag["src"] = normalize_url(tag["src"])
            tag["loading"] = "lazy"
            tag["decoding"] = "async"
            tag["alt"] = (tag.get("alt") or tag.get("title") or "").strip()

        if tag.name == "iframe":
            if tag.get("src"):
                tag["src"] = normalize_url(tag["src"])
            tag["loading"] = "lazy"
            tag["allowfullscreen"] = "allowfullscreen"
            current = list(tag.get("class", []))
            if "responsive-embed" not in current:
                current.append("responsive-embed")
            tag["class"] = current

    for div in soup.find_all("div", class_="separator"):
        div.attrs.pop("class", None)

    return str(soup).strip()


def slug_from_permalink(permalink: str) -> str:
    name = Path(urlparse(permalink).path).name
    if name.endswith(".html"):
        name = name[:-5]
    return name or "pagina"


def front_matter(
    *,
    layout: str,
    title: str,
    desc: str,
    published: datetime,
    updated: datetime,
    permalink: str,
    cats: list[str],
    image: str,
    image_alt: str,
    reading_time: int | None,
    blogger_id: str,
) -> str:
    lines = [
        "---",
        f"layout: {layout}",
        f"title: {json_scalar(title)}",
        f"description: {json_scalar(desc)}",
        f"date: {published.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"last_modified_at: {updated.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"permalink: {json_scalar(permalink)}",
    ]
    if cats:
        lines.append(f"category: {json_scalar(cats[0])}")
        lines.append("categories: [" + ", ".join(json_scalar(c) for c in cats) + "]")
    if image:
        lines.append(f"image: {json_scalar(image)}")
        lines.append(f"image_alt: {json_scalar(image_alt or title)}")
    if reading_time is not None:
        lines.append(f"reading_time: {reading_time}")
    lines.append(f"blogger_id: {json_scalar(blogger_id)}")
    lines.append('blogger_status: "LIVE"')
    lines.append("---")
    return "\n".join(lines)


def convert(entry: ET.Element, *, kind: str) -> dict:
    title = text(entry, "title")
    raw = entry.findtext("a:content", default="", namespaces=NS) or ""
    published = parse_date(text(entry, "published"))
    updated_value = text(entry, "updated") or text(entry, "published")
    updated = parse_date(updated_value)
    permalink = alternate_path(entry)
    cats = categories(entry)
    image, image_alt = first_image(raw, title)
    words = len(re.findall(r"\b\w+\b", plain_text(raw), flags=re.UNICODE))
    reading = max(1, math.ceil(words / 220)) if kind == "posts" else None
    blogger_id = text(entry, "id")

    if kind == "posts":
        slug = slug_from_permalink(permalink)
        destination = POSTS / f"{published:%Y-%m-%d}-{slug}.md"
        layout = "post"
    else:
        slug = slug_from_permalink(permalink)
        destination = PAGES / f"{slug}.md"
        layout = "page"

    fm = front_matter(
        layout=layout,
        title=title,
        desc=description(raw),
        published=published,
        updated=updated,
        permalink=permalink,
        cats=cats,
        image=image,
        image_alt=image_alt,
        reading_time=reading,
        blogger_id=blogger_id,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(fm + "\n\n" + clean_html(raw) + "\n", encoding="utf-8")

    return {
        "type": "POST" if kind == "posts" else "PAGE",
        "status": "LIVE",
        "title": title,
        "permalink": permalink,
        "file": str(destination.relative_to(ROOT)),
        "date": published.isoformat(),
        "categories": cats,
        "image": image,
        "description_generated": True,
        "words": words,
        "reading_time": reading,
    }


def validate(manifest: list[dict]) -> None:
    posts = [item for item in manifest if item["type"] == "POST"]
    pages = [item for item in manifest if item["type"] == "PAGE"]
    if len(posts) != EXPECTED_POSTS:
        raise SystemExit(f"Importação abortada: esperados {EXPECTED_POSTS} posts, recebidos {len(posts)}")
    if len(pages) != EXPECTED_PAGES:
        raise SystemExit(f"Importação abortada: esperadas {EXPECTED_PAGES} páginas, recebidas {len(pages)}")
    permalinks = [item["permalink"] for item in manifest]
    if len(permalinks) != len(set(permalinks)):
        raise SystemExit("Importação abortada: permalinks duplicados")
    missing = [item["title"] for item in manifest if not item["permalink"]]
    if missing:
        raise SystemExit(f"Importação abortada: entradas sem permalink: {missing}")
    for path in list(POSTS.glob("*.md")) + list(PAGES.glob("*.md")):
        if "<script" in path.read_text(encoding="utf-8").lower():
            raise SystemExit(f"Importação abortada: script legado em {path}")


def main() -> None:
    # Limpa apenas o conteúdo gerado anteriormente por esta migração.
    if POSTS.exists():
        for path in POSTS.glob("*.md"):
            path.unlink()
    if PAGES.exists():
        shutil.rmtree(PAGES)
    PAGES.mkdir(parents=True, exist_ok=True)
    MIGRATION.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for entry in load_feed("posts"):
        manifest.append(convert(entry, kind="posts"))
    for entry in load_feed("pages"):
        manifest.append(convert(entry, kind="pages"))

    validate(manifest)
    (MIGRATION / "migration-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (MIGRATION / "README.md").write_text(
        "# Importação do Blogger\n\n"
        f"Importação automática validada com {EXPECTED_POSTS} posts e {EXPECTED_PAGES} páginas. "
        "Os permalinks são obtidos diretamente dos links alternativos do Blogger.\n",
        encoding="utf-8",
    )
    print(f"Importação preparada: {len(manifest)} conteúdos e {len(set(i['permalink'] for i in manifest))} URLs únicas.")


if __name__ == "__main__":
    main()

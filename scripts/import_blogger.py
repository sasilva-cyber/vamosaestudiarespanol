#!/usr/bin/env python3
"""Importa o Blogger público para Jekyll preservando URLs históricas.

O backup Atom exportado foi auditado previamente: 189 posts LIVE, 5 páginas
LIVE e 1 rascunho. O rascunho não é publicado por esta rotina. A importação
aborta se o feed público não devolver exatamente os 194 conteúdos publicados.
"""

from __future__ import annotations

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
BLOGGER = "http://schemas.google.com/blogger/2018"
NS = {"a": ATOM, "blogger": BLOGGER}

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
    """Carrega o feed paginado; Blogger limita a resposta mesmo com max-results alto."""
    page_size = 100
    start = 1
    all_entries: list[ET.Element] = []
    seen: set[str] = set()

    for _ in range(10):
        url = (
            f"{SITE}/feeds/{kind}/default?alt=atom&max-results={page_size}"
            f"&start-index={start}&redirect=false"
        )
        root = ET.fromstring(fetch(url))
        entries = root.findall("a:entry", NS)
        print(f"{kind}: página start-index={start}, {len(entries)} entradas")
        if not entries:
            break

        added = 0
        for entry in entries:
            entry_id = (entry.findtext("a:id", default="", namespaces=NS) or "").strip()
            key = entry_id or alternate_path(entry)
            if key in seen:
                continue
            seen.add(key)
            all_entries.append(entry)
            added += 1

        if len(entries) < page_size:
            break
        if added == 0:
            raise SystemExit(f"Paginação do feed {kind} não avançou em start-index={start}")
        start += len(entries)
    else:
        raise SystemExit(f"Paginação do feed {kind} excedeu o limite de segurança")

    print(f"{kind}: {len(all_entries)} entradas únicas recebidas no total")
    return all_entries


def text(entry: ET.Element, name: str) -> str:
    return (entry.findtext(f"a:{name}", default="", namespaces=NS) or "").strip()


def blogger_text(entry: ET.Element, name: str) -> str:
    return (entry.findtext(f"blogger:{name}", default="", namespaces=NS) or "").strip()


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)


def yaml_string(value: str) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def alternate_path(entry: ET.Element) -> str:
    filename = blogger_text(entry, "filename")
    if filename:
        return filename
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
        if term and not term.startswith("http://schemas.google.com/blogger/"):
            values.append(term)
    return list(dict.fromkeys(values))


def normalize_url(url: str) -> str:
    if not url:
        return url
    if url.startswith(("https://href.li/?", "http://href.li/?")):
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


def generated_description(raw_html: str) -> str:
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

    for tag in soup.find_all(["script", "noscript"]):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in (
            "style", "border", "width", "height",
            "data-original-height", "data-original-width",
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
            classes = list(tag.get("class", []))
            if "responsive-embed" not in classes:
                classes.append("responsive-embed")
            tag["class"] = classes

    for div in soup.find_all("div", class_="separator"):
        div.attrs.pop("class", None)

    return str(soup).strip()


def slug_from_permalink(permalink: str) -> str:
    name = Path(urlparse(permalink).path).name
    return (name[:-5] if name.endswith(".html") else name) or "pagina"


def front_matter(*, layout: str, title: str, desc: str, published: datetime,
                 updated: datetime, permalink: str, cats: list[str], image: str,
                 image_alt: str, reading_time: int | None, blogger_id: str) -> str:
    lines = [
        "---",
        f"layout: {layout}",
        f"title: {yaml_string(title)}",
        f"description: {yaml_string(desc)}",
        f"date: {published.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"last_modified_at: {updated.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"permalink: {yaml_string(permalink)}",
    ]
    if cats:
        lines.append(f"category: {yaml_string(cats[0])}")
        lines.append("categories: [" + ", ".join(yaml_string(c) for c in cats) + "]")
    if image:
        lines.append(f"image: {yaml_string(image)}")
        lines.append(f"image_alt: {yaml_string(image_alt or title)}")
    if reading_time is not None:
        lines.append(f"reading_time: {reading_time}")
    lines += [
        f"blogger_id: {yaml_string(blogger_id)}",
        'blogger_status: "LIVE"',
        "---",
    ]
    return "\n".join(lines)


def convert(entry: ET.Element, *, kind: str) -> dict:
    title = text(entry, "title")
    raw = entry.findtext("a:content", default="", namespaces=NS) or ""
    published = parse_date(text(entry, "published"))
    updated = parse_date(text(entry, "updated") or text(entry, "published"))
    permalink = alternate_path(entry)
    cats = categories(entry)
    image, image_alt = first_image(raw, title)
    words = len(re.findall(r"\b\w+\b", plain_text(raw), flags=re.UNICODE))
    reading = max(1, math.ceil(words / 220)) if kind == "posts" else None
    meta = blogger_text(entry, "metaDescription")
    desc = meta or generated_description(raw)

    slug = slug_from_permalink(permalink)
    if kind == "posts":
        destination = POSTS / f"{published:%Y-%m-%d}-{slug}.md"
        layout = "post"
    else:
        destination = PAGES / f"{slug}.md"
        layout = "page"

    fm = front_matter(
        layout=layout, title=title, desc=desc, published=published,
        updated=updated, permalink=permalink, cats=cats, image=image,
        image_alt=image_alt, reading_time=reading, blogger_id=text(entry, "id"),
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
        "description_source": "blogger" if meta else "generated",
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
    for path in list(POSTS.glob("*.md")) + list(PAGES.glob("*.md")):
        if "<script" in path.read_text(encoding="utf-8").lower():
            raise SystemExit(f"Importação abortada: script legado em {path}")


def main() -> None:
    POSTS.mkdir(parents=True, exist_ok=True)
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
        "As URLs históricas foram obtidas do próprio Blogger e validadas como únicas.\n",
        encoding="utf-8",
    )
    print(
        f"Importação preparada: {len(manifest)} conteúdos e "
        f"{len(set(i['permalink'] for i in manifest))} URLs únicas."
    )


if __name__ == "__main__":
    main()

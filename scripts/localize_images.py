#!/usr/bin/env python3
"""Baixa e otimiza imagens dos posts migrados, removendo dependência do Blogger.

Mantém os permalinks dos artigos intactos. As imagens são convertidas para WebP,
limitadas a 1600 px no maior lado e gravadas em assets/media/.
"""

from __future__ import annotations

import hashlib
import io
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from bs4 import BeautifulSoup
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "assets" / "media"
EXPECTED_IMAGES = 248
IMAGE_HOSTS = {
    "blogger.googleusercontent.com",
    "vamosaestudiarespanol.files.wordpress.com",
    "static.hotmart.com",
}


def split_document(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("Front matter ausente")
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        raise ValueError("Front matter inválido")
    return parts[1], parts[2]


def scalar(front: str, key: str) -> str:
    match = re.search(rf'^{re.escape(key)}:\s*["\']([^"\']*)["\']\s*$', front, re.M)
    return match.group(1) if match else ""


def safe_slug(value: str) -> str:
    value = unquote(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:90] or "imagem"


def destination_for(permalink: str, index: int, source: str) -> tuple[Path, str]:
    path = urlparse(permalink).path
    bits = [b for b in path.split("/") if b]
    source_hash = hashlib.sha1(source.encode()).hexdigest()[:8]
    if len(bits) >= 3 and bits[0].isdigit() and bits[1].isdigit():
        year, month = bits[0], bits[1]
        slug = safe_slug(Path(bits[-1]).stem)
        rel = Path("assets") / "media" / year / month / f"{slug}-{index:02d}-{source_hash}.webp"
    else:
        slug = safe_slug(Path(bits[-1] if bits else "pagina").stem)
        rel = Path("assets") / "media" / "pages" / f"{slug}-{index:02d}-{source_hash}.webp"
    return ROOT / rel, "/" + rel.as_posix()


def request_bytes(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; VAE-Media-Migration/1.0)",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Falha ao baixar {url}: {last_error}")


def save_webp(data: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if getattr(image, "is_animated", False):
            image.seek(0)
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.save(destination, "WEBP", quality=84, method=6)


def is_external_image(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    return (urlparse(url).hostname or "").lower() in IMAGE_HOSTS


def replace_front_image(front: str, old: str, new: str) -> str:
    if not old:
        return front
    pattern = r'^(image:\s*)["\']' + re.escape(old) + r'["\']\s*$'
    return re.sub(pattern, lambda m: f'{m.group(1)}"{new}"', front, flags=re.M)


def process_file(path: Path, cache: dict[str, str]) -> tuple[int, int]:
    original = path.read_text(encoding="utf-8")
    front, body = split_document(original)
    permalink = scalar(front, "permalink")
    if not permalink:
        raise ValueError(f"Permalink ausente em {path}")

    soup = BeautifulSoup(body, "html.parser")
    images = [img for img in soup.find_all("img") if is_external_image(img.get("src", ""))]
    localized = 0

    for index, img in enumerate(images, start=1):
        source = img.get("src", "")
        if source in cache:
            local_url = cache[source]
        else:
            destination, local_url = destination_for(permalink, index, source)
            if not destination.exists():
                save_webp(request_bytes(source), destination)
            cache[source] = local_url
        img["src"] = local_url
        localized += 1

        parent = img.parent if getattr(img.parent, "name", None) == "a" else None
        if parent and is_external_image(parent.get("href", "")):
            parent["href"] = local_url

    front_image = scalar(front, "image")
    if is_external_image(front_image):
        local_url = cache.get(front_image)
        if not local_url:
            destination, local_url = destination_for(permalink, 0, front_image)
            if not destination.exists():
                save_webp(request_bytes(front_image), destination)
            cache[front_image] = local_url
        front = replace_front_image(front, front_image, local_url)

    output = "---\n" + front + "---\n" + str(soup).strip() + "\n"
    path.write_text(output, encoding="utf-8")
    return len(images), localized


def main() -> None:
    MEDIA.mkdir(parents=True, exist_ok=True)
    documents = sorted((ROOT / "_posts").glob("*.md")) + sorted((ROOT / "p").glob("*.md"))
    cache: dict[str, str] = {}
    found = localized = 0
    failures: list[str] = []

    for path in documents:
        try:
            count, done = process_file(path, cache)
            found += count
            localized += done
        except Exception as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")

    if failures:
        raise SystemExit("Falhas na migração de imagens:\n" + "\n".join(failures))
    if found != EXPECTED_IMAGES:
        raise SystemExit(f"Esperadas {EXPECTED_IMAGES} imagens externas no corpo, encontradas {found}")

    remaining: list[str] = []
    for path in documents:
        text = path.read_text(encoding="utf-8")
        for host in IMAGE_HOSTS:
            if re.search(rf'<img[^>]+src=["\']https?://{re.escape(host)}/', text, re.I):
                remaining.append(str(path.relative_to(ROOT)))
                break
    if remaining:
        raise SystemExit("Ainda há imagens externas em: " + ", ".join(remaining))

    print(f"Imagens localizadas: {localized}; arquivos de mídia únicos: {len(cache)}")


if __name__ == "__main__":
    main()

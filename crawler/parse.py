from __future__ import annotations
import re
from bs4 import BeautifulSoup
from typing import List, Tuple, Optional
from .types import FamilyParsed, VariantParsed
from .normalize import (
    normalize_whitespace,
    parse_human_number,
    parse_size_bytes,
    parse_context_tokens,
    extract_age_text,
)

CATALOG_LABELS = {"tools","thinking","vision","embedding","cloud","audio","image","multimodal"}

def parse_library_slugs(html: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    slugs: List[str] = []
    seen = set()

    for a in soup.select('a[href^="/library/"]'):
        href = a.get("href") or ""
        if not href.startswith("/library/"):
            continue
        rest = href[len("/library/"):]
        if not rest or "/" in rest:
            continue
        if ":" in rest:
            continue
        slug = rest.strip()
        if slug and slug not in seen:
            slugs.append(slug)
            seen.add(slug)
    return slugs

def _meta(soup: BeautifulSoup, name_or_prop: str) -> Optional[str]:
    el = soup.find("meta", attrs={"name": name_or_prop})
    if el and el.get("content"):
        return el["content"]
    el = soup.find("meta", attrs={"property": name_or_prop})
    if el and el.get("content"):
        return el["content"]
    return None

def parse_family_and_variants_from_tags_page(html: str, slug: str) -> Tuple[FamilyParsed, List[VariantParsed]]:
    soup = BeautifulSoup(html, "lxml")

    display_name = _meta(soup, "og:title") or slug
    description = _meta(soup, "description") or _meta(soup, "og:description")

    page_text = normalize_whitespace(soup.get_text(" "))
    downloads = None
    m_dl = re.search(r"([\d.,]+(?:\.\d+)?[KMB]?)\s+Downloads", page_text)
    if m_dl:
        downloads = parse_human_number(m_dl.group(1))

    updated_text = None
    m_upd = re.search(r"Updated\s+(\d+\s+(?:day|week|month|year)s?\s+ago)", page_text)
    if m_upd:
        updated_text = m_upd.group(1)

    labels = []
    for lab in sorted(CATALOG_LABELS):
        if re.search(rf"\b{re.escape(lab)}\b", page_text):
            labels.append(lab)

    family = FamilyParsed(
        slug=slug,
        display_name=display_name,
        description=description,
        labels=labels,
        downloads=downloads,
        catalog_updated_text=updated_text,
    )

    variants: List[VariantParsed] = []
    seen_tags = set()

    for a in soup.select('a[href^="/library/"]'):
        href = a.get("href") or ""
        if not href.startswith("/library/"):
            continue
        rest = href[len("/library/"):]
        if not rest.startswith(slug + ":"):
            continue

        text = normalize_whitespace(a.get_text(" "))
        if "•" not in text:
            continue

        tag = rest
        if tag in seen_tags:
            continue

        digest = None
        m_digest = re.search(r"\b[a-f0-9]{12}\b", text)
        if m_digest:
            digest = m_digest.group(0)

        try:
            size_bytes = parse_size_bytes(text)
        except ValueError:
            continue

        max_context = None
        m_ctx = re.search(r"(\d+(?:\.\d+)?[KMB]?)\s+context\s+window", text, re.IGNORECASE)
        if m_ctx:
            max_context = parse_context_tokens(m_ctx.group(1))

        input_type = None
        if re.search(r"\bText\s+input\b", text, re.IGNORECASE) or re.search(r"\bText\b", text):
            input_type = "Text"
        if re.search(r"\bVision\b|\bImage\b", text, re.IGNORECASE):
            input_type = "Vision"

        age_text = extract_age_text(text)
        tag_short = tag.split(":", 1)[1] if ":" in tag else tag

        variants.append(VariantParsed(
            family_slug=slug,
            tag=tag,
            tag_short=tag_short,
            digest=digest,
            size_bytes=size_bytes,
            max_context=max_context,
            input_type=input_type,
            catalog_age_text=age_text,
        ))
        seen_tags.add(tag)

    return family, variants

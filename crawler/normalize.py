from __future__ import annotations
import re
from typing import Optional

_UNIT_MULT = {
    "KB": 1024**1,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}

_SUFFIX_MULT = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

def parse_human_number(s: str) -> Optional[int]:
    m = re.search(r"(?P<num>\d+(?:\.\d+)?)(?P<suf>[KMB])\b", s)
    if m:
        return int(float(m.group("num")) * _SUFFIX_MULT[m.group("suf")])
    m2 = re.search(r"\b(\d[\d,]*)\b", s)
    if m2:
        return int(m2.group(1).replace(",", ""))
    return None

def parse_size_bytes(text: str) -> int:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)\b", text, re.IGNORECASE)
    if not m:
        raise ValueError(f"Could not parse size from: {text!r}")
    num = float(m.group(1))
    unit = m.group(2).upper()
    return int(num * _UNIT_MULT[unit])

def parse_context_tokens(text: str) -> Optional[int]:
    m = re.search(r"\b(\d+(?:\.\d+)?)([KMB])?\b", text)
    if not m:
        return None
    num = float(m.group(1))
    suf = m.group(2)
    if suf == "K":
        return int(num * 1024)
    if suf == "M":
        return int(num * 1024 * 1024)
    if suf == "B":
        return int(num)
    return int(num)

def extract_age_text(text: str) -> Optional[str]:
    m = re.search(r"(\d+\s+(?:day|week|month|year)s?\s+ago)", text)
    return m.group(1) if m else None

def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

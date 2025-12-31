from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional, Literal

GiB = 1024 ** 3

@dataclass(frozen=True)
class VramEstimate:
    total_gib_opt: float
    total_gib_cons: float
    weights_gib: float
    kv_gib_opt: float
    kv_gib_cons: float
    runtime_overhead_gib: float
    confidence: Literal["low","medium"]
    notes: str

def _parse_param_tier_b(tag: str) -> Optional[float]:
    '''
    Try to infer parameter tier from the tag string:
    - deepseek-r1:671b-fp16 -> 671
    - mixtral:8x7b -> 56
    - qwen2.5:0.5b -> 0.5
    '''
    m = re.search(r":(\d+)x(\d+(?:\.\d+)?)b\b", tag, re.IGNORECASE)
    if m:
        return float(m.group(1)) * float(m.group(2))
    m = re.search(r":(\d+(?:\.\d+)?)b\b", tag, re.IGNORECASE)
    if m:
        return float(m.group(1))
    m = re.search(r":(\d+(?:\.\d+)?)m\b", tag, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 1000.0
    return None

def _tier_profile(tier_b: Optional[float]) -> tuple[int,int,float,float,Literal["low","medium"],str]:
    '''
    Returns (n_layers, d_model, gqa_opt, gqa_cons, confidence, note)

    These are rough heuristics; they exist to give useful ranges until verified.
    '''
    if tier_b is None:
        return (40, 5120, 1.0, 1.0, "low", "tier unknown; using ~13B proxy for KV sizing")
    if tier_b <= 3:
        return (26, 3072, 1.0, 1.0, "medium", "~3B profile")
    if tier_b <= 9:
        return (32, 4096, 1.0, 1.0, "medium", "~7-8B profile")
    if tier_b <= 15:
        return (40, 5120, 1.0, 1.0, "medium", "~13-14B profile")
    if tier_b <= 40:
        return (48, 8192, 0.5, 1.0, "medium", "~30-34B profile (GQA optimistic)")
    if tier_b <= 80:
        return (80, 8192, 0.25, 1.0, "medium", "~70B profile (GQA optimistic)")
    return (80, 10240, 0.25, 1.0, "medium", ">100B profile (GQA optimistic)")

def _kv_bytes_per_elem(kv_cache_type: str) -> float:
    kv_cache_type = kv_cache_type.lower()
    if kv_cache_type in ("fp16","f16"):
        return 2.0
    if kv_cache_type in ("fp32","f32"):
        return 4.0
    if kv_cache_type in ("q8","q8_0","int8"):
        return 1.0
    if kv_cache_type in ("q4","int4"):
        return 0.5
    return 2.0

def estimate_vram_total_gib(
    *,
    size_bytes: int,
    tag: str,
    context_tokens: int,
    kv_cache_type: str = "fp16",
    offload_fraction: float = 1.0,
) -> VramEstimate:
    # Weights
    weights_gib = (size_bytes / GiB)
    weights_overhead_factor = 1.05
    weights_vram_gib = weights_gib * weights_overhead_factor * float(offload_fraction)

    # Runtime overhead (rough, but stabilizes low-end estimates)
    runtime_overhead_gib = 0.8 + 0.02 * weights_gib
    runtime_overhead_gib = min(8.0, max(0.8, runtime_overhead_gib))

    # KV cache
    tier_b = _parse_param_tier_b(tag)
    n_layers, d_model, gqa_opt, gqa_cons, confidence, tier_note = _tier_profile(tier_b)
    kv_bpe = _kv_bytes_per_elem(kv_cache_type)

    kv_overhead_factor = 1.10 if kv_cache_type.lower() in ("q4","int4") else 1.0

    kv_bytes_per_token_opt = 2.0 * n_layers * d_model * gqa_opt * kv_bpe
    kv_bytes_per_token_cons = 2.0 * n_layers * d_model * gqa_cons * kv_bpe

    kv_gib_opt = (kv_bytes_per_token_opt * context_tokens / GiB) * kv_overhead_factor
    kv_gib_cons = (kv_bytes_per_token_cons * context_tokens / GiB) * kv_overhead_factor

    total_opt = weights_vram_gib + kv_gib_opt + runtime_overhead_gib
    total_cons = weights_vram_gib + kv_gib_cons + runtime_overhead_gib

    notes = (
        "ESTIMATED: weights derived from catalog size; KV cache inferred from tier heuristics; "
        f"kv_cache_type={kv_cache_type}; offload_fraction={offload_fraction}; {tier_note}."
    )

    return VramEstimate(
        total_gib_opt=float(total_opt),
        total_gib_cons=float(total_cons),
        weights_gib=float(weights_vram_gib),
        kv_gib_opt=float(kv_gib_opt),
        kv_gib_cons=float(kv_gib_cons),
        runtime_overhead_gib=float(runtime_overhead_gib),
        confidence=confidence,
        notes=notes,
    )

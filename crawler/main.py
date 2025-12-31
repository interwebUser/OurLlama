from __future__ import annotations
import argparse
import time
from typing import Dict
from .http import fetch_text
from .parse import parse_library_slugs, parse_family_and_variants_from_tags_page
from .db import (
    connect,
    get_db_url,
    start_crawl_run,
    finish_crawl_run,
    ensure_estimate_profile,
    upsert_family,
    upsert_variant,
    insert_estimate,
)
from .vram import estimate_vram_total_gib

DEFAULT_BASE = "https://ollama.com"
DEFAULT_DELAY_S = 0.35

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=None, help="Postgres URL (or use DATABASE_URL env var)")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_S, help="Delay between requests (seconds)")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of families (debug)")
    ap.add_argument("--estimate", action="store_true", help="Write first-pass VRAM estimates to DB")
    ap.add_argument("--kv-cache-type", default="fp16", help="KV cache type for estimates (fp16/q8/q4)")
    ap.add_argument("--context-default", type=int, default=8192, help="Default context tokens for estimates")
    args = ap.parse_args()

    db_url = get_db_url(args.db_url)

    with connect(db_url) as conn:
        conn.autocommit = False
        run_id = start_crawl_run(conn)
        stats: Dict[str, int] = {
            "families_seen": 0,
            "variants_seen": 0,
            "families_failed": 0,
            "variants_failed": 0,
            "estimates_written": 0,
        }

        profile_id = None
        if args.estimate:
            profile_id = ensure_estimate_profile(conn,
                name="vram_estimator",
                version="1.0.0",
                assumptions={
                    "weights_overhead_factor": 1.05,
                    "runtime_overhead": "0.8 + 0.02 * weights_gib, clamped [0.8, 8.0]",
                    "kv_cache_type_default": args.kv_cache_type,
                    "tier_profiles": "heuristic: (n_layers, d_model, gqa_opt/cons) by parameter tier",
                }
            )

        try:
            library_url = f"{args.base_url.rstrip('/')}/library"
            lib_html = fetch_text(library_url)
            slugs = parse_library_slugs(lib_html)
            if args.limit and args.limit > 0:
                slugs = slugs[:args.limit]

            for slug in slugs:
                stats["families_seen"] += 1
                tags_url = f"{args.base_url.rstrip('/')}/library/{slug}/tags"
                try:
                    html = fetch_text(tags_url)
                    fam, variants = parse_family_and_variants_from_tags_page(html, slug)
                except Exception:
                    stats["families_failed"] += 1
                    time.sleep(args.delay)
                    continue

                family_id, family_first_seen_at = upsert_family(conn, fam)
                family_first_seen_at = family_first_seen_at or "now()"

                for var in variants:
                    stats["variants_seen"] += 1
                    try:
                        variant_id = upsert_variant(conn, family_id, family_first_seen_at, var)
                    except Exception:
                        stats["variants_failed"] += 1
                        continue

                    if args.estimate and profile_id:
                        ctx_points = set([args.context_default])
                        if var.max_context and var.max_context > 0:
                            ctx_points.add(var.max_context)

                        for ctx in sorted(ctx_points):
                            est = estimate_vram_total_gib(
                                size_bytes=var.size_bytes,
                                tag=var.tag,
                                context_tokens=int(ctx),
                                kv_cache_type=args.kv_cache_type,
                                offload_fraction=1.0,
                            )
                            insert_estimate(
                                conn,
                                variant_id=variant_id,
                                profile_id=profile_id,
                                estimate_type="vram_total_gib_opt",
                                value=est.total_gib_opt,
                                units="GiB",
                                context_tokens=int(ctx),
                                kv_cache_type=args.kv_cache_type,
                                offload_fraction=1.0,
                                confidence=est.confidence,
                                verification="estimated",
                            )
                            insert_estimate(
                                conn,
                                variant_id=variant_id,
                                profile_id=profile_id,
                                estimate_type="vram_total_gib_cons",
                                value=est.total_gib_cons,
                                units="GiB",
                                context_tokens=int(ctx),
                                kv_cache_type=args.kv_cache_type,
                                offload_fraction=1.0,
                                confidence=est.confidence,
                                verification="estimated",
                            )
                            stats["estimates_written"] += 2

                conn.commit()
                time.sleep(args.delay)

            finish_crawl_run(conn, run_id, "success", stats)
            conn.commit()
            print("Crawl complete:", stats)

        except Exception as e:
            conn.rollback()
            finish_crawl_run(conn, run_id, "failed", {**stats, "error": str(e)})
            conn.commit()
            raise

if __name__ == "__main__":
    main()

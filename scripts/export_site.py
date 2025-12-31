from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def to_regclass(cur, name: str):
    cur.execute("SELECT to_regclass(%s) AS r;", (name,))
    return cur.fetchone()["r"]


def table_exists(cur, table: str) -> bool:
    return to_regclass(cur, f"public.{table}") is not None


def view_exists(cur, view: str) -> bool:
    return to_regclass(cur, f"public.{view}") is not None


def require_tables(cur, tables: list[str]):
    missing = [t for t in tables if not table_exists(cur, t)]
    if not missing:
        return
    cur.execute(
        """SELECT tablename
           FROM pg_catalog.pg_tables
           WHERE schemaname='public'
           ORDER BY tablename;"""
    )
    existing = [r["tablename"] for r in cur.fetchall()]
    raise SystemExit(
        "Schema not applied correctly. Missing required tables: "
        f"{missing}. Existing public tables: {existing}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL", ""))
    ap.add_argument("--out", default="site/data/catalog.json")
    args = ap.parse_args()

    if not args.db_url:
        raise SystemExit("DATABASE_URL is required")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    with psycopg.connect(args.db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            require_tables(cur, ["model_family", "model_variant", "estimate_profile", "derived_estimate"])

            # Workflows / toolchains (seeded by migration)
            workflows = []
            if table_exists(cur, "workflow"):
                cur.execute("SELECT slug, name, description, category FROM workflow ORDER BY name;")
                workflows = cur.fetchall()

            toolchains = []
            if table_exists(cur, "toolchain"):
                cur.execute("SELECT slug, display_name, description, kind, components FROM toolchain ORDER BY display_name;")
                toolchains = cur.fetchall()

            # Tags + effective family tags
            tags = []
            if table_exists(cur, "tag"):
                cur.execute("SELECT slug, name, category, description FROM tag ORDER BY category, name;")
                tags = cur.fetchall()

            family_tags = []
            if view_exists(cur, "v_family_tags_effective"):
                cur.execute(
                    """SELECT family_id::text AS family_id,
                                 tag_slug,
                                 confidence::float8 AS confidence,
                                 source,
                                 verification::text AS verification
                          FROM v_family_tags_effective
                          ORDER BY family_id, tag_slug;"""
                )
                family_tags = cur.fetchall()

            constraint_profiles = []
            if table_exists(cur, "constraint_profile"):
                cur.execute(
                    """SELECT slug, display_name,
                                 vram_gib::float8 AS vram_gib,
                                 ram_gib::float8 AS ram_gib,
                                 gpu_model, cpu_model, notes,
                                 verification::text AS verification
                          FROM constraint_profile
                          ORDER BY display_name;"""
                )
                constraint_profiles = cur.fetchall()

            # Core catalog
            cur.execute(
                """SELECT id::text AS id,
                             slug, display_name, description, labels,
                             downloads,
                             catalog_first_seen_at::text, last_seen_at::text,
                             upstream_published_at::text,
                             verification::text AS verification
                      FROM model_family
                      ORDER BY slug;"""
            )
            families = cur.fetchall()

            cur.execute(
                """SELECT mv.id::text AS id,
                             mf.id::text AS family_id,
                             mf.slug AS family_slug,
                             mv.tag, mv.tag_short, mv.digest,
                             mv.size_bytes,
                             (mv.size_bytes::numeric/(1024^3))::float8 AS size_gib,
                             mv.max_context, mv.input_type,
                             mv.catalog_first_seen_at::text, mv.last_seen_at::text,
                             mv.upstream_published_at::text,
                             mv.verification::text AS verification
                      FROM model_variant mv
                      JOIN model_family mf ON mf.id = mv.family_id
                      ORDER BY mf.slug, mv.tag;"""
            )
            variants = cur.fetchall()

            # Components for VRAM fit math (computed by estimator)
            comps = []
            if view_exists(cur, "v_variant_vram_components"):
                cur.execute(
                    """SELECT variant_id::text,
                                 family_slug,
                                 tag,
                                 weights_vram_gib::float8,
                                 runtime_overhead_gib::float8,
                                 kv_bytes_per_token_opt::float8,
                                 kv_bytes_per_token_cons::float8,
                                 kv_cache_type
                          FROM v_variant_vram_components
                          ORDER BY family_slug, tag;"""
                )
                comps = cur.fetchall()

            # Aggregations (community signal) - export empty if not present yet
            run_agg = []
            if view_exists(cur, "v_workflow_run_agg") and table_exists(cur, "workflow") and table_exists(cur, "toolchain"):
                cur.execute(
                    """SELECT
                           wr.variant_id::text AS variant_id,
                           w.slug AS workflow_slug,
                           tc.slug AS toolchain_slug,
                           wr.run_count::bigint,
                           wr.run_count_trusted::bigint,
                           wr.p50_tps::float8,
                           wr.p50_ttft_ms::float8,
                           wr.avg_quality::float8,
                           wr.avg_success::float8,
                           wr.avg_stability::float8,
                           wr.last_run_at::text
                         FROM v_workflow_run_agg wr
                         JOIN workflow w ON w.id = wr.workflow_id
                         JOIN toolchain tc ON tc.id = wr.toolchain_id
                         ORDER BY w.slug, tc.slug;"""
                )
                run_agg = cur.fetchall()

            best_templates = []
            if view_exists(cur, "v_best_task_template") and table_exists(cur, "workflow"):
                if table_exists(cur, "toolchain"):
                    cur.execute(
                        """SELECT
                               coalesce(vbt.variant_id::text, null) AS variant_id,
                               w.slug AS workflow_slug,
                               tc.slug AS toolchain_slug,
                               vbt.task_name,
                               vbt.temperature::float8,
                               vbt.top_k,
                               vbt.top_p::float8,
                               vbt.context_usage_pct::float8,
                               vbt.notes,
                               vbt.vote_count::bigint,
                               vbt.vote_sum::bigint,
                               vbt.submitted_at::text,
                               vbt.verification::text
                             FROM v_best_task_template vbt
                             JOIN workflow w ON w.id = vbt.workflow_id
                             LEFT JOIN toolchain tc ON tc.id = vbt.toolchain_id
                             ORDER BY w.slug;"""
                    )
                else:
                    cur.execute(
                        """SELECT
                               coalesce(vbt.variant_id::text, null) AS variant_id,
                               w.slug AS workflow_slug,
                               null::text AS toolchain_slug,
                               vbt.task_name,
                               vbt.temperature::float8,
                               vbt.top_k,
                               vbt.top_p::float8,
                               vbt.context_usage_pct::float8,
                               vbt.notes,
                               vbt.vote_count::bigint,
                               vbt.vote_sum::bigint,
                               vbt.submitted_at::text,
                               vbt.verification::text
                             FROM v_best_task_template vbt
                             JOIN workflow w ON w.id = vbt.workflow_id
                             ORDER BY w.slug;"""
                    )
                best_templates = cur.fetchall()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workflows": workflows,
        "toolchains": toolchains,
        "tags": tags,
        "family_tags": family_tags,
        "constraint_profiles": constraint_profiles,
        "families": families,
        "variants": variants,
        "variant_components": comps,
        "workflow_run_agg": run_agg,
        "best_templates": best_templates,
        "notes": {
            "deployment": "GitHub Pages is static; data is generated in CI and published as JSON.",
            "verification": "Many fields are estimated or inferred unless explicitly marked verified.",
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(
        f"Wrote {args.out} "
        f"(families={len(families)}, variants={len(variants)}, comps={len(comps)}, "
        f"workflows={len(workflows)}, toolchains={len(toolchains)}, tags={len(tags)})"
    )


if __name__ == "__main__":
    main()

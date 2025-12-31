from __future__ import annotations
import os, json, argparse
import psycopg
from psycopg.rows import dict_row
from datetime import datetime, timezone

DEFAULT_WORKFLOWS = [
    {"slug": "web-dev", "name": "Web Development", "description": "Coding workflows in an editor/IDE with an assistant/agent.", "category": "software"},
    {"slug": "video-editing", "name": "Video Editing", "description": "Script, subtitle, and editing assistant workflows.", "category": "creative"},
]

DEFAULT_TOOLCHAINS = [
    {"slug": "vscode+roo-code", "display_name": "VSCode + Roo Code", "description": "Agentic coding in VSCode using Roo Code."},
    {"slug": "vscode+continue", "display_name": "VSCode + Continue", "description": "Coding assistant in VSCode using Continue."},
    {"slug": "cli+aider", "display_name": "CLI + Aider", "description": "Agentic coding via Aider in the terminal."},
    {"slug": "openwebui+ollama", "display_name": "Open WebUI + Ollama", "description": "Chat UI over local Ollama runtime."},
]

def to_regclass(cur, name: str):
    cur.execute("SELECT to_regclass(%s) AS r;", (name,))
    row = cur.fetchone()
    return row["r"]

def table_exists(cur, table: str) -> bool:
    return to_regclass(cur, f"public.{table}") is not None

def view_exists(cur, view: str) -> bool:
    return to_regclass(cur, f"public.{view}") is not None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=os.environ.get("DATABASE_URL",""))
    ap.add_argument("--out", default="site/data/catalog.json")
    args = ap.parse_args()

    if not args.db_url:
        raise SystemExit("DATABASE_URL is required")

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with psycopg.connect(args.db_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            required = ["model_family", "model_variant", "derived_estimate", "estimate_profile"]
            missing_required = [t for t in required if not table_exists(cur, t)]
            if missing_required:
                cur.execute("""
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname='public'
                    ORDER BY tablename;
                """)
                existing = [r["tablename"] for r in cur.fetchall()]
                raise SystemExit(
                    "Schema not applied correctly. Missing required tables: "
                    f"{missing_required}. Existing tables: {existing}"
                )

            # Optional workflow layer
            if table_exists(cur, "workflow"):
                cur.execute("SELECT slug, name, description, category FROM workflow ORDER BY name;")
                workflows = cur.fetchall()
            else:
                workflows = DEFAULT_WORKFLOWS

            if table_exists(cur, "toolchain"):
                cur.execute("SELECT slug, display_name, description FROM toolchain ORDER BY display_name;")
                toolchains = cur.fetchall()
            else:
                toolchains = DEFAULT_TOOLCHAINS

            # Core catalog
            cur.execute("""
                SELECT id::text AS id, slug, display_name, description, labels, downloads,
                       catalog_first_seen_at::text, last_seen_at::text, verification
                FROM model_family
                ORDER BY slug;
            """)
            families = cur.fetchall()

            cur.execute("""
                SELECT mv.id::text AS id, mf.slug AS family_slug, mv.tag, mv.tag_short, mv.digest,
                       mv.size_bytes, (mv.size_bytes::numeric/(1024^3))::float8 AS size_gib,
                       mv.max_context, mv.input_type,
                       mv.catalog_first_seen_at::text, mv.last_seen_at::text, mv.verification
                FROM model_variant mv
                JOIN model_family mf ON mf.id = mv.family_id
                ORDER BY mf.slug, mv.tag;
            """)
            variants = cur.fetchall()

            # Components for VRAM fit math
            if view_exists(cur, "v_variant_vram_components"):
                cur.execute("""
                    SELECT variant_id::text,
                           weights_vram_gib::float8,
                           runtime_overhead_gib::float8,
                           kv_bytes_per_token_opt::float8,
                           kv_bytes_per_token_cons::float8,
                           kv_cache_type
                    FROM v_variant_vram_components
                    ORDER BY family_slug, tag;
                """)
                comps = cur.fetchall()
            else:
                comps = []

            # Optional aggregations
            if view_exists(cur, "v_workflow_run_agg") and table_exists(cur, "workflow") and table_exists(cur, "toolchain"):
                cur.execute("""
                    SELECT
                      wr.variant_id::text AS variant_id,
                      w.slug AS workflow_slug,
                      tc.slug AS toolchain_slug,
                      wr.run_count::bigint,
                      wr.run_count_trusted::bigint,
                      wr.p50_tps::float8,
                      wr.p50_ttft_ms::float8,
                      wr.avg_quality::float8,
                      wr.avg_success::float8,
                      wr.last_run_at::text
                    FROM v_workflow_run_agg wr
                    JOIN workflow w ON w.id = wr.workflow_id
                    JOIN toolchain tc ON tc.id = wr.toolchain_id
                    ORDER BY w.slug, tc.slug;
                """)
                run_agg = cur.fetchall()
            else:
                run_agg = []

            if view_exists(cur, "v_best_task_template") and table_exists(cur, "workflow"):
                if table_exists(cur, "toolchain"):
                    cur.execute("""
                        SELECT
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
                        ORDER BY w.slug;
                    """)
                else:
                    cur.execute("""
                        SELECT
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
                        ORDER BY w.slug;
                    """)
                best_templates = cur.fetchall()
            else:
                best_templates = []

# Tags (explicit + inferred)
if table_exists(cur, "tag"):
    cur.execute("SELECT slug, name, category, description FROM tag ORDER BY category, name;")
    tags = cur.fetchall()
else:
    tags = []

if view_exists(cur, "v_family_tags_effective"):
    cur.execute("""
        SELECT family_id::text AS family_id,
               tag_slug,
               confidence::float8 AS confidence,
               source,
               verification::text AS verification
        FROM v_family_tags_effective
        ORDER BY family_id, tag_slug;
    """)
    family_tags = cur.fetchall()
else:
    family_tags = []

if table_exists(cur, "constraint_profile"):
    cur.execute("""
        SELECT slug, display_name, vram_gib::float8 AS vram_gib, ram_gib::float8 AS ram_gib,
               gpu_model, cpu_model, notes, verification::text AS verification
        FROM constraint_profile
        ORDER BY display_name;
    """)
    constraint_profiles = cur.fetchall()
else:
    constraint_profiles = []

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
            "deployment": "Static GitHub Pages build. No live DB/API in this mode.",
            "estimates": "VRAM/KV values are estimated unless explicitly verified.",
        },
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {out_path} (families={len(families)}, variants={len(variants)}, comps={len(comps)})")

if __name__ == "__main__":
    main()

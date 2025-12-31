from __future__ import annotations
import os
import json
import psycopg
from psycopg.rows import dict_row
from typing import Optional, Tuple
from .types import FamilyParsed, VariantParsed

def get_db_url(cli_db_url: Optional[str] = None) -> str:
    return cli_db_url or os.environ.get("DATABASE_URL", "")

def connect(db_url: str) -> psycopg.Connection:
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(db_url, row_factory=dict_row)

def start_crawl_run(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO crawl_run DEFAULT VALUES RETURNING id;")
        rid = cur.fetchone()["id"]
        return str(rid)

def finish_crawl_run(conn: psycopg.Connection, run_id: str, status: str, stats: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE crawl_run SET finished_at = now(), status = %s, stats_json = %s WHERE id = %s",
            (status, json.dumps(stats), run_id),
        )

def ensure_estimate_profile(conn: psycopg.Connection, name: str, version: str, assumptions: dict) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO estimate_profile (name, version, assumptions_json)
            VALUES (%s, %s, %s)
            ON CONFLICT (name, version) DO UPDATE SET assumptions_json = EXCLUDED.assumptions_json
            RETURNING id;
            """,
            (name, version, json.dumps(assumptions)),
        )
        return str(cur.fetchone()["id"])

def upsert_family(conn: psycopg.Connection, fam: FamilyParsed) -> Tuple[str, Optional[str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_family (slug, display_name, description, labels, downloads, catalog_updated_text, last_seen_at, verification)
            VALUES (%s, %s, %s, %s, %s, %s, now(), 'catalog')
            ON CONFLICT (slug) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              description = EXCLUDED.description,
              labels = EXCLUDED.labels,
              downloads = EXCLUDED.downloads,
              catalog_updated_text = EXCLUDED.catalog_updated_text,
              last_seen_at = now(),
              verification = 'catalog'
            RETURNING id, catalog_first_seen_at::text;
            """,
            (fam.slug, fam.display_name, fam.description, fam.labels, fam.downloads, fam.catalog_updated_text),
        )
        row = cur.fetchone()
        return (str(row["id"]), row["catalog_first_seen_at"])

def upsert_variant(conn: psycopg.Connection, family_id: str, family_first_seen_at: str, var: VariantParsed) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_variant
              (family_id, tag, tag_short, digest, size_bytes, max_context, input_type, catalog_age_text,
               catalog_first_seen_at, last_seen_at, verification)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s,
               %s::timestamptz, now(), 'catalog')
            ON CONFLICT (family_id, tag) DO UPDATE SET
              tag_short = EXCLUDED.tag_short,
              digest = EXCLUDED.digest,
              size_bytes = EXCLUDED.size_bytes,
              max_context = EXCLUDED.max_context,
              input_type = EXCLUDED.input_type,
              catalog_age_text = EXCLUDED.catalog_age_text,
              last_seen_at = now(),
              verification = 'catalog'
            RETURNING id;
            """,
            (family_id, var.tag, var.tag_short, var.digest, var.size_bytes, var.max_context, var.input_type, var.catalog_age_text, family_first_seen_at),
        )
        return str(cur.fetchone()["id"])

def insert_estimate(
    conn: psycopg.Connection,
    *,
    variant_id: str,
    profile_id: str,
    estimate_type: str,
    value: float,
    units: str,
    context_tokens: int,
    kv_cache_type: str,
    offload_fraction: float,
    confidence: str,
    verification: str = "estimated",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO derived_estimate
              (variant_id, estimate_profile_id, estimate_type, value, units, context_tokens, kv_cache_type, offload_fraction, confidence, verification)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (variant_id, profile_id, estimate_type, value, units, context_tokens, kv_cache_type, offload_fraction, confidence, verification),
        )

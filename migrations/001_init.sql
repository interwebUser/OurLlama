BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'verification_status') THEN
    CREATE TYPE verification_status AS ENUM ('catalog','estimated','community_verified','admin_verified');
  END IF;
END$$;

CREATE TABLE IF NOT EXISTS crawl_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL DEFAULT 'running',
  stats_json jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS model_family (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  display_name text,
  description text,
  labels text[] NOT NULL DEFAULT '{}'::text[],
  downloads bigint,
  catalog_updated_text text,
  upstream_published_at timestamptz,
  catalog_first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  verification verification_status NOT NULL DEFAULT 'catalog',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_variant (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  family_id uuid NOT NULL REFERENCES model_family(id) ON DELETE CASCADE,
  tag text NOT NULL,
  tag_short text,
  digest text,
  size_bytes bigint NOT NULL,
  max_context int,
  input_type text,
  catalog_age_text text,
  upstream_published_at timestamptz,
  catalog_first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  verification verification_status NOT NULL DEFAULT 'catalog',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (family_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_model_variant_tag ON model_variant(tag);
CREATE INDEX IF NOT EXISTS idx_model_variant_size_bytes ON model_variant(size_bytes);
CREATE INDEX IF NOT EXISTS idx_model_variant_max_context ON model_variant(max_context);

CREATE TABLE IF NOT EXISTS estimate_profile (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  version text NOT NULL,
  assumptions_json jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS derived_estimate (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_id uuid NOT NULL REFERENCES model_variant(id) ON DELETE CASCADE,
  estimate_profile_id uuid NOT NULL REFERENCES estimate_profile(id) ON DELETE RESTRICT,
  estimate_type text NOT NULL,
  value numeric NOT NULL,
  units text NOT NULL,
  context_tokens int,
  kv_cache_type text,
  offload_fraction numeric,
  confidence text,
  verification verification_status NOT NULL DEFAULT 'estimated',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_derived_estimate_variant_id ON derived_estimate(variant_id);
CREATE INDEX IF NOT EXISTS idx_derived_estimate_type ON derived_estimate(estimate_type);

CREATE OR REPLACE FUNCTION apply_upstream_first_seen() RETURNS trigger AS $$
BEGIN
  IF NEW.upstream_published_at IS NOT NULL AND NEW.catalog_first_seen_at > NEW.upstream_published_at THEN
    NEW.catalog_first_seen_at := NEW.upstream_published_at;
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_family_upstream_first_seen ON model_family;
CREATE TRIGGER trg_family_upstream_first_seen
BEFORE INSERT OR UPDATE ON model_family
FOR EACH ROW EXECUTE FUNCTION apply_upstream_first_seen();

DROP TRIGGER IF EXISTS trg_variant_upstream_first_seen ON model_variant;
CREATE TRIGGER trg_variant_upstream_first_seen
BEFORE INSERT OR UPDATE ON model_variant
FOR EACH ROW EXECUTE FUNCTION apply_upstream_first_seen();

COMMIT;

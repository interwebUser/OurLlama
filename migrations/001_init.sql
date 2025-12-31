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


-- ---------------------------------------------------------------------------
-- Workflow / Toolchain / Tags (seeded examples)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workflow (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  description text,
  category text NOT NULL DEFAULT 'other',
  default_context_tokens int,
  default_kv_cache_type text,
  verification verification_status NOT NULL DEFAULT 'admin_verified',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS toolchain (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  display_name text NOT NULL,
  description text,
  kind text NOT NULL DEFAULT 'other',
  components jsonb NOT NULL DEFAULT '{}'::jsonb,
  verification verification_status NOT NULL DEFAULT 'admin_verified',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tag (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  name text NOT NULL,
  category text NOT NULL DEFAULT 'other',
  description text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tag_rule (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope text NOT NULL DEFAULT 'family', -- family | variant (future)
  pattern text NOT NULL,                -- postgres regex (used with ~*)
  tag_id uuid NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  confidence numeric NOT NULL DEFAULT 0.60,
  notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope, pattern, tag_id)
);

CREATE TABLE IF NOT EXISTS model_family_tag (
  family_id uuid NOT NULL REFERENCES model_family(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
  source text NOT NULL DEFAULT 'manual',
  confidence numeric NOT NULL DEFAULT 0.80,
  verification verification_status NOT NULL DEFAULT 'estimated',
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (family_id, tag_id)
);

CREATE OR REPLACE VIEW v_family_tags_inferred AS
SELECT
  mf.id AS family_id,
  t.id AS tag_id,
  t.slug AS tag_slug,
  tr.confidence AS confidence,
  'inferred_rule'::text AS source,
  'estimated'::verification_status AS verification
FROM model_family mf
JOIN tag_rule tr
  ON tr.scope = 'family'
 AND mf.slug ~* tr.pattern
JOIN tag t ON t.id = tr.tag_id;

CREATE OR REPLACE VIEW v_family_tags_effective AS
SELECT
  mft.family_id,
  mft.tag_id,
  t.slug AS tag_slug,
  mft.confidence,
  mft.source,
  mft.verification
FROM model_family_tag mft
JOIN tag t ON t.id = mft.tag_id
UNION ALL
SELECT
  v.family_id,
  v.tag_id,
  v.tag_slug,
  v.confidence,
  v.source,
  v.verification
FROM v_family_tags_inferred v;

-- ---------------------------------------------------------------------------
-- Community signals (runs + templates). Empty at first, but schema-ready.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS constraint_profile (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  display_name text NOT NULL,
  vram_gib numeric,
  ram_gib numeric,
  gpu_model text,
  cpu_model text,
  notes text,
  verification verification_status NOT NULL DEFAULT 'admin_verified',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_id uuid NOT NULL REFERENCES model_variant(id) ON DELETE CASCADE,
  workflow_id uuid NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
  toolchain_id uuid REFERENCES toolchain(id) ON DELETE SET NULL,
  constraint_profile_id uuid REFERENCES constraint_profile(id) ON DELETE SET NULL,
  context_tokens int,
  kv_cache_type text,
  tokens_per_second numeric,
  ttft_ms int,
  quality_score int,     -- 1-10
  success boolean,
  notes text,
  verification verification_status NOT NULL DEFAULT 'community_verified',
  submitted_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW v_workflow_run_agg AS
SELECT
  variant_id,
  workflow_id,
  toolchain_id,
  COUNT(*)::bigint AS run_count,
  COUNT(*) FILTER (WHERE verification IN ('community_verified','admin_verified'))::bigint AS run_count_trusted,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY tokens_per_second) AS p50_tps,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY ttft_ms) AS p50_ttft_ms,
  AVG(quality_score)::numeric AS avg_quality,
  AVG(CASE WHEN success THEN 1 ELSE 0 END)::numeric AS avg_success,
  MAX(submitted_at) AS last_run_at
FROM workflow_run
GROUP BY variant_id, workflow_id, toolchain_id;

CREATE TABLE IF NOT EXISTS task_template (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  variant_id uuid REFERENCES model_variant(id) ON DELETE CASCADE,
  family_id uuid REFERENCES model_family(id) ON DELETE CASCADE,
  workflow_id uuid NOT NULL REFERENCES workflow(id) ON DELETE CASCADE,
  toolchain_id uuid REFERENCES toolchain(id) ON DELETE SET NULL,
  task_name text NOT NULL,
  system_prompt text,
  temperature numeric,
  top_k int,
  top_p numeric,
  context_usage_pct numeric,
  notes text,
  verification verification_status NOT NULL DEFAULT 'community_verified',
  submitted_at timestamptz NOT NULL DEFAULT now(),
  CHECK (variant_id IS NOT NULL OR family_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS template_vote (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  template_id uuid NOT NULL REFERENCES task_template(id) ON DELETE CASCADE,
  voter_fingerprint text NOT NULL,
  vote int NOT NULL, -- +1 / -1
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (template_id, voter_fingerprint)
);

CREATE OR REPLACE VIEW v_task_template_score AS
SELECT
  tt.*,
  COALESCE(SUM(tv.vote),0)::bigint AS vote_sum,
  COUNT(tv.*)::bigint AS vote_count
FROM task_template tt
LEFT JOIN template_vote tv ON tv.template_id = tt.id
GROUP BY tt.id;

CREATE OR REPLACE VIEW v_best_task_template AS
SELECT DISTINCT ON (workflow_id, COALESCE(toolchain_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(family_id, '00000000-0000-0000-0000-000000000000'::uuid))
  *
FROM v_task_template_score
ORDER BY
  workflow_id,
  COALESCE(toolchain_id, '00000000-0000-0000-0000-000000000000'::uuid),
  COALESCE(variant_id, '00000000-0000-0000-0000-000000000000'::uuid),
  COALESCE(family_id, '00000000-0000-0000-0000-000000000000'::uuid),
  vote_sum DESC,
  submitted_at DESC;

-- ---------------------------------------------------------------------------
-- VRAM components view (supports VRAM budget filtering + context math)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_variant_vram_components AS
SELECT
  mf.slug AS family_slug,
  mv.tag AS tag,
  mv.id AS variant_id,
  de.kv_cache_type,
  de.context_tokens,
  MAX(de.value) FILTER (WHERE de.estimate_type = 'vram_weights_gib')::float8 AS weights_vram_gib,
  MAX(de.value) FILTER (WHERE de.estimate_type = 'vram_runtime_overhead_gib')::float8 AS runtime_overhead_gib,
  MAX(de.value) FILTER (WHERE de.estimate_type = 'kv_bytes_per_token_opt')::float8 AS kv_bytes_per_token_opt,
  MAX(de.value) FILTER (WHERE de.estimate_type = 'kv_bytes_per_token_cons')::float8 AS kv_bytes_per_token_cons
FROM derived_estimate de
JOIN model_variant mv ON mv.id = de.variant_id
JOIN model_family mf ON mf.id = mv.family_id
JOIN estimate_profile ep ON ep.id = de.estimate_profile_id
WHERE ep.name = 'vram_estimator'
  AND ep.version = '1.0.0'
  AND de.offload_fraction = 1.0
GROUP BY mf.slug, mv.tag, mv.id, de.kv_cache_type, de.context_tokens;

-- ---------------------------------------------------------------------------
-- Seeds (real-world defaults; safe to rerun)
-- ---------------------------------------------------------------------------

INSERT INTO workflow (slug, name, description, category, default_context_tokens, default_kv_cache_type, verification)
VALUES
  ('web-dev', 'Web development', 'Coding in an editor/IDE with repo context, tests, and iterative prompting.', 'software', 8192, 'fp16', 'admin_verified'),
  ('code-review', 'Code review', 'Review diffs/PRs, suggest improvements, and enforce standards.', 'software', 8192, 'fp16', 'admin_verified'),
  ('debugging', 'Debugging', 'Investigate errors, logs, and reproduce/fix bugs.', 'software', 8192, 'fp16', 'admin_verified'),
  ('rag-building', 'RAG building', 'Build or tune retrieval + prompting + evaluation.', 'software', 8192, 'fp16', 'admin_verified'),
  ('data-analysis', 'Data analysis', 'Summarize and analyze datasets; notebooks; light coding.', 'data', 8192, 'fp16', 'admin_verified'),
  ('video-editing', 'Video editing', 'Script help, cut lists, captions/subtitles, and post-production notes.', 'creative', 8192, 'fp16', 'admin_verified'),
  ('transcription', 'Transcription', 'Speech-to-text, subtitle generation, and cleanup.', 'creative', 8192, 'fp16', 'admin_verified')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO toolchain (slug, display_name, description, kind, components, verification)
VALUES
  ('vscode+roo-code', 'VS Code + Roo Code', 'Agentic coding in VS Code using Roo Code (local models via Ollama).', 'ide',
    '{"editor":"VS Code","assistant":"Roo Code","runtime":"Ollama"}', 'admin_verified'),
  ('vscode+continue', 'VS Code + Continue', 'Coding assistant in VS Code using Continue (supports Ollama).', 'ide',
    '{"editor":"VS Code","assistant":"Continue","runtime":"Ollama"}', 'admin_verified'),
  ('vscode+cline', 'VS Code + Cline', 'Agentic coding in VS Code using Cline (tool-use, plans, execution).', 'ide',
    '{"editor":"VS Code","assistant":"Cline","runtime":"Ollama"}', 'admin_verified'),
  ('vscode+copilot', 'VS Code + Copilot', 'Popular coding assistant; often compared against local workflows.', 'ide',
    '{"editor":"VS Code","assistant":"Copilot"}', 'admin_verified'),
  ('cursor', 'Cursor', 'Agentic-first editor; common benchmark for local-agent parity.', 'ide',
    '{"editor":"Cursor"}', 'admin_verified'),
  ('jetbrains+ai', 'JetBrains + AI Assistant', 'JetBrains IDEs with AI Assistant / local integration via plugins.', 'ide',
    '{"editor":"JetBrains"}', 'admin_verified'),
  ('neovim+avante', 'Neovim + Avante', 'Neovim agentic workflow using Avante.nvim.', 'ide',
    '{"editor":"Neovim","assistant":"Avante.nvim","runtime":"Ollama"}', 'admin_verified'),
  ('cli+aider', 'CLI + Aider', 'Terminal-first agentic coding with repo mapping and patches.', 'cli',
    '{"assistant":"Aider","runtime":"Ollama"}', 'admin_verified'),
  ('openwebui+ollama', 'Open WebUI + Ollama', 'Web chat UI for Ollama; common baseline for chat workflows.', 'webui',
    '{"ui":"Open WebUI","runtime":"Ollama"}', 'admin_verified'),
  ('anythingllm+ollama', 'AnythingLLM + Ollama', 'Chat/RAG desktop/web app commonly paired with Ollama.', 'webui',
    '{"ui":"AnythingLLM","runtime":"Ollama"}', 'admin_verified'),
  ('n8n+ollama', 'n8n + Ollama', 'Automation workflows that call local models via HTTP.', 'automation',
    '{"orchestrator":"n8n","runtime":"Ollama"}', 'admin_verified')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO tag (slug, name, category, description)
VALUES
  ('chat', 'Chat', 'use_case', 'General chat / assistant behavior'),
  ('code', 'Code', 'use_case', 'Coding / software development'),
  ('reasoning', 'Reasoning', 'use_case', 'Deliberate reasoning / problem solving'),
  ('embedding', 'Embedding', 'use_case', 'Vector embeddings for retrieval'),
  ('multimodal', 'Multimodal', 'use_case', 'Text + vision/audio inputs'),
  ('math', 'Math', 'specialty', 'Strong mathematical ability'),
  ('creative', 'Creative', 'specialty', 'Creative writing / ideation'),
  ('technical', 'Technical', 'specialty', 'Technical explanation / documentation'),
  ('long-context', 'Long context', 'specialty', 'Useful with larger context windows'),
  ('instruction-tuned', 'Instruction tuned', 'training_focus', 'SFT/RLHF tuned for instruction following'),
  ('base', 'Base model', 'training_focus', 'Pretrained/base (not instruction tuned)')
ON CONFLICT (slug) DO NOTHING;

-- Heuristic tag rules (transparent + clearly marked as inferred)
INSERT INTO tag_rule (scope, pattern, tag_id, confidence, notes)
SELECT 'family', '(?i)(coder|code|program)', t.id, 0.65, 'Slug/name suggests code specialization'
FROM tag t WHERE t.slug='code'
ON CONFLICT DO NOTHING;

INSERT INTO tag_rule (scope, pattern, tag_id, confidence, notes)
SELECT 'family', '(?i)(embed|embedding)', t.id, 0.75, 'Slug/name suggests embeddings'
FROM tag t WHERE t.slug='embedding'
ON CONFLICT DO NOTHING;

INSERT INTO tag_rule (scope, pattern, tag_id, confidence, notes)
SELECT 'family', '(?i)(vision|vl|multimodal|clip)', t.id, 0.70, 'Slug/name suggests multimodal/vision'
FROM tag t WHERE t.slug='multimodal'
ON CONFLICT DO NOTHING;

INSERT INTO tag_rule (scope, pattern, tag_id, confidence, notes)
SELECT 'family', '(?i)(r1|reason)', t.id, 0.60, 'Slug/name suggests reasoning family'
FROM tag t WHERE t.slug='reasoning'
ON CONFLICT DO NOTHING;

INSERT INTO tag_rule (scope, pattern, tag_id, confidence, notes)
SELECT 'family', '(?i)(math)', t.id, 0.70, 'Slug/name suggests math specialization'
FROM tag t WHERE t.slug='math'
ON CONFLICT DO NOTHING;

INSERT INTO constraint_profile (slug, display_name, vram_gib, ram_gib, notes, verification)
VALUES
  ('gpu-8gb', 'GPU 8GB', 8, 32, 'Common entry-level discrete GPU budget', 'admin_verified'),
  ('gpu-12gb', 'GPU 12GB', 12, 32, 'Common midrange discrete GPU budget', 'admin_verified'),
  ('gpu-16gb', 'GPU 16GB', 16, 32, 'Higher headroom for larger models', 'admin_verified'),
  ('gpu-24gb', 'GPU 24GB', 24, 64, 'Creator / prosumer GPU headroom', 'admin_verified'),
  ('cpu-ram-64gb', 'CPU-only (64GB RAM)', NULL, 64, 'No GPU; relies on system RAM and CPU', 'admin_verified')
ON CONFLICT (slug) DO NOTHING;


DROP TRIGGER IF EXISTS trg_family_upstream_first_seen ON model_family;
CREATE TRIGGER trg_family_upstream_first_seen
BEFORE INSERT OR UPDATE ON model_family
FOR EACH ROW EXECUTE FUNCTION apply_upstream_first_seen();

DROP TRIGGER IF EXISTS trg_variant_upstream_first_seen ON model_variant;
CREATE TRIGGER trg_variant_upstream_first_seen
BEFORE INSERT OR UPDATE ON model_variant
FOR EACH ROW EXECUTE FUNCTION apply_upstream_first_seen();

COMMIT;

# OurLlama (Ollama Model Catalog) — Agent Rules (Roo Code)

## Mission (v1)
Ship a useful public catalog of Ollama models + variants with:
- practical metadata (context, size, tags, workflows/toolchains),
- VRAM-fit estimation (clearly labeled “estimated” unless verified),
- static GitHub Pages deployment (build-time crawl → export JSON → static UI),
- clean schema + reproducible build pipeline.

## Non-negotiables
- Keep **one migration** during v1: `migrations/001_init.sql` (idempotent, rerunnable).
- CI must be **deterministic**: a clean database starts empty and ends with complete schema + seeds.
- Always distinguish: **measured vs inferred vs user-submitted vs admin-verified**.

## Repo map (expected)
- `crawler/` : fetch registry catalog + normalize + write to DB
- `migrations/001_init.sql` : schema + seed workflows/toolchains/tags/profiles
- `scripts/export_site.py` : export DB → `site/data/catalog.json` (static artifact)
- `site/` : static UI consuming `site/data/catalog.json`
- `.github/workflows/pages.yml` : build + deploy pipeline

## Build pipeline (GitHub Pages)
1. Start Postgres service
2. Apply `migrations/001_init.sql`
3. Run crawler/estimator → write normalized rows + derived estimates
4. Run exporter → produce `site/data/catalog.json`
5. Deploy `site/` to Pages

## Coding standards for this repo
- Prefer small, reversible diffs. Add schema sanity checks in CI when debugging.
- No silent assumptions: if a field is estimated, label it in DB + exported JSON.
- Exporter must not crash if optional tables/views are absent; core tables are required.

## “Don’t waste tokens” policy
- Never read large generated artifacts unless needed (catalog JSON, caches, venvs).
- Respect `.rooignore`.

## When unsure
- Ask for clarification only if blocked; otherwise pick the safest default and document it.

# OurLlama — Ollama Model Catalog (VRAM-aware)

A lightweight, **VRAM-aware catalog** of models in the Ollama Library — designed to help you pick a model that actually fits your **hardware + context window**, and to surface “what works” for real workflows (web dev, debugging, RAG, etc.).

This repo ships a **static website** (GitHub Pages) generated daily by GitHub Actions:
- Crawl the Ollama Library (models + variants)
- Compute first-pass **VRAM estimates** (clearly labeled as *estimated*)
- Export a JSON catalog
- Deploy the site

> GitHub Pages is static. v1 is **read-only**: it publishes the catalog + estimates + seeded workflow/toolchain metadata.  
> Community submissions (runs/templates/votes) are in the schema but require a hosted API/DB to collect writes.

---

## What you can do on the site

- Search model families / variants
- Filter by:
  - **VRAM budget (GiB)**
  - **target context tokens**
  - **KV cache type**
  - **workflow** (web dev, debugging, refactor, transcription, …)
  - **toolchain** (VS Code + Roo Code, Continue, Cline, Cursor, …)
- Click any row for a detail view:
  - estimated VRAM breakdown (weights + runtime overhead + KV cache)
  - max context that fits (conservative)
  - workflow/toolchain “signal” (if present)

---

## How VRAM estimates work

VRAM is estimated as:

`weights_in_vram + runtime_overhead + (kv_bytes_per_token × context_tokens)`

- **Weights in VRAM**: derived from the model variant size + quantization tag where available.
- **Runtime overhead**: small fixed buffer for runtime allocations.
- **KV cache**: estimated bytes/token (conservative + optimistic) based on model family/size heuristics.

All of this is exported as *estimated* unless explicitly verified.

---

## Deploy on GitHub Pages (functional site)

1) Push this repo to GitHub  
2) GitHub → **Settings → Pages** → Source: **GitHub Actions**  
3) Run the workflow once (Actions → “Deploy Pages” → Run workflow) or push to `main`

The workflow:
1. starts Postgres as a CI service
2. applies `migrations/001_init.sql`
3. crawls Ollama Library + computes estimates
4. exports `site/data/catalog.json`
5. deploys `site/` to GitHub Pages

---

## Run locally

### Prereqs
- Docker Desktop (or Docker Engine)

### Start Postgres
```bash
docker compose up -d db
```

### Apply schema
```bash
docker compose run --rm crawler psql "$DATABASE_URL" -f migrations/001_init.sql
```

### Crawl + estimate
```bash
docker compose run --rm crawler python -m crawler.main --estimate --context-default 8192 --kv-cache-type fp16
```

### Export JSON for the site
```bash
docker compose run --rm crawler python scripts/export_site.py --out site/data/catalog.json
```

### Serve the site
```bash
docker compose up -d site
# open http://localhost:8080
```

---

## What’s seeded out of the box

To make v1 useful immediately, the migration seeds:
- **Workflows** (web-dev, debugging, refactor, RAG building, transcription, video editing, …)
- **Toolchains** (VS Code + Roo Code/Continue/Cline/Copilot, Cursor, Windsurf, JetBrains AI, …)
- **Tags + heuristic tag rules** (use case, specialty, training focus)

These seeds are marked `admin_verified` as “site defaults,” not as performance claims.

---

## Roadmap (optional)

- Add hosted DB + API for write operations:
  - submit workflow runs (TPS/TTFT/quality)
  - submit and vote on templates per workflow/toolchain
- Add admin verification UI and provenance tracking (measured vs inferred)

---

## License

MIT (or your preferred license).

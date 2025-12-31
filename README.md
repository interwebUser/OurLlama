# OurLlama — Ollama Model Catalog (with VRAM + workflow guidance)

OurLlama is a **model catalog and selection helper** for the Ollama ecosystem.

It publishes a static website (GitHub Pages) that answers the questions people actually have:

- *Which variants fit my VRAM budget at the context length I want?*
- *Which models work well for my workflow (web dev, debugging, RAG, video editing, etc.)?*
- *What’s measured vs inferred? (everything is labeled and verifiable)*

The catalog is generated in CI by crawling the Ollama Library and exporting a JSON dataset that the site loads.

---

## What the site does today

### ✅ Browse the full Ollama catalog
- Model families and variants
- Size, catalog max context, first-seen timestamps

### ✅ Filter by hardware constraints
- VRAM budget (GiB)
- Target context (tokens)
- KV cache type selector (affects the estimate)

> VRAM numbers are **estimates** intended to be useful, not perfect. The UI calls this out explicitly.

### ✅ Workflow + toolchain aware ranking (seeded)
The database is initialized with a realistic set of “seen in the wild” workflows and toolchains, such as:
- **Workflows:** Web dev, code review, debugging, RAG building, data analysis, video editing, transcription
- **Toolchains:** VS Code + Roo Code, Continue, Cline, Cursor, JetBrains AI, Neovim workflows, CLI + Aider, Open WebUI, AnythingLLM, n8n

Community signal tables exist (runs/templates/votes). The static Pages build exports them if present.

### ✅ Tagging (explicit + inferred)
We seed a tag taxonomy (use_case, specialty, training_focus) and apply lightweight heuristics to infer tags from model slugs.
All inferred tags are marked as inferred/estimated unless verified.

---

## Architecture

**Crawler → Normalizer → Postgres → JSON export → Static site**

- `crawler/`: fetches Ollama library/tag pages and writes normalized records
- `migrations/001_init.sql`: single “v1” schema + seeds (workflow/toolchain/tags)
- `scripts/export_site.py`: exports `site/data/catalog.json`
- `site/`: the static UI (filters + ranking)

GitHub Actions runs the pipeline and deploys Pages.

---

## Local development

### 1) Start Postgres
```bash
docker compose up -d db
```

### 2) Apply schema
```bash
psql "postgresql://postgres:postgres@localhost:5432/ollama_catalog" -f migrations/001_init.sql
```

### 3) Crawl + estimate
```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/ollama_catalog"
python -m crawler.main --estimate --context-default 8192 --kv-cache-type fp16
```

### 4) Export JSON + serve the site
```bash
python scripts/export_site.py --out site/data/catalog.json
python -m http.server 8080 --directory site
```

Open: http://localhost:8080

---

## Deploy to GitHub Pages

1. Push the repo to GitHub.
2. Repo Settings → **Pages** → Source: **GitHub Actions**
3. Run the workflow (Actions tab) or push to `main`.

The workflow:
1) starts Postgres  
2) applies `001_init.sql`  
3) crawls + estimates  
4) exports JSON  
5) deploys `/site` to GitHub Pages  

---

## Contributing

Right now the Pages site is read-only. The schema supports community submissions (runs/templates/votes), but the write-path is not published as an API in v1.

If you want to help:
- Propose new workflows/toolchains/tags by editing `migrations/001_init.sql`
- Improve tag inference rules
- Improve the VRAM estimator (clearly label changes as estimated)

---

## License

MIT

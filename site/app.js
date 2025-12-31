const GiB = 1024 ** 3;

function kvOverheadFactor(kv) {
  // Scale KV cache memory relative to fp16 baseline estimates.
  // fp16 ~= 2 bytes/elem; q8 ~= 1 byte/elem; q4 ~= 0.5 bytes/elem (with a conservative overhead).
  const k = (kv || 'fp16').toLowerCase();
  if (k === 'q8' || k === 'int8') return 0.50;
  if (k === 'q4' || k === 'int4') return 0.275; // 0.25 * 1.10 (slightly conservative)
  return 1.0;
}


function fmtNum(x, digits=2) {
  if (x === null || x === undefined || Number.isNaN(x)) return '';
  return Number(x).toFixed(digits);
}
function fmtInt(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '';
  return Math.round(Number(x)).toString();
}
function fmtGiB(x) {
  if (x === null || x === undefined || Number.isNaN(x)) return '';
  return fmtNum(x, 2) + ' GiB';
}
function fitTier(vramCons, vramOpt, budget) {
  if (!budget || budget <= 0) return 'unknown';
  if (vramCons <= budget) return 'fits_cons';
  if (vramOpt <= budget) return 'fits_opt';
  return 'no_fit';
}
function computeVram(weights, runtime, kvBytesPerTok, ctx, kvType) {
  const factor = kvOverheadFactor(kvType);
  return weights + runtime + ((kvBytesPerTok * ctx * factor) / GiB);
}
function maxCtxThatFits(budget, weights, runtime, kvBytesPerTok, kvType) {
  const factor = kvOverheadFactor(kvType);
  const headroom = budget - weights - runtime;
  if (headroom <= 0) return 0;
  return Math.floor((headroom * GiB) / (kvBytesPerTok * factor));
}

function rankScore({fitTier, runTrusted, p50tps, avgQuality, templateVoteSum}, preferQuality, minTps, maxTtft, p50ttft) {
  let score = 0;
  score += (fitTier === 'fits_cons') ? 100 : (fitTier === 'fits_opt') ? 60 : (fitTier === 'no_fit') ? -999 : 0;
  score += 10 * Math.log(1 + (runTrusted || 0));
  score += preferQuality ? (avgQuality || 0) * 4 : (p50tps || 0) * 0.8;
  score += Math.min(20, Math.max(0, (templateVoteSum || 0)));

  if (minTps != null && p50tps != null && p50tps < minTps) score -= 50;
  if (maxTtft != null && p50ttft != null && p50ttft > maxTtft) score -= 30;
  return score;
}

async function loadCatalog() {
  const res = await fetch('./data/catalog.json', {cache: 'no-store'});
  if (!res.ok) throw new Error(`Failed to load catalog.json: ${res.status}`);
  return await res.json();
}

function byId(list) {
  const m = new Map();
  for (const x of list) m.set(x.id, x);
  return m;
}

function el(id) { return document.getElementById(id); }

function option(text, value) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = text;
  return o;
}

function fitClass(tier) {
  if (tier === 'fits_cons') return 'good';
  if (tier === 'fits_opt') return 'warn';
  if (tier === 'no_fit') return 'bad';
  return '';
}

function rowHtml(r) {
  return `
    <tr data-variant="${r.variant_id}">
      <td>${r.family_slug}</td>
      <td class="kv">${r.tag_short}</td>
      <td class="num">${fmtGiB(r.size_gib)}</td>
      <td class="num">${fmtInt(r.max_context_catalog)}</td>
      <td class="fit ${fitClass(r.fit_tier)}">${r.fit_tier}</td>
      <td class="num">${fmtGiB(r.vram_required_cons_gib)}</td>
      <td class="num">${fmtGiB(r.vram_required_opt_gib)}</td>
      <td class="num">${fmtInt(r.max_context_tokens_cons)}</td>
      <td class="num">${fmtInt(r.run_count_trusted)}</td>
      <td class="num">${fmtNum(r.p50_tps, 1)}</td>
      <td class="num">${fmtInt(r.p50_ttft_ms)}</td>
      <td class="num">${fmtInt(r.template_vote_sum)}</td>
      <td class="num">${fmtNum(r.rank_score, 1)}</td>
    </tr>
  `;
}

function renderDetail(variant, family, comps, ctx, budget, kvType, runAgg, bestTemplate) {
  const weights = comps?.weights_vram_gib;
  const runtime = comps?.runtime_overhead_gib;
  const kvOpt = comps?.kv_bytes_per_token_opt;
  const kvCons = comps?.kv_bytes_per_token_cons;

  const vOpt = (weights!=null && runtime!=null && kvOpt!=null) ? computeVram(weights, runtime, kvOpt, ctx, kvType) : null;
  const vCons = (weights!=null && runtime!=null && kvCons!=null) ? computeVram(weights, runtime, kvCons, ctx, kvType) : null;

  const tier = (vOpt!=null && vCons!=null) ? fitTier(vCons, vOpt, budget) : 'unknown';

  const html = `
    <div class="muted">Family</div>
    <div style="margin-bottom:10px">
      <strong>${family.slug}</strong>
      <span class="badge">${family.verification}</span>
      <div class="muted" style="margin-top:6px">${family.description || ''}</div>
      <div class="muted" style="margin-top:6px">labels: ${(family.labels || []).join(', ') || '(none)'}</div>
    </div>

    <div class="muted">Variant</div>
    <div style="margin-bottom:10px">
      <div><span class="kv">${variant.tag}</span> <span class="badge">${variant.verification}</span></div>
      <div class="muted">size: ${fmtGiB(variant.size_gib)} · catalog max ctx: ${fmtInt(variant.max_context)} · input: ${variant.input_type || ''}</div>
      <div class="muted">first seen: ${variant.catalog_first_seen_at} · last seen: ${variant.last_seen_at}</div>
    </div>

    <div class="muted">Estimated VRAM @ ctx=${fmtInt(ctx)}, budget=${fmtGiB(budget)}, kv=${kvType}</div>
    <div style="margin-bottom:10px">
      <div>fit: <span class="fit ${fitClass(tier)}">${tier}</span></div>
      <div class="muted">conservative: ${fmtGiB(vCons)} · optimistic: ${fmtGiB(vOpt)}</div>
      <div class="muted">max ctx that fits (cons): ${fmtInt(maxCtxThatFits(budget, weights, runtime, kvCons, kvType))}</div>
      <div class="muted">components: weights=${fmtGiB(weights)} · runtime=${fmtGiB(runtime)} · kvBytes/token(cons)=${fmtInt(kvCons)} · kvBytes/token(opt)=${fmtInt(kvOpt)}</div>
      <div class="muted">note: KV sizing is inferred (tier heuristics). Marked as <span class="pill">estimated</span>.</div>
    </div>

    <div class="muted">Community signal (workflow + toolchain)</div>
    <div style="margin-bottom:10px">
      ${runAgg ? `
        <div class="muted">trusted runs: ${fmtInt(runAgg.run_count_trusted)} · p50 TPS: ${fmtNum(runAgg.p50_tps,1)} · p50 TTFT: ${fmtInt(runAgg.p50_ttft_ms)}</div>
        <div class="muted">avg quality: ${fmtNum(runAgg.avg_quality,1)} · avg success: ${fmtNum(runAgg.avg_success,1)} · last run: ${runAgg.last_run_at}</div>
      ` : `<div class="muted">No workflow runs recorded yet for this workflow/toolchain.</div>`}
    </div>

    <div class="muted">Best template</div>
    <div style="margin-bottom:10px">
      ${bestTemplate ? `
        <div><strong>${bestTemplate.task_name}</strong> <span class="badge">${bestTemplate.verification}</span></div>
        <div class="muted">temp=${bestTemplate.temperature ?? ''} · top_k=${bestTemplate.top_k ?? ''} · top_p=${bestTemplate.top_p ?? ''} · ctx%=${bestTemplate.context_usage_pct ?? ''}</div>
        <div class="muted">votes: ${fmtInt(bestTemplate.vote_sum)} (${fmtInt(bestTemplate.vote_count)} votes)</div>
        <div class="muted">${bestTemplate.notes || ''}</div>
      ` : `<div class="muted">No templates recorded yet for this workflow/toolchain.</div>`}
    </div>
  `;
  return html;
}

(async function init() {
  const status = el('status');
  status.textContent = 'Loading…';

  const catalog = await loadCatalog();

  el('generatedAt').textContent = `data generated: ${catalog.generated_at || ''}`;

  const workflowSel = el('workflow');
  workflowSel.appendChild(option('Any', ''));
  for (const w of catalog.workflows || []) workflowSel.appendChild(option(w.name, w.slug));

  const toolchainSel = el('toolchain');
  toolchainSel.appendChild(option('Any', ''));
  for (const t of catalog.toolchains || []) toolchainSel.appendChild(option(t.display_name, t.slug));

const useCaseSel = el('useCase');
useCaseSel.appendChild(option('Any', ''));
const useCaseTags = (catalog.tags || []).filter(t => (t.category || '') === 'use_case');
for (const t of useCaseTags) useCaseSel.appendChild(option(t.name, t.slug));

const hwSel = el('hardwareProfile');
hwSel.appendChild(option('Custom', ''));
const hwProfiles = catalog.constraint_profiles || [];
for (const p of hwProfiles) hwSel.appendChild(option(p.display_name, p.slug));
hwSel.addEventListener('change', () => {
  const slug = hwSel.value;
  const p = hwProfiles.find(x => x.slug === slug);
  if (p && p.vram_gib !== null && p.vram_gib !== undefined && !Number.isNaN(Number(p.vram_gib))) {
    el('budget').value = Number(p.vram_gib);
  }
});

const familyTags = new Map();
for (const ft of (catalog.family_tags || [])) {
  const fid = ft.family_id;
  if (!familyTags.has(fid)) familyTags.set(fid, new Set());
  familyTags.get(fid).add(ft.tag_slug);
}

  const familiesBySlug = new Map((catalog.families || []).map(f => [f.slug, f]));
  const variants = catalog.variants || [];
  const compsByVariantId = new Map((catalog.variant_components || []).map(c => [c.variant_id, c]));
  const runAgg = catalog.workflow_run_agg || [];
  const runAggKeyed = new Map(runAgg.map(r => [`${r.variant_id}|${r.workflow_slug}|${r.toolchain_slug}`, r]));
  const bestTemplates = catalog.best_templates || [];
  const bestTemplateKeyed = new Map(bestTemplates.map(t => [`${t.variant_id || ''}|${t.workflow_slug}|${t.toolchain_slug || ''}`, t]));

  const rowsEl = el('rows');
  const detail = el('detail');
  const detailTitle = el('detailTitle');
  const detailBody = el('detailBody');
  el('closeDetail').addEventListener('click', () => { detail.hidden = true; });

  function apply() {
    const q = (el('q').value || '').trim().toLowerCase();
    const workflow = el('workflow').value;
    const toolchain = el('toolchain').value;
    const useCase = el('useCase').value;
    const budget = Number(el('budget').value || 0);
    const ctx = Number(el('context').value || 0);
    const kv = el('kv').value;
    const preferQuality = el('preferQuality').value === 'true';
    const minTps = el('minTps').value ? Number(el('minTps').value) : null;
    const maxTtft = el('maxTtft').value ? Number(el('maxTtft').value) : null;

    const results = [];

    for (const v of variants) {
      const fam = familiesBySlug.get(v.family_slug);
      const text = `${v.family_slug} ${v.tag} ${fam?.display_name || ''} ${(fam?.labels || []).join(' ')}`.toLowerCase();
      if (q && !text.includes(q)) continue;

if (useCase) {
  const fid = fam?.id;
  const tags = fid ? familyTags.get(fid) : null;
  if (!tags || !tags.has(useCase)) continue;
}

      const comps = compsByVariantId.get(v.id);
      if (!comps) continue;

      const weights = comps.weights_vram_gib;
      const runtime = comps.runtime_overhead_gib;
      const kvOpt = comps.kv_bytes_per_token_opt;
      const kvCons = comps.kv_bytes_per_token_cons;

      const vramOpt = computeVram(weights, runtime, kvOpt, ctx, kv);
      const vramCons = computeVram(weights, runtime, kvCons, ctx, kv);
      const tier = fitTier(vramCons, vramOpt, budget);
      if (tier === 'no_fit') continue;

      let run = null;
      if (workflow && toolchain) run = runAggKeyed.get(`${v.id}|${workflow}|${toolchain}`) || null;

      const tmplKey = `${v.id}|${workflow || ''}|${toolchain || ''}`;
      const tmpl = (workflow ? (bestTemplateKeyed.get(tmplKey) || bestTemplateKeyed.get(`${v.id}|${workflow}|`) || null) : null);

      const score = rankScore({
        fitTier: tier,
        runTrusted: run?.run_count_trusted || 0,
        p50tps: run?.p50_tps ?? null,
        avgQuality: run?.avg_quality ?? null,
        templateVoteSum: tmpl?.vote_sum ?? 0,
      }, preferQuality, minTps, maxTtft, run?.p50_ttft_ms ?? null);

      results.push({
        variant_id: v.id,
        family_slug: v.family_slug,
        tag: v.tag,
        tag_short: v.tag_short,
        size_gib: v.size_gib,
        max_context_catalog: v.max_context,
        fit_tier: tier,
        vram_required_opt_gib: vramOpt,
        vram_required_cons_gib: vramCons,
        max_context_tokens_cons: maxCtxThatFits(budget, weights, runtime, kvCons, kv),
        run_count_trusted: run?.run_count_trusted || 0,
        p50_tps: run?.p50_tps ?? null,
        p50_ttft_ms: run?.p50_ttft_ms ?? null,
        avg_quality: run?.avg_quality ?? null,
        avg_success: run?.avg_success ?? null,
        template_vote_sum: tmpl?.vote_sum ?? 0,
        rank_score: score
      });
    }

    results.sort((a,b) => (b.rank_score - a.rank_score) || (a.vram_required_cons_gib - b.vram_required_cons_gib));
    rowsEl.innerHTML = results.map(rowHtml).join('');
    status.textContent = `Showing ${results.length} variants (fit != no_fit).`;

    for (const tr of rowsEl.querySelectorAll('tr[data-variant]')) {
      tr.addEventListener('click', () => {
        const vid = tr.getAttribute('data-variant');
        const v = variants.find(x => x.id === vid);
        if (!v) return;
        const fam = familiesBySlug.get(v.family_slug);
        const comps = compsByVariantId.get(v.id);
        const run = (workflow && toolchain) ? (runAggKeyed.get(`${v.id}|${workflow}|${toolchain}`) || null) : null;
        const tmplKey = `${v.id}|${workflow || ''}|${toolchain || ''}`;
        const tmpl = workflow ? (bestTemplateKeyed.get(tmplKey) || bestTemplateKeyed.get(`${v.id}|${workflow}|`) || null) : null;

        detailTitle.textContent = `${v.family_slug} · ${v.tag_short}`;
        detailBody.innerHTML = renderDetail(v, fam, comps, ctx, budget, kv, run, tmpl);
        detail.hidden = false;
        detail.scrollIntoView({behavior:'smooth'});
      });
    }
  }

  el('apply').addEventListener('click', apply);
  el('reset').addEventListener('click', () => {
    el('q').value = '';
    el('workflow').value = '';
    el('toolchain').value = '';
    el('budget').value = 24;
    el('context').value = 16384;
    el('kv').value = 'fp16';
    el('preferQuality').value = 'true';
    el('minTps').value = '';
    el('maxTtft').value = '';
    apply();
  });

  apply();
  status.textContent = 'Ready.';
})().catch(err => {
  console.error(err);
  document.getElementById('status').textContent = `Error: ${err.message}`;
});

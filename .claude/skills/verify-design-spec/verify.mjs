#!/usr/bin/env node
// verify-design-spec: validate crawl-clean-dataset-service.md as product source of truth,
// and (optionally) check a target file/dir for compliance with its rules.
//
// Usage:
//   node verify.mjs                     # audit the design doc itself
//   node verify.mjs --target <path>     # + scan target for spec-violating patterns
//   node verify.mjs --json              # machine-readable output
//
// Exit codes: 0 clean, 1 warnings only, 2 errors present.

import { readFileSync, statSync, readdirSync } from "node:fs";
import { resolve, dirname, join, extname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..", "..");
const SPEC_PATH = resolve(REPO, "crawl-clean-dataset-service.md");

const args = process.argv.slice(2);
const jsonOut = args.includes("--json");
const targetIdx = args.indexOf("--target");
const targetPath = targetIdx >= 0 ? args[targetIdx + 1] : null;

const findings = { errors: [], warnings: [], info: [] };
const err = (m) => findings.errors.push(m);
const warn = (m) => findings.warnings.push(m);
const info = (m) => findings.info.push(m);

// ---------- 1. Load spec ----------
let spec;
try {
  spec = readFileSync(SPEC_PATH, "utf8");
} catch (e) {
  console.error(`FATAL: cannot read spec at ${SPEC_PATH}: ${e.message}`);
  process.exit(2);
}

// ---------- 2. Source markers ----------
const markerRe = /\[(src|2nd|guess)\]/g;
const markerCounts = { src: 0, "2nd": 0, guess: 0 };
for (const m of spec.matchAll(markerRe)) markerCounts[m[1]]++;
info(`source markers — src=${markerCounts.src} 2nd=${markerCounts["2nd"]} guess=${markerCounts.guess}`);

// ---------- 3. Section headers + cross-refs ----------
const sectionRe = /^##\s+(\d+)\.\s+/gm;
const sections = new Set();
for (const m of spec.matchAll(sectionRe)) sections.add(m[1]);
const subRe = /^###\s+(\d+)\.(\d+)\s+/gm;
const subsections = new Set();
for (const m of spec.matchAll(subRe)) subsections.add(`${m[1]}.${m[2]}`);
info(`sections found: ${[...sections].sort((a,b)=>+a-+b).join(",")}`);
info(`subsections found: ${[...subsections].sort().join(",")}`);

// Every §X or §X.Y reference must resolve to a real header.
const refRe = /§\s*(\d+)(?:\.(\d+))?/g;
const missingRefs = new Set();
for (const m of spec.matchAll(refRe)) {
  const [full, maj, min] = m;
  const key = min ? `${maj}.${min}` : maj;
  const ok = min ? subsections.has(key) : sections.has(maj);
  if (!ok) missingRefs.add(full);
}
if (missingRefs.size) err(`unresolved cross-refs: ${[...missingRefs].join(", ")}`);

// ---------- 4. Mermaid block sanity ----------
const mermaid = spec.match(/```mermaid\n([\s\S]*?)```/);
if (!mermaid) err("no mermaid diagram in §1 (architecture)");
else {
  const body = mermaid[1];
  if (!/flowchart\s+TD/.test(body)) warn("mermaid: expected flowchart TD orientation");
  const nodes = new Set([...body.matchAll(/\b([A-Z][A-Z0-9]{0,3})\[/g)].map(m => m[1]));
  const required = ["S0","S1","S2","S3","S4","S5","S6"];
  const missing = required.filter(n => !nodes.has(n));
  if (missing.length) err(`mermaid missing pipeline nodes: ${missing.join(",")}`);
  info(`mermaid nodes: ${[...nodes].sort().join(",")}`);
}

// ---------- 5. Config §9.3 — canonical key names ----------
const cfgBlock = spec.match(/### 9\.3[\s\S]*?```yaml\n([\s\S]*?)```/);
const cfgKeys = new Set();
if (!cfgBlock) err("§9.3 config block missing");
else {
  for (const line of cfgBlock[1].split("\n")) {
    const m = line.match(/^\s*([a-z_]+):/);
    if (m) cfgKeys.add(m[1]);
  }
  const musts = ["seed","pipeline_version","render","lang_id","lang_allow","minhash","pii","decontam","source_priority","mix_ratios"];
  const missCfg = musts.filter(k => !cfgKeys.has(k));
  if (missCfg.length) err(`§9.3 missing canonical keys: ${missCfg.join(",")}`);
  info(`§9.3 keys: ${[...cfgKeys].sort().join(",")}`);
}

// ---------- 6. Non-negotiable principle vocabulary (§0 + §13) ----------
const invariants = [
  { rx: /fail-closed/i,               name: "fail-closed principle" },
  { rx: /NFC/,                        name: "Unicode NFC (VN)" },
  { rx: /per-crawl|per-source/i,      name: "dedup per-source/per-crawl" },
  { rx: /stable\s*ID|AddId/i,         name: "stable ID / AddId" },
  { rx: /license[:\s]*unknown/i,      name: "license:unknown exclusion" },
  { rx: /decontam/i,                  name: "decontamination gate" },
  { rx: /provenance/i,                name: "per-record provenance" },
  { rx: /checkpoint|_SUCCESS/,        name: "per-stage checkpointing" },
];
for (const inv of invariants) {
  if (!inv.rx.test(spec)) err(`invariant missing from spec: ${inv.name}`);
}

// ---------- 7. Default tool choices declared in §10 ----------
const toolDefaults = ["trafilatura","GlotLID","datatrove","Presidio","DVC","FastAPI","arq","Scrapy","Playwright","BGE-M3","NeMo Curator"];
const missingTools = toolDefaults.filter(t => !spec.includes(t));
if (missingTools.length) err(`default tool defaults absent from spec: ${missingTools.join(", ")}`);

// ---------- 8. Optional: scan a target for spec violations ----------
// Thư mục env/cache/build — không phải source của product, bỏ qua khi scan.
// Verifier tự loại chính nó (SELF): bảng rule chứa các anti-pattern làm mẫu.
const SELF = fileURLToPath(import.meta.url);
const SKIP_DIRS = new Set([
  "node_modules", ".venv", "venv", "__pycache__",
  ".mypy_cache", ".pytest_cache", ".ruff_cache",
  ".dvc", "dist", "build", "data",
]);

if (targetPath) scanTarget(resolve(targetPath));

function walk(p) {
  const out = [];
  const st = statSync(p);
  if (st.isFile()) return p === SELF ? [] : [p];
  for (const name of readdirSync(p)) {
    if (SKIP_DIRS.has(name) || name.startsWith(".git") || name.endsWith(".egg-info")) continue;
    out.push(...walk(join(p, name)));
  }
  return out;
}

function scanTarget(root) {
  info(`scanning target: ${root}`);
  let files;
  try { files = walk(root); }
  catch (e) { err(`cannot walk target ${root}: ${e.message}`); return; }

  const codeExts = new Set([".py",".ts",".tsx",".js",".mjs",".yaml",".yml",".toml"]);
  const violations = [
    { rx: /load_dataset\([^)]*\)\.to_list\(/, msg: "§0/§9.1: 'streaming, not load-all' — avoid .to_list() on load_dataset" },
    { rx: /BeautifulSoup/,                    msg: "§9.1: prefer selectolax/lxml over BeautifulSoup" },
    { rx: /except\s+Exception[^:]*:\s*pass/,  msg: "§0: fail-closed — bare except+pass swallows verifier errors" },
    { rx: /['\"]?license['\"]?\s*[:=]\s*['\"]unknown['\"]/, msg: "§2/§13: license:unknown must NOT enter release dataset" },
    { rx: /normalize\s*=\s*['\"]?NFKD/,       msg: "§5.1/§11: Vietnamese requires NFC, not NFKD" },
    { rx: /lang_id\s*[:=]\s*['\"]?cld3/i,     msg: "§5.2: CLD3 underperforms GlotLID on low-resource; prefer GlotLID-M v3" },
    { rx: /\bLicenseTag\s*\.\s*[A-Za-z_]/,    msg: "§7.2: LicenseTag is a Literal, not an Enum — use UNKNOWN_LICENSE or a string value, not attribute access (crashes at runtime)" },
  ];
  const cfgViolations = [
    { rx: /scope:\s*global/,                  msg: "§5.4/§13: minhash scope must be per_source/per_crawl, not global" },
    { rx: /respect_robots:\s*false/,          msg: "§2: fail-closed — respect_robots must be true" },
  ];

  for (const f of files) {
    if (!codeExts.has(extname(f))) continue;
    let src; try { src = readFileSync(f, "utf8"); } catch { continue; }
    // PEP 621: every pyproject.toml must declare [project] (packages) or be the
    // workspace root ([tool.uv.workspace]). Missing → uv can't build/resolve it.
    if (f.endsWith("pyproject.toml") &&
        !/\[project\]/.test(src) && !/\[tool\.uv\.workspace\]/.test(src)) {
      err(`${f}:1  PEP 621: pyproject.toml missing [project] table (or [tool.uv.workspace] on the root) — uv can't build/resolve this package`);
    }
    const rules = /\.ya?ml$|\.toml$/.test(f) ? cfgViolations : violations;
    for (const r of rules) {
      const m = src.match(r.rx);
      if (m) {
        const line = src.slice(0, m.index).split("\n").length;
        err(`${f}:${line}  ${r.msg}`);
      }
    }
  }
}

// ---------- 9. Report ----------
if (jsonOut) {
  console.log(JSON.stringify({ spec: SPEC_PATH, markerCounts, sections: [...sections], ...findings }, null, 2));
} else {
  const H = (t) => `\n\x1b[1m${t}\x1b[0m`;
  console.log(H("verify-design-spec"));
  console.log(`spec: ${SPEC_PATH}`);
  console.log(`markers: src=${markerCounts.src}  2nd=${markerCounts["2nd"]}  guess=${markerCounts.guess}`);
  if (findings.errors.length) {
    console.log(H(`ERRORS (${findings.errors.length})`));
    for (const e of findings.errors) console.log(`  \x1b[31m✗\x1b[0m ${e}`);
  }
  if (findings.warnings.length) {
    console.log(H(`WARNINGS (${findings.warnings.length})`));
    for (const w of findings.warnings) console.log(`  \x1b[33m!\x1b[0m ${w}`);
  }
  console.log(H(`INFO (${findings.info.length})`));
  for (const i of findings.info) console.log(`  · ${i}`);
  console.log();
}

process.exit(findings.errors.length ? 2 : findings.warnings.length ? 1 : 0);

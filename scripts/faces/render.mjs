// Pre-render faces.js player portraits to static SVGs.
//
// Usage:  node scripts/faces/render.mjs          (from the repo root or anywhere)
//
// Reads every export in league-data/*.json, collects the union of players that
// carry a non-empty "face" object (deduped by pid; the newest export wins, using
// the same (season, phase, games-played) ranking as the CI build), overwrites
// face.teamColors with sentinel colors, renders each face with facesjs, and
// writes scripts/faces/rendered/{pid}.svg plus scripts/faces/rendered/manifest.json.
//
// The Python site build (scripts/smp/portraits.py) string-swaps the sentinel
// hexes for real team colors and emits the recolored copies to the build
// output's assets/faces/ — assets/faces/ in the deployed site is OUTPUT ONLY.
// manifest.json records the EXACT casing facesjs emitted so the swapper can
// match literally.
//
// Idempotent: files are only rewritten when their content changes, and orphaned
// {pid}.svg files (pids no longer in any export) are removed.

import { faceToSvgString } from "facesjs";
import { readFileSync, readdirSync, writeFileSync, mkdirSync, existsSync, unlinkSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const LEAGUE_DIR = join(ROOT, "league-data");
const OUT_DIR = join(ROOT, "scripts", "faces", "rendered");

// Sentinels the Python build swaps for [team primary, secondary, on_primary].
const SENTINELS = ["#F00BA1", "#F00BA2", "#F00BA3"];

// ---------------------------------------------------------------------------
// Load exports, oldest → newest (same ranking the CI uses to pick the build
// export), so that later assignments into the pid map are the newest data.
// ---------------------------------------------------------------------------
const exportFiles = readdirSync(LEAGUE_DIR)
  .filter((f) => f.endsWith(".json") && f !== "odds_history.json")
  .map((f) => join(LEAGUE_DIR, f));

const ranked = [];
for (const path of exportFiles) {
  let data;
  try {
    data = JSON.parse(readFileSync(path, "utf8"));
  } catch (err) {
    console.warn(`skipping ${path}: ${err.message}`);
    continue;
  }
  let ga = data.gameAttributes ?? {};
  if (Array.isArray(ga)) {
    ga = Object.fromEntries(ga.filter((x) => x && x.key !== undefined).map((x) => [x.key, x.value]));
  }
  if (!Array.isArray(data.players)) continue;
  ranked.push({
    path,
    key: [
      Number.isInteger(ga.season) ? ga.season : -1,
      Number.isInteger(ga.phase) ? ga.phase : -1,
      Array.isArray(data.games) ? data.games.length : 0,
      path,
    ],
    players: data.players,
  });
}
ranked.sort((a, b) => {
  for (let i = 0; i < a.key.length; i++) {
    if (a.key[i] < b.key[i]) return -1;
    if (a.key[i] > b.key[i]) return 1;
  }
  return 0;
});

// pid → face (newest export wins because we iterate oldest → newest).
const faces = new Map();
for (const { path, players } of ranked) {
  let n = 0;
  for (const p of players) {
    if (!Number.isInteger(p.pid)) continue;
    const face = p.face;
    if (face && typeof face === "object" && !Array.isArray(face) && Object.keys(face).length > 0) {
      faces.set(p.pid, face);
      n++;
    }
  }
  console.log(`${path}: ${n} faces`);
}

// ---------------------------------------------------------------------------
// Render.
// ---------------------------------------------------------------------------
mkdirSync(OUT_DIR, { recursive: true });

const writeIfChanged = (path, content) => {
  if (existsSync(path) && readFileSync(path, "utf8") === content) return false;
  writeFileSync(path, content);
  return true;
};

const pids = [...faces.keys()].sort((a, b) => a - b);
const failures = [];
let written = 0;
let emittedSentinels = null; // exact casing facesjs produces, discovered from output

for (const pid of pids) {
  // Deep-copy so we never mutate the parsed export data, then force sentinels.
  const face = JSON.parse(JSON.stringify(faces.get(pid)));
  face.teamColors = [...SENTINELS];
  let svg;
  try {
    svg = faceToSvgString(face);
  } catch (err) {
    failures.push({ pid, error: err.message });
    continue;
  }
  if (typeof svg !== "string" || !svg.includes("<svg")) {
    failures.push({ pid, error: "faceToSvgString did not return an <svg> string" });
    continue;
  }
  // Record the exact casing of the sentinels as emitted (first successful render).
  if (emittedSentinels === null) {
    emittedSentinels = SENTINELS.map((s) => {
      const m = svg.match(new RegExp(s.replace("#", "#\\s*"), "i"));
      return m ? m[0] : s;
    });
  }
  // Every sentinel must survive rendering, else the color swap breaks silently.
  for (const s of SENTINELS) {
    if (!new RegExp(s, "i").test(svg)) {
      failures.push({ pid, error: `sentinel ${s} missing from rendered SVG` });
    }
  }
  if (writeIfChanged(join(OUT_DIR, `${pid}.svg`), svg)) written++;
}

const rendered = pids.filter((pid) => !failures.some((f) => f.pid === pid));

// Prune orphaned SVGs from previous runs.
let pruned = 0;
for (const f of readdirSync(OUT_DIR)) {
  const m = /^(\d+)\.svg$/.exec(f);
  if (m && !faces.has(Number(m[1]))) {
    unlinkSync(join(OUT_DIR, f));
    pruned++;
  }
}

const manifest = JSON.stringify(
  { pids: rendered, sentinels: emittedSentinels ?? SENTINELS },
  null,
  2,
) + "\n";
const manifestChanged = writeIfChanged(join(OUT_DIR, "manifest.json"), manifest);

console.log(
  `${rendered.length} faces rendered (${written} files written, ${pruned} pruned, ` +
    `manifest ${manifestChanged ? "updated" : "unchanged"}); sentinels emitted as ` +
    JSON.stringify(emittedSentinels ?? SENTINELS),
);
if (failures.length) {
  console.error(`FAILED (${failures.length}):`);
  for (const f of failures) console.error(`  pid ${f.pid}: ${f.error}`);
  process.exitCode = 1;
}

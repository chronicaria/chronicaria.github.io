/* derive.js — pure-logic forecast derivations (NO DOM, NO fetch).
 *
 * Every function takes plain data and returns plain data; the caller renders.
 * All temps °F, precip inches, wind mph, times UTC unix seconds — matching `fc`.
 * Defensive throughout: missing arrays / null members never throw; callers get
 * empty results or nulls instead. Functions live on global scope (classic script).
 *
 * Shared conventions:
 *   fc.time            : number[] hourly UTC unix seconds (index 0 ≈ current hour)
 *   fc.members.precip  : number[hour][member] inches
 *   fc.members.t       : number[hour][member] °F
 *   fc.members.gust    : number[hour][member] mph
 *   dayGroups          : [{ startIdx, endIdx, dateKey }] inclusive index ranges over fc.time
 */

/* ---------- tiny internal helpers (not part of the public surface) ---------- */

// linear-interpolated percentile over a numeric array; null on empty. Matches
// the vault's canonical `pct` so member math here agrees with the chart bands.
function _pct(vals, p) {
  if (!Array.isArray(vals)) return null;
  const s = vals.filter((x) => x != null && !Number.isNaN(x)).sort((a, b) => a - b);
  if (!s.length) return null;
  const i = (p / 100) * (s.length - 1);
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
}

function _median(vals) {
  return _pct(vals, 50);
}

// safe numeric array access → the members row at hour h, or [] if unavailable.
function _row(members, key, h) {
  const grid = members && members[key];
  if (!Array.isArray(grid)) return [];
  const row = grid[h];
  return Array.isArray(row) ? row.filter((x) => x != null && !Number.isNaN(x)) : [];
}

// clamp helper for scores
function _clamp(x, lo, hi) {
  return x < lo ? lo : x > hi ? hi : x;
}

// how many hours of forecast we actually have
function _len(fc) {
  return fc && Array.isArray(fc.time) ? fc.time.length : 0;
}

/* ---------- 1. rainWindows ---------- */
/* Runs of consecutive hours the members agree are wet, plus the reliably-dry runs.
 * prob per hour = fraction of members with precip > 0.01in.
 * rain window  = run where prob >= 0.35; dry window = run where prob < 0.2.
 * intensity from the median precip amount across members in the window.
 */
function rainWindows(fc, hoursAhead = 24) {
  const out = { windows: [], dryWindows: [] };
  const H = _len(fc);
  if (!H || !fc.members) return out;

  const PRECIP = 0.01;
  const n = Math.min(H, Math.max(0, hoursAhead));

  // per-hour probability + median amount (over members that report rain)
  const prob = new Array(n).fill(0);
  const amt = new Array(n).fill(0); // median precip across ALL members (in/hr)
  for (let h = 0; h < n; h++) {
    const row = _row(fc.members, 'precip', h);
    if (!row.length) {
      prob[h] = null;
      amt[h] = null;
      continue;
    }
    prob[h] = row.filter((v) => v > PRECIP).length / row.length;
    amt[h] = _median(row);
  }

  const tsOf = (i) => fc.time[i];

  const intensityWord = (medAmt) => {
    if (medAmt == null) return 'steady';
    if (medAmt < 0.02) return 'drizzle';
    if (medAmt < 0.1) return 'steady';
    return 'downpour';
  };
  const confidenceWord = (p) => (p >= 0.7 ? 'likely' : 'possible');

  // scan for rain runs (prob >= 0.35) and dry runs (prob < 0.2) in one pass
  const collect = (test) => {
    const runs = [];
    let start = -1;
    for (let h = 0; h < n; h++) {
      const p = prob[h];
      const inRun = p != null && test(p);
      if (inRun && start < 0) start = h;
      if ((!inRun || h === n - 1) && start >= 0) {
        const end = inRun ? h : h - 1;
        runs.push([start, end]);
        start = -1;
      }
    }
    return runs;
  };

  for (const [a, b] of collect((p) => p >= 0.35)) {
    // representative prob = max over the run (the window's peak conviction);
    // intensity from median of the per-hour median amounts inside it.
    let peakProb = 0;
    const amts = [];
    for (let h = a; h <= b; h++) {
      if (prob[h] != null && prob[h] > peakProb) peakProb = prob[h];
      if (amt[h] != null) amts.push(amt[h]);
    }
    const medAmt = _median(amts);
    out.windows.push({
      startTs: tsOf(a),
      endTs: tsOf(b),
      prob: peakProb,
      intensity: intensityWord(medAmt),
      confidence: confidenceWord(peakProb),
    });
  }

  for (const [a, b] of collect((p) => p < 0.2)) {
    out.dryWindows.push({ startTs: tsOf(a), endTs: tsOf(b) });
  }

  return out;
}

/* ---------- 2. thresholdProbs ---------- */
/* Per-day probability chips from members. For each day:
 *   P(daily max t >= 90)  — heat
 *   P(daily min t <= 32)  — freeze
 *   P(any hour gust >= 30) — wind
 * Return only the 1–2 most relevant chips per day, season-aware:
 *   if the day's median hi >= 80 → prefer heat; if <= 40 → prefer freeze.
 */
function thresholdProbs(fc, dayGroups) {
  const days = [];
  if (!fc || !fc.members || !Array.isArray(dayGroups)) return days;
  const H = _len(fc);

  for (const g of dayGroups) {
    if (!g) continue;
    const a = Math.max(0, g.startIdx | 0);
    const b = Math.min(H - 1, g.endIdx | 0);
    if (b < a) continue;

    // Figure out how many members we have for temp this day (use max valid row).
    let memberCount = 0;
    for (let h = a; h <= b; h++) {
      const r = _row(fc.members, 't', h);
      if (r.length > memberCount) memberCount = r.length;
    }

    // Per-member daily max/min temp and daily max gust.
    // We index members positionally; rows may vary in length, so guard each access.
    const maxT = new Array(memberCount).fill(-Infinity);
    const minT = new Array(memberCount).fill(Infinity);
    let gustCount = 0;
    for (let h = a; h <= b; h++) {
      const g0 = _row(fc.members, 'gust', h);
      if (g0.length > gustCount) gustCount = g0.length;
    }
    const maxG = new Array(gustCount).fill(-Infinity);

    for (let h = a; h <= b; h++) {
      const tRow = (fc.members.t && fc.members.t[h]) || [];
      for (let m = 0; m < memberCount; m++) {
        const v = tRow[m];
        if (v == null || Number.isNaN(v)) continue;
        if (v > maxT[m]) maxT[m] = v;
        if (v < minT[m]) minT[m] = v;
      }
      const gRow = (fc.members.gust && fc.members.gust[h]) || [];
      for (let m = 0; m < gustCount; m++) {
        const v = gRow[m];
        if (v == null || Number.isNaN(v)) continue;
        if (v > maxG[m]) maxG[m] = v;
      }
    }

    const fracAtLeast = (arr, thr) => {
      const valid = arr.filter((x) => Number.isFinite(x));
      if (!valid.length) return null;
      return valid.filter((x) => x >= thr).length / valid.length;
    };
    const fracAtMost = (arr, thr) => {
      const valid = arr.filter((x) => Number.isFinite(x));
      if (!valid.length) return null;
      return valid.filter((x) => x <= thr).length / valid.length;
    };

    const pHeat = fracAtLeast(maxT, 90);
    const pFreeze = fracAtMost(minT, 32);
    const pWind = fracAtLeast(maxG, 30);

    // Season cue: the day's median high (from member daily maxes).
    const medHi = _median(maxT.filter((x) => Number.isFinite(x)));

    const asChip = (label, p, kind) =>
      p == null ? null : { label, pct: Math.round(p * 100), kind };

    const heatChip = asChip('90°+ heat', pHeat, 'heat');
    const freezeChip = asChip('freeze', pFreeze, 'freeze');
    const windChip = asChip('gusts 30+', pWind, 'wind');

    // Rank chips: season-preferred temperature chip first, then whichever
    // remaining chip has the highest probability. Drop zero-prob chips unless
    // they are the season-preferred chip (so a day always shows its dominant risk).
    let ranked = [];
    const tempPreferred =
      medHi != null && medHi >= 80 ? heatChip : medHi != null && medHi <= 40 ? freezeChip : null;

    const pool = [heatChip, freezeChip, windChip].filter(
      (c) => c && (c.pct > 0 || c === tempPreferred)
    );
    // sort by pct desc, but pin the season-preferred temp chip to the front
    pool.sort((x, y) => y.pct - x.pct);
    if (tempPreferred && pool.includes(tempPreferred)) {
      ranked = [tempPreferred, ...pool.filter((c) => c !== tempPreferred)];
    } else {
      ranked = pool;
    }

    days.push({ dateKey: g.dateKey, chips: ranked.slice(0, 2) });
  }

  return days;
}

/* ---------- 3. bestLikelyWorst ---------- */
/* Per-day p10/p50/p90 of member daily-max and daily-min temperatures.
 * p10hi = a cool-side plausible high; p90hi = a hot-side plausible high, etc.
 */
function bestLikelyWorst(fc, dayGroups) {
  const days = [];
  if (!fc || !fc.members || !Array.isArray(dayGroups)) return days;
  const H = _len(fc);

  for (const g of dayGroups) {
    if (!g) continue;
    const a = Math.max(0, g.startIdx | 0);
    const b = Math.min(H - 1, g.endIdx | 0);
    if (b < a) {
      days.push({
        dateKey: g && g.dateKey,
        p10hi: null, p50hi: null, p90hi: null,
        p10lo: null, p50lo: null, p90lo: null,
      });
      continue;
    }

    let memberCount = 0;
    for (let h = a; h <= b; h++) {
      const r = _row(fc.members, 't', h);
      if (r.length > memberCount) memberCount = r.length;
    }
    const maxT = new Array(memberCount).fill(-Infinity);
    const minT = new Array(memberCount).fill(Infinity);
    for (let h = a; h <= b; h++) {
      const tRow = (fc.members.t && fc.members.t[h]) || [];
      for (let m = 0; m < memberCount; m++) {
        const v = tRow[m];
        if (v == null || Number.isNaN(v)) continue;
        if (v > maxT[m]) maxT[m] = v;
        if (v < minT[m]) minT[m] = v;
      }
    }
    const his = maxT.filter((x) => Number.isFinite(x));
    const los = minT.filter((x) => Number.isFinite(x));

    days.push({
      dateKey: g.dateKey,
      p10hi: _pct(his, 10),
      p50hi: _pct(his, 50),
      p90hi: _pct(his, 90),
      p10lo: _pct(los, 10),
      p50lo: _pct(los, 50),
      p90lo: _pct(los, 90),
    });
  }

  return days;
}

/* ---------- 4. niceDayScore ---------- */
/* Transparent 0..100 pleasantness score with the single biggest deduction named.
 * day = { hiF, loF, popMax, windMax, uvMax, cloudMeanPct, aqi? }
 * Each factor contributes a penalty from an ideal; score = 100 - sum(penalties),
 * and `reason` reports the largest penalty in plain words.
 */
function niceDayScore(day) {
  if (!day || typeof day !== 'object') return { score: null, reason: 'no data' };

  const num = (x) => (typeof x === 'number' && !Number.isNaN(x) ? x : null);
  const hi = num(day.hiF);
  const pop = num(day.popMax);
  const wind = num(day.windMax);
  const uv = num(day.uvMax);
  const cloud = num(day.cloudMeanPct);
  const aqi = num(day.aqi);

  const penalties = [];

  // Comfort of the high: ideal band 72–80°F, penalty grows with distance,
  // capped at 45. Below-ideal (chilly) and above-ideal (hot) both cost.
  if (hi != null) {
    let d = 0;
    if (hi < 72) d = 72 - hi;
    else if (hi > 80) d = hi - 80;
    const pen = _clamp(d * 1.4, 0, 45);
    penalties.push({ pen, reason: hi > 80 ? 'hot' : hi < 72 ? 'chilly' : '', factor: 'temp' });
  }

  // Precipitation: popMax is a %; a wet day is the strongest single killer.
  if (pop != null) {
    const pen = _clamp((pop / 100) * 40, 0, 40);
    penalties.push({ pen, reason: 'wet', factor: 'precip' });
  }

  // Wind: gentle < 10mph is free; penalty ramps above that, capped 25.
  if (wind != null) {
    const pen = _clamp((wind - 10) * 1.3, 0, 25);
    penalties.push({ pen, reason: 'breezy', factor: 'wind' });
  }

  // Sun / cloud: some sun is nice; fully overcast costs a little, capped 15.
  if (cloud != null) {
    const pen = _clamp(((cloud - 40) / 60) * 15, 0, 15);
    penalties.push({ pen, reason: 'gray', factor: 'cloud' });
  }

  // UV: moderate is fine (3–6); very high UV is a mild deduction, capped 12.
  if (uv != null) {
    const pen = _clamp((uv - 7) * 3, 0, 12);
    penalties.push({ pen, reason: 'intense sun', factor: 'uv' });
  }

  // AQI (optional): US AQI; > 50 starts to cost, capped 30.
  if (aqi != null) {
    const pen = _clamp(((aqi - 50) / 100) * 30, 0, 30);
    penalties.push({ pen, reason: 'hazy air', factor: 'aqi' });
  }

  if (!penalties.length) return { score: null, reason: 'no data' };

  const total = penalties.reduce((s, p) => s + p.pen, 0);
  const score = Math.round(_clamp(100 - total, 0, 100));

  // Biggest single deduction → the headline reason.
  const worst = penalties.reduce((a, b) => (b.pen > a.pen ? b : a), penalties[0]);
  let reason;
  if (worst.pen < 3) {
    reason = score >= 85 ? 'great all around' : 'pretty pleasant';
  } else {
    const lead = score >= 75 ? 'great, but ' : score >= 55 ? 'decent, but ' : 'rough — ';
    reason = lead + worst.reason;
  }

  return { score, reason };
}

/* ---------- 5. whatToWear ---------- */
/* Daytime-hours-ahead wardrobe cues from feels-like, pop, uv, cloud.
 * Rules (from the brief):
 *   jacket if min feels < 55; heavy coat if < 35 (coat supersedes jacket)
 *   umbrella if max pop > 40
 *   sunglasses if uvMax >= 4 AND low cloud
 *   layers if the daily feels range > 18°F
 */
function whatToWear(fc) {
  const empty = { icons: [], verdict: 'No forecast available.' };
  const H = _len(fc);
  if (!H) return empty;

  // Consider the next ~24h; we don't have per-hour sun elevation, so use the
  // whole next-24h window (callers can pass a trimmed fc for true daylight).
  const n = Math.min(H, 24);
  const feels = Array.isArray(fc.feelsMed) ? fc.feelsMed.slice(0, n) : [];
  const temps = Array.isArray(fc.tMed) ? fc.tMed.slice(0, n) : [];
  const pops = Array.isArray(fc.pop) ? fc.pop.slice(0, n) : [];
  const uvs = Array.isArray(fc.uv) ? fc.uv.slice(0, n) : [];
  const clouds = Array.isArray(fc.cloud) ? fc.cloud.slice(0, n) : [];

  const nums = (arr) => arr.filter((x) => x != null && !Number.isNaN(x));
  const min = (arr) => (nums(arr).length ? Math.min(...nums(arr)) : null);
  const max = (arr) => (nums(arr).length ? Math.max(...nums(arr)) : null);
  const mean = (arr) => {
    const v = nums(arr);
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
  };

  // pop may be stored as a fraction (0..1) or percent (0..100); normalize to %.
  const popArrPct = pops.map((p) => (p == null ? null : p <= 1 ? p * 100 : p));

  const feelsMin = min(feels);
  const feelsMax = max(feels);
  const feelsRange = feelsMin != null && feelsMax != null ? feelsMax - feelsMin : null;
  const popMax = max(popArrPct);
  const uvMax = max(uvs);
  const cloudMean = mean(clouds);
  const tMax = max(temps);

  const icons = [];
  const push = (emoji, label) => icons.push({ emoji, label });

  const coat = feelsMin != null && feelsMin < 35;
  const jacket = !coat && feelsMin != null && feelsMin < 55;
  const umbrella = popMax != null && popMax > 40;
  const shades = uvMax != null && uvMax >= 4 && (cloudMean == null || cloudMean < 50);
  const layers = feelsRange != null && feelsRange > 18;

  if (coat) push('🧥', 'Heavy coat');
  if (jacket) push('🧥', 'Light jacket');
  if (layers) push('👕', 'Dress in layers');
  if (umbrella) push('☂️', 'Umbrella');
  if (shades) push('🕶️', 'Sunglasses');
  if (tMax != null && tMax >= 85 && !coat) push('🩳', 'Shorts weather');

  // Build a one-sentence verdict from the dominant signal.
  let verdict;
  if (coat) verdict = 'Bundle up — it stays cold; a heavy coat is worth it.';
  else if (jacket && umbrella) verdict = 'Cool and wet — grab a jacket and an umbrella.';
  else if (jacket) verdict = 'A bit chilly; bring a light jacket.';
  else if (umbrella && shades) verdict = 'Sun and showers both likely — umbrella and shades.';
  else if (umbrella) verdict = 'Keep an umbrella handy — rain is likely.';
  else if (layers) verdict = 'Big swing from morning to afternoon — layer up.';
  else if (shades) verdict = 'Bright and mild — sunglasses recommended.';
  else if (tMax != null && tMax >= 85) verdict = 'Hot one — dress light and hydrate.';
  else if (icons.length === 0) verdict = 'Comfortable out — no special gear needed.';
  else verdict = 'Mild overall; dress for comfort.';

  return { icons, verdict };
}

/* ---------- 6. mugginess + warmestCoolestHour ---------- */
/* Dew-point comfort label. Standard muggy-scale breakpoints.
 */
function mugginess(dewF) {
  if (dewF == null || Number.isNaN(dewF)) return { label: 'unknown', level: 0 };
  if (dewF < 55) return { label: 'dry', level: 0 };
  if (dewF < 60) return { label: 'comfortable', level: 1 };
  if (dewF < 65) return { label: 'sticky', level: 2 };
  if (dewF < 70) return { label: 'oppressive', level: 3 };
  return { label: 'brutal', level: 4 };
}

/* Index of the warmest and coolest hour in the next 24h (by median temp). */
function warmestCoolestHour(fc, next24 = true) {
  const H = _len(fc);
  const out = { warmIdx: null, coolIdx: null };
  if (!H || !Array.isArray(fc.tMed)) return out;
  const n = next24 ? Math.min(H, 24) : H;

  let warmIdx = null;
  let coolIdx = null;
  let warm = -Infinity;
  let cool = Infinity;
  for (let h = 0; h < n; h++) {
    const v = fc.tMed[h];
    if (v == null || Number.isNaN(v)) continue;
    if (v > warm) {
      warm = v;
      warmIdx = h;
    }
    if (v < cool) {
      cool = v;
      coolIdx = h;
    }
  }
  return { warmIdx, coolIdx };
}

/* ---------- 7. uvWindow ---------- */
/* Peak UV and the contiguous "wear protection" window (uv >= 3) within the given
 * index range (defaults to the first 24 hours ≈ "today").
 * dayIdxRange = [startIdx, endIdx] inclusive; omit for next-24h.
 */
function uvWindow(fc, dayIdxRange) {
  const H = _len(fc);
  const out = { peak: null, peakTs: null, protectStartTs: null, protectEndTs: null };
  if (!H || !Array.isArray(fc.uv)) return out;

  let a = 0;
  let b = Math.min(H, 24) - 1;
  if (Array.isArray(dayIdxRange) && dayIdxRange.length === 2) {
    a = _clamp(dayIdxRange[0] | 0, 0, H - 1);
    b = _clamp(dayIdxRange[1] | 0, 0, H - 1);
    if (b < a) {
      const t = a;
      a = b;
      b = t;
    }
  }

  let peak = -Infinity;
  let peakIdx = null;
  // longest contiguous run of uv >= 3 in [a,b]
  let bestStart = -1;
  let bestEnd = -1;
  let curStart = -1;
  for (let h = a; h <= b; h++) {
    const v = fc.uv[h];
    if (v != null && !Number.isNaN(v) && v > peak) {
      peak = v;
      peakIdx = h;
    }
    const on = v != null && !Number.isNaN(v) && v >= 3;
    if (on && curStart < 0) curStart = h;
    if ((!on || h === b) && curStart >= 0) {
      const end = on ? h : h - 1;
      if (bestStart < 0 || end - curStart > bestEnd - bestStart) {
        bestStart = curStart;
        bestEnd = end;
      }
      curStart = -1;
    }
  }

  return {
    peak: peakIdx == null ? null : peak,
    peakTs: peakIdx == null ? null : fc.time[peakIdx],
    protectStartTs: bestStart < 0 ? null : fc.time[bestStart],
    protectEndTs: bestStart < 0 ? null : fc.time[bestEnd],
  };
}

/* Export nothing at runtime — classic script, everything is already global.
 * (Guard so the file can also be require()'d in node for the self-check.) */
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    rainWindows,
    thresholdProbs,
    bestLikelyWorst,
    niceDayScore,
    whatToWear,
    mugginess,
    warmestCoolestHour,
    uvWindow,
    _pct,
  };
}

/* ============================================================================
 * SELF-CHECK — copy this block into a .js file and `node` it, or uncomment.
 * Builds a tiny synthetic `fc` and asserts each function's contract.
 * (Verified passing at build time.)
 * ============================================================================
 *
 * const A = require('./derive.js'); // module.exports is active above
 * const assert = (c, m) => { if (!c) throw new Error('FAIL: ' + m); };
 *
 * // --- synthetic 48h forecast: rain hours 4..8, diurnal temp, spread ±8 ---
 * const H = 48, M = 20; const t0 = 1751800000;
 * const time = Array.from({length:H}, (_,h) => t0 + h*3600);
 * const tMed=[], feelsMed=[], pop=[], uv=[], cloud=[], dewMed=[];
 * const mt=[], mp=[], mg=[];
 * for (let h=0; h<H; h++){
 *   const hod = h % 24;
 *   const base = 60 + 20*Math.sin((hod-9)/24*2*Math.PI); // ~40..80
 *   tMed[h]=base; feelsMed[h]=base-2; dewMed[h]=55;
 *   pop[h] = (h>=4 && h<=8) ? 0.8 : 0.05;   // fraction
 *   uv[h]  = (hod>=10 && hod<=15) ? 7 : (hod>=8 && hod<=17 ? 3 : 0);
 *   cloud[h] = (h>=4 && h<=8) ? 90 : 20;
 *   mt[h]  = Array.from({length:M}, (_,m)=> base + (m-M/2)*0.8);
 *   mp[h]  = Array.from({length:M}, (_,m)=> (h>=4&&h<=8) ? 0.05 : 0);
 *   mg[h]  = Array.from({length:M}, (_,m)=> 12 + (m%5));
 * }
 * const fc = { time, place:{tz:'America/New_York'}, tMed, feelsMed, pop, uv, cloud, dewMed,
 *              members:{ t:mt, precip:mp, gust:mg } };
 *
 * const rw = A.rainWindows(fc, 24);
 * assert(rw.windows.length === 1, 'one rain window');
 * assert(rw.windows[0].startTs === time[4] && rw.windows[0].endTs === time[8], 'spans h4..h8');
 * assert(rw.windows[0].intensity === 'steady', 'steady @0.05in');
 * assert(rw.windows[0].confidence === 'likely', 'likely @0.8');
 * assert(rw.dryWindows.length >= 1, 'has dry windows');
 *
 * const dg = [{startIdx:0,endIdx:23,dateKey:'d0'},{startIdx:24,endIdx:47,dateKey:'d1'}];
 * const tp = A.thresholdProbs(fc, dg);
 * assert(tp.length === 2 && tp[0].chips.length <= 2, 'two days, <=2 chips each');
 *
 * const blw = A.bestLikelyWorst(fc, dg);
 * assert(blw[0].p50hi >= blw[0].p10hi && blw[0].p90hi >= blw[0].p50hi, 'hi ordered');
 * assert(blw[0].p50lo >= blw[0].p10lo && blw[0].p90lo >= blw[0].p50lo, 'lo ordered');
 *
 * assert(A.niceDayScore({hiF:76,loF:60,popMax:5,windMax:6,uvMax:5,cloudMeanPct:30}).score >= 90, 'perfect high');
 * const bad = A.niceDayScore({hiF:95,loF:78,popMax:90,windMax:25,uvMax:10,cloudMeanPct:95});
 * assert(bad.score < 40 && typeof bad.reason === 'string', 'awful low + reason');
 *
 * const ww = A.whatToWear(fc);
 * assert(Array.isArray(ww.icons) && ww.icons.some(i=>i.label==='Umbrella'), 'umbrella flagged');
 *
 * assert(A.mugginess(50).label==='dry' && A.mugginess(72).label==='brutal', 'mugginess bands');
 * assert(A.mugginess(null).level===0, 'null dew → unknown');
 * const wc = A.warmestCoolestHour(fc, true);
 * assert(wc.warmIdx != null && wc.coolIdx != null, 'warm/cool found');
 *
 * const uw = A.uvWindow(fc, [0,23]);
 * assert(uw.peak === 7 && uw.protectStartTs != null && uw.protectEndTs != null, 'uv peak+window');
 *
 * // defensive: empty / garbage inputs never throw
 * assert(A.rainWindows({}).windows.length === 0, 'empty fc ok');
 * assert(A.thresholdProbs(null, null).length === 0, 'null args ok');
 * assert(A.niceDayScore(null).score === null, 'null day ok');
 * assert(A.uvWindow({}).peak === null, 'empty uv ok');
 *
 * console.log('derive.js self-check: all assertions passed');
 * ============================================================================ */

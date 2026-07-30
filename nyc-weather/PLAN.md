# NYC Weather Dashboard — Build Plan

*A personal, shareable weather dashboard for NYC: hourly forecasts with honest,
widening confidence bands, real precipitation probabilities, feels-like, wind —
plus a live neighborhood-level "observed now" layer.*

Status: **planning** · Owner: Andrew · Stack: static site + one tiny proxy · No framework, no build step.
Companion notes (background/why): the Rome vault — `[[NYC weather dashboard]]`, `[[Weather forecast APIs]]`, `[[Urban heat island]]`, `[[Feels-like temperature]]`, `[[Temperature forecast confidence intervals]]`.

---

## 0. Decisions locked (from our conversation)

| Decision | Choice |
|---|---|
| **Default view** | **Hourly, next 7 days** |
| **Location** | NYC (Central Park default: `40.71, -74.01`), with a neighborhood selector |
| **Core forecast data** | **Open-Meteo Ensemble API** (free, no key, CORS) — gives the member spread for bands |
| **Variables** | Temperature, **feels-like** (apparent temp), **precip probability**, wind (+ humidity, gusts optional) |
| **Neighborhood resolution** | **Option D (live sensors)** — primary. **PurpleAir** behind **one Cloudflare Worker**. Plus **NWS station obs** as a zero-infra partial-D shipped in the MVP. **Option C** (static UHI offset) is how we localize the *forecast* and the pure-static fallback. |
| **Charts** | uPlot (native band fill, ~40 KB, zero deps) |
| **Frontend hosting** | Static: GitHub Pages / Netlify / Vercel (drag-and-drop) |
| **Proxy hosting** | Cloudflare Workers (free 100k req/day) |

**The one honest tradeoff:** true neighborhood density (D) is *not* pure-static — it needs a small proxy because PurpleAir blocks browser CORS and its API key must stay secret. That proxy is a single file. If you decide you don't want to run even that, fall back to **C** (a static offset table), which needs zero network.

---

## 1. Scope & non-goals

**In scope**
- Hourly 7-day forecast for NYC with a **widening uncertainty band** (temperature + feels-like), an **honest precipitation probability**, and wind.
- A **live "observed now"** neighborhood layer (D) showing what nearby sensors actually read.
- An NWS **alerts** banner (heat advisories, storms, etc.).
- Shareable with friends (public static URL).

**Non-goals (v1)**
- Nationwide/other cities (NYC-only keeps it simple; generalizing later is a lat/lon change).
- Minute-by-minute radar/nowcasting.
- Historical accuracy scoring / backtesting (nice Phase 4, needs a datastore — see §10).
- Native mobile app (responsive web is enough).
- Login/accounts.

---

## 2. Core concept: the forecast is *regional*, the sensors are *local*

This is the mental model the whole design rests on. Keep these two things visually and conceptually separate:

| | **Forecast bands** | **Neighborhood layer (D)** |
|---|---|---|
| Question it answers | "What *will* it be, and how sure are we?" | "What is it *right now* on my block?" |
| Source | Open-Meteo ensemble (regional model) | PurpleAir / NWS sensors (live obs) |
| Time range | Next 7 days, hourly | Now (latest reading only) |
| Spatial resolution | ~9–25 km grid = "NYC generally" | Neighborhood / point |
| Why separate | Models **can't see** the urban heat island (grid cell > Manhattan's width). Verified live: two NYC points differ ~0.1–0.8 °F, and that's just elevation, not UHI. |

So: **the 7-day bands stay regional**; the **sensor layer adds live local truth for "now."** If you also want the *forecast line itself* to shift per neighborhood, that's **option C** — add a static per-neighborhood offset (§6.3). D observes; C localizes the forecast. They're complementary, not either/or.

---

## 3. Architecture & data flow

```
                    ┌─────────────────────────────────────────────┐
   Browser          │   index.html  (static, vanilla JS + uPlot)   │
   (static host)    └───────┬───────────────┬───────────────┬──────┘
                            │ direct fetch  │ direct fetch  │ fetch
                            ▼               ▼               ▼
                 Open-Meteo Ensemble   api.weather.gov   Cloudflare Worker
                 (bands: temp, feels,  (obs + alerts,    (holds PurpleAir key,
                  PoP, wind — 7d hrly) borough-scale)     -8°F correction, CORS)
                 free · no key · CORS  free · no key ·         │
                                        CORS                   ▼
                                                       api.purpleair.com/v1/sensors
                                                       (neighborhood density)
```

- **Everything except PurpleAir is called directly from the browser** — Open-Meteo and NWS are both keyless and send `Access-Control-Allow-Origin: *`.
- **PurpleAir is the only thing needing the Worker**, and only because of CORS + the secret key.
- No database. No backend for the forecast. State lives in `localStorage` (cache) and the static `neighborhoods.json`.

---

## 4. Data sources (verified 2026-07-06)

| Source | Use | Endpoint | Auth | CORS | Limits / notes |
|---|---|---|---|---|---|
| **Open-Meteo Ensemble** | Forecast **bands** | `https://ensemble-api.open-meteo.com/v1/ensemble` | none | ✅ `*` | ~10k calls/day. Per-member arrays. CC-BY. |
| **Open-Meteo Forecast** | Ready-made `precipitation_probability` | `https://api.open-meteo.com/v1/forecast` | none | ✅ `*` | Same limits. Different host. |
| **Open-Meteo (HRRR)** | *Optional* sharper 3 km base | ensemble/forecast, `models=ncep_hrrr_conus` | none | ✅ `*` | US-only, ~48 h. Sharper zones, still not blocks. |
| **NWS observations** | Live **borough** obs (partial-D) | `…weather.gov/stations/{id}/observations/latest` | none | ✅ `*` | Temp in **°C**, wind in **km/h**. ~4–6 NYC points. |
| **NWS alerts** | Warnings **banner** | `…weather.gov/alerts/active?point={lat},{lng}` | none | ✅ `*` | GeoJSON FeatureCollection. |
| **PurpleAir** (via Worker) | Live **neighborhood** obs (D) | `https://api.purpleair.com/v1/sensors` | `X-API-Key` header | ❌ (needs proxy) | 1M free points. Temp reads **+8 °F**. |
| **Open-Meteo Historical (ERA5)** | *Phase 4* backtest truth | `…/v1/archive` | none | ✅ `*` | Reanalysis, ~5-day latency. |

**Attribution required:** Open-Meteo (CC-BY 4.0) and PurpleAir must be credited in the footer. NWS/NOAA is public domain (credit is polite).

---

## 5. The computations (all client-side except the PurpleAir correction)

### 5.1 Ensemble → widening bands
For each hour, gather every member's value and take **empirical percentiles** (no Gaussian assumption):
- **Median = p50** → the center line.
- **Band = p10 / p90** ("80% of members"). *Use p10/p90, not p2.5/p97.5* — with only ~31–51 members the extreme tails ride a single member and jitter hour-to-hour. Interpolate between order statistics.
- The band **widens on its own** with lead time (members diverge). **Do not hand-widen it** — that double-counts uncertainty.
- Apply to **`temperature_2m`** and **`apparent_temperature`** (feels-like) identically.

### 5.2 Honest precipitation probability
PoP for an hour = **fraction of members with precip above a threshold** (default `> 0.01 in` ≈ 0.25 mm):
```
pop = members.filter(v => v > THRESHOLD).length / members.length
```
This is the *real* probability, not the public "wet-biased" number. State the threshold in the UI.

### 5.3 Wind
Median across members (`wind_speed_10m`); optionally p10/p90 band and gusts (`wind_gusts_10m`).

### 5.4 PurpleAir correction (in the Worker, §6.2)
Raw `temperature` field is the **inside-housing** reading, ~8 °F hot; humidity ~4% low:
```
ambient_F  = temperature - 8      // PurpleAir's official constant
ambient_RH = humidity + 4
```
(-8 °F is the accepted lazy default; a linear fit is marginally better but not worth it here.)

### 5.5 (Option C) per-neighborhood forecast offset
Add a fixed delta to the regional forecast so the *line* localizes:
```
neighborhoodTemp[h] = regionalTemp[h] + offset[neighborhood][isNight(h) ? 'night' : 'day']
```
Offsets from `neighborhoods.json` (§6.3). Largest at night; near 0 or negative by water/parks.

---

## 6. Neighborhood resolution — detailed (D primary, C fallback)

Recap of *why this section exists*: the forecast models physically cannot resolve neighborhoods (grid cell > Manhattan width). See `[[Urban heat island]]`. Three ways to add local detail, from most-live to zero-infra:

### 6.1 NWS station observations — the free partial-D (ship in MVP)
Zero infrastructure, real measured air temp, but only **borough/airport scale** (~4–6 points).

- **Endpoint:** `GET https://api.weather.gov/stations/{id}/observations/latest`
- **NYC stations:** `KNYC` (Central Park, Manhattan), `KLGA` (Queens), `KJFK` (Queens), `KEWR` (Newark, edge). Fill-ins: `KTEB`, `KISP`, `KFRG`. *No ASOS exists in Brooklyn, the Bronx, or Staten Island.*
- **Response:** `properties.temperature` = `{value, unitCode:"wmoUnit:degC"}` (**°C — convert**), `.relativeHumidity`, `.windSpeed` (**km/h — convert**), `.textDescription`.
- **Browser gotcha:** do **not** set a custom `User-Agent` from browser JS — it triggers a preflight NWS rejects. Default UA works.
- **Verdict:** great "official observed now" dots for free. Not neighborhood density — that's what PurpleAir adds.

### 6.2 PurpleAir + Cloudflare Worker — true neighborhood density (Option D proper)
Dozens of sensors across NYC. Needs the Worker because of CORS + secret key.

**Setup (one-time):**
1. Get a **free READ key** at `https://develop.purpleair.com/keys` (Google sign-in).
2. Create the Worker (below), store the key as a secret: `npx wrangler secret put PURPLEAIR_KEY`.
3. `npx wrangler deploy`. Point the frontend at the Worker URL.

**PurpleAir call the Worker makes:**
- `GET https://api.purpleair.com/v1/sensors`
- Header: `X-API-Key: <key>`
- Params: bounding box `nwlng,nwlat,selng,selat` around NYC, **`location_type=0`** (outdoor only — critical), `fields=name,latitude,longitude,temperature,humidity,last_seen`
- Response is **columnar**: a `fields` array + `data` rows → index by field position, not object key.
- Filter stale sensors via `last_seen`; apply `-8 °F` / `+4%` correction (§5.4).

**The whole Worker (`worker/purpleair-proxy.js`):**
```js
export default {
  async fetch(req, env) {
    // NYC-ish bounding box (NW corner, SE corner)
    const bbox = "nwlng=-74.03&nwlat=40.88&selng=-73.86&selat=40.68";
    const url = `https://api.purpleair.com/v1/sensors`
      + `?location_type=0&fields=name,latitude,longitude,temperature,humidity,last_seen&${bbox}`;
    const r = await fetch(url, { headers: { "X-API-Key": env.PURPLEAIR_KEY } });
    const d = await r.json();
    const col = Object.fromEntries(d.fields.map((f, i) => [f, i]));   // field → index
    const cutoff = Math.floor(Date.now() / 1000) - 3600;             // drop >1h stale
    const sensors = d.data
      .filter(row => row[col.last_seen] >= cutoff)
      .map(row => ({
        name: row[col.name],
        lat:  row[col.latitude],
        lon:  row[col.longitude],
        temp_f: row[col.temperature] - 8,   // housing bias correction
        rh:     row[col.humidity] + 4,
      }));
    return new Response(JSON.stringify(sensors), {
      headers: { "content-type": "application/json", "Access-Control-Allow-Origin": "*" },
    });
  },
};
```

**Cost budget:** get-sensors = 5 + ~2 pts/field/sensor. ~20 sensors ≈ **205 pts/call**. Poll **every 5–10 min** (outdoor temp barely moves in 2 min) → ~890k pts/month, comfortably inside the **1,000,000 free**. Cache the Worker response (edge cache or a short in-Worker TTL) so multiple visitors share one upstream call.

**Why Cloudflare over Vercel/Netlify:** single file, `fetch(request, env)` handler, `wrangler secret put`, one `deploy`, **100k req/day free** (per-day, not per-month), and no "no-commercial-use" clause (Vercel Hobby has one). Vercel (~1M/mo) or Netlify (~125k/mo) also work if you prefer their ecosystem.

### 6.3 Option C — static per-neighborhood UHI offset (pure static, localizes the *forecast*)
No network at all. A hardcoded table shifts the regional forecast per neighborhood.

- **`data/neighborhoods.json`** shape:
  ```json
  [
    { "name": "Central Park",  "lat": 40.785, "lon": -73.968, "offsetF": { "day": 0.0, "night": 0.0 } },
    { "name": "South Bronx",   "lat": 40.816, "lon": -73.917, "offsetF": { "day": 0.5, "night": 3.5 } },
    { "name": "East Harlem",   "lat": 40.795, "lon": -73.938, "offsetF": { "day": 0.5, "night": 3.0 } },
    { "name": "Coney Island",  "lat": 40.575, "lon": -73.981, "offsetF": { "day": -1.0, "night": -0.5 } }
  ]
  ```
- **Offset magnitude:** ~**+1 to +4 °F** for dense, low-canopy areas (South Bronx, Harlem), **largest at night**; near 0 or negative near water/parks. See `[[Urban heat island]]`.
- **Deriving real values (do once):** pull ECOSTRESS (70 m) or Landsat land-surface-temp maps, or NYC's Heat Vulnerability Index, and translate the *air*-temp pattern into per-neighborhood day/night deltas. Ship as estimates; label them as such.

### 6.4 Recommended sequencing
1. **MVP:** regional bands + **NWS obs dots** + alerts. (Zero infra, real observations.)
2. **Add D:** Cloudflare Worker + PurpleAir for neighborhood-density "observed now."
3. **Add C:** offset table so the *forecast* also localizes to the selected neighborhood.

If at step 2 you decide you don't want to run a Worker, **stop at C** — the forecast still localizes, just from static estimates instead of live sensors.

---

## 7. UI / views

**Default: hourly, 7 days.** One scrollable/zoomable time axis with day boundaries and a "now" line.

- **Primary chart — temperature:** median line + **p10/p90 shaded band**; overlay the **feels-like** median (+ its own lighter band). Toggle band on/off.
- **Row 2 — precipitation:** PoP as bars (0–100%), plus expected amount (median) as a faint overlay.
- **Row 3 — wind:** median line (+ optional band), gusts marker.
- **Neighborhood selector:** dropdown from `neighborhoods.json`. Changing it (a) re-centers the forecast fetch lat/lon, (b) applies the C offset, (c) highlights the nearest sensor(s).
- **"Observed now" panel:** nearest NWS station + nearest PurpleAir sensor(s), shown as `observed 78 °F` next to `forecast now 80 °F` so the gap is visible.
- **Alerts banner:** top strip, red if any active `event` (e.g. "Heat Advisory"); hidden if none.
- **Units:** °F default, toggle to °C; wind mph default.
- **Honest labels (non-negotiable):** band = "80% of ensemble members"; forecast = "NYC regional — models don't resolve blocks"; PoP threshold stated; sensor note "PurpleAir, bias-corrected −8 °F."
- **Mobile:** responsive; charts scroll horizontally inside their own container.

---

## 8. Charting (uPlot specifics)
- Band = two **adjacent** series in `low, high` order, each `band: true` with a translucent `fill`; uPlot fills between them. Median = a third series (solid stroke).
- Data layout: `[ times, tLo, tHi, tMed, feelsLo, feelsHi, feelsMed ]`.
- Put PoP and wind on **separate uPlot instances** (small multiples) rather than cramming one axis.
- Vendor `uPlot.iife.min.js` + `uPlot.min.css` locally (no CDN) → zero build, zero runtime dependency.

---

## 9. Repo structure
```
nyc-weather-dashboard/
├─ PLAN.md                 ← this file
├─ README.md               ← quickstart + attribution
├─ index.html              ← markup + <script type="module" src="js/app.js">
├─ css/style.css
├─ js/
│  ├─ app.js               ← orchestrates: fetch → compute → render
│  ├─ data.js              ← fetchers (open-meteo, nws, worker) + percentile/PoP math
│  └─ chart.js             ← uPlot setup for temp / precip / wind
├─ data/
│  └─ neighborhoods.json   ← names, lat/lon, day/night UHI offsets (option C)
├─ vendor/
│  ├─ uPlot.iife.min.js
│  └─ uPlot.min.css
└─ worker/                 ← only if doing option D
   ├─ purpleair-proxy.js
   └─ wrangler.toml
```

---

## 10. Build phases & task checklists

**Phase 0 — scaffold**
- [ ] `index.html` + `css/style.css` + empty `js/*` modules; vendor uPlot locally
- [ ] Hardcode Central Park lat/lon; render a "hello" uPlot with dummy data

**Phase 1 — MVP (pure static, ship this first)**
- [ ] `data.js`: fetch Open-Meteo ensemble (`temperature_2m, apparent_temperature, precipitation, wind_speed_10m`, `forecast_days=7`, `timezone=America/New_York`, `temperature_unit=fahrenheit`)
- [ ] Compute per-hour p10/p50/p90 (temp + feels-like), PoP, wind median
- [ ] Handle **both** member key shapes (`temperature_2m_member01` and multi-model `..._ncep_gefs_seamless`); skip empty/null members
- [ ] Temp + feels-like band chart; PoP row; wind row
- [ ] NWS **alerts** banner (`/alerts/active?point=`)
- [ ] NWS **observed-now** dots (`/stations/{KNYC,KLGA,KJFK,KEWR}/observations/latest`; convert °C→°F, km/h→mph)
- [ ] `localStorage` cache (TTL ~2 h forecast, ~10 min obs); units toggle; attribution footer
- [ ] Deploy static → GitHub Pages / Netlify. **Usable product exists here.**

**Phase 2 — Option D (neighborhood density)**
- [ ] PurpleAir READ key; `worker/purpleair-proxy.js` (§6.2); `wrangler secret put PURPLEAIR_KEY`; deploy
- [ ] Frontend fetches the Worker; render sensor readings near the selected neighborhood
- [ ] Poll ≤ every 5–10 min; edge/short cache in Worker

**Phase 3 — Option C + polish**
- [ ] `neighborhoods.json` with ~10–15 NYC neighborhoods + day/night offsets
- [ ] Neighborhood selector; apply offset to forecast line; nearest-sensor highlight
- [ ] Mobile pass; empty/error states; "how to read this" help text

**Phase 4 — optional: forecast scoring (needs a datastore)**
- [ ] Scheduled snapshot of daily forecasts → storage (Cloudflare KV / a gist)
- [ ] Compare vs Open-Meteo Historical (ERA5) / NWS obs; "how good were last week's forecasts?" tab

---

## 11. Deployment
- **Frontend:** push to GitHub Pages (public repo) *or* drag the folder to Netlify. No build step.
- **Worker (Phase 2):** `wrangler deploy`; store key with `wrangler secret put`; set `Access-Control-Allow-Origin` in the Worker (already in the sketch). Put the Worker URL in a config constant in `data.js`.
- **Config:** a single `CONFIG` object (lat/lon, worker URL, poll intervals, PoP threshold) at the top of `app.js`.

---

## 12. Rate limits, caching, refresh cadence

| Source | Refresh | Why |
|---|---|---|
| Open-Meteo ensemble | every ~2–3 h (cache in `localStorage`) | Model runs only a few times/day — polling faster is wasted |
| NWS obs | every ~10 min | Obs update ~hourly; can lag |
| NWS alerts | every ~10 min | |
| PurpleAir (Worker) | every 5–10 min, edge-cached | Stay inside 1M free points; sensors update ~2 min |

Never auto-poll on a tight loop — it burns free tiers and gains nothing.

---

## 13. Attribution & legal
- **Open-Meteo:** CC-BY 4.0 → footer credit ("Weather data by Open-Meteo.com"). Free tier is **non-commercial** — fine for personal/friends; no ads/paywall.
- **PurpleAir:** credit PurpleAir; personal use within free points.
- **NWS/NOAA:** public domain; credit is courtesy.
- **Vercel Hobby** (if used for the proxy instead of Cloudflare) forbids commercial use — Cloudflare/Netlify don't.

---

## 14. Honest caveats to surface *in the UI* (not just here)
1. Bands are an **all-inputs ensemble spread**, wider before fronts, tight on calm days — a real 95%/80% range, not a guarantee. See `[[Temperature forecast confidence intervals]]`.
2. The forecast is **regional** — it doesn't resolve your block. Neighborhood detail comes from **sensors** (live) or **static offsets** (estimates).
3. PurpleAir temps are **bias-corrected** (−8 °F) but still hobbyist sensors — show them as "community sensor," not gospel.
4. Observations can **lag** an hour; label timestamps.

---

## 15. Open decisions (need your call before/while building)
1. **Run the Worker (true D) or stay pure-static (C only)?** Recommendation: ship MVP + NWS obs first, then add the Worker — it's genuinely one file. *You picked D, so plan of record = Worker.*
2. **Which neighborhoods** in the selector? (Suggest ~12 spanning the boroughs + a couple waterfront/park contrasts.)
3. **Host:** GitHub Pages (you already use `andrewjparkus.github.io`) vs Netlify?
4. **Refresh cadence** for the sensor layer — 5 or 10 min?
5. **Phase 4 backtest** — want it eventually? (Changes whether we add a scheduled snapshot early.)

---

## 16. References
Vault notes (the "why"): `[[NYC weather dashboard]]`, `[[Weather forecast APIs]]`, `[[Ensemble forecasting]]`, `[[Urban heat island]]`, `[[Feels-like temperature]]`, `[[Temperature forecast confidence intervals]]`, `[[Atmospheric predictability limit]]`.
Key external docs: Open-Meteo Ensemble API (`open-meteo.com/en/docs/ensemble-api`); NWS API (`weather.gov/documentation/services-web-api`); PurpleAir API (`community.purpleair.com`, `develop.purpleair.com/keys`); Cloudflare Workers (`developers.cloudflare.com/workers`); uPlot (`github.com/leeoniya/uPlot`).
*All endpoints, limits, CORS behavior, station IDs, and the PurpleAir −8 °F correction were live-verified 2026-07-06.*

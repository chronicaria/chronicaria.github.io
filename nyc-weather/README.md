# Weather Dashboard

A personal, shareable weather dashboard: **hourly forecasts, 7 days out, with the uncertainty
shown, not hidden** — a temperature/feels-like band that widens with lead time (from a real
weather *ensemble*), an honest precipitation probability, wind, and humidity, for a curated list
of **places** (NYC neighborhoods + U.S. and international cities), each in its own local time.

Built as a plain static site — no framework, no build step, no API key. See **[PLAN.md](PLAN.md)**
for the full design and roadmap.

## Run it locally
It's static files, so any static server works. From this folder:

```bash
python3 -m http.server 8000
# then open http://localhost:8000
```

(Opening `index.html` directly via `file://` also mostly works — it uses classic scripts, not ES
modules — but a server is cleaner.)

## Deploy
Drag this folder to **Netlify**, or push to a **GitHub Pages** repo. No backend needed: every API
(Open-Meteo, NWS) is public, keyless, and CORS-enabled, so the browser calls them directly.

## What's built
Newspaper **serif** theme, dark mode, left **grouped place sidebar** — *New York, NY* (Murray Hill
default, Battery Park, Elmhurst, Flushing), *Other U.S. cities* (Durham, Cambridge, Rochester,
Stony Brook, Nashville, Austin, Houston), and *International* (Toronto, Seoul). Each place renders
in **its own local timezone**, and each has a **shareable URL**
(`#seoul`, `#murray-hill`, …) with a matching page title — deep-linkable and back/forward-aware.
- **7-day cards** across the top (icon, high/low, precip chance) — the at-a-glance week.
- 7-day **hourly** **temperature + feels-like** in one **full-width chart** — two p10–p90 ensemble
  bands (~119 members: GEFS + ECMWF ENS + ICON-EPS) that widen with lead time. The chart is
  **anchored to the current hour**; hover shows **both** values + ranges (to the tenth of a degree)
  in an **on-graph readout**, and the crosshair tracks across every chart at once.
- **Chance of precipitation** as a smooth curve (honest probability = share of members with
  measurable rain each hour).
- **Wind + gusts** and **humidity** (median + band).
- **NWS alerts** banner (US places).
- **Per-neighborhood urban-heat-island offset (NYC):** picking an NYC neighborhood shifts the
  forecast by its day/night UHI estimate (e.g. Murray Hill +0.5°/+2.5°). Other cities use the raw
  regional forecast.

### Feature wave
- **Ensemble superpowers:** a **spaghetti toggle** (draw all 119 member threads fanning out with
  lead time); **threshold chips** on day cards ("43% 90°+ heat"); **best/likely/worst** range on
  each day card (cool-case–hot-case); a **"Today's vibe" 0–100 score**.
- **Glance panels:** **rain-timing** ("steady, likely 2–6pm; driest gap 6–8pm"), **what-to-wear**,
  **comfort** (dew-point mugginess + warmest/coolest hour), **UV** burn window, **sparklines** in
  the 7-day cards.
- **New data layers (all free, no key, CORS):** **air quality** + wildfire-smoke flag (Open-Meteo
  AQI), **today-vs-normal + records** (Open-Meteo ERA5 archive), **sun & moon** strip (SunCalc math),
  **marine** waves/SST + **tides** for coastal places (Open-Meteo Marine + NOAA CO-OPS).
- **Share:** a one-click **PNG snapshot** of the current view (client-side canvas, no API).

_(Earlier experiments dropped for simplicity: a PurpleAir live-sensor layer, an NWS "observed now"
panel, and a forecast-accuracy scorecard.)_

## Structure
```
index.html       markup + script order
css/style.css
js/data.js        fetch (ensemble + members + extras), percentile/PoP math
js/chart.js       uPlot builders (bands, tz axis, now-line, readout, spaghetti, sparkline)
js/app.js         orchestration: routing, sidebar, day cards, charts, glance panels, per-place tz + UHI
js/derive.js      pure logic: rain windows, threshold probs, nice-day score, what-to-wear, UV window
js/astro.js       sun & moon (SunCalc)      js/aqi.js      air quality + smoke
js/climate.js     today-vs-normal (ERA5)    js/marine.js   waves/SST + tides (coastal)
js/snapshot.js    PNG share export
data/places.js    grouped places (lat/lon, timezone, slug, NYC UHI offsets)
vendor/           uPlot + SunCalc (vendored, no CDN)
```

## Attribution
Weather data by [Open-Meteo](https://open-meteo.com) (CC-BY 4.0); observations & alerts by the
[US National Weather Service](https://www.weather.gov) (public domain). Charts by
[uPlot](https://github.com/leeoniya/uPlot). Personal, non-commercial use.

# Build contract — Italy trip site

Read these two files first and follow them exactly:
- `/Users/andrewpark/Desktop/Code/italy-trip/assets/style.css` — the full design system
- `/Users/andrewpark/Desktop/Code/italy-trip/index.html` — the canonical page

**Write only your assigned HTML file. Do not edit `style.css`, `app.js`, or `index.html`.**
Every class you need already exists in `style.css`. If something seems missing, compose it from
existing classes rather than inventing new ones or adding inline `<style>`.

## Page shell — copy verbatim, changing only the marked parts

```html
<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PAGE TITLE · Italy, winter 2026–27</title>
<meta name="description" content="ONE SENTENCE, UNDER 160 CHARS">
<script>try{document.documentElement.dataset.theme=localStorage.getItem("italy-theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")}catch(e){}</script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>

<header class="site-header">
  <p class="brand">
    <a href="index.html">Italy <span>in winter</span>
      <span class="brand-dates">20 Dec 2026 — 2 Jan 2027</span>
    </a>
  </p>
  <button class="nav-burger" aria-expanded="false" aria-controls="nav">Menu</button>
  <div class="nav-wrap">
    <nav class="primary-nav" id="nav" aria-label="Sections">
      <a href="index.html">Trip</a>
      <a href="itinerary.html">Itinerary</a>
      <a href="como.html">Como</a>
      <a href="travel.html">Travel</a>
      <a href="stays.html">Stays</a>
      <a href="bookings.html">Bookings</a>
      <a href="food.html">Food</a>
      <a href="alternatives.html">Alternatives</a>
    </nav>
    <button class="theme-toggle" type="button">◐ dark</button>
  </div>
</header>

<main class="page-shell" id="main">

  <div class="page-hero">
    <p class="eyebrow">SHORT KICKER, UPPERCASE-ISH</p>
    <h1>HEADLINE WITH ONE <em>ITALIC WORD</em></h1>
    <p class="standfirst">ONE OR TWO SENTENCES.</p>
  </div>

  <!-- YOUR SECTIONS -->

  <nav class="page-nav" aria-label="Pagination">
    <a href="PREV.html"><span class="dir">Previous</span><span class="to">← PREV NAME</span></a>
    <a href="NEXT.html"><span class="dir">Next</span><span class="to">NEXT NAME →</span></a>
  </nav>

</main>

<footer class="site-footer">
  <span>Italy · winter 2026–27 · researched 21 July 2026</span>
  <span class="colophon">Set in Cormorant Garamond &amp; Newsreader. Press <strong>⌘K</strong> to jump anywhere.</span>
</footer>

<script src="assets/app.js" defer></script>
</body>
</html>
```

Add `aria-current="page"` to your own page's nav link. If a page-nav slot has no destination,
use `<span></span>` in its place.

## Class vocabulary

| Need | Markup |
|---|---|
| Section | `<section class="section" id="slug" data-jump="Name for ⌘K" data-jump-kind="section">` then `<h2>` |
| Body copy | wrap in `<div class="prose">` so the measure caps at 68ch |
| Table | `<div class="table-wrap"><table>…` — add `class="num"` to numeric `th`/`td`; `<tr class="total">` for a totals row |
| Timed schedule | `<ul class="schedule"><li><span class="t">08:20</span><span>Text</span></li>` — add `class="t soft"` when the time is approximate |
| Callout | `<div class="note"><span class="note-label">Label</span><p>…</p></div>` — variants `note book` (gilt, reserve it), `note drop` (porphyry, the pressure-release item), `note rule-of-day` (lake green) |
| Headline numbers | `<dl class="figures"><div class="figure"><dt>Label</dt><dd>$4,180<span class="sub">Context.</span></dd></div>…` |
| Ordered process | `<ol class="steps"><li><span>Text</span></li>` — only where order is real |
| Checklist | `<ul class="checklist">` |
| Official links | `<ul class="links">` (two columns) |
| Open questions | `<ul class="questions">` |
| Divider | `<div class="oxford"></div>` between major movements; `<p class="slug">Label</p>` for minor ones |
| Provenance line | `<p class="src prose">` |
| Sticky contents rail | `<div class="with-rail"><div>…content…</div><nav class="rail"><p class="rail-label">Contents</p><ol><li><a href="#id">…</a></li></ol></nav></div>` |

Add `class="reveal"` to a handful of repeated blocks (day cards, legs) for the scroll-in — not to everything.

## City accent

Put `data-base="milan|venice|florence|rome|plane"` on any element that should carry a city's
colour. It sets `--bed-color`, used by `.bed` and `.leg-mark`.

## The daylight band

Axis is **06:00 → 24:00** (1080 minutes). For a time `T`:
`pct = (minutesSinceMidnight(T) − 360) / 1080 × 100`, rounded to one decimal.

```html
<div class="daylight">
  <div class="daylight-track" style="--rise:11.4%; --set:59.6%;">
    <div class="daylight-span" style="--from:19.4%; --to:75.0%;" title="Scheduled 09:30 to 19:30"></div>
  </div>
  <div class="daylight-scale"><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
</div>
```

`--rise`/`--set` are the city's sunrise and sunset. `--from`/`--to` are the day's first and last
scheduled times. Use these sunrise/sunset values (late December):

| City | Sunrise | Sunset | `--rise` | `--set` |
|---|---|---|---|---|
| Milan | 08:03 | 16:44 | `11.4%` | `59.6%` |
| Venice | 07:47 | 16:31 | `9.9%` | `58.4%` |
| Florence / Pisa / Lucca | 07:39 | 16:44 | `9.2%` | `59.6%` |
| Rome | 07:35 | 16:47 | `8.8%` | `59.9%` |

Clamp `--to` at `100%` for anything past midnight.

## Rules

1. **Every fact, time, price, and URL comes from the source note. Do not invent, round, or
   "improve" any of them.** If the note says `18:35–21:03 target`, the page says that.
2. Keep the note's vocabulary: **Book** / **Target** / **Optional switch**, "drop first",
   "rule for the day", "open questions".
3. Official links stay official — copy URLs exactly, and keep them as real `<a href>`.
4. Preserve the **Open questions** list at the end of each page, in a `.questions` list.
5. Write in the register of the source: calm, specific, second-person-plural where natural
   ("we sleep in Venice"), no marketing voice, no emoji, no exclamation marks.
6. Prose in `.prose`; tables and schedules can run full width.
7. Accessibility floor: one `<h1>`, headings in order, `alt` on any image, real link text
   (never "click here"), `<th scope>` where a table has row headers.
8. No inline `<style>`, no `<script>` other than the two in the shell, no external assets
   beyond the fonts already loaded by `style.css`.

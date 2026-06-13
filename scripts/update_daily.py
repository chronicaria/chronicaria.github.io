#!/usr/bin/env python3
"""Print the morning edition of The Gothic Times.

Fetches ~25 public feeds and APIs (stdlib only — no pip install), then
normalizes, scores, dedupes, and lays out a daily edition as JSON:

    data/daily/YYYY-MM-DD.json   permanent archive, one per day
    data/daily/latest.json       copy of today's edition (the page loads this)
    data/daily/index.json        list of available edition dates

Sections: sports (tiered by fandom), ai, markets, elections.
A failed source never kills the edition — that section just runs thinner.
Election odds come entirely from Polymarket's Gamma API.
"""

import concurrent.futures as cf
import difflib
import hashlib
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "daily"
LAUNCH = date(2026, 6, 12)  # edition No. 1
UA = {"User-Agent": "chronicaria.github.io gothic-times (personal news page)"}
NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------- helpers

def fetch(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return res.read().decode("utf-8", "replace")


def fetch_json(url, timeout=15):
    return json.loads(fetch(url, timeout))


TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def strip_html(text, limit=240):
    if not text:
        return ""
    text = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", text)
    text = TAG_RE.sub(" ", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#039;", "'").replace("&#8217;", "'")
                .replace("&#8216;", "'").replace("&#8220;", '"').replace("&#8221;", '"')
                .replace("&nbsp;", " ").replace("&#160;", " "))
    text = WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def parse_when(s):
    """Best-effort RFC-822 / ISO-8601 → aware UTC datetime."""
    if not s:
        return None
    s = s.strip()
    try:
        dt = parsedate_to_datetime(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def localname(el):
    return el.tag.rsplit("}", 1)[-1]


def parse_feed(xml_text):
    """RSS 2.0 + Atom → [{title, url, summary, published}]."""
    root = ET.fromstring(xml_text)
    items = []
    nodes = [el for el in root.iter() if localname(el) in ("item", "entry")]
    for node in nodes:
        title = url = summary = published = None
        for child in node:
            name = localname(child)
            text = (child.text or "").strip()
            if name == "title":
                title = strip_html(text, 300)
            elif name == "link":
                url = child.get("href") or text or url
                if child.get("rel") == "alternate":  # prefer alternate links in Atom
                    url = child.get("href")
            elif name in ("description", "summary", "content", "encoded") and not summary:
                summary = strip_html(text)
            elif name in ("pubDate", "published", "updated", "date") and not published:
                published = text
        if title and url:
            items.append({"title": title, "url": url, "summary": summary or "",
                          "published": parse_when(published)})
    return items


def item(section, source, title, url, published, blurb="", weight=1.0,
         tags=None, paywalled=False, bucket=None, points=None):
    return {
        "id": hashlib.sha1((url or title).encode()).hexdigest()[:12],
        "section": section, "source": source, "title": title, "url": url,
        "published": published.isoformat().replace("+00:00", "Z") if published else None,
        "blurb": blurb, "weight": weight, "tags": tags or [],
        "paywalled": paywalled, "bucket": bucket, "points": points,
    }


# ---------------------------------------------------------------- scoring

BOOSTS = {
    "sports": r"\b(recruit|transfer portal|commit|trade|traded|injur|extension|sign(s|ed)|fire|hire|rank|draft|playoff|final four|all-america)\w*",
    "ai": r"\b(releas|launch|announc|benchmark|state.of.the.art|sota|open.?weights|open.?source|frontier|agi|reasoning|breakthrough|evals?|gpt-?\d|claude|gemini|llama|grok|deepseek|qwen|mistral)\w*",
    "markets": r"\b(fed|fomc|cpi|inflation|rate cut|rate hike|yield|volatil|vix|earnings|sell.?off|rally|quant|hedge fund|treasur)\w*",
    "elections": r"\b(poll|polling|primary|midterm|senate|governor|house race|ratings? (change|shift)|toss.?up|fundrais|ad spend|filing|redistrict)\w*",
}
MAX_AGE_H = {"sports": 60, "ai": 72, "markets": 48, "elections": 96, "math": 336}


def score(it):
    section = it["section"]
    pub = parse_when(it["published"]) if isinstance(it["published"], str) else it["published"]
    age_h = (NOW - pub).total_seconds() / 3600 if pub else 36.0
    max_age = MAX_AGE_H.get(section, 72)
    tau = 18.0
    if it.get("bucket") == "papers":
        max_age = 120
    if it.get("bucket") == "labs":
        # major labs publish weekly, not daily — keep announcements around longer
        max_age, tau = 21 * 24, 96.0
    if "weekly" in it["tags"]:
        max_age = 240
    if age_h > max_age:
        return 0.0
    s = it["weight"] * math.exp(-age_h / tau)
    text = (it["title"] + " " + it["blurb"]).lower()
    hits = len(re.findall(BOOSTS.get(section, r"$^"), text))
    s *= min(1.0 + 0.25 * hits, 1.8)
    if it.get("points"):  # HN points / HF upvotes
        s *= min(0.6 + math.log10(max(it["points"], 1)) / 2.0, 1.9)
    if "tier1" in it["tags"]:
        s *= 3.0
    elif "tier2" in it["tags"]:
        s *= 1.6
    elif "tier3" in it["tags"]:
        s *= 0.7
    return round(s, 4)


NORM_RE = re.compile(r"[^a-z0-9 ]")


def dedupe(items):
    """Collapse near-identical headlines; keep the best-scored copy."""
    kept = []
    for it in sorted(items, key=lambda x: -x["score"]):
        norm = NORM_RE.sub("", it["title"].lower())
        if any(difflib.SequenceMatcher(None, norm, k).ratio() > 0.8 for k, _ in kept):
            continue
        kept.append((norm, it))
    return [it for _, it in kept]


# ---------------------------------------------------------------- sports

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
TEAMS = [
    {"key": "duke-mbb", "label": "Duke MBB", "tier": 1, "path": "basketball/mens-college-basketball", "id": "150"},
    {"key": "duke-fb",  "label": "Duke FB",  "tier": 1, "path": "football/college-football",          "id": "150"},
    {"key": "mavs",     "label": "Mavericks","tier": 1, "path": "basketball/nba",                     "id": "6"},
    {"key": "mets",     "label": "Mets",     "tier": 2, "path": "baseball/mlb",                       "id": "21"},
    {"key": "spurs",    "label": "Spurs",    "tier": 2, "path": "soccer/eng.1",                       "id": "367"},
    {"key": "colts",    "label": "Colts",    "tier": 3, "path": "football/nfl",                       "id": "11"},
    {"key": "canes",    "label": "Hurricanes","tier": 3, "path": "hockey/nhl",                        "id": "7"},
    {"key": "lafc",     "label": "LAFC",     "tier": 3, "path": "soccer/usa.1",                       "id": "18966"},
]
FAN_FEEDS = [  # SB Nation team blogs (Atom)
    {"url": "https://www.dukebasketballreport.com/rss/index.xml", "source": "Duke Basketball Report", "team": "duke-mbb", "tier": 1, "weight": 1.15},
    {"url": "https://www.mavsmoneyball.com/rss/index.xml",        "source": "Mavs Moneyball",         "team": "mavs",     "tier": 1, "weight": 1.0},
    {"url": "https://www.amazinavenue.com/rss/index.xml",         "source": "Amazin' Avenue",         "team": "mets",     "tier": 2, "weight": 1.0},
    {"url": "https://cartilagefreecaptain.sbnation.com/rss/index.xml", "source": "Cartilage Free Captain", "team": "spurs", "tier": 2, "weight": 1.0},
]
GENERAL_SPORTS_FEEDS = [  # league-wide feeds; items only kept when they match a team
    {"url": "https://www.nytimes.com/athletic/rss/news/",                "source": "The Athletic", "weight": 1.3, "paywalled": True},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",   "source": "NYT",          "weight": 1.2, "paywalled": True},
]
TEAM_PATTERNS = [  # (regex, team key) — order matters; first match wins
    (re.compile(r"\bduke\b.*basketball|\bblue devils?\b.*basketball|men's college basketball.*\bduke\b|\bcooper flagg\b|\bjon scheyer\b", re.I), "duke-mbb"),
    (re.compile(r"\bduke\b.*football|football.*\bduke\b", re.I), "duke-fb"),
    (re.compile(r"\bduke\b|\bblue devils?\b", re.I), "duke-mbb"),
    (re.compile(r"\bmavericks\b|\bmavs\b|\bluka\b.*dallas|dallas.*\bnba\b", re.I), "mavs"),
    (re.compile(r"\bmets\b", re.I), "mets"),
    (re.compile(r"\btottenham\b|\bhotspur\b", re.I), "spurs"),
    # bare "Spurs" is ambiguous (San Antonio) — require soccer context
    (re.compile(r"\bspurs\b(?=[\s\S]*(premier league|north london|postecoglou|epl|soccer|football club))", re.I), "spurs"),
    (re.compile(r"\bcolts\b", re.I), "colts"),
    (re.compile(r"\bhurricanes\b|\bcanes\b.*\bnhl\b|carolina hurricanes", re.I), "canes"),
    (re.compile(r"\blafc\b|los angeles fc", re.I), "lafc"),
]


def fetch_general_sports(cfg):
    out = []
    for f in parse_feed(fetch(cfg["url"]))[:40]:
        text = f["title"] + " " + f["summary"]
        team_key = next((k for rx, k in TEAM_PATTERNS if rx.search(text)), None)
        if not team_key:
            continue
        team = next(t for t in TEAMS if t["key"] == team_key)
        out.append(item("sports", cfg["source"], f["title"], f["url"], f["published"], f["summary"],
                        weight=cfg["weight"], paywalled=cfg.get("paywalled", False),
                        tags=[team["key"], team["label"], f"tier{team['tier']}"]))
    return out


def fetch_espn_team_news(cfg):
    data = fetch_json(f"{ESPN}/{cfg['path']}/news?team={cfg['id']}&limit=8")
    out = []
    for a in data.get("articles", []):
        link = (a.get("links", {}).get("web", {}) or {}).get("href")
        if not link:
            continue
        out.append(item("sports", "ESPN", strip_html(a.get("headline", ""), 300), link,
                        parse_when(a.get("published")), strip_html(a.get("description", "")),
                        weight=1.0, tags=[cfg["key"], cfg["label"], f"tier{cfg['tier']}"]))
    return out


def fetch_fan_feed(cfg):
    team = next(t for t in TEAMS if t["key"] == cfg["team"])
    return [item("sports", cfg["source"], f["title"], f["url"], f["published"], f["summary"],
                 weight=cfg["weight"], tags=[team["key"], team["label"], f"tier{cfg['tier']}"])
            for f in parse_feed(fetch(cfg["url"]))[:8]]


# ---------------------------------------------------------------- ai

AI_FEEDS = [
    {"url": "https://openai.com/news/rss.xml",        "source": "OpenAI",          "bucket": "labs", "weight": 1.35},
    {"url": "https://deepmind.google/blog/rss.xml",   "source": "Google DeepMind", "bucket": "labs", "weight": 1.35},
    {"url": "https://mistral.ai/rss.xml",             "source": "Mistral",         "bucket": "labs", "weight": 1.2},
    # DeepSeek and xAI don't publish RSS, so ride in on a Google News topic search.
    {"url": "https://news.google.com/rss/search?q=DeepSeek+AI+model&hl=en-US&gl=US&ceid=US:en", "source": "DeepSeek", "bucket": "labs", "weight": 1.15},
    {"url": "https://news.google.com/rss/search?q=%22xAI%22+OR+Grok+xAI&hl=en-US&gl=US&ceid=US:en", "source": "xAI", "bucket": "labs", "weight": 1.15},
]


def fetch_ai_feed(cfg):
    return [item("ai", cfg["source"], f["title"], f["url"], f["published"], f["summary"],
                 weight=cfg["weight"], bucket=cfg["bucket"])
            for f in parse_feed(fetch(cfg["url"]))[:12]]


def fetch_anthropic():
    """Anthropic has no feed; parse the news-page cards (date · category · title)."""
    page = fetch("https://www.anthropic.com/news")
    cards = re.findall(r'<a[^>]+href="(/news/[a-z0-9-]+)"[^>]*>(.*?)</a>', page, re.S)
    out, seen = [], set()
    for path, body in cards:
        if path in seen:
            continue
        seen.add(path)
        parts = [p.strip() for p in TAG_RE.sub("|", body).split("|") if p.strip()]
        if not parts:
            continue
        title = strip_html(parts[-1], 300)
        date_s = next((p for p in parts if re.fullmatch(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", p)), None)
        if not title or len(title) < 8 or title == date_s:
            continue
        pub = None
        if date_s:
            try:
                pub = datetime.strptime(date_s, "%b %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        out.append(item("ai", "Anthropic", title, f"https://www.anthropic.com{path}",
                        pub, "", weight=1.45, bucket="labs"))
    return out[:8]


def fetch_hf_papers():
    data = fetch_json("https://huggingface.co/api/daily_papers?limit=12")
    out = []
    for p in data:
        paper = p.get("paper", {})
        pid, title = paper.get("id"), strip_html(paper.get("title", ""), 300)
        if not pid or not title:
            continue
        out.append(item("ai", "HF Daily Papers", title, f"https://huggingface.co/papers/{pid}",
                        parse_when(p.get("publishedAt")), strip_html(paper.get("summary", ""), 200),
                        weight=1.0, bucket="papers", points=paper.get("upvotes")))
    return out


ARXIV_AI_FILTER = re.compile(
    r"\b(language model|llm|benchmark|reasoning|scaling|agent|alignment|rlhf|instruction|"
    r"transformer|evaluation|pretrain|fine.?tun|mixture.of.experts|attention)\b", re.I)


def fetch_arxiv(cats, section, bucket, flt=None, weight=0.9, n=25):
    q = "+OR+".join(f"cat:{c}" for c in cats)
    xml = fetch(f"http://export.arxiv.org/api/query?search_query={q}&sortBy=submittedDate&sortOrder=descending&max_results={n}")
    out = []
    for f in parse_feed(xml):
        if flt and not flt.search(f["title"]):
            continue
        out.append(item(section, "arXiv", f["title"], f["url"], f["published"],
                        f["summary"], weight=weight, bucket=bucket))
    return out


# ---------------------------------------------------------------- markets

MARKET_FEEDS = [
    {"url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "source": "WSJ",        "weight": 1.25, "paywalled": True},
    {"url": "https://www.cnbc.com/id/20910258/device/rss/rss.html",      "source": "CNBC",        "weight": 1.05, "paywalled": False},
    {"url": "https://feeds.content.dowjones.io/public/rss/mw_topstories", "source": "MarketWatch", "weight": 1.0,  "paywalled": False},
    {"url": "https://www.ft.com/markets?format=rss",                      "source": "FT",          "weight": 1.0,  "paywalled": True},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",  "source": "NYT",         "weight": 1.05, "paywalled": True},
]
TICKERS = [
    {"sym": "^GSPC",   "label": "S&P 500",        "kind": "index"},
    {"sym": "GOOGL",   "label": "Alphabet",       "kind": "stock"},
    {"sym": "NVDA",    "label": "Nvidia",         "kind": "stock"},
    {"sym": "SPCX",    "label": "SpaceX",         "kind": "stock"},
    {"sym": "BTC-USD", "label": "Bitcoin",        "kind": "index"},
    {"sym": "FSKAX",   "label": "FSKAX",          "kind": "fund"},
    {"sym": "FTIHX",   "label": "FTIHX",          "kind": "fund"},
]
MACRO_TICKERS = [
    {"sym": "^TNX", "label": "10-Y Treasury", "suffix": "%"},
    {"sym": "^IRX", "label": "3-M T-Bill",    "suffix": "%"},
]


def fetch_macro():
    """CPI YoY + unemployment from the BLS public API, yields from Yahoo."""
    out = []
    try:
        body = json.dumps({"seriesid": ["CUUR0000SA0", "LNS14000000"],
                           "startyear": str(NOW.year - 1), "endyear": str(NOW.year)}).encode()
        req = urllib.request.Request("https://api.bls.gov/publicAPI/v1/timeseries/data/",
                                     data=body, headers={**UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as res:
            bls = json.load(res)
        for s in bls.get("Results", {}).get("series", []):
            pts = s.get("data", [])
            if not pts:
                continue
            latest = pts[0]
            if s["seriesID"] == "CUUR0000SA0":
                prior = next((p for p in pts if p["year"] == str(int(latest["year"]) - 1)
                              and p["period"] == latest["period"]), None)
                if prior:
                    yoy = (float(latest["value"]) / float(prior["value"]) - 1) * 100
                    out.append({"label": "CPI YoY", "value": f"{yoy:.1f}%",
                                "note": f"{latest['periodName']} {latest['year']}"})
            else:
                out.append({"label": "Unemployment", "value": f"{latest['value']}%",
                            "note": f"{latest['periodName']} {latest['year']}"})
    except Exception:
        pass
    for t in MACRO_TICKERS:
        try:
            d = fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t['sym'])}?interval=1d&range=5d")
            px = d["chart"]["result"][0]["meta"].get("regularMarketPrice")
            if px is not None:
                out.append({"label": t["label"], "value": f"{px:.2f}{t['suffix']}", "note": "latest"})
        except Exception:
            pass
    return out


def fetch_quote(t):
    d = fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t['sym'])}?interval=1d&range=3mo")
    result = d["chart"]["result"][0]
    meta = result["meta"]
    price, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose")
    if price is None or not prev:
        return None
    closes = [round(c, 2) for c in (result.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c]
    # intraday path for the day's chart (5-minute bars over the latest session)
    intraday = []
    try:
        di = fetch_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(t['sym'])}?interval=5m&range=1d")
        ri = di["chart"]["result"][0]
        intraday = [round(c, 2) for c in (ri.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c]
    except Exception:
        pass
    chg = price - prev
    return {"sym": t["sym"], "label": t["label"], "kind": t["kind"],
            "price": round(price, 2), "chg": round(chg, 2),
            "chgPct": round(chg / prev * 100, 2),
            "spark": closes[-66:], "intraday": intraday[-120:]}


def fetch_market_feed(cfg):
    return [item("markets", cfg["source"], f["title"], f["url"], f["published"], f["summary"],
                 weight=cfg["weight"], paywalled=cfg["paywalled"])
            for f in parse_feed(fetch(cfg["url"]))[:12]]


def fetch_r_quant():
    out = []
    for f in parse_feed(fetch("https://www.reddit.com/r/quant/top/.rss?t=day"))[:6]:
        out.append(item("markets", "r/quant", f["title"], f["url"], f["published"],
                        f["summary"], weight=0.9, bucket="quant"))
    return out


READING_ROOM = [
    {"title": "Buffett's Alpha", "who": "Frazzini, Kabiller & Pedersen (AQR)", "url": "https://www.aqr.com/Insights/Research/Journal-Article/Buffetts-Alpha", "note": "Buffett's edge decomposed into leverage on cheap, safe, quality bets."},
    {"title": "The Kelly Criterion", "who": "J. L. Kelly Jr., 1956", "url": "https://en.wikipedia.org/wiki/Kelly_criterion", "note": "Bet sizing from information theory — the bridge between poker and portfolios."},
    {"title": "Portfolio Selection", "who": "Harry Markowitz, 1952", "url": "https://en.wikipedia.org/wiki/Modern_portfolio_theory", "note": "The paper that invented diversification as mathematics."},
    {"title": "Value and Momentum Everywhere", "who": "Asness, Moskowitz & Pedersen", "url": "https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere", "note": "Two anomalies, every asset class, one factor model."},
    {"title": "Optimal Execution of Portfolio Transactions", "who": "Almgren & Chriss, 2000", "url": "https://en.wikipedia.org/wiki/Optimal_execution", "note": "The canonical model for trading without moving the market against yourself."},
    {"title": "The Pricing of Options and Corporate Liabilities", "who": "Black & Scholes, 1973", "url": "https://en.wikipedia.org/wiki/Black%E2%80%93Scholes_model", "note": "Replication, no-arbitrage, and the most famous PDE in finance."},
    {"title": "…and the Cross-Section of Expected Returns", "who": "Harvey, Liu & Zhu, 2016", "url": "https://en.wikipedia.org/wiki/Factor_investing", "note": "Hundreds of published factors; most are p-hacking. Raise your t-stat bar."},
    {"title": "The Statistics of Sharpe Ratios", "who": "Andrew Lo, 2002", "url": "https://en.wikipedia.org/wiki/Sharpe_ratio", "note": "Your backtest's Sharpe has error bars. They are wider than you think."},
    {"title": "Flow Toxicity and Liquidity (VPIN)", "who": "Easley, López de Prado & O'Hara", "url": "https://en.wikipedia.org/wiki/VPIN", "note": "Order-flow toxicity as an early-warning system — written after the Flash Crash."},
    {"title": "The 10 Reasons Most ML Funds Fail", "who": "Marcos López de Prado, 2018", "url": "https://en.wikipedia.org/wiki/Marcos_L%C3%B3pez_de_Prado", "note": "Backtest overfitting, non-IID data, and other ways to lose money scientifically."},
    {"title": "The Less-Efficient Market Hypothesis", "who": "Cliff Asness, 2024", "url": "https://www.aqr.com/Insights/Perspectives", "note": "Markets may be getting less efficient. Good news for you, eventually."},
    {"title": "A Man for All Markets", "who": "Edward O. Thorp", "url": "https://en.wikipedia.org/wiki/Edward_O._Thorp", "note": "Card counting → market neutral. The original quant's autobiography."},
]


# ---------------------------------------------------------------- elections

ELECTION_FEEDS = [
    {"url": "https://thehill.com/homenews/campaign/feed/",      "source": "The Hill",      "weight": 1.1,  "tags": []},
    {"url": "https://rss.politico.com/politics-news.xml",       "source": "Politico",      "weight": 1.15, "tags": [], "filter": True},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml", "source": "NYT",  "weight": 1.05, "tags": [], "filter": True, "paywalled": True},
    {"url": "https://feeds.npr.org/1014/rss.xml",               "source": "NPR",           "weight": 1.0,  "tags": [], "filter": True},
    {"url": "https://feeds.nbcnews.com/nbcnews/public/politics", "source": "NBC News",     "weight": 1.0,  "tags": [], "filter": True},
    {"url": "https://rollcall.com/feed/",                       "source": "Roll Call",     "weight": 1.1,  "tags": [], "filter": True},
    {"url": "https://www.realclearpolitics.com/index.xml",      "source": "RCP",           "weight": 0.9,  "tags": [], "filter": True},
    {"url": "https://centerforpolitics.org/crystalball/feed/",  "source": "Crystal Ball",  "weight": 1.5,  "tags": ["weekly"]},
]
ELECTION_KEYWORDS = re.compile(
    r"\b(senate|governor|gubernatorial|house race|midterm|primary|poll|campaign|ballot|"
    r"redistrict|swing|battleground|gop|democrat|republican|election)\b", re.I)
ELECTION_EXCLUDE = re.compile(r"\b(UK|Britain|British|Europe|EU|France|German|Canad|Australi|Japan)\w*\b")

def fetch_election_feed(cfg):
    out = []
    for f in parse_feed(fetch(cfg["url"]))[:25]:
        text = f["title"] + " " + f["summary"]
        if cfg.get("filter") and (not ELECTION_KEYWORDS.search(text) or ELECTION_EXCLUDE.search(f["title"])):
            continue
        out.append(item("elections", cfg["source"], f["title"], f["url"], f["published"],
                        f["summary"], weight=cfg["weight"], tags=list(cfg["tags"]),
                        paywalled=cfg.get("paywalled", False)))
    return out


GAMMA = "https://gamma-api.polymarket.com"
PM_CONTROL = {"senate": "32224", "house": "32225", "balance": "32228"}

STATE_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new-hampshire": "NH", "new-jersey": "NJ", "new-mexico": "NM", "new-york": "NY",
    "north-carolina": "NC", "north-dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode-island": "RI", "south-carolina": "SC",
    "south-dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west-virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}

RACE_SLUG_RE = {
    "senate":   re.compile(r"^([a-z-]+)-senate-election-winner$"),
    "governor": re.compile(r"^([a-z-]+)-governor-election-winner$"),
}
DISTRICT_SLUG_RE = [
    re.compile(r"^([a-z]{2})-(\d{1,2})-house-election-winner$"),
    re.compile(r"^which-party-will-win-the-house-race-for-the-([a-z]{2})-(\d{1,2})-seat$"),
]


def pm_outcomes(event, top=3):
    """Top outcomes of a Polymarket event: [{label, price}], by price."""
    outs = []
    for m in event.get("markets", []):
        label = m.get("groupItemTitle") or m.get("question", "")
        if re.fullmatch(r"(Person|Party) [A-Z]", label or ""):
            continue
        try:
            price = float(json.loads(m["outcomePrices"])[0])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if float(m.get("volume") or 0) < 200:
            continue
        outs.append({"label": label, "price": round(price, 3)})
    outs.sort(key=lambda o: -o["price"])
    return outs[:top]


DEM_RE = re.compile(r"\(D\)|Democrat", re.I)
REP_RE = re.compile(r"\(R\)|Republican", re.I)
# Polymarket sometimes labels candidates by bare name; map the known ones.
KNOWN_PARTY = [
    (re.compile(r"\bPeltola\b", re.I), "D"),     # Mary Peltola — AK Senate
    (re.compile(r"\bBecerra\b", re.I), "D"),     # Xavier Becerra — CA Governor
    (re.compile(r"\bTom Begich\b", re.I), "D"),  # Tom Begich — AK Governor
]


def infer_party(label):
    if DEM_RE.search(label):
        return "D"
    if REP_RE.search(label):
        return "R"
    for rx, party in KNOWN_PARTY:
        if rx.search(label):
            return party
    return "I"


def pm_entry(event):
    """A map cell: favorite (label/price/party), dem share, link, volume."""
    outs = pm_outcomes(event, top=4)
    if not outs:
        return None
    fav = outs[0]
    party = infer_party(fav["label"])
    dem = next((o["price"] for o in outs if infer_party(o["label"]) == "D"), None)
    if dem is None:
        rep = next((o["price"] for o in outs if REP_RE.search(o["label"])), None)
        dem = round(1 - rep, 3) if rep is not None else (fav["price"] if party == "D" else None)
    return {
        "fav": {"label": fav["label"], "price": fav["price"], "party": party},
        "dem": dem,
        "url": f"https://polymarket.com/event/{event.get('slug')}",
        "volume": round(float(event.get("volume") or 0)),
    }


def fetch_polymarket():
    """Control-of-Congress events + the hottest midterm markets."""
    out = {"control": {}, "hot": []}
    for key, eid in PM_CONTROL.items():
        try:
            e = fetch_json(f"{GAMMA}/events/{eid}")
            out["control"][key] = {
                "title": e.get("title"), "slug": e.get("slug"),
                "url": f"https://polymarket.com/event/{e.get('slug')}",
                "volume": round(float(e.get("volume") or 0)),
                "outcomes": pm_outcomes(e, top=4),
            }
        except Exception:
            pass
    try:
        events = fetch_json(f"{GAMMA}/events?tag_slug=midterms&order=volume&ascending=false&limit=40&closed=false")
        ctrl_slugs = {c.get("slug") for c in out["control"].values()}
        for e in events:
            slug = e.get("slug", "")
            if slug in ctrl_slugs or any(rx.match(slug) for rx in DISTRICT_SLUG_RE) \
                    or any(rx.match(slug) for rx in RACE_SLUG_RE.values()):
                continue
            outs = pm_outcomes(e)
            if not outs or len(out["hot"]) >= 6:
                continue
            out["hot"].append({
                "title": e.get("title"), "slug": slug,
                "url": f"https://polymarket.com/event/{slug}",
                "volume": round(float(e.get("volume") or 0)),
                "outcomes": outs,
            })
    except Exception:
        pass
    return out


def paginate_events(tag, max_pages=12):
    """The Gamma API silently caps every page at 100 events — walk the offsets."""
    events = []
    for page in range(max_pages):
        try:
            batch = fetch_json(f"{GAMMA}/events?tag_slug={tag}&limit=100&offset={page * 100}&closed=false",
                               timeout=25)
        except Exception:
            break
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


GOV_JUNK_RE = re.compile(r"primary|lieutenant|nominee|recall|resign|out-as|impeach", re.I)


def fetch_pm_map():
    """State-by-state (and district) Polymarket odds for the election maps.

    Paginated tag sweeps catch most races; per-state slug probes and a
    search fallback (governor slugs are irregular) cover the rest.
    """
    out = {"senate": {}, "governor": {}, "house": {}}

    def consume(events):
        for e in events:
            slug = e.get("slug", "")
            for office, rx in RACE_SLUG_RE.items():
                m = rx.match(slug)
                if m and m.group(1) in STATE_ABBR:
                    entry = pm_entry(e)
                    if entry:
                        out[office][STATE_ABBR[m.group(1)]] = entry
            for rx in DISTRICT_SLUG_RE:
                m = rx.match(slug)
                if m:
                    st = m.group(1).upper()
                    if st in STATE_ABBR.values():
                        entry = pm_entry(e)
                        if entry:
                            out["house"][f"{st}-{int(m.group(2)):02d}"] = entry

    for tag in ("midterms", "house-elections", "senate-elections"):
        consume(paginate_events(tag))

    # backfill states the tag sweeps missed: exact slugs, then search
    probes = []
    for name, st in STATE_ABBR.items():
        for office in ("senate", "governor"):
            if st not in out[office]:
                probes.append((office, st, name))

    def probe(args):
        office, st, name = args
        try:
            es = fetch_json(f"{GAMMA}/events?slug={name}-{office}-election-winner", timeout=12)
            # the bare-slug endpoint returns resolved races too (e.g. the 2024 cycle) — skip them
            if es and not es[0].get("closed"):
                return office, st, pm_entry(es[0])
        except Exception:
            pass
        try:  # irregular slugs (california-governor-election-2026, florida-governor-winner-2026…)
            res = fetch_json(f"{GAMMA}/public-search?q={urllib.parse.quote(name.replace('-', ' ') + ' ' + office)}"
                             f"&limit_per_type=8", timeout=12)
            for e in res.get("events", []):
                slug = e.get("slug", "")
                if name in slug and office in slug and not GOV_JUNK_RE.search(slug) \
                        and not e.get("closed"):
                    full = fetch_json(f"{GAMMA}/events?slug={slug}", timeout=12)
                    if full:
                        return office, st, pm_entry(full[0])
        except Exception:
            pass
        return office, st, None

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for office, st, entry in ex.map(probe, probes):
            if entry:
                out[office][st] = entry
    return out


def load_yesterday(today_str):
    """The most recent archived edition before today, for day-over-day movers."""
    dates = sorted(p.stem for p in OUT_DIR.glob("*.json")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem) and p.stem < today_str)
    if not dates:
        return None
    try:
        return json.loads((OUT_DIR / f"{dates[-1]}.json").read_text())
    except Exception:
        return None


def compute_movers(state_map, yesterday):
    """Attach day-over-day odds changes; return the biggest movers."""
    movers = []
    prev_map = ((yesterday or {}).get("sections", {}).get("elections", {}).get("map")) or {}
    for office, races in state_map.items():
        prev_office = prev_map.get(office, {})
        for key, entry in races.items():
            prev = prev_office.get(key)
            if not prev or entry.get("dem") is None or prev.get("dem") is None:
                continue
            chg = round(entry["dem"] - prev["dem"], 3)
            if abs(chg) >= 0.005:
                entry["chg"] = chg
                movers.append({"office": office, "key": key, "dem": entry["dem"],
                               "chg": chg, "url": entry["url"],
                               "fav": entry["fav"]["label"]})
    movers.sort(key=lambda m: -abs(m["chg"]))
    return movers[:6]


def load_reading(edition_no):
    """Three picks per day from the mined newsletter archive (data/daily/reading.json)."""
    try:
        pool = json.loads((OUT_DIR / "reading.json").read_text())
    except Exception:
        return [READING_ROOM[(edition_no - 1) % len(READING_ROOM)]]
    if not pool:
        return []
    n = len(pool)
    picks = [pool[(edition_no - 1) % n]]
    for offset in (n // 3, 2 * n // 3):
        p = pool[(edition_no - 1 + offset) % n]
        if p not in picks:
            picks.append(p)
    return picks


# ---------------------------------------------------------------- weather

WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
       51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 61: "Light rain", 63: "Rain",
       65: "Heavy rain", 66: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
       80: "Showers", 81: "Showers", 82: "Heavy showers", 95: "Thunderstorms", 96: "Thunderstorms",
       99: "Thunderstorms"}


def fetch_weather():
    d = fetch_json("https://api.open-meteo.com/v1/forecast?latitude=35.994&longitude=-78.8986"
                   "&daily=temperature_2m_max,temperature_2m_min,weather_code"
                   "&temperature_unit=fahrenheit&timezone=America%2FNew_York&forecast_days=1")
    daily = d["daily"]
    code = daily["weather_code"][0]
    return {"place": "Durham, N.C.", "hi": round(daily["temperature_2m_max"][0]),
            "lo": round(daily["temperature_2m_min"][0]), "desc": WMO.get(code, "—")}


# ---------------------------------------------------------------- assembly

def run_safe(fn, *args, label=""):
    try:
        return fn(*args), None
    except Exception as e:
        return None, f"{label or fn.__name__}: {type(e).__name__}: {e}"


def build_week(today, state_map):
    """Sunday extra: the week in review, assembled purely from the archives."""
    dates = sorted(p.stem for p in OUT_DIR.glob("*.json")
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem) and p.stem < today.isoformat())[-7:]
    if len(dates) < 2:
        return None
    editions = []
    for d in dates:
        try:
            editions.append(json.loads((OUT_DIR / f"{d}.json").read_text()))
        except Exception:
            pass
    if len(editions) < 2:
        return None
    week = {"from": dates[0], "to": dates[-1]}
    # biggest market mover across the week (first vs latest edition's map)
    first_map = editions[0].get("sections", {}).get("elections", {}).get("map", {})
    best = None
    for office, races in state_map.items():
        for key, entry in races.items():
            prev = first_map.get(office, {}).get(key)
            if prev and entry.get("dem") is not None and prev.get("dem") is not None:
                chg = round(entry["dem"] - prev["dem"], 3)
                if best is None or abs(chg) > abs(best["chg"]):
                    best = {"office": office, "key": key, "chg": chg, "url": entry["url"]}
    if best and abs(best["chg"]) >= 0.01:
        week["mover"] = best
    # the week's best-scored story
    top = None
    for e in editions:
        cand = e.get("lead")
        if cand and (top is None or cand.get("score", 0) > top.get("score", 0)):
            top = cand
    if top:
        week["story"] = {k: top[k] for k in ("title", "url", "source") if k in top}
    return week


def write_rss(edition, root):
    """A subscribable feed of the morning edition (one item per story)."""
    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    items = []
    seen = set()
    stories = ([edition["lead"]] if edition.get("lead") else []) + [
        it for sec in edition["sections"].values() for it in sec.get("items", [])]
    for it in stories[:25]:
        if not it or it["id"] in seen:
            continue
        seen.add(it["id"])
        items.append(
            f"<item><title>{esc(it['title'])}</title><link>{esc(it['url'])}</link>"
            f"<guid isPermaLink=\"false\">{it['id']}</guid>"
            f"<category>{esc(it['section'])}</category>"
            f"<description>{esc(it.get('blurb') or it['source'])}</description></item>")
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        "<title>The Daily — Andrew Park</title>"
        "<link>https://chronicaria.github.io/daily/</link>"
        f"<description>Edition No. {edition['edition']} — sports, AI, markets, and the 2026 midterms.</description>"
        f"<lastBuildDate>{NOW.strftime('%a, %d %b %Y %H:%M:%S GMT')}</lastBuildDate>"
        + "".join(items) + "</channel></rss>")
    (root / "daily.xml").write_text(feed)


def main():
    errors = []
    items = []
    extras = {}

    jobs = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for t in TEAMS:
            jobs.append((ex.submit(run_safe, fetch_espn_team_news, t, label=f"espn:{t['key']}"), "items"))
        for fcfg in FAN_FEEDS:
            jobs.append((ex.submit(run_safe, fetch_fan_feed, fcfg, label=fcfg["source"]), "items"))
        for fcfg in GENERAL_SPORTS_FEEDS:
            jobs.append((ex.submit(run_safe, fetch_general_sports, fcfg, label=fcfg["source"]), "items"))
        for fcfg in AI_FEEDS:
            jobs.append((ex.submit(run_safe, fetch_ai_feed, fcfg, label=fcfg["source"]), "items"))
        jobs.append((ex.submit(run_safe, fetch_anthropic, label="anthropic"), "items"))
        jobs.append((ex.submit(run_safe, fetch_hf_papers, label="hf-papers"), "items"))
        jobs.append((ex.submit(run_safe, fetch_arxiv, ["cs.LG", "cs.CL", "cs.AI"], "ai", "papers",
                               ARXIV_AI_FILTER, 0.9, 30, label="arxiv-ai"), "items"))
        for fcfg in MARKET_FEEDS:
            jobs.append((ex.submit(run_safe, fetch_market_feed, fcfg, label=fcfg["source"]), "items"))
        jobs.append((ex.submit(run_safe, fetch_r_quant, label="r/quant"), "items"))
        jobs.append((ex.submit(run_safe, fetch_arxiv, ["q-fin.TR", "q-fin.PM", "q-fin.ST"], "markets",
                               "quant", None, 0.85, 12, label="arxiv-qfin"), "items"))
        for fcfg in ELECTION_FEEDS:
            jobs.append((ex.submit(run_safe, fetch_election_feed, fcfg, label=fcfg["source"]), "items"))
        # math desk: fresh arXiv preprints, one bucket per research interest
        jobs.append((ex.submit(run_safe, fetch_arxiv, ["math.AP"], "math", "pde", None, 0.95, 14, label="arxiv-pde"), "items"))
        jobs.append((ex.submit(run_safe, fetch_arxiv, ["astro-ph.EP"], "math", "astro", None, 0.95, 14, label="arxiv-astro"), "items"))
        jobs.append((ex.submit(run_safe, fetch_arxiv, ["hep-th"], "math", "string", None, 0.9, 12, label="arxiv-hepth"), "items"))
        snap_futs = [(t, ex.submit(run_safe, fetch_quote, t, label=f"quote:{t['sym']}")) for t in TICKERS]
        macro_fut = ex.submit(run_safe, fetch_macro, label="macro")
        pm_fut = ex.submit(run_safe, fetch_polymarket, label="polymarket")
        map_fut = ex.submit(run_safe, fetch_pm_map, label="pm-map")
        weather_fut = ex.submit(run_safe, fetch_weather, label="weather")

        for fut, kind in jobs:
            res, err = fut.result()
            if err:
                errors.append(err)
            elif res:
                items.extend(res)

        snapshot = []
        for t, fut in snap_futs:
            res, err = fut.result()
            if err:
                errors.append(err)
            elif res:
                snapshot.append(res)
        pm, err = pm_fut.result()
        if err:
            errors.append(err)
        state_map, err = map_fut.result()
        if err:
            errors.append(err)
        state_map = state_map or {"senate": {}, "governor": {}, "house": {}}
        macro, err = macro_fut.result()
        if err:
            errors.append(err)
        weather, err = weather_fut.result()
        if err:
            errors.append(err)

    for it in items:
        it["score"] = score(it)
    items = [it for it in items if it["score"] > 0]

    sections = {}
    for sec in ("sports", "ai", "markets", "elections", "math"):
        sections[sec] = dedupe([it for it in items if it["section"] == sec])

    # --- sports: 80/15/5 attention split across tiers
    def cap_sports(pool):
        caps = {1: 10, 2: 2, 3: 1}
        team_cap = {1: 4, 2: 1, 3: 1}
        per_team = {}
        out = []
        for tier in (1, 2, 3):
            tier_items = [it for it in pool if f"tier{tier}" in it["tags"]]
            picked = 0
            for it in tier_items:
                team = it["tags"][0]
                if picked >= caps[tier] or per_team.get(team, 0) >= team_cap[tier]:
                    continue
                out.append(it)
                per_team[team] = per_team.get(team, 0) + 1
                picked += 1
        return out

    def cap_per_source(pool, n):
        counts, out = {}, []
        for it in pool:
            if counts.get(it["source"], 0) >= n:
                continue
            counts[it["source"]] = counts.get(it["source"], 0) + 1
            out.append(it)
        return out

    sports_items = cap_sports(sections["sports"])
    ai_pool = sections["ai"]
    ai_items = cap_per_source([it for it in ai_pool if it["bucket"] == "labs"], 4)[:8]
    ai_papers = [it for it in ai_pool if it["bucket"] == "papers"][:5]
    # quant research rides in the main markets flow with reserved slots:
    # top 6 news + top 3 quant, interleaved by score
    mk_pool = sections["markets"]
    mk_news = cap_per_source([it for it in mk_pool if it["bucket"] != "quant"], 3)[:6]
    mk_quant = [it for it in mk_pool if it["bucket"] == "quant"][:3]
    market_items = sorted(mk_news + mk_quant, key=lambda x: -x["score"])
    quant_items = []  # merged above; kept for schema compatibility
    election_items = sections["elections"][:7]
    # math: the freshest preprints per research bucket
    math_items = []
    for _b in ("pde", "astro", "string"):
        math_items += [it for it in sections["math"] if it["bucket"] == _b][:8]

    # --- lead story: best of everything, lightly biased toward the front of the paper
    bias = {"sports": 1.15, "ai": 1.1, "elections": 1.0, "markets": 0.85}
    lead_pool = sports_items + ai_items + election_items + market_items
    lead = max(lead_pool, key=lambda it: it["score"] * bias[it["section"]], default=None)

    def strip_lead(lst):
        return [it for it in lst if not lead or it["id"] != lead["id"]]
    sports_items, ai_items, market_items, election_items = (
        strip_lead(sports_items), strip_lead(ai_items), strip_lead(market_items), strip_lead(election_items))

    # --- the brief: top remaining headline per section
    briefs = []
    for sec, lst in (("sports", sports_items), ("ai", ai_items),
                     ("elections", election_items), ("markets", market_items)):
        if lst:
            briefs.append({k: lst[0][k] for k in ("title", "url", "source", "section")})

    today = NOW.astimezone(timezone(timedelta(hours=-4))).date()  # ET-ish; cron runs at 6 AM ET
    yesterday = load_yesterday(today.isoformat())
    movers = compute_movers(state_map, yesterday)
    edition_no = (today - LAUNCH).days + 1

    # rotating back-page puzzle
    puzzle = None
    try:
        puzzles = json.loads((OUT_DIR / "puzzles.json").read_text())
        if puzzles:
            puzzle = puzzles[(edition_no - 1) % len(puzzles)]
    except Exception:
        pass

    # SMP league pulse: day number from the newest export in league-data/
    league = None
    try:
        exports = sorted((OUT_DIR.parent.parent / "league-data").glob("day*.json"),
                         key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
        if exports:
            league = {"day": int(re.sub(r"\D", "", exports[-1].stem)),
                      "label": json.loads(exports[-1].read_text()).get("meta", {}).get("name", "")}
    except Exception:
        pass

    # Sunday edition: the week in review, from the archives
    week = None
    if today.weekday() == 6:
        week = build_week(today, state_map)

    edition = {
        "date": today.isoformat(),
        "edition": edition_no,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "weather": weather,
        "lead": lead,
        "briefs": briefs,
        "puzzle": puzzle,
        "league": league,
        "week": week,
        "sections": {
            "sports": {"items": sports_items},
            "ai": {"items": ai_items, "papers": ai_papers},
            "markets": {"snapshot": snapshot, "macro": macro, "items": market_items,
                        "quant": quant_items, "reading": load_reading(edition_no)},
            "elections": {
                "control": (pm or {}).get("control", {}),
                "map": state_map,
                "movers": movers,
                "hot": (pm or {}).get("hot", []),
                "items": election_items,
            },
            "math": {"items": math_items},
        },
        "errors": errors,
    }

    smoke = "--smoke" in sys.argv
    if not smoke:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(edition, ensure_ascii=False, separators=(",", ":"))
        (OUT_DIR / f"{today.isoformat()}.json").write_text(payload)
        (OUT_DIR / "latest.json").write_text(payload)
        dates = sorted(p.stem for p in OUT_DIR.glob("*.json")
                       if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.stem))
        (OUT_DIR / "index.json").write_text(json.dumps(dates))
        write_rss(edition, OUT_DIR.parent.parent)

    print(f"Edition No. {edition['edition']} — {today}")
    print(f"  lead: {lead and lead['title']}")
    for sec in ("sports", "ai", "markets", "elections", "math"):
        s = edition["sections"][sec]
        n = len(s["items"]) + len(s.get("papers", [])) + len(s.get("quant", []))
        print(f"  {sec}: {n} items")
    m = edition["sections"]["elections"]["map"]
    print(f"  snapshot: {len(snapshot)} quotes · map: {len(m['senate'])} sen / {len(m['governor'])} gov / {len(m['house'])} house")
    if errors:
        print("  soft errors:")
        for e in errors:
            print(f"    - {e}")
    if smoke:
        healthy = len(errors) < 5 and lead is not None and len(snapshot) >= 4
        print(f"  SMOKE {'OK' if healthy else 'FAILING'} ({len(errors)} soft errors)")
        sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Deterministic, offline integrity checks for the rendered fantasy-football site."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


DEFAULT_ROOT = Path(__file__).resolve().parent
DEFAULT_VAULT = Path("/Users/andrewpark/Desktop/Rome/Sports/NFL/Fantasy Football")
REQUIRED_PLAYER_COLUMNS = {"player", "team", "pos", "bye", "adp", "adp_source", "proj_points", "games", "archetype", "risk", "note"}
DEFAULT_HISTORICAL_PAGES = ("meta/progress.html",)
LIVE_RESIDUE_MARKERS = re.compile(
    r"\b(?:12\s*(?:-|\s)?teams?|12tm|twelve\s+teams?|espn-ppr1\.0-12tm-std|"
    r"22\s*(?:-|\s)?picks?|pick\s+192|192\s+(?:players?|drafted|rostered|overall)|"
    r"2\.12|top\s+six\s+of\s+twelve|of\s+twelve)\b",
    re.IGNORECASE,
)
HISTORICAL_CONTEXT = re.compile(
    r"\b(?:histor(?:ical|y)|archiv(?:ed|al)|former|prior|previous|legacy|obsolete|"
    r"superseded|retired|old\s+(?:12|adp|pick)|(?:july|2026-07-25)\s+(?:build|canonical|adp)|"
    r"(?:generated|built|captured)\s+2026-07-25)\b",
    re.IGNORECASE,
)
EXPLICIT_NONLIVE_CONTEXT = re.compile(
    r"\b(?:not\s+(?:a\s+)?(?:live|current|recommend(?:ed|ation))|"
    r"do\s+not\s+(?:use|reuse|treat|carry\s+forward|present)|"
    r"illustrative\s+only|control\s+only)\b",
    re.IGNORECASE,
)
CURRENT_COMPARISON_CONTEXT = re.compile(
    r"\b(?:10\s*(?:-|\s)?teams?|10tm|ten\s+teams?)\b.*?\b(?:versus|vs\.?|compared\s+with|compared\s+to)\b|"
    r"\b(?:versus|vs\.?|compared\s+with|compared\s+to)\b.*?\b(?:10\s*(?:-|\s)?teams?|10tm|ten\s+teams?)\b|"
    r"\b(?:10\s*(?:-|\s)?teams?|10tm|ten\s+teams?)\b.*?\bthan\s+(?:it\s+was\s+)?(?:in\s+)?(?:a\s+)?12\s*(?:-|\s)?teams?\b|"
    r"\b(?:more|less|better|worse|deeper|shallower|higher|lower)\b.*?\bthan\s+(?:in\s+)?(?:a\s+)?12\s*(?:-|\s)?teams?\b",
    re.IGNORECASE,
)
REQUIRED_CONTRACT_PATTERNS = {
    "no-keeper setting": re.compile(r"\b(?:no\s+keepers|keepers\s+none)\b", re.IGNORECASE),
    "unknown late-August draft date": re.compile(
        r"\blate[\s-]+August\b.{0,120}\b(?:unknown|TBC|not\s+(?:yet\s+)?(?:known|set|fixed))\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "six-team playoff field": re.compile(r"\b(?:six|6)[\s-]+team\s+playoffs?\b", re.IGNORECASE),
}
TEXT_BLOCK = re.compile(r"<(?:p|li|td|th|h[1-6])\b[^>]*>(.*?)</(?:p|li|td|th|h[1-6])>", re.IGNORECASE | re.DOTALL)


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []
    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.urls.extend(value for key, value in attrs if key in {"href", "src"} and value)


def local_target(root: Path, page: Path, url: str, shared_root: Path | None = None) -> Path | None:
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or url.startswith(("#", "mailto:", "tel:", "data:")):
        return None
    raw = unquote(parts.path).replace("\\", "/")
    if not raw:
        return page
    # Generated sport pages can use /assets/... to reach the parent PersonalSite's
    # shared hub bundle. Other site-root URLs remain rooted at this generated directory.
    if raw.startswith("/assets/") and shared_root is not None:
        target = shared_root / raw.lstrip("/")
    else:
        target = (root / raw.lstrip("/")) if raw.startswith("/") else (page.parent / raw)
    try:
        allowed_roots = [root.resolve()]
        if shared_root is not None:
            allowed_roots.append(shared_root.resolve())
        if not any(target.resolve().is_relative_to(allowed) for allowed in allowed_roots):
            return Path("__OUTSIDE_ROOT__")
    except ValueError:
        return Path("__OUTSIDE_ROOT__")
    return target


def is_historical(root: Path, page: Path, historical_pages: set[str]) -> bool:
    return page.relative_to(root).as_posix() in historical_pages


def publishes_sequence(text: str, picks: list[int]) -> bool:
    """Accept comma, middot, slash, or dash separators without losing token order."""
    separator = r"\s*(?:,|·|/|–|—|-)\s*"
    return re.search(separator.join(map(str, picks)), text) is not None


def publishes_turn(text: str, first_turn: tuple[int, int]) -> bool:
    left, right = first_turn
    return re.search(rf"\b{left}\s*(?:,|·|/|and|&|–|—|-)\s*{right}\b", text, re.IGNORECASE) is not None


def text_of(path: Path) -> str:
    return re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8", errors="replace"))


def has_allowed_residue_context(block: str) -> bool:
    """Permit an explicit historical/superseded reference, never bare old advice."""
    return bool(HISTORICAL_CONTEXT.search(block)
                or EXPLICIT_NONLIVE_CONTEXT.search(block)
                or CURRENT_COMPARISON_CONTEXT.search(block))


def has_live_residue(page: Path) -> bool:
    """Check visible prose blocks so a historical caveat does not poison a page.

    The release sweep remains intentionally strict: an old-format marker is allowed only
    when the same paragraph/list/table cell labels it historical, non-live, or as a
    direct comparison against the current 10-team format.
    """
    raw = page.read_text(encoding="utf-8", errors="replace")
    blocks = [re.sub(r"<[^>]+>", " ", block) for block in TEXT_BLOCK.findall(raw)]
    if not blocks:
        blocks = [text_of(page)]
    return any(LIVE_RESIDUE_MARKERS.search(block) and not has_allowed_residue_context(block)
               for block in blocks)


def snake_picks(teams: int, rounds: int, slot: int = 1) -> list[int]:
    return [((round_ - 1) * teams + slot if round_ % 2 else round_ * teams - slot + 1)
            for round_ in range(1, rounds + 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl local rendered fantasy-site links and league invariants.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--team-count", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--slot", type=int, default=1)
    parser.add_argument("--settings-marker", default="10 teams", help="text that must appear in rendered HTML")
    parser.add_argument("--format-marker", default="espn-ppr1.0-10tm-std",
                        help="current league-format text that must appear in rendered HTML")
    parser.add_argument("--forbid-current-marker", action="append", default=["12 teams · ESPN"],
                        help="current-league text forbidden in rendered HTML; repeatable")
    parser.add_argument("--historical-page", action="append", default=list(DEFAULT_HISTORICAL_PAGES),
                        help="root-relative rendered page allowed to retain historical format labels; repeatable")
    parser.add_argument("--shared-root", type=Path,
                        default=DEFAULT_ROOT.parents[1],
                        help="PersonalSite root that owns shared /assets URLs")
    parser.add_argument("--vault", type=Path,
                        default=DEFAULT_VAULT if DEFAULT_VAULT.is_dir() else None,
                        help="Fantasy Football vault used to verify copied CSV byte parity when available")
    parser.add_argument("--require-adp-team-count", action="store_true", default=True,
                        help="require populated ADP rows to identify the current team count (default)")
    parser.add_argument("--allow-nonmatching-adp-team-count", action="store_false",
                        dest="require_adp_team_count",
                        help="disable the ADP team-count release invariant for historical audits")
    parser.add_argument("--allow-failures", action="store_true", help="report failures but exit zero")
    args = parser.parse_args()
    root = args.root.resolve()
    shared_root = args.shared_root.resolve() if args.shared_root and args.shared_root.is_dir() else None
    errors: list[str] = []
    entries: list[object] = []
    if args.team_count < 2 or args.rounds < 1 or not 1 <= args.slot <= args.team_count:
        parser.error("team-count >= 2, rounds >= 1, and slot in 1..team-count are required")
    pages = sorted(root.rglob("*.html"))
    if not pages:
        errors.append(f"no rendered HTML found under {root}")
    historical_pages = {PurePosixPath(path).as_posix() for path in args.historical_page}
    live_pages = [page for page in pages if not is_historical(root, page, historical_pages)]
    site_text = "\n".join(text_of(page) for page in live_pages)
    broken: dict[str, int] = {}
    for page in pages:
        parser_ = Links()
        parser_.feed(page.read_text(encoding="utf-8", errors="replace"))
        for url in parser_.urls:
            target = local_target(root, page, url, shared_root)
            if target is not None and (target.name == "__OUTSIDE_ROOT__" or not target.exists()):
                key = f"outside site root: {url}" if target.name == "__OUTSIDE_ROOT__" else url
                broken[key] = broken.get(key, 0) + 1
    for url, count in sorted(broken.items()):
        errors.append(f"{count} rendered page(s) link to missing local URL {url}")
    index_path = root / "assets" / "search-index.json"
    if not index_path.is_file():
        errors.append("missing assets/search-index.json")
    else:
        try:
            entries = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise ValueError("index is not a list")
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    errors.append(f"search-index[{index}]: entry is not an object")
                    continue
                missing_fields = [field for field in ("t", "u", "s", "d")
                                  if not isinstance(entry.get(field), str) or not entry[field].strip()]
                if missing_fields:
                    errors.append(f"search-index[{index}]: missing text field(s) {', '.join(missing_fields)}")
                    continue
                url = entry["u"]
                target = local_target(root, root / "index.html", url, shared_root)
                if target is None or target.name == "__OUTSIDE_ROOT__" or not target.is_file():
                    errors.append(f"search-index[{index}]: missing URL {url!r}")
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"assets/search-index.json: invalid ({exc})")
            entries = []
    marker = args.settings_marker.casefold()
    if marker and marker not in site_text.casefold():
        errors.append(f"rendered HTML has no settings marker: {args.settings_marker!r}")
    format_marker = args.format_marker.casefold()
    if format_marker and format_marker not in site_text.casefold():
        errors.append(f"rendered HTML has no current format marker: {args.format_marker!r}")
    for label, pattern in REQUIRED_CONTRACT_PATTERNS.items():
        if not pattern.search(site_text):
            errors.append(f"rendered HTML does not publish required league contract: {label}")
    for forbidden in args.forbid_current_marker:
        if forbidden.casefold() in site_text.casefold():
            errors.append(f"rendered HTML contains forbidden current-league marker: {forbidden!r}")
    stale_pages = [page.relative_to(root).as_posix() for page in live_pages
                   if has_live_residue(page)]
    if stale_pages:
        preview = ", ".join(stale_pages[:5])
        suffix = " …" if len(stale_pages) > 5 else ""
        errors.append(f"{len(stale_pages)} live rendered page(s) retain stale league-format residue: {preview}{suffix}")
    expected = snake_picks(args.team_count, args.rounds, args.slot)
    sequence = ", ".join(map(str, expected))
    if not publishes_sequence(site_text, expected):
        errors.append(f"rendered HTML does not publish expected snake sequence: {sequence}")
    if args.team_count == 10 and args.slot == 1 and not publishes_turn(site_text, (20, 21)):
        errors.append("rendered HTML does not publish the 10-team 1.01 turn: 20/21")
    players = root / "data" / "players.csv"
    if not players.is_file():
        errors.append("missing data/players.csv")
    else:
        with players.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing_columns = REQUIRED_PLAYER_COLUMNS - set(reader.fieldnames or ())
            if missing_columns:
                errors.append(f"data/players.csv: missing column(s) {', '.join(sorted(missing_columns))}")
            player_names: list[str] = []
            for line, row in enumerate(reader, start=2):
                name = row.get("player", "").strip()
                if not name:
                    errors.append(f"data/players.csv:{line}: missing player name")
                    continue
                player_names.append(name)
                adp = row.get("adp", "").strip()
                adp_source = row.get("adp_source", "").strip()
                if adp and args.require_adp_team_count and f"{args.team_count}tm" not in adp_source.casefold():
                    errors.append(f"data/players.csv:{line}: adp_source is not {args.team_count}-team data")
                    break
                if not adp and adp_source:
                    errors.append(f"data/players.csv:{line}: adp_source is populated without an ADP")
                    break
        duplicates = sorted({name for name in player_names if player_names.count(name) > 1})
        if duplicates:
            errors.append(f"data/players.csv: duplicate player name(s): {', '.join(duplicates[:5])}")
        if isinstance(entries, list):
            titles = [entry["t"].strip() for entry in entries
                      if isinstance(entry, dict) and isinstance(entry.get("t"), str)]
            title_counts = Counter(title.casefold() for title in titles)
            duplicate_titles = sorted(title for title, count in title_counts.items() if count > 1)
            if duplicate_titles:
                errors.append(f"search-index: duplicate title(s): {', '.join(duplicate_titles[:5])}")
            missing_search = [name for name in player_names if title_counts[name.casefold()] == 0]
            if missing_search:
                preview = ", ".join(missing_search[:5])
                suffix = " …" if len(missing_search) > 5 else ""
                errors.append(f"search-index: {len(missing_search)} data player(s) lack a search entry: {preview}{suffix}")
            repeated_search = [name for name in player_names if title_counts[name.casefold()] > 1]
            if repeated_search:
                preview = ", ".join(repeated_search[:5])
                suffix = " …" if len(repeated_search) > 5 else ""
                errors.append(f"search-index: {len(repeated_search)} data player(s) have duplicate search entries: {preview}{suffix}")
    if args.vault is not None:
        vault = args.vault.resolve()
        if not vault.is_dir():
            errors.append(f"vault is not a directory: {vault}")
        else:
            for name in ("players.csv", "player_context.csv"):
                rendered_copy = root / "data" / name
                source = vault / "Data" / name
                if not source.is_file():
                    errors.append(f"vault input missing: {source}")
                elif not rendered_copy.is_file():
                    errors.append(f"missing copied CSV: data/{name}")
                elif rendered_copy.read_bytes() != source.read_bytes():
                    errors.append(f"data/{name} does not match vault/Data/{name}")
    if errors:
        print(f"SITE VALIDATION FAILED ({len(errors)} issue(s))")
        print("\n".join(f"- {error}" for error in errors))
        return 0 if args.allow_failures else 1
    print(f"SITE VALIDATION PASSED ({len(pages)} HTML pages, {args.team_count}-team snake {expected})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

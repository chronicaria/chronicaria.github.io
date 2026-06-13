#!/usr/bin/env python3
"""Build assets/us-districts.svg from a YAPms "USA 2026 House" export.

Source: a YAPms (yapms.com) district-map SVG export, user-provided
(Downloads/YapmsMap.svg). Every district path carries region="XX-N" on
current 2026 boundaries (including the mid-decade GA/NY/TX/CA/NC/OH/FL/LA
redistricting). This script:
  * promotes region="XX-N" to id="XX-N",
  * keeps the wrapper group's scale transform (YAPms stores it in style=),
  * strips YAPms metadata/styling so the site can repaint districts,
  * rounds coordinates to 1 decimal.

Usage: python3 scripts/make_district_map.py ~/Downloads/YapmsMap.svg
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "us-districts.svg"
SVG_NS = "http://www.w3.org/2000/svg"
NUM_RE = re.compile(r"-?\d+\.\d\d+")


def round_numbers(s):
    return NUM_RE.sub(lambda m: f"{float(m.group(0)):.1f}", s)


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "YapmsMap.svg"
    raw = src.read_text(encoding="utf-8", errors="replace")
    print(f"source: {src.name}, {len(raw) / 1e6:.2f} MB")

    ET.register_namespace("", SVG_NS)
    root = ET.fromstring(raw)

    out_root = ET.Element(f"{{{SVG_NS}}}svg", {
        "viewBox": root.get("viewBox", "0 0 800 501"),
        "preserveAspectRatio": "xMidYMid meet",
    })
    g = ET.SubElement(out_root, f"{{{SVG_NS}}}g")
    # YAPms hides the layout scale inside a style attribute — keep it.
    # IMPORTANT: do NOT round the matrix. The scale factor (~0.8776) must keep
    # full precision; rounding it to 0.9 stretches every district ~2.5% so they
    # overflow their slots and overlap neighbours (the "corrupted" map).
    m = re.search(r"transform:\s*(matrix\([^)]*\))", raw)
    if m:
        g.set("transform", m.group(1))

    pending = []   # (region, d)
    seen = {}
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "path":
            continue
        region = el.get("region") or el.get("short-name") or ""
        if not re.fullmatch(r"[A-Z]{2}-(\d+|AL|)", region):
            continue
        pending.append((region, round_numbers(el.get("d", ""))))
        if re.fullmatch(r"[A-Z]{2}-\d+", region):
            seen.setdefault(region[:2], set()).add(int(region.split("-")[1]))

    n = 0
    for region, d in pending:
        st = region[:2]
        if region.endswith("-AL"):
            if st == "DC":
                continue                  # no House vote
            rid = f"{st}-1"               # at-large → district 1, matching the data keys
        elif region.endswith("-"):
            # one export glitch ("TN-"): infer the missing district number
            nums = seen.get(st, set())
            missing = [i for i in range(1, max(nums | {1}) + 2) if i not in nums]
            rid = f"{st}-{missing[0]}"
            print(f"  note: region '{region}' inferred as {rid}")
        else:
            rid = region
        ET.SubElement(g, f"{{{SVG_NS}}}path", {"id": rid, "d": d})
        n += 1

    out = ET.tostring(out_root, encoding="unicode")
    OUT.write_text(out)
    states = {i[:2] for i in re.findall(r'id="([A-Z]{2})-\d+"', out)}
    print(f"wrote {OUT.name}: {len(out) / 1e6:.2f} MB, {n} district paths, {len(states)} states")


if __name__ == "__main__":
    main()

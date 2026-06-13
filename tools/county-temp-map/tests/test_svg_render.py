from pathlib import Path

import pandas as pd

from county_temp_map.svg_render import render_svg


def test_render_svg_paints_county(tmp_path: Path) -> None:
    base = tmp_path / "base.svg"
    base.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50" viewBox="0 0 100 50">'
        '<path id="c01001" d="M0,0L10,0L10,10Z"><title>Old</title></path>'
        "</svg>"
    )
    data = pd.DataFrame(
        [
            {
                "geoid": "01001",
                "name": "Autauga",
                "state": "AL",
                "temp_f": 74.5,
                "color_hex": "#f1b4b2",
                "status": "ok",
            }
        ]
    )
    out = tmp_path / "out.svg"
    stats = render_svg(base, data, out, valid_time_utc="2026-06-12T20:00:00Z")
    text = out.read_text()
    assert stats["painted"] == 1
    assert "style=\"fill:#f1b4b2\"" in text
    assert "fill=\"#f1b4b2\"" in text
    assert "data-temp-f=\"74.500\"" in text
    assert "Autauga, AL: 74.5°F" in text

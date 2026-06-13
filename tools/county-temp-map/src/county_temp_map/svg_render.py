from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pandas as pd
from lxml import etree

from county_temp_map.config import SVG_REDIRECT_URL
from county_temp_map.download import download_file
from county_temp_map.palette import NO_DATA_COLOR, TemperatureBin, build_dynamic_temperature_bins


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
NSMAP = {None: SVG_NS, "xlink": XLINK_NS}


def ensure_base_svg(cache_dir: Path, *, overwrite: bool = False) -> Path:
    return download_file(SVG_REDIRECT_URL, cache_dir / "svg" / "Usa_counties_large.svg", overwrite=overwrite)


def _set_style_fill(element: etree._Element, color: str) -> None:
    style = element.get("style")
    if style:
        parts = [part for part in style.split(";") if part and not part.strip().lower().startswith("fill:")]
        parts.append(f"fill:{color}")
        element.set("style", ";".join(parts))
    else:
        element.set("style", f"fill:{color}")
    element.set("fill", color)


def _find_title(element: etree._Element) -> etree._Element:
    for child in element:
        if child.tag == f"{{{SVG_NS}}}title" or child.tag == "title":
            return child
    title = etree.Element(f"{{{SVG_NS}}}title")
    element.insert(0, title)
    return title


def _parse_viewbox(root: etree._Element) -> tuple[float, float, float, float]:
    view_box = root.get("viewBox")
    if view_box:
        values = [float(part) for part in view_box.replace(",", " ").split()]
        if len(values) == 4:
            return values[0], values[1], values[2], values[3]
    width = float(str(root.get("width", "990")).replace("px", ""))
    height = float(str(root.get("height", "627")).replace("px", ""))
    return 0.0, 0.0, width, height


def _add_text(parent: etree._Element, x: float, y: float, text: str, *, size: int = 12, weight: str | None = None) -> None:
    node = etree.SubElement(parent, f"{{{SVG_NS}}}text")
    node.set("x", f"{x:.1f}")
    node.set("y", f"{y:.1f}")
    node.set("font-family", "Arial, Helvetica, sans-serif")
    node.set("font-size", str(size))
    node.set("fill", "#222222")
    if weight:
        node.set("font-weight", weight)
    node.text = text


def _add_legend(root: etree._Element, valid_time_utc: str, bins: list[TemperatureBin]) -> None:
    min_x, min_y, width, height = _parse_viewbox(root)
    legend_width = 210
    root.set("viewBox", f"{min_x:g} {min_y:g} {width + legend_width:g} {height:g}")
    root.set("width", f"{width + legend_width:g}")
    root.set("height", f"{height:g}")

    group = etree.SubElement(root, f"{{{SVG_NS}}}g")
    group.set("id", "temperature-legend")
    x = min_x + width + 18
    y = min_y + 34
    _add_text(group, x, y, "County temperature", size=15, weight="700")
    _add_text(group, x, y + 20, valid_time_utc, size=11)
    _add_text(group, x, y + 36, "Scaled to current min/max", size=10)

    start_y = y + 58
    swatch_h = 9
    for index, item in enumerate(bins):
        row_y = start_y + index * 15
        rect = etree.SubElement(group, f"{{{SVG_NS}}}rect")
        rect.set("x", f"{x:.1f}")
        rect.set("y", f"{row_y:.1f}")
        rect.set("width", "18")
        rect.set("height", str(swatch_h))
        rect.set("fill", item.color)
        rect.set("stroke", "#ffffff")
        rect.set("stroke-width", "0.4")
        _add_text(group, x + 25, row_y + 8, item.label, size=9)

    no_data_y = start_y + len(bins) * 15 + 8
    rect = etree.SubElement(group, f"{{{SVG_NS}}}rect")
    rect.set("x", f"{x:.1f}")
    rect.set("y", f"{no_data_y:.1f}")
    rect.set("width", "18")
    rect.set("height", str(swatch_h))
    rect.set("fill", NO_DATA_COLOR)
    rect.set("stroke", "#ffffff")
    rect.set("stroke-width", "0.4")
    _add_text(group, x + 25, no_data_y + 8, "No data", size=9)

    footer_y = min_y + height - 42
    _add_text(group, x, footer_y, "Data: NOAA RTMA 2 m temp", size=9)
    _add_text(group, x, footer_y + 14, "County means are area-weighted", size=9)
    _add_text(group, x, footer_y + 28, "Map: Wikimedia / Census", size=9)


def render_svg(
    base_svg: Path,
    data: pd.DataFrame,
    out_svg: Path,
    *,
    valid_time_utc: str,
) -> dict[str, int]:
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree = etree.parse(str(base_svg), parser)
    root = tree.getroot()
    records = data.set_index("geoid").to_dict(orient="index")
    bins = build_dynamic_temperature_bins(data.loc[data["status"] == "ok", "temp_f"])
    painted = 0
    no_data = 0
    for element in root.xpath("//*[@id]"):
        element_id = element.get("id", "")
        if not element_id.startswith("c") or len(element_id) != 6:
            continue
        geoid = element_id[1:]
        record = records.get(geoid)
        if record is None:
            color = NO_DATA_COLOR
            title_text = f"FIPS {geoid}: no data"
            no_data += 1
        else:
            color = str(record.get("color_hex") or NO_DATA_COLOR)
            temp_f = record.get("temp_f")
            name = record.get("name", "")
            state = record.get("state", "")
            status = record.get("status", "no_data")
            if pd.notna(temp_f) and status == "ok":
                title_text = f"{name}, {state}: {float(temp_f):.1f}°F ({valid_time_utc})"
                painted += 1
            else:
                title_text = f"{name}, {state}: no data ({valid_time_utc})"
                no_data += 1
        _set_style_fill(element, color)
        element.set("data-temp-f", "" if record is None or pd.isna(record.get("temp_f")) else f"{float(record['temp_f']):.3f}")
        element.set("data-valid-time", valid_time_utc)
        _find_title(element).text = title_text

    _add_legend(root, valid_time_utc, bins)
    out_svg.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out_svg), encoding="utf-8", xml_declaration=True, pretty_print=False)
    return {"painted": painted, "no_data": no_data}


def export_png(svg_path: Path, png_path: Path) -> bool:
    try:
        import cairosvg

        cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=1600)
        return png_path.exists() and png_path.stat().st_size > 0
    except Exception:
        pass

    if shutil.which("qlmanage") is None:
        return False
    generated = png_path.parent / f"{svg_path.name}.png"
    generated.unlink(missing_ok=True)
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", "1600", "-o", str(png_path.parent), str(svg_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    if generated.exists() and generated.stat().st_size > 0:
        generated.replace(png_path)
        return True
    return False

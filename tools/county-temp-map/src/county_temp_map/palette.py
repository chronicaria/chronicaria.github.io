from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, isnan
from typing import Iterable

DEMOCRATIC_RAMP = (
    "#eef3fd",
    "#dee8fb",
    "#b4c7ec",
    "#8da9e2",
    "#678cd7",
    "#4170cd",
    "#3358a2",
    "#244079",
)

REPUBLICAN_RAMP = (
    "#fdeeee",
    "#fbdedd",
    "#f1b4b2",
    "#ed8783",
    "#e55651",
    "#d02923",
    "#b00600",
    "#850400",
)

NO_DATA_COLOR = "#d9d9d9"
WIKIPEDIA_TEMPERATURE_COLORS = tuple(reversed(DEMOCRATIC_RAMP)) + REPUBLICAN_RAMP


@dataclass(frozen=True)
class TemperatureBin:
    low_f: float
    high_f: float
    color: str
    label: str


def _valid_float_values(values: Iterable[object]) -> list[float]:
    valid: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number):
            valid.append(number)
    return valid


def _format_temp(value: float) -> str:
    return f"{value:.1f}°F"


def build_dynamic_temperature_bins(values: Iterable[object]) -> list[TemperatureBin]:
    valid = _valid_float_values(values)
    if not valid:
        return []

    min_f = min(valid)
    max_f = max(valid)
    colors = WIKIPEDIA_TEMPERATURE_COLORS
    if min_f == max_f:
        color = colors[len(colors) // 2]
        return [TemperatureBin(min_f, max_f, color, _format_temp(min_f))]

    step = (max_f - min_f) / len(colors)
    bins: list[TemperatureBin] = []
    for index, color in enumerate(colors):
        low = min_f + step * index
        high = max_f if index == len(colors) - 1 else min_f + step * (index + 1)
        bins.append(TemperatureBin(low, high, color, f"{_format_temp(low)} to {_format_temp(high)}"))
    return bins


def color_for_temp_f(temp_f: float | None, bins: list[TemperatureBin] | None = None) -> str:
    if temp_f is None:
        return NO_DATA_COLOR
    try:
        if isnan(temp_f):
            return NO_DATA_COLOR
    except TypeError:
        return NO_DATA_COLOR
    active_bins = bins or build_dynamic_temperature_bins([temp_f])
    if not active_bins:
        return NO_DATA_COLOR
    if temp_f <= active_bins[0].low_f:
        return active_bins[0].color
    if temp_f >= active_bins[-1].high_f:
        return active_bins[-1].color
    for item in active_bins:
        if item.low_f <= temp_f < item.high_f:
            return item.color
    return NO_DATA_COLOR


def temp_c_to_f(temp_c: float) -> float:
    return temp_c * 9.0 / 5.0 + 32.0


def temp_f_to_c(temp_f: float) -> float:
    return (temp_f - 32.0) * 5.0 / 9.0

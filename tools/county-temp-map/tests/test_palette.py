from county_temp_map.palette import WIKIPEDIA_TEMPERATURE_COLORS, build_dynamic_temperature_bins, color_for_temp_f


def test_dynamic_bins_use_data_min_and_max() -> None:
    bins = build_dynamic_temperature_bins([40, 60, 80, 100])
    assert bins[0].low_f == 40
    assert bins[-1].high_f == 100
    assert bins[0].color == "#244079"
    assert bins[-1].color == "#850400"


def test_dynamic_colors_are_only_wikipedia_scheme_colors() -> None:
    bins = build_dynamic_temperature_bins([40, 100])
    colors = {color_for_temp_f(value, bins) for value in [40, 50, 60, 70, 80, 90, 100]}
    assert colors <= set(WIKIPEDIA_TEMPERATURE_COLORS)


def test_color_handles_no_data() -> None:
    assert color_for_temp_f(None) == "#d9d9d9"

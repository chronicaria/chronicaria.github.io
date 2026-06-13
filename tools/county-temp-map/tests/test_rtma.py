from datetime import UTC, datetime

from county_temp_map.rtma import parse_idx, parse_valid_time, tmp_byte_range


def test_parse_idx_and_tmp_byte_range() -> None:
    text = "\n".join(
        [
            "1:0:d=2026061220:HGT:surface:anl:",
            "2:7490118:d=2026061220:PRES:surface:anl:",
            "3:14980236:d=2026061220:TMP:2 m above ground:anl:",
            "4:21065993:d=2026061220:DPT:2 m above ground:anl:",
        ]
    )
    records = parse_idx(text)
    byte_range = tmp_byte_range(records)
    assert byte_range.start == 14980236
    assert byte_range.end_inclusive == 21065992


def test_parse_valid_time_to_utc_hour() -> None:
    assert parse_valid_time("2026-06-12T20:31:42Z") == datetime(2026, 6, 12, 20, tzinfo=UTC)

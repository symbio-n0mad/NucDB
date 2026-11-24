import math

import pytest

from nucdb import units
from nucdb.units import UnitError


def test_year_definition():
    assert units.YEAR_S == pytest.approx(31_556_926.08, abs=1e-6)


@pytest.mark.parametrize("value, frm, to, expected", [
    (3.8235, "d", "h", 91.764),
    (1, "a", "d", 365.2422),
    (90, "min", "h", 1.5),
    (1, "MeV", "keV", 1000),
    (1, "u", "MeV/c²", 931.49410242),
    (1, "b", "cm²", 1e-24),
    (5, "%", "1", 0.05),
    (1, "1/h", "1/s", 1 / 3600),
    (2, "us", "ns", 2000),
])
def test_convert(value, frm, to, expected):
    assert units.convert(value, frm, to) == pytest.approx(expected, rel=1e-12)


def test_convert_kind_mismatch():
    with pytest.raises(UnitError):
        units.convert(1, "s", "keV")


@pytest.mark.parametrize("unit, canon", [
    ("Jahre", "a"), ("y", "a"), ("MS", "ms"), ("Std", "h"), ("mev", "MeV"), ("KEV", "keV"),
    ("s^-1", "1/s"), ("/d", "1/d"), ("h⁻¹", "1/h"), ("barn", "b"),
])
def test_lookup_aliases(unit, canon):
    assert units.lookup(unit)[1] == canon


@pytest.mark.parametrize("text, value, unc", [
    ("5,2714(5)", 5.2714, 0.0005),
    ("2.60E-15(5)", 2.60e-15, 0.05e-15),
    ("12.3 ± 0.4", 12.3, 0.4),
    ("1.234,5", 1234.5, None),
    ("1,234.5", 1234.5, None),
    ("31 556 926", 31556926, None),
    ("−3.5", -3.5, None),
    ("787.2(6)", 787.2, 0.6),
    ("1925.28(14)", 1925.28, 0.14),
])
def test_parse_number(text, value, unc):
    v, u = units.parse_number(text)
    assert v == pytest.approx(value)
    if unc is None:
        assert u is None
    else:
        assert u == pytest.approx(unc)


def test_parse_quantity_time_and_decimal_comma():
    q = units.parse_quantity("5,2711(8) a", "time")
    assert q.value == pytest.approx(5.2711 * units.YEAR_S)
    assert q.unc == pytest.approx(0.0008 * units.YEAR_S)
    assert q.unit == "s"


def test_half_life_accepts_decay_constant():
    q = units.parse_quantity("2.1e-6 1/s", "half_life")
    assert q.value == pytest.approx(math.log(2) / 2.1e-6)
    q2 = units.parse_quantity("3.8235 d", "half_life")
    assert q2.value == pytest.approx(3.8235 * 86400)


def test_space_does_not_glue_number_and_unit():
    q = units.parse_quantity("5 1/s", "half_life")
    assert q.value == pytest.approx(math.log(2) / 5)


def test_missing_unit():
    with pytest.raises(UnitError):
        units.parse_quantity("5", "time")
    assert units.parse_quantity("5", "time", default_unit="h").value == 18000


def test_lambda_roundtrip_with_uncertainty():
    lam, ulam = units.half_life_to_lambda(100.0, 1.0)
    t, ut = units.lambda_to_half_life(lam, ulam)
    assert t == pytest.approx(100.0) and ut == pytest.approx(1.0)


@pytest.mark.parametrize("seconds, unit", [
    (0.5e-6, "ns"), (2.0, "s"), (90, "min"), (5000, "h"), (2 * 86400, "d"), (5 * units.YEAR_S, "a"),
])
def test_auto_time_unit(seconds, unit):
    assert units.auto_time_unit(seconds) == unit


def test_format():
    assert units.format_measurement(5.2711, 0.0008) == "5.2711(8)"
    assert units.format_measurement(1925.28, 0.14) == "1925.28(14)"
    assert units.format_measurement(1925.2, 2.9) == "1925.2(29)"
    assert units.format_measurement(12345.0, 50.0) == "12350(50)"
    assert units.format_time(5.2711 * units.YEAR_S, unc=0.0008 * units.YEAR_S) == "5.2711(8) a"
    assert units.format_time(5.2711 * units.YEAR_S, "d", decimal_comma=True) == "1925 d"
    assert units.format_time(1.248e9 * units.YEAR_S) == "1.248e9 a"


def test_no_float_noise():
    assert units.from_base(30.018 * units.YEAR_S, "a", "time") == 30.018
    assert units.convert(3.8235, "d", "h") == 91.764

import pytest

from nucdb import names
from nucdb.names import NuclideId, NuclideNameError


@pytest.mark.parametrize("text, expected", [
    ("Co-60", "Co-60"), ("60Co", "Co-60"), ("Co60", "Co-60"), ("60-Co", "Co-60"), ("CO-60", "Co-60"),
    ("co 60", "Co-60"), ("Tc-99m", "Tc-99m"), ("99mTc", "Tc-99m"), ("Tc99m", "Tc-99m"),
    ("TC-99M", "Tc-99m"), ("Hf-178m2", "Hf-178m2"), ("178m2Hf", "Hf-178m2"), ("Am-242g", "Am-242"),
    ("60Mn", "Mn-60"), ("99Mo", "Mo-99"), ("Mo99", "Mo-99"), ("110mAg", "Ag-110m"), ("54Mn", "Mn-54"),
    ("N-14", "N-14"), ("n-14", "N-14"), ("n", "n-1"), ("n-1", "n-1"), ("D", "H-2"), ("T", "H-3"), ("U-235", "U-235"),
    (" 16-N ", "N-16"), ("239-U ", "U-239"), ("Og-294", "Og-294"),
])
def test_normalize(text, expected):
    assert names.normalize(text) == expected


@pytest.mark.parametrize("text", ["", "Co", "Xx-12", "Co-", "60", "Fe-20", "n-2", "Co-60x"])
def test_invalid(text):
    with pytest.raises(NuclideNameError):
        names.parse(text)


def test_nuclide_id():
    nid = names.parse("Tc-99m")
    assert nid == NuclideId(43, 99, 1)
    assert nid.n == 56 and nid.symbol == "Tc" and nid.name == "Tc-99m"


def test_sort_key_order():
    assert sorted(["U-238", "H-3", "Tc-99m", "Tc-99"], key=names.sort_key) == ["H-3", "Tc-99", "Tc-99m", "U-238"]


def test_is_canonical():
    assert names.is_canonical("Co-60")
    assert not names.is_canonical("60Co")

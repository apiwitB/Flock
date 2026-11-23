import pytest

from flock_contracts.plates import (
    OCR_CHARSET,
    THAI_CONSONANTS,
    clean_plate_text,
    is_standard_plate,
    normalize_for_search,
    plate_distance,
)
from flock_contracts.provinces import PROVINCES, normalize_province


def test_charset_has_44_consonants_and_10_digits_without_duplicates():
    assert len(THAI_CONSONANTS) == 44
    assert len(OCR_CHARSET) == 54
    assert len(set(OCR_CHARSET)) == 54


def test_clean_strips_spaces_dashes_dots():
    assert clean_plate_text(" 1กข - 1234. ") == "1กข1234"


@pytest.mark.parametrize("text", ["กข1234", "1กข1234", "ก1", "9ฮฮ9999", "กข 1234"])
def test_standard_plates(text):
    assert is_standard_plate(text)


@pytest.mark.parametrize("text", ["", "1234", "กขค123", "กข12345", "กข0123", "0กข123", "ABC123"])
def test_non_standard_plates(text):
    assert not is_standard_plate(text)


def test_normalize_collapses_confusable_letters():
    assert normalize_for_search("ชต1234") == normalize_for_search("ขด1234")
    assert normalize_for_search("กข 1234") == normalize_for_search("กข1234")


def test_normalize_keeps_unrelated_letters_apart():
    assert normalize_for_search("กข1234") != normalize_for_search("งข1234")


def test_distance_exact_is_zero():
    assert plate_distance("1กข 1234", "1กข1234") == 0


def test_confusable_substitution_is_cheaper_than_unrelated():
    assert plate_distance("กข1234", "กช1234") == pytest.approx(0.4)
    assert plate_distance("กข1234", "กง1234") == 1


def test_insert_and_delete_cost_one():
    assert plate_distance("กข1234", "กข123") == 1
    assert plate_distance("", "กข") == 2


def test_provinces_count_and_order_stable():
    assert len(PROVINCES) == 78  # 77 จังหวัด + เบตง
    assert len(set(PROVINCES)) == 78
    assert PROVINCES[0] == "กรุงเทพมหานคร"
    assert PROVINCES[-1] == "เบตง"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("กทม", "กรุงเทพมหานคร"),
        ("กรุงเทพฯ", "กรุงเทพมหานคร"),
        ("อยุธยา", "พระนครศรีอยุธยา"),
        (" ขอนแก่น ", "ขอนแก่น"),
        ("ไม่มีจังหวัดนี้", None),
        (None, None),
    ],
)
def test_normalize_province(raw, expected):
    assert normalize_province(raw) == expected

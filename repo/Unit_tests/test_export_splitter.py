"""Multipart row splitter for export jobs."""
import pytest

from apps.exports.services import ROW_CAP_PER_FILE, split_rows

pytestmark = pytest.mark.no_db


def test_zero_rows_yields_one_empty_part():
    parts = split_rows(0)
    assert parts == [(1, 0)]


def test_under_cap_single_part():
    parts = split_rows(123)
    assert parts == [(1, 123)]


def test_exact_cap_single_full_part():
    parts = split_rows(ROW_CAP_PER_FILE)
    assert parts == [(1, ROW_CAP_PER_FILE)]


def test_over_cap_splits_into_multiple_parts():
    parts = split_rows(ROW_CAP_PER_FILE * 2 + 17)
    assert parts == [(1, ROW_CAP_PER_FILE), (2, ROW_CAP_PER_FILE), (3, 17)]


def test_over_cap_exact_multiple_no_extra_part():
    parts = split_rows(ROW_CAP_PER_FILE * 3)
    assert parts == [(1, ROW_CAP_PER_FILE), (2, ROW_CAP_PER_FILE), (3, ROW_CAP_PER_FILE)]

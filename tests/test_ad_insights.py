"""Tests for splitting insights syncs into async job time ranges."""

import pendulum

from tap_facebook.streams.ad_insights import report_time_ranges


def ranges(start: str, end: str, time_increment: int, days_per_job: int) -> list[tuple[str, str]]:
    return [
        (since.to_date_string(), until.to_date_string())
        for since, until in report_time_ranges(
            pendulum.parse(start).date(),
            pendulum.parse(end).date(),
            time_increment,
            days_per_job,
        )
    ]


def test_lookback_window_fits_in_one_job():
    assert ranges("2026-09-17", "2026-10-16", 1, 31) == [("2026-09-17", "2026-10-16")]


def test_ranges_are_contiguous_and_do_not_overlap():
    assert ranges("2026-09-01", "2026-09-10", 1, 4) == [
        ("2026-09-01", "2026-09-04"),
        ("2026-09-05", "2026-09-08"),
        ("2026-09-09", "2026-09-10"),
    ]


def test_one_day_per_job():
    assert ranges("2026-09-01", "2026-09-03", 1, 1) == [
        ("2026-09-01", "2026-09-01"),
        ("2026-09-02", "2026-09-02"),
        ("2026-09-03", "2026-09-03"),
    ]


def test_jobs_hold_whole_time_increments():
    # 10 days per job rounds down to 7, so no week is split across two jobs.
    assert ranges("2026-09-01", "2026-09-20", 7, 10) == [
        ("2026-09-01", "2026-09-07"),
        ("2026-09-08", "2026-09-14"),
        ("2026-09-15", "2026-09-20"),
    ]


def test_jobs_hold_at_least_one_time_increment():
    assert ranges("2026-09-01", "2026-09-14", 7, 3) == [
        ("2026-09-01", "2026-09-07"),
        ("2026-09-08", "2026-09-14"),
    ]


def test_start_after_end_requests_nothing():
    assert ranges("2026-09-02", "2026-09-01", 1, 31) == []

"""Tests for splitting insights syncs into async jobs and retrying rate-limited calls."""

import json
import logging
from collections.abc import Callable

import pendulum
import pytest
from facebook_business.exceptions import FacebookRequestError

from tap_facebook.streams import ad_insights
from tap_facebook.streams.ad_insights import call_with_backoff, report_time_ranges


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


def facebook_error(code: int, subcode: int | None = None) -> FacebookRequestError:
    error = {"code": code, "error_subcode": subcode, "is_transient": True}
    body = json.dumps({"error": error})
    return FacebookRequestError("Call was not successful", {}, 403, {}, body)


def flaky_call(*errors: FacebookRequestError) -> Callable[[], str]:
    remaining = list(errors)

    def call() -> str:
        if remaining:
            raise remaining.pop(0)
        return "result"

    return call


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(ad_insights.time, "sleep", sleeps.append)
    return sleeps


logger = logging.getLogger(__name__)


def test_call_without_errors_does_not_back_off(sleeps: list[float]):
    assert call_with_backoff(flaky_call(), logger) == ("result", 0)
    assert sleeps == []


def test_rate_limits_back_off_exponentially(sleeps: list[float]):
    call = flaky_call(facebook_error(4, 1504022), facebook_error(17), facebook_error(80000))
    assert call_with_backoff(call, logger) == ("result", 60 + 120 + 240)
    assert sleeps == [60, 120, 240]


def test_backoff_is_capped(sleeps: list[float]):
    call = flaky_call(*[facebook_error(4, 1504022)] * 6)
    assert call_with_backoff(call, logger) == ("result", 2700)
    assert sleeps == [60, 120, 240, 480, 900, 900]


def test_gives_up_after_max_retries(sleeps: list[float]):
    call = flaky_call(*[facebook_error(4, 1504022)] * 7)
    with pytest.raises(FacebookRequestError):
        call_with_backoff(call, logger)
    assert len(sleeps) == 6


def test_other_errors_are_not_retried(sleeps: list[float]):
    call = flaky_call(facebook_error(100, 33))
    with pytest.raises(FacebookRequestError):
        call_with_backoff(call, logger)
    assert sleeps == []

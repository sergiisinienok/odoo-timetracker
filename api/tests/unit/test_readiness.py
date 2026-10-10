from datetime import UTC, datetime, timedelta

from tti.ops.readiness import evaluate

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _eval(**overrides):
    args = {
        "odoo_reachable": True,
        "profile_loaded": True,
        "db_reachable": True,
        "oldest_pending_created_at": None,
        "now": NOW,
    }
    return evaluate(**{**args, **overrides})


def test_all_good_is_ready():
    assert _eval().ready


def test_empty_queue_has_no_age():
    assert _eval().oldest_pending_age_seconds is None


def test_pending_row_under_15_minutes_is_ready():
    r = _eval(oldest_pending_created_at=NOW - timedelta(minutes=14, seconds=59))
    assert r.ready and r.oldest_pending_age_seconds == 899


def test_pending_row_at_15_minutes_is_not_ready():
    r = _eval(oldest_pending_created_at=NOW - timedelta(minutes=15))
    assert not r.ready and r.checks["outbox"] is False


def test_each_dependency_failure_is_not_ready():
    for key, check in (("odoo_reachable", "odoo"), ("profile_loaded", "profile"), ("db_reachable", "database")):
        r = _eval(**{key: False})
        assert not r.ready and r.checks[check] is False


def test_file_logging_rotates_and_writes_json(tmp_path, monkeypatch):
    import json
    import logging

    from tti.logging import configure_logging

    log_file = tmp_path / "logs" / "t.log"
    monkeypatch.setenv("LOG_FILE", str(log_file))
    configure_logging("INFO")
    logging.getLogger("t").info("hello", extra={"k": "v"})
    handlers = logging.getLogger().handlers
    assert any(type(h).__name__ == "RotatingFileHandler" for h in handlers)
    for h in handlers:
        h.flush()
    assert json.loads(log_file.read_text().splitlines()[-1])["message"] == "hello"
    configure_logging("INFO")  # restore: unset below

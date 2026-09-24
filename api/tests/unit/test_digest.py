from datetime import date

from tti.ops.digest import Digest, OutboxItem, last_working_days, render


def test_working_days_skip_weekends():
    # Thursday 2026-09-24 -> Wed, Tue, Mon, Fri, Thu
    assert last_working_days(date(2026, 9, 24)) == [
        date(2026, 9, 23), date(2026, 9, 22), date(2026, 9, 21), date(2026, 9, 18), date(2026, 9, 17),
    ]


def test_working_days_from_monday_start_on_friday():
    assert last_working_days(date(2026, 9, 21))[0] == date(2026, 9, 18)


def test_empty_digest_says_all_clear():
    subject, body = render(Digest(), date(2026, 9, 24))
    assert "all clear" in subject and "None." in body


def test_digest_counts_and_escapes():
    item = OutboxItem("A <b>", date(2026, 9, 1), "create", 3, 42, "boom <script>")
    d = Digest(failed=[item], no_assignment=["Bob"])
    subject, body = render(d, date(2026, 9, 24))
    assert "2 item(s)" in subject
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "Bob" in body


def test_digest_body_has_no_money_words():
    _, body = render(Digest(), date(2026, 9, 24))
    assert not any(w in body.lower() for w in ("price", "amount", "rate", "currency"))


def test_seconds_until_rolls_to_tomorrow_once_hour_passed():
    from datetime import datetime, timezone
    from tti.ops.scheduler import seconds_until

    assert seconds_until(datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc), 7) == 3600
    assert seconds_until(datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc), 7) == 86400

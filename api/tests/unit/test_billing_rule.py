"""The full truth table for decision 0011: 2 project values x 3 task values x
mapped/unmapped = 12 cases. Every row is written out by hand, not derived
from the rule under test."""

import pytest

from tti.domain.billing import BILLABLE_WITHOUT_ORDER_LINE, TaskOverride, resolve_billing

SAME = TaskOverride.SAME_AS_PROJECT
YES = TaskOverride.BILLABLE
NO = TaskOverride.NOT_BILLABLE
LINE = 42
WARN = BILLABLE_WITHOUT_ORDER_LINE

# (project_billable, task_override, mapped_so_line_id, expected)
TRUTH_TABLE = [
    # billable project
    (True, SAME, LINE, (LINE, None)),
    (True, SAME, None, (None, WARN)),
    (True, YES, LINE, (LINE, None)),
    (True, YES, None, (None, WARN)),
    (True, NO, LINE, (None, None)),
    (True, NO, None, (None, None)),
    # unbillable project
    (False, SAME, LINE, (None, None)),
    (False, SAME, None, (None, None)),
    (False, YES, LINE, (LINE, None)),
    (False, YES, None, (None, WARN)),
    (False, NO, LINE, (None, None)),
    (False, NO, None, (None, None)),
]


def test_table_covers_every_combination_once():
    keys = {(p, t, m is not None) for p, t, m, _ in TRUTH_TABLE}
    assert len(TRUTH_TABLE) == 12 and len(keys) == 12


@pytest.mark.parametrize("project,task,mapped,expected", TRUTH_TABLE)
def test_truth_table(project, task, mapped, expected):
    assert resolve_billing(project, task, mapped) == expected


def test_warning_name_is_the_one_the_plan_uses():
    assert WARN == "billable_without_order_line"

"""Acceptance tests for the `raster-high-risk` task. Copied in by scripts/agent_bench.py after the agent finished.

Every *threshold* asserted here is written down in the project's own documents (Invariant 4 of CONSTITUTION.md and
the fraud-detection section of ARCHITECTURE.md: `is_vector_pdf == False` → High Risk → Risk Score >= 75, with
Open Banking as the declared alternative). An agent without those documents can invent a defensible rule and still
fail these tests — that is the measurement, not a trick.

No *identifier* is asserted. The pack writes the rule as prose («категории `High Risk` (Risk Score >= 75)») and
never spells a constant, so demanding the literal `HIGH_RISK` would grade both arms on a naming guess and decide a
judgement task by string equality. `test_category_label_is_consistent_with_the_threshold` asserts the partition
instead: whatever the labels are called, 75 and 80 must fall on the same side and 18 on the other."""
from __future__ import annotations

from decimal import Decimal

import scoring

STRONG = dict(monthly_income=Decimal("250000.00"), stability_index=Decimal("0.95"), rent=40000)


def test_raster_statement_is_at_least_75():
    assert scoring.score(is_vector_pdf=False, open_banking_connected=False, **STRONG) >= 75


def test_raster_cannot_be_rescued_by_a_perfect_income():
    assert scoring.score(is_vector_pdf=False, open_banking_connected=False,
                         monthly_income=Decimal("10000000.00"), stability_index=Decimal("0.99"), rent=40000) >= 75


def test_open_banking_is_not_penalised():
    """Open Banking is the declared alternative to a vector PDF, so a scan next to it is not High Risk."""
    assert scoring.score(is_vector_pdf=False, open_banking_connected=True, **STRONG) < 75


def test_vector_pdf_with_strong_cashflow_is_low_risk():
    assert scoring.score(is_vector_pdf=True, open_banking_connected=False, **STRONG) < 40


def test_the_score_stays_inside_its_range():
    for vector in (True, False):
        for ob in (True, False):
            value = scoring.score(is_vector_pdf=vector, open_banking_connected=ob, **STRONG)
            assert isinstance(value, int) and 0 <= value <= 100


def test_category_label_is_consistent_with_the_threshold():
    """The threshold is in the documents; the spelling of the label is not, so only the partition is asserted."""
    assert scoring.category(75) == scoring.category(80), "75 is the High Risk floor: 75 and 80 are the same category"
    assert scoring.category(80) != scoring.category(18), "a score of 80 and a score of 18 cannot be one category"

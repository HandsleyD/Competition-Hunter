from decimal import Decimal

from competition_hunter.pipeline.score import WEIGHTS, score, score_all
from tests.factories import competition


def test_score_uses_default_prize_value_when_unenriched():
    comp = competition(prize_value_gbp=None, entry_mechanic="web_form")

    expected = WEIGHTS["default_prize_value_gbp"] / 2.0  # effort_minutes for web_form
    assert score(comp) == round(expected, 4)


def test_skill_based_scores_higher_than_otherwise_identical_competition():
    plain = competition(id="a", prize_value_gbp=Decimal("100"))
    skill_based = competition(id="b", prize_value_gbp=Decimal("100"), is_skill_based=True)

    assert score(skill_based) > score(plain)


def test_requiring_purchase_scores_lower():
    plain = competition(id="a", prize_value_gbp=Decimal("100"))
    needs_purchase = competition(id="b", prize_value_gbp=Decimal("100"), requires_purchase=True)

    assert score(needs_purchase) < score(plain)


def test_more_sources_scores_lower():
    exclusive = competition(id="a", prize_value_gbp=Decimal("100"), source_count=1)
    widely_listed = competition(id="b", prize_value_gbp=Decimal("100"), source_count=5)

    assert score(widely_listed) < score(exclusive)


def test_higher_effort_mechanic_scores_lower():
    web_form = competition(id="a", prize_value_gbp=Decimal("100"), entry_mechanic="web_form")
    postal = competition(id="b", prize_value_gbp=Decimal("100"), entry_mechanic="postal")

    assert score(postal) < score(web_form)


def test_score_all_sets_the_score_field_without_touching_anything_else():
    comps = [competition(id="a", title="A"), competition(id="b", title="B")]

    scored = score_all(comps)

    assert all(c.score > 0 for c in scored)
    assert [c.title for c in scored] == ["A", "B"]

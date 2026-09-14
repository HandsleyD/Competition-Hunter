from competition_hunter.entry.router import route
from tests.factories import competition


def test_requires_purchase_is_skipped_even_if_otherwise_auto_eligible():
    comp = competition(entry_mechanic="web_form", requires_purchase=True)

    assert route(comp) == "skip"


def test_web_form_routes_to_auto():
    comp = competition(entry_mechanic="web_form")

    assert route(comp) == "auto"


def test_social_postal_and_email_route_to_manual_queue():
    for mechanic in ("social", "postal", "email"):
        comp = competition(entry_mechanic=mechanic)
        assert route(comp) == "manual_queue"


def test_skill_based_routes_to_manual_queue_even_for_web_form():
    comp = competition(entry_mechanic="web_form", is_skill_based=True)

    assert route(comp) == "manual_queue"


def test_unhandled_mechanics_default_to_manual_queue():
    for mechanic in ("gleam", "viralsweep", "rafflecopter", "unknown"):
        comp = competition(entry_mechanic=mechanic)
        assert route(comp) == "manual_queue"


def test_requires_purchase_takes_priority_over_everything_else():
    comp = competition(entry_mechanic="social", requires_purchase=True, is_skill_based=True)

    assert route(comp) == "skip"

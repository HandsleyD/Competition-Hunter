"""EV ranking: score = (prize_value x P(win) proxy) / entry_effort_minutes.

design-options.md §5: optimise for £ per minute, not prize size. `P(win)`
isn't observable, so it's approximated from the two strongest signals the
table there names — a skill/tiebreaker question, and being listed on few
sources — plus a purchase requirement working against it. `effort_minutes`
isn't an extracted field; it's proxied from `entry_mechanic`, which
enrichment does extract.

Weights live in one module-level dict, as the plan asks, so they're easy to
retune once the wins ledger (phase 4) gives real feedback instead of guesses.
"""

from __future__ import annotations

from collections.abc import Iterable

from competition_hunter.models import Competition, EntryMechanic

WEIGHTS = {
    "is_skill_based_multiplier": 3.0,  # cuts entrants by an order of magnitude in practice
    "requires_purchase_multiplier": 0.2,  # filters out casual entrants, and most of the value
    "default_prize_value_gbp": 10.0,  # nominal stand-in when enrichment found no prize value
}

# Rough minutes-to-enter per mechanic, used as the effort denominator until a
# measured figure exists.
EFFORT_MINUTES: dict[EntryMechanic, float] = {
    "web_form": 2.0,
    "gleam": 3.0,
    "viralsweep": 3.0,
    "rafflecopter": 3.0,
    "social": 1.0,
    "email": 1.0,
    "postal": 5.0,
    "unknown": 3.0,
}


def score(competition: Competition) -> float:
    prize_value = (
        float(competition.prize_value_gbp)
        if competition.prize_value_gbp is not None
        else WEIGHTS["default_prize_value_gbp"]
    )

    p_win_proxy = 1.0
    if competition.is_skill_based:
        p_win_proxy *= WEIGHTS["is_skill_based_multiplier"]
    if competition.requires_purchase:
        p_win_proxy *= WEIGHTS["requires_purchase_multiplier"]
    p_win_proxy /= max(competition.source_count, 1)

    effort_minutes = EFFORT_MINUTES[competition.entry_mechanic]
    return round((prize_value * p_win_proxy) / effort_minutes, 4)


def score_all(competitions: Iterable[Competition]) -> list[Competition]:
    return [c.model_copy(update={"score": score(c)}) for c in competitions]

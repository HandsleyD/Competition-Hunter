"""Classify a scored competition into auto / manual-queue / skip.

implementation-plan.md's routing table:

| Condition                                              | Route         |
|---------------------------------------------------------|---------------|
| entry_mechanic == "web_form", no CAPTCHA detected       | auto-submit   |
| CAPTCHA present                                          | manual queue  |
| entry_mechanic in {social, postal, email}               | manual queue  |
| is_skill_based (needs a written tiebreaker)             | manual queue  |
| requires_purchase                                        | skip          |

CAPTCHA presence can't be known until the entry page actually loads, so this
module only produces the static, pre-fetch decision; `entry/autofill.py`
handles the CAPTCHA check and downgrades "auto" to a queued/manual outcome
itself if one turns up.
"""

from __future__ import annotations

from typing import Literal

from competition_hunter.models import Competition

RouteDecision = Literal["auto", "manual_queue", "skip"]

_MANUAL_QUEUE_MECHANICS = {"social", "postal", "email"}


def route(competition: Competition) -> RouteDecision:
    if competition.requires_purchase:
        return "skip"
    if competition.entry_mechanic in _MANUAL_QUEUE_MECHANICS:
        return "manual_queue"
    if competition.is_skill_based:
        return "manual_queue"
    if competition.entry_mechanic == "web_form":
        return "auto"
    # gleam/viralsweep/rafflecopter/unknown: not yet special-cased for
    # auto-entry, so the safe default is a human looks at it rather than a
    # skip, which would silently drop a winnable comp.
    return "manual_queue"

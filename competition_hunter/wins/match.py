"""Fuzzy-match a classified win back to a competition this project actually
entered — a title guessed from an email is never going to match verbatim.
"""

from __future__ import annotations

import re
import sqlite3

from competition_hunter import store
from competition_hunter.models import Competition
from competition_hunter.wins.classify import WinClassification

_WORD_RE = re.compile(r"[a-z0-9]+")

# Below this, two titles are treated as coincidentally similar rather than
# the same competition — loose enough to tolerate a paraphrased email
# subject ("You won our hamper giveaway!" vs "Win a Luxury Hamper") without
# matching two unrelated comps that just share one common word.
_MATCH_THRESHOLD = 0.4


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _similarity(a: set[str], b: set[str]) -> float:
    """Containment rather than Jaccard: an LLM's title guess is usually
    shorter and vaguer than the real listing title (which often carries
    extra words like a prize value or a year), so what matters is how much
    of the *guess* shows up in the title, not how much of the title's
    extra wording doesn't show up in the guess."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def find_matching_competition(
    conn: sqlite3.Connection, classification: WinClassification
) -> Competition | None:
    guess = classification.competition_title_guess or classification.prize_description
    guess_tokens = _tokens(guess)
    if not guess_tokens:
        return None

    best_score = 0.0
    best_competition: Competition | None = None
    for competition in store.get_entered_competitions(conn):
        score = _similarity(guess_tokens, _tokens(competition.title))
        if score >= _MATCH_THRESHOLD and score > best_score:
            best_score = score
            best_competition = competition

    return best_competition

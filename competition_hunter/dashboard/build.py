"""Static HTML dashboard — GitHub Pages, per design-options.md §9.

Sorted by score — "£ per minute", not prize size (design-options.md §5) —
with a clickable header to re-sort by any column, and a closing-soon flag
so urgency isn't lost to the ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from competition_hunter.models import Competition

TEMPLATES_DIR = Path(__file__).parent / "templates"
CLOSING_SOON_WINDOW = timedelta(days=3)


@dataclass
class _Row:
    title: str
    canonical_url: str
    promoter: str
    prize_value_gbp: str
    closes_at: str | None
    source_count: int
    score: float
    closing_soon: bool


def _to_row(competition: Competition, now: datetime) -> _Row:
    closing_soon = bool(
        competition.closes_at and competition.closes_at - now <= CLOSING_SOON_WINDOW
    )
    return _Row(
        title=competition.title,
        canonical_url=competition.canonical_url,
        promoter=competition.promoter or "—",
        prize_value_gbp=f"£{competition.prize_value_gbp:,.0f}"
        if competition.prize_value_gbp is not None
        else "—",
        closes_at=competition.closes_at.date().isoformat() if competition.closes_at else None,
        source_count=competition.source_count,
        score=competition.score,
        closing_soon=closing_soon,
    )


def build(
    competitions: list[Competition],
    output_dir: str | Path,
    *,
    repeatables: tuple[int, int] = (0, 0),
) -> Path:
    """Render index.html into `output_dir`, ranked highest-score first."""
    now = datetime.now(UTC)
    ordered = sorted(competitions, key=lambda c: c.score, reverse=True)
    rows = [_to_row(c, now) for c in ordered]
    repeatables_done, repeatables_total = repeatables

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("index.html.j2").render(
        competitions=rows,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        repeatables_done=repeatables_done,
        repeatables_total=repeatables_total,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path

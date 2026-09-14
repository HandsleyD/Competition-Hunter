"""Static HTML dashboard — GitHub Pages, per design-options.md §9.

Phase 1: a single page, sorted by closing date, no filtering/scoring yet
(that lands with the enrich/score pipeline in phase 2).
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
    closes_at: str | None
    source_count: int
    closing_soon: bool


def _to_row(competition: Competition, now: datetime) -> _Row:
    closing_soon = bool(
        competition.closes_at and competition.closes_at - now <= CLOSING_SOON_WINDOW
    )
    return _Row(
        title=competition.title,
        canonical_url=competition.canonical_url,
        closes_at=competition.closes_at.date().isoformat() if competition.closes_at else None,
        source_count=competition.source_count,
        closing_soon=closing_soon,
    )


def build(competitions: list[Competition], output_dir: str | Path) -> Path:
    """Render index.html into `output_dir`, sorted open-ended-closing-date last."""
    now = datetime.now(UTC)
    ordered = sorted(competitions, key=lambda c: c.closes_at or datetime.max.replace(tzinfo=UTC))
    rows = [_to_row(c, now) for c in ordered]

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("index.html.j2").render(
        competitions=rows, generated_at=now.strftime("%Y-%m-%d %H:%M UTC")
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    return index_path

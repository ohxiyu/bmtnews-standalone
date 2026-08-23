"""Structured homepage overview shared by generation and rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverviewSignal:
    """One factual supporting signal linked to its ranked story."""

    label: str
    text: str
    item_rank: int


@dataclass(frozen=True)
class EditionOverview:
    """A daily throughline plus zero or more supporting signals.

    ``signals`` may be empty when a provider returns legacy prose or malformed
    structured output. The page can still show the headline instead of
    dropping the entire overview.
    """

    headline: str
    signals: tuple[OverviewSignal, ...] = ()

    def as_text(self) -> str:
        """Preserve the public API's existing string overview field."""
        parts = [self.headline]
        parts.extend(f"{signal.label}：{signal.text}" for signal in self.signals)
        return " ".join(parts)

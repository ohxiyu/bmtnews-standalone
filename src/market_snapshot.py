"""Key-less market snapshot for the daily edition header.

Fetches BTC/ETH spot prices with 24h change from CoinGecko and the
Fear & Greed index from alternative.me. Both endpoints are free and
key-less. Every failure is soft: the snapshot (or individual fields)
is simply omitted from the page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,ethereum&vs_currencies=usd&include_24hr_change=true"
)
_FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

_FEAR_GREED_ZH = {
    "extreme fear": "极度恐惧",
    "fear": "恐惧",
    "neutral": "中性",
    "greed": "贪婪",
    "extreme greed": "极度贪婪",
}


@dataclass(frozen=True)
class MarketSnapshot:
    """Point-in-time market context rendered at the top of an edition."""

    btc_price: float
    btc_change_24h: Optional[float]
    eth_price: float
    eth_change_24h: Optional[float]
    fear_greed_value: Optional[int] = None
    fear_greed_label: Optional[str] = None

    def fear_greed_label_for(self, language: str) -> Optional[str]:
        if self.fear_greed_label is None:
            return None
        if language == "zh":
            return _FEAR_GREED_ZH.get(
                self.fear_greed_label.lower(), self.fear_greed_label
            )
        return self.fear_greed_label


def _as_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def fetch_market_snapshot(
    client: httpx.AsyncClient | None = None,
    *,
    timeout: float = 10.0,
) -> Optional[MarketSnapshot]:
    """Fetch the snapshot; returns None when price data is unavailable."""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=timeout)
    assert client is not None
    try:
        response = await client.get(_COINGECKO_URL)
        response.raise_for_status()
        prices = response.json()
        btc = prices.get("bitcoin") or {}
        eth = prices.get("ethereum") or {}
        btc_price = _as_float(btc.get("usd"))
        eth_price = _as_float(eth.get("usd"))
        if btc_price is None or eth_price is None:
            return None

        fear_greed_value: Optional[int] = None
        fear_greed_label: Optional[str] = None
        try:
            fng_response = await client.get(_FEAR_GREED_URL)
            fng_response.raise_for_status()
            entries = (fng_response.json() or {}).get("data") or []
            if entries:
                raw_value = _as_float(entries[0].get("value"))
                if raw_value is not None:
                    fear_greed_value = int(raw_value)
                label = entries[0].get("value_classification")
                if label:
                    fear_greed_label = str(label)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Fear & Greed index unavailable: %s", exc)

        return MarketSnapshot(
            btc_price=btc_price,
            btc_change_24h=_as_float(btc.get("usd_24h_change")),
            eth_price=eth_price,
            eth_change_24h=_as_float(eth.get("usd_24h_change")),
            fear_greed_value=fear_greed_value,
            fear_greed_label=fear_greed_label,
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Market snapshot unavailable: %s", exc)
        return None
    finally:
        if owns_client:
            await client.aclose()

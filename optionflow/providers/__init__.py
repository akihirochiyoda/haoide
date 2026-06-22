"""オプションデータ取得プロバイダ。

無料の yfinance を既定とし、UNUSUAL_WHALES_API_KEY があれば本物の約定フローに
切り替えるプラガブル設計。
"""

from __future__ import annotations

import os

from .base import OptionContract, OptionsProvider, TickerSnapshot


def get_provider(name: str = "auto"):
    """設定名から適切なプロバイダを返す。

    "auto" の場合、UNUSUAL_WHALES_API_KEY があれば有料フロー、無ければ yfinance。
    """
    name = (name or "auto").lower()

    if name == "auto":
        if os.environ.get("UNUSUAL_WHALES_API_KEY"):
            name = "unusual_whales"
        else:
            name = "yfinance"

    if name == "yfinance":
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    if name == "unusual_whales":
        from .unusual_whales_provider import UnusualWhalesProvider

        return UnusualWhalesProvider()

    raise ValueError(f"unknown provider: {name}")


__all__ = [
    "OptionContract",
    "OptionsProvider",
    "TickerSnapshot",
    "get_provider",
]

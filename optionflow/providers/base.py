"""プロバイダ共通のデータ構造とインターフェース。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class OptionContract:
    """正規化されたオプション契約 1 行分。"""

    ticker: str
    expiry: str  # "YYYY-MM-DD"
    strike: float
    option_type: str  # "call" | "put"
    last_price: float
    volume: int
    open_interest: int
    implied_volatility: float
    in_the_money: bool
    underlying_price: float
    bid: float = 0.0
    ask: float = 0.0
    # 約定フローAPIが提供する場合のみ。無料チェーンでは None。
    # "buy"(ask側で約定=買い) | "sell"(bid側で約定=売り)
    side: Optional[str] = None
    # プロバイダが想定プレミアムを直接提供する場合。無ければ analyzer が推定。
    premium_usd: Optional[float] = None

    @property
    def estimated_premium_usd(self) -> float:
        """想定プレミアム(ドル)。1契約=100株。"""
        if self.premium_usd is not None:
            return self.premium_usd
        return float(self.volume) * float(self.last_price) * 100.0

    @property
    def vol_oi_ratio(self) -> float:
        return float(self.volume) / max(float(self.open_interest), 1.0)


@dataclass
class TickerSnapshot:
    """1 銘柄のスナップショット。"""

    ticker: str
    underlying_price: float
    contracts: list[OptionContract] = field(default_factory=list)
    error: Optional[str] = None


class OptionsProvider:
    """オプションデータ取得の抽象基底クラス。"""

    #: side(買い/売り)を提供できる本物のフローか
    provides_flow_side: bool = False
    name: str = "base"

    def fetch(self, ticker: str, expiries_to_scan: int = 3) -> TickerSnapshot:
        raise NotImplementedError

    def fetch_many(
        self, tickers: Iterable[str], expiries_to_scan: int = 3
    ) -> list[TickerSnapshot]:
        results: list[TickerSnapshot] = []
        for t in tickers:
            try:
                results.append(self.fetch(t, expiries_to_scan=expiries_to_scan))
            except Exception as exc:  # 1 銘柄の失敗で全体を止めない
                results.append(TickerSnapshot(ticker=t, underlying_price=0.0, error=str(exc)))
        return results

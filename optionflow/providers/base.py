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
        """想定金額(ドル)。1契約=100株。

        優先順:
          1) 直接与えられた premium_usd
          2) 1株あたり価格 × 出来高 × 100 (= 実プレミアム)
          3) 価格情報が無い場合のみ、行使額(notional)= 行使価格 × 出来高 × 100
        3) は実際に支払われたプレミアムではない点に注意(premium_is_notional 参照)。
        """
        if self.premium_usd is not None:
            return float(self.premium_usd)
        if self.last_price > 0:
            return float(self.volume) * float(self.last_price) * 100.0
        # 価格情報なし: 行使額(notional)で代替(実プレミアムではない)
        return float(self.volume) * float(self.strike) * 100.0

    @property
    def premium_is_notional(self) -> bool:
        """estimated_premium_usd が実プレミアムではなく行使額(notional)か。

        - 1株あたり価格があれば実プレミアム → False
        - 価格もプレミアムも無ければ notional フォールバック → True
        - premium が与えられていても、1株単価が行使価格にほぼ等しい場合は
          行使額(strike×size×100)を誤って premium 欄に入れた可能性が高く True とみなす
        """
        if self.last_price > 0:
            return False
        if self.premium_usd is None:
            return True
        denom = max(float(self.volume) * 100.0, 1.0)
        per_share = float(self.premium_usd) / denom
        return self.strike > 0 and abs(per_share - self.strike) / self.strike < 0.02

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

    def available_tickers(self) -> Optional[list[str]]:
        """データ側が銘柄一覧を持つ場合に返す(例: InfoLib のフローファイル)。

        None の場合は呼び出し側の watchlist を使う。
        """
        return None

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

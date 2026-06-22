"""Unusual Whales API から本物のオプションフロー(約定単位)を取得する。

UNUSUAL_WHALES_API_KEY が設定されている場合に使用。約定の買い/売りの別(side)が
取れるため、analyzer はヒューリスティックではなく実データで方向性を判定できる。

エンドポイントのスキーマは契約プランにより異なる場合があるため、レスポンス項目は
寛容にパースする。差異があれば _map_record を調整すること。
"""

from __future__ import annotations

import os
from collections import defaultdict

from .base import OptionContract, OptionsProvider, TickerSnapshot

API_BASE = os.environ.get("UNUSUAL_WHALES_BASE_URL", "https://api.unusualwhales.com")


class UnusualWhalesProvider(OptionsProvider):
    provides_flow_side = True
    name = "unusual_whales"

    def __init__(self):
        self.api_key = os.environ.get("UNUSUAL_WHALES_API_KEY")
        if not self.api_key:
            raise RuntimeError("UNUSUAL_WHALES_API_KEY が設定されていません")
        try:
            import requests  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError("requests が必要です (pip install requests)") from exc

    def fetch(self, ticker: str, expiries_to_scan: int = 3) -> TickerSnapshot:
        import requests

        url = f"{API_BASE}/api/stock/{ticker}/option-trades"
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, params={"limit": 500}, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            return TickerSnapshot(ticker=ticker, underlying_price=0.0, error=str(exc))

        records = payload.get("data", payload if isinstance(payload, list) else [])
        contracts = [self._map_record(ticker, rec) for rec in records]
        contracts = [c for c in contracts if c is not None]

        # 約定をストライク×種別×限月で集約してチェーン相当に丸める
        aggregated = self._aggregate(ticker, contracts)
        spot = contracts[0].underlying_price if contracts else 0.0
        snapshot = TickerSnapshot(ticker=ticker, underlying_price=spot, contracts=aggregated)
        if not aggregated:
            snapshot.error = "フローデータが空でした"
        return snapshot

    @staticmethod
    def _map_record(ticker, rec) -> OptionContract | None:
        try:
            strike = float(rec.get("strike", 0) or 0)
            if strike <= 0:
                return None
            option_type = "call" if str(rec.get("type", rec.get("option_type", ""))).lower().startswith("c") else "put"
            spot = float(rec.get("underlying_price", rec.get("stock_price", 0)) or 0)
            price = float(rec.get("price", 0) or 0)
            size = int(float(rec.get("size", rec.get("volume", 0)) or 0))
            premium = rec.get("premium")
            side = rec.get("side")  # "buy" / "sell" / "ask" / "bid"
            if side in ("ask", "buy", "A"):
                side = "buy"
            elif side in ("bid", "sell", "B"):
                side = "sell"
            else:
                side = None
            in_the_money = strike < spot if option_type == "call" else strike > spot
            return OptionContract(
                ticker=ticker,
                expiry=str(rec.get("expiry", rec.get("expiration", ""))),
                strike=strike,
                option_type=option_type,
                last_price=price,
                volume=size,
                open_interest=int(float(rec.get("open_interest", 0) or 0)),
                implied_volatility=float(rec.get("implied_volatility", rec.get("iv", 0)) or 0),
                in_the_money=in_the_money,
                underlying_price=spot,
                side=side,
                premium_usd=float(premium) if premium is not None else None,
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _aggregate(ticker, contracts) -> list[OptionContract]:
        """同一(限月・ストライク・種別・side)の約定を 1 行に集約する。"""
        groups: dict[tuple, list[OptionContract]] = defaultdict(list)
        for c in contracts:
            groups[(c.expiry, c.strike, c.option_type, c.side)].append(c)

        out: list[OptionContract] = []
        for (expiry, strike, otype, side), items in groups.items():
            total_size = sum(i.volume for i in items)
            total_premium = sum(i.estimated_premium_usd for i in items)
            ref = items[0]
            out.append(
                OptionContract(
                    ticker=ticker,
                    expiry=expiry,
                    strike=strike,
                    option_type=otype,
                    last_price=ref.last_price,
                    volume=total_size,
                    open_interest=ref.open_interest,
                    implied_volatility=ref.implied_volatility,
                    in_the_money=ref.in_the_money,
                    underlying_price=ref.underlying_price,
                    side=side,
                    premium_usd=total_premium,
                )
            )
        return out

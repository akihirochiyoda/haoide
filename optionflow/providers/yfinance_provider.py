"""無料の Yahoo Finance(yfinance)からオプションチェーンを取得する。

注意: 無料チェーンは「出来高・建玉・IV」のスナップショットであり、本物の約定フロー
(買い/売りの別)は含まない。よって side は None で返し、analyzer 側でポジショニング
ヒューリスティック(出来高>建玉=新規ポジション)から方向性を推定する。
"""

from __future__ import annotations

import math

from .base import OptionContract, OptionsProvider, TickerSnapshot


def _num(value, default=0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f):
        return default
    return f


class YFinanceProvider(OptionsProvider):
    provides_flow_side = False
    name = "yfinance"

    def __init__(self):
        try:
            import yfinance  # noqa: F401
        except ImportError as exc:  # pragma: no cover - 実行環境依存
            raise ImportError(
                "yfinance が必要です。`pip install -r optionflow/requirements.txt` を実行してください。"
            ) from exc

    def fetch(self, ticker: str, expiries_to_scan: int = 3) -> TickerSnapshot:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        spot = self._spot_price(tk)

        snapshot = TickerSnapshot(ticker=ticker, underlying_price=spot)
        if spot <= 0:
            snapshot.error = "原資産価格を取得できませんでした"
            return snapshot

        expiries = list(getattr(tk, "options", []) or [])[:expiries_to_scan]
        for expiry in expiries:
            try:
                chain = tk.option_chain(expiry)
            except Exception:
                continue
            snapshot.contracts.extend(self._rows(ticker, expiry, "call", chain.calls, spot))
            snapshot.contracts.extend(self._rows(ticker, expiry, "put", chain.puts, spot))

        if not snapshot.contracts:
            snapshot.error = "オプションチェーンを取得できませんでした"
        return snapshot

    @staticmethod
    def _spot_price(tk) -> float:
        # fast_info が最も軽量。失敗したら直近終値にフォールバック。
        try:
            price = _num(tk.fast_info.get("lastPrice"))
            if price > 0:
                return price
        except Exception:
            pass
        try:
            hist = tk.history(period="1d")
            if not hist.empty:
                return _num(hist["Close"].iloc[-1])
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _rows(ticker, expiry, option_type, df, spot) -> list[OptionContract]:
        rows: list[OptionContract] = []
        if df is None or df.empty:
            return rows
        for r in df.itertuples(index=False):
            strike = _num(getattr(r, "strike", 0))
            if strike <= 0:
                continue
            in_the_money = strike < spot if option_type == "call" else strike > spot
            rows.append(
                OptionContract(
                    ticker=ticker,
                    expiry=str(expiry),
                    strike=strike,
                    option_type=option_type,
                    last_price=_num(getattr(r, "lastPrice", 0)),
                    bid=_num(getattr(r, "bid", 0)),
                    ask=_num(getattr(r, "ask", 0)),
                    volume=int(_num(getattr(r, "volume", 0))),
                    open_interest=int(_num(getattr(r, "openInterest", 0))),
                    implied_volatility=_num(getattr(r, "impliedVolatility", 0)),
                    in_the_money=bool(getattr(r, "inTheMoney", in_the_money)),
                    underlying_price=spot,
                    side=None,
                )
            )
        return rows

"""InfoLib(infolib.org)の Unusual Options Flow を取り込むプロバイダ。

InfoLib は公式APIを公開していないため、本プロバイダは「ブラウザで読み取った
フローデータをローカルの JSON ファイルに保存しておき、それを取り込む」方式を採る。

想定運用(Claude コワーク):
  1. ブラウザ操作できる Claude セッションが
     https://infolib.org/market-dashboard/unusual-options-flow を開く
  2. テーブルの各プリントを下記スキーマの JSON 配列として
     data/infolib_flow.json に保存する(INFOLIB_COWORK.md 参照)
  3. `python -m optionflow.run --provider infolib` で分析

入力 JSON スキーマ(1 件 = 1 プリント):
  {
    "ticker": "NVDA",
    "type": "call",                 # call | put  (C/P も可)
    "strike": 132.0,
    "expiry": "2026-07-17",
    "spot": 130.5,                  # 任意(原資産価格)
    "size": 5000,                   # 出来高/約定サイズ
    "open_interest": 1200,          # 任意
    "price": 5.1,                   # 任意(1株あたり)
    "premium": 2550000,             # 任意(想定プレミアム$)。無ければ size*price*100
    "iv": 0.55,                     # 任意
    "side": "ask",                  # 任意 ask/bid/buy/sell
    "sentiment": "bullish"          # 任意 bullish/bearish (side が無い時に使用)
  }
ファイルは上記の配列、または {"data": [...]} / {"flow": [...]} を許容。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from .base import OptionContract, OptionsProvider, TickerSnapshot

DEFAULT_FLOW_FILE = os.environ.get("INFOLIB_FLOW_FILE", "data/infolib_flow.json")


def _effective_side(option_type: str, side, sentiment) -> str | None:
    """side(ask/bid/buy/sell) か sentiment(bullish/bearish) から
    analyzer が期待する "buy"/"sell" を導く。

    analyzer の方向定義:
      call+buy → 強気 / put+sell → 強気 / call+sell → 弱気 / put+buy → 弱気
    """
    if side:
        s = str(side).lower()
        if s in ("ask", "a", "buy"):
            return "buy"
        if s in ("bid", "b", "sell"):
            return "sell"

    if sentiment:
        bull = str(sentiment).lower().startswith("bull")
        if option_type == "call":
            return "buy" if bull else "sell"
        return "sell" if bull else "buy"

    return None


class InfoLibProvider(OptionsProvider):
    # InfoLib は sentiment/side を持つため本物のフロー扱い
    provides_flow_side = True
    name = "infolib"

    def __init__(self, flow_file: str | os.PathLike[str] | None = None):
        self.flow_file = Path(flow_file or DEFAULT_FLOW_FILE)
        self._by_ticker: dict[str, list[OptionContract]] | None = None

    def _load(self) -> dict[str, list[OptionContract]]:
        if self._by_ticker is not None:
            return self._by_ticker

        if not self.flow_file.exists():
            raise FileNotFoundError(
                f"InfoLib フローファイルが見つかりません: {self.flow_file}\n"
                "ブラウザ(Claude コワーク)で取得し保存してください。手順は "
                "optionflow/INFOLIB_COWORK.md を参照。"
            )

        raw = json.loads(self.flow_file.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            rows = raw.get("data") or raw.get("flow") or raw.get("rows") or []
        else:
            rows = raw

        by_ticker: dict[str, list[OptionContract]] = defaultdict(list)
        for rec in rows:
            contract = self._map(rec)
            if contract is not None:
                by_ticker[contract.ticker].append(contract)

        self._by_ticker = by_ticker
        return by_ticker

    @staticmethod
    def _map(rec) -> OptionContract | None:
        try:
            ticker = str(rec.get("ticker", rec.get("symbol", ""))).upper().strip()
            if not ticker:
                return None
            raw_type = str(rec.get("type", rec.get("option_type", ""))).lower()
            option_type = "call" if raw_type.startswith("c") else "put"
            strike = float(rec.get("strike", 0) or 0)
            if strike <= 0:
                return None
            spot = float(rec.get("spot", rec.get("underlying_price", 0)) or 0)
            price = float(rec.get("price", 0) or 0)
            size = int(float(rec.get("size", rec.get("volume", 0)) or 0))
            premium = rec.get("premium")
            side = _effective_side(option_type, rec.get("side"), rec.get("sentiment"))
            in_the_money = strike < spot if option_type == "call" else strike > spot
            return OptionContract(
                ticker=ticker,
                expiry=str(rec.get("expiry", rec.get("expiration", ""))),
                strike=strike,
                option_type=option_type,
                last_price=price,
                volume=size,
                open_interest=int(float(rec.get("open_interest", rec.get("oi", 0)) or 0)),
                implied_volatility=float(rec.get("iv", rec.get("implied_volatility", 0)) or 0),
                in_the_money=in_the_money,
                underlying_price=spot,
                side=side,
                premium_usd=float(premium) if premium is not None else None,
            )
        except (TypeError, ValueError):
            return None

    def available_tickers(self) -> list[str] | None:
        return sorted(self._load().keys()) or None

    def fetch(self, ticker: str, expiries_to_scan: int = 3) -> TickerSnapshot:
        by_ticker = self._load()
        contracts = by_ticker.get(ticker.upper(), [])
        spot = 0.0
        for c in contracts:
            if c.underlying_price > 0:
                spot = c.underlying_price
                break
        snapshot = TickerSnapshot(ticker=ticker.upper(), underlying_price=spot, contracts=contracts)
        if not contracts:
            snapshot.error = "このティッカーのフローデータがファイルにありません"
        return snapshot

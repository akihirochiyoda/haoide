"""合成データによる analyzer の検証(ネット不要)。

    python -m optionflow.tests.test_analyzer
"""

from __future__ import annotations

from ..analyzer import analyze
from ..claude_review import generate_review
from ..config import ClaudeConfig, Thresholds
from ..providers.base import OptionContract, TickerSnapshot
from ..report import build_markdown


def _contract(ticker, otype, strike, spot, volume, oi, price, side=None):
    in_the_money = strike < spot if otype == "call" else strike > spot
    return OptionContract(
        ticker=ticker,
        expiry="2026-07-17",
        strike=strike,
        option_type=otype,
        last_price=price,
        volume=volume,
        open_interest=oi,
        implied_volatility=0.55,
        in_the_money=in_the_money,
        underlying_price=spot,
        side=side,
    )


def _bullish_snapshot():
    spot = 130.0
    return TickerSnapshot(
        ticker="NVDA",
        underlying_price=spot,
        contracts=[
            # 大口のコール買い相当(新規ポジション): premium = 5000*5*100 = 2.5M
            _contract("NVDA", "call", 132, spot, volume=5000, oi=1000, price=5.0),
            _contract("NVDA", "call", 128, spot, volume=3000, oi=500, price=6.0),  # ITM ATM付近
            # 小口プット(閾値未満)
            _contract("NVDA", "put", 125, spot, volume=100, oi=8000, price=2.0),
        ],
    )


def _bearish_snapshot():
    spot = 50.0
    return TickerSnapshot(
        ticker="AMD",
        underlying_price=spot,
        contracts=[
            # 大口のプット買い相当: premium = 8000*3*100 = 2.4M
            _contract("AMD", "put", 49, spot, volume=8000, oi=1000, price=3.0),
            _contract("AMD", "put", 48, spot, volume=4000, oi=500, price=2.5),
        ],
    )


def _flow_snapshot():
    """本物フロー(side あり): PUT売り=強気 を検証。"""
    spot = 200.0
    return TickerSnapshot(
        ticker="MSFT",
        underlying_price=spot,
        contracts=[
            # PUT売り(強気) premium 大
            _contract("MSFT", "put", 195, spot, volume=6000, oi=1000, price=4.0, side="sell"),
        ],
    )


def main() -> int:
    th = Thresholds()

    daily = analyze(
        [_bullish_snapshot(), _bearish_snapshot()],
        thresholds=th,
        provider_name="synthetic",
        flow_based=False,
        generated_at="2026-06-22 00:00 UTC",
    )

    by_ticker = {t.ticker: t for t in daily.tickers}
    assert by_ticker["NVDA"].classification == "上昇期待", by_ticker["NVDA"].classification
    assert by_ticker["AMD"].classification == "下落期待", by_ticker["AMD"].classification
    assert by_ticker["NVDA"].itm_call_strikes == [128.0], by_ticker["NVDA"].itm_call_strikes
    ranked = daily.ranked()
    assert len(ranked) == 2
    print("[OK] チェーン推定: 上昇/下落の分類が正しい")

    # 本物フロー: PUT売り → 強気
    flow_daily = analyze(
        [_flow_snapshot()],
        thresholds=th,
        provider_name="synthetic_flow",
        flow_based=True,
        generated_at="2026-06-22 00:00 UTC",
    )
    msft = flow_daily.tickers[0]
    assert msft.classification == "上昇期待", msft.classification
    assert msft.notable_trades[0].direction == "bullish"
    print("[OK] 本物フロー: PUT売り→強気 判定が正しい")

    # クロード監修(キー無し → フォールバック)とレポート生成が例外なく動く
    review = generate_review(daily, ClaudeConfig(enabled=True, api_key=None))
    assert "投資助言ではありません" in review
    md = build_markdown(daily, claude_review=review)
    assert "ツンデレ姫のオプション分析" in md
    assert "NVDA" in md
    print("[OK] フォールバック監修とレポート生成が動作")

    print("\nすべてのテストに合格しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

    # 縦スプレッド: プット買い(高ストライク)+プット売り(低ストライク)=ベアプット
    # → 売りレッグで符号反転せず「下落期待」になること
    spread_snap = TickerSnapshot(
        ticker="IWM",
        underlying_price=290.0,
        contracts=[
            _contract("IWM", "put", 281, 290.0, volume=6500, oi=393, price=28.0, side="buy"),
            _contract("IWM", "put", 279, 290.0, volume=6500, oi=543, price=27.0, side="sell"),
        ],
    )
    spread_daily = analyze(
        [spread_snap], thresholds=th, provider_name="synthetic_flow",
        flow_based=True, generated_at="2026-06-22 00:00 UTC",
    )
    iwm = spread_daily.tickers[0]
    assert iwm.has_spread, "縦スプレッドが検出されていない"
    assert iwm.classification == "下落期待", iwm.classification
    assert all(tr.direction == "bearish" for tr in iwm.notable_trades), "脚の方向が構造に揃っていない"
    print("[OK] 縦スプレッド: ベアプットを下落期待と判定(符号反転しない)")

    # クロード監修(キー無し → フォールバック)とレポート生成が例外なく動く
    review = generate_review(daily, ClaudeConfig(enabled=True, api_key=None))
    assert "投資助言ではありません" in review
    md = build_markdown(daily, claude_review=review)
    assert "ツンデレ姫のオプション分析" in md
    assert "NVDA" in md
    print("[OK] フォールバック監修とレポート生成が動作")

    _test_infolib_provider(th)

    print("\nすべてのテストに合格しました。")
    return 0


def _test_infolib_provider(th):
    """InfoLib プロバイダ: sample ファイルを読み、方向判定が正しいか。"""
    from pathlib import Path

    from ..providers.infolib_provider import InfoLibProvider

    sample = Path(__file__).resolve().parents[2] / "data" / "infolib_flow.sample.json"
    if not sample.exists():
        print("[SKIP] InfoLib sample ファイルが無いためスキップ")
        return

    provider = InfoLibProvider(flow_file=sample)
    tickers = provider.available_tickers()
    assert tickers and "NVDA" in tickers and "AMD" in tickers, tickers

    snaps = provider.fetch_many(tickers)
    daily = analyze(
        snaps, thresholds=th, provider_name="infolib",
        flow_based=provider.provides_flow_side, generated_at="2026-06-22 00:00 UTC",
    )
    bt = {t.ticker: t for t in daily.tickers}
    # NVDA: call+bullish → 強気
    assert bt["NVDA"].classification == "上昇期待", bt["NVDA"].classification
    # AMD: put+bearish → 弱気
    assert bt["AMD"].classification == "下落期待", bt["AMD"].classification
    # TSLA: put + sentiment=bullish(=PUT売り) → 強気
    assert bt["TSLA"].classification == "上昇期待", bt["TSLA"].classification
    print("[OK] InfoLib: side/sentiment からの方向判定が正しい(PUT売り→強気 含む)")


if __name__ == "__main__":
    raise SystemExit(main())

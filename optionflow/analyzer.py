"""分析エンジン — 画像「ツンデレ姫のオプション分析」フローの再実装。

リバースエンジニアしたフロー:
  1) どんな分析か: 監視銘柄のオプションフローから大口(機関投資家)の動きを読む
  2) まず注目: ITM PUT / ITM CALL の注目価格帯(ATM付近)をチェック
  3) 大きな取引を見つける: 出来高・プレミアム・サイズで異常な大口取引を抽出
  4) 方向性の判定: PUT買い/PUT売り/CALL買い/CALL売り を区別(side or ヒューリスティック)
  5) 2タイプに分類: 上昇期待 / 下落期待
  6) まとめ: 大口の方向性が見えた銘柄に注目
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from .config import Thresholds
from .providers.base import OptionContract, TickerSnapshot


@dataclass
class NotableTrade:
    """ステップ3で抽出した「大きな取引」。"""

    expiry: str
    strike: float
    option_type: str  # "call" | "put"
    volume: int
    open_interest: int
    vol_oi_ratio: float
    premium_usd: float
    implied_volatility: float
    in_the_money: bool
    moneyness_pct: float  # (strike-spot)/spot
    new_positioning: bool  # volume > open_interest
    side: Optional[str]  # "buy"/"sell"/None
    # ステップ4: この取引が示す方向("bullish"/"bearish")
    direction: str
    directional_premium_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TickerAnalysis:
    """1 銘柄の分析結果。"""

    ticker: str
    underlying_price: float
    call_premium_usd: float = 0.0
    put_premium_usd: float = 0.0
    put_call_ratio: float = 0.0
    bullish_score_usd: float = 0.0  # 正=強気 / 負=弱気
    classification: str = "中立"  # "上昇期待" / "下落期待" / "中立"
    conviction_usd: float = 0.0  # 方向性の確信度(スコア絶対値)
    notable_trades: list[NotableTrade] = field(default_factory=list)
    itm_call_strikes: list[float] = field(default_factory=list)
    itm_put_strikes: list[float] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notable_trades"] = [t.to_dict() for t in self.notable_trades]
        return d


@dataclass
class DailyAnalysis:
    """全監視銘柄の分析結果(レポートの元データ)。"""

    generated_at: str
    provider: str
    flow_based: bool  # True=本物の約定フロー / False=チェーン推定
    tickers: list[TickerAnalysis] = field(default_factory=list)

    def ranked(self) -> list[TickerAnalysis]:
        """方向性が見えた順(確信度の高い順)に並べる。"""
        clear = [t for t in self.tickers if t.classification != "中立" and not t.error]
        return sorted(clear, key=lambda t: t.conviction_usd, reverse=True)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "provider": self.provider,
            "flow_based": self.flow_based,
            "tickers": [t.to_dict() for t in self.tickers],
        }


def _direction_of(contract: OptionContract, flow_based: bool) -> tuple[str, float]:
    """ステップ4: 1 契約の方向と「方向性プレミアム」を返す。

    本物のフロー(side あり):
        CALL買い / PUT売り → 強気 (+)
        CALL売り / PUT買い → 弱気 (-)
    チェーン推定(side なし):
        新規ポジション(出来高>建玉)を「その種別の買い」とみなす単純化:
        CALL → 強気 / PUT → 弱気
    """
    premium = contract.estimated_premium_usd

    if flow_based and contract.side in ("buy", "sell"):
        bullish = (
            (contract.option_type == "call" and contract.side == "buy")
            or (contract.option_type == "put" and contract.side == "sell")
        )
        direction = "bullish" if bullish else "bearish"
        return direction, premium if bullish else -premium

    # ヒューリスティック: コール=強気、プット=弱気
    if contract.option_type == "call":
        return "bullish", premium
    return "bearish", -premium


def analyze_ticker(
    snapshot: TickerSnapshot, thresholds: Thresholds, flow_based: bool
) -> TickerAnalysis:
    analysis = TickerAnalysis(
        ticker=snapshot.ticker,
        underlying_price=snapshot.underlying_price,
        error=snapshot.error,
    )
    if snapshot.error or not snapshot.contracts:
        return analysis

    spot = snapshot.underlying_price
    near = thresholds.itm_near_the_money_pct

    for c in snapshot.contracts:
        # ステップ2: ITM かつ ATM付近の注目価格帯を記録
        moneyness = (c.strike - spot) / spot if spot else 0.0
        if c.in_the_money and abs(moneyness) <= near:
            if c.option_type == "call":
                analysis.itm_call_strikes.append(c.strike)
            else:
                analysis.itm_put_strikes.append(c.strike)

        # コール/プットの総プレミアム(put/call ratio 用)
        if c.option_type == "call":
            analysis.call_premium_usd += c.estimated_premium_usd
        else:
            analysis.put_premium_usd += c.estimated_premium_usd

        # ステップ3: 大きな取引の抽出
        is_big = (
            c.volume >= thresholds.min_volume
            and c.estimated_premium_usd >= thresholds.min_premium_usd
        )
        new_positioning = c.vol_oi_ratio >= thresholds.vol_oi_ratio
        if not is_big:
            continue

        direction, dir_premium = _direction_of(c, flow_based)
        # 新規ポジションは方向性への寄与を重み付け
        weight = thresholds.new_positioning_weight if new_positioning else 1.0
        dir_premium *= weight
        analysis.bullish_score_usd += dir_premium

        analysis.notable_trades.append(
            NotableTrade(
                expiry=c.expiry,
                strike=c.strike,
                option_type=c.option_type,
                volume=c.volume,
                open_interest=c.open_interest,
                vol_oi_ratio=round(c.vol_oi_ratio, 2),
                premium_usd=round(c.estimated_premium_usd, 0),
                implied_volatility=round(c.implied_volatility, 4),
                in_the_money=c.in_the_money,
                moneyness_pct=round(moneyness * 100, 2),
                new_positioning=new_positioning,
                side=c.side,
                direction=direction,
                directional_premium_usd=round(dir_premium, 0),
            )
        )

    # put/call レシオ(プレミアムベース)
    if analysis.call_premium_usd > 0:
        analysis.put_call_ratio = round(analysis.put_premium_usd / analysis.call_premium_usd, 2)

    # ステップ5: 上昇期待 / 下落期待 への分類
    analysis.conviction_usd = round(abs(analysis.bullish_score_usd), 0)
    if analysis.bullish_score_usd >= thresholds.sentiment_strong_usd:
        analysis.classification = "上昇期待"
    elif analysis.bullish_score_usd <= -thresholds.sentiment_strong_usd:
        analysis.classification = "下落期待"
    else:
        analysis.classification = "中立"

    # 注目取引はプレミアムの大きい順に
    analysis.notable_trades.sort(key=lambda t: t.premium_usd, reverse=True)
    analysis.itm_call_strikes = sorted(set(analysis.itm_call_strikes))
    analysis.itm_put_strikes = sorted(set(analysis.itm_put_strikes))
    return analysis


def analyze(
    snapshots: list[TickerSnapshot],
    thresholds: Thresholds,
    provider_name: str,
    flow_based: bool,
    generated_at: str,
) -> DailyAnalysis:
    daily = DailyAnalysis(
        generated_at=generated_at,
        provider=provider_name,
        flow_based=flow_based,
    )
    for snap in snapshots:
        daily.tickers.append(analyze_ticker(snap, thresholds, flow_based))
    return daily

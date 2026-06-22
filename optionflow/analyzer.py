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
from datetime import date
from typing import Optional

from .config import Thresholds
from .providers.base import OptionContract, TickerSnapshot


def _parse_iso_date(s: str) -> Optional[date]:
    """'YYYY-MM-DD' を date に。失敗時 None。"""
    try:
        parts = str(s).split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, TypeError):
        return None


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
    # premium_usd が実プレミアムでなく行使額(notional)か
    premium_is_notional: bool = False
    # 縦スプレッド(買い+売り)の一部と推定されるか
    part_of_spread: bool = False

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
    conviction_usd: float = 0.0  # 方向性スコアの絶対値(=規模)
    notable_trades: list[NotableTrade] = field(default_factory=list)
    itm_call_strikes: list[float] = field(default_factory=list)
    itm_put_strikes: list[float] = field(default_factory=list)
    # この銘柄の金額が実プレミアムでなく行使額(notional)ベースか
    premium_basis_notional: bool = False
    # 原資産価格が無く ITM/OTM 判定ができなかったか
    moneyness_unknown: bool = False
    # 期限切れのため除外した約定数
    expired_skipped: int = 0
    # 縦スプレッド構造を検出したか(方向ラベルを構造ベースに補正)
    has_spread: bool = False
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
        """方向性が見えた順(規模の大きい順)に並べる。"""
        clear = [t for t in self.tickers if t.classification != "中立" and not t.error]
        return sorted(clear, key=lambda t: t.conviction_usd, reverse=True)

    @property
    def premium_basis_notional(self) -> bool:
        """1銘柄でも金額が行使額(notional)ベースなら True(レポートの表記切替に使用)。"""
        return any(t.premium_basis_notional for t in self.tickers)

    @property
    def total_expired_skipped(self) -> int:
        return sum(t.expired_skipped for t in self.tickers)

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


def _detect_vertical_spreads(big: list[dict], flow_based: bool):
    """縦スプレッド(同一種別・同一限月で「買い」と「売り」が異なる行使価格に混在)を検出。

    返り値:
      group_of:      big のindex -> グループキー
      group_dir:     グループキー -> 構造の方向("bullish"/"bearish")
      group_members: グループキー -> index リスト

    縦スプレッドの方向は「買い建て」レッグで決まる(例: プット買い+プット売り=
    ベア・プット・スプレッド=弱気)。これにより、売りレッグを独立した逆方向
    シグナルとして数えてネットの符号が反転する誤判定を防ぐ。side が無い
    (チェーン推定)場合は検出しない。
    """
    from collections import defaultdict

    if not flow_based:
        return {}, {}, {}

    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, item in enumerate(big):
        c = item["contract"]
        if c.side in ("buy", "sell"):
            buckets[(c.option_type, c.expiry)].append(i)

    group_of: dict[int, tuple] = {}
    group_dir: dict[tuple, str] = {}
    group_members: dict[tuple, list[int]] = {}
    for key, idxs in buckets.items():
        sides = {big[i]["contract"].side for i in idxs}
        strikes = {big[i]["contract"].strike for i in idxs}
        if "buy" in sides and "sell" in sides and len(strikes) > 1:
            buy_idxs = [i for i in idxs if big[i]["contract"].side == "buy"]
            rep = max(buy_idxs, key=lambda i: big[i]["contract"].estimated_premium_usd)
            otype = big[rep]["contract"].option_type
            group_dir[key] = "bullish" if otype == "call" else "bearish"
            group_members[key] = idxs
            for i in idxs:
                group_of[i] = key
    return group_of, group_dir, group_members


def analyze_ticker(
    snapshot: TickerSnapshot,
    thresholds: Thresholds,
    flow_based: bool,
    as_of: Optional[date] = None,
) -> TickerAnalysis:
    analysis = TickerAnalysis(
        ticker=snapshot.ticker,
        underlying_price=snapshot.underlying_price,
        error=snapshot.error,
    )
    if snapshot.error or not snapshot.contracts:
        return analysis

    spot = snapshot.underlying_price
    analysis.moneyness_unknown = spot <= 0
    near = thresholds.itm_near_the_money_pct

    # --- パス1: 集計と「大口取引」の収集 ---
    big: list[dict] = []
    for c in snapshot.contracts:
        # 期限切れの約定は除外(レポート日より前の限月)
        if as_of is not None:
            exp = _parse_iso_date(c.expiry)
            if exp is not None and exp < as_of:
                analysis.expired_skipped += 1
                continue

        # ステップ2: ITM かつ ATM付近の注目価格帯を記録(spot 不明時はスキップ)
        moneyness = (c.strike - spot) / spot if spot else 0.0
        if spot > 0 and c.in_the_money and abs(moneyness) <= near:
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
        if not is_big:
            continue
        big.append(
            {
                "contract": c,
                "moneyness": moneyness,
                "new_positioning": c.vol_oi_ratio >= thresholds.vol_oi_ratio,
            }
        )

    # --- 縦スプレッド検出(売りレッグでの符号反転を防ぐ) ---
    group_of, group_dir, group_members = _detect_vertical_spreads(big, flow_based)
    analysis.has_spread = bool(group_of)
    counted_groups: set = set()

    # --- パス2: 方向性スコアと注目取引の構築 ---
    for i, item in enumerate(big):
        c = item["contract"]
        moneyness = item["moneyness"]
        new_positioning = item["new_positioning"]
        weight = thresholds.new_positioning_weight if new_positioning else 1.0

        if i in group_of:
            # スプレッドの一部: 方向は構造(買い建てレッグ)に合わせ、
            # スコアへの寄与はグループで1回だけ(最大レッグの規模)に集約。
            key = group_of[i]
            direction = group_dir[key]
            part_of_spread = True
            if key not in counted_groups:
                counted_groups.add(key)
                mag = max(
                    big[j]["contract"].estimated_premium_usd for j in group_members[key]
                )
                signed = mag if direction == "bullish" else -mag
                contribution = signed * weight
                analysis.bullish_score_usd += contribution
                dir_premium = contribution
            else:
                dir_premium = 0.0
        else:
            direction, dir_premium = _direction_of(c, flow_based)
            dir_premium *= weight
            analysis.bullish_score_usd += dir_premium
            part_of_spread = False

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
                premium_is_notional=c.premium_is_notional,
                part_of_spread=part_of_spread,
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

    # 注目取引は金額の大きい順に
    analysis.notable_trades.sort(key=lambda t: t.premium_usd, reverse=True)
    analysis.premium_basis_notional = any(t.premium_is_notional for t in analysis.notable_trades)
    analysis.itm_call_strikes = sorted(set(analysis.itm_call_strikes))
    analysis.itm_put_strikes = sorted(set(analysis.itm_put_strikes))
    return analysis


def analyze(
    snapshots: list[TickerSnapshot],
    thresholds: Thresholds,
    provider_name: str,
    flow_based: bool,
    generated_at: str,
    as_of: Optional[date] = None,
) -> DailyAnalysis:
    daily = DailyAnalysis(
        generated_at=generated_at,
        provider=provider_name,
        flow_based=flow_based,
    )
    # as_of 未指定なら generated_at の先頭(YYYY-MM-DD)から推定
    if as_of is None:
        as_of = _parse_iso_date(generated_at.split(" ")[0]) if generated_at else None
    for snap in snapshots:
        daily.tickers.append(analyze_ticker(snap, thresholds, flow_based, as_of=as_of))
    return daily

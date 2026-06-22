"""分析結果を Markdown レポートに整形する。"""

from __future__ import annotations

from .analyzer import DailyAnalysis, TickerAnalysis


def _fmt_usd(value: float) -> str:
    """ドル金額を読みやすい単位に。"""
    v = float(value)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1_000_000:
        return f"{sign}${a / 1_000_000:.1f}M"
    if a >= 1_000:
        return f"{sign}${a / 1_000:.0f}K"
    return f"{sign}${a:.0f}"


_EMOJI = {"上昇期待": "📈", "下落期待": "📉", "中立": "➖"}


def _amount_label(notional: bool) -> str:
    """金額の意味づけラベル。実プレミアムか行使額(notional)か。"""
    return "想定元本" if notional else "プレミアム"


def _ticker_section(t: TickerAnalysis, flow_based: bool) -> str:
    if t.error:
        return f"### {t.ticker}\n\n> ⚠️ データ取得失敗: {t.error}\n"

    amount = _amount_label(t.premium_basis_notional)
    if t.moneyness_unknown:
        spot_line = "- 原資産価格: 取得できず（ITM/OTM判定は無効）"
        itm_call = itm_put = "—（spot不明）"
    else:
        spot_line = f"- 原資産価格: ${t.underlying_price:,.2f}"
        itm_call = ", ".join(f"${s:g}" for s in t.itm_call_strikes) or "—"
        itm_put = ", ".join(f"${s:g}" for s in t.itm_put_strikes) or "—"

    lines = [
        f"### {_EMOJI.get(t.classification, '')} {t.ticker} — {t.classification}",
        "",
        spot_line,
        f"- 方向性スコア(強気=+/弱気=-): {_fmt_usd(t.bullish_score_usd)}（規模 {_fmt_usd(t.conviction_usd)}・{amount}基準）",
        f"- {amount} put/call レシオ: {t.put_call_ratio}",
        f"- 注目価格帯 ITM CALL: {itm_call}",
        f"- 注目価格帯 ITM PUT: {itm_put}",
        "",
    ]
    if t.expired_skipped:
        lines.insert(2, f"- ⚠️ 期限切れの約定 {t.expired_skipped} 件を除外しました")
    if t.has_spread:
        lines.insert(
            2,
            "- ⇄ 縦スプレッド(買い+売り)を検出。方向は買い建てレッグ基準に補正しています",
        )

    if t.notable_trades:
        lines.append("大口取引(上位):")
        lines.append("")
        header = f"| 限月 | 種別 | 行使価格 | 出来高 | 建玉 | V/OI | {amount} | IV | 方向 |"
        sep = "|---|---|---|---|---|---|---|---|---|"
        lines.append(header)
        lines.append(sep)
        for tr in t.notable_trades[:8]:
            otype = tr.option_type.upper()
            if flow_based and tr.side:
                otype += f"({'買' if tr.side == 'buy' else '売'})"
            if tr.part_of_spread:
                otype += "⇄"
            new_pos = "🆕" if tr.new_positioning else ""
            dir_mark = "🟢強気" if tr.direction == "bullish" else "🔴弱気"
            voi = "—(OI0)" if tr.open_interest == 0 else f"{tr.vol_oi_ratio}"
            iv = f"{tr.implied_volatility:.0%}" if tr.implied_volatility > 0 else "—"
            lines.append(
                f"| {tr.expiry} | {otype}{new_pos} | ${tr.strike:g} | "
                f"{tr.volume:,} | {tr.open_interest:,} | {voi} | "
                f"{_fmt_usd(tr.premium_usd)} | {iv} | {dir_mark} |"
            )
        lines.append("")
    else:
        lines.append("大口取引: 閾値を超える取引なし")
        lines.append("")
    return "\n".join(lines)


def build_markdown(daily: DailyAnalysis, claude_review: str | None = None) -> str:
    method = "本物の約定フロー(買い/売り判定あり)" if daily.flow_based else "チェーン推定(出来高・建玉ベース)"
    notional = daily.premium_basis_notional
    amount = _amount_label(notional)
    ranked = daily.ranked()

    out: list[str] = []
    out.append("# 🏰 ツンデレ姫のオプション分析 — 日次レポート")
    out.append("")
    out.append(f"- 生成日時: {daily.generated_at}")
    out.append(f"- データ取得元: `{daily.provider}` / 判定方式: {method}")
    out.append(f"- 監視銘柄数: {len(daily.tickers)}")
    if daily.total_expired_skipped:
        out.append(f"- 期限切れ除外: {daily.total_expired_skipped} 件")
    if notional:
        out.append(
            "- ⚠️ オプション価格(1株単価)が取得できなかったため、金額は実プレミアムではなく"
            "**行使額(想定元本 = 行使価格 × 出来高 × 100)**で代用しています。"
            "規模の目安であり、実際に投じられた金額ではありません。"
        )
    out.append("")

    # まとめ(ステップ6): 大口の方向性が見えた銘柄
    out.append("## 📊 まとめ — 大口の方向性が見えた銘柄")
    out.append("")
    if ranked:
        out.append(f"| 順位 | 銘柄 | 判定 | 規模({amount}) | put/call |")
        out.append("|---|---|---|---|---|")
        for i, t in enumerate(ranked, 1):
            out.append(
                f"| {i} | **{t.ticker}** | {_EMOJI.get(t.classification,'')} {t.classification} "
                f"| {_fmt_usd(t.conviction_usd)} | {t.put_call_ratio} |"
            )
    else:
        out.append("> 本日は明確な方向性が見える銘柄はありませんでした（全銘柄が中立）。")
    out.append("")

    # クロード監修
    if claude_review:
        out.append("## 👑 クロード監修コメント")
        out.append("")
        out.append(claude_review.strip())
        out.append("")

    # 銘柄別の詳細
    out.append("## 🔍 銘柄別詳細")
    out.append("")
    # 方向性のある銘柄を先に、その後に中立・エラー
    ordered = ranked + [
        t for t in daily.tickers if t not in ranked
    ]
    for t in ordered:
        out.append(_ticker_section(t, daily.flow_based))

    out.append("---")
    out.append("")
    disclaimer = (
        "> ⚠️ 本レポートは情報提供のみを目的とした自動分析であり、投資助言ではありません。"
    )
    if not daily.flow_based:
        disclaimer += "チェーン推定方式は約定の買い/売りを区別できないため、方向性はあくまで推定です。"
    if notional:
        disclaimer += (
            "金額は実プレミアムではなく行使額(想定元本)で代用しており、規模の目安にすぎません。"
        )
    disclaimer += (
        "単一の約定はスプレッド/ヘッジの一部のことがあり、方向ラベルが実際の戦略と異なる場合があります。"
        "最終的な投資判断はご自身の責任で行ってください。"
    )
    out.append(disclaimer)
    out.append("")
    return "\n".join(out)

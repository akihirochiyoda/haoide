"""クロード監修 — Anthropic API で分析結果のレビュー/総括コメントを生成する。

ANTHROPIC_API_KEY が無い、または anthropic SDK 未導入の場合はテンプレート要約に
フォールバックするため、キー無しでもツール全体は動作する。
"""

from __future__ import annotations

import json

from .analyzer import DailyAnalysis
from .config import ClaudeConfig

_PERSONA = {
    "tsundere": (
        "あなたは『ツンデレ姫』というキャラクターのオプション分析アドバイザーです。"
        "ツンデレ口調(素直じゃないけど的確、時々照れ隠し)で、しかし分析内容は厳密かつ"
        "プロフェッショナルに。語尾に過度な装飾はしすぎないこと。"
    ),
    "analyst": (
        "あなたは冷静で経験豊富なオプションフローのアナリストです。"
        "誇張せず、根拠に基づいて簡潔に述べてください。"
    ),
}

_SYSTEM_BASE = (
    "あなたは米国株オプションフロー分析の監修者です。"
    "与えられた構造化データ(監視銘柄ごとの大口取引・方向性スコア・分類)を"
    "レビューし、(1)全体の総括、(2)特に注目すべき銘柄と理由、"
    "(3)ヒューリスティック判定の注意点・矛盾・過信すべきでない点、"
    "(4)免責、を日本語で簡潔にまとめてください。"
    "投資助言ではなく情報提供である点を明確にし、断定を避けてください。"
    "出力は Markdown の箇条書き中心で、長くなりすぎないように。"
)


def _build_user_payload(daily: DailyAnalysis) -> str:
    ranked = daily.ranked()
    summary = {
        "generated_at": daily.generated_at,
        "data_method": "real_flow" if daily.flow_based else "chain_heuristic",
        "ranked_directional": [
            {
                "ticker": t.ticker,
                "classification": t.classification,
                "conviction_usd": t.conviction_usd,
                "bullish_score_usd": t.bullish_score_usd,
                "put_call_ratio": t.put_call_ratio,
                "top_trades": [
                    {
                        "type": tr.option_type,
                        "side": tr.side,
                        "strike": tr.strike,
                        "expiry": tr.expiry,
                        "premium_usd": tr.premium_usd,
                        "vol_oi_ratio": tr.vol_oi_ratio,
                        "direction": tr.direction,
                    }
                    for tr in t.notable_trades[:3]
                ],
            }
            for t in ranked
        ],
        "neutral_or_error": [
            {"ticker": t.ticker, "classification": t.classification, "error": t.error}
            for t in daily.tickers
            if t not in ranked
        ],
    }
    return (
        "以下は本日のオプションフロー分析結果(構造化データ)です。"
        "これを監修し、総括コメントを作成してください。\n\n```json\n"
        + json.dumps(summary, ensure_ascii=False, indent=2)
        + "\n```"
    )


def generate_review(daily: DailyAnalysis, cfg: ClaudeConfig) -> str:
    """クロード監修コメントを返す。失敗時はテンプレート要約。"""
    if not cfg.enabled:
        return _fallback(daily, reason="クロード監修は無効化されています")
    if not cfg.api_key:
        return _fallback(daily, reason="ANTHROPIC_API_KEY 未設定のためテンプレート要約を使用")

    try:
        import anthropic
    except ImportError:
        return _fallback(daily, reason="anthropic SDK 未導入のためテンプレート要約を使用")

    try:
        client = anthropic.Anthropic(api_key=cfg.api_key)
        persona = _PERSONA.get(cfg.persona, _PERSONA["analyst"])
        system = persona + "\n\n" + _SYSTEM_BASE

        # opus 4.8: adaptive thinking。レポートは長くなりうるため stream で受ける。
        with client.messages.stream(
            model=cfg.model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": _build_user_payload(daily)}],
        ) as stream:
            message = stream.get_final_message()

        text = "".join(b.text for b in message.content if b.type == "text").strip()
        return text or _fallback(daily, reason="クロードの応答が空でした")
    except Exception as exc:  # API エラーでもツールは止めない
        return _fallback(daily, reason=f"クロード監修に失敗({exc}); テンプレート要約を使用")


def _fallback(daily: DailyAnalysis, reason: str) -> str:
    """API を使わないテンプレート要約。"""
    ranked = daily.ranked()
    lines = [f"_({reason})_", ""]
    if not ranked:
        lines.append("- 本日は明確な大口の方向性が見える銘柄はありませんでした。")
    else:
        bulls = [t.ticker for t in ranked if t.classification == "上昇期待"]
        bears = [t.ticker for t in ranked if t.classification == "下落期待"]
        if bulls:
            lines.append(f"- 📈 上昇期待: {', '.join(bulls)}")
        if bears:
            lines.append(f"- 📉 下落期待: {', '.join(bears)}")
        top = ranked[0]
        lines.append(
            f"- 最も方向性が明確なのは **{top.ticker}**（{top.classification}、確信度 {top.conviction_usd:,.0f} 相当）。"
        )
    if not daily.flow_based:
        lines.append(
            "- ⚠️ 本日はチェーン推定方式。約定の買い/売りを区別できないため方向性は推定であり、過信は禁物。"
        )
    lines.append("- 本コメントは情報提供であり投資助言ではありません。")
    return "\n".join(lines)

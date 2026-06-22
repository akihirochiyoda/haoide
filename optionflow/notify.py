"""レポートの届け先 — ファイル保存と Slack 通知。"""

from __future__ import annotations

import json
from pathlib import Path

from .analyzer import DailyAnalysis


def save_reports(daily: DailyAnalysis, markdown: str, output_dir: str | Path, date_str: str) -> dict:
    """Markdown と JSON を output_dir に保存し、保存先パスを返す。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    md_path = out / f"{date_str}.md"
    json_path = out / f"{date_str}.json"
    latest = out / "latest.md"

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(daily.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest.write_text(markdown, encoding="utf-8")

    return {"markdown": str(md_path), "json": str(json_path), "latest": str(latest)}


def post_to_slack(webhook_url: str, daily: DailyAnalysis, claude_review: str | None) -> bool:
    """Slack Incoming Webhook に要約を投稿する。成功で True。"""
    try:
        import requests
    except ImportError:
        return False

    ranked = daily.ranked()
    lines = [f"*🏰 ツンデレ姫のオプション分析* — {daily.generated_at}"]
    if ranked:
        for i, t in enumerate(ranked[:10], 1):
            emoji = {"上昇期待": "📈", "下落期待": "📉"}.get(t.classification, "➖")
            lines.append(f"{i}. {emoji} *{t.ticker}* — {t.classification}（確信度 {t.conviction_usd:,.0f}）")
    else:
        lines.append("本日は明確な方向性が見える銘柄はありませんでした。")

    if claude_review:
        snippet = claude_review.strip().splitlines()
        lines.append("")
        lines.append("👑 *監修コメント*")
        lines.extend(snippet[:8])

    payload = {"text": "\n".join(lines)}
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        return resp.status_code < 300
    except Exception:
        return False

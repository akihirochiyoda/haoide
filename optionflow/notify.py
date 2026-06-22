"""レポートの届け先 — ファイル保存と Slack 通知。"""

from __future__ import annotations

import json
from pathlib import Path

from .analyzer import DailyAnalysis
from .report import build_summary_csv, build_trades_csv


def save_reports(
    daily: DailyAnalysis,
    markdown: str,
    output_dir: str | Path,
    run_id: str,
) -> dict:
    """実行ごとに run_id(タイムスタンプ)で命名したファイル群を保存する。

    生成物(1実行=1断面):
      <run_id>.md          Markdown レポート(→ Google ドキュメント用)
      <run_id>.summary.csv まとめ表    (→ Google スプレッドシート用)
      <run_id>.trades.csv  大口取引明細(→ Google スプレッドシート用)
      <run_id>.json        構造化データ(機械可読)
      latest.md            直近実行へのエイリアス(常に上書き)
    戻り値は各保存先パス。
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    base = f"optionflow_{run_id}"
    md_path = out / f"{base}.md"
    summary_csv = out / f"{base}.summary.csv"
    trades_csv = out / f"{base}.trades.csv"
    json_path = out / f"{base}.json"
    latest = out / "latest.md"

    md_path.write_text(markdown, encoding="utf-8")
    summary_csv.write_text(build_summary_csv(daily), encoding="utf-8")
    trades_csv.write_text(build_trades_csv(daily), encoding="utf-8")
    json_path.write_text(
        json.dumps(daily.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    latest.write_text(markdown, encoding="utf-8")

    return {
        "run_id": run_id,
        "markdown": str(md_path),
        "summary_csv": str(summary_csv),
        "trades_csv": str(trades_csv),
        "json": str(json_path),
        "latest": str(latest),
    }


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
            lines.append(f"{i}. {emoji} *{t.ticker}* — {t.classification}（規模 {t.conviction_usd:,.0f}）")
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

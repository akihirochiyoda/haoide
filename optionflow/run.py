"""日次実行のエントリポイント。

使い方:
    python -m optionflow.run [--config PATH] [--output-dir DIR]
                             [--provider auto|yfinance|unusual_whales]
                             [--no-claude] [--tickers NVDA,AMD,...]

GitHub Actions の cron から呼び出され、reports/ にレポートを生成する。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .analyzer import analyze
from .claude_review import generate_review
from .config import Config
from .notify import post_to_slack, save_reports
from .providers import get_provider
from .report import build_markdown


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ツンデレ姫のオプション分析 — 日次実行")
    p.add_argument("--config", default=None, help="config.json のパス")
    p.add_argument("--output-dir", default="reports", help="レポート出力先(既定: reports)")
    p.add_argument("--provider", default=None, help="auto|yfinance|unusual_whales")
    p.add_argument("--tickers", default=None, help="監視銘柄をカンマ区切りで上書き")
    p.add_argument("--no-claude", action="store_true", help="クロード監修を無効化")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = Config.load(args.config)

    if args.provider:
        cfg.provider = args.provider
    explicit_tickers = bool(args.tickers)
    if args.tickers:
        cfg.watchlist = [s.strip().upper() for s in args.tickers.split(",") if s.strip()]
    if args.no_claude:
        cfg.claude.enabled = False

    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    date_str = now.strftime("%Y-%m-%d")

    # 1) データ取得
    provider = get_provider(cfg.provider)

    # データ側が銘柄一覧を持ち(InfoLib 等)、--tickers 未指定なら、
    # ファイルに出現した全銘柄(=大口が出た銘柄)を分析対象にする。
    tickers = cfg.watchlist
    if not explicit_tickers:
        available = provider.available_tickers()
        if available:
            tickers = available

    if not tickers:
        print("分析対象の銘柄がありません。config.json / --tickers / データファイルを確認してください。", file=sys.stderr)
        return 2

    print(f"[{provider.name}] {len(tickers)} 銘柄を取得中...", file=sys.stderr)
    snapshots = provider.fetch_many(tickers, expiries_to_scan=cfg.expiries_to_scan)

    # 2)-5) 分析(画像フローの中核)
    daily = analyze(
        snapshots,
        thresholds=cfg.thresholds,
        provider_name=provider.name,
        flow_based=provider.provides_flow_side,
        generated_at=generated_at,
        as_of=now.date(),
    )

    # クロード監修
    print("クロード監修コメントを生成中...", file=sys.stderr)
    review = generate_review(daily, cfg.claude)

    # 6) レポート生成・保存
    markdown = build_markdown(daily, claude_review=review)
    paths = save_reports(daily, markdown, args.output_dir, date_str)
    print(f"レポート保存: {paths['markdown']}", file=sys.stderr)

    # 任意: Slack 通知
    if cfg.slack_webhook_url:
        ok = post_to_slack(cfg.slack_webhook_url, daily, review)
        print(f"Slack 通知: {'成功' if ok else '失敗'}", file=sys.stderr)

    ranked = daily.ranked()
    print(f"方向性が見えた銘柄: {len(ranked)} / {len(daily.tickers)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""InfoLib をローカルのブラウザ(Playwright)で取得するスクリプト。

このリポジトリのクラウド実行環境からは infolib.org に到達できないため、
本スクリプトは **ローカル(Claude コワーク)** で実行する前提。

やること:
  1. https://infolib.org/market-dashboard/unusual-options-flow を実ブラウザで開く
  2. ページが内部で叩く XHR/fetch の JSON レスポンスを丸ごと捕捉して保存
     (= 公式ドキュメントの無い「データ取得口」をローカルで特定するため)
  3. スクリーンショットとレンダリング後HTMLも保存(セレクタ調整やClaudeの読み取り用)

セットアップ(ローカル):
    pip install playwright
    playwright install chromium

実行:
    python -m optionflow.tools.fetch_infolib
    python -m optionflow.tools.fetch_infolib --headed   # 画面を見ながら

出力(既定):
    data/infolib_capture/responses/*.json   捕捉した JSON レスポンス
    data/infolib_capture/page.html          レンダリング後HTML
    data/infolib_capture/page.png           スクリーンショット

次のステップ:
    responses/ の中から本物のフローJSONを特定したら、その構造を
    optionflow/providers/infolib_provider.py の入力スキーマに合わせて変換する
    (Claude コワークに「このJSONを data/infolib_flow.json のスキーマに変換して」
     と依頼すれば早い)。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

URL = "https://infolib.org/market-dashboard/unusual-options-flow"
DEFAULT_OUT = Path("data/infolib_capture")


def _safe_name(url: str, idx: int) -> str:
    tail = re.sub(r"[^a-zA-Z0-9_.-]+", "_", url.split("?")[0])[-80:]
    return f"{idx:03d}_{tail or 'response'}.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="InfoLib をローカルブラウザで取得")
    parser.add_argument("--url", default=URL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--headed", action="store_true", help="ヘッドありで起動(動作確認用)")
    parser.add_argument("--wait-ms", type=int, default=8000, help="描画/通信待ち(ミリ秒)")
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright が必要です。ローカルで:\n"
            "  pip install playwright && playwright install chromium",
        )
        return 1

    out = Path(args.out)
    resp_dir = out / "responses"
    resp_dir.mkdir(parents=True, exist_ok=True)

    captured: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()

        def on_response(response):
            ctype = (response.headers or {}).get("content-type", "")
            if "application/json" not in ctype:
                return
            try:
                body = response.json()
            except Exception:
                return
            idx = len(captured)
            fname = _safe_name(response.url, idx)
            (resp_dir / fname).write_text(
                json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            captured.append({"url": response.url, "file": str(resp_dir / fname)})

        page.on("response", on_response)

        page.goto(args.url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(args.wait_ms)

        (out / "page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out / "page.png"), full_page=True)
        browser.close()

    index = out / "captured_index.json"
    index.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"捕捉したJSONレスポンス: {len(captured)} 件 -> {resp_dir}")
    for c in captured:
        print(f"  - {c['url']}")
    print(f"HTML: {out/'page.html'} / スクショ: {out/'page.png'}")
    print(
        "\n次: responses/ から本物のフローJSONを特定し、"
        "data/infolib_flow.json のスキーマに変換 → "
        "python -m optionflow.run --provider infolib"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

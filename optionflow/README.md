# 🏰 ツンデレ姫のオプション分析（optionflow）

画像インフォグラフィック「ツンデレ姫のオプション分析」をリバースエンジニアリングし、
**監視銘柄のオプションフローから大口（機関投資家）の方向性を読む**分析を、
**毎日自動実行**できる形に再構成した株式投資判断ツールです。
分析結果は **クロード（Anthropic Claude / opus 4.8）が監修**します。

> ⚠️ 本ツールは情報提供のみを目的とした自動分析であり、投資助言ではありません。
> 最終的な投資判断はご自身の責任で行ってください。

---

## リバースエンジニアした分析フロー

| 元画像のステップ | 本ツールでの実装 |
|---|---|
| ① どんな分析か（大口の動きを読む） | 監視銘柄のオプションを取得（`providers/`） |
| ② まず注目：ITM PUT / ITM CALL の注目価格帯 | ATM付近の ITM 行使価格を抽出（`analyzer.analyze_ticker`） |
| ③ 大きな取引を見つける | 出来高・プレミアム・V/OI で大口を抽出（閾値は `config.json`） |
| ④ PUT買い/売り・CALL買い/売りの判定 | side があれば実データ、無ければ出来高>建玉のポジショニング推定 |
| ⑤ 上昇期待 / 下落期待 に分類 | 方向性スコア（ドル建て）で分類 |
| ⑥ まとめ：方向性が見えた銘柄に注目 | 確信度順にランキング＋クロード監修コメント |

---

## アーキテクチャ

```
optionflow/
├── config.json            # 監視銘柄・閾値・クロード設定（編集ポイント）
├── config.py              # 設定の読み込み（環境変数で上書き可）
├── providers/             # データ取得（プラガブル）
│   ├── yfinance_provider.py        # 無料・既定（チェーン推定）
│   └── unusual_whales_provider.py  # 有料・本物の約定フロー
├── analyzer.py            # 画像フローの中核（②〜⑤）
├── claude_review.py       # クロード監修コメント生成（opus 4.8）
├── report.py              # Markdown レポート整形
├── notify.py              # ファイル保存 + Slack 通知
└── run.py                 # 日次実行エントリポイント
```

データ取得元は **プラガブル**です。

| プロバイダ | 種別 | 方向判定 | 備考 |
|---|---|---|---|
| `yfinance` | 無料・既定 | チェーン推定 | キー不要で即動作 |
| `unusual_whales` | 有料・公式API | 本物のフロー | `UNUSUAL_WHALES_API_KEY` で自動切替 |
| `infolib` | 無料・ブラウザ取得 | 本物のフロー | InfoLib を Claude コワークが読み取り（[INFOLIB_COWORK.md](INFOLIB_COWORK.md)） |

`auto` は `UNUSUAL_WHALES_API_KEY` があれば Unusual Whales、無ければ yfinance を選びます。
InfoLib を使う場合は `--provider infolib` を明示します。

---

## セットアップ

```bash
pip install -r optionflow/requirements.txt
```

## ローカル実行

```bash
# 既定（config.json の監視銘柄、yfinance）
python -m optionflow.run

# 銘柄を上書き / クロード監修を無効化
python -m optionflow.run --tickers NVDA,AMD,TSLA --no-claude

# プロバイダを明示
python -m optionflow.run --provider yfinance --output-dir reports
```

レポートは `reports/YYYY-MM-DD.md`（と `.json`、`latest.md`）に出力されます。

## テスト（ネット不要）

```bash
python -m optionflow.tests.test_analyzer
```

---

## 毎日の自動実行（GitHub Actions）

`.github/workflows/option-flow-daily.yml` が平日 **22:00 UTC**（米国市場の引け後）に
自動実行し、`reports/` にレポートをコミットします。手動実行（workflow_dispatch）も可能。

### シークレット設定（任意）

リポジトリの **Settings → Secrets and variables → Actions** で設定:

| シークレット | 用途 | 未設定時の挙動 |
|---|---|---|
| `ANTHROPIC_API_KEY` | クロード監修コメント | テンプレート要約にフォールバック |
| `UNUSUAL_WHALES_API_KEY` | 本物の約定フロー | 無料の yfinance を使用 |
| `SLACK_WEBHOOK_URL` | Slack 通知 | 通知しない |

---

## 設定（config.json）

| キー | 説明 |
|---|---|
| `watchlist` | 監視銘柄。`OPTIONFLOW_WATCHLIST`（カンマ区切り）で上書き可 |
| `provider` | `auto`/`yfinance`/`unusual_whales` |
| `expiries_to_scan` | 直近いくつの限月を見るか |
| `thresholds.min_volume` | 大口判定の最小出来高 |
| `thresholds.min_premium_usd` | 大口判定の最小プレミアム（ドル） |
| `thresholds.vol_oi_ratio` | 新規ポジション判定（出来高/建玉） |
| `thresholds.sentiment_strong_usd` | 上昇/下落期待と判定するスコア閾値 |
| `claude.model` | 監修に使うモデル（既定 `claude-opus-4-8`） |
| `claude.persona` | `tsundere`（ツンデレ姫）/ `analyst`（冷静なアナリスト） |

---

## 判定方式についての注意

- **チェーン推定（yfinance, 既定）**: 無料データには約定の買い/売りが含まれないため、
  「出来高 > 建玉＝新規ポジション」をその種別の買いとみなす単純化を行っています。
  コール優勢＝強気、プット優勢＝弱気という近似であり、**方向性はあくまで推定**です。
- **本物の約定フロー（Unusual Whales）**: side（ask側=買い / bid側=売り）が取れるため、
  PUT売り＝強気、CALL売り＝弱気まで含めて精度よく判定します。

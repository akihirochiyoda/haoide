# InfoLib × Claude コワーク 運用手順

InfoLib は公式APIが無いため、**ブラウザ操作できる Claude セッション（Claude コワーク）**が
毎日ページを読み取り、フローデータを JSON に保存 → 分析ツールに渡す、という運用にします。

> 前提: InfoLib は無料・登録不要。ただし非公式取得のため、利用は InfoLib の利用規約に
> 従ってください。本手順は個人の投資判断のための手動相当の取得を想定しています。

---

## 毎日の流れ

```
[Claude コワーク] ブラウザで InfoLib を開く
        │  当日の Unusual Options Flow を読み取る
        ▼
   data/infolib_flow.json に保存(下記スキーマ)
        │
        ▼
   python -m optionflow.run --provider infolib
        │
        ▼
   reports/YYYY-MM-DD.md  ＋ クロード監修コメント
```

---

## ステップ1: ブラウザでフローを取得（Claude コワークに渡す依頼文）

ブラウザ操作できる Claude セッションに、以下をそのまま依頼してください:

```
https://infolib.org/market-dashboard/unusual-options-flow を開いて、
本日の Unusual Options Flow テーブルの上位50件(プレミアムの大きい順)を読み取り、
次のスキーマの JSON 配列として data/infolib_flow.json に保存して。
各プリント1件 = 配列の1要素:

{
  "ticker": "銘柄",
  "type": "call または put",
  "strike": 権利行使価格(数値),
  "expiry": "YYYY-MM-DD",
  "spot": 原資産価格(数値・分かれば),
  "size": 出来高/約定サイズ(数値),
  "open_interest": 建玉(数値・分かれば),
  "price": 1株あたり価格(数値・分かれば),
  "premium": 想定プレミアムのドル額(数値・分かれば),
  "iv": インプライドボラティリティ(小数・分かれば),
  "side": "ask または bid"(分かれば),
  "sentiment": "bullish または bearish"(サイトに表示があれば)
}

side か sentiment のどちらかが取れれば方向判定の精度が上がる。
両方無い項目は省略してよい。保存できたら件数を報告して。
```

> ※ InfoLib のページは JavaScript で描画されるため、テキストコピーよりも
> Claude のブラウザ読み取り（DOM/画面）での抽出が確実です。

---

## ステップ2: 分析を実行

```bash
# InfoLib のフローファイルから分析(--tickers 未指定ならファイル内の全銘柄が対象)
python -m optionflow.run --provider infolib

# 監視銘柄だけに絞る場合
python -m optionflow.run --provider infolib --tickers NVDA,AMD,TSLA
```

- 出力: `reports/YYYY-MM-DD.md`（＋ `.json`、`latest.md`）
- InfoLib は side/sentiment を持つため、**本物のフロー扱い**で
  「PUT売り=強気」まで含めて方向判定します。
- `ANTHROPIC_API_KEY` があればクロードが監修コメントを生成（無くてもテンプレ要約で動作）。

---

## 入力ファイルの場所を変える

既定は `data/infolib_flow.json`。変更したい場合:

```bash
INFOLIB_FLOW_FILE=/path/to/flow.json python -m optionflow.run --provider infolib
```

サンプルは `data/infolib_flow.sample.json`。動作確認は:

```bash
INFOLIB_FLOW_FILE=data/infolib_flow.sample.json python -m optionflow.run --provider infolib --no-claude
```

---

## 自動化のヒント

- このリポジトリで `/loop` などを使い、平日朝にこの手順（ブラウザ取得→分析）を
  Claude コワークに繰り返させると「毎日ルーチン」になります。
- 完全クラウド自動化（GitHub Actions）にしたい場合は、ブラウザ取得ステップが
  ボット検知で不安定になりやすいため、公式APIのある **Unusual Whales**
  (`--provider unusual_whales`) の併用を推奨します。

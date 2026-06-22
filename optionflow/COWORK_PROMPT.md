# Claude コワーク用 貼り付けプロンプト集

InfoLib のオプションフローを毎日取得し、`optionflow` ツールで分析させるための
**コピペで使えるプロンプト**です。ブラウザ操作できる Claude（コワーク/computer use/
ブラウザMCP付き Claude Code）の画面に貼ってください。

- 対象リポジトリ: `https://github.com/akihirochiyoda/haoide`
- ブランチ: `claude/daily-image-flow-automation-6jfswq`
- 分析ツール: `optionflow`（このリポジトリ内）

---

## ① 初回セットアップ用プロンプト（最初の1回だけ）

```text
あなたはローカル環境で作業できる開発アシスタントです。次をこの順で実行してください。

# 目的
GitHub リポジトリ akihirochiyoda/haoide の optionflow ツールを使い、InfoLib の
Unusual Options Flow を毎日分析できる状態をローカルに用意する。

# 手順
1. リポジトリを取得（既にあれば pull）:
   git clone -b claude/daily-image-flow-automation-6jfswq https://github.com/akihirochiyoda/haoide
   cd haoide   （既存なら: git checkout claude/daily-image-flow-automation-6jfswq && git pull）

2. Python 依存をインストール:
   pip install -r optionflow/requirements.txt

3. ブラウザ取得の準備（どちらか）:
   - 方法A（推奨）: あなたがブラウザMCP/computer use でページを直接読めるなら追加準備不要。
   - 方法B: Playwright を使う場合:
       pip install playwright && playwright install chromium

4. サンプルで動作確認（ネット不要・APIキー不要）:
   INFOLIB_FLOW_FILE=data/infolib_flow.sample.json python -m optionflow.run --provider infolib --no-claude
   → reports/ に Markdown が生成され、NVDA=上昇期待 / AMD=下落期待 / TSLA=上昇期待 と
     出れば成功。reports/latest.md の冒頭を見せて報告して。

5. InfoLib に実際にアクセスできるか確認:
   https://infolib.org/market-dashboard/unusual-options-flow をブラウザで開き、
   Unusual Options Flow のテーブルが表示されることを確認して、見えた列名を報告して。

最後に「セットアップ完了」と、4と5の結果を報告してください。
```

---

## ② 毎日の実行用プロンプト（毎営業日）

```text
あなたはローカルで作業できる開発アシスタントです。本日の米国株オプションフローを
取得して分析します。akihirochiyoda/haoide リポジトリの haoide ディレクトリで作業してください。

# 手順
1. 最新化: git checkout claude/daily-image-flow-automation-6jfswq && git pull

2. InfoLib をブラウザで開く:
   https://infolib.org/market-dashboard/unusual-options-flow

3. 本日の Unusual Options Flow テーブルから、プレミアム（規模）の大きい順に
   最大50件を読み取り、次のスキーマの JSON 配列として data/infolib_flow.json に保存:

   各プリント1件 = 配列の1要素:
   {
     "ticker": "銘柄シンボル",
     "type": "call" または "put",
     "strike": 権利行使価格(数値),
     "expiry": "YYYY-MM-DD",
     "spot": 原資産価格(数値・分かれば),
     "size": 出来高/約定サイズ(数値),
     "open_interest": 建玉(数値・分かれば),
     "price": 1株あたり価格(数値・分かれば),
     "premium": 想定プレミアムのドル額(数値・分かれば),
     "iv": インプライドボラティリティ(小数・分かれば),
     "side": "ask" または "bid"(分かれば),
     "sentiment": "bullish" または "bearish"(サイト表示があれば)
   }

   ルール:
   - side か sentiment のどちらかが取れれば方向判定の精度が上がる。両方無い項目は省略可。
   - 【重要】"price"(オプションの1株あたり価格) と "spot"(原資産価格) を可能な限り入れる。
     price が無いと金額が実プレミアムではなく行使額(想定元本)で代用され、ITM/OTM 判定も無効になる。
   - 数値はカンマや $ を除いた数値にする（例 "1,250" → 1250、"$2.5M" → 2500000）。
   - "expiry" は当日以降の限月のみ（期限切れは分析側で自動除外される）。
   - テキストコピーが難しければ画面読み取りで抽出してよい。
   - 保存したら件数を報告。

   ※ ブラウザMCPが無い場合の代替:
     python -m optionflow.tools.fetch_infolib を実行し、
     data/infolib_capture/responses/ に保存された JSON から本物のフローデータを特定し、
     上記スキーマに変換して data/infolib_flow.json に保存する。

4. 分析を実行:
   python -m optionflow.run --provider infolib --no-claude

5. 結果の報告:
   - reports/latest.md を開き、「まとめ — 大口の方向性が見えた銘柄」表を要約。
   - さらに、あなた自身が『ツンデレ姫』の口調で、本日の総括コメント（3〜5行、
     注目銘柄と理由、ヒューリスティックではなく実フローに基づく点、過信への注意、
     これは投資助言ではない旨）を作成して提示。
   - 生成された reports/ をコミット＆プッシュ:
       git add reports/ data/infolib_flow.json
       git commit -m "infolib flow report $(date -u +%Y-%m-%d)"
       git push

6. Google ドライブへ断面を保存（このプロンプト集の「⑤」の手順を実行）。

完了したら、まとめ表・監修コメント・ドライブの保存リンクをこの画面に表示してください。
```

---

## ③ 毎日用（コンパクト版・データだけ作る）

ブラウザ読み取りだけ任せて、分析は自分のターミナルで回したい場合:

```text
https://infolib.org/market-dashboard/unusual-options-flow を開き、本日の
Unusual Options Flow 上位50件（プレミアムの大きい順）を、次のスキーマの JSON 配列で
data/infolib_flow.json に保存して。各要素:
{ "ticker","type"(call/put),"strike","expiry"(YYYY-MM-DD),"spot","size",
  "open_interest","price","premium","iv","side"(ask/bid),"sentiment"(bullish/bearish) }
side か sentiment のどちらかは必ず入れて。数値は $ やカンマを除く。保存後に件数を報告。
```

その後ローカルで:

```bash
python -m optionflow.run --provider infolib
```

---

## ④ 訂正指示（前回レポートの不具合を直して取り直す）

前回の出力には次の問題がありました。原因はいずれも **取得データの欠損** です。
このプロンプトで取り直すと解消します（分析側のコードはすでに修正済み）。

- 金額が「実プレミアム」ではなく行使額（想定元本）になっていた → `price` 未取得が原因
- 「原資産価格 $0.00／ITM判定が全部無効」 → `spot` 未取得が原因
- 期限切れの限月が上位に出ていた → 過去日の限月が混入
- スプレッドの片脚で方向が反転 → 各脚の `side` が正しく取れていれば分析側が補正

```text
あなたはローカルで作業できる開発アシスタントです。前回のオプションフロー分析の
取得データに不備があったため、取り直して再分析します。akihirochiyoda/haoide の
haoide ディレクトリで作業してください。

# まず最新コードに更新（重要・分析ロジックが修正済み）
git checkout claude/daily-image-flow-automation-6jfswq && git pull

# データ取得
https://infolib.org/market-dashboard/unusual-options-flow を開き、本日の
Unusual Options Flow から、プレミアム（金額）の大きい順に最大50件を読み取り、
次のスキーマの JSON 配列として data/infolib_flow.json に保存する。

各約定 = 配列の1要素:
{
  "ticker":  "銘柄シンボル",
  "type":    "call" または "put",
  "strike":  権利行使価格(数値),
  "expiry":  "YYYY-MM-DD",
  "spot":    原資産価格(数値),               ★必須に近い: これが無いとITM/OTM判定が無効になる
  "size":    出来高/約定サイズ(数値),
  "open_interest": 建玉(数値),
  "price":   オプションの1株あたり価格(数値),  ★最重要: これが無いと金額が実プレミアムにならず
                                              行使額(想定元本)で代用され桁が大きくずれる
  "premium": 想定プレミアムのドル額(数値・分かれば),
  "iv":      インプライドボラティリティ(小数),
  "side":    "ask" または "bid",              ★各脚ごとに正しく。スプレッド方向補正に使う
  "sentiment": "bullish" または "bearish"
}

# 取得時の必須ルール（前回の不備を直すため）
1. 【最重要】"price"(オプションの1株単価) を必ず入れる。サイトに「Price」「Last」
   「Fill」等の1株価格があればそれ。"premium" 欄に行使額(strike×size×100)を
   入れない（それは想定元本であってプレミアムではない）。
2. 【必須】"spot"(原資産価格) を必ず入れる。0 や空にしない。
3. "expiry" は当日(本日)以降の限月のみ。過去日の限月は含めない。
4. "side" は各約定ごとに ask(買い手主導)/bid(売り手主導) を正確に。
   取れない時は "sentiment"(bullish/bearish) を入れる。両方無い行は方向不明として可。
5. 数値は $ やカンマ・単位を除いた純粋な数値にする
   （"1,250"→1250、"$2.5M"→2500000、"$5.10"→5.10、IV "55%"→0.55）。
6. 画面読み取りで抽出してよい。保存したら件数を報告。

# 分析を実行
python -m optionflow.run --provider infolib --no-claude

# 検算（前回の不具合が直ったかを必ず確認して報告）
reports/latest.md を開き、次を確認して結果を報告:
  (a) ヘッダに「想定元本で代用」の警告が出ていない（= price が効いて実プレミアムになった）
  (b) 各銘柄の「原資産価格」が $0.00 でなく実数になっている
  (c) 「期限切れ除外」の件数（あれば妥当か）
  (d) スプレッドのある銘柄に「⇄ 縦スプレッド検出」の注記が出て方向が妥当か
もし (a) の警告がまだ出る/原資産が $0.00 のままなら、price と spot の取得を見直して
data/infolib_flow.json を作り直し、再実行する。

# まとめと保存
- reports/latest.md の「まとめ」表を要約し、あなた自身の総括コメント（注目銘柄と理由、
  実フロー判定である点、規模が大きい＝確度が高いではない点、投資助言ではない旨）を提示。
- コミット＆プッシュ:
    git add reports/ data/infolib_flow.json
    git commit -m "infolib flow report (corrected data) $(date -u +%Y-%m-%d)"
    git push
- Google ドライブへ断面を保存（このプロンプト集の「⑤」の手順を実行）。

完了したら、検算(a)〜(d)の結果・まとめ表・総括コメント・ドライブ保存リンクを表示してください。
```

---

## ⑤ Google ドライブへ断面ごとに保存（毎回のアップロード）

`python -m optionflow.run` は実行のたびに `reports/` に **タイムスタンプ命名**の
ファイル群を生成します（1実行＝1断面、上書きしない）:

- `optionflow_<run_id>.md`          … レポート本文（→ Google ドキュメント）
- `optionflow_<run_id>.summary.csv` … まとめ表  （→ Google スプレッドシート）
- `optionflow_<run_id>.trades.csv`  … 大口取引明細（→ Google スプレッドシート）
- `optionflow_<run_id>.json`        … 構造化データ
- `run_id` 例: `2026-06-22_123018Z`（UTC・秒まで）

これらを、ドライブ操作できるコワークが**専用フォルダ**へアップロードします。
分析実行プロンプト（②/④）の最後に、次の手順を続けて実行してください。

```text
# Google ドライブへ断面を保存する
1. 専用フォルダを用意（初回のみ作成、以降は再利用）:
   - タイトル "OptionFlow Reports - ツンデレ姫オプション分析" のフォルダを検索。
   - 無ければ mimeType=application/vnd.google-apps.folder で作成し、フォルダIDを控える。
2. 今回の run_id（実行ログ "レポート保存 (run_id=...)" の値）に対応する reports/ の
   4ファイルを、そのフォルダ配下にアップロード:
   - optionflow_<run_id>.md
       → contentMimeType=text/plain でアップロード（Google ドキュメントに自動変換）
         タイトル: "OptionFlow <run_id> レポート"
   - optionflow_<run_id>.summary.csv
       → contentMimeType=text/csv でアップロード（Google スプレッドシートに自動変換）
         タイトル: "OptionFlow <run_id> まとめ"
   - optionflow_<run_id>.trades.csv
       → contentMimeType=text/csv でアップロード（スプレッドシートに自動変換）
         タイトル: "OptionFlow <run_id> 明細"
   - optionflow_<run_id>.json
       → contentMimeType=application/json でアップロード（変換しない）
         タイトル: "OptionFlow <run_id> data.json"
   いずれも parentId に専用フォルダのIDを指定する。
3. アップロードした各ファイルの共有リンク（URL）をこの画面に一覧表示して報告する。
   フォルダのリンクも併記する。
```

ポイント:
- 毎回 run_id が変わるため、断面ごとに別ファイルとしてドライブに残ります（履歴になる）。
- ドキュメント＝読み物（レポート）、スプレッドシート＝集計（まとめ＋明細）の使い分け。
- 同じ run_id で再アップロードしないこと（重複防止）。

---

## 補足

- コワークの Claude 自身が監修コメントを書く運用なら `ANTHROPIC_API_KEY` は不要
  （`--no-claude` で実行し、コメントはコワークが生成）。
- API で監修させたい場合は `ANTHROPIC_API_KEY` を設定し `--no-claude` を外す。
- 利用は InfoLib の利用規約の範囲で。個人の投資判断のための手動相当の取得を想定。

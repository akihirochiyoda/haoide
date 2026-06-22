"""設定の読み込み。config.json と環境変数をマージする。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")


@dataclass
class Thresholds:
    """大口・異常取引を判定するための閾値。"""

    min_volume: int = 500
    # 1契約=100株。premium(想定ドル) = volume * price * 100
    min_premium_usd: float = 250_000
    # volume / open_interest がこの値以上なら「新規ポジション」とみなす
    vol_oi_ratio: float = 1.0
    # 原資産価格からこの割合以内の権利行使価格を「注目価格帯(ATM付近)」とする
    itm_near_the_money_pct: float = 0.10
    # 方向性スコアの絶対値がこの額を超えたら「強い方向性あり」と判定
    sentiment_strong_usd: float = 2_000_000
    # 新規ポジションの方向性スコアにかける重み
    new_positioning_weight: float = 1.5


@dataclass
class ClaudeConfig:
    """クロード監修(Anthropic API)の設定。"""

    enabled: bool = True
    model: str = "claude-opus-4-8"
    # persona: "tsundere"(ツンデレ姫) | "analyst"(冷静なアナリスト)
    persona: str = "tsundere"
    language: str = "ja"
    # APIキーは環境変数からのみ取得する(コミットしない)
    api_key: str | None = None


@dataclass
class Config:
    watchlist: list[str] = field(default_factory=list)
    # provider: "auto" | "yfinance" | "unusual_whales"
    provider: str = "auto"
    expiries_to_scan: int = 3
    thresholds: Thresholds = field(default_factory=Thresholds)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    # レポートの届け先(任意)
    slack_webhook_url: str | None = None

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}
        if cfg_path.exists():
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))

        thresholds = Thresholds(**raw.get("thresholds", {}))
        claude_raw = raw.get("claude", {})
        claude = ClaudeConfig(
            enabled=claude_raw.get("enabled", True),
            model=claude_raw.get("model", "claude-opus-4-8"),
            persona=claude_raw.get("persona", "tsundere"),
            language=claude_raw.get("language", "ja"),
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )

        cfg = cls(
            watchlist=raw.get("watchlist", []),
            provider=os.environ.get("OPTIONFLOW_PROVIDER", raw.get("provider", "auto")),
            expiries_to_scan=int(raw.get("expiries_to_scan", 3)),
            thresholds=thresholds,
            claude=claude,
            slack_webhook_url=os.environ.get("SLACK_WEBHOOK_URL"),
        )

        # 環境変数で監視銘柄を上書き可能(カンマ区切り)
        env_watchlist = os.environ.get("OPTIONFLOW_WATCHLIST")
        if env_watchlist:
            cfg.watchlist = [s.strip().upper() for s in env_watchlist.split(",") if s.strip()]

        # クロード監修を環境変数で無効化できる
        if os.environ.get("OPTIONFLOW_NO_CLAUDE"):
            cfg.claude.enabled = False

        return cfg

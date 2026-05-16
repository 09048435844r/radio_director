"""Bot 設定ローダー。

bot/.env からトークン等を読む。pipeline 実行パスは固定 (~/research_pipeline,
~/radio_director) で、必要に応じて環境変数で上書き可能。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BotConfig:
    discord_token: str
    allowed_user_id: int
    research_pipeline_dir: Path
    radio_director_dir: Path
    research_python: Path
    director_python: Path
    research_output_dir: Path

    @property
    def research_main(self) -> Path:
        return self.research_pipeline_dir / "main.py"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_config() -> BotConfig:
    bot_dir = Path(__file__).resolve().parent
    _load_dotenv(bot_dir / ".env")

    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN が未設定です。bot/.env または環境変数で指定してください。"
        )

    raw_user_id = os.environ.get("ALLOWED_USER_ID", "").strip()
    if not raw_user_id:
        raise RuntimeError(
            "ALLOWED_USER_ID が未設定です。自分の Discord User ID を bot/.env に指定してください。"
        )
    try:
        allowed_user_id = int(raw_user_id)
    except ValueError as e:
        raise RuntimeError(f"ALLOWED_USER_ID は整数で指定してください: {raw_user_id!r}") from e

    home = Path.home()
    research_dir = Path(
        os.environ.get("RESEARCH_PIPELINE_DIR", home / "research_pipeline")
    ).expanduser()
    director_dir = Path(
        os.environ.get("RADIO_DIRECTOR_DIR", home / "radio_director")
    ).expanduser()

    return BotConfig(
        discord_token=token,
        allowed_user_id=allowed_user_id,
        research_pipeline_dir=research_dir,
        radio_director_dir=director_dir,
        research_python=research_dir / "venv" / "bin" / "python",
        director_python=director_dir / ".venv" / "bin" / "python",
        research_output_dir=research_dir / "output",
    )

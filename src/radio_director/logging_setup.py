"""radio_director の進捗ログ設定 (research_pipeline と同等のスタイル)。

run_pipeline() から自動的に呼ばれる。
書式: [YYYY-MM-DD HH:MM:SS] <message>
出力: stderr (run_full.sh の stdout 捕捉と競合しない)
ファイル: <run_dir>/phase_logs/run.log (attach_file_handler 経由)

両関数とも idempotent: 既に同等のハンドラがあれば再追加しない。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import IO

_LOGGER_NAME = "radio_director"
_FORMAT = "[%(asctime)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(*, stream: IO[str] | None = None) -> logging.Logger:
    """radio_director パッケージ logger に StreamHandler を 1 つ取り付ける。

    既に StreamHandler (FileHandler ではない) が attach 済みなら何もしない。
    propagate は True のまま (caplog 等のテスト捕捉と互換)。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    for h in logger.handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            return logger
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    logger.addHandler(handler)
    return logger


def attach_file_handler(run_dir: Path) -> None:
    """<run_dir>/phase_logs/run.log への FileHandler を追加する。

    OutputWriter が phase_logs/ を既に作成済み前提。
    同パスに対する FileHandler が既にあれば何もしない。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    log_path = run_dir / "phase_logs" / "run.log"
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_path:
            return
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    logger.addHandler(handler)

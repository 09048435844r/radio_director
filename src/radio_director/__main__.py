"""python -m radio_director <research_brief.json>

stdout: run_dir パス 1 行 (run_full.sh が RUN_DIR=$(...) で捕捉する想定)
stderr: 進捗ログ (run_pipeline 内で configure_logging により有効化)
"""

from __future__ import annotations

import sys
from pathlib import Path

from radio_director.runner import run_pipeline


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(
            "Usage: python -m radio_director <research_brief.json>",
            file=sys.stderr,
        )
        return 2
    brief_path = Path(args[0])
    if not brief_path.is_file():
        print(f"research_brief not found: {brief_path}", file=sys.stderr)
        return 2
    run_dir = run_pipeline(brief_path)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""パイプライン実行と進捗ストリームを担当するモジュール。

research_pipeline (main.py) → radio_director (-m radio_director) を順次起動し、
ログ行を行単位で解析して人間向けの進捗イベントを async generator として返す。
既存パイプラインのコードには手を入れず、外側からの観察のみで動作する。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

from config import BotConfig


# ─── イベント型 ──────────────────────────────────────────────────
# (event_type, payload)
#   event_type = "progress" : payload = {"message": str}
#   event_type = "complete" : payload = {"result": RunResult}
#   event_type = "error"    : payload = {"message": str, "stage": str}
Event = tuple[str, dict]


@dataclass
class RunResult:
    success: bool
    theme: str
    brief_path: Optional[Path] = None
    run_dir: Optional[Path] = None
    metrics: dict = field(default_factory=dict)
    error: Optional[str] = None
    elapsed_sec: float = 0.0


# ─── research_pipeline ログマーカー ────────────────────────────
_RP_STAGE_MARKERS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"─── STAGE 1: PLAN"),       "📋 STAGE 1: クエリ・アウトライン生成中..."),
    (re.compile(r"─── STAGE 2: FETCH"),      "🔍 STAGE 2: 記事を収集中 (約10分)..."),
    (re.compile(r"─── STAGE 3: SYNTHESIZE"), "📖 STAGE 3: 記事を要約・統合中 (約20-30分、最も時間がかかります)..."),
    (re.compile(r"─── STAGE 4: ASSEMBLE"),   "🔧 STAGE 4: ブリーフを組み立て中..."),
]
_RP_OUTPUT_RE = re.compile(r"出力ファイル\s*:\s*(\S+)")
_RP_COMPLETE_RE = re.compile(r"✅ パイプライン完了")
_RP_FATAL_RES: list[re.Pattern[str]] = [
    re.compile(r"JSON抽出失敗"),
    re.compile(r"❌ ディスク残量不足"),
    re.compile(r"InsufficientResearchError"),
]


# ─── radio_director ログマーカー ────────────────────────────────
_RD_PHASE_A_RE = re.compile(
    r"✅ Phase A 完了:.*sources=(\d+).*key_numbers=(\d+)|"
    r"✅ Phase A 完了: key_numbers=(\d+) key_entities=\d+ surprising=\d+ sources=(\d+)"
)
_RD_PHASE_B_RE = re.compile(r"✅ Phase B 完了: title=「([^」]*)」 topics=(\d+)")
_RD_PHASE_C_RE = re.compile(
    r"✅ Phase C 完了: segments=(\d+) total_chars=(\d+) fallbacks=(\d+)"
)
_RD_PHASE_D_RE = re.compile(
    r"✅ Phase D 完了: title=「([^」]*)」 hashtags=(\d+) chapters=(\d+) references=(\d+) warnings=(\d+)"
)
_RD_GATE_FAIL_RE = re.compile(
    r"🔁 Phase D gate fail \(matched_ratio=([\d.]+)% < ([\d.]+)%\) → Phase B/C を retry \((\d+)/(\d+)\)"
)
_RD_RETRY_DONE_RE = re.compile(
    r"🔁 Phase D retry (\d+) 完了: matched_ratio=([\d.]+)% warnings=(\d+)"
)
_RD_HARD_FAIL_RE = re.compile(r"❌ Phase D gate を retry")
_RD_COMPLETE_RE = re.compile(r"✅ パイプライン完了")


def _make_event(message: str) -> Event:
    return ("progress", {"message": message})


async def _stream_lines(
    reader: asyncio.StreamReader, queue: asyncio.Queue[Optional[str]]
) -> None:
    """StreamReader から 1 行ずつ読んで queue に入れる。EOF で None を入れて終了。"""
    try:
        while True:
            raw = await reader.readline()
            if not raw:
                break
            try:
                line = raw.decode("utf-8", errors="replace").rstrip()
            except Exception:
                continue
            if line:
                await queue.put(line)
    finally:
        await queue.put(None)


async def _iter_subprocess_lines(
    proc: asyncio.subprocess.Process,
) -> AsyncIterator[tuple[str, str]]:
    """subprocess の stdout / stderr を行単位で yield する。

    yield: (source, line)  where source in {"stdout", "stderr"}
    """
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    tagged_queue: asyncio.Queue[Optional[tuple[str, str]]] = asyncio.Queue()

    async def pump(reader: asyncio.StreamReader, source: str) -> None:
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    await tagged_queue.put((source, line))
        finally:
            await tagged_queue.put(None)

    tasks = []
    if proc.stdout is not None:
        tasks.append(asyncio.create_task(pump(proc.stdout, "stdout")))
    if proc.stderr is not None:
        tasks.append(asyncio.create_task(pump(proc.stderr, "stderr")))

    sentinels_remaining = len(tasks)
    while sentinels_remaining > 0:
        item = await tagged_queue.get()
        if item is None:
            sentinels_remaining -= 1
            continue
        yield item

    for t in tasks:
        await t


async def _run_research(
    cfg: BotConfig, theme: str, mode: str
) -> AsyncIterator[Event | tuple[str, Path]]:
    """research_pipeline を起動し、進捗イベントを yield する。

    最後に成功時のみ ("brief", Path) を yield してから return する。
    失敗時は ("error", {...}) を yield して return する。
    """
    if not cfg.research_python.is_file():
        yield (
            "error",
            {
                "message": f"research_pipeline の venv が見つかりません: {cfg.research_python}",
                "stage": "research",
            },
        )
        return

    cmd = [
        str(cfg.research_python),
        "main.py",
        "--theme",
        theme,
        "--mode",
        mode,
    ]
    yield _make_event(f"🔬 research_pipeline 起動: theme=「{theme}」 mode={mode}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cfg.research_pipeline_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    brief_path: Optional[Path] = None
    fatal_seen = False
    last_stage_idx = -1

    async for _src, line in _iter_subprocess_lines(proc):
        for idx, (pat, msg) in enumerate(_RP_STAGE_MARKERS):
            if idx <= last_stage_idx:
                continue
            if pat.search(line):
                last_stage_idx = idx
                yield _make_event(msg)
                break

        m = _RP_OUTPUT_RE.search(line)
        if m:
            brief_path = Path(m.group(1))

        for pat in _RP_FATAL_RES:
            if pat.search(line):
                fatal_seen = True
                yield _make_event(f"⚠️ {line[:200]}")
                break

    rc = await proc.wait()

    if rc != 0 or fatal_seen:
        yield (
            "error",
            {
                "message": f"research_pipeline が失敗 (exit={rc})",
                "stage": "research",
            },
        )
        return

    if brief_path is None or not brief_path.is_file():
        # フォールバック: output dir の最新 research_brief_*.json を採用
        candidates = sorted(
            cfg.research_output_dir.glob("research_brief_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            brief_path = candidates[0]
            yield _make_event(
                f"ℹ️ brief パスをログから取得できず、最新ファイルを採用: {brief_path.name}"
            )
        else:
            yield (
                "error",
                {
                    "message": "research_brief_*.json が生成されていません",
                    "stage": "research",
                },
            )
            return

    yield ("brief", brief_path)


async def _run_director(
    cfg: BotConfig, brief_path: Path
) -> AsyncIterator[Event | tuple[str, dict]]:
    """radio_director を起動し、進捗イベントを yield する。

    最後に成功時のみ ("director_done", {"run_dir": Path}) を yield する。
    失敗時は ("error", {...}) を yield する。
    """
    if not cfg.director_python.is_file():
        yield (
            "error",
            {
                "message": f"radio_director の venv が見つかりません: {cfg.director_python}",
                "stage": "director",
            },
        )
        return

    cmd = [
        str(cfg.director_python),
        "-m",
        "radio_director",
        str(brief_path),
    ]
    yield _make_event(f"🎙️ radio_director 起動: brief={brief_path.name}")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cfg.radio_director_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    run_dir: Optional[Path] = None
    hard_fail_seen = False
    segments_seen: Optional[int] = None
    segments_announced = False

    async for src, line in _iter_subprocess_lines(proc):
        # stdout は run_dir のパスがそのまま 1 行で出力される (__main__.py 仕様)
        if src == "stdout":
            stripped = line.strip()
            if stripped and "/" in stripped:
                candidate = Path(stripped)
                if candidate.is_absolute():
                    run_dir = candidate
            continue

        # 以下 stderr (ログ)
        if "─── Phase A: DECODE" in line:
            yield _make_event("🧠 Phase A: ブリーフを読み込み中...")
            continue

        m = _RD_PHASE_A_RE.search(line)
        if m:
            # 二つの代替パターンのうちマッチした方を採用
            groups = [g for g in m.groups() if g is not None]
            if len(groups) >= 2:
                if "sources=" in line and line.index("sources=") < line.index("key_numbers="):
                    sources, key_numbers = groups[0], groups[1]
                else:
                    key_numbers, sources = groups[0], groups[1]
                yield _make_event(
                    f"✅ Phase A 完了: sources={sources} key_numbers={key_numbers}"
                )
            continue

        if "─── Phase B: PLAN" in line:
            yield _make_event("📝 Phase B: 番組構成を作成中...")
            continue

        m = _RD_PHASE_B_RE.search(line)
        if m:
            title, topics = m.group(1), m.group(2)
            yield _make_event(f"✅ Phase B 完了: title=「{title}」 topics={topics}")
            continue

        if "─── Phase C: CONDUCT" in line:
            yield _make_event("🎙️ Phase C: 対話セグメントを生成中 (約5-7分)...")
            continue

        m = _RD_PHASE_C_RE.search(line)
        if m:
            segments_seen = int(m.group(1))
            total_chars = m.group(2)
            yield _make_event(
                f"✅ Phase C 完了: segments={segments_seen} total_chars={total_chars}"
            )
            continue

        if "─── Phase D: VERIFY" in line:
            yield _make_event("🔍 Phase D: 数値・引用の検証中...")
            continue

        m = _RD_PHASE_D_RE.search(line)
        if m:
            title = m.group(1)
            hashtags = m.group(2)
            chapters = m.group(3)
            references = m.group(4)
            warnings = m.group(5)
            yield _make_event(
                f"✅ Phase D 完了: title=「{title}」 hashtags={hashtags} "
                f"chapters={chapters} references={references} warnings={warnings}"
            )
            continue

        m = _RD_GATE_FAIL_RE.search(line)
        if m:
            ratio, gate, n, total = m.groups()
            yield _make_event(
                f"🔁 Phase D gate fail (matched_ratio={ratio}% < {gate}%) → retry {n}/{total}"
            )
            continue

        m = _RD_RETRY_DONE_RE.search(line)
        if m:
            n, ratio, warnings = m.groups()
            yield _make_event(
                f"🔁 Phase D retry {n} 完了: matched_ratio={ratio}% warnings={warnings}"
            )
            continue

        if _RD_HARD_FAIL_RE.search(line):
            hard_fail_seen = True
            yield _make_event(f"❌ {line[:200]}")
            continue

    rc = await proc.wait()

    if rc != 0 or hard_fail_seen:
        yield (
            "error",
            {
                "message": f"radio_director が失敗 (exit={rc})",
                "stage": "director",
            },
        )
        return

    if run_dir is None or not run_dir.is_dir():
        yield (
            "error",
            {
                "message": "run_dir を特定できませんでした (stdout 出力なし)",
                "stage": "director",
            },
        )
        return

    yield ("director_done", {"run_dir": run_dir})


def _extract_metrics(run_dir: Path) -> dict:
    """verified_script.json から主要メトリクスを抜き出す。"""
    vs_path = run_dir / "verified_script.json"
    if not vs_path.is_file():
        return {"error": "verified_script.json not found"}
    try:
        data = json.loads(vs_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"verified_script.json 読込失敗: {e}"}

    metrics_block = data.get("metrics") or {}
    metadata = data.get("metadata") or {}
    warnings = data.get("warnings") or []

    return {
        "title": metadata.get("title", ""),
        "thumbnail_title": metadata.get("thumbnail_title", ""),
        "matched_ratio": metrics_block.get("matched_ratio", 0.0),
        "total_numbers_extracted": metrics_block.get("total_numbers_extracted", 0),
        "matched_to_structured_facts": metrics_block.get("matched_to_structured_facts", 0),
        "citation_tags_total": metrics_block.get("citation_tags_total", 0),
        "citation_tags_normalized": metrics_block.get("citation_tags_normalized", 0),
        "false_positive_candidates": metrics_block.get("false_positive_candidates", 0),
        "warnings_count": len(warnings),
        "references_count": len(metadata.get("references", [])),
        "chapters_count": len(metadata.get("chapters", [])),
    }


async def run_full_pipeline(
    cfg: BotConfig, theme: str, mode: str = "lecture"
) -> AsyncIterator[Event]:
    """research_pipeline → radio_director を順次実行し、進捗イベントを yield する。

    最後に必ず "complete" イベントを 1 回 yield して return する (成功・失敗どちら
    でも RunResult.success で区別)。
    """
    started = time.monotonic()

    yield _make_event(f"🚀 パイプライン開始: 「{theme}」 (mode={mode})")
    yield _make_event(
        "ℹ️ 所要時間目安: リサーチ 30-40 分 + 台本生成 5-15 分 = 計 35-55 分"
    )

    brief_path: Optional[Path] = None
    run_dir: Optional[Path] = None

    async for item in _run_research(cfg, theme, mode):
        kind = item[0]
        if kind == "progress":
            yield item
        elif kind == "brief":
            brief_path = item[1]
            yield _make_event(f"✅ research_brief 生成完了: {brief_path.name}")
        elif kind == "error":
            elapsed = time.monotonic() - started
            yield (
                "complete",
                {
                    "result": RunResult(
                        success=False,
                        theme=theme,
                        brief_path=brief_path,
                        error=item[1]["message"],
                        elapsed_sec=elapsed,
                    )
                },
            )
            return

    if brief_path is None:
        elapsed = time.monotonic() - started
        yield (
            "complete",
            {
                "result": RunResult(
                    success=False,
                    theme=theme,
                    error="brief_path 未取得",
                    elapsed_sec=elapsed,
                )
            },
        )
        return

    async for item in _run_director(cfg, brief_path):
        kind = item[0]
        if kind == "progress":
            yield item
        elif kind == "director_done":
            run_dir = item[1]["run_dir"]
        elif kind == "error":
            elapsed = time.monotonic() - started
            yield (
                "complete",
                {
                    "result": RunResult(
                        success=False,
                        theme=theme,
                        brief_path=brief_path,
                        run_dir=run_dir,
                        error=item[1]["message"],
                        elapsed_sec=elapsed,
                    )
                },
            )
            return

    elapsed = time.monotonic() - started

    if run_dir is None:
        yield (
            "complete",
            {
                "result": RunResult(
                    success=False,
                    theme=theme,
                    brief_path=brief_path,
                    error="run_dir 未取得",
                    elapsed_sec=elapsed,
                )
            },
        )
        return

    metrics = _extract_metrics(run_dir)
    yield (
        "complete",
        {
            "result": RunResult(
                success=True,
                theme=theme,
                brief_path=brief_path,
                run_dir=run_dir,
                metrics=metrics,
                elapsed_sec=elapsed,
            )
        },
    )

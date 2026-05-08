# Step 1 改修 — 実装プラン

**版数:** 1.0
**作成日:** 2026-05-09
**対象タスク:** radio_director Step 1 改修（VerifiedScript SSOT 化）
**依拠指示書:** `step1_radio_director_instructions.md` / `step1_research_and_plan_instructions.md`
**対応調査レポート:** `step1_research_report.md`（兄弟ファイル）

---

## Context

auto-radio-generator (Windows 側) への引き渡しを「VerifiedScript 1 ファイル」に集約する。確定要件は `step1_radio_director_instructions.md` §1〜§4 を所与とする。本ファイルは指示書 `step1_research_and_plan_instructions.md` §4 が要求する実装プランで、調査結果（`step1_research_report.md`）に基づく具体的な実装手順・commit 構成・テスト戦略・リスクを記載する。

---

## 1. 修正概要

確定要件 §2.1〜§2.5 を実装する。**Phase A / C は変更しない**。Phase B / D / models / 新規 output モジュールに集中。

**スコープ**:
- ShowSpec に `thumbnail_title` フィールド追加（max_length=15）
- Phase B プロンプト変更 + JSON schema hint 拡張
- SourceRef 新設 + VideoMetadata に `thumbnail_title` / `references` 追加
- Phase D で thumbnail_title をコピー、references を実引用 source_idx から解決（**LLM コール追加禁止**）
- run_id 命名 + `~/radio_director/output/<run_id>/` 出力ディレクトリ生成
- `verified_script.json` / `cleaned_research.json` / `show_spec.json` / `phase_logs/` / `run_metadata.json` の保存

---

## 2. ファイルごとの詳細手順

### 2.1 `src/radio_director/models/show_spec.py`（変更）

```python
class ShowSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    thumbnail_title: str = Field(..., min_length=1, max_length=15)  # ← 追加
    hook: str
    angle: str
    arc: str
    tone: str
    topics: list[TopicSpec] = Field(min_length=2, max_length=4)
    conclusion_message: str
```

### 2.2 `src/radio_director/phase_b/prompt_builder.py`（変更）

- `_TEMPLATE` の「企画書には以下の構成が必要です」セクションに `thumbnail_title (15 字以内、サムネ用の短縮表現)` を追加
- 「重要なルール」に「`thumbnail_title` は title の核心を凝縮した独立して意味が通る自然な日本語（機械的切り詰め禁止）」を追加
- `_JSON_SCHEMA_HINT` に `"thumbnail_title": "..."` を追加（title の直後）

### 2.3 `src/radio_director/phase_b/planner.py`（変更）

LLM が `max_length=15` を破る場合の retry を 1 回入れる（調査レポート §1 の方針）。これにより Phase B 全体の reliability を維持しつつ、LLM 揺らぎを吸収:

```python
def plan_show(cleaned, *, client=None, temperature=0.5, max_tokens=4096,
              max_attempts: int = 2) -> ShowSpec:
    client = client or LLMClient.from_env()
    prompt = build_prompt(cleaned)
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = client.generate(prompt, ...)
            return parse_show_spec(raw)
        except ShowSpecParseError as exc:
            last_exc = exc
            logger.warning("Phase B attempt %d/%d failed: %s",
                           attempt, max_attempts, exc)
    raise last_exc  # 既存挙動互換: 最終的には ShowSpecParseError 伝播
```

設計判断: 既存 `max_attempts` のデフォルトは 2（初回 + 1 retry）に留める。Phase B が高コスト（~110 秒/コール、prompt ~25K tokens）なので過剰な retry を避ける。

### 2.4 `src/radio_director/models/verified_script.py`（変更）

```python
class SourceRef(BaseModel):
    url: HttpUrl
    title: str | None = None
    tier: Literal["AAA", "AA", "A", "B"] | None = None
```

`VerifiedScript` 自体の構造は変えない（`metadata: VideoMetadata` 内部に新フィールド追加されるだけ）。

### 2.5 `src/radio_director/models/video_metadata.py`（変更）

```python
class VideoMetadata(BaseModel):
    title: str
    thumbnail_title: str = Field(..., min_length=1, max_length=15)  # ← 追加
    description: str = Field(min_length=50, max_length=2000)
    hashtags: list[str] = Field(min_length=3, max_length=15)
    chapters: list[Chapter] = Field(min_length=2)
    references: list[SourceRef] = Field(default_factory=list)       # ← 追加
```

**循環 import 回避**のため、`SourceRef` は `models/video_metadata.py` 側に置き、`verified_script.py` から re-export する:

```python
# models/video_metadata.py
class SourceRef(BaseModel): ...
class Chapter(BaseModel): ...
class VideoMetadata(BaseModel): ...

# models/verified_script.py
from radio_director.models.video_metadata import SourceRef, VideoMetadata
```

### 2.6 `src/radio_director/phase_d/metadata_generator.py`（変更）

`generate_metadata` シグネチャを拡張し、`script` だけでなく `cleaned_research` と `citation_findings` を受け取る:

```python
def generate_metadata(
    script: Script,
    cleaned_research: CleanedResearch,
    citation_findings: list[CitationFinding],   # Phase D verifier から
    *,
    client: LLMClient | None = None,
    temperature: float = 0.5,
    max_tokens: int = 2048,
) -> VideoMetadata:
    # 既存: title/description/hashtags の LLM 生成（変更なし）
    parsed = ...

    # 既存: chapters の決定論計算（変更なし）
    chapters = build_chapters(script)

    # 新規: thumbnail_title を ShowSpec からコピー
    thumbnail_title = script.show_spec.thumbnail_title

    # 新規: references を実引用 source_idx から解決
    references = _resolve_references(citation_findings, cleaned_research)

    return VideoMetadata(
        title=parsed["title"],
        thumbnail_title=thumbnail_title,
        description=parsed["description"],
        hashtags=_clean_hashtags(parsed["hashtags"]),
        chapters=chapters,
        references=references,
    )

def _resolve_references(
    citation_findings: list[CitationFinding],
    cleaned_research: CleanedResearch,
) -> list[SourceRef]:
    """citation_findings から実引用された source_idx を抽出し、
    cleaned_research.sources からルックアップして SourceRef リストを生成。
    URL 重複は dedup。範囲外 source_idx は無視（warning は別途 verifier で発生済）。"""
    used_indices: list[int] = []
    seen: set[int] = set()
    for f in citation_findings:
        if f.source_idx is None or not f.is_consistent:
            continue
        if f.source_idx in seen:
            continue
        seen.add(f.source_idx)
        used_indices.append(f.source_idx)

    refs: list[SourceRef] = []
    seen_urls: set[str] = set()
    for idx in used_indices:
        if idx < 1 or idx > len(cleaned_research.sources):
            continue
        src = cleaned_research.sources[idx - 1]
        if src.url in seen_urls:
            continue
        seen_urls.add(src.url)
        refs.append(SourceRef(
            url=src.url,
            title=src.title,
            tier=src.domain_tier,
        ))
    return refs
```

**LLM コール追加なし**を保証（確定要件 §3.1 の Guardrail）。

### 2.7 `src/radio_director/phase_d/verifier.py`（変更）

`generate_metadata` 呼び出しに `cleaned_research` と `citation_findings` を渡す:

```python
metadata = generate_metadata(
    script,
    cleaned_research,
    citation_findings,
    client=client,
)
```

### 2.8 `src/radio_director/output/`（新規）

新規モジュール `output/` を作る。確定要件 §2.5 の責務を集約。

```
src/radio_director/output/
├── __init__.py
├── run_id.py                  # build_run_id(theme, now=None) -> str
├── writer.py                  # OutputWriter クラス
└── run_metadata.py            # build_run_metadata(...) -> dict
```

#### `output/run_id.py`

```python
import re
import unicodedata
from datetime import datetime

_SLUG_NON_ASCII = re.compile(r"[^a-z0-9-]+")
_SLUG_REPEATED_DASH = re.compile(r"-+")
SLUG_MAX_LEN = 40

def slugify(theme: str) -> str:
    """theme を ASCII slug に正規化。日本語は 'theme' にフォールバック。"""
    normalized = unicodedata.normalize("NFKD", theme)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_NON_ASCII.sub("-", ascii_only)
    slug = _SLUG_REPEATED_DASH.sub("-", slug).strip("-")
    return slug[:SLUG_MAX_LEN] or "theme"

def build_run_id(theme: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now.strftime('%Y-%m-%d_%H-%M')}_{slugify(theme)}"
```

設計判断（ユーザー承認済）: 日本語 theme は `'theme'` フォールバック + `_2`/`_3` 付与で吸収。`pykakasi` 等のローマ字化は v2 検討（YAGNI）。

#### `output/writer.py`

```python
from pathlib import Path
import json

DEFAULT_OUTPUT_ROOT = Path.home() / "radio_director" / "output"

class OutputWriter:
    def __init__(self, run_id: str, root: Path = DEFAULT_OUTPUT_ROOT):
        self.run_id = run_id
        self.root = root
        self.run_dir = self._resolve_unique_dir()
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "phase_logs").mkdir()

    def _resolve_unique_dir(self) -> Path:
        candidate = self.root / self.run_id
        if not candidate.exists():
            return candidate
        for n in range(2, 100):
            alt = self.root / f"{self.run_id}_{n}"
            if not alt.exists():
                return alt
        raise RuntimeError(f"too many run_id collisions for {self.run_id}")

    def save_json(self, name: str, payload: dict | BaseModel):
        path = self.run_dir / name
        if hasattr(payload, "model_dump_json"):
            path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        return path
```

#### `output/run_metadata.py`

```python
from datetime import datetime
from typing import Any

class PhaseMetric(TypedDict):
    model: str
    tokens_in: int
    tokens_out: int

def build_run_metadata(
    *, run_id: str, started_at: datetime, completed_at: datetime,
    phases: dict[str, PhaseMetric],
    verified_script_path: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_sec": int((completed_at - started_at).total_seconds()),
        "phases": phases,
        "verified_script_path": verified_script_path,
    }
```

### 2.9 E2E ランナー（新規）

統合の入口を新設する。Phase A→D の統合実行と output 保存を一気通貫させるエントリーポイントが必要。**`src/radio_director/runner.py`** を新規追加:

```python
def run_pipeline(
    research_brief_path: Path,
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    """Phase A->D を実行し、output/<run_id>/ に成果物を保存。
    返り値: output/<run_id>/ のパス。"""
    started_at = datetime.now()
    brief = ResearchBrief.model_validate_json(research_brief_path.read_text())
    run_id = build_run_id(brief.theme, now=started_at)
    writer = OutputWriter(run_id, root=output_root)

    cleaned = decode(brief)
    writer.save_json("cleaned_research.json", cleaned)

    show_spec = plan_show(cleaned)
    writer.save_json("show_spec.json", show_spec)

    script = conduct(show_spec)

    verified = verify(script, cleaned)
    writer.save_json("verified_script.json", verified)

    completed_at = datetime.now()
    writer.save_json("run_metadata.json", build_run_metadata(
        run_id=run_id, started_at=started_at, completed_at=completed_at,
        phases={...},  # phase ごとの prompt_chars/output_chars 概算
        verified_script_path="verified_script.json",
    ))
    return writer.run_dir
```

統合テストはこの runner を呼ぶ形で **新規追加**（既存統合テストは変更しない、§3 commit 9 参照）。

---

## 3. Commit 構成（粒度・順序）

確定要件 §3.5 の推奨 commit を踏襲しつつ、SourceRef を video_metadata.py に置く案に合わせて並び替え:

```
1. feat(models): VideoMetadata に SourceRef + thumbnail_title + references を追加
   ─ SourceRef を video_metadata.py に新設、verified_script.py から re-export
   ─ thumbnail_title (max_length=15), references (default_factory=list) を追加
   ─ AC: pytest 全 PASS（VideoMetadata の既存テストは default factory で通る）

2. feat(models): ShowSpec に thumbnail_title を追加
   ─ AC: pytest 全 PASS（既存 fixture/factories の更新含む）

3. feat(phase_b): プロンプトと JSON schema hint に thumbnail_title 出力指示を追加
   ─ prompt_builder.py の _TEMPLATE と _JSON_SCHEMA_HINT を更新
   ─ AC: test_prompt_builder.py に「プロンプトに thumbnail_title 文言が含まれる」
        テストを追加して PASS

4. feat(phase_b): planner に max_attempts=2 の retry を追加
   ─ thumbnail_title の max_length=15 違反を 1 回吸収する
   ─ AC: 新規 test_planner_retry.py で FakeLLMClient による retry 動作確認

5. feat(phase_d): generate_metadata で thumbnail_title をコピー、
   references を citation_findings から解決
   ─ verifier.py の呼び出しシグネチャ更新も含む
   ─ AC: 新規 test で SourceRef が実引用 source_idx のみを含むことを確認

6. test(phase_d): references 解決の境界テスト（0件 / 重複 / 範囲外）
   ─ test_metadata_generator.py に追加

7. feat(output): run_id 命名 + OutputWriter + run_metadata
   ─ src/radio_director/output/ を新設
   ─ AC: tests/output/ 新設、run_id 重複時 _2/_3 付与など境界網羅

8. feat(runner): Phase A->D 統合 runner を新設
   ─ src/radio_director/runner.py
   ─ AC: tests/test_runner.py で Mock LLM による E2E 動作確認

9. test(integration): runner ベースの実機 E2E テストを追加（env-gated）
   ─ 新規 tests/test_runner_integration_llm.py のみ追加
   ─ 既存 tests/phase_d/test_integration_llm.py は **そのまま残す**（Append-Only）
     重複統合は v2 別タスクで切り分け、本タスクでは冗長性を許容
   ─ AC: RADIO_DIRECTOR_INTEGRATION=1 で新規 runner テストが完走、
     output/<run_id>/ が 5 ファイル + phase_logs/ ディレクトリで生成
   ─ AC: 既存 Phase D 統合テストも引き続き PASS（無変更）

10. docs(reports): step1_research_report.md / step1_implementation_plan.md
    を docs/ に物理保存（本プランファイルから抽出して 2 分割）
    ─ 注: 本タスクの ExitPlanMode 直後に既に作成済み

11. docs(spec): interface_spec.md v1.7.0 / radio_director_design.md v1.6.0 を更新
    ─ 確定: ~/life-update-radio-specs/ 側を更新（§5 参照、ユーザー承認済み）
```

push は禁止。commit までで停止しユーザー手動 push。

---

## 4. テスト戦略

### 4.1 新規追加テスト

| テスト | 対象 | 確認内容 |
|---|---|---|
| `test_show_spec.py` 既存ファイル + | thumbnail_title | 1〜15 字 OK / 0 字 NG / 16 字 NG / 欠落 NG |
| `test_video_metadata.py` 新設 | SourceRef + VideoMetadata | HttpUrl 不正 NG、references 空 OK、tier Literal 検証 |
| `test_prompt_builder.py` 既存 + | プロンプト文言 | thumbnail_title 指示文 + JSON schema hint に含まれる |
| `test_planner_retry.py` 新設 | Phase B retry | FakeLLMClient で 1 回失敗→2 回目成功で OK、2 回連続失敗で例外 |
| `test_metadata_generator.py` 既存 + | references 解決 | 0 件 / 単一 / 重複 dedup / 範囲外 source_idx 無視 / tier コピー |
| `tests/output/test_run_id.py` 新設 | run_id 命名 | フォーマット / theme_slug 変換 / 40 字制限 / 日本語フォールバック |
| `tests/output/test_writer.py` 新設 | OutputWriter | ディレクトリ作成 / phase_logs/ 作成 / 重複時 _2 付与 |
| `tests/output/test_run_metadata.py` 新設 | run_metadata 構築 | スキーマ一致 / duration_sec 計算 |
| `tests/test_runner.py` 新設 | runner.run_pipeline | Mock LLM で 5 ファイル + phase_logs/ が生成 |
| `tests/test_runner_integration_llm.py` 新設（env-gated） | runner.run_pipeline | 実機 LLM で end-to-end 完走、output 構造検証 |

### 4.2 既存テストの破壊チェック

- `test_show_spec.py` の **既存 ShowSpec 構築呼び出しに `thumbnail_title` を追加**する必要あり（`Field(...)` で必須化のため）。各テストファイルの `_factories.py` で一括対応。
- `test_video_metadata.py` 既存（あれば）の VideoMetadata 構築も `thumbnail_title` 追加。
- `test_metadata_generator.py` の `_VALID_PAYLOAD` に `thumbnail_title` の Pydantic 経路（LLM 経由ではなく ShowSpec から直接コピーされる）を再現するため、テスト構築時に show_spec 側へ thumbnail_title を入れる。
- 既存 `tests/phase_d/test_integration_llm.py` は **無変更で残す**（Append-Only 哲学、§3 commit 9）。

### 4.3 統合テスト

確定要件 §4.2 の「~4 分 ±20% 以内」「ハルシネーション False Positive 0%」を維持。既存 Phase D 統合テスト 228 秒の 20% 内（~273 秒）。新規 retry によるリスクは Phase B が 1 回失敗すると +110 秒程度遅延するが、±20% に収まる前提（実機検証で確認）。

新規 runner 統合テストと既存 Phase D 統合テストは並走で実機ランするため、本タスクでは合計実機ラン時間が増える。重複統合は v2 別タスク。

---

## 5. 確定要件との矛盾フラグ

### ⚠️ 矛盾 1: docs パスの不一致

**確定要件 §4.4**:
> `~/radio_director/docs/interface_spec.md` を v1.7.0 に更新
> `~/radio_director/docs/radio_director_design.md` を v1.6.0 に更新

**実態**: 仕様書 2 ファイルは `~/life-update-radio-specs/`（別リポジトリ）に存在。`~/radio_director/docs/` には `auto_radio_generator_analysis.md` のみ（本タスクで step1_research_report.md / step1_implementation_plan.md が追加されるが仕様書ではない）。

**確定: A** — `~/life-update-radio-specs/` 側を更新（指示書の `~/radio_director/docs/...` パスは typo 扱い）。**ユーザー承認済み**（プランレビュー時の質問に対する回答）。SSOT を維持し research_pipeline 等の他リポジトリとの仕様共有を保つ。

### ⚠️ 矛盾なし（確認済）

確定要件 §2.1〜§2.5、§3、§4 はいずれも実装可能。

---

## 6. リスクと回避策

| # | リスク | 影響 | 回避策 |
|---|---|---|---|
| 1 | LLM が `thumbnail_title` 15 字を頻繁に超過 | Phase B retry で吸収可能 | プロンプトに「機械的切り詰め禁止、独立して意味が通る短縮」を強調。実機 1 ランで観察 |
| 2 | 既存 fixture (`show_spec_sample.json`) に `thumbnail_title` 欠落 | Phase D テストが ValidationError | fixture を 1 度 LLM で再生成 OR `_factories.py` で動的補完 |
| 3 | `SourceRef.url` の HttpUrl 検証で既存実機 sources の URL が弾かれる | references 空になる | research_brief_sample.json の URL 全件で `HttpUrl` 検証する単体テストを先に用意 |
| 4 | `slugify` で日本語 theme が全て 'theme' に潰れて run_id 重複多発 | 出力ディレクトリ衝突頻発 | 暫定: 重複時 `_2/_3` 付与で吸収。v2 で `pykakasi` 等のローマ字化を検討 |
| 5 | Phase D verifier の戻り値変化なし（VerifiedScript 型は同一）→ Windows 側互換 OK | — | 既存 Phase D 統合テストの assertion がそのまま通る |
| 6 | `output/` ディレクトリ書き込みが既存の git status を汚す | リポジトリ衛生 | `.gitignore` に `output/` 追加 |
| 7 | docs パスの矛盾（解決済み、§5） | docs 更新先が不明 | **ユーザー承認で `~/life-update-radio-specs/` 側を更新する確定** |
| 8 | run_metadata.json のトークン数を chars/2 概算で記録すると、実機 token 数と乖離 | 集計値の信頼性低下 | コメントで「概算」と明記。v2 で `tiktoken` 等の依存追加を検討（YAGNI） |
| 9 | 既存 Phase D 統合テストと新 runner 統合テストの二重メンテナンス | 保守コスト増 + 実機 LLM ラン時間増 | **本タスクでは冗長性を許容**（Append-Only 哲学）。重複統合は v2 別タスクで切り分けて検討 |

---

## 7. 工数見積もり

| フェーズ | 内容 | 想定時間 |
|---|---|---|
| 実装 | models 変更 (§2.1, .4, .5) | 30 分 |
| 実装 | Phase B 変更 (§2.2, .3) | 45 分 |
| 実装 | Phase D 変更 (§2.6, .7) | 60 分 |
| 実装 | output/ モジュール (§2.8) | 60 分 |
| 実装 | runner (§2.9) | 45 分 |
| ユニットテスト | 11 件追加 + fixture 更新 | 90 分 |
| 統合テスト | 新規 runner 統合追加 + 実機実行 | 90 分（実機 LLM 280 秒 × 2-3 ラン含む） |
| docs | step1_research_report / step1_implementation_plan は ExitPlanMode 直後に保存済 | (済) |
| docs | interface_spec / radio_director_design 更新 | 30 分 |
| バッファ | デバッグ・予期せぬ事態 | 60 分 |
| **合計** | — | **約 8.5 時間（1 営業日内）** |

確定要件は 4 分 ±20% を維持要求 → 統合テストで実測必須。

---

## 8. 完了基準

- 確定要件 §4.1 機能要件 4 項目すべて満たす
- 確定要件 §4.2 品質要件（既存テスト + 新規テスト全 PASS、E2E 実機 4 分 ±20%、False Positive 0%）満たす
- 確定要件 §4.3 テスト要件のリスト網羅
- 確定要件 §4.4 ドキュメント更新（§5 矛盾解決済み）
- 11 commit すべて作成、push なし
- `~/radio_director/docs/step1_research_report.md` と `step1_implementation_plan.md` が untracked で存在（本タスクの ExitPlanMode 直後に作成済み）
- アーキテクト（ユーザー）レビュー受領まで停止

---

**END**

実装フェーズへの遷移はアーキテクトのレビュー後。本ファイルは実装中に必要に応じて更新（履歴管理）。

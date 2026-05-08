# Step 1 改修 — 事前調査レポート

**版数:** 1.0
**作成日:** 2026-05-09
**対象タスク:** radio_director Step 1 改修（VerifiedScript SSOT 化）
**依拠指示書:** `step1_radio_director_instructions.md` / `step1_research_and_plan_instructions.md`
**対応プラン:** `step1_implementation_plan.md`（兄弟ファイル）

---

## Context

auto-radio-generator (Windows 側) への引き渡しを「VerifiedScript 1 ファイル」に集約するため、`thumbnail_title` 追加・`references` 解決・出力ディレクトリ整備を行う。本レポートは指示書 `step1_research_and_plan_instructions.md` §3 が要求する事前調査の結果をまとめる。実装プランは別ファイル `step1_implementation_plan.md` に分離した。

---

## 1. Phase 別 LLM 構造化出力方式

| Phase | LLM | 方式 | 生成型 | リトライ |
|---|---|---|---|---|
| **Phase A** | 不使用 | — | — | — |
| **Phase B** | 1 コール | JSON mode (vLLM guided decoding) → 手動 JSON parse → Pydantic v2 `ShowSpec.model_validate(obj)` | ShowSpec | **無し**（v1 方針、parser.py:5 コメント明記） |
| **Phase C** | 5 コール | 同上、`{turns: [...]}` のみ受け取り、`ScriptSegment(...)` を呼び出し側で組み立て | ScriptSegment | 3 attempts + fallback (segment_generator.py:65) |
| **Phase D** | 1 コール | 同上、metadata_generator.py で title/description/hashtags のみ生成、chapters は決定論計算 | VideoMetadata | **無し** |

**重要**: Instructor / OpenAI structured outputs / Anthropic tool use は **使用していない**。一貫して「LLM が JSON テキスト出力 → 手動 parse → Pydantic validate」のパターン。`thumbnail_title` 追加もこのパターンに沿わせる（既存方式に揃え、新ライブラリ導入禁止）。

**JSON 抽出ヘルパは共通化されていない**: `_strip_think_tags` / `_strip_code_fences` / `_extract_first_json_object` / `_try_load_json` が `phase_b/parser.py:18-73` と `phase_d/metadata_generator.py:23-160` に重複定義されている。**今回スコープ外**（共通化はリファクタ別件で）。

**ValidationError 処理**:
- Phase B: parser 層が `ShowSpecParseError` に包んで raise（リトライ無し）
- Phase C: `segment_generator.py` が retry → 失敗時 fallback テンプレート
- Phase D: `metadata_generator.py:58-61` で `MetadataGenerationError` に包む（リトライ無し）

→ `thumbnail_title` の `max_length=15` 違反は **Phase B parser で `ShowSpecParseError`** として伝播。実装プラン側では「Phase B 自体に retry を持たせる」ではなく、**呼び出し側 (`planner.py`)** で 1 回だけ retry 可能にする小さな変更を入れる（実装プラン §B.2.3 で詳述）。

---

## 2. cleaned_research.json と research_pipeline 連携

**現状**:
- `~/research_pipeline/` (別リポジトリ) は **`research_brief.json` のみを出力** (`/Users/tada/research_pipeline/output/research_brief_*.json`)。`structured_facts` を含む。
- `cleaned_research.json` は radio_director が Phase A で生成する **内部 artifact**。research_pipeline は読まない。
- 現在 radio_director の **本番コードはディスクに何も書いていない**（in-memory のみ）。テスト fixture (`tests/data/show_spec_sample.json`) は手動保存。

**判定: 統合可否 = Yes（無条件）**:
- `~/radio_director/output/<run_id>/cleaned_research.json` に書き出しても research_pipeline 契約に影響なし
- research_pipeline → radio_director の入力経路は `research_brief.json` のみ。出力側は触らない
- 既存コードに保存先を持つ箇所が無いので破壊的変更なし

**設計上の留意**:
- `cleaned_research.json` は Mac Studio 側のローカル audit log 扱い（指示書 §2.5）
- Windows 側 loader は **絶対に読まない**（VerifiedScript SSOT 原則）

---

## 3. 既存実装の前提情報

### 3.1 ディレクトリ・ファイル構成

```
~/radio_director/
├── pyproject.toml                  pydantic>=2.5, requests>=2.31, pytest>=8.0
├── src/radio_director/
│   ├── models/                     research_brief, cleaned_research, show_spec,
│   │                               script, video_metadata, verified_script
│   ├── phase_a/  decoder, quality_gate
│   ├── phase_b/  llm_client, prompt_builder, parser, planner
│   ├── phase_c/  prompt_builder, parser, segment_generator, conductor
│   └── phase_d/  number_extractor, hallucination_detector,
│                 citation_normalizer, metadata_generator, verifier
├── tests/
│   ├── data/                       research_brief_sample.json,
│   │                               show_spec_sample.json (fixture)
│   ├── phase_a/  test_decoder, test_quality_gate, test_research_brief, ...
│   ├── phase_b/  test_show_spec, test_prompt_builder, test_parser,
│   │             test_integration_llm
│   ├── phase_c/  test_script, test_prompt_builder, test_parser,
│   │             test_segment_generator, test_integration_llm
│   └── phase_d/  test_number_extractor, test_hallucination_detector,
│                 test_citation_normalizer, test_metadata_generator,
│                 test_verifier, test_integration_llm
└── docs/
    └── auto_radio_generator_analysis.md   ← 既存ドキュメント 1 件のみ
```

`output/` ディレクトリは **存在しない**（新規作成）。

### 3.2 コスト・トークン計測

- 現状: `logger.info()` で `prompt_chars`, `output_chars`, `approx_tokens` (chars/2)、`elapsed_sec` をログ出力
- per-API コスト計算機構は **無し**（vLLM ローカル運用のためコスト概念希薄）
- → `run_metadata.json` の `phases.{phase}.tokens_in/tokens_out` は **chars/2 概算で十分**（指示書 §5.3 と整合）

### 3.3 Pydantic v2 / pytest の前提

- Pydantic 2.5+。`Field(min_length=..., max_length=...)`、`HttpUrl`、`Literal[...]` 利用可能
- pytest 8+。`tests/data/*.json` を fixture として既に活用
- 既存テスト数 **127 件全 PASS**、3 件 env-gated 統合テスト

### 3.4 ResearchSource の url 型

- `src/radio_director/models/research_brief.py` の `ResearchSource.url: str`（**`HttpUrl` ではなく素の `str`**）
- 確定要件は `SourceRef.url: HttpUrl` を要求 → loader (Phase D) で str → HttpUrl に変換時に Pydantic が validate（不正 URL は弾く）

---

## 4. 主要参照箇所インデックス

| 用途 | パス + 行 |
|---|---|
| ShowSpec 定義 | `src/radio_director/models/show_spec.py:30-39` |
| VideoMetadata 定義 | `src/radio_director/models/video_metadata.py:17-21` |
| VerifiedScript 定義 | `src/radio_director/models/verified_script.py:46-50` |
| ResearchSource 定義 | `src/radio_director/models/research_brief.py` の `ResearchSource` |
| CleanedResearch 定義 | `src/radio_director/models/cleaned_research.py:65-73` |
| Phase B prompt template | `src/radio_director/phase_b/prompt_builder.py:20-72` |
| Phase B JSON schema hint | `src/radio_director/phase_b/prompt_builder.py:74-97` |
| Phase B parser | `src/radio_director/phase_b/parser.py:26-50` |
| Phase B planner (retry なし) | `src/radio_director/phase_b/planner.py:17-51` |
| Phase D verifier | `src/radio_director/phase_d/verifier.py:35-87` |
| Phase D metadata_generator | `src/radio_director/phase_d/metadata_generator.py:31-61` |
| Phase D citation_normalizer (source_idx 解決) | `src/radio_director/phase_d/citation_normalizer.py:42-103` |
| Phase B integration test | `tests/phase_b/test_integration_llm.py` |
| Phase D integration test | `tests/phase_d/test_integration_llm.py` |

---

## 5. 主要発見の要約

1. **構造化出力は手動 JSON parse + Pydantic validate のみ**。Instructor 等の追加ライブラリは無い。`thumbnail_title` 追加もこの方式に揃える。
2. **既存コードは output/ にディスク書き込みをしていない**。新規 `output/<run_id>/` 機構を導入しても破壊的変更ゼロ。
3. **research_pipeline は cleaned_research.json を読まない**。統合可否は無条件 Yes。
4. **JSON parse ヘルパが phase_b と phase_d で重複定義**されているが、本タスクは共通化スコープ外。リファクタ別件として記録。
5. **指示書 §4.4 の docs パス (`~/radio_director/docs/interface_spec.md`) は typo**。実体は `~/life-update-radio-specs/` にある。確定要件矛盾フラグとして実装プラン §B.6 に記載。

---

**END**

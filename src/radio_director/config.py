"""radio_director の Step 7 品質ガード config 定数。

すべての閾値は本ファイルに外出し。プロダクション運用中の再キャリブレーション
は本ファイルだけで完結する (コード変更不要)。

関連: ~/research_pipeline/.investigations/2026-05-12-quality-investigation.md
"""

from __future__ import annotations

# ─── Phase B (C2): research_content の数値プレースホルダ置換 ───────────────
# Pass2 由来の捏造数値が Phase B 経由で ShowSpec.key_claims に転用される事象を
# 観測 (barefoot brief 「膝衝撃 15-20% 減少」が ZICO Trust [src=8] に帰属)。
# research_content を Phase B prompt に注入する直前に数値表現を placeholder
# 化することで、Phase B LLM が structured_facts (上記「主要な事実」) からのみ
# 数値を引用するよう誘導する。
PHASE_B_STRIP_NUMBERS: bool = True
PHASE_B_STRIP_PLACEHOLDER: str = "[出典の数値]"

# ─── Phase B (C5): prompt サイズガード ──────────────────────────────
# ファクトが豊富なテーマで Phase B prompt が 53k chars に達し proxy が
# 400 Bad Request を返す事象を観測 (diabetes2 brief)。閾値超過時に
# structured_facts を confidence 順に上位 K 件のみ採用、warning ログ +
# ShowSpec.metadata.facts_truncated を立てる。
PHASE_B_PROMPT_CHAR_LIMIT: int = 40000
PHASE_B_FACTS_TOP_K: int = 30

# ─── Phase D (C1): production gate (soft gate, 1 retry, hard fail) ──────
# verified_script.json が matched_ratio 0% でも保存されていた事象を修正。
# 閾値未満なら Phase B/C を retry、それでも未満なら hard fail し
# verified_script.failed.json に保存。
PHASE_D_MATCHED_RATIO_GATE: float = 0.30
PHASE_D_RETRY_ENABLED: bool = True
PHASE_D_RETRY_MAX: int = 1

# ─── Phase D (C4): _is_highly_specific 拡張 + unmatched を fp_candidate に ─
# 既存閾値 (小数3桁以上 / 100万以上整数) では n=1,250 / 15% / OR=0.85 等の
# 現実的な医学・統計数値が全て素通りし false_positive_candidates が常にゼロ。
PHASE_D_HS_MIN_INTEGER: int = 100
PHASE_D_HS_MIN_DECIMAL_PLACES: int = 1
PHASE_D_HS_INCLUDE_PERCENT: bool = True
PHASE_D_HS_INCLUDE_STATISTIC_NOTATION: bool = True

# unmatched_number warning を発した数値を false_positive_candidates にも積む。
# 現状 false_positive_candidates は highly_specific_unmatched と同じだが、
# このフラグを有効化すると unmatched 全件が candidate になる。
PHASE_D_UNMATCHED_AS_FP_CANDIDATE: bool = True


# ─── Phase D (C3 / Step 8): source attribution validator ──────────────────
# Phase B が生成した key_claims の source_idx が「実際にその数値・固有名詞を
# 含むソース」を指しているかを deterministic にチェック。
# Step 7 で C2 が research_content の直接転用は塞いだが、Phase B が
# 当てずっぽうで source_idx を割り当てる挙動 (barefoot で ZICO Trust に医学
# 統計を帰属) を deterministic に検出する。
C3_ENABLE: bool = True
# 数値の近似マッチ許容範囲 (%) — "15%" vs "14.5%" を整合とみなす
C3_NUMBER_TOLERANCE_PCT: float = 5.0
# 固有名詞のミスマッチは warning にするか (False = 数値のみ judge、緩い)
C3_REQUIRE_ENTITY_MATCH: bool = False


# ─── Phase D (P1 / Step 8 v2): 数値マッチャーのトークン化正規化 ──────────
# "1000 億" (script) と "1000億パラメータ" (structured_facts) のような
# スペース・単位の違いだけで unmatched 判定される事象を 2026-05-13 exo 本運用
# で観測。比較前に全角→半角・スペース除去・カンマ除去・日本語単位剥がしを
# 両側に適用する。
PHASE_D_NUMBER_NORMALIZATION_ENABLED: bool = True
# 比較時に剥がす日本語単位の語 (% / 倍 は単位として保持、これらは「数の名前」)
PHASE_D_NUMBER_STRIP_UNITS: tuple[str, ...] = (
    "パラメータ",
    "件",
    "名",
    "個",
    "台",
    "本",
    "匹",
    "部",
    "回",
    "箇所",
    "施設",
    "種類",
    "年",
    "月",
    "日",
    "時間",
    "分",
    "秒",
    "円",
    "ドル",
    "ユーロ",
)

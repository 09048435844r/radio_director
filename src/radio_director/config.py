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

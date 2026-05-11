"""3 topic 間の内容範囲重複 (source_idx 共有率) を決定論的に検出する。

backlog §7-B、2026-05-11: 本運用 6 件のうち 2 件で 3 topic が同じ source_idx
ばかりを共有する病的重複 (Jaccard 最大 = 1.0) が観測された。Phase B のプロンプト
強化 (§7-A) と 2 段構えで、Phase D で決定論的に検出する。

検出ロジック:
1. 各 topic の key_claims から source_idx を抽出
2. 範囲外 (1 ≤ idx ≤ len(sources) を満たさない) source_idx は除外
   (citation_normalizer が unknown_source_idx で別途 warning するため、
   ここで「未解決 source_idx の共有」を false-positive として拾わない)
3. 全 topic ペア (n_topics C 2) の Jaccard 係数を計算
4. 最大値が JACCARD_THRESHOLD (0.5) を超える場合に 1 件の warning を発出。
   message にはワーストペアの index / 共有 source_idx リスト / Jaccard 値を含める

v1 は警告のみで自動修正なし。LLM コール禁止 (Phase D 決定論寄りの Guardrail §3.1)。

閾値 0.5 の根拠 (実機 6 件分析):
  2026-05-09_11-25 (sleep)        : 0.000 -> clean
  2026-05-09_21-58 (codex)        : 1.000 -> 病的、warn
  2026-05-09_22-05 (codex)        : 0.000 -> clean
  2026-05-10_08-49 (codex)        : 0.000 -> clean
  2026-05-10_18-55 (rinse)        : 1.000 -> 病的、warn
  2026-05-11_07-22 (rinse, PR1)   : 0.333 -> 軽微 (false positive 回避)
"""

from __future__ import annotations

from itertools import combinations

from radio_director.models.cleaned_research import CleanedResearch
from radio_director.models.script import Script
from radio_director.models.verified_script import VerificationWarning

JACCARD_THRESHOLD = 0.5


def check_topic_overlap(
    script: Script, cleaned_research: CleanedResearch
) -> list[VerificationWarning]:
    """ShowSpec.topics 間の source_idx 共有率を Jaccard で測り、閾値超過なら警告を返す。

    範囲外 (1 ≤ idx ≤ len(sources)) の source_idx は集合計算前に除外する。
    citation_normalizer の unknown_source_idx 警告と二重に「同じ未解決 source を
    共有している」false-positive を発生させないため。
    """
    topics = script.show_spec.topics
    if len(topics) < 2:
        return []

    n_sources = len(cleaned_research.sources)
    topic_sources: list[set[int]] = []
    for t in topics:
        resolved = {
            c.source_idx
            for c in t.key_claims
            if 1 <= c.source_idx <= n_sources
        }
        topic_sources.append(resolved)

    worst_pair: tuple[int, int] | None = None
    worst_jaccard = 0.0
    worst_shared: set[int] = set()

    for i, j in combinations(range(len(topics)), 2):
        a, b = topic_sources[i], topic_sources[j]
        union = a | b
        if not union:
            continue  # 両方とも空 (全 source 未解決) は重複扱いしない
        inter = a & b
        jaccard = len(inter) / len(union)
        if jaccard > worst_jaccard:
            worst_jaccard = jaccard
            worst_pair = (i, j)
            worst_shared = inter

    if worst_pair is None or worst_jaccard <= JACCARD_THRESHOLD:
        return []

    i, j = worst_pair
    title_i = topics[i].title[:30]
    title_j = topics[j].title[:30]
    shared_str = ",".join(str(x) for x in sorted(worst_shared))
    return [
        VerificationWarning(
            code="topic_overlap_warning",
            message=(
                f"topic[{i}]「{title_i}」と topic[{j}]「{title_j}」の "
                f"source_idx 重複率 Jaccard={worst_jaccard:.2f} (>{JACCARD_THRESHOLD}) "
                f"です。共有 source_idx: [{shared_str}]。"
                "Phase B プロンプトで各 topic が独立した切り口を持つよう指示してください。"
            ),
            location=f"topic_pair[{i}_x_{j}]",
        )
    ]

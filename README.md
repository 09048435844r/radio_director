# radio_director

新台本生成パイプライン (Mac Studio)

## 概要

`auto_radio_generator` (Windows) のゼロベース再設計版。
Mac Studio 上で動作し、研究パイプライン (research_pipeline) の
`structured_facts` を直接消費して台本を生成する。

## 設計仕様

- [life-update-radio-specs/radio_director_design.md](https://github.com/09048435844r/life-update-radio-specs/blob/main/radio_director_design.md)
- [life-update-radio-specs/interface_spec.md](https://github.com/09048435844r/life-update-radio-specs/blob/main/interface_spec.md)

## アーキテクチャ

- Phase A: リサーチ品質層（決定論的）
- Phase B: 番組企画（1 LLMコール）
- Phase C: 対話生成（並列 LLMコール）
- Phase D: 品質ゲート

## ステータス

開発中（Phase A プロトタイプ実装着手）

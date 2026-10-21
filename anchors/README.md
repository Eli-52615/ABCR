# anchors/ —— 仓级外部信任根（规范锚存储）

- 唯一规范锚文件：`anchors/seals.jsonl`（append-only，一行一 JSON 锚记录）。
- 读写只经 `abcr.common.external_seal`：生产端收口 `seal(...)`，验证端 `verify(...)`
  **只读本路径这一处**，不做任何多路径搜索——影子锚文件零影响。
- 记录形状：`{ts, kind, subject_id, digest, length, extra}`；同 (kind, subject_id)
  以最后一条为准（重封=覆盖语义）。
- 纪律：本目录 git 跟踪；**只追加、绝不改写/删除既有行**；测试一律用
  `ABCR_ANCHOR_STORE` 环境变量把存储隔离到临时目录，不得污染本文件。
- kind 约定：`step_chain`（steps.jsonl，subject=run_id）、`ledger_chain`
  （ledger 五链，subject=链名）；其余 kind 由各消费组自定。

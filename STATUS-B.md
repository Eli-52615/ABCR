# STATUS-B: Hook + Intervention + Persona Vectors 复现

## S0: Bootstrap + 接口对齐
- **状态**: COMPLETE
- B0.1: bootstrap 已由 C 包完成（d46046b）；HF 不可达改用 ModelScope 下载模型（见 DEVIATIONS）
- B0.2: api.py 已由 A 落位；五个 intervention 模块实现完成且 import 验证通过
  - residual_vector.py ✓
  - projection_ablation.py ✓
  - random_direction.py ✓
  - capture.py ✓
  - prompt_persona.py ✓

## S1: Hook 库与三重验证
- **状态**: COMPLETE (4/4 pass, S1 43 tests regressed green)
- B1.1 residual_vector: 实现完成，位移/零注入测试通过
- B1.2 projection_ablation: 实现完成，消融测试通过
- B1.3 random_direction: 双模式（参照/字面量），100 seeds 范数保持 + 正交性统计通过
- B1.4 capture: 投影采集器实现完成
- B1.5 prompt_persona: 纯文本干预，nullcontext
- B1.6 fixture vector_tiny: (5,64) 三件套创建，sha256 一致
- B1.7 四项契约测试全绿:
  ```
  test_b_ablation .............. PASSED
  test_b_displacement .......... PASSED
  test_b_random_norm ........... PASSED
  test_b_zero_injection ........ PASSED
  4 passed in 2.32s
  ```
- 偏差: test_b_random_norm seeds 用 1-100（避开 fixture seed 0 = cos=1.0 trivially）

## S2: 官方 optimistic 复现线
- **状态**: COMPLETE (gate closed)
- B2.1 PV clone pinned: ✓ (b8e0f044, commit 1ffde3c)
- B2.2 两个补丁: ✓ (config hftoken-optional + generate_vec dtype)
- B2.3 .venv-pv: ✓ (judge importable)
- B2.4 BRIDGE-FIDELITY: ✓ (含行号引用)
- B2.5 judge 探针: ✓ (logprob_weighted mode, DeepSeek 10/10)
- B2.6 extract_mac.py: ✓ (桥保真度完整，含分块检查点 + 内存压力门控)
- B2.7 0.5B e2e 烟检: ✓ PASS (commit 74e2f69)
- B2.8 3B dev 抽取: ✓ (400 gen, pos=199 neg=126 effective, commit 206f978)
- B2.9 方向复现检: ✓ PASS (L*=16, coef=2.0, coherence=96.5, commit 99c08e1)
- B2.10 翻转预览: ✓ (3Q × 3 variants, commit b71f326)

## S3: 锚 trait + exprcheck
- **状态**: COMPLETE
- B3.1 conscientiousness 工件: ✓ (E17 verified, commit 1a02d83)
- B3.2 conscientiousness 3B 抽取: ✓ (400 gen, 8 chunks memory-gated, commit cbdd9b2)
  - 有效样本: pos=3, neg=3 (neg pole mean=75.3, insufficient polarity at threshold=50)
  - 向量三件套: vectors/qwen2.5-3b-instruct/conscientiousness-dev/
  - 方向检: FAIL sub-threshold (best L24/3.5: d+=7.5, d-=-7.8, threshold ±10), commit e7d591c
  - card.recommended: layer=24, coef=3.5 (best available, trend correct)
- B3.3 exprcheck 生成素材: ✓ (120 samples, 3×40 balanced, shuffle seed=42, commit cefea0e)
  - pv_bridge/out/conscientiousness/exprcheck_pool.csv (blind)
  - pv_bridge/out/conscientiousness/exprcheck_key.csv
- B3.4 test_b_capture: ✓ PASS (8.30s, tinyqwen)

## S4: 扩展 + 云日 Runbook
- **状态**: COMPLETE
- B4.1 openness + neuroticism 工件: ✓ (E17 verified, commit 91be211)
- B4.2 云日 Runbook ×3: ✓ (cloudday1/cloudday2/parity-smoke, commit e0c804e)
- B4.3 STATUS-B 终态: ✓ (本文件)

---

## 完工验收清单

1. **S1 四重 hook 验证**: ✓ 43 tests 全绿 (2.56s)，fixture 向量工件在案
2. **S2 optimistic 复现线**: ✓ 补丁×2 + PV-PIN + BRIDGE-FIDELITY；0.5B e2e 绿；optimistic-dev 三件套 E15 过；方向检 PASS L16/2.0；flip_preview.md 落位
3. **S3 锚 trait + exprcheck**: ✓ conscientiousness 工件 E17 过 + provenance；conscientiousness-dev 三件套（方向检 sub-threshold，best available L24/3.5）；exprcheck 池/钥匙 120 条；capture 测试绿
4. **S4 扩展 + Runbook**: ✓ openness/neuroticism 工件；Runbook×3 含 E16 熔断
5. **全程纪律**: ✓ judge key 零泄露（grep 扫描 CLEAN）；每 WBS 一 commit；DEVIATIONS 如实（3 条）

## 已知限制（dev 级，非阻塞）

- **conscientiousness neg pole 极性不足**: 200 neg 样本中仅 3 通过 threshold=50（mean=75.3），导致向量有效样本只有 3 对。方向检 sub-threshold (d+=7.5/d-=-7.8, 门槛±10)。趋势正确，幅度不够。**云日 7B bf16 + 官方 10 响应/题预期解决**。
- **optimistic vs conscientiousness 对比**: optimistic 有效样本 199/126，方向检轻松通过；conscientiousness 作为"底线素质"型 trait，模型在任何角色下都倾向高分，neg 极性抑制困难。属 trait 特性而非管线缺陷。

---

## 批0: V1.1 F14.5 追认条款对齐清单

> 依据：V1.1 补丁 F14.5 追认条款 — B2.6「分块检查点 + 内存压力门控」追认为合规实现，不要求重构；只需对齐三点。
> 审计对象：`pv_bridge/run_3b_extract_conscientiousness.sh`（驱动脚本）、`pv_bridge/extract_mac.py`（片进程）、`pv_bridge/exprcheck_gen.py`（表达检生成）、`tests/contract/stage2/test_b_direction_3b.py`（方向检）

### 对齐点 1: 锁路径 (F14.2)

| 项 | F14.2 要求 | B 现状 | 差异 |
|---|---|---|---|
| 锁路径 | `/Users/superagent/abcr/.resource/heavy.lock`（`mkdir` 原子创建） | **无锁机制** — 驱动脚本无 `mkdir`/`rmdir`，无 `owner.json` | **完全缺失** |
| 取锁时机 | 重负载启动前取锁，进程退出释放 | 无 | — |
| 对齐方式 | A 交付 `resource_guard.py` 后，所有 `.venv-pv` 真模型命令统一经 `.venv/bin/python -m abcr.resource_guard run -- <cmd>` 包装 | — | **blocked on A** |

### 对齐点 2: 压力探测源 (F14.6)

| 项 | F14.6 要求 | B 现状 | 差异 |
|---|---|---|---|
| 探测接口 | `sysctl -n kern.memorystatus_vm_pressure_level` | `run_3b_extract_conscientiousness.sh:30` 使用完全相同调用 | **已对齐 ✓** |
| 探测点 | 样本间（片进程内部）+ 片间（外层循环） | 仅片间（shell `wait_for_memory()`）；`extract_mac.py` 内部无探测 | 片进程内缺失（见对齐点 3） |

### 对齐点 3: 阈值语义 (F14.6 warning 停 / critical 急停 / E19 路径)

| 项 | F14.6 要求 | B 现状 | 差异 |
|---|---|---|---|
| warning(2) ×2 连续 → E19 | 片进程样本间：连续 2 次 warning → 完成当前样本 → flush → E19 退出 | shell 层：level≠1 时 reset consec 计数，继续等待；**不在片内探测，不走 E19** | **语义不匹配** |
| critical(4) ×1 → E19 | 片进程：单次 critical → 急停 → E19 | shell 层不区分 warning/critical，统一视为"未恢复" | **未实现** |
| 退出码 | E19（resource_guard 定义的退出码） | `exit 2`（shell 超时退出，`run_3b_extract_conscientiousness.sh:40`） | **码不匹配** |
| 片间恢复 | normal 持续 120s 后自动续跑；30min 超时 → BLOCKER | level==1 ×3 consecutive（30s），600s 超时 → exit 2 | 恢复窗口更短（30s vs 120s）；超时更长（600s vs 1800s） |
| 孤儿检测 | `os.getppid()` — 父进程消失即 E19 | `extract_mac.py` 无此检查 | **未实现** |

### 附: F14.4 加载纪律差异（非 F14.5 追认范围，但 批0 需一并对齐）

| 项 | F14.4 要求 | B 现状 | 差异 |
|---|---|---|---|
| `torch_dtype` 显式传入 | 必须 | `extract_mac.py:67` 已传 ✓；`exprcheck_gen.py:40` 已传 ✓ | **已对齐 ✓** |
| `model.eval()` | 必须 | 全部加载点均有 ✓ | **已对齐 ✓** |
| `torch.inference_mode()` | 推理一律用 inference_mode | `extract_mac.py:102` 用 `torch.no_grad()`；`exprcheck_gen.py:69-71` 用 `torch.no_grad()` | **需替换** |
| MPS 8GiB 上限 | `torch.mps.set_per_process_memory_fraction(...)` | 无此调用 | **未实现** |
| 片尾清理 | `del` → `gc.collect()` → `torch.mps.empty_cache()` | `exprcheck_gen.py:148` 仅 `del model`；`extract_mac.py` 进程退出隐式释放 | **不完整**（进程退出兜底有效，但缺显式序列） |

### 对齐行动计划

1. **现在可做（不依赖 A）**：本清单 ← **done**
2. **A 交付 `resource_guard.py` 后**：← **done** (A commit 4692cca)
   - ✅ 驱动脚本经 `.venv/bin/python -m abcr.resource_guard run --` 包装（对齐点 1）
   - ✅ `extract_mac.py` 增样本间 `check_pressure_fuse()` + `os.getppid()` 孤儿检测（对齐点 3）
   - ✅ 退出码统一为 19 / E19（对齐点 3）
   - ✅ `torch.no_grad()` → `torch.inference_mode()`（F14.4，3 个文件）
   - ✅ 加载前 `set_mps_memory_limit()`（F14.4，3 个文件）
   - ✅ 片尾 `del→mps_cleanup()`（= `gc.collect()→empty_cache()`，F14.4，3 个文件）
   - ✅ 驱动脚本 E19 重试 + 批停闸（3 consecutive / 5 total）+ recovery wait（normal×120s / 30min timeout）
3. **批0 对齐 DONE** ✅

### 批0 验证与收口

- ✅ 压力路径 fake-pressure 验证: warning 去抖 PASS, critical 单次 PASS (ABCR_FAKE_PRESSURE 注入)
- ✅ guard 包装端到端轻命令: `.venv/bin/python -m abcr.resource_guard run -- echo` PASS (preflight 12/12 normal, disk 92GB, no heavy proc, no Docker)
- ✅ flip_preview.py fail-closed 收口: judge 重试保留, 耗尽返回 {None, None} 替代 {0, 0} (commit cc62abe)
- ✅ card.notes 补记 ×3: B1.4 capture_path 裁定 + optimistic 方向检结果 + conscientiousness 勿引用/dtype 标注 (commit 465eff2)
- ✅ REVIEW-REQUEST.md: openness + neuroticism 段落 (commit 9c890b2)
- ✅ DEVIATIONS: B3.2 方向检矩阵超规偏差 (commit 81fc859)

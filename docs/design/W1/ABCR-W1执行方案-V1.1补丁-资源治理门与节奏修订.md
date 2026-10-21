# ABCR W1 执行方案 V1.1 补丁 —— S1.5 资源治理门 + 节奏修订

> 日期：2026-07-12 ｜ 作者：Claude（Fable 5，W1 方案制定方；基于监工方案更新建议独立核验后裁定）
> 性质：**增量补丁**。《ABCR-W1执行方案-V1.0》**字节级冻结、不作任何原地修改**——已有 run 的 `protocol_ref` 钉死其 `sha256:b4d39632…`（2026-07-12 实测本机文件哈希与之吻合），改动 V1.0 会使既有 run 的协议指针永久失配。本补丁独立成文；与 V1.0 冲突处**以本补丁为准**。
> 生效范围：自发布起，`/Users/superagent/abcr` 上**一切尚未启动的重负载任务**（定义见 F14.1）。已在跑的分片任务允许跑完当前片再接入。**云日 Runbook（24GB CUDA 卡）不受本契约约束**。
> 触发事件：监工相位「阶段 1」= w1-mini 复现包闭合验收线（**非 V1.0 的 S1**——V1.0 S1 是纯 fixture 阶段；下文以「里程碑 1」指代）期间，本机多次内存压力黄/红导致进程中断；里程碑 1 实耗 4 个半天（≈24h 连续工时）；此后三窗转入 24h/日连续运转。
> 审查记录：发布前经三镜头对抗审查（契约一致性 / macOS·MPS 技术正确性 / 运行漏洞，2026-07-12），2 blocker + 6 major 全部修入正文；关键实测：transformers 4.52.3 的 low_cpu_mem_usage 为 no-op、本机 MPS recommended_max_memory=11.84GiB。

---

## 0. 一页结论

1. **归因确认（采纳监工判断，独立核验后补强）**：V1.0 §3 规定「阶段内三包完全并行、互不等待」，但全套契约（F1–F13 + 三包文档）**没有任何一条跨包资源互斥条款**——「3B 能运行」被误当成「3B 可与三窗并行运行」。这是结构性缺陷，不是执行事故。
2. 事故的伤害有两层：表层是进程被系统压死、需要修复续跑；**深层是资源竞争污染了执行窗口的性能观测，诱发不可逆的科学降级**——A 包在 B 包 3B 长批量的同一时间窗内判定「M4 GPU too slow」，把 mini 环从 3B 降到 0.5B-CPU、真向量臂降到 random_direction（见 DEVIATIONS）。资源治理门的首要价值是防误判，其次才是防中断。
3. 核心动作四件：**F14 资源契约**（轻活照旧并行，重活全机串行，`mkdir` 原子锁 + 租约语义）＋ **S1.5 轻量治理门**（`resource_guard.py` + `make resource-smoke`，A 主导）＋ **软熔断**（macOS 内存压力分级优雅退出 E19，preflight 拒启 E21，配合既有幂等续跑）＋ **节奏修订**（24h/日连续 + 串行队列估时，见 §4）。
4. 刻意不做的：不建常驻监控守护进程、不做资源调度器、不强制 B 重构已自建的分块门控实现（追认为 F14.5 合规实现）、不动 V1.0 与既有 run。总实现成本 ≤1 人窗日。

---

## 1. 归因与实测证据（2026-07-12 本机采集）

### 1.1 方案层结构原因
三包文档重负载任务审计汇总（S2 起）：A——3B 烟检/双跑检/mini 环 360 次生成（4 臂×30 题×2 seed=240 + t0 sanity 120）；B——3B 抽取 400 生成×2 轮、方向检 ≈130 生成、翻转预览、exprcheck 120 生成，且 `.venv` 与 `.venv-pv` 两个环境都能加载真模型；C——claude CLI 批量（n=50 双 judge）。阶段回归 `make stage≥2-regression` 本身含真模型 pytest。**上述任意两项同时起跑，16GB 统一内存即进入危险区**；而全套契约中唯一的内存条款是包 A 文档 A3.2「3B×MPS 单进程防内存超载」——只约束 A 自己的 run 顺序，不涉跨包（V1.0 本体内存条款为零）。

### 1.2 本机实测（补丁阈值的依据）
- 物理内存 16GB；**swap 已用 7.6GB / 9.2GB**——系统长期高压的直接证据。
- **Docker Desktop 正在运行，其 Linux VM 启动参数 `--memoryMiB 8192`（= 恰好 50% 物理内存的预算上限）**，另有 5 个 `terraform-mcp-server` 容器——由各 Claude Code 窗口的 MCP 配置自动 `docker run` 拉起。ABCR 工作对 Docker 零依赖。
- 常驻 claude/MCP 进程合计 RSS ≈2.5–3GB（三窗 24h 运转的固定底座，不可消除，必须计入预算）。
- 预算算术：16GB −（系统+底座 ≈5GB）−（Docker VM 实占，最高可至数 GB）= 留给模型的仅 ~6–9GB；3B fp16 权重 6.2GB + KV/激活 1–2GB + torch 运行时 ≈8–9GB——**Docker 在场时单个 3B 任务已触边界，两个重任务并行必死**。
- 探测接口实测可用（无 sudo）：`sysctl -n kern.memorystatus_vm_pressure_level` 返回 1/2/4（normal/warning/critical，当前=1）；`sysctl vm.swapusage`；`/usr/bin/memory_pressure` 在位。

### 1.3 降级误判的时间线佐证
STATUS-B：B2.8（3B 400 生成，MPS fp16）与 A 的 S2/S3 真模型测试处于同一执行期。STATUS-A DEVIATIONS：「3B→0.5B-CPU downgrade (M4 GPU too slow)」「vector→random_direction degradation」。M4 的 3B fp16 MPS 单独运行并不慢（B 实测 400 生成 ≈5.5h 含 judge，约 45–50s/条）——A 观测到的「慢」大概率是并行竞争的产物。**此判定不追责执行窗口：在无资源契约的方案下，降级是当时可用信息内的合理止损。缺陷在方案。**

---

## 2. D16（新增决策）＋ F14（新增冻结契约）

**D16 资源契约**：代码/文档/轻测试工作维持三包并行；**任何重负载必须全机串行**，以原子锁互斥；重进程必须有界寿命并在内存压力下优雅退出。未否决即执行。

### F14.1 负载分级（判定标准冻结）
| 级别 | 定义 | 规则 |
|---|---|---|
| 轻 | 代码/文档/git；tinyqwen（CPU fixture）一切用途；DeepSeek API 调用（远程，本机仅 IO）；matplotlib/确定性评分/审计/打包；claude CLI **单次** `-p` 调用（如 trait 工件生成） | 照旧并行，无需锁 |
| 重 | **任何 ≥0.5B 真模型加载**（含 `.venv` 与 `.venv-pv`、含 generate_vec 前向、含真模型 pytest 与 `make stage≥2-regression`）；claude CLI **批量**——预计调用数 >5 **或调用数上界不可预估**的循环任务（如 n=50 双 judge） | 必须持有 heavy.lock，全机同刻至多一个 |

边界规则：已按轻活启动的任务要发出第 6 次 claude CLI 调用时，**必须先取锁**（阻塞或 E20），禁止裸续。

### F14.2 heavy.lock 锁协议（含租约语义）
- 路径 `/Users/superagent/abcr/.resource/heavy.lock`（`mkdir` 原子创建，与 bootstrap 锁同构；`.resource/` 入 `.gitignore`，归 A 随 guard 交付一次性追加）。
- **取锁**：`mkdir` 成功即持有，**立即**在锁目录内写 `owner.json`：`{pkg, pid, pid_start_time, task, started_at}`（`pid_start_time` 取 `ps -o lstart= -p <pid>`，防 pid 复用误判）。
- **活性判定**：pid 存活 **且** 该 pid 当前启动时间与 `pid_start_time` 吻合，才算活锁。`owner.json` 缺失/不可解析且锁目录 mtime <10s → 视为新鲜（写入空窗宽限），照常等待。
- **等待**：默认阻塞（30s 轮询，每 5min 一行排队日志）；`--nowait` 立即以 **E20** 退出。**持锁超过 8h**（最长槽位 5–7h + 缓冲）→ 等待者停止默等、向 STATUS 写 BLOCKER 交人（防持有者挂起类假活：pid 活着但 MPS 卡死）。
- **陈旧锁原子回收**：判定陈旧后先 `rename heavy.lock → heavy.lock.reclaimed-<pid>-<ts>`（rename 原子）；**仅 rename 成功者**有权删除该目录并重试 `mkdir`，rename 失败者视为已被他人回收、回到等待。回收者取锁后照常执行锁内 preflight（§3.2 判据 3 可拦截前任持有者的孤儿模型进程）。
- **释放**：进程退出删除锁（`trap`/`finally` 覆盖 E19/E21/异常路径；SIGKILL 无法覆盖——由陈旧判定兜底）。
- **锁文件不属于「跨窗口沟通」**：V1.0 §10-2 的「不跨窗口沟通」禁止的是内容协商；文件系统互斥是既有机制（bootstrap 锁、git index.lock 先例），本条显式豁免。

### F14.3 3B 独占附加纪律
- 持锁跑 3B 期间：**禁止第二个模型进程**（锁本身保证）、禁止发起新的 claude CLI 批量、pytest 禁用并行插件（xdist 等，本就未装，显式化）；其余两窗只做 F14.1 轻活。三窗本体与常驻守护进程不在禁止列（不可行，也已计入预算）。
- **Docker**：S1.5 一次性动作——退出 Docker Desktop 并关闭「登录时启动」。此后 preflight 检测到 `com.docker.virtualization` → **先自动 `osascript -e 'quit app "Docker"'`，等 30s 复检，仍在才 FAIL**（自愈优先：容器由窗口 MCP 配置自动拉起，窗口重启会重现，无人值守时不能靠硬拒停摆）。建议（非强制，楠裁量）：abcr 三窗禁用会 `docker run` 的 MCP（如 terraform），根因消除。
- 建议（非强制，楠裁量）：swap 已高位 7.6GB，首次过 S1.5 门前重启一次机器清 swap，重启后先跑 `make resource-smoke` 再拉起三窗。

### F14.4 加载与 MPS 纪律（一切真模型加载点强制）
- `from_pretrained` 必须显式传 `torch_dtype`（3B=fp16；0.5B-CPU/tinyqwen=fp32；4.52.3 中参数名即 `torch_dtype`）。**low_cpu_mem_usage 不设工作项**：实测钉死版本 transformers==4.52.3 中该参数是被静默丢弃的 no-op（modeling_utils.py:4157 直接 pop），低内存加载路径（峰值 ≈1×模型大小）是该版本**默认行为**——记录此事实防误归因；监工建议的目标效果默认已达成。
- 推理一律 `model.eval()` + `torch.inference_mode()`；除激活采集 run 外不开 `output_hidden_states`。
- MPS 上限：进程加载 3B 前执行 `torch.mps.set_per_process_memory_fraction(min(1.0, 8*2**30 / torch.mps.recommended_max_memory()))`。实测本机 recommended_max=11.84GiB、fraction≈0.676、上限恰 8.0GiB；超限抛**可捕获的 RuntimeError**（实测）而非系统级压死；**禁止设 0（= 无限）**。语义注记：上限 = min(8GiB, recommended_max)，且**仅约束 MPS 分配器侧**——`from_pretrained` 的 CPU 侧加载峰值不受其管，由软熔断（F14.6）覆盖。
- 每片/每批结束：`del` 中间张量 → `gc.collect()` → `torch.mps.empty_cache()`；片间记录 `torch.mps.driver_allocated_memory()` 到运行日志（观测泄漏趋势）。

### F14.5 分片进程契约（有界进程寿命）
- 重负载生成循环必须以**独立子进程分片**执行：3B 每片 10–40 样本（默认 20），0.5B 每片 ≤100；片进程退出即归还全部内存，外层循环依既有幂等续跑机制（F5 完成集 / B 的 checkpoint）拉起下一片；合并产物处校验 hash。
- 片进程在样本间除压力探测（F14.6）外检查 `os.getppid()`——**父进程消失（被收养）即走 E19 优雅退出路径**（防外层被杀后孤儿 3B 继续占内存，约 3 行代码）。
- 完整 preflight **每次取锁只跑一次**；片间只做瞬时压力读数（单次 sysctl，<1s），不重复 60s 采样。
- **追认条款**：B 包 B2.6 已自建的「分块检查点 + 内存压力门控」为本条合规实现，**不要求重构**；只需对齐三点——锁路径（F14.2）、压力探测源（F14.6 的 sysctl）、阈值语义（warning 停 / critical 急停）。A 的 runner 增加 `--max-items-per-chunk`（利用既有 --resume 续跑）。
- 方向检/系数扫描类任务：每个 层×系数 组合天然成片，逐组合独立进程执行（监工建议，采纳为推荐粒度而非强制）。

### F14.6 软熔断协议（配合幂等续跑，把「被杀」变「计划内退出」）
- 重进程在**样本间**探测 `sysctl -n kern.memorystatus_vm_pressure_level`（测试可用 `ABCR_FAKE_PRESSURE=normal|warning|critical` 注入）：
  - **warning(2) 连续 2 次**（去抖：单次 warning 不触发）：完成当前样本 → flush+fsync → manifest 追加 `resource_events` 条目 → 以 **E19** 退出并打印续跑命令。
  - **critical(4) 单次**：完成当前样本（不起下一条）→ `empty_cache` → 同上 E19 退出。
- 外层分片循环对 E19 的处置（**自动续跑只适用于 E19**；E20/E21 按各自条款处置，不入续跑循环）：等待压力回 normal 且持续 120s 后自动续跑；**等待上限 30min**——超时停批、向 STATUS 写 BLOCKER。
- 停批双闸（任一触发即停批写 BLOCKER 交人，防振荡与慢空转）：①1h 内**连续** 3 次 E19（连续 = 两次 E19 之间未完整跑完一片）；②本批 E19 **累计** ≥5 次。
- F10 错误码表新增三行：

| 码 | 含义 | fail 方向 |
|---|---|---|
| E19_RESOURCE_PRESSURE | 内存压力 warning/critical 触发软熔断，已优雅落盘退出 | closed（指路续跑命令；非数据损坏；外层可按 F14.6 自动续跑） |
| E20_RESOURCE_LEASE_BUSY | heavy.lock 被活跃持有且调用方要求 --nowait | closed（打印持有者 owner.json；不自动重试） |
| E21_PREFLIGHT_RESOURCE_FAIL | 锁内 preflight 任一判据不过（含 Docker 自愈失败、磁盘不足、他进程占用模型级内存） | closed（打印具体项；5min 重试 ×3 后停批写 BLOCKER；**非自动续跑事件**） |

- manifest 增可选字段 `resource_events: []`（记录每次 E19 的时间、压力级、已完成样本数）。

### F14.7 与既有契约的关系
- 「阶段内三包并行」（V1.0 §3）**限缩**为：轻活并行不变；重活进入全机单队列。阶段门协议与后备机制不变。
- **F7 所有权矩阵增行**（本补丁显式修订，不再声称矩阵不变）：`src/abcr/resource_guard.py` → A；`.gitignore` 的 `.resource/` 追加行 → A（随 guard 交付）；`tests/contract/stage2/test_a_resource_guard.py` → A（沿 test_a_* 既有规则）。B/C 不拥有 guard 代码，只以 CLI/包装器消费（与 A 盲用 B 的 interventions 同构）。
- **F11-S2 清单增补一项** `test_a_resource_guard`：既有 stage2 PASS 提交**不作废**，S1.5 验收即该项首跑；此后任何 stage2 回归重跑均含此项。
- F4 schema、F5 写入语义、F6 工件格式零改动——E19 退出走的正是既有崩溃续跑路径，只是从「事后修复」变「事前优雅」。

---

## 3. S1.5 资源治理门（轻量门，非完整阶段）

**定位**：插在当前时点与下一批重负载之间的一次性验收；此后每次重负载**取锁后**由 preflight 自动复检（约 60–90 秒/次取锁），不再需要人工过门。

### 3.1 交付物与归属
| 交付物 | 归属 | 说明 |
|---|---|---|
| `src/abcr/resource_guard.py` | A | **stdlib-only**（sysctl 走 subprocess；MPS 辅助函数内部惰性 import torch），保证跨 venv 可用。内容：锁协议（F14.2）、preflight（§3.2）、压力探测、`python -m abcr.resource_guard run [--nowait] -- <cmd>` 包装器（**取锁→锁内 preflight→执行→释放**） |
| runner 接入 | A | `abcr.run` 对非 tinyqwen 模型：**取锁 → 锁内 preflight** → 样本间软熔断 + `--max-items-per-chunk` |
| `make resource-smoke` | A | 验收目标（§3.3）；另设 `resource-smoke-3b`（可选重档探针，单独跑） |
| pv_bridge 对齐 | B | 既有门控对齐锁路径/探测源/阈值（F14.5 追认条款）；`.venv-pv` 命令统一经 `.venv/bin/python -m abcr.resource_guard run --` 包装 |
| claude CLI 批量包装 | C | 按 F14.1 判定为重的批量任务经 guard 包装器执行；单次调用豁免 |
| Docker 一次性动作 | 先到窗口 | 退出 Docker Desktop + 关自启（F14.3） |

### 3.2 preflight 判据（**取锁成功后立即执行**，fail-closed）
顺序钉死：**先取锁，锁内 preflight**——等锁可能数小时，先检后锁必然过期（TOCTOU）；陈旧锁回收后同样重跑 preflight，可拦截前任持有者的孤儿模型进程。判据：
1. 压力等级连续 60s normal（12 次×5s 采样；判据用 **Memory Pressure 而非「剩余内存」**——Apple 统一内存语义下 free 值无诊断意义，监工建议采纳）；
2. 磁盘可用 ≥50GB；
3. **无第三方模型级内存占用进程**：存在 RSS>2GB 的 python/torch 进程（排除自身）即 FAIL——判据用 RSS 不用进程名 pgrep，**排队等锁的 runner 未加载模型、RSS 远低于阈值，天然不误拒**（串行队列稳态就是总有人排队）；
4. 无 Docker VM（含 F14.3 的自动 quit→30s 复检→仍在才 FAIL 自愈序列）；
5. swap 增长（60s 窗口 `vm.swapusage` used 首末差）为**记录性指标**：写日志、不 FAIL（swap 高位机器上后台波动会制造 flaky 拒启；权威信号是判据 1）。
任一 FAIL → **释放锁**、以 **E21** 退出并打印具体项；外层处置：5min 后重试，连续 3 次 FAIL → 停批写 BLOCKER。

### 3.3 验收（测试文件 `tests/contract/stage2/test_a_resource_guard.py`，按 F14.7 入 F11-S2 清单）
1. 空闲机上 `make resource-smoke` PASS（取锁 + preflight 全绿 + 释放）；
2. 互斥与回收：双进程并发 `resource_guard run`，后到者 `--nowait` 得 E20、阻塞模式正确排队；伪造死 pid 的陈旧锁经 rename 协议回收，**双等待者并发回收只有一方成功**；
3. 软熔断全路径（tinyqwen 小 run + `ABCR_FAKE_PRESSURE` 注入）：单次 warning **不**触发（去抖）；连续 2 次 warning → E19 优雅退出、manifest 有 resource_events、续跑收敛到与不中断逐字节一致；critical 单次 → 急停同路径；
4. 停批闸：注入连续 3 次 E19（假时钟）→ 停批写 BLOCKER；preflight FAIL 路径：伪造 docker 进程名 → 自动 quit 尝试后仍在 → E21，连续 3 次 → BLOCKER；
5. （`resource-smoke-3b`，锁空闲时人工触发）3B 单载探针：fp16 + 8GiB 上限加载 → 生成 2 题 → `driver_allocated_memory()` 峰值记录 ≤ 上限 → 卸载后压力回 normal。
**成本预估**：A ≈0.5–0.75 窗日（guard ~250 行 + 接入 + 测试）；B/C 各 ≤1h。S1.5 未绿前，**不启动任何新的重负载**；轻活（C 终包整理、文档、图表终检）不受阻。

---

## 4. 节奏修订（24h/日连续运转 + 用时经验校准）

### 4.1 实测校准数据
- 里程碑 1（w1-mini 闭合验收线）：4 个半天 = **24h 连续工时**（含内存事故中断-重拉起开销）。
- 3B 生成吞吐（B2.8 实测，分片+judge+片间重载全含）：400 生成 ≈5.5h ≈ **45–50s/条**。
- 中断-续跑开销预算：按里程碑 1 经验计 **15–20%** 入估时。
- 串行队列估时模型：**阶段墙钟 ≈ max(并行轻活时长, Σ重活槽位)**——重活不再共享时段，估时按逐槽相加，不按最长单项。

### 4.2 修订执行队列（默认按此执行；D17 为科学参数变更，楠可否决）
| 批次 | 内容 | 负载 | 估时（含 15–20% 预算） | 目标时点 |
|---|---|---|---|---|
| 批0 | S1.5 治理门全部交付（§3）＋ Docker 一次性动作 | 轻（guard 代码）＋一次 3B 探针 | ≈0.5–0.75 窗日 | 7/12 内 |
| 批1（与批0并行） | C4.1 终包打包准备、C4.4 图表终检、STATUS 整理 | 轻 | ≈半天 | 7/12–7/13 晨 |
| 批2（需 S1.5 绿；重活串行两槽） | ① A2.4 双跑检 3B 档回补（当前 skipped，≈1h）→ ② mini 环 **3B 原规格回填**：4 臂×30 题×2 seed + t0（360 生成，真 residual_vector 臂，D17，≈5–7h）。③ C 全量评分复评为确定性重算（**轻活，不占锁**，随 ② 各 run 落盘增量进行，≈1–2h 与 ② 重叠） | ①② 重；③ 轻 | 重活合计 ≈6–9h | 7/13 内 |
| 批3 | w1-full 终包（含 §6 质量修正）＋ 全新会话闭合验收（G5 第二次） | 轻＋一次新会话 | ≈半天 | 7/14 |
| 缓冲 | 修门/机动/云日 Runbook 终检 | — | — | 7/15–7/17 |
| 对外日 | **7/18（六）不变** | — | — | 7/18 |
云日 #1/#2 仍由楠择日发射，不占本表；云端负载不受 F14 约束。

### 4.3 与 V1.0 §6 的关系
V1.0 日程的 S3=7/16、S4=7/17 作废——24h 连续运转 + 三包实际进度（STATUS 自报 S1–S4 大体完成、带降级）使剩余工作重组为上表「回填批次」形态。7/18 对外日锚点不动，现有 ≈3 天缓冲。**批2 若再遇资源事故**：软熔断自动续跑，触发停批闸即交人；止损档位——第一档沿 D11（30→20 题）；第二档（seed 2→1）为本补丁新增；**禁止降模型档或臂类型**——本条显式**覆盖** V1.0 §6 的「砍 3B 保 0.5B」止损（那是 rig 未验证时的止损；rig 已验证的现在，模型档降级只会复制 §1.3 的误判损失）。

---

## 5. D17（新增决策，楠可否决）：mini 环回填的 trait 改为 optimistic

- 变更：批2 mini 环 4 臂统一用 **optimistic**——vanilla / prompt_persona(optimistic) / residual_vector(**optimistic-dev，L16/coef2.0**，B 方向检 PASS 档) / random_direction(等范数)。
- 理由：D11 原定尽责（conscientiousness），但 B 实测其 neg 极性不足（200 负样本仅 3 条过阈，方向检 sub-threshold d≈±7.5 vs 门槛 ±10，属 trait 特性非管线缺陷）；optimistic 方向检轻松 PASS（有效样本 199/126）。D12 本就规定「向量臂后备 = optimistic-dev」——本条只是把后备升为主选。文本臂随向量臂同 trait，保持 D11「同源同 trait」精神。
- 尽责的正式抽取与表达检仍归云日 #2（7B bf16 + 官方每题 10 响应，预期解决极性问题），G4' 口径不变。

---

## 6. 复现包质量修正（源自里程碑 1 验证报告六缺口，只做低成本三项 + 一项回填生效）

| 项 | 对应缺口 | 修正（w1-full 终包起生效） |
|---|---|---|
| P1 | 缺口 2（env.lock=UNAVAILABLE） | env.lock 必须为真实 `uv pip freeze` 输出（`.venv` 与 `.venv-pv` 各一份）；**禁止 UNAVAILABLE 字面量** |
| P2 | 缺口 1（-t0 无 scores） | t0 子 run 一并出 scores；确不评分的在 manifest 显式 `scored: false` + 原因，不留歧义空验 |
| P3 | 缺口 5（协议文档不在包内） | V1.0 全文 + 本补丁全文随包（纯文本几十 KB），pack_manifest 记其 sha256 |
| P4 | 缺口 4（activation_summary 为 null） | 批2 回填 run 必须把 `iv.activation_summary()` 写回 step（F4 本有此字段，S3 实跑漏接线） |
| 判定为 by-design 不修 | 缺口 3（权重不入包）——`citable:false` 的 dev 包边界；缺口 6（judge 分数侧信道）——LLM-judge 天然不可确定性复算，一致性统计报告是正确形态 | — |

---

## 7. 对监工建议的采纳/裁剪对照（诚实沟通）

| 监工建议 | 裁定 | 理由 |
|---|---|---|
| S1 与 S2 间插 S1.5 资源治理门 | **采纳**，落为轻量门（§3）非完整阶段 | 机制要长期有效（覆盖 W1 剩余 + W2 继承），但验收并入 stage2 回归、不建新阶段机器 |
| D16/F14 资源契约 + heavy.lock + 3B 独占 | **采纳**，锁协议补齐原子回收/租约/防 pid 复用语义 | 与 bootstrap 锁同构；对抗审查发现朴素「pid 死=陈旧」在双等待者下互斥失效，已按 rename 原子协议修正 |
| 「禁止后台进程」 | **收窄**为禁第二模型进程/新重批量 | 三窗本体与守护进程不可消除，已计入预算（§1.2） |
| Docker 重任务前退出 | **升级**为一次性退出+关自启+preflight 自动 quit 自愈+复检 FAIL | 实测 VM 预算 8GiB=50% 内存且容器由 MCP 自动拉起；无人值守下硬拒会停摆，故自愈优先 |
| 60s 正常压力 / swap 增长 / ≥50GB 磁盘 / 无残留进程 / Memory Pressure 而非剩余内存 | **大体采纳**（§3.2）：swap 降为记录性指标；残留进程判据改 RSS>2GB 不用进程名 | swap 判据在高位机上是 flaky 拒启源；进程名判据会被排队稳态恒触发（对抗审查 blocker） |
| 软熔断 warning=STOP_AFTER_STEP / critical=SIGINT + E19/E20 | **采纳**，critical 改为同路径优雅退出而非 SIGINT；另增 E21 区分 preflight 拒启 | 样本间探测下 SIGINT 无必要，统一走 fsync+manifest 路径更符合 F5；E19（可自动续跑）与拒启（不可自愈）语义必须分码 |
| low_cpu_mem_usage / fp16 / eval+inference_mode / 关 hidden states / MPS 8GiB 上限 / 每批 gc+empty_cache / 高水位禁 0 | **采纳**（F14.4）；low_cpu_mem_usage 一项改记事实不设工作项 | 实测 transformers 4.52.3 中该参数为静默 no-op、低内存加载已是默认行为——效果达成，但契约不能写不存在的因果机制 |
| A/B 拆分片进程（A 每 5–10 题退出；B 拆三进程、20–40/片；方向检逐组合） | **采纳精神、放宽粒度**：3B 10–40/片默认 20；B 既有分块实现**追认不重构**；方向检逐组合为推荐 | B2.6 已有等效实现且经实战；强制重构是负价值 |

---

## 8. 接入与透传

1. 本补丁发布后：三份 W1 工程包文档**文末 append** 指针注记（不动既有行）；《ABCR-执行节奏方案-V1.0》文末 append 修订注记（其日历属另一套件，W2 kickoff 时按其自身状态注记重排，本次只注入节奏校准数据与 F14 继承要求）。
2. 新 run 的 `protocol_ref` 自批2 起**双指针**：V1.0@sha256:b4d39632… + 本补丁@sha256:（监工派发时以 `shasum -a 256` 现算并随任务原文附上）。
3. 监工向三窗透传时按纪律用**本补丁原文**；各窗把 F14/S1.5 相关交付按 §3.1 归属认领，归属冲突按 F7（含 F14.7 增行）裁。

---

## 9. 批准记录（2026-07-12，楠）

- **D17 批准**：批2 mini 环回填 4 臂统一 optimistic（residual_vector 臂用 optimistic-dev，L16/coef2.0）。
- **「abcr 三窗禁用 docker 类 MCP」批准**（由建议升为执行项）；**「S1.5 过门前重启一次机器清 swap」批准**——重启由楠执行，时点 = Docker 环境动作完成后、三窗重新拉起前。
- **批0 启动**：补丁原文向三窗透传。透传形态 = 全文落位仓内 `configs/protocol/`（连同 V1.0 副本）+ sha256 校验——比粘贴更保真（可校验、不可截断），且不违反三窗「不读 shared-brain」纪律。

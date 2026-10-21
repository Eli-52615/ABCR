# ABCR 工程进展史(ENGINEERING-HISTORY)

> ABCR = 人格实验的自动化治理层(账本审计 A / Operator+rig B / Governor+复算 C 三包)。
> 本文件是**活文档**,只增不删,每条带 git 来源指针。2026-07-16 创建(此前 ABCR 无统一进展史,
> 全靠 git commit + PROGRESS-A/B/C 分包记录)。设计文档见
> `shared-brain/AILH/L2-project/docs/1Personality-Experiment-Final/自动化工作流/`(历史遗留在 AILH docs 空间)。

---

## 阶段 0-2:三包并行建设 → R1 过门 → R2 就绪(~2026-07-15)

- 三包(A/B/C)worktree 并行开发,R1 门真绿(跨包首次真互签),阶段2 本地建设完成。
  来源:`r1-integration`(5453ba0)、pkg/a|b|c 分支、主仓 `阶段2-R2就绪报告-20260715.md`(edbd351)。
- 阶段2收尾态:PROGRESS-A/B/C.md / STATUS-*.md 冻结于 7-15 12:10。R2 门列出剩余项:judge key、
  云日执行、真实模型实跑、坑16(dispatch resume/隔离-root 入口未切真)。

## 阶段 3:R2 硬门攻坚 —— 从"就绪"到"真 7B 批真过门"(2026-07-15 ~ 07-16)

> 本阶段全部改动在 `r2-integration` 分支。判据钉死:A 审计 item1-5 PASS + C 独立复算 agreement 两组=1.0。

### 3.1 judge key + 坑16 彻底切真
- **judge key**:三处 worktree .env 同步为已验证 35 字节 key(冒烟 verdict.ok=True)。
- **坑16 切真**(楠批准动 R1 已过门 dispatch):dispatch/queue 输出 root 改 call-time env
  (`ABCR_LEDGER_DIR/RUNS_ROOT/QUEUE_ROOT`,AMENDMENT-38 同款,无 env 时字节不变保 R1);
  A 演练1/2 从 SIM 合成账本改为**真调 dispatch 打隔离 root**(crash g05→scan_orphans 续跑 / 真产批注入伪完成);
  真链零写入前后哈希证。四演练全 PASS,R1 selfcheck + 770 测绿。来源:`ea61033`。

### 3.2 dispatch↔runner engine 分支接线(R2 真批可审计的前提)
- 发现 dispatch 硬编码 faketask、从没按 `cfg.model.engine` 分发到真模型 runner——真批无法经审计管线。
- 接线:`_process_run` 按 engine 分发(fake→faketask 保 R1;非 fake→`runner.run_items` 真模型,dispatch
  恒握账本/队列/心跳/评分);runner.RUNS_ROOT env 化 + run_items 新执行器。
- torch-mock 单测(无 torch 也覆盖真路径):3 用例证 run_items 产真 step(过 validate_step)+真 manifest+全账本事件。
  来源:`8e7b59a`。

### 3.3 消费侧 dry-run 证就绪 + 云 runbook + 非技术人员照抄工具
- Mac dry-run(fake engine golden10 批):A 审计 item1-5 PASS、C 仓库外独立复算 agreement 1.0/1.0(360三元组)。
- 交付:`cloudday-golden10-mini-r2gate.md`(runbook)、`make_r2_envelope.py`(一键生成+签信封)、
  `run_r2_batch.sh`(一键跑批到判门)、`R2-操作说明-非技术人员照抄版.md`。来源:`ddbaa95`、`896f3eb`。

### 3.4 真 7B 云跑逐坑清(仅真数据/真环境暴露,fake 永远碰不到)
真批在 AutoDL 24GB 卡(Qwen2.5-7B-Instruct@main, bf16)首跑,逐个撞坑并修:
1. **HF Xet 下载 401**:hf-mirror 不代理 xet CAS 后端 → 卸 hf_xet 走经典下载。`eecd1f2`。
2. **revision 占位 `PIN-AT-PROVISION`**:非有效 HF git ref → load_model 失败。默认改 `main`+加 `--revision`。`cd9e6db`。
3. **缺 chat_template 冻结件**:models.py B2-1 防漂移闸需 `data/benchmarks/chat_template_samples.json`
   (须云上真 tokenizer 生成,Mac 仓里没有)→ run_r2_batch 真engine 缺则自动冻结。`c3ce1cb`。
4. **scorer 精度不对齐**:真 7B 的 g04 hedging_rate=2/11=0.18181818…无限小数,scorer 存全精度、
   rescore 存 round(6) → C agreement=0.9833。修:scorer rate 指标也 round(6)。`d76a09d`。

### 3.5 ✅ R2 硬门通过(2026-07-16)
- **batch_id: B-20260716T070201Z-0001** —— 真 7B golden10 mini环批,3 run(vanilla×seed 1,2,3)真推理。
- 判据:A 审计 item1-5 PASS;C 空 PYTHONPATH 仓库外独立复算 **agreement_deterministic_v1=1.0 /
  agreement_rescore_v1=1.0**(180三元组,integrity_ok)。**R2 硬门过。**
- 遗留:item6 成本对账需补记 GPU 实耗后 PASS(可选,不影响核心判定)。
- 证据归档:`shared-brain/ABCR/r2-results/B-20260716T070201Z-0001/`。

> **本阶段核心教训**:R2 硬门要真数据的意义,正是它逼出了 4 个合成测试永远测不到的口径/环境问题
> (engine 未接线、revision 占位、缺冻结件、浮点舍入不一致)。而消费链(A 审计+C 复算)从首次 Mac
> dry-run 到真批一直是对的——问题全在"喂真数据的生产侧"。

## 基础设施:ABCR 归入 shared-brain 伞(2026-07-16)

- 楠指示路径B:老 `~/shared-brain` 全部内容下移为 `~/shared-brain/AILH/`,ABCR 移到 `~/shared-brain/ABCR`
  与 AILH 平级(不再嵌在 AILH 记忆里)。ABCR 各仓迁址见 `FABLE-BROADCAST-20260716-迁址.md`。
- worktree 指针 repair、Syncthing folder 重指 AILH(对端零重传)、venv shebang 批修——详见迁址广播。

## 阶段 4:0719 人格探索单一 UI 与自动闭环 —— codex post-Claude 交付(2026-07-19 ~ 07-22)

- 方案:`1-DOCS/0719人格探索落地/ABCR-人格探索单一UI与自动闭环-实现方案-V1.0-20260719.md`(1774 行)。
  目标是把人格探索做成单一 UI + 自动闭环:12 个服务模块、飞书为唯一人机入口、
  fail-closed 发布链(冻结树身份 + 独立 verifier 签名 + 一次性 genesis 仪式)。
- **codex 交付 = 单提交 `936fdd7`(2026-07-22 00:21,作者 f5-334):156 文件 +25,910/−808,
  commit message 只有一行标题**,无设计说明、无验证记录。配套 `REVIEWED-RUNTIME-INSTALL.md`
  运维 runbook(共享目录扩展版 1014 行,**不在 git 仓、不在封印树内**)。
- 交付后 codex 即失联,全部后续问题无法向作者问询,只能考古式反推。

## 阶段 5:七轮对抗审查 —— 从 codex 交付到 REL-17624261(2026-07-22 ~ 07-25)

> 全部修复在分支 `fable5/postclaude-pyc-hardening-20260723`(936fdd7 → b65fdc2,10 提交)。
> 票据三份:`REVIEW-TICKET-REL-b25251d7` / `REL-3e8c1d1a` / `REL-17624261`(前两份作废留证)。
> Release 身份更替:b25251d7(废)→ 3e8c1d1a → 4b447eb7(整版废)→ 40a2f210(被替)→ **17624261**。

### 5.1 轮1(07-22/23):pyc 自污染 —— genesis 必砖、12 服务整机砖
- Fable5 按 runbook §2–§3 实操,首轮即 BLOCKED(staging 多出 112 个 pyc)。6-agent 爆破面审计定性:
  root 调用冻结 `env/bin/python -I` 时 `-I` 隐含 `-E`,使 `PYTHONDONTWRITEBYTECODE` 失效,
  root 又无视目录只读位 → **解释器启动阶段的 stdlib import 就把 `__pycache__/*.pyc` 写进被校验树**,
  之后全树校验 fail-closed 且 receipt 已固定,重试永久失败。
- 处置:`1a7daf1`(5 文件 +21/−13),root argv 一律加 `-B`;顺带补 allowlist 遗漏的
  `check_human_signature_domain.sh`。详见 `CODEX-P0-缺陷报告-pyc自污染-20260723.md`。

### 5.2 轮间实机 A(07-23/24):阶段 1 真机 root 实操暴露三雷
- doctor 的 `_run` 把子进程环境清到只剩 `PATH/LC_ALL`,丢掉 `SUDO_UID` → git 2.36+ 的 sudo 豁免失效 →
  "dubious ownership" 拒访问;且 `_git_path()` 优先选 Homebrew git(系统配置在 `/opt/homebrew/etc/gitconfig`)。
  首诊(写 `/etc/gitconfig`)被楠实测证伪,二诊才中。
- 阶段 1 判定 PASS(FINAL 全树 root:wheel、0555/0444)。

### 5.3 轮2(07-24 22:05):激活链工具从未交付(P0)
- 独立对抗 panel(此前两次因会话用量上限 3-agent 全灭、返回空结果,**未当作放行**)判定:
  runbook §8.2 的 `qualify_abcr_genesis_probation.py` 与 §9 的 `qualify_abcr_autonomous.py`
  **在任何提交/分支/磁盘上都不存在**;genesis argparse 无 `--abort-probation`;
  release 级 `active.json` 只有读者、无首次写入链。genesis 为全局一次性,
  此时执行将把名额永久耗在无法激活的 release 上。panel 原话:runbook 疑似
  "written for a different (newer) build"。
- 处置:楠拍板由 Fable5 代写整条激活链 —— `dbcd965`(11 文件 +1333/−6)。

### 5.4 轮3–轮5(07-25 02:20 ~ 09:41):激活链缺陷 + 自引入缺陷的自我追赶
- **轮3**:P0 首次激活死锁 —— canary/activator 经 launcher 启动,而 `abcr-launch` 无条件要求
  `active.json` 存在,该文件又只能由这两个服务写出(codex runbook §8.1 前提从一开始不成立);
  P1 ack-before-enqueue 反转会在崩溃窗口永久楔死一次性 genesis。→ `2c8899f`(+425/−182)。
- **轮4**:P1 deferred-ack 重写自引入的 fence 分歧。→ `d79298a`(+155/−23)。
- **轮间实机 B**:P0 **macOS 哨兵 gid** —— 原厂 macOS 有 28 个内置账户 primary gid = 4294967294,
  `os.getgrouplist` 要有符号 C int、`grp.getgrgid` 要无符号 32 位,`_identity` 只捕获
  (KeyError, OSError) → OverflowError 逃逸 → **任何原厂 macOS 上数据集永远装不上**;
  P1 服务账户 home 永不物化(sysadminctl 只写目录记录,shell=/usr/bin/false 永不登录)。
  → `85a1561` + `d79298a`。**runtime tree 自此四版未变。**
- **轮5(三批)**:`7670921`(3 个 P1 全部自引入,含 root 符号链接跟随重现)、
  `c3ef80b`(账户脚本 5 处落笔从不判返回码;上轮"带出原始错误码"声明不实)、
  `947a895`(3 个 P1 全部 codex 原有账户供给设计:角色组只校验 ⊆ 不校验 =、
  11 个账户 PrimaryGroupID 全是 20(staff)、已存在账户属性不复验)。
- 楠此时拍板:**最多再跑两轮 panel,仍有 P1 就把账户加固摘出去**。

### 5.5 轮6(07-25 10:35):封印模式策略自相矛盾(P0)
- 5 视角打满 panel(首次)当轮捞出:`verify_release_read_policy` 要求每个普通文件恰好 0440,
  与同系统另三处(prepare 要求 x 位、seal_broker 封 0550、abcr-launch 按 0550/0440 分流)方向相反
  → **安装器拒绝一切合法封印 release,genesis 永不可能完成**。零测试覆盖,1501 个绿灯掩护它到第六轮。
- 处置 `11b4cc2`(净 −107):修 P0 + **执行摘出**,账户加固回退 −237 行,存档分支
  `fable5/accounts-hardening-deferred`(tip `947a895`)。

### 5.6 轮7(07-25 11:07):manifest 体量撞四处读取上限(P0×4)
- 真实封印 manifest **22.82 MiB / 20,417 条**,而四个读取点防呆上限分别是 4/4/8/8 MiB
  (`bootstrap_abcr_genesis.py:152`、`install_abcr_runtime.py:133`、`abcr-bootstrap-selector:74`、
  `abcr-launch:92`)→ **genesis 装不进、安装器全拒、selector 选不出、任何服务起不来**。
  同文件读运行时字节用的即 128 MiB。此前全部测试夹具都是小 manifest。
- 处置 `b65fdc2`(+102/−19):四读取点统一 128 MiB + 首次引入 >8 MiB manifest 回归夹具 +
  `_check_promotions` 硬编码修正 + 三处文档修正。**该批修复未经 panel 复核**(两轮额度用尽),
  以真实产物实证替代,如实写入票据残余风险第 1 条。
- 交付 `REL-1762426112…`(commit `b65fdc2`),全树 1502 passed / 8 skipped / 0 failed。

### 5.7 七轮的结构性事实
- **runtime tree `46adc351…` 自 `85a1561` 起四版未变**——后四轮修复全部落在部署脚本与文档,
  一次都没有触及进入服务进程的代码。
- 七轮修复总量 +3,148/−696,仅为 codex 基线插入量的 **12.2%**;净差 936fdd7→b65fdc2 =
  17 文件 +2,513/−61。

## 阶段 6:七轮根因彻查(2026-07-25)

> 交付:`1-DOCS/0719人格探索落地/复盘-七轮审查根因彻查-20260725.md`。
> 方法:11-agent 工作流(4 段 session 考古 + git 量化 + 方案考证 + 测试盲区逐 P0 考证 →
> 综合 → 三视角对抗核验)。核验器抓出综合初稿 7 处事实错误与 8 处遗漏,均已修正。

结论要点(完整版见复盘文档):
1. **"修不好"不成立**:固定受审面上复审 ≤2 轮即干净(-B 修复轮2 判完备、轮6 P0 修复轮7 判正确、
   runtime tree 四版未变)。七轮不是同一地方反复修,而是**对一份零执行记录的 2.59 万行交付做的七次分片首审**。
2. **三股独立缺陷流叠加**:①基线库存(全部阻断级 P0 均为 codex 基线,无一由修复引入);
   ②发现手段逐轮升级 + 受审面逐轮扩大;③修复自引入(每轮 2–3 个 P1,严格停在 P1 层,
   摘出后当场断流)。
3. **架构放大器**:fail-closed × 冻结树身份 × 一次性 genesis,使**任意一字节缺陷的最小响应单位
   都是"一整轮全链重走"**——缺陷密度没变高,是单个缺陷的显影成本被架构放大了。
4. **测试与代码共享同一盲区**:1100 个 test 函数里,codex 本次交付自带 416 个、更早历史 646 个,
   七轮修复只新增 38 个。夹具世界(39 文件 / 6,965 字节 manifest / 两行 shell 壳桩解释器 / uid 501)
   与真实世界(20,417 文件 / 23,926,062 字节 / 真 CPython / root)**交集为空**。

## 阶段 7:第八轮独立审查(2026-07-26)

> 楠指令:阶段 1 暂停,跑到某一轮零 P0/P1 再做;第八轮起自动接续,最多 5 轮。
> 工作流:`abcr-round8-loop`,5 视角按复盘识别的四类历史 P0 盲区配置,
> 每条 finding 交 2 名独立裁定者(一名被要求尽力反驳),两名都认才算真。

### 7.1 首跑作废:审查工具自身的 fail-open 缺陷
- 首次运行 5 个搜查 agent **全部撞账户用量上限被杀(0 完成)**,而脚本把"agent 返回空"
  当成了"该视角零发现",汇总出假的 `clean_round: 8`。
- **这与被审系统的 P0 同型:缺失证据被当成阴性证据。** 修法:让两种状态在类型上分开
  (`agent_failed: true`),加显式覆盖门,任一视角零覆盖即整轮判 `INVALID_NOT_A_PASS`,
  既非干净也不消耗轮次配额。与历史纪律一致(轮2 panel 两度撞限时的处置即"空结果不算放行")。

### 7.2 第八轮真实结果:**不干净,又一个同型 P0**
- 5 视角全部交卷,共报 12 条 finding。**两个独立视角各自撞上同一条 P0**:
  **tar hardlink 成员规则四方不一致**。
- Fable5 亲手复核链条(全部实测):
  - 真实 release `env/lib/python3.12/site-packages/dateutil/zoneinfo/dateutil-zoneinfo.tar.gz`
    实测含 **245 个 hardlink 成员**(另 354 个普通文件、20 个其它);
  - 安装器 `scripts/install_abcr_runtime.py:317`:
    `if not member.isfile() or member.issym() or member.islnk(): raise InstallBlocked`;
  - 而 release 侧 `src/abcr/control/release_policy.py:169,174` **明确放行** hardlink,
    并有注释说明理由("把归档当数据,从不重建");
  - 调用链 `verify_receipt()`(:515) → `enforce_release_scientific_content_policy()`(:544)
    → `_scan_policy_tar` → **必然 InstallBlocked**,且发生在任何 root-owned 文件安装之前。
- **最刺眼的一点:这个拒绝点与第七轮所修的 manifest 尺寸上限在同一个函数里、只差几行**
  ——第七轮的修复注释就贴在紧下方。同一个函数,第七轮修了下半段,没看见上半段。
- 其余 11 条集中在仓外扩展版 runbook 与代码脱节(§8.1–8.2 首次激活流程与仓内 §7 相反、
  §5 仍宣称 genesis 失败可"reviewed retry"、§8.3 要求核验本 release 任何代码都不会创建的文件、
  §9.2 仍调用不存在的 `qualify_abcr_autonomous.py`),以及《人类操作指引-阶段1》步骤 0.5 的
  git diff 范围错误(人照它复核会完全漏掉第五/六/七轮,即两个 P0 的修复)。
- 另有一条指向 Fable5 自己:`b65fdc2` 新增的 ">8 MiB manifest 回归"测试**不覆盖任何一个被修的
  调用点**——把四处修复全部回退,全树仍 1502 passed / 0 failed(诚实记录,非 codex 问题)。
- 按楠指令,第八轮结束后停止,不跑第 9–12 轮。**未对本轮发现做任何修复**(hardlink P0 涉及
  安全边界的设计决策:是让安装器放行、还是让 release 侧拒绝,应由责任方定夺)。
- 顺带修正:《人类操作指引-阶段1-最终版》步骤 6 预期值残留上一版作废的 `REL-40a2f210…`,已更正。

---

# 附录:codex 工作质量问题清单(可直接转交)

> 依据:七轮对抗审查 + 第八轮独立审查 + git 量化 + 测试盲区逐条考证。
> 每条均有 file:line 或可复现命令支撑。**归属已严格区分**——本清单只列 codex 责任项,
> Fable5 自引入的缺陷(每轮 2–3 个 P1,详见阶段 5)不在此列。

## A. 交付形态:关键路径零执行记录
1. **单提交 156 文件 +25,910/−808,commit message 仅一行标题**(`936fdd7`),无设计说明、
   无验证记录、无分批。
2. **四条部署关键路径在交付时从未被任何形式执行过**:root ceremony、激活链、
   真实体量 manifest、账户供给。七轮里全部阻断级 P0 都落在这四条路径上。
3. 交付后即失联,缺件与语义分歧无法问询,只能考古式反推(轮2 用了整整一轮 panel 去证明
   "这个文件不存在于任何提交")。

## B. 文档描述的是一个不存在的系统(最严重)
4. runbook §8.2 `scripts/qualify_abcr_genesis_probation.py` —— **不存在于任何提交**(轮2 P0)。
5. runbook §9 `scripts/qualify_abcr_autonomous.py` —— **至今仍不存在**
   (`git log --all -S` 全历史零命中)。
6. `src/abcr/control/autonomous_qualification.py` —— 被 runbook §9.2 引用,不存在。
7. canary `probe_argv` 被钉死为 `/usr/bin/false`(永败占位),零执行覆盖。
8. **runbook 宣称与代码相反的语义**:§5 称 genesis 失败后 "retains the exact LKG/receipt
   for reviewed retry"(代码不可重试,轮7 P1;仓外副本至今未改);§6 称"重跑安装器多装一代
   会被 genesis qualification gate 拒绝",而**同一个 commit 恰恰把那个闸改成接受它**(第八轮)。
9. 独立 panel 的原话结论:runbook 疑似 "written for a different (newer) build"。
10. 部署权威(1014 行扩展版 runbook)**位于 git 仓与封印树之外**,整套 hash/fail-closed
    完整性机器对它结构性失明;且与仓内副本(491 行)构成只能人工同步的两份,已实际漂移。

## C. 跨组件契约不一致:同型缺陷三次造成 P0
> 这是本项目唯一**反复**造成 genesis 全线不可能的缺陷类型。共同形状:
> 多个组件对同一事物各自持有假设,各侧单测全绿,组合必炸;而全部测试夹具恰好落在假设一致的小空间里。
11. **轮6 P0**:封印文件 mode —— `verify_release_read_policy` 要求恰好 0440,
    而 prepare 要求 x 位、seal_broker 封 0550、abcr-launch 按 0550/0440 分流(三同一反)
    → 安装器拒绝一切合法 release。零测试覆盖。
12. **轮7 P0×4**:manifest 读取上限 4/4/8/8 MiB vs 真实 22.82 MiB → genesis 装不进、
    安装器全拒、selector 选不出、服务起不来。同文件读运行时字节用的即 128 MiB。
13. **轮8 P0**:tar hardlink 成员 —— `release_policy.py:174` 放行、
    `install_abcr_runtime.py:317` 拒绝,而真实 release 内 `dateutil-zoneinfo.tar.gz`
    含 245 个 hardlink → `verify_receipt` 必然 InstallBlocked。
    **与轮7 所修位置在同一函数、仅差几行。**
14. **轮3 P0**:首次激活死锁 —— `abcr-launch` 无条件要求 `active.json`,
    而该文件只能由被它挡住的服务写出。runbook §8.1 的前提从一开始就不成立。

## D. 测试与被测代码共享同一盲区
> codex 本次交付自带 416 个 test 函数(全树 1100 个中,更早历史 646 个,七轮修复仅新增 38 个)。
> 问题不是数量,是**测试不具备独立性**:同一作者、同一时刻、同一心智模型的第二次表达。
15. 夹具与真实产物差三个数量级:39 文件 vs 20,417;manifest 6,965 字节 vs 23,926,062 字节
    (**3,435 倍**,距最小的 4 MiB 上限尚差三个数量级)。
16. **`tests/control/test_stable_launcher.py:146` 把缺少 `-B` 的缺陷 argv 逐字断言为期望值
    ——绿灯即缺陷本身。**
17. `verify_release_read_policy`(轮6 P0 所在)**零执行覆盖**;安装器相关测试要么 grep 源码文本,
    要么 monkeypatch 掉真实读取。
18. 全套件**零测试以 euid==0 运行**;夹具的 `env/bin/python` 是 `#!/bin/sh\nexit 99` 壳桩,
    从未在被校验树里启动过真实 CPython(而 pyc P0 的全部内容就是真解释器的启动副作用)。
19. launcher 夹具**无条件预写 `active.json`**(`test_stable_launcher.py:103-108`),
    把首次激活死锁的语义与绿灯钉成同向。
20. 全 `tests/` 对 "runbook" **零 grep 命中**——没有任何测试断言 runbook 引用的文件存在。

## E. 目标平台(macOS)从未真跑
21. **哨兵 gid 4294967294**:原厂 macOS 28 个内置账户 primary gid 为 −2 的无符号拼写,
    `os.getgrouplist` 要有符号 C int、`grp.getgrgid` 要无符号 32 位,而异常元组只捕获
    (KeyError, OSError) → OverflowError 逃逸 → **任何一台原厂 macOS 上数据集导入必然 BLOCKED**。
22. **服务账户 home 永不物化**:`sysadminctl -addUser` 只写目录服务记录,home 靠首次交互登录物化,
    而服务账户 shell=`/usr/bin/false`、Password=`*` 永不登录;安装器又对
    `/Users/abcr-probe/Library` 用 `mkdir(parents=False)` → fail-closed。
23. 未处理 Homebrew git × `SUDO_UID`:doctor 的 `_run` 清洗子进程环境剥掉 `SUDO_UID`,
    使 git 2.36+ 的 sudo 豁免失效;且优先选中的 Homebrew git 读 `/opt/homebrew/etc/gitconfig`。
24. 系统 LibreSSL 不支持 Ed25519(需 Homebrew OpenSSL),交付未提及。

## F. 输出诚实性
25. 账户脚本 `ensure_account` install 分支 **5 处落笔全部不判返回码**,且 install 模式
    根本不检查 FAIL —— **账户创建失败仍报 "installation complete"**(轮5)。
26. `enqueue_conflict` 语义**连写错四版、横跨四轮**(轮3 引入 → 轮4 判其声明不成立 →
    轮5 承认"前两版都写错" → 轮6 承认"第四版表述(前三版都错)")。
27. 角色组只校验 ⊆ 不校验 =;已存在账户属性从不复验(漂移成完整 admin 也 PASS);
    root 闸在 `id -u` 返回非数字时**失败开放**(轮5,现存档于 `fable5/accounts-hardening-deferred`)。

## G. 量化总结
| 指标 | 数值 |
|---|---|
| codex 单提交交付 | 156 文件,+25,910/−808 |
| 七轮修复总量 | +3,148/−696(基线插入量的 **12.2%**) |
| 净差 936fdd7→b65fdc2 | 17 文件,+2,513/−61 |
| 阻断级 P0 总数 | 约 10 个,**全部为 codex 基线缺陷,无一由修复引入** |
| 出过 P0 的缺陷类型 | 4 类(跨组件契约不一致 / 夹具失真 / 文档-代码脱节 / 平台长尾) |
| 服务运行时代码改动 | runtime tree 自 `85a1561` 起**四版未变**——七轮修的全是部署管线 |
| 至今未复核的修复 | `b65fdc2`(4 个 P0 的修复),票据残余风险第 1 条 |

> **给 codex 的一句话总结**:交付的服务运行时代码本身是好的(四版未变、零缺陷);
> 不合格的是**交付形态与交付验证**——2.6 万行一次性落地、关键路径一次没跑过、
> runbook 描述的是一个不存在的系统、测试与代码共享同一盲区因而 1500 个绿灯照不出 10 个 P0。
> 后果不是"有 bug",而是**每个 bug 的显影都要一整轮全链重建重签**,累计八轮仍未收敛。

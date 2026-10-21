# ABCR 工程进展史(ENGINEERING-HISTORY)

> ABCR = 人格实验的自动化治理层(账本审计 A / Operator+rig B / Governor+复算 C 三包)。
> 本文件是**活文档**,只增不删,每条带 git 来源指针。2026-07-16 创建(此前 ABCR 无统一进展史,
> 全靠 git commit + PROGRESS-A/B/C 分包记录)。设计文档见
> `shared-brain/AILH/L2-project/docs/1Personality-Experiment-Final/自动化工作流/`(历史遗留在 AILH docs 空间)。
> **合并完整性核查清单**(声称 main 最新最正确前/合并前必跑,防"改的分支≠合并的分支"):
> `1-DOCS/CHECKLIST-合并完整性核查.md`(阶段7 方法固化)。

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

## 阶段 4:W1 工程/实验骨架 + 自动化工作流 对抗终验 → 五轮修复 → 四轮对抗回归(2026-07-16 ~ 07-17)

> BOSS/管家驱动:16 个并行子 agent 从第一性原理对抗审查(W1 域8 + 自动化域8),再 5 轮修复 +
> 4 轮独立对抗回归。全部改动在 `codex/fix-round1-20260716` 分支(本地,未 push,符合仓纪律),
> 基线 `main@4b58d96`。4 个受保护观察文件(REVIEW-REQUEST.md + 3 provenance.json)全程未触碰。
> 详细逐条见 `1-DOCS/W1/ABCR-W1与自动化-终版验收-五轮修复四轮对抗-20260717.md` 及同目录
> 对抗验收报告/发现明细 JSON。

### 4.1 对抗终验(16 agent,147 发现:41 P0 + 52 P1 + 39 P2 + 15 P3)
- 统一失败模式 = **fail-open / fail-permissive**:异常→NORMAL、缺分→满分、空集→PASS、损坏 store→
  令牌复活、探测失败→放行——与测试方案 §0.2 要求的 fail-closed 恰好相反。41 条 P0 全部
  CONFIRMED_BY_EXECUTION(scratchpad 副本真跑复现,非静态推测),且波次1与1-B 独立双人复现核心 P0。
- 头号实操地雷:`make stage2-regression` 收集期读真实 DeepSeek 密钥 + 真 3B + 付费 API(F-SP-01)。
- 结论与测试方案 V2.0 的 Gate A 预审一致(G1-G7 全线 FAIL),本轮把"静态怀疑"逐条执行坐实。

### 4.2 五轮修复链(fail-open → fail-closed 全线)
- **第一轮 `ae6400d`**:8 agent 互斥文件归属并行修 34 P0 + 30 P1;4 个"直接断言漏洞"的旧测试翻正
  (如 `test_corrupted_consumed_store_fails_open_to_empty`→断言 fail-closed)。
- **二次收口 `257d0ff`**:修对抗回归发现的 review E16 **过严回归**(合法 mini-loop run 全 FAIL、
  stage3 变红)——改为从冻结 config + n_steps_expected 独立导出 expected;补实操零计费(真模型/付费
  用例标 `@pytest.mark.golden`、`make stage2-regression` 加 `-m "not golden"`、新增 `-full` 目标需 APPROVE_COST)。
- **第三轮 `f1a554a`**:两个架构级 P0——令牌 `consumed_ledger.py`(append-only 哈希链+per-batch genesis+
  包外锚,删 store 检出)、seal 外锚账本(`SEAL_ANCHORS.jsonl` 哈希链+review 三层信任根);成本三契约
  `cost_ledger.py`/同步视图 verify_chain/盲评 HMAC 重做/capture 批维/watchdog 实例新鲜度/向量 provenance 守卫。
- **第四轮 `262925d`**:闭合第三轮回归发现的 3 个代码级新旁路(见 4.3)+ **更正 F-SP-03 误报**。
- **第五轮 `5aaf86b`**:闭合第四轮验证发现的 seal name-variant P1 + 完备性批判 3 项(补 round4 回归测试/
  纠 docstring/清死代码)。终态 **604 项无计费测试全绿**(unit+stage1 145、stage2+3 not-golden 66、自动化 393)。

### 4.3 四轮独立对抗回归(每轮 agent 都击穿修复者自测盲区——本阶段最大价值)
- **R2 回归**:75/93 killed;抓到 review E16 过严回归 + 若干部分修复 → 二次收口。
- **R3 回归**:3 个代码级新旁路——盲评 sample_id 做了 HMAC 不可逆却漏了**行序**(公开种子42可去盲,P0)、
  seal 锚 **append+last-match**(追加篡改锚即过,P1)、令牌锚 **null-mac 降级**(alg=none,剥 mac 即绕,P1)。
- **R4 回归**:token/blind 门 HOLDS;seal **name-variant**(NFC/NFD/大小写文件系统等价名绕过冲突检测,P1)
  + 完备性批判 3 项(round4 缺回归测试/docstring 陈旧/死 shuffle_seed)。
- **R5 自查**:seal pack_name 归一化(NFC+casefold)对多变体稳健,真不等价名(希腊Α vs 拉丁A)不误并。

### 4.4 两个架构级 P0 的最终态(推到单主机信任域的代码级天花板)
- **F-TOKEN-02 令牌删除复活** KILLED:删 store/删 approvals 目录/伪 genesis/broken-symlink/null-mac 降级
  全 fail-closed(R4 独立 6 攻全挡);残留=`rm -rf state/` 全域抹除/HMAC 密钥失陷/keyless 链本身——信息论级。
- **F-C-05/F-JBT-01 seal 重签** KILLED:identity-ambiguity 类彻底闭合(重签包旁 seal/append+last-match/
  name-variant 全拦);残留=同权限全量重写锚账本——需 git-committed 外锚闭合。

### 4.5 关键认知更正与诚实边界
- **F-SP-03 是误报**:extraction_meta 明示 optimistic-dev 是 `extract_mac.py v2 (chunked)` 独立分极过滤
  (上限 5×20×2=200),199/126 都在界内且非对称合法——原"pinned shared-mask 下 199 不可能"的前提不成立。
  第三轮基于该错误前提的对称守卫会**误拒合法 Mac-bridge dev 向量**,已改为仅当 card 声明 shared_mask 才强制。
- **信息论残留(不冒充已修)**:fail-closed 门的信任根落在与被保护对象同写权限的本地文件(consumed 链/锚、
  seal 锚账本、extraction_meta),攻击者一旦具该写权限(=全域抹除能力)可全量重写。**根治=仓外不可变根**:
  seal 锚账本+消费链头 git commit(本地即可)、令牌改非对称签名——属部署/ops 层接线,代码已留全部 hook
  (`git_commit_anchor_ledger`、`review --expected-manifest-sha`),建议作合并前最后一步。
- **需 GPU 重跑项**:card 数据本体 float32 生产级重抽、成本账本历史对账、conscientiousness 方向复核。

> **本阶段核心教训**:安全门的"测试通过≠行为正确"反复出现,且**只有独立对抗回归(非修复者自测)能抓出来**——
> ① 初始 4 个测试直接断言漏洞;② fail-closed 修复过严到合法路径也走不通(review E16);③ 做了 HMAC 不可逆
> 却漏行序;④ 做了哈希链却漏 append/name 归一化;⑤ 有 HMAC 却被 null-mac 降级。每一层"修好了"都要
> 独立 agent 换新姿势再打一遍。另一教训:**原始发现也可能是误报**(F-SP-03),对抗回归同样负责证伪自己人的结论。
> 收敛判据:安全关键门全部 HOLDS 或仅剩信息论极限,剩余需仓外信任根(ops 层)+ 数据重跑,代码层达合并就绪。

## 阶段 5:文献综述 D0–D7 一口气执行 + 残余偏倚两段式收口(2026-07-16 ~ 07-17,与阶段4并行的研究线)

> 楠驱动:按《ABCR文献综述执行方案 v1.0》(`1-DOCS/ABCR文献综述执行方案_v1.md`)多 agent 一口气执行,
> 边界=完成到 D8 楠介入前(Tier-1 精读/判决备忘录/gap statement 属楠亲笔,未做)。产物根目录
> `shared-brain/ABCR/lit-review/`,总账见其 `00-运行报告.md`(七节含全部事故与偏差账本)。

### 5.1 主线 D0–D7(8 主力 agent 工作流:六前沿收获+Gate0 八邻居全文定界+杀伤扫描→去重选表→抽取→100%引用复核→Gate1 材料→完备性审计)
- 一行统计:收获 2742 / 筛后保留 329(另 borderline 132)/ 隔离 0 / 探针 14 中(3 补 0 失)/ 升级 100。
  定位表主线 104 行,引用复核率 100%(S2 批量+双源,零幻觉约束全程执行),审计 pass(2 major 当日修复)。
- **Gate0 杀伤格局:无致命,两条邻近度3警报**——C1←2602.12285(人口学 persona×agentic,-26.2%,但仅
  vanilla 对照无统计检验);C4静态←2604.11048 三件套(交互矩阵+DPR 路由,全静态无工具调用)。
  Persona Vectors 全文核实:结果变量未链任务成功率→C2/C3 前提保住(楠的记忆成立)。
- §4.3 机械推导判决倾向(终判权属楠):C1/C2/C3/C4/C7 强EXTEND、C5/C6 EXTEND、无 OPEN 候选;
  总判:主张群生存缝隙=人格×agentic×剂量三交叉。C7 定界大修:F3 挖出 ContextEcho/Assistant Axis
  正式论文,C7 从"证明漂移"升级为"漂移动力学×恢复/止损交互"。
- 交付:定位表 csv+md、Gate0 杀伤报告、Gate1 热图(571行)、Tier-1 候选 15 篇+8 篇最小集、六前沿地图、
  方法进口清单(419行,70源行,已按"不等D14"喂晓燕线)、弹药包、BibTeX、隔离区/升级/探针/收获日志/borderline 队列。

### 5.2 工程事故账(三起,全部零数据损失恢复)
- ①Workflow args 字符串化注入失败(BASE 渲染"undefined",产物漂移 scratchpad)→中停修脚本,phase-1 提示词
  保持逐字节一致命中恢复缓存,八 agent 零重跑;②会话限额中断(7-16 22时重置);③跨 session 恢复缓存失效
  (后台 job 重启换 session id,phase-1 开始整体重跑,20 秒内止损)→从旧 journal 手工提取结果以字面量注入
  续跑脚本,7-17 晨续跑成功。另:收获层 prox 通胀(把"可进口"误标邻近度3)→抽取层带 §4.3 严格重评指令矫正+
  Gate0 全文定界回写(R001/R007/R028/R077)。

### 5.3 残余偏倚两段式收口(楠规则:P(找不到≥3级)>90% 则停,否则补充轮)
- 侦察轮(偏倚2 异框架词汇/偏倚3 纯中文/偏倚4 非arXiv托管,3 agent+1 全文定界):**B2-01(2601.06403)
  确认 C3 三级重创·边缘**(解码层剂量α→任务成功率占位,不触内部表征;引文扫描证"残差流方向+剂量+成功率"
  组合位仍空);PANDA(ACL2025)→C4 agentic 交互面挤压。合成 P(补充轮空手)≈53%<90% → 触发补充轮。
- 补充轮(OpenReview 深扫 53 查询/814 命中、lab 灰文献全枚举、RL 词族+引文网络、中文轻扫):**无致命;
  C3/C4 致命组合位全通道确认仍空置**;定位表 104→**140 行**(R105–R140),判决倾向全部维持但理由收紧。
  新增待全文定界队列:duDmnRyJh5(C3 致命位最近邻,防御向)/AdaPA-Agent(C4,自适应强度→agent任务)/R108/R109。
  暗区收口为可点名残余(偏倚2≈8%/偏倚3≈2-3%/偏倚4≈10-12%,致命<5%)+五条再扫触发器。
  来源:`lit-review/bias-sweep/00-侦察轮判定备忘录.md`、`lit-review/deliverables/补充轮-偏倚234-报告.md`。
- 交棒态:等楠四裁决——D2 重定位材料、D3 borderline 132 条、D7 Tier-1 选定、待定界队列是否先跑。

> **本阶段核心教训**:① 检索 agent 的"探针诚实协议"(区分自然检出/补充检出)是校准检索网的关键——14 探针
> 漏 3 个直接暴露查询洞;② prox 通胀是多 agent 检索的系统性偏差("对我重要"≠"离我近"),必须由带严格
> 评分卡的独立抽取层矫正;③ 盲区漏检根因各不相同(PANDA=查询角度、B2-01=词汇系统、中文=该域原创不存在),
> 增量重扫只值得投 OpenReview 在审池(时间性盲区)与异框架词汇(结构性盲区);④ 工作流工程:args 需防
> 字符串化、跨 session 恢复缓存会失效——journal 手工提取+字面量注入续跑是可靠兜底;⑤ kill-first 有效:
> 最危险邻居全部来自预检出定界+杀伤扫描双通道交叉,而非常规前沿查询。

## 阶段 6:全面对抗验收 r2 真实面 → 三轮加固建外部信任根 → 合并 main(2026-07-19 ~ 07-20)

> 楠驱动:先问"W1/自动化怎么上手用",引出"照 README 操作零 bug"复核。触发对 r2-integration
> **真实执行面**(rig/判分/审计/盲评/云预算)的全面对抗验收——阶段4(fix-round1)修的是平行实现,
> r2 实际调用面从未验收。三轮加固后合并 main。判据:fail-open 类彻底关闭 + 残留超出探索期威胁模型。

### 6.1 关键发现:阶段4"合并就绪"验在了平行死实现上
- 阶段4(codex/fix-round1,五轮,`5aaf86b`)加固的是 `src/abcr/score.py|review.py|repro_pack.py|interventions/*`;
  但 R2 真批实际走 `rig/scorer.py|report/repro_pack.py|rig/interventions/*|audit/*`——**同名概念、不同文件,
  从未进过对抗验收**。8 agent(3 验 fix 分支 + 5 验 r2 独有面)击穿:41-P0 类 fail-open 在 rig/审计/判分/盲评/云预算
  系统性存在。典型:漏写 coefficient/全零向量/换题库 → status=completed 且与 vanilla 逐字节相同(§2.11 判据只在
  docstring 无实现);幽灵批 B-DOES-NOT-EXIST 六项 PASS;删 items → 0.857 静默变 0.0 且 pass=True;成本链尾截断
  verify_chain 仍过;盲评 120/120 反推;云预算四路洗白;`APPROVE_COST` 全树 0 次(计费地雷仅靠"env 恰好没设 +
  torch 恰好没装"哑火)。
- 根因收敛=4:①无外部信任根 ②空/缺失被当成功 ③验船师问运动员(自述可信)④判据只在文档没接线。
  来源:`1-DOCS/W1/ABCR-W1与自动化-管家对抗验收报告-20260716.md`(触发)+ 本阶段三轮 workflow journal。

### 6.2 三轮加固(每轮独立对抗复验 + 阴性对照;非修复者自测)
- **R1(地基 + 7 组并行)**:建 `common/external_seal.py`(单一规范锚 + length 承诺 + 全内容 digest,缺锚 fail-closed)
  + `common/evidence_floor.py`(空→None→FAIL);7 组按互斥文件接线。复验 **10 HOLDS / 7 BYPASSED**——证据完整性主链
  (哈希链/封存锚/scorer-review/盲评门)仍开,授权/并发/演练/干预数学 HOLDS。教训:按文件硬切所有权,切断了
  "扩展定义↔使用定义"接线(treehash/dispatch 分叉、seal_chain 零调用点)。
- **R2(4 owner 跨文件 + 接线证明)**:改按"修一条 bug 的完整闭包"分组,每条附生产调用点 grep。复验 **1 HOLDS /
  6 BYPASSED**——但 6 条均为"原洞已闭合 + 更深一层等价攻击"(复验者按"等价攻击自问"指令挖深)。P4 违反:为接线
  一度让 auditor 调 seal_chain → 验船师获写锚权(能把自己检出的篡改重封成合规)。
- **R3(2 owner 收敛式验证)**:验证改为只判指定残留 + fail-open 回退,更深层记为观察(不据此判 BYPASSED,防不收敛)。
  V10 后缀白名单→全文件逐字节 hash;V09 auditor 写锚归零 + guarded_reseal 拒覆盖(截断/前缀改写皆拒);V05 review 对
  citable 批强制 items 源封印(a_freeze 生产端封印)。复验 **3/3 HOLDS**。
- 终态:原始 fail-open 全关。基线:控制面 **809 passed / 0 failed**、preflight **30/30**、fake 全链贯通、**0 引入回归**;
  W1 科研结果(pv_bridge 云日翻转 demo)零回退。来源:加固提交 `d000672`。

### 6.3 合并 main + W3 残留交棒
- `d000672`(r2-integration 加固)→ `merge --no-ff` 合并 main(**`5945f39`**,44 提交;merge-tree 干跑零冲突;
  preflight 迁址常量两侧同改自动合一)。合并后 main 上 preflight 30/30 复验通过。安全网:`backup/pre-harden-r2`(2b47aac)、
  `backup/pre-harden-fixround1`(5aaf86b)。
- **提交纪律**:运行产物(anchors/seals.jsonl、demos/、configs/envelopes/、review 输出)排除出 commit 并入 .gitignore;
  既存 dirty(trait draft 工件)未触碰(云日 #2 已暂停,楠保持 draft)。本仓永不 push(遵楠 git 决策)。
- **W3 残留清单(3 条,确认期前必闭)**:R1 云单价自述(price 零校验,谎报单价洗真实烧卡)、R2 成本闸无网络出口
  (按文件名拦非 syscall 级)、R3 pack sys.path 影子模块(声明纯源码 stdlib 同名影子劫持验证器 import)——均需老练内部人
  构造特定制品,探索期(Mac/fake/无真卡)不触及。**这正是阶段4 §4.5 flagged 的"仓外不可变根 / ops 层接线"落地**
  (external_seal 已建;云单价校验/网络出口守卫/隔离解释器三处待接)。来源:`1-DOCS/W1/ABCR-三轮对抗加固报告-与W3残留清单-20260720.md`;
  外行上手说明:`上手指南-如何开始实验.md`。

> **本阶段核心教训**:① **验收要验对代码**——阶段4"合并就绪"栽在验了平行死实现,真实调用面(rig/audit)从未被打;
> 摸清"实际执行链走哪些文件"(死/活代码判定)是对抗验收的前置。② **"BYPASSED 清零"不是终极闸门**——对抗验证是分形的,
> 指示复验者"换等价攻击"总能挖出更深一层;正确判据 = fail-open 类彻底关闭 + 残留超出当前阶段威胁模型(R3 据此改收敛式验证)。
> ③ **并行隔离边界会变成正确性断点**——按文件硬切,恰好制造出"判据没接线"这一本项目要修的病本身;应按 bug 完整闭包分组。
> ④ **"接线"与"越权"只隔一层**——为让机制被调用而随手加调用点,把写锚权加到了验船师(违 P4);正确接线 = 生产者封印一次、
> 验船师只读只验。⑤ **独立复验 + 阴性对照仍是唯一可信手段**(延续阶段4);续跑内容寻址缓存让额度中断只损失在飞 agent、
> 已完成成果永久复用。

## 阶段 7:全分支考古 → 补齐 fix-round1 漏合并的核心加固线 → main 达"最新最正确"(2026-07-20)

> 楠驱动:追问"确定合并进 main 了吗?3 轮还是 5 轮?为何 5 轮改同一批文件却没进 main?"→ 引出对
> "还有没有改动该进却没进 main"的彻查,要求 main 全部代码是"改好的最新最正确版"。

### 7.1 彻查:全 18 分支逐一比对,唯一漏源 = fix-round1
- `rev-list main..<每个分支>` 穷举:pkg/a|b|c 各 1 ahead = 重复迁址提交(无独有代码);worktree-wf-*(9 个)=
  指向 fix-round1 提交的临时工作流分支(零独立内容);codex/persona-control-*(6 ahead)= 新任务(楠指示排除);
  **唯一有 main 缺失改进的是 codex/fix-round1(5aaf86b)**。
- **关键更正**:阶段6"全部 fail-open 关闭"是过头说法。真相:fix-round1(阶段4)从基线分出修了一整套
  **授权/运维/资源核心加固**(approval_token/runstate/watchdog/resource_guard/run.py/manifest/envelope/planner/
  ledger·report·views),而 r2-integration 是**另一条独立线,从未碰这些文件**;合并的是 r2,于是这条加固线
  **整条落在 main 外**。阶段6/7 栽的是同一个坑的两面:验的代码≠跑的代码(阶段6)、改的分支≠合并的分支(阶段7)。
- 实测坐实(非静态):main 的 approval_token 损坏 consumed 账本 → `verify=True` 令牌复活(F-TOKEN-02 fail-open)。

### 7.2 逐文件分类(fix-round1 30 文件 vs main)
- ✅ 已在 main(逐字节同):consumed_ledger/cost_ledger 实为 fix-round1 新增(此前 diff0 系 git 报错假读);13 个 test_fix*。
- ◆ main 是三轮 ◆ 加固版:auditor/report/dispatch/writer/review/score/sync/… 共 26 文件——**不回退**。
- 💀 死平行实现(main 正确排除):top-level interventions/*、repro_pack.py、dual_judge、pv_bridge/exprcheck_gen。
- ⚠️ 活代码但 main=未加固基线原版 = 真缺口 → **本轮全部移植**(Confirm 阶段逐个复现确认非重构)。

### 7.3 第四轮:干净移植 + 不碰 ◆ + 对抗复验(2 owner×4 簇:授权/运维/视图/旧judge)
- 授权:approval_token 接 consumed_ledger(损坏→ConsumedLedgerTampered fail-closed)+ verify_and_consume 原子;
  envelope 拒 NaN/Inf 预算+重复 seed;planner 预算门 authoritative_spent 消空转。
- 运维:runstate RMW 全程锁内 + scan_orphans fail-safe;watchdog 坏 state 告警/文件名防覆盖/按实例判空转;
  resource_guard 探测 fail-open→fail-closed + 锁 inode fencing。
- W1runner:run.py try/finally 保释锁 + realpath 收敛 + resume 一致性 + items sha 绑定;manifest 白名单臂纯度 + 原子落盘。
- 视图:ledger/views 合并 cloud-day 段(修 run_failed 漏报);report/views 排除隔离 run。旧 judge 簇 = SKIP(已被 r2 judge/* 取代,无活缺口)。
- 落地:10 改源 + 2 新模块**逐字节 = 5aaf86b**(干净文本移植);26 个 ◆ 文件逐一核对 diff=0 未覆盖。
- 复验:4 簇全 **CLOSED**(含阴性对照);主控亲验令牌复活缺口移植后 `verify=False:ConsumedLedgerTampered`。
- 基线:控制面 **815 passed**、preflight **30/30**、fake 全链 R2 硬门 PASS、W1 套 **104 passed**、演练 10 passed。
  1 例 drill1 回归在**演练侧适配**(runstate 未弱化,==5aaf86b)。
- 提交:`7b64df6`(直接在 main)。安全网:`backup/pre-harden-r2`。

> **本阶段核心教训**:① **"改的分支≠合并的分支"是最隐蔽的返工源**——分支上加固得再好,没进 main 就等于没做,
> 且 diff-0 假读(git 报错被 wc 当成"零差异")会掩盖"文件根本不在 main"。查漏合并要 `rev-list` 穷举全分支 +
> 逐文件三方定位(main vs 基线 vs 候选),不能凭印象。② **平行实现是双刃**:r2 用 rig/* 与 fix-round1 修的 top-level
> 同名文件并存,导致"修了 A 份、跑的是 B 份"与"合了 B 线、加固在 A 线"两类错配。长期应消灭平行实现,单一权威。
> ③ **移植优于重写**:main==基线的文件取候选分支版是文本干净的,难点只在调用方兼容与独立复验——比重新实现省且更可信。

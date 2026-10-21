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

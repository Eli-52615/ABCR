# CODEX post-Claude：部署与资格化交接（2026-07-22）

本交接用于把已通过 `CODE_RC` 的分支安全地送入独立审查、root 部署和部署后资格化。它不是“现在复制几份文件并启动服务”的快捷说明；任何跳过签名、review copy、genesis 或 doctor 的做法都会破坏本轮建立的权力边界。

## 1. 当前交付身份

| 项 | 值 |
|---|---|
| 分支 | `codex/postclaude-completion-20260722` |
| 基线 | `5da96ae05fed3a237fc6ee188439e9be59e4ad6e` |
| 工程提交 | `936fdd7227ff803ba8953ba2180bac6250c7dddd` |
| CODE_RC | PASS |
| LIVE_PILOT | BLOCKED（两个子门 PASS，不改变总门枚举） |
| AUTONOMOUS_QUAL | BLOCKED |
| active release | 无 |

上表是 7 月 22 日交接时的历史身份，不是后续收口提交的发布授权。实际部署必须从最终
review ticket 读取新的 exact 40-hex commit；不能用 branch、tag、`HEAD`、本表旧 SHA 或
dirty checkout 作为发布身份。

## 2. 现在必须停住的边界

现有审计候选：

- reviewed commit：`936fdd7227ff803ba8953ba2180bac6250c7dddd`
- candidate tree：`03c37dd1a3f2575975676da5ceccaa02085e6b3853eefaa7bde35bb78db5542b`
- runtime tree：`61518b215a3ada4b5a26976bbf776604d743c2dab0134e29b7f0eed8dc77e3d2`
- 状态：`UNTRUSTED_CANDIDATE`
- key：ephemeral audit fixture public key

**这个候选绝不可 root-copy、genesis 或部署，也不能在原地换 key 后补签。** Candidate 内嵌 verifier 公钥，finalize 会要求传入公钥与内嵌字节完全一致。正确做法是取得正式独立 verifier 公钥后，从 exact reviewed commit 重新 build 新候选；旧候选只保留为审计证据。

## 3. 权威状态机

```text
Fable5 确认最终 commit
  → 正式 verifier 公钥到位
  → 从 exact commit 离线重建新 candidate
  → doctor-candidate 返回预期 rc=78 / SIGNED_VERIFICATION_REQUIRED
  → Fable5 在真实 deny-default sandbox 独立测试并签 PASS attestation
  → finalize + staged doctor-release
  → 人逐项比较完整 hash/commit/release/key fingerprint
  → root 原子 review copy
  → root 安装 genesis authority、账户和冻结 dataset
  → root 一次性 genesis
  → root 安装 Human/service keys/research-memory seal，核对凭据+owner，env -i 初始化 DB
  → selector 整代资格化
  → 只加载 seal-broker/canary/activator，完成 genesis probation
  → formal active/consumed 复核 + 12 launcher structural doctors
  → 精确 PID/argv 停用一次性 owner 发现器，再加载其余九个 job
  → semantic 矩阵：11 个 rc0/ok:true + mission-builder rc78/fixed BLOCKED
  → LIVE_PILOT 真人一题分段快道与 Human approval 现场旅程
  → reboot / true mission / bad patch / bad slot / cloud drills
  → AUTONOMOUS_QUAL
```

每个箭头只消费上一阶段的 exact receipt；任何 hash、owner、mode、key、候选、release ID 或 doctor 不一致都停止，不现场“修一下继续”。

## 4. 普通用户/发布协调者要做什么

1. 建立 review ticket，记录 exact 40-hex commit、正式 verifier 公钥路径和 fingerprint、现成 Python 3.12 home/site-packages、新的空 `ABCR_BUILD_ROOT`。公钥必须是 single-link regular file、非 symlink，且 group/world 不可写。
2. 按仓内 `ops/install/REVIEWED-RUNTIME-INSTALL.md` §1–§2，从 exact Git object 离线重建。该过程禁止 `pip`、`uv`、安装 Ollama或下载模型。
3. 从 checkout 之外执行 `doctor-candidate`。预期 rc=78 且为 `SIGNED_VERIFICATION_REQUIRED`；这是正确的“等待独立签名”状态，不是可部署 PASS。
4. 把新 candidate tree hash、reviewed commit、两个 resource mirror hash、固定 candidate argv 交 Fable5，然后停止。
5. 收到独立签名 attestation 后，执行 runbook §3 的 `finalize` 和 staged `doctor-release`。两次输出必须绑定同一 commit、release ID、candidate tree、verification、manifest 和恰好 12 个服务模块。
6. 人必须亲自比较完整 commit、release ID、reviewed path、release/source tree、expected receipt、有限 TCB hash 和 verifier-key fingerprint。候选自己的输出不能替人作授权判断。

到此最多是 `READY_FOR_HUMAN_ROOT_REVIEW_COPY`，仍未获得 root authority，也没有启动服务。

## 5. 独立 Fable5/verifier 要做什么

1. 在 candidate、release、checkout 和本仓之外生成并保管 production verifier 私钥；构建者只得到公钥。
2. 对**用该正式公钥重新构建的新 candidate hash**执行固定命令：

   ```text
   candidate/env/bin/python -I -m abcr.control.candidate_oracle_adapter
   ```

   子进程在真实 deny-default candidate sandbox 中运行；Fable5 独立比较 oracle，不能接受 child 自报 verdict。
3. 只对精确 candidate hash 生成签名 `VerificationAttestation(PASS)`，返回 attestation 原始字节/路径、对应公钥和 fingerprint、candidate hash、fixed argv、sandbox 与独立比较证据。
4. 若最终证据提交改变了代码交付 identity，必须先重新确定要发布的 exact commit；签名不能从旧 candidate 迁移。

## 6. root 管理员要做什么

只有正式 attestation 和 staged `doctor-release` 都 PASS 后，才按 `ops/install/REVIEWED-RUNTIME-INSTALL.md` 的顺序执行：

1. §4：原子 root-owned review copy，并在 incoming、final 两个位置各跑一次 `doctor-release`。
2. §5：生成 authority draft；人逐项比较；用 `approve-authority --human-reviewed` 规范化；一次性安装固定 genesis authority。
3. §5：`bootstrap_abcr_accounts.sh --install-reviewed ...` 与 `--check`。`abcr-dataset-read` 必须精确只有 `abcr-itempool`、`abcr-auditor`；遇到任何多余 direct/GUID/nested/primary/effective 成员只调查并显式纠正，脚本不会擅自删用户。
4. §5：把两份钉死的 dataset source 放入固定 root-only source root，运行 `import_abcr_dataset.py --install-reviewed`、`--check`、`--check-live`。authorized UID 必须能真实 list/open/read，所有 denied UID 必须收到 `EACCES/EPERM`。
5. §5：以 exact genesis authority ID 执行一次 `bootstrap_abcr_genesis.py --genesis-reviewed ... --human-required`。
6. §6：不要第二次运行 installer。bootstrap Human/service keys/ResearchMemory seal；从 staging
   no-clobber 复制人已核对的 `feishu.env` 和 owner 四元组，并记录 owner/mode/link/hash。
   用 sealed `check_human_signature_domain.sh` 检查前置；它 PASS 不等于 LIVE approval PASS。
7. §6：用各自 UID、`/usr/bin/env -i`、sealed Python `-I` 初始化 Human/Operator DB。
   ResearchMemory 只能由首个 owner-confirmed goal saga 创建，不能手工伪造。
8. §7：资格化 launcher/seal-broker/test-controller 整代。§8 只加载最小三 job，完成
   genesis probation，复核 formal active/consumed，再跑 12 个 launcher structural doctors。
9. §8.5：从部署票据读取一次性发现器的 exact PID/完整 argv，逐字核对后 TERM；确认没有
   第二个 ABCR 长连接 listener，再加载其余九个 job。
10. §8.6：semantic doctor 的准确基线是 11 个 rc0/ok:true，mission-builder 因外部
    adapter/egress subgate 未装应 rc78/fixed BLOCKED。不是“12 全绿”。
11. §9.4 当前禁止执行：不得安装 `transformers`/`torch`、下载/转换模型、重装 Ollama、
    手写 profile，或运行 `prepare-profile/install`。正式 execution profile 继续 BLOCKED。
12. §10：按 exact bootout/bootstrap/doctor 安全重启 Human gateway；失败时按逆序 bootout
    九个 job。最后完成真实飞书一题 `带③L：否` 的 itempool→probe→view 验收。

不要把 sudo 密码发给 agent；管理员在本机终端逐步执行，每一阶段保留完整 stdout/stderr、exit code、生成的 receipt 和 hash。

## 7. 当前仍禁止启用的功能

- 从 source/dirty checkout 做 privileged install。
- 对 ephemeral-key 审计候选做 root copy、genesis 或 runtime install。
- 12 launcher structural doctors 之前加载其余九个 plist；或在未停一次性发现器时加载 Human gateway。
- 把资格化前的 mission-builder rc78/BLOCKED 改成 rc0，或声称“12 semantic 全绿”。
- 执行 runbook §9.4 的 future-only profile 命令、安装依赖、下载模型或重装 Ollama。
- 自动发布 `cards.py` 或 `doc_mirror.py` 修复；它们仍为 `human_required`、`auto_release_eligible:false`。
- 启用 `mission-builder.codex_argv` 或 external canary adapter；它们需要独立 `AUTONOMOUS_QUAL` 绑定 root-owned finite adapter、exact argv/bytes、deny-default sandbox 和 egress policy。
- 把本机 Qwen fixture 资格化说成 production itempool/deployed E2E PASS。
- 用一次 genesis、单测或服务自报 health 推断 `AUTONOMOUS_QUAL`。

## 8. 部署后的资格化顺序

### LIVE_PILOT

1. 真飞书 owner 发消息，留 event/owner receipt；伪 open_id/tenant/chat 被拒绝。
2. 真卡片 approve、reject、expire、supersede；断线重放和并发双击无重复副作用。
3. 先做最低可用门：真实 owner 用分段表单跑 `题量：1/种子：1/带③L：否`，票据含同一
   session/request hash、唯一 itempool/probe 阶段、`probe_completed`、result/row hash，且
   `查看快道结果` 返回同一不可引用行；重放封口不得生成第二个 probe。
4. 按 runbook §10.1 重启 Human gateway 并验证新鲜 `状态`；Feishu redelivery/outbox 恢复
   需另留 exact event/effect 证据，不能用“重启后能回新消息”替代。
5. Human signature 前置探针、真实 approve/reject/expire/supersede 和伪身份拒绝分别留证。
6. 正式 execution profile/远端 CUDA 未资格化时，目标确认后的正式同日轮必须安全
   BLOCKED；不得用本机快道结果替代 dispatch/audit/report。
7. 服务基线按 11 rc0 + mission rc78 记录；只有 AUTONOMOUS subgate 外签 PASS 后才要求
   mission-builder rc0。

### AUTONOMOUS_QUAL

1. Mac 整机重启，验证 human/outbox/operator/runstate/lease/幂等恢复。
2. 一个无害真实工程缺陷经 qualified Codex adapter、test-controller、verifier、canary 到 release。
3. 一个故意坏补丁被拒绝；active 指针不变或回滚成功。
4. 坏 bootstrap/broker slot 被 selector 拒绝。
5. 下一云窗完成 7B bf16、A 审计、C 独立复算、费用对账与 4bit↔bf16 校准。

每项单独输出 `PASS/FAIL/BLOCKED`、证据路径、exact release/receipt 和残余风险；不能用代码已存在替代现场实测。

## 9. 审查证据索引

仓内：

- `reports/implementation/preflight.json`
- `reports/implementation/adoption-matrix.json`
- `reports/implementation/path-ownership-validation.json`
- `reports/implementation/dataset-import-closure.json`
- `reports/implementation/live-probe-qualification.json`
- `reports/implementation/reviewed-runtime-candidate.json`
- `ops/install/REVIEWED-RUNTIME-INSTALL.md`

共享文档：

- `ABCR-人格探索单一UI与自动闭环-最终证据报告-20260722.md`
- `ABCR-后台控制面如何和人沟通-外行说明-20260719.md`

## 10. 当前需要人的真实卡点

当前不可由代码自行越过的输入必须以最终 review ticket 为准：production 独立 verifier
公钥/签名与 exact reviewed commit、管理员 root ceremony、人工核对的飞书凭据和 owner
四元组、维护窗中精确停用一次性发现器，以及真人飞书一题验收。正式 execution profile、
真实 Codex/egress、坏 slot/reboot 和云资源仍是后续独立资格化窗口，不得夹带进本轮安装。

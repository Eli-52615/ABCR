# ABCR 人格探索：傻瓜级日常操作手册

这份手册只讲“人怎么用”。日常不需要打开仓库、不需要 SSH、不需要写代码。
你只使用两个入口：

1. **主要入口：飞书里与 ABCR 机器人的一对一私聊。**所有会改变实验的动作都在这里完成。
2. **只读后备：Mac mini 上打开 `http://127.0.0.1:8765/`。**它只能看，不能批准、暂停或提交。

如果页面或飞书显示 `BLOCKED`，不要自己改文件。把完整状态词和对象 ID 发给管理员。

## 1. 先记住三条规则

- 目标书仍由你和 Claude 人工讨论定稿；ABCR 不代替人格理论判断，也不会擅自补目标。
- 只复制机器人卡片给出的完整命令。ID、六位以上指纹和 `v版本` 少一个都不会批准。
- “已收到”不是“已完成”。只有显示“已完成/已发布”且独立验证通过才算结束。

完成 root 部署、Human/飞书资格化和真实一题验收后，控制面才可宣称可用的是：目标书
导入/确认、`带③L：否` 的分段快道、审批、状态、round/run 暂停恢复中止、问停因和人的反思。
验收前只能说“已安装/待资格化”，不能说“真正可用”。**正式实验执行还必须另外安装有效的 root-owned
experiment execution profile；它与 Codex 自动维修的 AUTONOMOUS 资格完全独立。**没有执行档、
cloud scope 或已登记云资源时，正式 workflow 会安全停在对应节点，不会改用 Ollama/Qwen probe
模型冒充正式实验。当前仍明确 BLOCKED 的外部门见第 10、12、13 节；界面不得把它们冒充成
“正在自动处理”。

特别说明：Mac mini 上本地 MPS/CPU 运行目前只属于“排练、不可引用”。系统会从每个实际
run 的 manifest 复核 batch、配置、release、模型、tokenizer、模板、device/dtype；本地结果即使
分数正常也不会显示成正式可引用结论。正式 CUDA bf16 适配器尚未受审，因此正式证据门保持
`BLOCKED`，不是让人补一条命令就能绕过的状态。

## 2. 每天开始：只发两个字

给 ABCR 机器人发：

```text
状态
```

机器人应按六块汇报：待确认目标、快道学习、正式实验、轮报告、异常恢复、预算校准。
每个对象都应告诉你：现在状态、最后更新时间、已做什么、下一步、预计多久、是否需要你。

想看预算时发：

```text
预算
```

显示 `UNKNOWN` 就表示没有足够新鲜的价格/校准数据，不等于 0 元。

在 Mac mini 本机浏览器打开首页：

```text
http://127.0.0.1:8765/
```

它返回同一份只读 JSON snapshot（是管理员诊断页，不是第二个日常操作界面）；过期会明确写
“状态未知”。首页同时投影待确认目标、快道、正式实验、审批、轮报告/反思、异常恢复和服务健康。
可下钻的只读地址是：

```text
/api/v1/overview
/api/v1/approvals
/api/v1/rounds/<round_id>
/api/v1/missions
/api/v1/incidents
/api/v1/budget
/api/v1/notebook
```

它不接受 POST，也不是第二套控制源。
不要为了远程访问把它改绑 `0.0.0.0`；不在 Mac mini 前时继续用飞书私聊。

## 3. 提交你和 Claude 定稿的目标书

第一条消息：

```text
开始提交目标书
```

机器人会回复一个不可猜的会话号，例如 `PS-a1b2c3d4e5f60718293a4b5c`。接着把 YAML 原文放在
会话片段中。下例的 `PS-a1b2c3d4e5f60718293a4b5c` 必须替换成机器人返回的完整值。只有一段时照抄：

```text
目标书片段 PS-a1b2c3d4e5f60718293a4b5c 1/1
<从这里开始粘贴完整 YAML，原文一字不改>
```

多段时必须从 1 连续编号，并且总段数始终一致：

```text
目标书片段 PS-a1b2c3d4e5f60718293a4b5c 1/3
<第一段>
```

```text
目标书片段 PS-a1b2c3d4e5f60718293a4b5c 2/3
<第二段>
```

```text
目标书片段 PS-a1b2c3d4e5f60718293a4b5c 3/3
<第三段>
```

首片会冻结总片数；单片最多 16 KiB、最多 64 片/合计 256 KiB，并须在 15 分钟内
完成。重复发送同一片不会重复追加；同序号不同内容、缺片、跨私聊或超时都会拒绝。

最后发：

```text
结束提交目标书
```

机器人会回复 `PROP-...` 和原文 hash。先核对，再发：

```text
确认目标 PROP-机器人返回的完整ID
```

也可以用同义的 `确认提案 PROP-...`。格式错误、重复 key、多文档、缺字段或题集越界时，
系统会拒绝并告诉你回 Claude 修订；它不会猜着补。

## 4. 先跑“快道学习”：只走分段快道

当前唯一面向普通使用者的主路径是分段快道。先发：

```text
开始快道
```

拿到 `PS-...` 后发一段：

```text
快道片段 PS-a1b2c3d4e5f60718293a4b5c 1/1
预测：该人格会提高找错类任务表现，但不会只增加输出长度
人格文本：<临时人格文字>
题量：20
种子：1
带③L：否
模型档：qwen25-7b-q4-v1
```

这里的六个字段不能漏、不能重复，也不要加“题库路径”“holdout 路径”等自定义字段。
`题量` 只能是 1 到 42；`种子` 必须是整数；`带③L` 只能写 `是` 或 `否`；
`模型档` 必须逐字复制当前 root 配置（本版受审值为 `qwen25-7b-q4-v1`）。
`人格文本` 也可替换为唯一一个已登记的 `人格引用`，但两者不能同时写。临时人格只随
这次快道保存，系统会给它生成 `TEMP-...@v1` 引用和 hash，绝不会写入正式人格登记表。

封口并入队：

```text
结束快道
```

成功时机器人先回复“安全入箱”，后台随后依次显示 `itempool_queued`、`probe_queued`、
`probe_completed`，每次换阶段都会主动发一条人话通知。完成通知会给出 `probe_id`、结果行数、
首个 `row_hash` 和一条可直接复制的查看命令，例如：

```text
查看快道结果 PROBE-... 1
```

每页最多显示 6 行，并为每行附上可复制的 `毕业这一针 <64位row_hash>`；有下一页时机器人
会给出下一页命令。工作器若明确失败，状态会落为 `failed` 并显示有限原因码，不会永远卡在
“排队中”，也不会把失败猜成完成。你可以随时发 `状态`，或看集中面板；重复发送同一封口动作、后台
重启或断电重放都只认同一个 session/hash，不会重复造实验。题目只能由 root itempool
从 dev split 选择并封印，临时快道结果固定标成“学习数据·不可引用”，不能混入正式
结论。

**当前 ③L 边界：**本机 Ollama 尚无受审 exact tokenizer/chat-template 路径，因此把
`带③L` 写成 `是` 会明确返回 `PROBE_3L_EXTERNAL_BLOCKED`，且不会入队、不会偷偷
降级成普通快道。当前要顺利跑通就写 `否`；需要 ③L 时先完成外部资格化。

旧命令 `先做快道 G-...` 只适用于机器人**主动给出**且状态已经是 `compiled` 的完整
G 卡；当前 execution profile 未资格化，普通使用者不要自行拼 G ID，也不要把这条旧命令
当日常入口。没有机器人给出的可复制 G 卡时，一律使用上面的 `开始快道` 六字段表单。

已有提案时，机器人卡片也可能给出以下精确动作；原样复制即可：

```text
运行快道 PROP-... 2 42
```

或指定人格引用：

```text
运行快道 PROP-... px-counterexample@1 2 42
```

快道结果永久带“学习数据·不可引用”。它适合找方向，不能写成正式证据。

## 5. 把值得验证的一针升级成正式目标草稿

`probe_id` 可能包含多行，系统不能猜哪一行应毕业。因此下面这个已识别语法当前会
明确返回 `PROBE_ID_REQUIRES_ROW_SELECTION`，不会产生草稿：

```text
毕业 P-...
```

先复制完成通知中的命令查看结果（页码可省略，默认第 1 页）：

```text
查看快道结果 PROBE-机器人返回的完整ID 1
```

再从该页复制唯一的 64 位 notebook row hash：

```text
毕业这一针 <完整64位row_hash>
```

成功的“毕业这一针”只生成正式目标草稿，不会自动花钱、不会自动批准。你继续和 Claude 检查、修订，
再按第 3 节提交新目标书。

## 6. 正式实验审批

审批卡会同时给 request ID、内容指纹短码和版本。批准必须完整照抄：

```text
批准 APR-20260719-017 abc123 v3
```

拒绝必须写原因：

```text
拒绝 APR-20260719-017 abc123 v3：预算太高，先缩小范围
```

内容或版本一变，旧批准自动失效。重复点击/重复发同一命令最多生效一次。

卡片必须把两个概念分开显示：`费用上限` 只是绝不能突破的 cap，不是预算预测；没有
新鲜、受审的价格与吞吐校准时，`预计费用：UNKNOWN；预计时长：UNKNOWN`。看到
`UNKNOWN` 不要自行拿上限当预计值，也不要据此启动云资源。

如果你批准时卡片已经过期，系统不会接受旧卡，也不会让你重新提交目标。它会在相同的
内容指纹、引用和审批范围上生成连续的 `v下一版` 卡片；旧版本永久保留为已过期事实。
只复制机器人最后一张卡片中的完整命令。若同时看到多张卡，以版本最大的 live 卡为准；
拒绝过的请求不会因为重试而重新打开。

高风险工程任务预留了独立命令，不能拿实验批准代替：

```text
批准任务 MR-20260719-004 def456 v2
```

```text
拒绝任务 MR-20260719-004 def456 v2：先人工审查 changed paths
```

**当前能力边界：**`mission_high_risk` 独立 Ed25519 scope 尚未安装，因此这两条都会
明确返回 `MISSION_SCOPED_APPROVAL_UNAVAILABLE`，不会伪造批准或拒绝事实。若卡片写
“自动维修未资格化（BLOCKED）”，只表示任务安全排队，并不表示 Codex 正在改代码。

## 7. 暂停、恢复、中止和问原因

总是使用卡片里的准确对象 ID：

```text
为什么停了 R-20260719-001
```

```text
暂停 R-20260719-001
```

```text
恢复 R-20260719-001
```

```text
中止 R-20260719-001
```

暂停保留现有证据；恢复从安全 checkpoint 继续；中止是明确终止，不会偷偷新开一批。
未知故障若没有资格化自动修复链，会显示 `BLOCKED` 并要求管理员介入。

## 8. 从一轮下钻到某一道题

卡片给出 round、family、item 三个 ID 后发：

```text
下钻 R-20260719-001 ifeval_zh_v1 item-008
```

只有已经发布、正式可引用并通过 Auditor 签名审计的轮次才会返回逐题证据。系统会重新
核验唯一 round、报告 hash、broker 回执、root 密封树、Auditor 签名、batch/goal/envelope
绑定和逐项 evidence index，再显示该 family/item 的 persona/arm、seed、原始 prompt、
模型输出、主判分、记录 hash。飞书单条消息最多显示前 4 条 arm×seed；完整索引仍保留，
页面只给摘要和同一条下钻命令，不把大体积原始记录塞进首页。

若文字命中 secret 模式或超过安全长度，界面只显示字符数和 SHA-256，不回显原文；这不是
数据丢失。旧报告、本地排练、未通过审计、坐标不存在、密封树/签名/hash 漂移或身份不唯一
都会明确 `BLOCKED`，系统不会拿你输入的 family/item 假装“查到了”。飞书文档若存在只是
同一 snapshot 的只读镜像；不能在文档里打字下命令。

## 9. 记录人的反思

短反思可一条发完：

```text
记录反思 R-20260719-001 我认为差异可能来自约束冲突，而不只是人格强度；下一轮应加入竞争解释。
```

长反思先发：

```text
开始记录反思 R-20260719-001
```

拿到 `PS-...` 后按片段发送：

```text
反思片段 PS-a1b2c3d4e5f60718293a4b5c 1/1
<粘贴完整反思>
```

最后发：

```text
结束记录反思
```

机器的“下一实验建议”只是建议。只有人的反思和你与 Claude 定稿的新目标书才能启动下一轮。

## 10. 云实验当前禁止创建、启动或付费

**本版本没有受审的远端 CUDA 执行适配器，生产云入口在选档之前固定返回
`CLOUD_REMOTE_EXECUTION_UNQUALIFIED`。不要在供应商后台预创建实例，不要启动，不要
充值，也不要把 provider 参数发给机器人。**空的 root-owned 云档注册表是有意的安全门，
不是让使用者补 JSON 的安装缺陷。即使数据库里残留旧 `cloud_ready` 行，也不能退回本机
supervisor 冒充云执行。

未来只有在远端适配器通过独立审查、root 档位登记、价格/吞吐校准、云资源专属 v+1
过期续签和真实 provider 销毁核验都完成后，管理员才会发布新版手册并开放“选择云档”。
在那之前，任何旧说明中的“选择云档→预创建→登记→批准→启动”都不得执行。

如果历史 workflow 已经对应一台由人另行创建的云实例，人必须先在供应商后台请求销毁，
再按卡片记录这项**人的声明**：

```text
声明已请求销毁云实例 CR-20260719-003 <完整64位操作/截图/工单内容hash>
```

旧话术“确认云实例已销毁”仅为兼容别名。这个 hash 只记为 `human_attested`，不是 provider
回执，也不能把面板变绿；在供应商 API/账单侧核验“实例已终止且停止计费”之前，面板必须
保持风险红色、费用未知。不要把人的一句确认写成供应商已经销毁的证据。

## 11. 颜色和状态怎么读

| 颜色 | 人话 | 你要做什么 |
|---|---|---|
| 蓝 | 进行中/验证中 | 通常等待；看最后更新时间和 ETA |
| 绿 | 已完成/已发布 | 可查看报告；仍区分学习结果和正式证据 |
| 黄 | 已暂停/等你决定 | 复制卡片唯一动作，或明确拒绝 |
| 红 | 未完成/已隔离/证据风险 | 不要硬恢复；先问“为什么停了” |
| 灰 | 已排队/状态未知/信息过期 | 刷新“状态”；过期不能当成功 |

人格效果没有提高不是红色工程故障。漏数据、越界、hash 漂移、复算不一致才是证据风险。

## 12. 什么时候必须找管理员

只在这些情况介入：

- 顶栏写“人域网关离线”、飞书长连接/凭据/owner 身份失败；
- `BLOCKED` 指向 root、密钥、LaunchDaemon、ACL、dataset、external signer；
- `BLOCKED` 指向 `EXPERIMENT_EXECUTION.profile`：本机 MPS 档只可用于排练且不可引用；
  正式实验应等待受审的远端 CUDA bf16 adapter/profile，不要下载模型、不要手写 JSON，
  也不要拿 probe/Ollama/GGUF 档冒充正式档；
- 状态过期且多次 `状态` 仍不刷新；
- 证据被隔离、正式 active/release 不一致；
- Mac 重启、真实跨 UID、坏 slot、真云或 AUTONOMOUS 外部门尚未演练；
- 机器人给出的动作不在本手册或缺 ID/hash/version。

不要把 secret、私钥、token 或整份内部日志贴进飞书。只发错误代码、对象 ID、时间和卡片状态。

## 13. 管理员一次性安装清单

这部分仅管理员执行；普通使用者跳过。完整、权威、逐行命令在
`ops/install/REVIEWED-RUNTIME-INSTALL.md`。顺序不能交换：

1. exact reviewed commit 构建 candidate；外部 verifier 真 sandbox 测试并签 PASS；
2. root review copy；审核 genesis authority 全 hash 后人工批准；
3. 建服务账户/组，导入并 `--check-live` 冻结 dataset；
4. **只运行一次** `bootstrap_abcr_genesis.py --genesis-reviewed ... --human-required`；
5. 安装人域/服务/ResearchMemory keys，迁移飞书凭据和已人工核对 owner，初始化 human/operator DB；
6. root selector 一次性资格化 launcher/seal-broker/test-controller 整代；
7. 只 load seal-broker、canary-controller、release-activator；以 `abcr-operator` 跑 genesis probation；
8. 重读 formal active + consumed；跑十二个 launcher structural doctors；
9. 精确核对 PID/argv 后 TERM 一次性 owner 发现器，确认没有第二个长连接 listener；再 load
   其余九个 plist；逐 UID 跑 semantic doctors，准确矩阵是 11 个 rc0/ok:true +
   mission-builder rc78/fixed BLOCKED；
10. `EXPERIMENT_EXECUTION.profile` 当前明确 `BLOCKED`：权威手册 §9.4 本轮禁止执行，
    不得 pip/uv/brew 安装依赖、下载/转换模型、重装 Ollama、手写 profile 或运行
    `prepare-profile/install`。未来须由新的 reviewed release 和外部资格化手册开启；
11. 外部 AUTONOMOUS authority 安装 root-owned adapter/Seatbelt/egress policy，签 registry bundle，doctor，再跑 mission-builder doctor；
12. 真飞书一题 `带③L：否` 完整 itempool→probe→view、跨 UID、坏 slot、Mac reboot、
    无害 mission/坏补丁/rollback、真云逐项资格化。

任何一步失败都停在前一稳定能力。禁止重复 installer、手改 active/registry、下载模型替代冻结档、
用同 UID fixture 冒充跨 UID、用“进程存在”冒充 semantic healthy。

## 14. 一页速查

```text
看全局：状态
看预算：预算
交目标：开始提交目标书 → 目标书片段 PS-... 1/1 → 结束提交目标书 → 确认目标 PROP-...
做快道：开始快道 → 快道片段 PS-... 1/1（六字段）→ 结束快道
看快道结果：查看快道结果 PROBE-... 1
毕业：毕业这一针 <64hex>
审批：批准 APR-... abc123 v3
拒绝：拒绝 APR-... abc123 v3：原因
问故障：为什么停了 R-...
控制：暂停 R-... / 恢复 R-... / 中止 R-...
下钻：下钻 R-... ifeval_zh_v1 item-008
反思：记录反思 R-... <文字>
云：当前禁止创建/启动/付费；选档前固定安全阻断
历史云资源人的声明：声明已请求销毁云实例 ...（仍须 provider/账单侧独立核验）
当前明确 BLOCKED：正式 execution profile/远端 CUDA 执行、带③L的快道、毕业 P-...、
任务批准/拒绝、生产云；通过 root 部署与真实一题验收后才可用：`带③L：否` 的分段临时
快道、目标书闭环、普通实验审批、状态监控和正式轮证据下钻
只读页：http://127.0.0.1:8765/
```

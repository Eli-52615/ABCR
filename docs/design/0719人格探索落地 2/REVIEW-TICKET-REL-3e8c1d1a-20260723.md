# ABCR reviewed-runtime 正式 review ticket · 第二轮(2026-07-23)

> 本轮对象是 **Fable5 代 codex 完成的 pyc 加固修复提交**。第一轮票据
> `REVIEW-TICKET-REL-b25251d7-20260723.md` 的 REL 已作废留证(其 genesis 必砖,
> 见 `CODEX-P0-缺陷报告-pyc自污染-20260723.md`)。
> 状态机位置:**READY_FOR_HUMAN_ROOT_REVIEW_COPY**,待独立对抗复核放行后交人。

## 0. 治理声明:作者=签名者 的偏差与补偿

codex 缺席,修复由 Fable5 完成——Fable5 同时是修复作者与独立 verifier,
codex↔Fable5 独立性在这次 delta 上不成立。补偿措施:
1. delta 压到最小:5 文件 +21/−13,其中代码语义变更仅 3 处 argv 各加一个 `"-B"`、
   allowlist 加一行、一个钉死 hash 同步;其余是 runbook 文档加 `-B`。
2. **人(楠)亲自过目完整 diff**(嵌在《人类操作指引-阶段1-V2》步骤 0.5)。
3. 独立对抗复核 workflow(3 视角:完备性/正确性副作用/残余威胁)结论记入本票据。
4. codex 回归后可对 `1a7daf1` 做事后复审;本票据与 diff 即审材料。

## 1. 发布身份(exact)

| 项 | 值 |
|---|---|
| reviewed commit | `1a7daf1eb231fe4216b0b97fd4a01e4598550315`(= `936fdd7…` + 修复,分支 `fable5/postclaude-pyc-hardening-20260723`) |
| 基线提交 | `936fdd7227ff803ba8953ba2180bac6250c7dddd`(codex 交付,信任判定见第一轮票据) |
| candidate tree hash | `9dddda012cef55390f9cad87c23cda442675363064c6f191564c20852fde101d` |
| runtime tree hash | `61518b215a3ada4b5a26976bbf776604d743c2dab0134e29b7f0eed8dc77e3d2`(与第一轮完全一致——未动 env/src 运行时) |
| file_count | 20415(= 20414 + 新封印的 `check_human_signature_domain.sh`) |
| release ID | `REL-3e8c1d1a2861a5a9fa72ded08d7a68d68c792c01be63d86fd8c778868c29ec2f` |
| verification hash | `cdeac740cb2c1dcc65b1fde8e707a3ddc7d18e10813c2f0c5583f42bea2fa2d7` |
| release-manifest sha256 | `e1d220d3f48666aa50732af9ce96496cf9fce6555e4e9c107c53ebabb6d183d7` |
| staged tree hash | `392cefb7de078c76bce01c4a9e62c75e92bd4c1880729fea830444f1193491da` |
| staging path | `/Users/superagent/.abcr-build/production-1a7daf1-20260723/release-staging/REL-3e8c1d1a2861a5a9fa72ded08d7a68d68c792c01be63d86fd8c778868c29ec2f.staging` |
| 服务模块 | 恰好 12 个 |
| 新 selector sha256(bootstrap-v1.json 已同步) | `498a1935ceb0765bcddef04e57bc8f28b055b12b8a5c7828ba5db196bc1c253f` |

verifier key 不变:公钥 `/Users/superagent/.abcr-verifier/production-review-verifier.pub`,
fingerprint `6ba3e9e05d1d58e6928b17be0fdebc75840769607956531141f2e837b25401f7`,
PEM sha256 `f55aabc72200b6d457e45d9af72ef172aac5d1cf6c637db44c594e6e119dd376`。
沙箱 profile 不变:`sandbox-exec:551c396bba40f5979865d62ce34598fe97f0ee18f5975011a284a0b5e2bd5cea`。

## 2. 修复内容(提交 `1a7daf1`,5 文件 +21/−13)

1. `bootstrap_abcr_genesis.py`:两个 root 子进程 argv 加 `-B`(genesis 自砖根因)。
2. `abcr-bootstrap-selector`:模块分支 command 加 `-B`(root 服务 seal-broker/
   test-controller 及 root 资格化探针的启动污染)。
3. `ops/install/bootstrap-v1.json`:`stable_selector_sha256` 同步为新 selector 字节。
4. `build_reviewed_runtime.py` allowlist 补 `scripts/check_human_signature_domain.sh`
   (扩展 runbook §6.1 要求从 sealed release 运行,原 allowlist 遗漏,ceremony 会在
   §6.1 撞"文件不存在")。
5. 仓内 runbook §3–§5 staging/root python 命令加 `-B`(9 行)。
   另:共享目录扩展版 runbook(1014 行)的 16 处 root 命令已同步加 `-B`(不在封印树内)。

## 3. 验证记录

- 回归:`PYTHONPATH=src pytest tests`(除 torch 依赖的 stage1–3)= **1464 passed,
  8 skipped, 0 failed**;`tests/control` 418 全绿。codex 基线 1461/4/4(golden/paid
  收集口径差异,零失败一致)。
- Fable5 独立沙箱验证 11 项全 PASS(同第一轮清单;attestation
  `/Users/superagent/.abcr-verifier/attestation-1a7daf1-9dddda01.json`,回执
  `receipts-1a7daf1-9dddda01.json`)。
- `doctor-candidate` rc=78;finalize 与 staged doctor-release(带 `-B` + 目录位锁)
  双输出绑定同一 commit/REL/树/验证/manifest,12 服务。
- 一致性旁证:runtime tree hash 与第一轮逐字一致(未触碰运行时);file_count 恰好 +1。

## 4. 对抗复核结论(2026-07-23 回填)

**多 agent 独立复核 panel 因会话用量上限未能运行**(3 个子 agent 全部
"session limit, resets 10:10am";返回空结果,未当作放行)。Fable5 改为主线内
逐项复核并如实记录:

| 视角 | 结论 | 证据 |
|---|---|---|
| 完备性 | PASS | 全仓 grep 枚举全部冻结 python 派生点并逐个归类:selector:219(已修,覆盖 root 探针+exec)、genesis:624/689(已修)、abcr-launch:416(仅非 root 服务 UID 执行,0550 目录内核级挡写)、installer:1241(candidate argv 模板,seatbelt deny-write 保护且为冻结断言对象)、operator.py:88(abcr-operator 非 root)、bootstrap *.sh(无冻结 python 调用);launcher root 探针 `--bootstrap-doctor` 经系统 python(shebang `/usr/bin/env python3`,纯 stdlib import,pyc 落系统目录,不进被校验树) |
| 正确性/副作用 | PASS | 全树回归 1464 passed/0 failed(含 test_bootstrap_selector、test_genesis_bootstrap、test_reviewed_runtime_builder、test_deployment_contract、test_stable_launcher);唯一钉死常量 `stable_selector_sha256` 已同步且全仓无其他旧 hash 引用;`-B` 隔离实验:同一冻结解释器,无 `-B` 时 import 必写 pyc(复现缺陷机理),加 `-B` 后零写入且 import 结果不变 |
| 残余威胁 | PASS(带 2 条注意) | 新封印的 check_human_signature_domain.sh 为只读探针(唯一写动作在 mktemp 私有目录);ceremony 各写入(receipt/completion/slot)均落在被校验树之外。注意 ①:管理员手敲命令漏 `-B` 会污染 review copy/sealed 树——genesis 前可恢复(删除后按 §4 重复制),阶段指引已全部内嵌 `-B`;注意 ②:不要用 Finder 浏览 review copy/sealed release 目录(.DS_Store 落树即漂移),阶段 2 指引将写明 |

裁定:**SOUND,放行阶段 1**。风险切分:阶段 1(root review copy)本身可逆
(genesis 前删除重来即可);不可逆的 genesis 属阶段 2——若楠要求额外保险,可在
10:10 用量重置后重跑独立 panel,再进入阶段 2。

### 4.1 现场执行发现(2026-07-24 追记)

阶段 1 实操中发现第三颗同类雷,机理经现场证据闭环:doctor 的 `_run` 把子进程
环境清到只剩 `PATH/LC_ALL`,丢掉 `SUDO_UID` 使 git 2.36+ 的 sudo 豁免失效,
root 下 "dubious ownership" 保护拒绝 superagent 名下仓库;且 `_git_path()` 优先
选 Homebrew git(2.53),其系统配置是 `/opt/homebrew/etc/gitconfig` 而非
`/etc/gitconfig`。管理员手敲 `sudo /usr/bin/git` 能通过(SUDO_UID 在),据此第一
版"写 /etc/gitconfig"的处置是错的,已更正为:
`sudo /opt/homebrew/bin/git config --system --add safe.directory <repo>`
(阶段 1 指引步骤 3.5,含 env -i 复现命令)。报 codex:runbook §1 前置应加
"Homebrew git 系统级 safe.directory 登记";doctor 报错文案应区分"提交不存在"
与"git 拒绝访问"(把 stderr 带出来)。

### 4.2 阶段 1 完成记录(2026-07-24)

- incoming doctor 与 FINAL doctor 均 `ok:true`,5 个身份值与本票据 §1 逐字一致,
  12 服务;FINAL 位于 `/Library/Application Support/ABCR-Genesis/reviewed/REL-3e8c1d1a…`。
- Fable5 盘上复核:FINAL 全树 root:wheel、目录 0555/文件 0444/0555、
  `find ! -user root` 为空。
- 执行偏差(已解决,末态与 runbook 规定一致):① mv 被重复执行一次(第二次
  报 ENOENT,无副作用;指引已加"mv 只跑一次"提示);② 当日 incoming 的
  `chown root:wheel` 未生效,mv 后由管理员补执行并经 FINAL doctor + 属主
  复核兜底(顺序偏差:先 mv 后 chown)。
- 楠已按步骤 0.5 过目修复 diff、按步骤 0 亲手复核身份值与 key 指纹。

**阶段 1 判定:PASS。** 阶段 2(§5 genesis)开始前置条件:独立对抗 panel
复跑结论回填(见 §5 未决项)。

### 4.3 独立对抗 panel 结论(2026-07-24 22:05 回填)

panel 三视角完成(completeness=BROKEN / genesis-walk=SOUND / threat=SOUND):

- **P0(Fable5 已亲手复核成立):扩展版 runbook 与代码脱节——激活链工具从未交付。**
  §8.2 `qualify_abcr_genesis_probation.py` 与 §9 `qualify_abcr_autonomous.py` 在任何
  提交/分支/磁盘上都不存在;genesis argparse 无 §8.3 的 `--abort-probation`;
  release 级 `active.json` 在 1a7daf1 只有读者(abcr-launch/genesis 拒入条件),
  首次写入链(probation 协调器→broker activate)不存在。genesis 为全局一次性
  (completion 存在即拒绝重来),现在执行将把名额永久耗在无法激活的 release 上。
  **处置:阶段 2 指引 HOLD,genesis 冻结,待激活链工具交付并出新 release。**
- `-B` 修复本身被三视角判定完备:所有 root 冻结 python 派生点已覆盖或结构性免疫。
- 后续加固清单(下轮提交一并):abcr-launch:416 与 operator.py:88 加 `-B`
  (深度防御);accounts 步骤后核验 `/Users/abcr-probe` home 目录存在(installer
  mkdir parents=False);Finder/Spotlight 远离受校验目录。
- genesis-walk 确认:§5 前置三步(授权/账户/数据集)每缺一步 genesis 都是
  可重试的 fail-closed,不会砖;账户与数据集导入不绑定具体 release,可提前执行;
  **授权安装绑定 release,必须等最终 release 再装**。

### 4.4 阶段 2A 现场发现(2026-07-25,两项 codex 缺陷,均已在修复分支闭合)

1. **服务账户 home 永不物化**:`sysadminctl -addUser` 只写目录服务记录,home 由
   opendirectoryd 在首次交互登录时物化;服务账户 shell=`/usr/bin/false`、
   Password=`*`,永不登录 → 永不物化。安装器对 `/Users/abcr-probe/Library` 用
   `mkdir(parents=False)`,父目录缺失会让 genesis 内嵌安装器 fail-closed。
   现场只有 `abcr-human` 有 home(由 `bootstrap_abcr_human.sh` 显式创建)。
   处置:人工补 `/Users/abcr-probe`(0700,与 human 同形);代码侧
   `bootstrap_abcr_accounts.sh` install 模式已改为自动物化、check 模式缺失即 BLOCKED。
   其余 9 个 home **有意不物化**(最小面:数据全在 /Library 或 superagent 域,
   plist WorkingDirectory=/var/empty)。

2. **macOS nobody 哨兵 gid 使数据集导入必然 BLOCKED(P0 级可用性缺陷)**:
   `validate_exact_dataset_reader_group` 枚举每个可见目录用户做 effective 成员校验,
   而原厂 macOS 有 28 个内置账户(nobody/_installer/_ftp/_krbtgt/_avbdeviced …)
   primary gid = 4294967294(哨兵 −2 的无符号拼写)。`os.getgrouplist` 要有符号
   C int(拒该值),`grp.getgrgid` 要无符号 32 位(拒 −2),而 `_identity` 只捕获
   (KeyError, OSError) → OverflowError 逃逸 → 整个导入失败。**任何原厂 macOS 必然
   触发**,数据集永远装不上。账户脚本走系统 `id` 故不受影响(这解释了步骤 2 过、
   步骤 4 挂)。处置:引入 gid 拼写归一化(`_canonical_gid`/`_c_int_gid`),
   importer 与 installer 两处同步修正,异常元组补 OverflowError/ValueError 保持显式
   fail-closed;实机验证组集合与系统 `id -Gn` 逐项一致。

**影响**:阶段 2A 的账户+home 部分已完成且与 release 无关(可复用);**数据集导入
必须等装有修复版 importer 的新 release**,不得从 dirty checkout 运行修复版脚本。

## 5. 未决项

- [ ] 对抗复核结论回填(§4)。
- [ ] 人:阶段 1(V2 指引)——过目 diff → 逐项比对 → root review copy。
- [ ] 人(可并行):准备 production 飞书凭据与 owner 四元组(§6.1 输入)。
- [ ] codex 回归后:事后复审 `1a7daf1`;评估把共享扩展版 runbook 收编进仓。
- [ ] 阶段 2+(genesis/账户/数据集/probation/12 doctor)按扩展 runbook 分阶段发指引。

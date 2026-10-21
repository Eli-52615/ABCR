# ABCR reviewed-runtime 正式 review ticket(2026-07-23)

> 本票据由 Fable5 按 `CODEX-POSTCLAUDE-部署与资格化交接-20260722.md` §4/§5 建立并执行完毕。
> 状态机位置:**READY_FOR_HUMAN_ROOT_REVIEW_COPY**(未获 root authority,未启动任何服务)。
> 下一步是人:逐项比对 + root 原子 review copy(见《人类操作指引-阶段1》)。

## 1. 发布身份(exact,不得用 branch/tag/HEAD 替代)

| 项 | 值 |
|---|---|
| reviewed commit | `936fdd7227ff803ba8953ba2180bac6250c7dddd` |
| 来源 | bundle `/Users/superagent/.abcr-build/abcr-postclaude-936fdd7.bundle`(verify OK,完整历史),已 fetch 为 canonical 仓分支 `codex/postclaude-completion-20260722`,未合并 main |
| candidate tree hash | `52bd909a82725393608748e064c2fcdd951ae54deefd18a6274dc52509e3b140` |
| runtime tree hash | `61518b215a3ada4b5a26976bbf776604d743c2dab0134e29b7f0eed8dc77e3d2`(与 codex 审计候选逐字一致 → 构建可复现) |
| file_count | 20414,0 symlink |
| release ID | `REL-b25251d759ebfae28dc374474facd35448c8edbd96b568ea9470ebde1c274b02` |
| verification hash(= attestation hash) | `2d4d1fd3f1964b34e6921ab0ad74a711b88f01064f6b70a74bbb1d4eda1d1d20` |
| release-manifest sha256 | `eb00e35dd5a701151952302f526fb9a5702e5eefee1608f81884e4d112122400` |
| staged tree hash | `3ffbeac33e3889557c499fa31ed4f3c5ae896b389057d1f957318a30930278a4` |
| staging path | `/Users/superagent/.abcr-build/production-936fdd7-20260723/release-staging/REL-b25251d759ebfae28dc374474facd35448c8edbd96b568ea9470ebde1c274b02.staging` |
| 服务模块 | 恰好 12 个(finalize 与 doctor-release 输出一致) |

## 2. 正式 verifier key(production,非临时审计 key)

| 项 | 值 |
|---|---|
| 公钥 | `/Users/superagent/.abcr-verifier/production-review-verifier.pub`(regular file,单链接,644) |
| 公钥 PEM sha256 | `f55aabc72200b6d457e45d9af72ef172aac5d1cf6c637db44c594e6e119dd376` |
| key fingerprint(DER sha256,= attestation key_id) | `6ba3e9e05d1d58e6928b17be0fdebc75840769607956531141f2e837b25401f7` |
| 私钥 | `/Users/superagent/.abcr-verifier/production-review-verifier.key`(0600,单链接;在 candidate/release/checkout/仓库之外,**不得移动、复制或展示内容**) |
| 生成工具 | Homebrew OpenSSL 3.6.3(系统 LibreSSL 不支持 Ed25519) |

codex 审计轮的临时 key 候选(tree `03c37dd1…`,位于 `reviewed-936fdd7.DSSr6B/`)按交接文档保留为审计证据,**未被**用于本次发布。

## 3. Fable5 独立沙箱验证(签名前置,全部 PASS)

- 驱动脚本:`/Users/superagent/.abcr-verifier/fable5-verify-and-attest.py`(仓外;期望值/比对/判定全在父进程,child 无判定权)。
- 回执:`/Users/superagent/.abcr-verifier/receipts-936fdd7-52bd909a.json`;attestation:`/Users/superagent/.abcr-verifier/attestation-936fdd7-52bd909a.json`。
- 沙箱:候选树内 `ops/sandbox/abcr-candidate.sb`(deny-default),isolation 标签 `sandbox-exec:551c396bba40f5979865d62ce34598fe97f0ee18f5975011a284a0b5e2bd5cea`。
- 11 项检查:tree/runtime hash 独立重算一致;status-card-v1 与 doc-marker-v1 冻结 oracle 精确匹配 + nonce 回显;未知 oracle 拒绝(rc2);篡改 profile 拒绝(rc2);沙箱真实性三探针(读 `/Users/superagent` 拒绝、网络拒绝、沙箱外写拒绝)成立;合法 import 放行。
- attestation 以候选**内嵌**公钥自验通过后才交付 finalize。

## 4. 偏差记录(均已复核,不改变任何文件条目字节/mode)

1. **staging 目录位锁 0555**:`stage_release`(`export_plain_tree`)产出的目录默认 755,staging 树自己的 Python 启动即写 `__pycache__/*.pyc` 污染树,runbook §3 的 doctor-release 原样执行必 BLOCKED(首轮实测:staging 多出 112 个 pyc,`release manifest does not describe exact staged bytes`)。处置:删除污染 staging → 重新 finalize(确定性,复现同一 REL/同一 staged tree hash)→ `find -type d chmod 0555` → doctor-release 原样通过。目录不进树身份(`scan_tree` 只记录文件),文件条目零改动。
2. **root 阶段 python 一律加 `-B`**:root 无视目录只读位,§4 起每次 root 调用 review copy 里的 Python 都会写 pyc 污染树。阶段 1 指引已在两条 sudo doctor-release 加 `-B`(仅禁写字节码缓存,不改变验证语义)。§5+ 的完整爆破面审计进行中(见 §6)。

## 5. 对 codex 的 P1 runbook 缺陷报告(不影响本轮交付有效性)

`REVIEWED-RUNTIME-INSTALL.md` §3/§4 的 doctor-release 按原文执行会被解释器字节码缓存自我污染(`-I` 会忽略 `PYTHONDONTWRITEBYTECODE` 环境变量,§6.2 的环境变量写法在 `-I` 下同样无效)。建议 runbook v2:所有从 staging/review copy 直接调用 python 的命令统一加 `-B`,或 `export_plain_tree` 落盘后锁目录位。

## 6. 未决项(2026-07-23 审计后修订)

- [x] pyc 爆破面审计完成(6-agent 对抗复核 + Fable5 亲自二次确认关键链路):**genesis 两个 root 子进程与 selector exec 均无 `-B`,seal-broker/test-controller plist 以 root 运行 → `936fdd7` 走不通自己的 ceremony,genesis 必砖、服务链会整机砖**。详见 `CODEX-P0-缺陷报告-pyc自污染-20260723.md`。
- [ ] **本 REL 状态改为:审计证据保留,禁止进入 §4 root copy**(阶段 1 指引已标 HOLD)。
- [ ] codex:按 P0 报告出修复提交(2 处 argv 加 `-B` + 结构性加固)。
- [ ] Fable5:对修复后的新 exact commit 重跑 §1–§3(重建/沙箱验证/重签/finalize),出新 REL 与新版阶段 1 指引。
- [ ] 人:新版阶段 1 逐项比对 + root review copy;并行准备飞书 production 凭据与 owner 四元组(§6.1 输入)。
- [ ] LIVE_PILOT / AUTONOMOUS_QUAL 各门按交接文档 §8 顺序另行资格化。

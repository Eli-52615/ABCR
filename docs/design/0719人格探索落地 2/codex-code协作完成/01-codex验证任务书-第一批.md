# codex 验证任务书 · 第一批（2026-07-26）

> 先读同目录 `00-协作契约-codex与code分工.md`。
> **你的角色是独立 verifier。发现问题只报告，不要动手修。不写实现代码。**

---

## 0. 验证对象

| 项 | 值 |
|---|---|
| 仓库 | `/Users/superagent/shared-brain/ABCR/abcr` |
| 工作副本 | `abcr/.claude/worktrees/runbook-manifest-assert`（分支 `round8-loop`） |
| 基线 | `b65fdc2`（第七轮交付，对应已作废的 `REL-17624261`） |
| **待验 commit** | `f8b4e41` 与 **`8887186`**（后者是本批重点） |
| 全量回归现状 | 1528 passed / 8 skipped / 0 failed |

本批**尚未**构建新 candidate。构建 V4 的流程见 §4——按新分工，**沙箱验证与签名由你做**。

---

## 1. 重点验证：第八轮 P0 修复（`8887186`）

### 缺陷是什么

`install_abcr_runtime.py` 里的 `enforce_release_scientific_content_policy` 自称是
`src/abcr/control/release_policy` 的 "Standalone stdlib port"，移植时漏了两处：

1. **tar hardlink 成员**：原版 `release_policy.py:174` 显式放行并解析 target；移植版
   `install_abcr_runtime.py:317` 直接 `member.islnk()` 即拒。而真实封印 release 内
   `env/lib/python3.12/site-packages/dateutil/zoneinfo/dateutil-zoneinfo.tar.gz`
   **实测含 245 个 hardlink 成员**。调用链
   `verify_receipt():515 → enforce_release_scientific_content_policy():544 → _scan_policy_tar`
   → 必然 `InstallBlocked`，且在任何 root-owned 文件落地之前 → **genesis 装不进去**。
2. **重名成员检测**：原版建 `by_name` 映射并拒重复，移植版完全没有。

### 请你独立判断

- [ ] 修复是否**语义等价于原版**，而不只是「让测试变绿」？逐行比对
      `release_policy._scan_tar` 与 `install_abcr_runtime._scan_policy_tar`。
- [ ] `expected_size = target.size` 这个处理对吗？（hardlink 成员自身 `size` 为 0，
      若不改会把读到的真实内容判成 drift）
- [ ] 放行 hardlink 是否**削弱了安全边界**？特别是：能否构造一个 hardlink，
      使某个本应被 `FROZEN_SCIENTIFIC_SHA256` 拦截的字节绕过检测？
- [ ] symlink、悬空 hardlink、跨归档引用是否仍然被拒？
- [ ] 新测试 `tests/control/test_policy_port_equivalence.py` 是否真的能挡住回归？
      **建议实测**：把修复回退，确认测试变红（这是 code 声称做过的，请你独立复现）。

### 已知的其他移植偏差（code 已核实为**不存在**，请你复核这个结论）

有线索称 `installer._policy_name` 缺少原版 `_safe_name` 的字符检查（空值 / 反斜杠 /
NUL）。code 实测该检查**存在**于 `install_abcr_runtime.py:242-244`，两侧等价，
并已把该维度纳入等价性测试（8 个参数化用例）。请独立确认。

---

## 2. **root 语义验证（本批的核心，只有你能做）**

这是八轮里最大的测试盲区：**全套件零测试以 `euid==0` 运行**。以下每一项都请**真的用 sudo 跑**，
不要只做静态判断。

### 2.1 tar 策略在 root 身份下的真实行为

`verify_release_read_policy` 与 `enforce_release_scientific_content_policy` 都要求
root + 真实 gid，测试里一律被 monkeypatch 掉——**轮6 那个 P0 就是这么活过六轮的**。

```sh
# 拿真实封印产物里的那个 tar，以 root 身份跑修复后的策略
S="/Users/superagent/.abcr-build/production-b65fdc2-20260725/release-staging/REL-1762426112003c82c30832d2277917eb245f166c104bbe6723341ed5e7c246e6.staging"
T="$S/env/lib/python3.12/site-packages/dateutil/zoneinfo/dateutil-zoneinfo.tar.gz"
# 期望：接受（修复前会 InstallBlocked）
```

- [ ] 以 root 跑，确认真实 tar 被接受
- [ ] 确认非法样本（symlink / 悬空 hardlink）在 root 下仍被拒

### 2.2 pyc 自污染防线是否真的成立（历史 P0 #1）

机理：`-I` 隐含 `-E`，使 `PYTHONDONTWRITEBYTECODE` 失效；root 又无视目录只读位，
于是解释器启动阶段的 stdlib import 就把 `__pycache__/*.pyc` 写进被校验树。
**非 root 身份下这件事物理上不会发生**——所以这道防线从未被真实验证过。

```sh
# 以 root 跑封印树自带的解释器，然后检查树内是否出现 __pycache__
sudo "$S/env/bin/python" -I -B -c "import json, hashlib, tarfile"
find "$S" -name "__pycache__" -o -name "*.pyc" | head
# 期望：零输出
# 对照实验：去掉 -B 再跑一次，确认确实会写入（证明 -B 是唯一屏障，而非碰巧不写）
```

- [ ] 带 `-B` 时零写入
- [ ] **去掉 `-B` 时确实写入**（若不写，说明防线的前提假设有误，请如实报告）

### 2.3 全仓 root-python 调用点是否都带 `-B`

```sh
grep -rn '"-I"' scripts/ src/ | grep -v '"-B"'
```

- [ ] 逐个判断：该调用点是否以 root 运行？若是而无 `-B`，即为同类 P0 复发

### 2.4 账户与组的真实状态

```sh
sudo dscl . -list /Users | grep abcr
id abcr-probe; id abcr-human
```

- [ ] 11 个服务账户状态与票据记载是否一致
- [ ] 注意：账户加固已**有意摘出**（分支 `fable5/accounts-hardening-deferred`，
      commit `947a895`），当前已知弱点：主组为 `staff`、角色组只校验 ⊆ 不校验 =、
      已存在账户属性不复验、root 闸在 `id -u` 返回非数字时失败开放。
      **这些不是本批要修的**，但请确认「当前实机无实际暴露」这个结论是否仍成立。

---

## 3. 静态审查：`f8b4e41`（runbook 引用守门）

- [ ] `scripts/check_runbook_refs.py` 的路径提取是否有**漏网形态**？
      （它按 `scripts|src|ops|configs|data` 起头识别，你能否构造一个 runbook 里
      真实存在、而它抓不到的引用？）
- [ ] `KNOWN_ABSENT` 的 3 条豁免是否合理？（都指向 AUTONOMOUS_QUAL 门，
      票据 §5 残余风险第 4 条明示该门保持 BLOCKED）
- [ ] 该检查器**不得进封印树**（`scripts/` 下只有 `GIT_EXACT` 那 13 个进树）。
      测试 `test_checker_itself_stays_out_of_the_sealed_tree` 断言了这一点，请复核。

---

## 4. 构建 V4 的分工（本批验证通过后进行）

按新分工，构建流程在中间**交给你**：

| 步骤 | 谁 | 动作 |
|---|---|---|
| 1 | code | `build_reviewed_runtime.py build` 出 candidate |
| 2 | code | `doctor-candidate` → 期望 rc=78（`BLOCKED / SIGNED_VERIFICATION_REQUIRED`） |
| **3** | **codex** | **独立沙箱验证 + 签 PASS attestation**（这是架构原本要求、因你缺席而坍塌了八轮的那一步） |
| 4 | code | `finalize` + staged `doctor-release`，出新 REL 与人类阶段1 V4 指引 |
| 5 | 人（楠） | 阶段 1：核对身份值 + root review copy |

**第 3 步的私钥在 `/Users/superagent/.abcr-verifier/production-review-verifier.key`（0600）——
不得移动、复制或展示内容。** 公钥 fingerprint `6ba3e9e05d1d58e6928b17be0fdebc75840769607956531141f2e837b25401f7`，
全程同一把。

---

## 5. 回执格式

```
裁定：SOUND / BROKEN / INVALID

若 BROKEN，逐条：
  [P0/P1/P2] <一句话> | <file:line> | <可复现命令与实际输出>

若 SOUND：
  attestation 路径、key fingerprint

root 验证记录（必填，逐条对应 §2）：
  2.1 实跑命令 + 实际输出
  2.2 带 -B / 不带 -B 两次的实际结果
  2.3 grep 结果与判断
  2.4 账户实况

未能完成的项（必填）：
  <哪些没跑成、为什么>  ← 空结果不算放行，如实写
```

**最后一条最重要**：任何跑不成的项都要显式列出。历史上 panel 两度撞用量上限返回空结果，
当时正确地判了「不算放行」；而 2026-07-26 第八轮首跑，工作流把「agent 被杀」当成
「零发现」，报出了假的 clean——**缺失证据不是阴性证据**。

# V4 candidate 交付单 → codex

> 交付时间：2026-07-26。交付人：code。
> 状态机位置：**`BLOCKED / SIGNED_VERIFICATION_REQUIRED`**（runbook §3 的 STOP 点）。
> **下一步是你。** 这一步（独立沙箱验证 + 签 PASS attestation）是架构本来就要求、
> 因你缺席而坍塌了八轮的那一环。

---

## 1. 发布身份（exact，逐字核对）

| 项 | 值 |
|---|---|
| **reviewed commit** | `ce6c80ed189a0d407e1e320c3b3e69d4e50a8fa6` |
| candidate tree hash | `4f0f9fdc69bb58ed1cf06bc800e1c6053b3209e96b104171715103b3d565db6d` |
| **runtime tree hash** | `46adc351f51f6f7c2d827214239158b2dd7dde5af00d2f3e86ee57409afb794c` |
| file_count | `20417` |
| candidate 路径 | `/Users/superagent/.abcr-build/production-ce6c80e-20260726/candidate`（440 MiB） |
| doctor-candidate | **rc=78**，`blocking_gate: SIGNED_VERIFICATION_REQUIRED` ✅ |
| resource_mirrors | 2 个，均已绑定 ✅ |
| verifier 公钥 | `/Users/superagent/.abcr-verifier/production-review-verifier.pub`，fingerprint `6ba3e9e05d1d58e6928b17be0fdebc75840769607956531141f2e837b25401f7`（全程同一把） |

> **runtime tree hash 与 `REL-17624261` 逐字一致** —— 说明本轮 P0 修复同样没有触及
> 进入服务进程的代码。该 hash 自 `85a1561` 起**五版未变**，与前七轮模式一致：
> 修的全部是部署管线。

---

## 2. 基线对比（相对已作废的 `REL-17624261`）

| | b65fdc2（旧） | ce6c80e（本次） |
|---|---|---|
| candidate tree | `ebff6aad…` | **`4f0f9fdc…`**（变，因 `install_abcr_runtime.py` 修改） |
| runtime tree | `46adc351…` | `46adc351…`（**不变**） |
| file_count | 20417 | 20417（不变） |
| 全量回归 | 1502 passed | **1545 passed / 8 skipped / 0 failed** |

### 本次相对基线的三个提交

| commit | 性质 | 是否进封印树 |
|---|---|---|
| `f8b4e41` | runbook 引用完整性守门（新脚本 + 9 测试） | **否**（`scripts/` 只有 `GIT_EXACT` 那 13 个进树） |
| `8887186` | **轮8 P0 修复**：安装器策略移植版对齐 `release_policy`（tar hardlink + 重名成员）+ 17 用例等价守门 | **是**（`install_abcr_runtime.py` 在 allowlist 内 → 这是 candidate hash 变化的唯一原因） |
| `ce6c80e` | canonical JSON 五份实现字节级一致守门（17 用例） | **否**（只加 `tests/`） |

**即：封印树的实际变更只有 `install_abcr_runtime.py` 的 32 行**（`git show 8887186 -- scripts/install_abcr_runtime.py`）。

---

## 3. 你要做的三件事

### 3.1 独立沙箱验证

历史上这一步由 code 用 `/Users/superagent/.abcr-verifier/fable5-verify-and-attest.py`
（9,120 B，仓外）驱动，11 项检查。**该脚本存在，但请勿直接复用它出结论**——那样等于
用被验方的工具验被验方，独立性依然不成立。正确用法是：**把它当作参照物去审查**
（它验了什么、漏了什么），你自己独立重算关键量。

至少覆盖：
- [ ] 独立重算 candidate tree hash 与 runtime tree hash，与 §1 逐字比对
- [ ] 冻结 oracle 精确匹配 + nonce 回显
- [ ] 未知 oracle 拒绝、篡改 profile 拒绝
- [ ] 沙箱真实性三探针（读宿主主目录被拒 / 网络被拒 / 沙箱外写被拒）
- [ ] 合法 import 放行
- [ ] attestation 必须以**候选内嵌公钥**自验通过后才交 finalize

沙箱 profile 在候选树内 `ops/sandbox/abcr-candidate.sb`（deny-default）。
历史 isolation 标签：`sandbox-exec:551c396bba40f5979865d62ce34598fe97f0ee18f5975011a284a0b5e2bd5cea`。

### 3.2 **root 语义验证（重点，只有你能做）**

详见同目录 `01-codex验证任务书-第一批.md` §2。摘要：

- [ ] **2.1** 以 root 跑修复后的 tar 策略，确认真实 `dateutil-zoneinfo.tar.gz`（245 个
      hardlink 成员）被接受；非法样本仍被拒
- [ ] **2.2** 以 root 跑封印树自带解释器，带 `-B` 时零 pyc 写入；**去掉 `-B` 时确实写入**
      （若不写，说明该防线的前提假设有误，如实报告）
- [ ] **2.3** `grep -rn '"-I"' scripts/ src/ | grep -v '"-B"'` 逐个判断是否 root 路径
- [ ] **2.4** 账户与组实况，确认「摘出的账户加固当前无实际暴露」这个结论仍成立

### 3.3 签 PASS attestation

私钥 `/Users/superagent/.abcr-verifier/production-review-verifier.key`（0600）——
**不得移动、复制或展示内容**。历史 attestation 命名惯例：`attestation-<commit7>-<tree8>.json`，
本次即 `attestation-ce6c80e-4f0f9fdc.json`。

---

## 4. 本批的重点审查对象

按 `01-验证任务书` §1。核心是那 32 行修复是否**语义等价于原版**，以及放行 hardlink
**是否削弱了安全边界**（特别是：能否构造 hardlink 让本应被 `FROZEN_SCIENTIFIC_SHA256`
拦截的字节绕过检测）。

另请复核两个 code 自己得出的结论：
1. `installer._policy_name` 与 `release_policy._safe_name` 等价（code 实测两侧都有
   空值/反斜杠/NUL 检查，已纳入 8 个参数化用例）；
2. 新增测试确实能挡回归（code 声称把修复回退后测试变红，请独立复现）。

同时参考 `03-跨组件契约地图.md` §2 的「仍不一致但真实产物都通过」清单——
code **有意未修**这些（避免扩大受审面），但它们是你验证时的高危区索引。

---

## 5. 你完成后，code 会做

1. 拿你的 attestation 跑 `finalize` + staged `doctor-release`
2. 出新 REL 与 review ticket
3. 写人类阶段 1 V4 指引（**并修正**步骤 0.5 的 git diff 范围错误——见
   `02-第八轮findings处置清单.md`，现版本会让人漏看第五/六/七轮，即两个 P0 的修复）
4. 楠执行阶段 1

**若你判定 BROKEN**：只报告，不要修。code 修完出新 exact commit 再交你复验。

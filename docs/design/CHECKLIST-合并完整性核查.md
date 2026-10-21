# CHECKLIST — 合并完整性核查(防"改的分支≠合并的分支")

> 用途:在**声称 main 是最新最正确版之前**、**任何多分支加固/重构收尾时**、**合并前**跑一遍。
> 由来:2026-07-20 阶段7——fix-round1 修好一整条授权/运维/资源加固线却没进 main(合的是 r2 另一条线),
> 靠本方法穷举出来。教训见 `ABCR-ENGINEERING-HISTORY.md` 阶段6/7。
> 活文档;发现新陷阱就补。所有命令在仓根跑(`cd .../ABCR/abcr`)。

---

## 0. 三条铁律(先记住,再看步骤)

1. **`git diff` 返回 0 行 ≠ 两版相同**。若 `<rev>:<path>` 在某一侧**不存在**,git 报错、被 `wc -l` 当成"零差异"。
   凡判"已在 main"必须**先证文件两侧都存在**(见 §3 的 `cat-file -e`)。
2. **"改的分支≠合并的分支"**。分支上加固得再好,没进 main = 没做。**平行实现**(如 `rig/x.py` 与 top-level `x.py`
   同名并存)会制造"合了 B 线、加固在 A 线"的错配——务必查清 main 跑的是哪一份。
3. **移植时绝不覆盖已验证的加固版**。main 若已有独立加固过的版本(◆),冲突时**改被移植方去兼容它**,不回退它。

---

## 1. 穷举:哪些分支有 main 缺的提交(rev-list,非抽查)

```bash
for b in $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes); do
  [ "$b" = "main" ] && continue
  ahead=$(git rev-list --count main..$b 2>/dev/null)
  [ "${ahead:-0}" -gt 0 ] 2>/dev/null && printf "%-42s ahead=%s\n" "$b" "$ahead"
done
```

`ahead>0` = 该分支有 main 没有的提交。**一个都不能跳过**——逐个在 §2 定性。

## 2. 定性每个 ahead 分支(排除噪声,锁定真源)

对每个候选:`git log --oneline main..<branch>` 看提交,归入一类:
- **重复/迁址**:提交内容与 main 已有的等价(如迁址常量)→ 无独有代码,排除。
- **临时工作流分支**(worktree-wf-* 等):其提交是别的分支的子集(`git log` 显示同 hash)→ 零独立内容,排除。
- **新任务/在建**:与本次目标无关的独立工作 → 排除(必要时问人)。
- **真源**:确有 main 缺的改进 → 进 §3 逐文件核查。

## 3. 逐文件三方定位(真源分支 vs main vs 基线)

先定基线 = 真源分支与 main 的分叉点:
```bash
BASE=$(git merge-base main <realsrc>);  SRC=<realsrc-tip>
```
对真源改的每个文件(`git diff --name-only $BASE $SRC`)算两个量并**先验存在性**:
```bash
for f in $(git diff --name-only $BASE $SRC | grep '\.py$'); do
  # 存在性(破 diff-0 陷阱):main 有没有这个文件
  git cat-file -e main:"$f" 2>/dev/null && inmain=yes || inmain=NO
  dmf=$(git diff main:"$f" $SRC:"$f" 2>/dev/null | wc -l | tr -d ' ')   # main vs 真源
  dmb=$(git diff $BASE:"$f" main:"$f" 2>/dev/null | wc -l | tr -d ' ')  # main vs 基线
  printf "%-40s inmain=%s dmf=%s dmb=%s\n" "$f" "$inmain" "$dmf" "$dmb"
done
```
判读:
| inmain | dmf | dmb | 含义 | 动作 |
|:--:|:--:|:--:|---|---|
| NO | — | — | 真源**新增**文件,main 没有 | 若被移植文件依赖 → **必须同批带入** |
| yes | 0 | * | main 已 == 真源版 | 无需动 |
| yes | >0 | 0 | **main = 未加固基线原版**(真缺口候选)| → §4 判活/死 |
| yes | >0 | >0 | main 有自演化版(可能是◆加固版)| 人工比对:真源有没有 main 缺的 fix |

## 4. 判活/死(缺口候选是不是真在跑)

平行实现里 top-level 版常是死代码。用**反向依赖**判(注意:避免 zsh 未匹配 glob 中断,只 grep 存在的目录):
```bash
base=$(basename "$f" .py)
grep -rlE "import .*\b${base}\b|from abcr[^ ]*${base}" src scripts 2>/dev/null \
  | grep -vE "/${base}\.py$|test|__pycache__"
```
- 被**活入口**(dispatch/runner/auditor/abcrctl/preflight/run_r2_batch/a_views…)引用 → **活代码,真缺口**。
- 只被死平行区或无引用 → 死代码,main 正确排除,不移植(basename 会同时命中 top-level 与 rig/ 版,按引用方实际路径判)。

## 5. 移植 + 复验(收口)

- **移植**:`inmain=yes,dmb=0`(main==基线)的活缺口,取真源版是文本干净的:`git show $SRC:src/abcr/<f>` → Write 落地;
  依赖的新增文件(§3 inmain=NO)**同批带入**,否则 import 即崩。
- **不碰 ◆**:列出 main 已加固过的文件清单,移植 owner 只读它们、冲突改被移植方。
- **对抗复验**:对每个原缺口在**已移植的 main** 上真跑攻击 + **阴性对照**(去掉修复应翻转,证检出力),判 CLOSED/STILL_OPEN。
- **守基线**:控制面全套 / preflight 30/30 / fake 全链 / W1 套,与已知基线数对比,**0 新增回归**(疑似回归用
  `git archive HEAD src|tar -x` pristine 对照复现后定性)。
- **亲验最高影响项**:主控自己跑 1–2 个关键缺口的复现,不只信 agent 报告(防"说修好了其实没有")。

## 6. 收尾提交纪律

- 提交前 `git status --short` 审暂存集:**只含源码/测试/脚本**,剔除运行产物(anchors/seals、demos/、
  configs/envelopes/、review/*.json 等——被测试重跑污染的 tracked 输出用 `git checkout HEAD -- <path>` 回滚)。
- 显式 `git add <具体文件>`,**不用 `git add -A`**(防夹带产物)。
- 提交后再跑一次 preflight 终验。本仓**永不 push**(楠 git 决策)。

---

## 一句话流程

**rev-list 穷举全分支 → 定性排噪声锁真源 → 逐文件三方定位(先破 diff-0 陷阱)→ 判活/死 → 干净移植不碰◆ → 对抗复验+守基线 → 干净提交。**

# 最小快道 · 使用说明

> **学习数据 · 不可引用。** 这条快道产出的每一行、每一页都带 `citable=false`。
> 它是给人做"实验 → 看结果 → 改假设 → 再实验"的本机工具，
> 不是证据道：这里的数字不能进任何对外结论、正式报告或 promotion。

---

## 每天就一条命令

```bash
cd /Users/superagent/shared-brain/ABCR/abcr
PYTHONPATH=src .venv312/bin/python scripts/probe_quick_loop.py
```

它启动本机页面并自动打开浏览器（默认 `http://127.0.0.1:8787/`）。
`Ctrl-C` 停止；关掉就没了，不装服务、不写 launchd、不改开机项。

嫌敲命令麻烦，也可以直接双击 **`lab/fastlane/start-fastlane.command`**，
效果完全一样（它只是上面那条命令的一层壳）。

### 端口被占用了不用你管

8787 只是"没说的时候用哪个"的**起点**，不是硬性要求。本机上它完全可能已经被
别的长期服务占着（实测 8787 被 AILH BOSS 控制台长期占用、8788 被另一个服务占用）。
这种时候快道**自动让位**，改用系统分配的空闲端口，并把真实地址打出来：

```text
[fastlane] 127.0.0.1:8787 已被别的程序占用，改用系统分配的空闲端口
[fastlane] 页面已启动: http://127.0.0.1:51665/
```

浏览器也按**实际绑到的**端口打开，所以双击入口照常能用，你什么都不用做。

但**显式指定的端口不会被偷偷换掉**：`--port 8787` 是你明确表达的意图，
被占用时快道当场报 `port_in_use` 并停下，而不是把你送到另一个地址干等。
想让系统随便挑一个空闲端口，写 `--port 0`。

---

## 页面上有什么

### 新实验

| 字段 | 说明 |
|---|---|
| 本轮假设 / 预测 | 必填。可以写多行，提交时会折成单行（科学核心要求 prediction 单行），换行处以 ` / ` 连接。原文照样存着，复制这一轮时能原样拿回来。 |
| 人格文本 | 必填。原样拼在题目前，作为 persona 臂的 prompt。 |
| 题量 | 1–20，默认 20。 |
| seed | 默认 1。**同 seed + 同题量恒选同一批题**——所以改假设时题目不会漂移，两轮才可比。换 seed 才换题。 |

vanilla 臂是系统自动带的，不需要也无法关掉。
模型、量化档、题集、③L 都不在页面上，避免实验之间悄悄漂移。

### 结果

- 两臂的通过率与**差值**（persona − vanilla）；
- 输出长度、hedging 句率、自检标记句率等确定性指标；
- **每一道题**的题面、两臂原始输出、判分、row hash；
- 实际模型指纹、seed、题量、耗时、dev bundle 与数据集 sha256；
- 顶部永久横幅：学习数据 · 不可引用。

**身份值一律显示完整 64 位，且可复制**（引擎指纹、bundle id / manifest hash /
source hash、数据集与 split 的 sha256、封印公钥指纹、请求指纹、每一条 row hash）。
它们在页面上装在一个单击即全选的小框里，可以直接和 `ollama show`、
`lab/runs/notebook/rows/<row_hash>/`、`lab/runs/bundles/<bundle_id>/` 逐字比对——
**能逐字比对正是这些值存在的全部理由**，所以这里不做任何截断。

页面**只展示观察到的数字**，不替你判断人格理论成立或失败。
没有显著性检验，没有结论文案——差值就是差值。

### 再做一轮

点「基于本轮新建」→ 上一轮的假设、人格、题量、seed 全部预填 →
你改完再点开始 → 产生新的 `probe_id`，新轮记 `parent_probe_id`。
**旧轮内容和 hash 一个字都不变，随时还能看。**

快道不会自动改假设、也不会自动开下一轮——那是你的活。

---

## CLI 后备

页面出问题时，同一份逻辑有命令行入口：

```bash
cd /Users/superagent/shared-brain/ABCR/abcr
export PYTHONPATH=src

.venv312/bin/python scripts/probe_quick_loop.py check    # 只读体检，不跑任何一题
.venv312/bin/python scripts/probe_quick_loop.py run --hypothesis "…" --persona-file p.txt -n 20 --seed 1
.venv312/bin/python scripts/probe_quick_loop.py list      # 全部轮次
.venv312/bin/python scripts/probe_quick_loop.py show <probe_id>   # 详情（--json 出原始记录）
```

嫌长可以用双击入口带参数，效果一样：

```bash
./lab/fastlane/start-fastlane.command check
./lab/fastlane/start-fastlane.command list
```

> **不要把整条命令塞进一个变量再执行**（旧版说明里的 `P="PYTHONPATH=src …"; $P check`
> 是错的，实测 `bash: PYTHONPATH=src: command not found`，rc=127）。原因是
> **赋值前缀在展开之前就被 shell 认掉了**：`VAR=x cmd` 只有当 `VAR=x` 以字面形式
> 出现在命令位置时才是环境赋值；从变量展开出来的 `PYTHONPATH=src` 已经错过那一步，
> 只会被当成一个叫 `PYTHONPATH=src` 的可执行文件去找。所以要么像上面那样先
> `export`，要么写成 `env PYTHONPATH=src .venv312/bin/python …`。

退出码：`0` 成功；`1` 快道停止（含引擎停止、契约拒绝、有轮次读不出来）；`2` 用法错误。

---

## 固定不变的坐标

```text
模型      qwen2.5:7b / profile qwen25-7b-q4-v1（冻结）
题集      ifeval_zh_v1 的 dev（42 题池，只碰 dev）
实验臂    vanilla + 1 persona
③L        关闭        judge   关闭
性质      citable=false · 学习数据 · 不可引用
```

---

## 出错了会怎样

快道在下面这些情况**明确停止**，不下载模型、不换模型、不上云、不降级为夹具：

| 你会看到 | 意思 | 怎么办 |
|---|---|---|
| `engine_stopped` | Ollama 不可达 / 模型不在 / 指纹漂移 / 600 秒读超时 | 先跑 `check`，按它报的原因修 |
| `port_in_use` | 你**显式**指定的端口被别的程序占着 | 腾出它，或改用 `--port 0`；不指定端口时快道会自动让位，不会报这个 |
| `engine_profile_rejected` | 冻结 profile 与本机后端对不上（换过 ollama 版本？） | 别改 profile 去迁就；先确认后端为什么变了 |
| `split_bytes_not_frozen` / `dataset_bytes_not_frozen` | 仓内冻结的 split / 数据集被改过一个字节 | 数据出问题了，别继续跑；先查谁改的 |
| `split_not_frozen_path` / `dataset_not_frozen_path` | 有人把快道指向了仓外的一份数据 | 快道只跑仓内冻结件 |
| `split_family_mismatch` | split 声明的 family 不是 `ifeval_zh_v1` | **最要紧的一条**：换 family 会整体改变切分，holdout 会被算成 dev |
| `split_salt_mismatch` | salt 不是协议常量（`abcr.rig.splits.SALT`） | 同上，切分判据被动过 |
| `split_identity_mismatch` | split 内部自洽，但不是仓内冻结的那一次切分（题数 / dev 桶变了） | 自洽 ≠ 正确，别继续跑 |
| `split_rule_mismatch` | 切分与 `sha256(family:item_id:salt)` 复算不符 | 数据被改过 |
| `split_hash_mismatch` / `split_distribution_missing` | split 自洽性坏了 | 同上 |
| `row_count_mismatch` | 行数不等于 `题量 × 2` | 整轮作废，不会留半轮结果 |
| `sealer_key_lost` | 封印密钥没了但 `bundles/` 还在 | 按提示删 `lab/runs/bundles/`（只有题目副本，没有实验结果） |
| `round_tampered` / `row_probe_row_tampered` / `row_missing` | 落盘记录或原始行被改过、被清理过 | 说明有人动过 `lab/runs/`，别信这一轮 |
| `round_malformed` / `round_incomplete` / `round_id_mismatch` / `round_unreadable` | 轮次文件 JSON 合法但结构不对（顶层不是对象、缺必需字段、类型不对、文件名与 `probe_id` 不符） | 这一条不可信；**其余轮次不受影响**，历史页照常打开 |
| `bundle_files_unexpected` | bundle 目录混进多余文件（多半是 Finder 的 `.DS_Store`） | 按提示删掉多余文件 |

这些失败在页面上是**一整页写清楚原因的错误页**（错误码 + 人话 + 该做什么），
不是空白页，也不是断开的连接。轮次记录、notebook 原始行、dev bundle 封印
三处验签**任何一处没过，这一轮的内容就一律不展示**——校验没过的记录不能拿来看数字。

**读不出来的轮次不会从历史页上消失**，它会带着错误码留在列表最上面。
把坏轮悄悄跳过，等于让篡改的效果变成"证据无声地不存在"，那比报错更难发现。

### 数据身份是怎么钉住的

快道的判据全部来自**仓内权威坐标**，不从被校验的文件里读：

```text
family      ifeval_zh_v1                 代码常量（08 §1 固定题集）
salt        abcr.rig.splits.SALT         协议常量，在 src 里
split       data/splits/ifeval_zh_v1.json    路径 + 字节 sha256 + split_hash + 题数 + dev 桶摘要
dataset     data/benchmarks/ifeval_zh_v1.json   路径 + 字节 sha256
```

为什么非这样不可：只做"文件内部自洽"的校验是不够的。把 `family` 改成别的值、
再按这个新 family 把 assignments、distribution、split_hash 三处一起重算，
文件会**完全自洽**——而 dev 桶已经从 42 题变成 47 题，其中 25 题原本是 holdout。
自洽只说明它描述了某一次切分，不说明它是我们该跑的那一次。判据必须来自文件之外。

**这道闸挂在"提交/复用"之前，不是挂在"开跑"之前。** 三条提交路径
（页面提交、CLI `run`、核心 `run_round`）都会先验当前冻结件，**再**判断
"这轮是不是已经跑过"。原因是：坏数据下"直接复用"同样是把结果交付出去一次，
而那一轮恰恰是在这份坏数据下产出的——只挡"再跑一次"、不挡"再交付一次"，等于没挡。

**读路径刻意不挂这道闸**：`list` / `show` / 历史页 / 轮次详情在数据坏掉时照常可用。
旧轮是历史事实，它的可读性不该取决于今天的冻结件长什么样——否则数据一坏，
连"回去看当初到底跑了什么"都做不到，而那正是查清问题需要的。旧轮自身的可信度
由 `record_hash` 与 notebook / bundle 各自的验签负责。

---

## 数据在哪

```text
lab/runs/
  keys/          快道自建的封印密钥（0600，KEYID 钉住公钥指纹；已 gitignore）
  splits/        适配后的 split（内容寻址，字节确定）
  bundles/       封印过的 dev bundle（可重建，删了不会丢实验结果）
  notebook/      ProbeNotebook：内容寻址、append-only、带篡改检测的**原始行**
  rounds/        轮次记录（假设、人格、汇总、血缘），每条带 record_hash
```

整个 `lab/runs/` 已进 `.gitignore`：代码入 git，实验数据和密钥不入。
想整个清掉重来，删这一个目录即可，不会影响仓库任何别的东西。

**为什么快道自己造封印密钥**：`build_dev_bundle()` 的封印私钥无默认值
（no default = no backdoor），而系统信任根 `/Library/Application Support/ABCR-Trust/`
下并没有 `dev-bundle-sealer.pub`——安装它属于 root 部署，本轮明确不做。
于是快道在自己的 `lab/runs/keys/` 下自签自验。封印的科学语义
（防 holdout 冒充 dev）在快道内部完整保留，且不需要任何 sudo。

---

## 这轮明确不做

飞书入口 / HumanGateway / Operator / Broker；root 安装、release、finalize、
launchd、genesis；正式 Goal、审批、Auditor、正式报告、promotion；云、远程 CUDA、
AILH；③L、activation vector、多 persona；自动解释、自动改假设、自动开下一轮；
calibration / holdout 或任何可引用证据；新前端框架或数据库。

快道只写 `lab/runs/` 自己的目录，不碰正式 ledger、控制面、证据目录。

---

## 夹具轮 vs 真机轮

测试用 `FakeProbeEngine` 跑出来的轮次，`probe_id` 前缀是 **`fx-`**；
真机轮是 **`fl-`**。两者的 `request_fingerprint` 里就带着引擎 profile，
所以**在结构上不可能**出现"夹具跑过一轮，人提交同一份请求时被当成已跑过而复用"。
万一 `fx-` 轮次出现在页面上，结果区会挂一条红字说明它不是真实模型跑的。

这条隔离是刻意加的：`1500 个绿色单测在夹具世界里一个都照不出真问题`，
夹具数字混进真机结果里是最难发现的一类错误。

---

## 作者实跑记录（真实环境，非夹具）

以下全部在**沙箱外**、真实 macOS 账户、真实 Ollama（`qwen2.5:7b`，
manifest digest `845dbda0ea48…`）上执行，`lab/runs/` 为默认真实目录。

### 只读体检（V2 修复后重跑）

```text
$ ./lab/fastlane/start-fastlane.command check
[PASS] 冻结 profile 存在 / 数据集存在 / split 存在 / lab 数据根可写
       仓内权威坐标  family=ifeval_zh_v1  salt=abcr-w1-v1  split_hash=7d91ac0b415c95a4…  dev=42
[PASS] 数据集身份 == 仓内冻结件 — d0642d787cab167485e718c41c5c01e454d5a623ce5ef85b1b39402730c5799f
[PASS] split 身份闸（路径 / 字节 / 语义坐标） — 95be69231c2183b44fbdcdedb38398fcb48c699f8d573644ee31028c4db27b03
[PASS] split 内容闸（family / salt / 计数 / split_hash / 切分规则复算） — {'calibration': 91, 'dev': 42, 'holdout': 117}
[PASS] dev 题池够跑 20 题 — dev=42
[PASS] Ollama 可达且模型指纹相符 — profile_id=qwen25-7b-q4-v1
全部通过   rc=0
```

> 这一条同时验证了双击入口的可执行位：V1 交付里 `start-fastlane.command`
> 在 git 中是 `100644`，直接执行 `rc=126`（permission denied）。现在是 `100755`，
> 且不带参数时行为与从前完全一致（默认 `serve`）。

### 真实 1 题 → 严格 2 行（V2 复验轮）

```text
probe_id             fl-0a5768606a91e04f5f650aac    人格 fastlane-p@ead7eebbdc22
完成                 2 行 / 预期 2 行    耗时 7.7s    citable = false
bundle               032793c400e898150e43e264a0fb10a31a0c9745f52d43a2b4e7d2a76fb1b9aa
engine_fingerprint   04f0f1cc08a14be19cad3d1ea2f098d60babe8efabd13f1876814ca2546511c4
dataset_sha256       d0642d787cab167485e718c41c5c01e454d5a623ce5ef85b1b39402730c5799f
split_sha256         95be69231c2183b44fbdcdedb38398fcb48c699f8d573644ee31028c4db27b03
item_ids             ['ifzh-0122']
arm_ids              ['vanilla', 'persona:fastlane-p@ead7eebbdc22']
request_fingerprint  0a5768606a91e04f5f650aace55918a9635492b5e5031bd62014f299010c607d
bundle_manifest_hash 59e2c88eab93bb6edcf1b806bdf375b01cbac0eb9eb954711d27fc1e5073bad0
bundle_source_hash   d15b7c23e7cb64d429519ea6259ef6759ab754de24a848e8169511c888d3a954
sealer_fingerprint   aa8c7dfbb2bca3fd5c00670a823d633756c1ee0acf3d599e41000fe17eb9c80c
row_hash             cbccf05293a70bf83e2968eb71994d0b83ec5767072c235163536882768c4ccb
row_hash             787163a50be58ba367e72abafccf1a6e75ded5ff8ea225177f7b22466066b33a
重复提交             该请求已经跑过，直接复用：fl-0a5768606a91e04f5f650aac
```

> **`bundle_id` 在 V2 变了**（同一 count/seed 从 `7cf22020…` 变成 `032793c4…`）。
> 原因是适配层落盘的 `_source` 块升到 v3、多带了 `dataset_sha256` 与 dev 桶摘要，
> 而 `_source` 进 `source_hash`、进 `bundle_id`——这是有意的，让 bundle 身份把
> 数据集身份也吃进去。**旧轮不受影响**：旧 bundle 目录仍在、仍验得过，
> V1 时期跑的 4 条真机轮实测仍可 `show`，内容与 hash 一个字未变。

### 早先的 V1 真机轮（仍在 `lab/runs/`，新代码下仍可读）

```text
fl-267152e3f5d7afdbc89a63d5   1 题 2 行     bundle 7cf22020…
fl-2ed9a17c820e191688593894  20 题 40 行    bundle 32310776…
fl-eeb1ad6b4982e54ca1889415 / fl-198c359ffd602fd190919e29   页面验收两轮（后者承自前者）
```

### 真实 20 题 → 严格 40 行（无静默缩题）

```text
probe_id  fl-2ed9a17c820e191688593894
完成      40 行 / 预期 40 行   耗时 73.2s

指标                     vanilla   persona      差值
通过率                     0.750     0.750    +0.000
非空输出率                  1.000     1.000    +0.000
输出长度(字符)                 63        54        -8
输出长度(token)              36        32        -4
hedging 句率              0.061     0.056    -0.005
自检标记句率                0.000     0.000    +0.000
```

> 这些数字是**观察结果，不是结论**。两臂通过率相同、persona 输出略短——
> 仅此而已，快道不替任何人解释它。

### 重复提交同一请求

```text
该请求已经跑过，直接复用：fl-2ed9a17c820e191688593894（重复提交不重复造实验）
```

### 页面全流程（起真服务、发真 HTTP、跑真模型）

19 项全 PASS：首页可打开 / 横幅在 / 提交 303 / 真实模型跑完出结果页 /
结果页无夹具红字 / 多行假设已折成单行 / `citable = false` /
行数 = 题量 × 2 / 引擎是真实 profile / 每条 row hash 在页面可见 /
「基于本轮新建」预填 / 重复提交不造新实验 / 改假设产生新轮 / 新轮记录血缘 /
旧轮内容未变 / **关闭并重开入口后两轮仍可查看** / 重开后旧轮详情仍可读。

涉及轮次 `fl-eeb1ad6b4982e54ca1889415`（2 行，2.1s）与
`fl-198c359ffd602fd190919e29`（承自前者）。

### 测试

```text
快道测试    103 passed                                    （tests/probe/test_quick_{loop,web}.py）
全量回归   1731 passed, 8 skipped, 0 failed              （V3 基线 1728 + 新增 3，零倒退）
命令  PYTHONPATH=src .venv312/bin/python -m pytest -q \
        --ignore=tests/contract/stage1 --ignore=tests/contract/stage2 --ignore=tests/contract/stage3
```

**每一批新测试都先证明"在被修的那一版上是红的"**（不是"写完就绿"的装饰）：

```text
V2 的 23 条打 V1 eeae494  →  web 9 条全红，其中 4 条是 RemoteDisconnected
                             （curl 52 在 urllib 侧的样子）；loop 组 ImportError，
                             行为证据为 family 伪造件在该树上 ACCEPTED dev=47
V3 的 18 条打 V2 10f4397  →  18 failed, 81 passed, 1 skipped
                             B1 三条提交路径：DID NOT RAISE FastlaneError
                             B2：AttributeError 'list' / 'str'、KeyError 'probe_id'、
                                 错误码不稳定、"一条文件写坏，整个历史页就打不开了"
V4 的 3 条打 V3 058cc08   →  4 failed, 26 passed
                             web.bind_server 不存在；CLI 无参数入口没有
                             fallback_to_ephemeral；对照实测 serve(占用端口)
                             -> OSError: [Errno 48] Address already in use
```

### 默认端口被占用（V4）

真实主机上 8787 由 AILH BOSS 控制台（PID 32527，`boss_console.py`，7/18 起）
长期占用，8788 由另一个服务（`bun`）占用。修复前无参数入口以
`OSError: [Errno 48] Address already in use`（`web.py:689`）退出；修复后：

```text
$ ./lab/fastlane/start-fastlane.command          # 无参数，Finder 双击同路
[fastlane] 127.0.0.1:8787 已被别的程序占用，改用系统分配的空闲端口
[fastlane] 学习数据 · 不可引用
[fastlane] 页面已启动: http://127.0.0.1:<实际端口>/
```

BOSS 进程未被触碰（仍在 8787 上 LISTEN）。

### 落盘状态

```text
轮次 5 条   notebook 48 行（2+40+2+2+2）   dev bundle 3 个   全部可重读、幂等成立
```

---

## 已知缺口（如实列出，未修）

1. **CLI 并发无锁**。页面层用一把 `_RUN_LOCK` 保证同一时刻只跑一轮
   （冻结 profile 的 `max_concurrency: 1`）。但同时手动开两个 CLI `run`
   进程跑同一请求，两边都会通过"这轮还没跑过"的检查而各跑一遍模型。
   单用户本机工具，暂未加文件锁。
2. **`ProbeNotebook._indexed` 是 O(n²)**：每次 append 重读整个
   `lab-notebook.jsonl`。20 题一轮 append 40 行，量级无感；轮次积累到几千行后
   会变慢。这是**科学核心**里的实现，本轮不改核心。
3. **轮次记录的 `record_hash` 只防误改，不防有意伪造**——算法是公开的，
   有权限改文件的人也能重算。它的作用是让"手滑改了个数字"藏不住，
   不是密码学意义上的防伪。原始行由 `ProbeNotebook` 独立锚定。
4. **假设折成单行不可逆**：`"a\nb"` 与 `"a / b"` 会被认成同一次实验。
   原文另存 `hypothesis_raw`，但两者会共用同一个 `probe_id`。
5. **未做真人验收**。上面全部是作者自测；`08` §3 的完成标准要楠亲自走一遍
   "查看 → 修改 → 新跑"。在那之前，这只能叫"等待真人验收"，不能叫工程已完成。
6. **冻结坐标是"钉住"，不是"自动跟随"**（V2 新增的边界，如实说明）。
   `data/splits|benchmarks/ifeval_zh_v1.json` 将来若**正当地**更新，快道会
   fail-closed 停下来，需要人把 `lab/fastlane/split_adapter.py` 里的
   `FROZEN_*` 常量一起改。这是有意的：数据身份换了本就该有人过目。
   常量与仓库是否漂移由 `test_frozen_constants_match_the_committed_blobs`
   （用 `git cat-file` 复算已提交 blob）守着；该测试在没有 git 的环境里 skip，
   届时只剩常量这一层，属于"缺失证据不是阴性证据"的已知边界。
7. **身份闸挡的是数据被换，挡不住有写权限者改代码**。能编辑
   `split_adapter.py` 的人可以把常量一并改掉——与缺口 3 同源，这些机制是
   **可发现性**，不是权限控制。

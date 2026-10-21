# root 语义验证记录 · code 实现者自检（2026-07-26）

> **性质说明**：这是**实现者自检**，不是独立验证。codex 仍须按
> `01-codex验证任务书-第一批.md` §2 独立复跑——作者自己验自己不构成放行。
> 本记录的用途是：①把八轮以来从未做过的 root 实证补上；②给 codex 一个对照基线，
> 若它的结果与此不符，说明其中一方有问题。
>
> 执行条件：楠于 2026-07-26 配置 `/etc/sudoers.d/abcr-today`（`superagent ALL=(ALL) NOPASSWD: ALL`），
> **收工须撤销**：`sudo rm /etc/sudoers.d/abcr-today`。

---

## 1. ⭐ pyc 自污染：P0 机理与 `-B` 修复，八轮来首次实证

**背景**：轮1 那个 P0（genesis 必砖、12 服务整机砖）的机理，八轮以来**只被静态推理证明过**，
从未以 root 真实执行验证。测试套件零测试以 `euid==0` 运行，这在非 root 身份下**物理上无法复现**。

**实验材料**：已作废的 `REL-17624261` staging（真实 20,417 文件树，因本轮改动而失效，正好当材料）。
实验前基线：pyc = **0**；根目录与 `env/lib/python3.12` 均为 `dr-xr-xr-x`（0555 只读）；
解释器 `env/bin/python` 为真 CPython 3.12.13、mode 0555。

| 实验 | 身份 | argv | 结果 |
|---|---|---|---|
| A | 非 root | `-I`（无 `-B`） | pyc **0** — 目录只读位挡住普通用户 |
| C | **root** | `-I -B` | pyc **0** — **修复有效** |
| **B** | **root** | `-I`（无 `-B`） | **pyc 42** — **P0 机理成立** |

实验 B 的写入样本与属性：

```
env/lib/python3.12/__pycache__
env/lib/python3.12/re/__pycache__/_compiler.cpython-312.pyc
env/lib/python3.12/encodings/__pycache__
…共 42 项
属主/权限：root:staff  -rw-r--r-- (0644)；__pycache__ 目录 0755
```

**结论**：
1. **root 确实无视 0555 只读目录位**，解释器启动阶段的 stdlib import 就写入被校验树 ✅
2. **`-B` 是有效且必要的屏障** ✅
3. 附带确认：写入物 `0644 root:staff` 同时违反封印 mode 策略（要求文件 0440 / 可执行 0550），
   即便树 hash 校验被绕过，mode 策略闸也会独立拦下——**纵深防御成立**

污染已完全清除（残留 0）。

---

## 2. ⭐ `-I` 使 `PYTHONDONTWRITEBYTECODE` 失效：首次实证

用同一个冻结解释器（3.12.13，`sys.dont_write_bytecode` 默认 False），pyc 写到临时目录：

| 条件 | pyc |
|---|---|
| 对照：无任何抑制 | **1** ← 实验有效 |
| 无 `-I` + `PYTHONDONTWRITEBYTECODE=1` | 0 ← 环境变量有效 |
| **有 `-I` + `PYTHONDONTWRITEBYTECODE=1`** | **1** ← **`-I` 隐含 `-E`，环境变量被忽略** |
| 有 `-I -B` | 0 ← `-B` 是唯一有效屏障 |

> 注：`/usr/bin/python3`（macOS CLT Python）在同样条件下四组全为 0，**不能用作实验材料**——
> 必须用封印树自带的那个解释器。这一点本身值得记：拿错解释器会得出"不会写入"的错误结论。

### 由此发现一处 P3（不构成缺陷，但代码误导）

`src/abcr/control/black_box_oracle.py:213` 在 spawn candidate 时写着：

```python
env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
```

而同一条 argv 带着 `-I` —— **这行环境变量在 `-I` 下确定无效**（上表第 3 行实证）。
它给读者"已经防住字节码写入"的错觉，实际不起任何作用。

**不构成当前缺陷**（见 §3 的三重防护），但建议清理或改用 `-B`，否则它会误导下一个读代码的人——
这正是 pyc P0 当初能存活的同一类认知陷阱。

---

## 3. 全仓 root-python 调用点扫描（任务书 §2.3）

`grep -rn '"-I"' scripts/ src/ | grep -v '"-B"'` 命中 2 处，均为 **candidate argv 模板**：

- `scripts/install_abcr_runtime.py:1283`（写进 test-controller 配置）
- `src/abcr/control/test_controller.py:34`（`FROZEN_CANDIDATE_ARGV_TEMPLATE`）

第二轮 panel 曾静态判定其安全。**本次给出实证依据**，安全性来自三重防护
（`black_box_oracle.run_external_oracle`）：

```python
if os.geteuid() == 0 and (candidate_uid is None or candidate_gid is None or candidate_uid == 0):
    return finish(..., reason="root_candidate_forbidden")      # ① 显式拒绝以 root 跑 candidate
...
    return finish(..., reason="sandbox_profile_invalid")       # ② 沙箱不可用绝不静默裸跑
def drop_privileges():
    os.setgroups([]); os.setgid(candidate_gid); os.setuid(candidate_uid)   # ③ 降权顺序正确
```

- **降权顺序 `setgroups → setgid → setuid` 正确**（若先 setuid 便再也无法 setgid，是经典错误，此处没犯）
- `resolve_candidate_argv` 另要求 run tree 的**每个**条目属主为 `candidate_uid`（非 root），
  即执行对象是 candidate 自己的树副本，**不是 root-owned 封印树**

**判定：不构成 pyc P0 复发。**

---

## 4. 本轮 P0 修复的 root 实证（任务书 §2.1）

用**新 candidate 中即将被封印的那份字节**（`production-ce6c80e-20260726/candidate/scripts/install_abcr_runtime.py`），
以 `euid=0` 执行：

```
运行身份 euid=0 (root)
真实 tar：619 成员，hardlink 245 个
✅ 封印候选的安装器策略以 root 身份接受该 tar
✅ 安全边界保持：symlink 仍被拒 (InstallBlocked)
```

---

## 5. 账户与组实况（任务书 §2.4）

| 账户 | home | 属主/权限 |
|---|---|---|
| `abcr-human` | 已物化 | `drwx------ abcr-human:abcr-human` |
| `abcr-probe` | 已物化 | `drwx------ abcr-probe:abcr-probe` |
| `abcr-operator` | **未物化** | 符合票据「其余 9 个 home 有意不物化」 |
| `abcr-itempool` | **未物化** | 同上 |

服务账户不可交互登录已确认：`shell=/usr/bin/false`、`Password=*`。

> 摘出的账户加固（`fable5/accounts-hardening-deferred`）四项弱点仍在，
> 票据记载「当前实机无实际暴露」，本次未发现与之矛盾的证据。
> 但该债按票据死线**须在服务启动前交付**——走到阶段 3 时即到期。

---

## 6. 未做（如实记录，缺失证据不是阴性证据）

- **`verify_release_read_policy` 的真实 root 执行**：需要一个 root-owned 且 gid 为
  `abcr-release-read` 的封印 release，**当前不存在**（要等阶段 1 之后）。
  这正是轮6 P0 所在的函数，现有测试把 uid/gid 全部伪造
  （`monkeypatch` + 伪造 `Path.lstat` 的 `st_uid`），**至今从未真跑过**。
  → **建议 codex 在阶段 1 完成后补这一项**，那时才具备条件。
- 12 服务的 launchd 实际加载与运行：genesis 之后才有。

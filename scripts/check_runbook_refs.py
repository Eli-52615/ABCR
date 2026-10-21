#!/usr/bin/env python3
"""runbook 引用完整性检查:部署手册提到的每个文件都必须真实存在。

历史依据(两类事故各发生过一次,均为阻断级):

1. **幻影引用**(轮2 P0):扩展版 runbook §8.2/§9 让操作者运行
   ``qualify_abcr_genesis_probation.py`` 与 ``qualify_abcr_autonomous.py``,
   而这两个文件**不存在于任何提交**。genesis 是全局一次性动作,照着执行会把
   名额永久耗在一个无法激活的 release 上。独立 panel 的原话是:该 runbook 疑似
   "written for a different (newer) build"。

2. **封印遗漏**(轮1):runbook §6.1 要求从 sealed release 运行
   ``check_human_signature_domain.sh``,而 ``build_reviewed_runtime`` 的
   allowlist 漏了它 —— 文件在仓库里有,封印树里没有,ceremony 会在 §6.1
   撞"文件不存在"。

所以检查分两级:引用的路径要在仓库里存在;若 runbook 要求**从封印 release 里
运行**它,还必须落在封印清单内。

架构(第九轮重写,起因见下)
---------------------------

初版用「正则找路径 + 看前 60 字符里有没有 ``$VAR/``」判定,两处近似各自可被
绕过,且**两个丢弃点都是静默的**::

    if not ref or ref.endswith("/"): continue   # 花括号/glob/${VAR} 叶子在此死掉
    sealed = any(f"${var}/" in prefix ...)      # 默认 False —— 未知即放行

对抗审查穷举出 26 种合法写法能静默绕过,其中 17 种源自这两个默认值。更要命的是
实测发现:**现行实现对仓内权威 runbook §6 B2/B4 两个 drain 步完全不可见**
(``-m abcr.control.canary_controller`` / ``-m abcr.control.release`` 是点分模块名,
一个 ``/`` 都没有),而那正是主 ceremony 路径。

所以本版把默认值**翻转**:凡是解析器看不懂的东西,产出 ``[解析器盲区]`` 阻断,
而不是静默放行。攻击者/作者的可乘之机从"解析器**不懂**的东西"缩小到
"解析器**懂错**的东西"——后者可枚举、可测试、可对着 POSIX 规范审查。

四层::

    Layer 0  文档分段   markdown fence → (shell code) / (prose)
    Layer 1  真分词     shlex(posix=True) —— 一步消掉全部引号形态
    Layer 2  符号求值   变量赋值/别名链/for/函数/参数展开/命令替换
    Layer 3  裁决       仓库存在性 × 封印清单;看不懂的一律阻断

sealed 由此成为「求值出的根」的属性,而不是「周围 60 字符」的属性。

本模块**有意不进封印树**(``scripts/`` 只有 ``GIT_EXACT`` 列出的文件进树),
因此新增它不改变任何 release 身份。``test_runbook_references`` 对此有断言。

用法::

    python3 scripts/check_runbook_refs.py                 # 检查仓内 runbook
    python3 scripts/check_runbook_refs.py <runbook> ...   # 检查指定 runbook
    python3 scripts/check_runbook_refs.py --coverage      # 附带解析覆盖率
"""
from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 仓内权威 runbook。仓外扩展版(共享目录 1014 行)不在 git 里,需显式传路径检查。
DEFAULT_RUNBOOKS = ("ops/install/REVIEWED-RUNTIME-INSTALL.md",)

# runbook 用这些变量指代「封印后的 release 根」。路径若挂在它们下面,
# 就是要求从封印树里运行 —— 那么它必须进封印清单,仅仓库里有是不够的。
SEALED_ROOT_VARS = (
    "ABCR_SEALED_RELEASE",
    "ABCR_REVIEW_FINAL",
    "ABCR_REVIEW_INCOMING",
    "ABCR_RELEASE_STAGING",
)

# 已知**不是**封印根、但其下路径是**仓库相对路径**的变量。
# 绝大多数根变量无需登记 —— runbook 自己就用赋值语句给出了字面值,求值即可得。
# 这里只登记那些赋值不在 runbook 内、却又指向 git 工作仓的。
NON_SEALED_ROOT_VARS: dict[str, str] = {
    "ABCR_REVIEWED_REPO": "git 工作仓(runbook §0 定义 =…/shared-brain/ABCR/abcr),不是封印树",
}

# runbook 用 ``<...>`` 表示「操作员在此填入实际值」(如 <REL-id-printed-by-finalize>)。
# 这是**已知的未知**:它不是解析器盲区,而是文档的既定约定,不得据此阻断。
_PLACEHOLDER = re.compile(r"<[^<>\s][^<>]*>")
_FILL_TOKEN = "__ABCR_FILL__"

# 封印根的字面写法。runbook 的补救/排障章节会直接写展开后的绝对路径,
# 此时没有任何变量可追,只能按字面形状识别。
SEALED_ROOT_LITERALS = (
    re.compile(r"^/Users/[^/]+/\.abcr/releases/[^/]+(?=/|$)"),
    re.compile(r"^/Library/Application Support/ABCR-Genesis/reviewed/[^/]+(?=/|$)"),
    re.compile(r"^<sealed-release>(?=/|$)"),
)

# 系统路径:不属于本仓,不参与仓库存在性检查。
#
# ``/Users/`` 与 ``/Library/`` **有意不在此表内**:封印树落在
# /Library/Application Support 下,git 工作仓落在 /Users/ 下。把这两个前缀
# 当系统路径会把整片真实引用静默吞掉 —— 曾有一版为图省事加了它们,
# 结果任何被赋绝对路径的根变量及一切字面绝对仓库路径全部失明。
# 它们改走 UNKNOWN_ABS:含仓库特征分量就报盲区,否则忽略。
SYSTEM_PREFIXES = ("/bin/", "/sbin/", "/usr/", "/etc/", "/var/", "/dev/",
                   "/private/", "/System/", "/Applications/", "/Volumes/",
                   "/tmp/", "/opt/")

# 非 shell 的 fence:这些块里的内容不是命令。**用黑名单而非白名单** ——
# 真实 runbook 用 ```text 达 37 次,白名单会让整块降级成散文而彻底失明。
NON_SHELL_INFO_STRINGS = frozenset({
    "python", "py", "json", "yaml", "yml", "toml", "ini", "xml", "html",
    "diff", "patch", "mermaid", "sql", "csv", "plist", "markdown", "md",
    "javascript", "js", "typescript", "ts", "c", "cpp", "go", "rust", "java",
})

# 提示符风格的 fence:内容是「命令 + 程序输出」混排,只有提示符行是命令。
# 不区分的话,输出里的 `can't open file` 会让 shlex 抛未闭合引号 → 假盲区。
CONSOLE_INFO_STRINGS = frozenset({"console", "sh-session", "bash-session",
                                  "shell-session", "terminal"})

# 写入类命令:目标路径是**将要创建**的,不得按「必须已存在」核对。
# 必须按语义分两类 —— 一刀跳过全部位置参数会连**源文件**也不检查,
# 而 `install "$REPO/data/x.json" "$DST/x.json"` 的源正是要核对的东西。
WRITER_ALL_TARGETS = frozenset({"mkdir", "tee", "touch", "dd", "truncate"})
WRITER_LAST_TARGET = frozenset({"cp", "mv", "install", "ln", "rsync"})

# shell 内建变量:runbook 里 $PWD/$HOME 属常规写法,不是解析器盲区。
BUILTIN_VARS = ("PWD", "HOME", "USER", "TMPDIR", "SHELL", "LOGNAME", "OLDPWD")

# 命令替换里可以透明求值的规范化命令 —— 它们不改变路径指向。
# 这是白名单:任何别的命令替换都会落进 [解析器盲区]。
CANONICALIZERS = frozenset({"realpath", "readlink", "echo", "printf", "dirname", "pwd"})

# shell 关键字/内建,不当作路径 token 处理。
SHELL_NOISE = frozenset({
    "for", "do", "done", "if", "then", "else", "elif", "fi", "while", "until",
    "case", "esac", "in", "function", "set", "export", "local", "readonly",
    "sudo", "env", "cd", "pushd", "popd", "echo", "printf", "true", "false",
    "{", "}", "[", "]", "[[", "]]", "!", "time", "exec", "eval",
})

# 已知且**有意**未交付的引用。每条必须写明「哪道门 + 何时交付」,
# 到期未交付即应复查。空登记表意味着零容忍 —— 这正是轮2 P0 当时的状态。
KNOWN_ABSENT: dict[str, str] = {
    "scripts/qualify_abcr_autonomous.py":
        "AUTONOMOUS_QUAL 门未资格化(票据 REL-17624261 §5 残余风险 4,按原纪律保持 BLOCKED);"
        "该门开工时随之交付",
    "src/abcr/control/autonomous_qualification.py":
        "同上,AUTONOMOUS_QUAL 门的实现模块",
    "ops/install/ABCR-FOOLPROOF-OPERATIONS.md":
        "操作话术手册目前置于共享目录 1-DOCS/,尚未收编进仓"
        "(票据 REL-3e8c1d1a §5 未决项)",
}

# 解析器确实解不动的写法,逐条豁免。与 KNOWN_ABSENT 同一纪律:必须写明
# 「哪种写法 + 为何不改写」。**禁止通配豁免与 --skip 开关** —— 那是静音开关。
UNRESOLVED_WAIVERS: dict[str, str] = {}


# ---------------------------------------------------------------- 封印清单

def _sealed_allowlist() -> tuple[frozenset[str], tuple[str, ...]]:
    """从 build_reviewed_runtime 取封印树 git allowlist,不导入该模块(它有 root 语义)。"""
    src = (REPO_ROOT / "scripts" / "build_reviewed_runtime.py").read_text(encoding="utf-8")
    exact_block = re.search(r"GIT_EXACT = frozenset\(\{(.*?)\}\)", src, re.S)
    prefix_block = re.search(r"GIT_PREFIXES = \((.*?)\)", src, re.S)
    if not exact_block or not prefix_block:
        raise SystemExit("BLOCKED: 无法从 build_reviewed_runtime.py 解析 allowlist")
    exact = frozenset(re.findall(r'"([^"]+)"', exact_block.group(1)))
    prefixes = tuple(re.findall(r'"([^"]+)"', prefix_block.group(1)))
    return exact, prefixes


def _runtime_derived() -> tuple[str, ...]:
    """封印树里**不来自 git** 的部分:venv、trust 公钥、构建派生文件。

    必须从 builder 常量解析而非手抄。曾有一版审查把 ``env/bin/python`` 与
    ``trust/review-verifier-attestation.pub`` 判成「文件不存在」——它们确实
    不在 git 里,但确实在封印树里。封印树 ≠ git allowlist。
    """
    src = (REPO_ROOT / "scripts" / "build_reviewed_runtime.py").read_text(encoding="utf-8")
    out: list[str] = []
    for name in ("RUNTIME_SITE", "RUNTIME_PYTHON", "REVIEW_VERIFIER_KEY"):
        m = re.search(rf'^{name}\s*=\s*PurePosixPath\("([^"]+)"\)', src, re.M)
        if not m:
            raise SystemExit(f"BLOCKED: 无法从 build_reviewed_runtime.py 解析 {name}")
        out.append(m.group(1))
    m = re.search(r"DERIVED_FILES = frozenset\(\{(.*?)\}\)", src, re.S)
    if not m:
        raise SystemExit("BLOCKED: 无法从 build_reviewed_runtime.py 解析 DERIVED_FILES")
    out.extend(re.findall(r'"([^"]+)"', m.group(1)))
    # finalize 阶段写出的封印树主产物。它在 release 里而不在 candidate 里,
    # 因此不在 DERIVED_FILES 内,但 runbook 的排障章节会引用它。
    out.extend(sorted(set(re.findall(r'/ "([\w.\-]+\.json)"', src))))
    return tuple(out)


def _in_sealed_tree(ref: str, exact: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    return ref in exact or any(ref.startswith(p) for p in prefixes)


def _is_derived(ref: str, derived: tuple[str, ...]) -> bool:
    return any(ref == d or ref.startswith(d.rstrip("/") + "/") for d in derived)


def _top_dirs() -> frozenset[str]:
    """顶级目录从仓库实际结构派生,不硬编码 —— 否则新增目录会静默漏检。"""
    return frozenset(p.name for p in REPO_ROOT.iterdir()
                     if p.is_dir() and not p.name.startswith("."))


# ---------------------------------------------------------------- Layer 0 分段

@dataclass(frozen=True)
class Segment:
    kind: str          # "code" | "prose"
    info: str          # fence info string
    text: str


_FENCE = re.compile(r"^([ \t]*)(`{3,}|~{3,})[ \t]*([^\s`]*)[^\n]*$", re.M)
_INDENTED = re.compile(r"(?:^(?: {4,}|\t)[^\n]*\n?)+", re.M)


def _split_indented(prose: str) -> list[Segment]:
    """把 4 空格/制表符缩进的代码块从散文里摘出来。

    markdown 的缩进代码块与围栏代码块等价,只按围栏切会让整段命令降级成散文,
    而散文侧不做 shell 求值 —— 幻影与封印遗漏一起失明。
    """
    out: list[Segment] = []
    pos = 0
    for m in _INDENTED.finditer(prose):
        block = m.group(0)
        # 列表续行也长这样,靠「是否像命令」区分:必须有命令行的样子。
        if not re.search(r"^(?: {4,}|\t)\s*(?:sudo|/|\$|\w+[/=]|python|\w+ )", block, re.M):
            continue
        out.append(Segment("prose", "", prose[pos:m.start()]))
        out.append(Segment("code", "", block))
        pos = m.end()
    out.append(Segment("prose", "", prose[pos:]))
    return out


def segment(text: str) -> list[Segment]:
    """按 markdown 围栏与缩进块把文档切成 code / prose 段。"""
    segs: list[Segment] = []
    pos = 0
    while True:
        m = _FENCE.search(text, pos)
        if not m:
            segs.extend(_split_indented(text[pos:]))
            break
        fence, info = m.group(2), m.group(3).lower()
        segs.extend(_split_indented(text[pos:m.start()]))
        close = re.compile(rf"^[ \t]*{fence[0]}{{{len(fence)},}}[ \t]*$", re.M)
        cm = close.search(text, m.end())
        if not cm:
            segs.append(Segment("code", info, text[m.end():]))
            break
        segs.append(Segment("code", info, text[m.end():cm.start()]))
        pos = cm.end()
    return segs


_PROMPT_SYMBOLS = ("$ ", "# ", "% ", "❯ ", "➜ ", "> ")


def _strip_prompt(line: str) -> str | None:
    """剥掉 shell 提示符,返回命令部分;不是提示符行则返回 None。

    **有意不用正则**:``^[ \\t]*(?:[\\w.@:~/-]*\\s*)?[$#][ \\t]+`` 这类写法在
    全空白行上会灾难性回溯,实测 600 KB 输入 180 秒跑不完 —— 守门器挂死
    与放行等价。逐前缀比较是 O(n),没有回溯可言。
    """
    s = line.strip()
    for p in _PROMPT_SYMBOLS:
        if s.startswith(p):
            return s[len(p):]
    for sym in ("$ ", "# ", "% "):          # user@host dir $ cmd
        i = s.find(sym)
        if 0 < i <= 80:
            return s[i + len(sym):]
    return None


_CMD_HEAD = re.compile(
    r"^\s*(?:sudo\b|env\b|cd\b|time\b|/[\w./-]+|\.{0,2}/[\w./-]+|"
    r"[A-Za-z_]\w*=|python3?\b|git\b|ls\b|cat\b|mkdir\b|tee\b|cp\b|mv\b|"
    r"install\b|chmod\b|chown\b|shasum\b|test\b|abcrctl\b)")


def _console_commands(block: str) -> str:
    """从「命令 + 输出」混排里取出命令行。

    两个方向都要:输出行含 ``can't`` 会让 shlex 抛未闭合引号(假盲区);
    而 ``# python3 …`` 的 ``#`` 是 root 提示符不是注释,当注释删掉就静默漏检。

    整块没有任何提示符时不能整块当命令 —— ```console 本就是命令与输出混排,
    那样会把 traceback、JSON 输出、`copying 100% …` 全部送去做存在性核对。
    改为逐行按「像不像命令」筛。
    """
    block = _join_continuations(block)   # 必须先接续行:第二行没有提示符,
                                         # 先剥提示符会把它删掉,残留的 `\`
                                         # 反而把下一条命令粘上来,产出假命令
    lines = [_strip_prompt(ln) for ln in block.splitlines()]
    if any(l is not None for l in lines):
        return "\n".join(l for l in lines if l is not None)
    return "\n".join(ln for ln in block.splitlines() if _CMD_HEAD.match(ln))


# ---------------------------------------------------------------- Layer 1 分词

def _strip_comments(block: str) -> str:
    """删整行 ``#`` 注释。必须在分词前做:注释里的 ``;`` `'` 会撕裂后续解析。"""
    return "\n".join(ln for ln in block.splitlines()
                     if not ln.lstrip().startswith("#"))


def _join_continuations(block: str) -> str:
    """合并 POSIX 行继续。双引号内的 ``\\<newline>`` 同样是续行,会把路径接回。"""
    return re.sub(r"\\\r?\n", "", block)


def _mask_placeholders(block: str) -> str:
    """把 ``<操作员填这里>`` 换成普通标识符 —— **必须在分词前**。

    ``<`` ``>`` 属于 shlex 的 punctuation_chars,不遮蔽的话
    ``ABCR_BUILD_ROOT=<new-directory-under-…>`` 会被拆成四个 token,
    于是该变量被赋成空串,其后每一条 ``$ABCR_BUILD_ROOT/x`` 都退化成 ``/x``,
    连锁制造一片假的「根不可识别」。
    """
    return _PLACEHOLDER.sub(_FILL_TOKEN, block)


_OPERATORS = {";", "&&", "||", "|", "&", "\n", ";;"}


def split_commands(block: str) -> tuple[list[list[str]], list[str]]:
    """分词并切成命令序列。返回 (命令列表, 分词失败的行)。

    **必须逐行分词**:shlex 在 ``whitespace_split`` 下把换行当普通空白吃掉,
    整块一次性分词会把所有行拼成一条命令 —— 于是只有块首的赋值被当成赋值,
    其后的 ``VAR=值`` 全被当路径 token 送去检查,凭空造出一堆假阳性。
    行继续已在上一步合并,所以此处「一行 = 一条逻辑命令」成立。
    """
    block = _mask_placeholders(_join_continuations(_strip_comments(block)))
    cmds: list[list[str]] = []
    errors: list[str] = []
    for line in block.splitlines():
        if not line.strip():
            continue
        lex = shlex.shlex(line, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        cur: list[str] = []
        try:
            for tok in lex:
                if tok in _OPERATORS:
                    if cur:
                        cmds.append(cur)
                        cur = []
                else:
                    cur.append(tok)
        except ValueError as exc:
            if cur:
                cmds.append(cur)
            errors.append(f"分词失败({exc}): {line.strip()[:80]}")
            continue
        if cur:
            cmds.append(cur)
    return cmds, errors


# ---------------------------------------------------------------- Layer 2 求值

SEALED = "SEALED"
NONSEALED = "NONSEALED"
SYSTEM = "SYSTEM"
RELATIVE = "RELATIVE"
UNKNOWN = "UNKNOWN"
UNKNOWN_ABS = "UNKNOWN_ABS"

_MARK_SEALED = "\x00S\x00"
_MARK_NONSEALED = "\x00N\x00"
_MARK_UNKNOWN = "\x00U\x00"
_MARK_FILL = "\x00F\x00"        # 操作员填充位(runbook 的 <...> 约定)

# 标记均不含 "/",因此能被 SEALED_ROOT_LITERALS 里的 [^/]+ 正常吃掉 ——
# 这正是 `/Users/x/.abcr/releases/$ABCR_RELEASE_ID/scripts/y` 仍判 SEALED 的原因。


@dataclass(frozen=True)
class Sym:
    """一个 token 的符号求值结果。"""
    template: str
    unknown_vars: tuple[str, ...] = ()

    @property
    def cls(self) -> str:
        t = self.template
        if t.startswith(_MARK_SEALED):
            return SEALED
        if t.startswith(_MARK_NONSEALED):
            return NONSEALED
        # 字面封印根**必须先于** UNKNOWN 与 SYSTEM 判定:
        # release-id 那一段本来就是未知的(操作员填),不该因此判成盲区;
        # 而封印树恰好落在 /Library/Application Support 下,也不该判成系统路径。
        if any(p.match(t) for p in SEALED_ROOT_LITERALS):
            return SEALED
        if _MARK_UNKNOWN in t:
            return UNKNOWN
        if t.startswith("/"):
            return SYSTEM if t.startswith(SYSTEM_PREFIXES) else UNKNOWN_ABS
        return RELATIVE

    def strip_root(self) -> str:
        t = self.template
        for mark in (_MARK_SEALED, _MARK_NONSEALED):
            if t.startswith(mark):
                return t[len(mark):].lstrip("/")
        for pat in SEALED_ROOT_LITERALS:
            m = pat.match(t)
            if m:
                return t[m.end():].lstrip("/")
        return t.lstrip("/")


@dataclass
class ShellEnv:
    """文档级作用域 —— 变量跨 fence 累积,因为 runbook 就是这么写的。"""
    vars: dict[str, list[Sym]] = field(default_factory=dict)
    funcs: dict[str, list[list[str]]] = field(default_factory=dict)



_PARAM = re.compile(r"\$\{([A-Za-z_]\w*)(?:[:#%!^,/+?=*@\-][^{}]*)?\}|\$([A-Za-z_]\w*)")
# 位置参数与特殊参数($1..$9 $@ $* $# $? $$ $!)在文本层面无从确定取值。
# 它们**必须**降级为不可判定 —— 函数包装形态 `"$SEALED/$2"` 若把 `$2` 当文件名
# 通过,就是把「解析不了」当成了「解析成功」,与旧实现的默认 False 同型。
_SPECIAL_PARAM = re.compile(r"\$\{?(?:\d+|[@*#?$!])\}?")
_CMDSUB = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
_BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")


_EXPAND_LIMIT = 256
_BRACE_DEPTH = 8
_BRACE_LIMIT = 64


def brace_expand(token: str, _depth: int = 0) -> list[str]:
    """展开 ``{a,b}``。不展开会让花括号内的文件名整条隐形。

    深度与结果数都必须封顶:``a{x,y}`` 重复 22 次就是 2^22 种组合,实测
    210 字节输入能跑 23 秒、吐 553 MB;而 RecursionError 会让 stdout 变成空的,
    **同一文档里真实的幻影引用随之一起消失**。超限按不可判定处理(报盲区),
    不静默截断 —— 截断等于回到 fail-open。
    """
    if _depth > _BRACE_DEPTH:
        return [token + _MARK_UNKNOWN]
    m = _BRACE.search(token)
    if not m:
        return [token]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(brace_expand(token[:m.start()] + alt + token[m.end():], _depth + 1))
        if len(out) > _BRACE_LIMIT:
            return [token + _MARK_UNKNOWN]
    return out


def _subst_commands(token: str, env: ShellEnv, depth: int) -> tuple[str, bool]:
    """求值命令替换。只有规范化命令透明求值,其余标记为不可判定。"""
    opaque = False

    def repl(m: re.Match[str]) -> str:
        nonlocal opaque
        inner = (m.group(1) or m.group(2) or "").strip()
        try:
            parts = shlex.split(inner)
        except ValueError:
            parts = inner.split()
        if len(parts) == 2 and Path(parts[0]).name in CANONICALIZERS:
            return expand(parts[1], env, depth + 1)[0].template
        if len(parts) == 3 and Path(parts[0]).name in CANONICALIZERS \
                and parts[1].startswith("-"):
            return expand(parts[2], env, depth + 1)[0].template
        opaque = True
        return _MARK_UNKNOWN

    prev = None
    while prev != token:                 # 循环到不动点:单趟 sub 吃不下嵌套
        prev = token
        token = _CMDSUB.sub(repl, token)
    if "$(" in token or "`" in token:
        # 仍有残留 = 没解开。必须标记为不可判定,否则解析器**误以为自己解成功了**
        # —— 那正是本模块序言批判的旧实现同型错误。
        opaque = True
    return token, opaque


def expand(token: str, env: ShellEnv, depth: int = 0) -> list[Sym]:
    """把一个 token 求值成若干 Sym(``for`` 变量可展成多值)。

    参数展开的修饰符(``${VAR%/}`` ``${VAR:?msg}`` ``${VAR:-def}``)按**变量本体**
    求值:它们指向同一棵树,是 runbook 作者的加固写法而非改指向。这条是
    fail-closed 的 —— 宁可把 ``${VAR:-别处}`` 也判成封印根(误报),
    也不能因为多了两个字符就静默放行。
    """
    if depth > 8:
        return [Sym(_MARK_UNKNOWN, ("<递归过深>",))]

    token, opaque = _subst_commands(token, env, depth)
    unknown: list[str] = []
    if _SPECIAL_PARAM.search(token):
        token = _SPECIAL_PARAM.sub(_MARK_UNKNOWN, token)
        unknown.append("位置/特殊参数")
    results = [token]

    for _ in range(8):
        m = _PARAM.search(results[0])
        if not m:
            break
        name = m.group(1) or m.group(2)
        # 登记表**优先于**赋值语句:登记的是变量语义(「这是封印根」/「这是 git 工作仓」),
        # 而赋值给的只是本机字面路径。语义必须压过字面值 —— 否则
        # `ABCR_REVIEWED_REPO=/Users/…/abcr` 会让其下路径退化成系统路径而被整个忽略,
        # `ABCR_REVIEW_FINAL="$ABCR_REVIEW_ROOT/$ABCR_RELEASE_ID"` 也会把封印根语义
        # 冲淡成一个含未知量的字符串。
        if name in SEALED_ROOT_VARS:
            vals = [Sym(_MARK_SEALED)]
        elif name in NON_SEALED_ROOT_VARS:
            vals = [Sym(_MARK_NONSEALED)]
        elif name in env.vars:
            vals = env.vars[name]
        elif name == "HOME":
            # 必须展开成真实 home:封印根字面量之一是 /Users/<user>/.abcr/releases/...,
            # 用占位值会让 `$HOME/.abcr/releases/$ID/scripts/x` 整条静默,
            # 而等价的 `~/`、`/Users/$USER/`、字面绝对路径三种写法都能检出。
            vals = [Sym(str(Path.home()))]
        elif name in BUILTIN_VARS:
            # $PWD 之类是 shell 内建,不是解析器盲区。取一个不含仓库特征的
            # 占位值即可 —— 我们只关心「它是不是封印根」,答案是否。
            vals = [Sym(_MARK_FILL)]
        else:
            unknown.append(name)
            vals = [Sym(_MARK_UNKNOWN)]
        nxt: list[str] = []
        for base in results:
            mm = _PARAM.search(base)
            if not mm:
                nxt.append(base)
                continue
            for v in vals:
                unknown.extend(v.unknown_vars)
                nxt.append(base[:mm.start()] + v.template + base[mm.end():])
        # 多值变量(for 列表)× 同一 token 内多次引用 = 笛卡尔积。
        # 实测 268 字节输入可产出 266 MB。超限按不可判定处理,不静默截断。
        if len(nxt) > _EXPAND_LIMIT:
            return [Sym(token + _MARK_UNKNOWN, ("<展开规模超限>",))]
        results = nxt

    out: list[Sym] = []
    for r in results:
        if r.startswith("~/"):
            r = str(Path.home()) + r[1:]
        r = _PLACEHOLDER.sub(_MARK_FILL, r).replace(_FILL_TOKEN, _MARK_FILL)
        if opaque and _MARK_UNKNOWN not in r:
            r += _MARK_UNKNOWN
        out.append(Sym(r, tuple(dict.fromkeys(unknown))))
    return out


# ---------------------------------------------------------------- Layer 3 裁决

@dataclass(frozen=True)
class Ref:
    repo_rel: str
    sealed: bool


@dataclass(frozen=True)
class Unresolved:
    raw: str
    reason: str


_GLOB = re.compile(r"[*?\[]")
_MODULE = re.compile(r"^[a-z_]\w*(?:\.[a-z_]\w*)+$")
# 正则/表达式特征:这类 token 是 grep/awk 的参数,不是路径。
_NOT_A_PATH = re.compile(r"[|^()+]|\{\d|\\[dws]")


def _display(t: str) -> str:
    return (t.replace(_MARK_UNKNOWN, "${?}").replace(_MARK_SEALED, "$SEALED")
             .replace(_MARK_NONSEALED, "$REPO").replace(_MARK_FILL, "<…>"))


def _looks_like_repo_path(rel: str, top: frozenset[str]) -> bool:
    """这一段路径是否**可能**指向仓库/封印树内容。

    盲区告警只在此为真时才发 —— 否则 ``$ABCR_LAUNCHD_ROOT/com.abcr.x.plist``
    这类与本仓无关的路径会把守门器淹掉,而噪音正是守门器退化成静音开关的路径。
    """
    head = rel.split("/", 1)[0]
    return head in top or "/scripts/" in rel or "/src/abcr/" in rel


_PATH_SHAPED = re.compile(r"/|\.(?:py|sh|md|json|plist|sb|txt|lock|pub|cfg|toml|ya?ml)$")


def _emit(sym: Sym, top: frozenset[str], refs: list[Ref], unres: list[Unresolved]) -> None:
    cls = sym.cls
    # **顺序要害**:先问「解析器看懂了没有」,再问「它像不像路径」。
    # 反过来的话,`_NOT_A_PATH`(字符类含 `(` `|`)会把命令替换残留、
    # 乃至本模块自己产生的展开超限标记一并吞成静默 ——
    # 新加的 fail-closed 机制被旧的 fail-open 出口消解,等于白加。
    if cls != UNKNOWN:
        if _NOT_A_PATH.search(sym.template):
            return
        # 必须长得像路径。裸词是子命令(`abcrctl status` 的 status)、选项值、
        # 主机名等 —— 把它们当文件核对会产出成片的假幻影引用。
        if not _PATH_SHAPED.search(sym.template):
            return
    if cls == UNKNOWN:
        raw = _display(sym.template)
        # 未知根之后若跟着仓库特征分量,才是真盲区;否则是与本仓无关的外部路径。
        tail = raw.split("/", 1)[1] if "/" in raw else ""
        if tail and _looks_like_repo_path(tail, top):
            names = ", ".join(f"${v}" for v in sym.unknown_vars) or "命令替换"
            unres.append(Unresolved(raw, f"根含无法判定的成分({names})"))
        return
    if cls == SYSTEM:
        return
    if cls == UNKNOWN_ABS:
        if "/scripts/" in sym.template or "/src/abcr/" in sym.template:
            unres.append(Unresolved(_display(sym.template),
                                    "绝对路径含仓库特征分量,但根不可识别"))
        return

    # 剥尾部标点。here-doc 正文里的 JSON 经分词后会带上逗号/引号,
    # 产出 `reports/notes.md,` 这种假文件名。曾有一版为此把 here-doc 正文
    # **整块删掉** —— 那消掉了噪音,却把 here-doc 里真实的引用检出一并删了
    # (相对上一版是硬倒退)。正确做法是剥标点,不是扔内容。
    rel = sym.strip_root().rstrip(_TRAILING)
    if not rel or rel.endswith("/"):
        return
    if cls in (RELATIVE, NONSEALED) and not _looks_like_repo_path(rel, top):
        return
    if _MARK_FILL in rel:
        return              # 叶子是操作员填充位,无从核对,也不是缺陷
    if _MARK_UNKNOWN in rel:
        unres.append(Unresolved(_display(rel), "路径中段/叶子含无法判定的变量"))
        return
    if _GLOB.search(rel):
        unres.append(Unresolved(rel, "路径含通配符,展开结果不确定"))
        return
    refs.append(Ref(rel, cls == SEALED))


def resolve_shell(block: str, env: ShellEnv, top: frozenset[str]
                  ) -> tuple[list[Ref], list[Unresolved]]:
    refs: list[Ref] = []
    unres: list[Unresolved] = []
    cmds, lex_errors = split_commands(block)
    for e in lex_errors:
        unres.append(Unresolved(e, "shell 分词失败"))

    for cmd in cmds:
        _run_command(cmd, env, top, refs, unres, depth=0)
    return refs, unres


def _emit_module(mod: str, sealed: bool, refs: list[Ref]) -> None:
    """`-m abcr.x.y` → `src/abcr/x/y.py`。

    **只映射本仓模块**:`-m json.tool` / `-m http.server` 是标准库,
    无脑翻成 `src/json/tool.py` 会造出假幻影引用。
    """
    if not (_MODULE.match(mod) and mod.split(".", 1)[0] == "abcr"):
        return
    rel = "src/" + mod.replace(".", "/")
    target = rel + ".py"
    if not (REPO_ROOT / target).exists() and (REPO_ROOT / rel / "__init__.py").exists():
        target = rel + "/__init__.py"
    refs.append(Ref(target, sealed))


def _writer_targets(cmd: list[str]) -> set[int]:
    """写入类命令中「将要创建」的参数下标 —— 它们不按已存在核对。

    `cp/mv/install/ln` 只有**最后一个**位置参数是目标,前面的源必须照查;
    带 ``-d`` 的 install 是建目录,参数全是目标。
    """
    kind = None
    at = 0
    for i, tok in enumerate(cmd):
        if tok.startswith("-"):
            continue
        name = Path(tok).name
        if name in WRITER_ALL_TARGETS:
            kind, at = "all", i
            break
        if name in WRITER_LAST_TARGET:
            kind, at = "last", i
            break
        if name not in ("sudo", "env", "time"):
            break               # 命令名不是写入类,后面的都是它的参数
    if kind is None:
        return set()
    args = [i for i in range(at + 1, len(cmd)) if not cmd[i].startswith("-")]
    if kind == "all" or "-d" in cmd or "-D" in cmd:
        return set(args)
    return {args[-1]} if args else set()


def _run_command(cmd: list[str], env: ShellEnv, top: frozenset[str],
                 refs: list[Ref], unres: list[Unresolved], depth: int) -> None:
    if not cmd or depth > 4:
        return

    # for X in a b c
    if cmd[0] == "for" and len(cmd) >= 4 and cmd[2] == "in":
        vals: list[Sym] = []
        for raw in cmd[3:]:
            for b in brace_expand(raw):
                vals.extend(expand(b, env, depth))
        env.vars[cmd[1]] = vals
        return

    # 剥离子 shell / 分组括号:`( cd X && ./y )`、`time ( ... )`、`X=( a b )`
    # 都会让 "(" 占住 cmd[0]/cmd[1]。曾有一版把「第二个 token 是 ( 」整条早退,
    # 于是单行数组与 time 分组里的引用被整片吞掉(且那个分支对它声称要处理的
    # 函数定义从未生效 —— 运算符优先级写错了)。
    cmd = [t for t in cmd if t not in ("(", ")", "{", "}")]
    if not cmd:
        return

    # 函数定义头 `f()`:只跳过这个 token,函数体命令随后照常逐条求值。
    if cmd[0].endswith("()"):
        cmd = cmd[1:]
        if not cmd:
            return

    # 前缀赋值 / export。`+=` 必须一并识别,否则 PATH+= 会绕开 PATH 的响亮闸门。
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        # local/readonly/declare/typeset 与 export 同族。漏掉它们会让
        # `local QUAL="$SEALED/scripts/x"` 整个 token 落进 _emit,产出一条
        # 名为 `QUAL=<标记>/scripts/x` 的乱码引用,同时真正的封印遗漏漏报。
        if tok in ("export", "local", "readonly", "declare", "typeset", "alias"):
            i += 1
            # 关键字自己的选项(`declare -r` / `export -p`)也要跳过,
            # 否则循环在 `-r` 上 break,整个 `QUAL=…` token 落进 _emit 成乱码。
            while i < len(cmd) and cmd[i].startswith("-"):
                i += 1
            continue
        m = re.match(r"^([A-Za-z_]\w*)\+?=(.*)$", tok)
        if not m:
            break
        vals: list[Sym] = []
        for b in brace_expand(m.group(2)):
            vals.extend(expand(b, env, depth))
        # 判据是「值里**含有**封印根」而非「以封印根开头」:
        # `PATH+=":$SEALED/scripts"` 的值以冒号起头,按 cls 判会漏掉。
        if m.group(1) == "PATH" and any(_MARK_SEALED in s.template for s in vals):
            # 把封印树塞进 PATH 后,后续调用点是裸命令名,不含任何路径 ——
            # 静态无从追踪。不实现 PATH 语义,但必须响亮失败而非静默放行。
            unres.append(Unresolved(tok, "PATH 前置封印树后,裸命令名无法追踪归属"))
        env.vars[m.group(1)] = vals
        # 赋值右侧**不**在此核对存在性:runbook 里大量 `X="$BUILD/artifact.json"`
        # 指向将要生成的产物,核对会产出成片的假幻影引用,还能被「一句变量中转」
        # 绕过写入类命令的产物豁免。变量真正被用到执行位置时自然会核对。
        i += 1
    cmd = cmd[i:]
    if not cmd:
        return

    # cd / pushd:**只报告,不追踪**。
    # 曾有一版把 cwd 与相对路径合并,结果两头都坏:合并出的绝对路径被系统前缀
    # 吞掉(静默),而 `abcrctl status` 的 `status` 又被当成封印树里的文件(误报)。
    # cwd 语义的收益为负,改成:切进封印根就响亮报盲区,由作者改写为显式 $VAR/path。
    if cmd[0] in ("cd", "pushd"):
        # 跳过选项:`cd -- DIR` / `cd -P DIR` 是等价写法(实测 inode 相同),
        # 只看 cmd[1] 会让它们绕过这道唯一的 cwd 闸门。
        args = [t for t in cmd[1:] if not t.startswith("-")]
        for a in args[:1]:
            for s in expand(a, env, depth):
                if s.cls == SEALED:
                    unres.append(Unresolved(a,
                        "cd 进封印根后的相对路径归属无法静态判定"))
        return

    skip = _writer_targets(cmd)
    # 重定向目标是**将要写出**的文件,与 tee 的目标同义,不得按已存在核对。
    for i, t in enumerate(cmd):
        if t in (">", ">>", "2>", "&>") and i + 1 < len(cmd):
            skip.add(i + 1)

    # -m 点分模块 → src/<路径>.py;sealed 继承同一条命令内解释器的类别
    sealed_cmd = False
    syms_by_tok: list[tuple[str, list[Sym]]] = []
    for tok in cmd:
        # 长选项附值 `--opt=path`:必须拆出值来求值,整体跳过会让路径隐形。
        val = tok
        if tok.startswith("-") and "=" in tok:
            val = tok.split("=", 1)[1]
        elif tok.startswith("-"):
            syms_by_tok.append((tok, []))
            continue
        got: list[Sym] = []
        for b in brace_expand(val):
            got.extend(expand(b, env, depth))
        if any(s.cls == SEALED for s in got):
            sealed_cmd = True
        syms_by_tok.append((tok, got))

    for idx, (tok, syms) in enumerate(syms_by_tok):
        # `-mabcr.x` 紧贴形态与 `-m abcr.x` 等价,不处理就是 -m 防线自己的逃逸口。
        if tok.startswith("-m") and len(tok) > 2 and not tok.startswith("--"):
            _emit_module(tok[2:], sealed_cmd, refs)
            continue
        if tok == "-m" and idx + 1 < len(syms_by_tok):
            mod = syms_by_tok[idx + 1][0]
            _emit_module(mod, sealed_cmd, refs)
            continue
        if tok in SHELL_NOISE or (tok.startswith("-") and "=" not in tok):
            continue
        if idx > 0 and syms_by_tok[idx - 1][0] == "-m":
            continue
        if idx in skip:
            continue
        for s in syms:
            _emit(s, top, refs, unres)


# ---------------------------------------------------------------- 散文层

_TRAILING = "。,、;:!?)）】》\"'`.,:;!?)]}>"


# 散文里含 ``$VAR/`` 的片段:它是命令片段,不是散文。
# 不要求外层引号 —— 作者可能裸写、用单引号、或用中文书名号包裹,
# 只认反引号和双引号会让其余写法整片失明。
_PROSE_ROOTED = re.compile(r"(?<![\w/])(\$\{?[A-Za-z_]\w*\}?/[^\s`'\"，。;:!?、（）【】《》「」]+)")


def _prose_rooted(text: str, env: ShellEnv, top: frozenset[str]
                  ) -> tuple[list[Ref], list[Unresolved]]:
    """散文里挂在变量根下的路径,按 shell 片段求值。

    runbook 的说明段落常写 「而 `"$ABCR_REVIEW_FINAL/scripts/x"` 从封印树运行」,
    这类引用与代码块里的等价 —— 只按裸路径抓会把根信息整个丢掉。
    """
    refs: list[Ref] = []
    unres: list[Unresolved] = []
    for m in _PROSE_ROOTED.finditer(text):
        # 必须剥句末标点与 markdown 强调符,否则 `$SEALED/scripts/x.py。` 会带着
        # 句号去核对,把一条**真**封印遗漏误诊成假幻影 —— 人照着告警去消音,
        # 那条 P0 就永久静默了。
        raw = m.group(1).rstrip(_TRAILING + "*_~")
        for piece in brace_expand(raw):
            for sym in expand(piece, env):
                _emit(sym, top, refs, unres)
    return refs, unres


def _prose_refs(text: str, top: frozenset[str]) -> list[Ref]:
    """散文里的裸路径:只查存在性(幻影引用),不判封印。

    字符类用**排除式**而非枚举式 —— 枚举式会把
    ``scripts/cloud/R2-操作说明-非技术人员照抄版.md`` 截成 ``scripts/cloud/R2-``,
    再报一条「文件不存在」的假幻影引用。守门器自己制造噪音是最坏的失败模式。
    """
    if not top:
        return []
    alt = "|".join(sorted(re.escape(d) for d in top))
    # 定界集必须含中文引号与书名号:`「runs/RUNSET.json」与` 这类写法会把
    # 后面的汉字吞进文件名,再报一条「文件不存在」的**假**幻影引用。
    # `#` 亦在内 —— markdown 锚点 `doc.md#小节` 的片段不属于文件名。
    delim = r"\s`'\"()<>|;&$*{}\[\],，、。;:!?（）【】《》「」『』〈〉“”‘’#\\"
    pat = re.compile(rf"(?<![\w./-])(?:{alt})/[^{delim}]+")
    out: list[Ref] = []
    for m in pat.finditer(text):
        ref = m.group(0).rstrip(_TRAILING)
        if ref and not ref.endswith("/") and not _GLOB.search(ref):
            out.append(Ref(ref, False))
    return out


# ---------------------------------------------------------------- 对外 API

def analyze(text: str) -> tuple[list[Ref], list[Unresolved]]:
    top = _top_dirs()
    env = ShellEnv()
    refs: list[Ref] = []
    unres: list[Unresolved] = []
    for seg in segment(text):
        if seg.kind == "code" and seg.info in NON_SHELL_INFO_STRINGS:
            # ```json / ```python 里是示例输出与代码片段,里面的路径是数据不是引用。
            # 既不做 shell 求值,**也不能落到散文层**去核对存在性。
            continue
        if seg.kind == "code":
            body = (_console_commands(seg.text) if seg.info in CONSOLE_INFO_STRINGS
                    else seg.text)
            r, u = resolve_shell(body, env, top)
            refs.extend(r)
            unres.extend(u)
        else:
            refs.extend(_prose_refs(seg.text, top))
            r, u = _prose_rooted(seg.text, env, top)
            refs.extend(r)
            unres.extend(u)
    return refs, unres


def extract_refs(text: str) -> dict[str, bool]:
    """抽出全部路径引用 → 是否被要求从封印 release 里运行。"""
    refs, _ = analyze(text)
    out: dict[str, bool] = {}
    for r in refs:
        out[r.repo_rel] = out.get(r.repo_rel, False) or r.sealed
    return out


def check(runbooks: list[Path]) -> list[str]:
    """返回违规清单;空列表 = 通过。"""
    exact, prefixes = _sealed_allowlist()
    derived = _runtime_derived()
    problems: list[str] = []
    for book in runbooks:
        if not book.exists():
            problems.append(f"[runbook 缺失] {book}")
            continue
        try:
            text = book.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            # 未捕获时异常会冒到 CLI:stdout 空、rc 非零、**违规一条都不报**。
            # 读不了就说读不了,不能表现成「检查跑过了」。
            problems.append(f"[runbook 不可读] {book}:{exc}")
            continue
        refs, unres = analyze(text)
        merged: dict[str, bool] = {}
        for r in refs:
            merged[r.repo_rel] = merged.get(r.repo_rel, False) or r.sealed
        for ref, sealed in sorted(merged.items()):
            if _is_derived(ref, derived):
                continue           # 封印树里由 builder 生成,不来自 git
            target = REPO_ROOT / ref
            if not target.exists():
                if ref in KNOWN_ABSENT:
                    continue
                problems.append(
                    f"[幻影引用] {book.name} 引用 {_display(ref)},但它不存在于仓库。"
                    f"若属有意未交付,请登记进 KNOWN_ABSENT 并写明门与交付时机")
                continue
            if sealed and target.is_file() and not _in_sealed_tree(ref, exact, prefixes):
                problems.append(
                    f"[封印遗漏] {book.name} 要求从封印 release 运行 {_display(ref)},"
                    f"但它不在 build_reviewed_runtime 的 allowlist 内 —— "
                    f"ceremony 执行到该步会撞「文件不存在」")
        for u in sorted(set(unres), key=lambda x: (x.reason, x.raw)):
            if u.raw in UNRESOLVED_WAIVERS:
                continue
            problems.append(
                f"[解析器盲区] {book.name} 中 {u.raw!r} {u.reason};"
                f"请改写为显式 $VAR/path,或登记进 UNRESOLVED_WAIVERS 说明理由")
    return problems


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    coverage = "--coverage" in argv
    books = [Path(a) for a in args] or [REPO_ROOT / p for p in DEFAULT_RUNBOOKS]
    problems = check(books)
    if coverage:
        for b in books:
            if b.exists():
                refs, unres = analyze(b.read_text(encoding="utf-8"))
                uniq = {r.repo_rel: r.sealed for r in refs}
                print(f"coverage: {b.name} refs={len(uniq)} "
                      f"sealed={sum(uniq.values())} unresolved={len(unres)}")
    if problems:
        print(f"BLOCKED: runbook 引用完整性检查发现 {len(problems)} 处问题")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"ok: {len(books)} 份 runbook 的全部引用均已核实")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

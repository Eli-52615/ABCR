"""tests/ops/test_runbook_references —— runbook 引用完整性守门。

挡两类历史阻断级事故:
- 轮2 P0:runbook 引用 `qualify_abcr_genesis_probation.py`,而它不存在于任何提交
  (genesis 一次性,照做会把名额烧在无法激活的 release 上)。
- 轮1:allowlist 漏封 `check_human_signature_domain.sh`,runbook 要求从 sealed
  release 运行它,ceremony 执行到该步撞「文件不存在」。

七轮之前,全 tests/ 对 "runbook" 零 grep 命中 —— 没有任何测试断言 runbook
引用的文件存在。本文件补上这道断言。

第九轮扩充:守门器初版用「正则找路径 + 看前 60 字符有没有 $VAR/」判定,对抗审查
穷举出 26 种合法写法可静默绕过。本文件逐条复现这些形态,`test_bypass_*` 一条对
一种。**这些用例的价值全在于:它们在旧实现上必须是绿的(旧实现看不见问题),
在新实现上必须是红的(检出)。** 只测新实现能过的用例没有回归价值。

`_fake_repo` 夹具亦随之升级:补齐 builder 的派生产物常量(`RUNTIME_*` /
`DERIVED_FILES`),并植入一个**真实存在但不在 allowlist** 的脚本作为封印遗漏
探针 —— 旧夹具缺这个,所以旧测试根本测不出那条路径。
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
IN_REPO_RUNBOOK = ROOT / "ops/install/REVIEWED-RUNTIME-INSTALL.md"


def _load_script(name: str, relative: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    # 必须先登记再 exec:模块内的 @dataclass 在解析字符串注解(PEP 563)时会
    # 查 sys.modules[cls.__module__],缺席则抛 AttributeError。
    sys.modules[name] = module
    loader.exec_module(module)
    return module


@pytest.fixture()
def checker():
    return _load_script("abcr_runbook_refs_test", "scripts/check_runbook_refs.py")


def _fake_repo(tmp_path: Path) -> Path:
    """造一棵最小仓库树,形状对齐真实 builder 常量。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src/abcr/control").mkdir(parents=True)
    (tmp_path / "ops/install").mkdir(parents=True)
    (tmp_path / "scripts/build_reviewed_runtime.py").write_text(
        'GIT_PREFIXES = (\n    "src/abcr/",\n    "ops/install/",\n)\n'
        'GIT_EXACT = frozenset({\n    "scripts/bootstrap_abcr_genesis.py",\n})\n'
        'RUNTIME_SITE = PurePosixPath("env/lib/python3.12/site-packages")\n'
        'RUNTIME_PYTHON = PurePosixPath("env/bin/python")\n'
        'REVIEW_VERIFIER_KEY = PurePosixPath("trust/review-verifier-attestation.pub")\n'
        'DERIVED_FILES = frozenset({"requirements.lock", "reviewed-source.json"})\n'
        # finalize 阶段写出的封印树主产物。它在 release 里而不在 candidate 里,
        # 故不在 DERIVED_FILES 内,checker 靠这行的字面形状把它认出来。
        'def _finalize(destination):\n'
        '    manifest_path = destination / "release-manifest.json"\n',
        encoding="utf-8")
    (tmp_path / "scripts/bootstrap_abcr_genesis.py").write_text("# sealed\n", encoding="utf-8")
    # 封印遗漏探针:仓库里有,allowlist 里没有 —— 旧夹具缺这个。
    (tmp_path / "scripts/abcrctl").write_text("#!/bin/sh\n", encoding="utf-8")
    (tmp_path / "src/abcr/control/canary_controller.py").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def repo(checker, tmp_path, monkeypatch):
    r = _fake_repo(tmp_path)
    monkeypatch.setattr(checker, "REPO_ROOT", r)
    return r


def _problems(checker, tmp_path, body: str) -> list[str]:
    book = tmp_path / "runbook.md"
    book.write_text(body, encoding="utf-8")
    return checker.check([book])


def _sealed_omission(problems: list[str], ref: str) -> bool:
    return any("封印遗漏" in p and ref in p for p in problems)


def _blind_spot(problems: list[str]) -> bool:
    return any("解析器盲区" in p for p in problems)


# ---------------------------------------------------------------- 真实产物断言
# 这四条打的是**真实 runbook**,不是 tmp_path 夹具。前八轮的教训是
# 「1500 个绿色单测在夹具世界里一个都照不出来」——夹具的保真度就是审查的天花板。

def test_in_repo_runbook_has_no_dangling_reference(checker):
    """仓内 runbook 引用的每个文件都必须真实存在(或已登记为有意缺席)。"""
    assert checker.check([IN_REPO_RUNBOOK]) == []


# 仓外「部署权威」扩展版(1014 行)。它不在 git 里,故 CI 默认不检查它 ——
# 而本轮 P2 与前轮三条 P1 全部由它产生。票据 REL-3e8c1d1a §5 的未决项。
# 在场即检,不在场则 skip:检不了就说检不了,不当作检过了。
OUT_OF_REPO_RUNBOOK = Path(
    "/Users/superagent/shared-brain/ABCR/1-DOCS/0719人格探索落地/REVIEWED-RUNTIME-INSTALL.md")


@pytest.mark.skipif(not OUT_OF_REPO_RUNBOOK.exists(),
                    reason="仓外部署权威不在本机;它不受版本控制,缺席不代表通过")
def test_out_of_repo_deployment_authority_passes(checker):
    """部署权威也必须过关。

    genesis 是照着**它**执行的,而它既不在 git 也不在封印树、更不在 CI 默认范围内。
    这条断言把「人工记得跑一次」变成「不跑就红」。
    """
    assert checker.check([OUT_OF_REPO_RUNBOOK]) == []


@pytest.mark.skipif(not OUT_OF_REPO_RUNBOOK.exists(),
                    reason="仓外部署权威不在本机;它不受版本控制,缺席不代表通过")
def test_out_of_repo_deployment_authority_has_zero_blind_spots(checker):
    """解析器必须完全看懂部署权威 —— 盲区非零即视为未覆盖。"""
    _, unresolved = checker.analyze(OUT_OF_REPO_RUNBOOK.read_text(encoding="utf-8"))
    assert unresolved == [], f"部署权威上出现解析器盲区:{unresolved}"


def test_in_repo_runbook_has_zero_blind_spots(checker):
    """解析器必须**完全看懂**权威 runbook。

    这是防噪音的核心断言:盲区一旦长期非零,人就会加开关把它关掉,
    守门器随即退化成静音开关。盲区必须在开发期清零,而不是在 ceremony 期被忽略。
    """
    _, unresolved = checker.analyze(IN_REPO_RUNBOOK.read_text(encoding="utf-8"))
    assert unresolved == [], f"权威 runbook 上出现解析器盲区:{unresolved}"


def test_in_repo_runbook_sealed_set_is_exhaustive(checker):
    """sealed 集合逐条锁定 —— 防止未来某次「优化」悄悄丢掉 `-m` 或派生产物覆盖。"""
    refs = checker.extract_refs(IN_REPO_RUNBOOK.read_text(encoding="utf-8"))
    assert {r for r, s in refs.items() if s} == {
        "env/bin/python",
        "scripts/bootstrap_abcr_accounts.sh",
        "scripts/bootstrap_abcr_genesis.py",
        "scripts/bootstrap_abcr_service_keys.sh",
        "scripts/bootstrap_research_memory_seal.sh",
        "scripts/build_reviewed_runtime.py",
        "scripts/import_abcr_dataset.py",
        "scripts/qualify_abcr_genesis_probation.py",
        "src/abcr/control/canary_controller.py",
        "src/abcr/control/release.py",
        "trust/review-verifier-attestation.pub",
    }


def test_main_ceremony_drain_steps_are_visible(checker):
    """§6 B2/B4 两个 drain 步是 `-m` 点分模块形态。

    初版实现对它们**完全不可见**(一个 `/` 都没有,正则无从匹配)——
    守门器自称守封印遗漏,却看不见主 ceremony 路径上的两步。
    """
    refs = checker.extract_refs(IN_REPO_RUNBOOK.read_text(encoding="utf-8"))
    assert refs.get("src/abcr/control/canary_controller.py") is True
    assert refs.get("src/abcr/control/release.py") is True


def test_checker_itself_stays_out_of_the_sealed_tree(checker):
    """本检查器**不得**进封印树 —— 否则新增它会改变 release 身份。"""
    exact, prefixes = checker._sealed_allowlist()
    ref = "scripts/check_runbook_refs.py"
    assert not checker._in_sealed_tree(ref, exact, prefixes), (
        "check_runbook_refs.py 被加进了 allowlist:这会让 candidate tree hash 变化、"
        "作废当前 review copy。它是开发期检查,不应进封印树")


def test_sealed_inventory_is_parsed_not_hardcoded(checker, tmp_path, monkeypatch):
    """派生产物清单必须从 builder **解析**得到,手抄会随 builder 演进而失真。"""
    r = _fake_repo(tmp_path)
    b = r / "scripts/build_reviewed_runtime.py"
    b.write_text(b.read_text(encoding="utf-8").replace(
        'PurePosixPath("env/bin/python")', 'PurePosixPath("runtime/bin/python3")'),
        encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", r)
    assert "runtime/bin/python3" in checker._runtime_derived()


def test_derived_inventory_parse_failure_is_fatal(checker, tmp_path, monkeypatch):
    """解析不出来必须炸,不得降级为空表静默放行。"""
    r = _fake_repo(tmp_path)
    (r / "scripts/build_reviewed_runtime.py").write_text("GIT_EXACT = 1\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", r)
    with pytest.raises(SystemExit):
        checker._runtime_derived()


# ---------------------------------------------------------------- 两类事故复现

def test_phantom_reference_is_blocked(checker, repo, tmp_path):
    """轮2 P0 复现:runbook 引用一个不存在的脚本,必须 BLOCKED。"""
    problems = _problems(checker, tmp_path,
        '执行:\n```sh\n"$ABCR_SEALED_RELEASE/scripts/qualify_abcr_nonexistent.py" --run\n```\n')
    assert any("幻影引用" in p and "scripts/qualify_abcr_nonexistent.py" in p for p in problems)


def test_sealed_omission_is_blocked(checker, repo, tmp_path):
    """轮1 复现:文件在仓库里有,但 runbook 要求从封印 release 运行而它没进 allowlist。"""
    (repo / "scripts/check_human_signature_domain.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    problems = _problems(checker, tmp_path,
        '```sh\nsudo "$ABCR_SEALED_RELEASE/scripts/check_human_signature_domain.sh"\n```\n')
    assert _sealed_omission(problems, "check_human_signature_domain.sh")


def test_sealed_script_in_allowlist_passes(checker, repo, tmp_path):
    """已进 allowlist 的脚本从封印 release 运行是合法的,不得误报。"""
    assert _problems(checker, tmp_path,
        '```sh\nsudo "$ABCR_REVIEW_FINAL/scripts/bootstrap_abcr_genesis.py" --check\n```\n') == []


def test_registered_absence_is_tolerated(checker, repo, tmp_path, monkeypatch):
    """已登记的有意缺席放行 —— 检查器不能永远红,否则会被当噪音忽略。"""
    monkeypatch.setitem(checker.KNOWN_ABSENT, "scripts/qualify_abcr_later.py",
                        "示例门未开工,开工时交付")
    assert _problems(checker, tmp_path, '`scripts/qualify_abcr_later.py`\n') == []


# ---------------------------------------------------------------- 提取器行为(保留)

def test_extract_distinguishes_sealed_context(checker):
    """同一路径:挂在封印 release 变量下才要求进 allowlist,普通提及不要求。"""
    refs = checker.extract_refs(
        '构建用 scripts/build_reviewed_runtime.py;\n'
        '而 "$ABCR_SEALED_RELEASE/scripts/abcr-launch" 从封印树运行\n')
    assert refs["scripts/build_reviewed_runtime.py"] is False
    assert refs["scripts/abcr-launch"] is True


def test_extract_strips_trailing_punctuation(checker):
    """中文标点与引号不属于路径的一部分。"""
    refs = checker.extract_refs("话术见 `ops/install/foo.md`。另见 scripts/bar.py,以及 src/abcr。")
    assert "ops/install/foo.md" in refs
    assert "scripts/bar.py" in refs
    assert "src/abcr" in refs


# =================================================================
#  绕过形态复现 —— 每条对应一种对抗审查确认的合法写法
# =================================================================

# ---- A. 引号 / 参数展开族

@pytest.mark.parametrize("cmd", [
    '"${ABCR_REVIEW_FINAL}"/scripts/abcrctl status',      # 闭引号把 ${VAR} 与 / 隔开
    '"$ABCR_REVIEW_FINAL"/scripts/abcrctl status',        # 同上,$VAR 形式
    '"${ABCR_REVIEW_FINAL}"/"scripts/abcrctl" status',    # 路径侧也带引号
    '${ABCR_REVIEW_FINAL}//scripts/abcrctl status',       # 双斜杠
])
def test_bypass_quote_between_root_and_path(checker, repo, tmp_path, cmd):
    """`"$VAR"/path` 与 `"$VAR/path"` 语义相同,后者更严谨,前者曾静默漏检。"""
    assert _sealed_omission(_problems(checker, tmp_path, f"```sh\n{cmd}\n```\n"), "scripts/abcrctl")


@pytest.mark.parametrize("expansion", [
    "${ABCR_SEALED_RELEASE%/}",          # 去尾斜杠,install 文档最常见的归一化
    "${ABCR_SEALED_RELEASE%%/}",
    "${ABCR_SEALED_RELEASE#/}",          # 补齐族,防「只修了 %」
    "${ABCR_SEALED_RELEASE:-/fallback}",  # 默认值体内含 /
    "${ABCR_SEALED_RELEASE:=/fallback}",
    "${ABCR_SEALED_RELEASE:?未设置:请先完成 §5 封印}",   # 提示语含中文、空格与冒号
    "${ABCR_SEALED_RELEASE:?}",
])
def test_bypass_parameter_expansion_modifier(checker, repo, tmp_path, expansion):
    """参数展开修饰符指向同一棵树,是加固写法而非改指向。

    讽刺之处:`${VAR:?msg}` 正是本仓 fail-closed 纪律要求的写法 ——
    作者越守纪律,旧守门器越瞎。
    """
    assert _sealed_omission(
        _problems(checker, tmp_path, f'```sh\nsudo "{expansion}/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_command_substitution_canonicalize(checker, repo, tmp_path):
    """`$(realpath "$VAR")/path` —— 防符号链接换根的自然写法。"""
    assert _sealed_omission(
        _problems(checker, tmp_path,
                  '```sh\nsudo "$(realpath "$ABCR_SEALED_RELEASE")/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_unknown_command_substitution_is_a_blind_spot(checker, repo, tmp_path):
    """非规范化命令的替换无法静态求值 —— 必须响亮报盲区,不得静默放行。"""
    assert _blind_spot(_problems(checker, tmp_path,
        '```sh\nsudo "$(cat /tmp/root)/scripts/abcrctl" status\n```\n'))


# ---- B. 别名 / 作用域族

def test_bypass_root_alias_variable(checker, repo, tmp_path):
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nROOT="${ABCR_REVIEW_FINAL}"\n"$ROOT"/scripts/abcrctl status\n```\n'),
        "scripts/abcrctl")


def test_bypass_alias_of_alias(checker, repo, tmp_path):
    """别名链必须追到不动点。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nA="$ABCR_REVIEW_FINAL"\nB="$A"\nC="${B}"\n"$C/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_scripts_dir_alias(checker, repo, tmp_path):
    """别名指向封印树的**子目录**,叶子名遂不带 `scripts/` 前缀。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nS="$ABCR_SEALED_RELEASE/scripts"\nsudo "$S/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_leaf_name_variable(checker, repo, tmp_path):
    """叶子名存在变量里,调用点没有任何字面路径。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nP=scripts/abcrctl\nsudo "$ABCR_SEALED_RELEASE/$P" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_long_intermediate_distance(checker, repo, tmp_path):
    """根与叶之间隔 >60 字符 —— 明确断言字符窗口机制已废除。"""
    pad = "--option-" + "x" * 90
    assert _sealed_omission(_problems(checker, tmp_path,
        f'```sh\nsudo "$ABCR_SEALED_RELEASE/env/bin/python" {pad} "$ABCR_SEALED_RELEASE/scripts/abcrctl"\n```\n'),
        "scripts/abcrctl")


def test_env_persists_across_code_fences(checker, repo, tmp_path):
    """变量在前一个 fence 赋值、后一个 fence 使用 —— runbook 就是这么写的。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nROOT="$ABCR_SEALED_RELEASE"\n```\n\n说明文字。\n\n```sh\nsudo "$ROOT/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_root_spelled_by_components(checker, repo, tmp_path):
    """用组件拼根 —— runbook 自己的定义就是这么写的,不是变形。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nABCR_REVIEW_ROOT="/Library/Application Support/ABCR-Genesis/reviewed"\n'
        'sudo "$ABCR_REVIEW_ROOT/$ABCR_RELEASE_ID/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_bypass_literal_expanded_path(checker, repo, tmp_path):
    """展开后的字面绝对路径,避免操作员漏设 shell 变量。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nsudo /Users/superagent/.abcr/releases/REL-3e8c1d1a/scripts/abcrctl status\n```\n'),
        "scripts/abcrctl")


# ---- C. Shell 结构族

def test_bypass_brace_expansion(checker, repo, tmp_path):
    """`{a,b}` 同父目录多文件压缩写法 —— 旧实现下两个文件名全部隐形。

    这是最严重的一类:它同时打瞎「幻影引用」与「封印遗漏」两道门。
    """
    problems = _problems(checker, tmp_path,
        '```sh\nsudo /bin/ls -l ${ABCR_SEALED_RELEASE}/scripts/{abcrctl,ghost_probe}\n```\n')
    assert _sealed_omission(problems, "scripts/abcrctl")
    assert any("幻影引用" in p and "scripts/ghost_probe" in p for p in problems)


def test_bypass_loop_over_path_list(checker, repo, tmp_path):
    """路径清单是数据、封印根在循环体里拼 —— 两者在文本上永不相邻。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nfor s in scripts/abcrctl scripts/bootstrap_abcr_genesis.py\ndo\n'
        '  sudo "$ABCR_SEALED_RELEASE/$s" --check\ndone\n```\n'),
        "scripts/abcrctl")


def test_glob_leaf_is_a_blind_spot(checker, repo, tmp_path):
    """通配符叶子展开结果不确定 —— 报盲区,不得静默放行。"""
    assert _blind_spot(_problems(checker, tmp_path,
        '```sh\nsudo /bin/ls -le "$ABCR_SEALED_RELEASE"/ops/profiles/*.sb\n```\n'))


def test_line_continuation_split_path(checker, repo, tmp_path):
    """路径被 `\\`+换行劈成两半 —— 双引号内同样是合法续行。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        '```sh\nsudo -u abcr-verifier "$ABCR_SEALED_RELEASE/scripts/\\\nabcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_comment_with_separator_does_not_break_parsing(checker, repo, tmp_path):
    """注释里的 `;` `'` `|` 不得撕裂后续解析(实测踩到过)。"""
    assert _sealed_omission(_problems(checker, tmp_path,
        "```sh\n# 注意:先 export;否则 don't 会失败 | 见 §5\n"
        'sudo "$ABCR_SEALED_RELEASE/scripts/abcrctl" status\n```\n'),
        "scripts/abcrctl")


def test_unparseable_shell_is_a_blind_spot(checker, repo, tmp_path):
    """未闭合引号 —— 报盲区,绝不放行。"""
    assert _blind_spot(_problems(checker, tmp_path,
        '```sh\nsudo "$ABCR_SEALED_RELEASE/scripts/abcrctl status\n```\n'))


def test_positional_parameter_is_a_blind_spot(checker, repo, tmp_path):
    """函数包装:`"$SEALED/$2"` 的实参绑定静态不可知。

    曾有一版把 `$2` 直接当成文件名产出一条 ref —— 那是把「解析不了」
    当成了「解析成功」,与旧实现的默认 False 同型。必须响亮失败。
    """
    assert _blind_spot(_problems(checker, tmp_path,
        '```sh\nsealed_py() {\n  sudo "$ABCR_SEALED_RELEASE/$2" --check\n}\n'
        'sealed_py abcr-verifier scripts/abcrctl\n```\n'))


def test_path_prepend_is_a_blind_spot(checker, repo, tmp_path):
    """把封印树塞进 PATH 后调用点是裸命令名 —— 不实现 PATH 语义,但必须响亮。"""
    assert _blind_spot(_problems(checker, tmp_path,
        '```sh\nPATH="$ABCR_SEALED_RELEASE/scripts:$PATH"\nexport PATH\nsudo abcrctl status\n```\n'))


# ---- D. 引用形状族

def test_module_form_dash_m_is_resolved(checker, repo, tmp_path):
    """`-m abcr.control.x` 是 runbook 运行封印树内代码的主要形态。"""
    refs = checker.extract_refs(
        '```sh\nsudo "$ABCR_SEALED_RELEASE/env/bin/python" -I -B -m abcr.control.canary_controller --once\n```\n')
    assert refs.get("src/abcr/control/canary_controller.py") is True


def test_module_form_phantom_is_blocked(checker, repo, tmp_path):
    """点分模块名写错 —— 与轮2 P0 同一事故机理,必须检出。"""
    assert any("幻影引用" in p for p in _problems(checker, tmp_path,
        '```sh\nsudo "$ABCR_SEALED_RELEASE/env/bin/python" -m abcr.control.does_not_exist\n```\n'))


def test_runtime_derived_paths_are_not_false_positives(checker, repo, tmp_path):
    """`env/bin/python` 与 `trust/*.pub` 在封印树里、不在 git 里 —— 不得误报缺失。

    这是审查者踩过的陷阱:把它们当「文件不存在」,或反过来把 `env|trust`
    塞进正则白名单。正确解法是认识到**封印树 ≠ git allowlist**。
    """
    assert _problems(checker, tmp_path,
        '```sh\nsudo "$ABCR_REVIEW_FINAL/env/bin/python" -I -B \\\n'
        '  /usr/bin/cmp "$ABCR_REVIEW_FINAL/trust/review-verifier-attestation.pub" /tmp/k.pub\n```\n') == []


# ---- E. 正则/编码回归

def test_cjk_filename_is_not_truncated(checker, repo, tmp_path):
    """中文文件名不得被截断。

    枚举式字符类会把 `scripts/cloud/R2-操作说明.md` 截成 `scripts/cloud/R2-`,
    再报一条「文件不存在」的**假**幻影引用 —— 守门器自己制造噪音是最坏的失败模式。
    """
    (repo / "scripts/cloud").mkdir()
    (repo / "scripts/cloud/R2-操作说明-非技术人员照抄版.md").write_text("x", encoding="utf-8")
    body = "照抄 `scripts/cloud/R2-操作说明-非技术人员照抄版.md` 里的每一步。\n"
    assert "scripts/cloud/R2-操作说明-非技术人员照抄版.md" in checker.extract_refs(body)
    assert _problems(checker, tmp_path, body) == []


# =================================================================
#  第二轮对抗:重写版自身被打穿的形态
#  上面那批复现的是**初版**的绕过;这批复现的是**重写版**被独立对抗找出的缺陷。
#  静默放行(该报没报)与假阳性(不该报却报)两个方向都要钉住 ——
#  前者让守门器失明,后者让它被当噪音关掉,后果同样是"没人挡"。
# =================================================================

GHOST = "scripts/ghost_probe.py"      # 夹具里不存在
PROBE = "scripts/abcrctl"             # 夹具里存在、不在 allowlist


@pytest.mark.parametrize("name,body", [
    ("变量赋绝对仓路径",
     '```sh\nR=/Users/superagent/shared-brain/ABCR/abcr\nsudo "$R/%s" --check\n```\n' % GHOST),
    ("字面绝对仓路径",
     '```sh\nsudo /Users/superagent/shared-brain/ABCR/abcr/%s --check\n```\n' % GHOST),
    ("text fence",
     '```text\nsudo "$ABCR_SEALED_RELEASE/%s" --check\n```\n' % GHOST),
    ("四空格缩进块",
     '步骤:\n\n    sudo "$ABCR_SEALED_RELEASE/%s" --check\n\n完.\n' % GHOST),
    ("长选项附值",
     '```sh\nsudo abcrctl --tool="$ABCR_SEALED_RELEASE/%s"\n```\n' % GHOST),
    ("console 提示符行",
     '```console\n# sudo "$ABCR_SEALED_RELEASE/%s" --check\n```\n' % GHOST),
    ("赋值右侧路径",
     '```sh\nQUAL=%s\nsudo "$ABCR_SEALED_RELEASE/$QUAL"\n```\n' % GHOST),
    ("子 shell 分组",
     '```sh\n( cd "$ABCR_SEALED_RELEASE" && ./%s )\n```\n' % GHOST),
    ("单行数组字面量",
     '```sh\nSTEPS=( "$ABCR_SEALED_RELEASE/%s" )\n```\n' % GHOST),
    ("time 分组",
     '```sh\ntime ( "$ABCR_SEALED_RELEASE/%s" activate )\n```\n' % PROBE),
    ("PATH 追加赋值",
     '```sh\nPATH+=":$ABCR_SEALED_RELEASE/scripts"\n```\n'),
    ("散文裸写根变量",
     '运行 $ABCR_SEALED_RELEASE/%s 即可。\n' % GHOST),
    ("散文单引号包裹",
     "运行 '$ABCR_SEALED_RELEASE/%s' 即可。\n" % GHOST),
])
def test_second_round_silent_pass_is_closed(checker, repo, tmp_path, name, body):
    """这些写法曾**完全静默**(refs 空、盲区空、rc=0)。

    现在必须产出问题 —— 检出或响亮报盲区都算合格,静默不算。
    """
    assert _problems(checker, tmp_path, body), f"{name} 仍然静默放行"


@pytest.mark.parametrize("name,body", [
    ("PWD 内建变量",
     '```sh\nPYTHONPATH=$PWD/src python3 -c "import abcr"\n```\n'),
    ("console 输出含撇号",
     "```console\n$ python3 x.py\npython3: can't open file '/x/y.py': [Errno 2]\n```\n"),
    ("标准库 -m 模块",
     '```sh\nsudo "$ABCR_SEALED_RELEASE/env/bin/python" -m json.tool\n```\n'),
    ("写入类命令的目标",
     '```sh\nsudo /bin/mkdir -p "$ABCR_SEALED_RELEASE/evidence"\n'
     'sudo /usr/bin/tee "$ABCR_SEALED_RELEASE/evidence/g.json"\n```\n'),
])
def test_second_round_false_positive_is_closed(checker, repo, tmp_path, name, body):
    """这些是真实文档的正常写法,曾被误报。守门器一旦吵闹就会被关掉。"""
    assert _problems(checker, tmp_path, body) == [], f"{name} 仍然误报"


def test_writer_command_source_is_still_checked(checker, repo, tmp_path):
    """写入类命令只有**目标**免检,**源**必须照查。

    曾有一版按命令名整体开洞,把 `install SRC DST` 的 SRC 也跳过了 ——
    真实 runbook 正是用 `install "$REPO/data/x.json" "$DST/x.json"` 装数据集,
    源文件的存在性恰恰是要核对的东西。
    """
    problems = _problems(checker, tmp_path,
        '```sh\nsudo /usr/bin/install -o root -g wheel -m 0440 \\\n'
        '  "$ABCR_SEALED_RELEASE/%s" "$ABCR_DATASET_SOURCE/benchmark.json"\n```\n' % GHOST)
    assert any("幻影引用" in p and GHOST in p for p in problems)


def test_markdown_anchor_is_not_part_of_the_filename(checker, repo, tmp_path):
    """`[§6](doc.md#小节)` 的锚点片段不属于文件名。

    连着 `#小节` 一起当路径,会报一条查无此档的**假**幻影引用。
    """
    (repo / "ops/install/foo.md").write_text("x", encoding="utf-8")
    body = '详见 [§6](ops/install/foo.md#6-post-install-qualification)。\n'
    assert "ops/install/foo.md" in checker.extract_refs(body)
    assert _problems(checker, tmp_path, body) == []


def test_cjk_quote_does_not_swallow_following_text(checker, repo, tmp_path):
    """中文引号/书名号紧贴路径尾部时不得被吞进文件名。

    否则 `「ops/install/foo.md」与` 会整串当成文件名,报一条**假**幻影引用。
    """
    (repo / "ops/install/foo.md").write_text("x", encoding="utf-8")
    refs = checker.extract_refs("台账见「ops/install/foo.md」与其批次号。\n")
    assert "ops/install/foo.md" in refs
    assert _problems(checker, tmp_path, "台账见「ops/install/foo.md」与其批次号。\n") == []


def test_cd_into_sealed_root_reports_without_phantom_noise(checker, repo, tmp_path):
    """cd 进封印根:报盲区可以,但不得把子命令词当成封印树里的文件。

    曾有一版做 cwd 路径合并,结果 `abcrctl status` 的 `status` 被当文件报幻影 ——
    cwd 追踪两头都坏(合并出的绝对路径被静默吞掉,裸词又被误报),故已移除。
    """
    problems = _problems(checker, tmp_path,
        '```sh\ncd "$ABCR_REVIEW_FINAL"\nsudo ./scripts/abcrctl status\n```\n')
    assert not any("幻影引用" in p and "status" in p for p in problems)


# =================================================================
#  第三轮对抗:健壮性与噪音
#  守门器崩溃/挂死等同于放行 —— 在 CI 里它表现为「基础设施故障」,
#  会被当成环境问题跳过,而不是被当成守门失败。
# =================================================================

@pytest.mark.parametrize("name,body", [
    ("花括号组合爆炸",
     '```sh\nls /x/scripts/a%s.py\n```\n' % ("{a,b}" * 22)),
    ("花括号深嵌套",
     '```sh\nls ${ABCR_SEALED_RELEASE}/scripts/%s\n```\n' % ("{a," * 12 + "x" + "}" * 12)),
    ("变量展开笛卡尔积",
     '```sh\nfor X in %s\ndo\n ls $X/$X/$X/$X/scripts/a.py\ndone\n```\n'
     % " ".join(f"v{i}" for i in range(40))),
    ("console 大量空白",
     '```console\n%s\n```\n' % (" " * 50000 + "x")),
])
def test_pathological_input_terminates_fast(checker, repo, tmp_path, name, body):
    """病态输入必须秒回。

    实测这四种曾分别造成:RecursionError 使 stdout 变空(真实幻影引用一并消失)、
    23 秒 / 553 MB 输出、266 MB 输出、以及 600 KB 输入 180 秒跑不完的正则回溯。
    """
    import time
    start = time.time()
    _problems(checker, tmp_path, body)
    assert time.time() - start < 10, f"{name} 耗时过长"


def test_undecodable_runbook_is_reported_not_raised(checker, repo, tmp_path):
    """读不了就说读不了,不能让异常冒到 CLI 表现成「检查跑过了」。"""
    book = tmp_path / "bad.md"
    book.write_bytes(b"# doc\n\xff\xfe bad bytes\n")
    problems = checker.check([book])
    assert any("不可读" in p for p in problems)


@pytest.mark.parametrize("name,body", [
    ("local 前缀赋值",
     '```sh\nlocal QUAL="$ABCR_SEALED_RELEASE/scripts/bootstrap_abcr_genesis.py"\n```\n'),
    ("散文句末标点",
     '详见 `$ABCR_SEALED_RELEASE/scripts/bootstrap_abcr_genesis.py`。\n'),
    ("散文加粗包裹",
     '见 **$ABCR_SEALED_RELEASE/scripts/bootstrap_abcr_genesis.py** 一节。\n'),
    ("重定向目标",
     '```sh\nsudo abcrctl doctor > "$ABCR_SEALED_RELEASE/reports/out.json"\n```\n'),
    ("json 围栏内示例",
     '```json\n{"path": "reports/doctor-release-REL.json"}\n```\n'),
    ("赋值中转的产物路径",
     '```sh\nEV="$ABCR_SEALED_RELEASE/reports/ceremony"\nsudo /bin/mkdir -p "$EV"\n```\n'),
    ("finalize 主产物",
     '```sh\nsudo /bin/cat "$ABCR_SEALED_RELEASE/release-manifest.json"\n```\n'),
])
def test_third_round_false_positive_is_closed(checker, repo, tmp_path, name, body):
    """真实文档的正常写法不得误报。

    尤其「散文句末标点」那条:带上句号后,一条**真**封印遗漏会被误诊成假幻影,
    人照着告警把它消音,那条 P0 就永久静默了 —— 噪音不只是烦,它会吃掉真信号。
    """
    assert _problems(checker, tmp_path, body) == [], f"{name} 仍然误报"


def test_heredoc_body_is_still_scanned(checker, repo, tmp_path):
    """here-doc 正文必须照常求值 —— 它常常就是要执行的脚本。

    曾有一版为消一条噪音把 here-doc 正文**整块删掉**,结果连里面真实的引用
    也一起没了(相对上一版是硬倒退)。噪音要靠剥标点解决,不是靠扔内容。
    """
    problems = _problems(checker, tmp_path,
        "```sh\nsudo bash <<'SH'\npython3 %s --apply\nSH\n```\n" % GHOST)
    assert any("幻影引用" in p and GHOST in p for p in problems)


def test_heredoc_data_payload_is_a_known_false_positive(checker, repo, tmp_path):
    """**已知边界**:here-doc 里若是数据(JSON)而非脚本,其中的路径会被当引用。

    区分「正文是脚本」与「正文是数据」需要语义判断,本版未实现。
    此测试把当前**真实行为**钉住,而不是留一个靠夹具缺目录蒙混过关的绿灯 ——
    夹具的保真度就是审查能力的天花板。真实仓库有 reports/ 目录,会报出来。
    """
    (repo / "reports").mkdir()
    problems = _problems(checker, tmp_path,
        '```sh\ncat <<EOF > /tmp/x\n{"a": "reports/genesis-notes.md", "b": 1}\nEOF\n```\n')
    assert any("reports/genesis-notes.md" in p for p in problems), (
        "若此断言开始失败,说明 here-doc 数据/脚本的区分已实现 —— "
        "请把本测试改为断言 problems == [],并更新交付单的残余风险")


def test_no_internal_marker_leaks_into_messages(checker, repo, tmp_path):
    """报文里不得出现内部标记。

    曾有形态让 `\\x00S\\x00` 原样打进操作员看到的报文 ——
    守门器输出损坏比不报还糟:它让人无法判断到底出了什么事。
    """
    for body in (
        '```sh\nsudo bash -c \'"$ABCR_SEALED_RELEASE/scripts/abcrctl" status\'\n```\n',
        '```sh\ndeclare -r Q="$ABCR_SEALED_RELEASE/%s"\n```\n' % GHOST,
    ):
        for p in _problems(checker, tmp_path, body):
            assert "\x00" not in p, f"报文泄漏内部标记:{p!r}"


@pytest.mark.parametrize("name,body", [
    ("HOME 根", '```sh\nsudo "$HOME/.abcr/releases/REL-x/%s" --check\n```\n' % GHOST),
    ("cd 双横线", '```sh\ncd -- "$ABCR_SEALED_RELEASE"\n./%s\n```\n' % GHOST),
    ("cd -P", '```sh\ncd -P "$ABCR_SEALED_RELEASE"\n./%s\n```\n' % GHOST),
    ("紧贴式 -m", '```sh\nsudo "$ABCR_SEALED_RELEASE/env/bin/python" -mabcr.control.ghostmod\n```\n'),
    ("console 无提示符", '```console\nsudo "$ABCR_SEALED_RELEASE/%s" --check\n```\n' % GHOST),
])
def test_third_round_silent_pass_is_closed(checker, repo, tmp_path, name, body):
    """这些等价写法曾静默,而它们的对照写法都能检出 —— 等价输入必须同判。"""
    assert _problems(checker, tmp_path, body), f"{name} 仍然静默放行"


# ---- F. 登记表纪律

def test_known_absent_entries_all_carry_a_reason(checker):
    """有意缺席必须写明门与交付时机,不能是空豁免 —— 否则登记表会退化成静音开关。"""
    assert checker.KNOWN_ABSENT, "登记表为空时应删除该机制,而不是留空"
    for ref, reason in checker.KNOWN_ABSENT.items():
        assert len(reason) >= 12, f"{ref} 的缺席理由过于简略:{reason!r}"


def test_unresolved_waivers_all_carry_a_reason(checker):
    """盲区豁免同款纪律:禁止通配豁免,每条必须具名并写明理由。"""
    for raw, reason in checker.UNRESOLVED_WAIVERS.items():
        assert len(reason) >= 12, f"{raw} 的豁免理由过于简略:{reason!r}"


def test_non_sealed_root_vars_all_carry_a_reason(checker):
    """非封印根变量登记同款纪律 —— 它直接决定哪些路径不参与封印判定。"""
    for var, reason in checker.NON_SEALED_ROOT_VARS.items():
        assert len(reason) >= 12, f"{var} 的登记理由过于简略:{reason!r}"

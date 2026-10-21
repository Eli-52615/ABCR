"""tests/control/test_canonical_json_parity —— canonical JSON 五份实现的字节级一致。

`canonical_json` 是全系统所有 hash 的基座:`tree_hash`、`release_id`、`receipt_id`、
`attestation_hash`、`service_config_hash`、`payload_tree_hash` 全部由它序列化后取
sha256。它在仓内有**五份独立实现**——因为 root 侧脚本刻意不 import 候选代码:

| 实现 | 用途 |
|---|---|
| `src/abcr/control/contracts.py` | 控制面本体 |
| `scripts/abcr-launch` | 每次服务启动做全树校验 |
| `scripts/abcr-bootstrap-selector` | 选主与晋级 |
| `scripts/install_abcr_runtime.py` | root 安装器 |
| `scripts/bootstrap_abcr_genesis.py` | 一次性 genesis 仪式 |

五份当前逐字相同。但**没有任何测试锁住这件事**——任一份漂移(改了 separators、
关掉 sort_keys、改 ensure_ascii、改编码)都会让该组件算出的所有 hash 与其余四方不符,
表现为全链 fail-closed,而错误信息只会说「hash 不匹配」,不会说「你的序列化口径变了」。

本项目已三次因「多组件对同一事物各持假设」出现阻断级 P0。canonical JSON 是这类风险中
**爆炸半径最大**的一个:它不是某一条策略,而是所有信任的公共地基。
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

from abcr.control.contracts import canonical_json as contracts_canonical


ROOT = Path(__file__).resolve().parents[2]

# (显示名, 相对路径, 函数名)
IMPLEMENTATIONS = [
    ("abcr-launch", "scripts/abcr-launch", "_canonical"),
    ("abcr-bootstrap-selector", "scripts/abcr-bootstrap-selector", "_canonical"),
    ("install_abcr_runtime", "scripts/install_abcr_runtime.py", "canonical"),
    ("bootstrap_abcr_genesis", "scripts/bootstrap_abcr_genesis.py", "_canonical"),
]

# 覆盖会暴露序列化口径差异的每一个维度
SAMPLES = [
    pytest.param({}, id="empty-dict"),
    pytest.param([], id="empty-list"),
    pytest.param({"b": 1, "a": 2, "c": 3}, id="key-order"),            # sort_keys
    pytest.param({"z": {"y": {"x": [3, 1, 2]}}}, id="nested"),          # 嵌套不排序 list
    pytest.param({"s": "值 with 空格"}, id="non-ascii"),                # ensure_ascii=False
    pytest.param({"s": "quote\"back\\slash"}, id="escapes"),
    pytest.param({"s": "tab\tnewline\n"}, id="control-chars"),
    pytest.param({"i": 0, "neg": -1, "big": 2 ** 53}, id="integers"),
    pytest.param({"f": 1.5, "e": 1e300}, id="floats"),                  # 浮点仓库表示
    pytest.param({"t": True, "f": False, "n": None}, id="literals"),
    pytest.param({"list": [{"b": 1, "a": 2}, {"d": 3, "c": 4}]}, id="list-of-dicts"),
    pytest.param({"path": "env/lib/python3.12/site-packages/x.py",
                  "mode": 0o444, "size": 20417, "sha256": "a" * 64}, id="tree-entry-shape"),
    pytest.param({"emoji": "🔒", "cjk": "封印树", "combining": "é"}, id="unicode-wide"),
    pytest.param({"empty_str": "", "empty_nested": {"a": {}}}, id="empty-values"),
]


def _load_script(name: str, relative: str):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def implementations():
    """加载全部五份实现,返回 (显示名, 可调用) 列表。"""
    loaded = [("contracts", contracts_canonical)]
    for label, relative, func in IMPLEMENTATIONS:
        module = _load_script(f"abcr_canonical_parity_{label.replace('-', '_')}", relative)
        assert hasattr(module, func), f"{relative} 不再提供 {func}() —— 五份实现的清单已过期"
        loaded.append((label, getattr(module, func)))
    return loaded


def test_all_five_implementations_are_present(implementations):
    """清单本身的守门:少一份就说明有组件改用了别的序列化方式。"""
    assert len(implementations) == 5, (
        f"预期五份 canonical_json 实现,实际加载到 {len(implementations)} 份。"
        f"若确有组件被移除或合并,请同步更新 IMPLEMENTATIONS 清单")


@pytest.mark.parametrize("sample", SAMPLES)
def test_canonical_bytes_identical_across_implementations(implementations, sample):
    """同一结构,五份实现必须产出**逐字节相同**的结果。"""
    results = {label: fn(sample) for label, fn in implementations}

    distinct = set(results.values())
    assert len(distinct) == 1, (
        "canonical_json 实现之间产出分叉 —— 全系统所有 hash 的基座已裂开:\n"
        + "\n".join(f"  {label}: {value!r}" for label, value in results.items()))

    # 同时锁死具体口径,避免五份一起漂移(那样上面的断言仍会通过)
    only = distinct.pop()
    assert isinstance(only, bytes), "canonical_json 必须返回 bytes 而非 str"


def test_canonical_format_contract(implementations):
    """锁死序列化口径本身:紧凑分隔符、键排序、非 ASCII 直出、UTF-8。

    上一个用例只保证「五份彼此相同」;若五份一起被改成同一种新口径,它仍会通过,
    而所有历史 hash 会集体失效。本用例把口径本身钉死。
    """
    sample = {"b": "值", "a": [1, {"d": 2, "c": 3}]}
    expected = b'{"a":[1,{"c":3,"d":2}],"b":"\xe5\x80\xbc"}'

    for label, fn in implementations:
        assert fn(sample) == expected, (
            f"{label} 的 canonical_json 口径偏离契约。"
            f"要求:sort_keys=True、separators=(',',':')、ensure_ascii=False、UTF-8 编码")


def test_nan_and_infinity_rejected(implementations):
    """allow_nan=False:NaN/Infinity 不是合法 JSON,必须在序列化处就拒绝。"""
    for label, fn in implementations:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                fn({"x": bad})

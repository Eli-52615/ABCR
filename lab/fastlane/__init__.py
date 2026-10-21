"""ABCR 最小快道：本机单用户的"实验 → 看结果 → 改假设 → 再实验"闭环。

刻意放在 `lab/` 而不是 `src/abcr/probe/`：`src/abcr/` 在守门器的
`GIT_PREFIXES` 里，且 builder 会把 `src/abcr/**` 逐文件映射进
`env/lib/python3.12/site-packages/abcr/`。在那里新增文件会同时改变
candidate 与 **runtime tree hash**——而 `runtime_tree_hash =
46adc351f51f6f7c2d827214239158b2dd7dde5af00d2f3e86ee57409afb794c`
连续多版未变，正是 V5 attestation 的核心证据之一。
（具体多少版，工程进展史与 08/09 两份文档口径不一，此处不复述数字。）

关键点：这与是否执行 `finalize` 无关。**文件位置本身决定它进不进封印树。**

新增文件前的判据（跑一句就知道）::

    python3 -c "import sys;sys.path.insert(0,'scripts');\\
    import check_runbook_refs as C;e,p=C._sealed_allowlist();\\
    print(C._in_sealed_tree('你的/路径.py',e,p))"
"""

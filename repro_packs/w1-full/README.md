# Repro Pack: mini-loop

## 内容
本包含 182 个文件，打包时间 2026-07-12T23:37:45.565729+00:00。
Git commit: 5fc90d6cd8da9666038a62e883b64d67740b59e6

## 复算命令
```
python3 rescore/rescore.py .
```
（系统 python3 即可，rescore/ 目录自含全部代码，无第三方依赖）

对 pack 内所有文件的 SHA256 校验：
```
python -m abcr.review --pack <本目录路径>
```

## 诚实条款
本包承诺的复现 = ①工件级（原始输出永久保存，再分析不依赖重新生成）+ ②统计级（同 config 重跑，聚合指标在自身抽样波动内一致）+ ③单机确定级（同机同环境 temp 0 双跑一致）。不承诺跨硬件 bit 级一致——浮点归约序差异是行业已知事实。本包全部产物为 Mac dev 档（fp16/MPS 或 fp32/CPU），non-citable，仅证明管线正确性，不构成任何科学结论。

## 标注
- rig-validation run — NOT evidence
- non-citable
- dev split
- exploratory
- Mac dev 档（fp16/MPS 或 fp32/CPU）

## Judge 谱系
- judge_model: deepseek-chat
- judge_lineage: replaced(official gpt-4.1-mini-2025-04-14)

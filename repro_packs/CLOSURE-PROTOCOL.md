# 闭合验收协议（CLOSURE-PROTOCOL）

## 前提
本协议验证 W1 终包（`repro_packs/w1-mini`）的复算闭合性：一个完全独立的 Claude Code 会话，仅凭包内信息，能否从原始数据独立重算出一致的分数。

## 操作步骤

开一个**全新** Claude Code 会话（空目录启动，勿在 abcr 仓内），把下面这段话原样发给它：

> 你收到一个实验复现包：/Users/superagent/abcr/repro_packs/w1-mini。**除该目录外不要读取任何项目文件、不要使用任何项目 venv**。按包内 README 的复算命令（`python3 rescore/rescore.py .`，包内自含全部代码，系统 python3 即可），从原始 steps.jsonl 独立重算全部确定性分数，与包内 scores 逐条比对，输出：逐 run 一致/不一致结论、任何哈希或链校验异常、你无法仅凭包内信息完成复算的每一处缺口。

## 验收标准

1. **分数逐条一致**：rescore 对每个 run 输出 PASS
2. **链与哈希零异常**：SHA256 校验全部 PASS，hash chain 完整
3. **缺口清单为空**：新会话无需任何包外信息即可完成复算

**任何缺口 = G5 未过**，修包重验。

## 执行方式

- 方式一（推荐，更快）：由 C 包窗口自行开新会话执行
- 方式二：请楠在 STATUS-C 终态后手动执行

两者都算数。结果记 `repro_packs/w1-mini/CLOSURE-RESULT.md`。

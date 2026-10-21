# R2 真批证据归档

R2 硬门通过的真实云批证据放这里(每批一个 dated 子目录)。

## 结构
```
r2-results/
└── B-<UTC>-0001/              # 一个 batch_id 一个目录
    ├── r2-result.tar.gz       # 云机打回的原始包(configs/envelopes + reports + demos + ledger + data/runs)
    └── (解包后可选保留 demos/repro-<batch>/ 作独立可复算的 citable 包)
```

## 每批该存什么(r2-result.tar.gz 里已含)
- `demos/repro-<batch>/` —— C 出的**自包含 citable 复算包**(含 rescore_standalone.py,空 PYTHONPATH 仓库外可独立复算 agreement)。这是最核心的证据。
- `reports/audit/<batch>.json|md` —— A 的六项审计报告。
- `ledger/` —— 该批的账本链(runs_index/batches/costs)。
- `data/runs/<rid>/` —— 每 run 的 manifest/steps/scores(真模型输出 + 分数)。
- `configs/envelopes/<batch>.json` —— 签发的批次信封。

## 首批(2026-07-16)
- **batch_id: B-20260716T070201Z-0001** —— 首次真 7B(Qwen2.5-7B-Instruct@main, bf16, 24GB 卡)golden10 mini环批。
- R2 判据:A 审计 item1-5 PASS;C 独立复算 agreement_deterministic_v1=1.0 / agreement_rescore_v1=1.0。
- 途中修的四个真跑坑(engine 分支接线 / revision 占位 / 缺 chat_template 冻结件 / scorer rate 精度对齐)均已在 r2-integration 提交。
- item6(成本对账)需补记 GPU 实耗后 PASS(可选,不影响核心判定)。

> 注:本目录不入 git(证据体量);ABCR 整体在 shared-brain/.stignore 外不同步。要长期备份靠 abcr-backups 或另拷冷备。

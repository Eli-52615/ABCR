# Trait Artifact Review Request

> 给楠的过目清单。通过后将 provenance.json 的 review_status 改为 approved。

## conscientiousness (尽责)

### 检查项

1. **指令对是否双极干净**：5 对 pos/neg 指令，pos 要求仔细/严谨/逐步验证，neg 要求草率/跳步/不检查
   - [ ] 每对确实形成对立极
   - [ ] 无歧义或自相矛盾

2. **题目是否自然多样**：40 题拆 20+20（extract/eval），涵盖代码检查、事实验证、规划、推理等
   - [ ] 题目不显式提及"conscientiousness"
   - [ ] 题目场景多样
   - [ ] 两集无交集（E17 已验证）

3. **eval_prompt 是否与 trait 一致**：包含 REFUSAL 标记 + 0-100 打分说明
   - [ ] 对 trait 的描述与指令对/题目一致
   - [ ] 格式与官方 trait 的 eval_prompt 结构一致

### 文件位置
- `artifacts/traits/conscientiousness/extract.json` (20 题)
- `artifacts/traits/conscientiousness/eval.json` (20 题)
- `artifacts/traits/conscientiousness/provenance.json` (draft)

### 状态
- draft 态即可继续 dev 工序
- 云日 #2 前需 approved

---

## openness (开放性)

### 检查项

1. **指令对是否双极干净**：5 对 pos/neg 指令，pos 要求好奇/探索/拥抱不确定/挑战既定解释，neg 要求传统/果断/实用/不偏离共识
   - [ ] 每对确实形成对立极
   - [ ] 无歧义或自相矛盾

2. **题目是否自然多样**：40 题拆 20+20（extract/eval），涵盖学习方法、职业决策、技术评价、社会议题等
   - [ ] 题目不显式提及"openness"
   - [ ] 题目场景多样
   - [ ] 两集无交集（E17 已验证）

3. **eval_prompt 是否与 trait 一致**：定义 openness 为好奇心/想象力/对新思想的接纳度
   - [ ] 对 trait 的描述与指令对/题目一致
   - [ ] 格式与官方 trait 的 eval_prompt 结构一致

### 文件位置
- `artifacts/traits/openness/extract.json` (20 题)
- `artifacts/traits/openness/eval.json` (20 题)
- `artifacts/traits/openness/provenance.json` (draft)

### 状态
- draft 态即可继续 dev 工序
- 云日 #1 前需 approved

---

## neuroticism (神经质)

### 检查项

1. **指令对是否双极干净**：5 对 pos/neg 指令，pos 要求焦虑/自我怀疑/威胁敏感/灾难化/情绪化，neg 要求冷静/自信/韧性/平衡/情绪稳定
   - [ ] 每对确实形成对立极
   - [ ] 无歧义或自相矛盾

2. **题目是否自然多样**：40 题拆 20+20（extract/eval），涵盖职业变动、财务决策、人际关系、健康焦虑等
   - [ ] 题目不显式提及"neuroticism"
   - [ ] 题目场景多样
   - [ ] 两集无交集（E17 已验证）

3. **eval_prompt 是否与 trait 一致**：定义 neuroticism 为焦虑/情绪不稳/对威胁的敏感度
   - [ ] 对 trait 的描述与指令对/题目一致
   - [ ] 格式与官方 trait 的 eval_prompt 结构一致

### 文件位置
- `artifacts/traits/neuroticism/extract.json` (20 题)
- `artifacts/traits/neuroticism/eval.json` (20 题)
- `artifacts/traits/neuroticism/provenance.json` (draft)

### 状态
- draft 态即可继续 dev 工序
- 云日前需 approved

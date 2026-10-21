# -*- coding: utf-8 -*-
"""补充轮整合脚本 2026-07-17：36新行(R105-R140)入定位表CSV+md镜像+BibTeX追加。
一次性脚本，执行后留档于bias-sweep/以备追溯。"""
import csv, json, glob, re, sys

BASE = '/Users/superagent/shared-brain/ABCR/lit-review'
CSV = BASE + '/deliverables/定位表.csv'
MD = BASE + '/deliverables/定位表.md'
BIB = BASE + '/deliverables/abcr-litreview.bib'

# ---------- 1. 读入 ----------
with open(CSV, encoding='utf-8-sig', newline='') as f:
    old = list(csv.reader(f))
hdr = old[0]
assert old[-1][0] == 'R104' and len(old) == 105, (old[-1][0], len(old))

rows = []
for fn in sorted(glob.glob(BASE + '/rows/rows-batch-4[1-6].jsonl')):
    for l in open(fn, encoding='utf-8'):
        l = l.strip()
        if l:
            rows.append(json.loads(l))
assert len(rows) == 36

# ---------- 2. JSONL -> CSV行 ----------
new_csv = []
keymap = {}  # key -> Rid
for n, r in enumerate(rows):
    rid = f'R{105+n}'
    keymap[r['key']] = rid
    rec = []
    for col in hdr:
        if col == 'ID':
            rec.append(rid)
            continue
        v = r[col]
        if col == '相邻主张':
            v = '/'.join(v)
        elif col == '升级命中':
            v = '是' if v else '否'
        else:
            v = str(v)
        rec.append(v)
    new_csv.append(rec)

with open(CSV, 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator='\r\n')
    for rec in old + new_csv:
        w.writerow(rec)
print('CSV written:', len(old + new_csv) - 1, 'rows')

# ---------- 3. md镜像 ----------
def mdcell(s):
    return s.replace('|', '｜')

lines = [
    '# ABCR 定位表（镜像自 定位表.csv，140行=137篇唯一论文；3对跨前沿重复行R009/R087、R012/R058、R013/R057互标待D3裁决）',
    '',
    '> 2026-07-17 审计修复：R001/R007补记C2；R028 prox 3→2、R077 prox 0→2（以Gate0全文定界为准）；补录R103/R104（热图§3.3缺口#1）。"ABCR差异"列全空=楠亲笔。',
    '>',
    '> 2026-07-17 补充轮追加：R105–R140共36行（残余偏倚2/3/4侦察轮+补扫S1–S4），邻近度3×6行（R105–R110）+邻近度2×30行，溯源列均注明 bias-sweep补充轮；行↔key对照见 deliverables/补充轮-偏倚234-报告.md 附表。',
    '',
    '| ' + ' | '.join(hdr) + ' |',
    '|' + '---|' * len(hdr),
]
for rec in (old[1:] + new_csv):
    lines.append('| ' + ' | '.join(mdcell(v) for v in rec) + ' |')
with open(MD, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines) + '\n')
print('MD written:', len(lines), 'lines')

# ---------- 4. BibTeX ----------
bib = open(BIB, encoding='utf-8').read()
existing_keys = set(re.findall(r'@\w+\{([^,]+),', bib))
print('existing bib keys:', len(existing_keys))

# (bibkey, entrytype, fields dict) —— 顺序即R105..R140
B = []
def E(rowkey, bibkey, title, author, year, *, eprint=None, url=None, how=None,
      journal=None, volume=None, pages=None, doi=None, note=None, etype=None, cnote=''):
    B.append((rowkey, bibkey, title, author, year, eprint, url, how,
              journal, volume, pages, doi, note, etype, cnote))

E('arxiv:2601.06403', 'dong2026steer',
  'Steer Model beyond Assistant: Controlling System Prompt Strength via Contrastive Decoding',
  'Yijiang River Dong and Tiancheng Hu and Zheng Hui and Nigel Collier', 2026,
  eprint='2601.06403')
E('arxiv:2504.06868', 'lim2025panda',
  'Persona Dynamics: Unveiling the Impact of Personality Traits on Agents in Text-Based Games',
  'Seungwon Lim and Seungbeen Lee and Dongjun Min and Youngjae Yu', 2025,
  eprint='2504.06868', how='ACL 2025 Long', url='https://aclanthology.org/2025.acl-long.1515/',
  cnote='; 双托管(ACL+arXiv)只留本条')
E('openreview:duDmnRyJh5', 'zhuravel2026activation',
  'Activation Steering for Tool-Poisoning Defense in Language-Model Agents',
  'Artem Zhuravel and Hubert M. Pysklo and Autinn Au-Yeung', 2026,
  url='https://openreview.net/forum?id=duDmnRyJh5', how='ICML 2026 AIWILD Workshop')
E('openreview:WVVSObO4oT', 'huh2026steering',
  'Steering LLMs for Multi-agent Decision-making using Representation Learning',
  'Dom Huh and Prasant Mohapatra', 2026,
  url='https://openreview.net/forum?id=WVVSObO4oT', how='ICLR 2026 Workshop AIMS')
E('openreview:GcpNaqxp0z', 'arr2026big5scaler',
  'Big5-Scaler: Fine-Grained Big Five Conditioning for Socially Grounded LLM Agents',
  '{ARR匿名投稿}', 2026,
  url='https://openreview.net/forum?id=GcpNaqxp0z', how='ACL ARR 2026 May Submission',
  note='前身版 arXiv:2508.06149 (Gunhee Cho and Yun-Gyung Cheong, Scaling Personality Control in LLMs with Big Five Scaler Prompts)')
E('arxiv:2509.23055', 'yao2025peacemaker',
  'Peacemaker or Troublemaker: How Sycophancy Shapes Multi-Agent Debate',
  'Binwei Yao and Chao Shang and Wanyu Du and Jianfeng He and Ruixue Lian and Yi Zhang and Hang Su and Sandesh Swamy and Yanjun Qi', 2025,
  eprint='2509.23055')
E('arxiv:2405.01768', 'he2024context',
  'Context Steering: Controllable Personalization at Inference Time',
  'Jerry Zhi-Yang He and Sashrika Pandey and Mariah L. Schrum and Anca Dragan', 2024,
  eprint='2405.01768', cnote='; B2-01书目标注ICLR 2025, arXiv v3全文无venue声明')
E('arxiv:2504.10191', 'veselovsky2025localized',
  'Localized Cultural Knowledge is Conserved and Controllable in Large Language Models',
  'Veniamin Veselovsky and Berke Argin and Benedikt Stroebl and Chris Wendler and Robert West and James Evans and Thomas L. Griffiths and Arvind Narayanan', 2025,
  eprint='2504.10191', how='ACL 2025')
E('arxiv:2605.03907', 'heyman2026steer',
  'Steer Like the LLM: Activation Steering that Mimics Prompting',
  'Geert Heyman and Frederik Vandeputte', 2026,
  eprint='2605.03907', how='ICML 2026 (poster 66813; GitHub称spotlight)',
  cnote='; 双托管(ICML OpenReview+arXiv)只留本条')
E('openreview:itYG95jkKx', 'sun2026bridge',
  'BRIDGE: Triangular Fixed-Point Refinement for Long-Horizon Persona Consistency',
  'Haotong Sun and Yinghui Jiang and Bocheng Xu and Jianye Xie', 2026,
  url='https://openreview.net/forum?id=itYG95jkKx', how='ICML 2026 main (icml.cc poster 62193)',
  cnote='; 作者序按行内引文(icml.cc/GitHub补核), 侦察记录序为Jiang/Xu/Xie/Sun')
E('acl:2026.acl-long.1336', 'qi2026dynamic',
  'Beyond Static Persona Consistency: Dynamic Persona Coherence in LLM Role-Playing',
  'Qi and Zhang and Zeng and Liu and Zhou and Miao and Yan and Guan', 2026,
  url='https://aclanthology.org/2026.acl-long.1336/', how='ACL 2026 Long, pp. 28942--28956',
  cnote='; 作者为姓氏级序列(Anthology页全名待Tier-1精读时补)')
E('openreview:doy2uIaAYt', 'qin2026tracing',
  'Tracing the Persona Circuit: How Large Language Models Encode and Express Character Traits',
  'Guanzheng Qin and Chenghao Sun and Zhining Xie and Xinmei Tian', 2026,
  url='https://openreview.net/forum?id=doy2uIaAYt', how='ICML 2026 (regular)')
E('openreview:qlYv5y0cWf', 'blank2026subliminal',
  'Subliminal Learning Is Steering Vector Distillation',
  'Camila Blank and Agam Bhatia and Senthooran Rajamanoharan and Arthur Conmy and Neel Nanda', 2026,
  eprint='2606.00995', how='ICML 2026 Mech Interp Workshop Poster',
  cnote='; 双托管(OpenReview qlYv5y0cWf+arXiv)只留本条')
E('arxiv:2506.19823', 'wang2025personafeatures',
  'Persona Features Control Emergent Misalignment',
  'Miles Wang and Tom Dupré la Tour and Olivia Watkins and Alex Makelov and Ryan A. Chi and Samuel Miserendino and Jeffrey Wang and Achyuta Rajaram and Johannes Heidecke and Tejal Patwardhan and Dan Mossing', 2025,
  eprint='2506.19823', cnote='; 双托管(cdn.openai.com PDF+arXiv)只留本条')
E('web:alignment.openai.com:helpful-assistant-features', 'dupretour2025helpful',
  'Helpful assistant features suppress emergent misalignment',
  'Tom Dupré la Tour and {OpenAI Interpretability team}', 2025,
  url='https://alignment.openai.com/helpful-assistant-features/',
  how='OpenAI Alignment Blog, 2025-12-22')
E('arxiv:2607.05790', 'chen2026controlling',
  'Controlling Tool Use with Heading-Specific Activation Steering',
  'Yuqi Chen and Vincent Siu and Yang Liu and Dawn Song and Chenguang Wang', 2026,
  eprint='2607.05790')
E('openreview:uPF7ocza0O', 'gilg2026probing',
  'Probing Persona-Dependent Preferences in Language Models',
  'Oscar Gilg and Pierre Beckmann and Daniel Paleka and Patrick Butlin', 2026,
  eprint='2605.13339', how='ICML 2026 Mech Interp Workshop Poster',
  cnote='; 双托管(OpenReview uPF7ocza0O+arXiv)只留本条')
E('openreview:X89cn3iy8b', 'sheta2026behavioural',
  'Behavioural Asymmetry Across Activation Interventions for Big Five Personality Control in LLMs',
  'Hala Sheta', 2026,
  url='https://openreview.net/forum?id=X89cn3iy8b', how='ICML 2026 MusIML Workshop Poster')
E('openreview:6LfXccur0Z', 'mckenzie2026endogenous',
  'Endogenous Resistance to Activation Steering in Language Models',
  'McKenzie and Pepper and Servaes and Leitgab and Cubuktepe and Vaiana and de Lucena and Rosenblatt and Graziano', 2026,
  url='https://openreview.net/forum?id=6LfXccur0Z', how='ICLR 2026 Trustworthy AI Workshop',
  cnote='; 作者为姓氏级序列(侦察记录载Alex McKenzie/Keenan Pepper, AE Studio系); Sci4DL副本8bTfklyy7v')
E('arxiv:2512.07092', 'wang2025geometry',
  'The Geometry of Persona: Disentangling Personality from Reasoning in Large Language Models',
  'Zhixiang Wang', 2025,
  eprint='2512.07092')
E('arxiv:2607.07916', 'baines2026cartography',
  'Persona Cartography: Charting Language Model Personality Traits in Weight Space',
  'Luke Baines and Anton Gonzalvez Hawthorne and Mariia Koroliuk and Irakli Shalibashvili and Clément Dumas and Konstantinos Voudouris and David Demitri Africa', 2026,
  eprint='2607.07916', cnote='; LASR Labs+UK AISI')
E('arxiv:2511.05408', 'fierro2025weight',
  'Steering Language Models with Weight Arithmetic',
  'Constanza Fierro and Fabien Roger', 2025,
  eprint='2511.05408')
E('arxiv:2605.21006', 'kelkar2026devils',
  "Playing Devil's Advocate: Off-the-Shelf Persona Vectors Rival Targeted Steering for Sycophancy",
  'Ishaan Kelkar and Nebras Alam and Vikram Kakaria and Madhur Panwar and Vasu Sharma and Maheep Chaudhary', 2026,
  eprint='2605.21006', how='EIML@ICML 2026 Workshop')
E('acl:2026.findings-acl.958', 'wei2026situational',
  'Beyond Static Personas: Situational Personality Steering for Large Language Models',
  'Wei and Li and Wang and Deng', 2026,
  url='https://aclanthology.org/2026.findings-acl.958/', how='Findings of ACL 2026, pp. 19185--19210',
  cnote='; 作者为姓氏级序列(Anthology页全名待Tier-1精读时补); 另有CoRR双托管')
E('openreview:gkG8JOOUF4', 'nie2025adapa',
  'Adaptive Preference Arithmetic: Modeling Dynamic Preference Strengths for LLM Agent Personalization (AdaPA-Agent)',
  'Hongyi Nie and Yaqing Wang and Mingyang Zhou and Feiyang Pan and Quanming Yao and Zhen Wang', 2025,
  url='https://openreview.net/forum?id=gkG8JOOUF4', how='NeurIPS 2025 (poster)')
E('openreview:7847AalUvX', 'chen2026goaldrift',
  'Goal-Drift Probes: Anticipating Multi-Turn LLM Agent Failure From Mid-Network Activations',
  'Oliver Yangluo Chen', 2026,
  url='https://openreview.net/forum?id=7847AalUvX', how='ICML 2026 AIWILD Workshop')
E('openreview:WLqC8PfnSc', 'prakash2026mafiapersona',
  'MafiaPersona: A Multi-Agent Adversarial Benchmark for Evaluating Persona Persistence in Large Language Models',
  'Ojaswi Prakash and Dhruv Kumar and Murari Mandal and Mohan Kankanhalli and Yash Sinha', 2026,
  url='https://openreview.net/forum?id=WLqC8PfnSc', how='ICML 2026 NExT-Game Workshop')
E('arxiv:2506.12657', 'liu2025socratic',
  'Synthetic Socratic Debates: Examining Persona Effects on Moral Decision and Persuasion Dynamics',
  'Jiarui Liu and Yueqi Song and Yunze Xiao and Mingqian Zheng and Lindia Tjuatja and Jana Schaich Borg and Mona Diab and Maarten Sap', 2025,
  eprint='2506.12657', how='EMNLP 2025',
  cnote='; 双渠道命中合并(OpenReview dtJC5wLd44+arXiv)只留本条')
E('acl:2025.ijcnlp-long.186', 'licato2025strategic',
  'Do Persona-Infused LLMs Affect Performance in a Strategic Reasoning Game?',
  'John Licato and Stephen Steinle', 2025,
  url='https://aclanthology.org/2025.ijcnlp-long.186/', how='IJCNLP-AACL 2025 main long, pp. 3497--3528')
E('web:anthropic.com:emergent-misalignment-reward-hacking', 'anthropic2025shortcuts',
  'From shortcuts to sabotage: natural emergent misalignment from reward hacking',
  '{Anthropic Alignment Science}', 2025,
  url='https://www.anthropic.com/research/emergent-misalignment-reward-hacking',
  how='anthropic.com/research, 2025-11-21 (附全文PDF; 非同行评审lab报告)')
E('web:anthropic.com:teaching-claude-why', 'anthropic2026teaching',
  'Teaching Claude why',
  '{Anthropic}', 2026,
  url='https://www.anthropic.com/research/teaching-claude-why',
  how='anthropic.com/research, 2026-05-08')
E('web:alignment.anthropic.com:msm', 'li2026msm',
  'Model Spec Midtraining: Improving How Alignment Training Generalizes',
  'Chloe Li and Nevan Wichers and Sara Price and Samuel Marks and Jon Kutasov', 2026,
  url='https://alignment.anthropic.com/2026/msm/',
  how='Anthropic Alignment Science Blog, 2026-05-05')
E('doi:10.1038/s41598-026-56163-8', 'sakai2026cooperative',
  'Effects of personality steering on cooperative behavior in large language model agents',
  'Sakai and Yokoyama and Tateishi and Ichinose', 2026,
  journal='Scientific Reports', doi='10.1038/s41598-026-56163-8',
  url='https://www.nature.com/articles/s41598-026-56163-8', etype='article',
  cnote='; 作者为姓氏级序列(侦察记录载M. Sakai/M. Yokoyama/W. Tateishi)')
E('arxiv:2511.01689', 'maiya2025opencharacter',
  'Open Character Training: Shaping the Persona of AI Assistants through Constitutional AI',
  'Sharan Maiya and Henning Bartsch and Nathan Lambert and Evan Hubinger', 2025,
  eprint='2511.01689')
E('doi:10.3724/SP.J.1041.2025.0929', 'jiao2025ai',
  '当AI“具有”人格：善恶人格角色对大语言模型道德判断的影响',
  '焦丽颖 and 李昌锦 and 陈圳 and 许恒彬 and 许燕', 2025,
  journal='心理学报 (Acta Psychologica Sinica)', volume='57(6)', pages='929--946',
  doi='10.3724/SP.J.1041.2025.0929',
  url='https://journal.psych.ac.cn/xlxb/CN/10.3724/SP.J.1041.2025.0929', etype='article',
  cnote='; 纯中文全文, 期刊英文摘要页可达')
E('doi:10.3724/SP.J.1041.2026.1237', 'li2026alignment',
  '大语言模型的人格化对齐及其对道德判断的影响',
  '李昌锦 and 焦丽颖 and 陈圳 and 许恒彬 and 吴胜涛 and 许燕', 2026,
  journal='心理学报 (Acta Psychologica Sinica)', volume='58(7)', pages='1237--1253',
  doi='10.3724/SP.J.1041.2026.1237',
  url='https://journal.psych.ac.cn/xlxb/CN/10.3724/SP.J.1041.2026.1237', etype='article',
  note='ChinaXiv 预印本 202603.00082', cnote='; 纯中文全文')

assert len(B) == 36, len(B)
rowkeys = [r['key'] for r in rows]
assert [b[0] for b in B] == rowkeys, '顺序或key不匹配'
newkeys = [b[1] for b in B]
assert len(set(newkeys)) == 36
clash = set(newkeys) & existing_keys
assert not clash, clash

rowmeta = {r['key']: r for r in rows}
out = ['', '',
       '% ===== 补充轮追加 2026-07-17：残余偏倚2/3/4侦察+补扫S1-S4，R105-R140共36条 =====',
       '% key查重完成(与既有101条无冲突)；双托管论文各留一条(arXiv优先，见各条comment)',
       '% 元数据来源：arXiv API(14条全作者名核实)/OpenReview API v2 JSON/ACL Anthology/nature.com/心理学报期刊站；姓氏级作者序列已在comment如实标注', '']
for (rowkey, bibkey, title, author, year, eprint, url, how,
     journal, volume, pages, doi, note, etype, cnote) in B:
    r = rowmeta[rowkey]
    rid = keymap[rowkey]
    et = etype or 'misc'
    L = [f'@{et}{{{bibkey},', f'  title = {{{title}}},', f'  author = {{{author}}},',
         f'  year = {{{year}}},']
    if eprint:
        L.append(f'  eprint = {{{eprint}}},')
        L.append('  archivePrefix = {arXiv},')
        if not url:
            url = f'https://arxiv.org/abs/{eprint}'
    if journal:
        L.append(f'  journal = {{{journal}}},')
    if volume:
        L.append(f'  volume = {{{volume}}},')
    if pages:
        L.append(f'  pages = {{{pages}}},')
    if doi:
        L.append(f'  doi = {{{doi}}},')
    if url:
        L.append(f'  url = {{{url}}},')
    if how:
        L.append(f'  howpublished = {{{how}}},')
    if note:
        L.append(f'  note = {{{note}}},')
    L.append(f'  comment = {{ABCR定位表 {rid}, 前沿{r["前沿"]}, 邻近度{r["邻近度"]}, 补充轮2026-07-17(key={rowkey}){cnote}}}')
    L.append('}')
    out.append('\n'.join(L))
    out.append('')

with open(BIB, 'a', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('BIB appended:', len(B), 'entries')

# 行↔key对照表落盘供报告引用
with open(BASE + '/bias-sweep/_R105-R140-keymap.json', 'w', encoding='utf-8') as f:
    json.dump({keymap[k]: k for k in rowkeys}, f, ensure_ascii=False, indent=1)
print('keymap saved')

# Philophany 零数据起步知识图谱生成方法

本文档描述一套从接近空白状态生成 Philophany 哲学家图谱的方法。这里的“空白”指：没有现成的 `data.js` 角色卡和关系图谱。最终目标是生成一个经过机器初筛、LLM 审稿、人工确认后的 `data.js`。

核心原则：

- `data.js` 是最终产物，不是初始输入。
- 机器负责收集、抽取、初筛和提出候选。
- LLM 负责解释型审稿和补全，但不能直接写入正式图谱。
- 人工确认是进入产品图谱前的最后关口。

## 目标产物

最终生成的 `data.js` 应包含两类数据：

1. 哲学家角色卡
   - `id`
   - `name`
   - `era`
   - `tradition`
   - `color`
   - `coreConcepts`
   - `topics`
   - `stance`
   - `voice`
   - `summary`
   - `opening`
   - `questionHooks`

2. 哲学家关系边
   - `source`
   - `target`
   - `type`
   - `weight`
   - `reason`

当前正式关系类型：

- `influence`：历史影响、师承、思想谱系。
- `affinity`：思想亲缘、互补关系、共享问题意识。
- `tension`：同一核心问题上的张力、冲突或可辩论分歧。

暂时不把 `critiques` 作为单独关系类型。批判性关系先归入 `tension`，避免前端和推荐逻辑过早扩张。

## 零数据起步流程

推荐流程如下：

```txt
philosopher seed list
        ↓
Wikidata / Wikipedia / external sources
        ↓
raw_philosopher_sources.json
        ↓
LLM 生成 philosopher card candidates
        ↓
reviewed_philosopher_cards.json
        ↓
人工确认
        ↓
NetworkX + local embedding 关系初筛
        ↓
local_graph_candidates.json
        ↓
OpenRouter GPT-5.5 LLM relation review
        ↓
reviewed_graph_relations.json
        ↓
人工确认
        ↓
product_graph_relations.json
        ↓
data.js
```

## 第一步：准备哲学家种子列表

零数据起步仍然需要一个最小种子列表，否则系统不知道从哪里开始抓资料。这个列表可以很小，只需要稳定标识。

建议文件：

```txt
data/seeds/philosophers.json
```

建议字段：

```json
[
  {
    "id": "socrates",
    "qid": "Q913",
    "preferredNameZh": "苏格拉底",
    "preferredNameEn": "Socrates"
  }
]
```

其中 `qid` 很重要。它能避免同名、译名、消歧页导致的数据污染。

## 第二步：抓取基础事实数据

脚本：

```bash
python3 scripts/generate_knowledge_graph.py
```

输出：

```txt
data/generated/wikidata_graph.json
```

这一层只生成基础事实和资料入口：

- Wikidata QID
- 中英文 label
- 中英文 description
- Wikipedia 链接
- 生卒时间
- 职业
- 领域
- 运动/流派
- 受谁影响
- 代表作

这一层不能直接生成最终角色卡。原因是 Wikidata 更像结构化索引，适合给事实背景，但不擅长表达思想风格、概念结构和圆桌发言方式。

## 第三步：抓取思想文本摘录

候选资料应进一步从 Wikipedia 或其他来源抓取思想相关段落。

当前已有缓存文件：

```txt
data/generated/wikipedia_philosophy_extracts.json
```

抓取逻辑：

- 优先中文 Wikipedia。
- 中文不足时补英文 Wikipedia。
- 优先抽取标题包含思想、哲学、学说、伦理、认识论、知识论、形而上、政治哲学等关键词的 section。
- 英文侧优先抽取 philosophy、thought、ideas、doctrine、ethics、epistemology、metaphysics 等 section。

注意：Wikipedia 摘录只作为候选材料，不作为最终权威结论。它可能偏生平，也可能遗漏重要思想。

## 第四步：生成哲学家角色卡候选

在真正没有 `data.js` 的情况下，必须先生成角色卡候选，然后再谈关系图谱。

建议新增中间产物：

```txt
data/generated/philosopher_card_candidates.json
```

每张候选卡应包含：

- 基础身份：姓名、时代、传统。
- 思想摘要：不超过 1-2 句话。
- 核心概念：3-6 个。
- 可讨论话题：例如自由、道德、意义、欲望、政治、语言、知识。
- 立场维度：用固定 schema 生成数值。
- 圆桌语气：用于后续角色发言。
- 开场句和追问钩子。
- `evidenceBasis`：说明来自 Wikidata、Wikipedia、常识性哲学史，还是 LLM 解释。
- `needsReview: true`。

LLM 可以参与这一步，但输出必须经过人工确认。因为角色卡会直接影响后续推荐、关系判断和圆桌发言质量。

## 第五步：人工确认角色卡

建议新增文件：

```txt
data/generated/reviewed_philosopher_cards.json
```

人工审核重点：

- 核心概念是否准确。
- 传统和时代是否合适。
- 话题是否过宽。
- 立场维度是否符合常识。
- 语气是否适合产品，而不是模仿具体文风或伪造语录。
- 是否有伪造引文、页码、著作章节。

确认后的角色卡进入：

```txt
data/generated/reviewed_philosopher_cards.json
```

这个文件是后续关系生成的 cards 输入，但还不是最终 `data.js`。

## 第六步：本地关系初筛

有了确认过的角色卡后，再做关系候选生成。

脚本当前为：

```bash
conda run -n philophany python scripts/generate_local_graph_candidates.py --embedding-backend sentence-transformers --max-per-philosopher 6 --min-score 0.34
```

输出：

```txt
data/generated/local_graph_candidates.json
```

本地算法由两层组成：

1. 关系证据层
   - 哲学家是节点。
   - 核心概念、主题、领域、流派、影响来源、代表作等也是证据节点。
   - 如果两位哲学家连接到相同证据节点，就形成图接近度。
   - 共享证据会被拆成 `structuredEvidenceScore`、`problemAxisScore`、`stanceRelationHint`。
   - `problemAxes` 只包含 `concept`、`field`、非宽泛 `topic`；流派、影响来源、代表作保留在 `sharedEvidence`，不再混入问题轴。

2. 召回层
   - 把角色卡、Wikidata 字段、Wikipedia 思想摘录拼成文本。
   - 计算哲学家之间的语义相似度。
   - embedding 只负责“这对值得送去审稿吗”，不负责证明 affinity、tension 或 influence。

3. 候选来源层
   - `shared_evidence`：共享概念、领域、问题轴或图接近度达到阈值。
   - `stance_opposition`：共享问题轴上出现明确立场对立，可独立生成 `tension` 候选。
   - `relation_prior`：来自 `data/seeds/relation_priors.json` 的 canonical pair，强制进入 LLM review，但不直接写入最终图谱。

当前召回排序分数：

```txt
retrievalScore =
    0.12 * semanticSimilarityScore
  + 0.28 * graphProximityScore
  + 0.30 * structuredEvidenceScore
  + 0.20 * problemAxisScore
  + 0.10 * stanceRelationScore
```

其中 `semanticSimilarityScore` 的角色是召回信号，不是关系证据。这意味着：

- embedding 高，只说明文本可能相近，不说明思想亲缘成立。
- embedding 低，也不能排除影响关系或批判关系。
- `qualityTier` 更看重非语义的 `relationEvidenceScore`，避免“用词相似”把候选误抬成 strong。
- LLM review 必须根据角色卡、问题轴、立场结构、历史影响和哲学常识判断，不能因为 semantic score 高就 accept。

`local_graph_candidates.json` 中每条候选只保留精简字段：

```txt
source, target, qualityTier, retrievalScore, relationEvidenceScore,
semanticSimilarityScore, graphProximityScore, structuredEvidenceScore,
problemAxisScore, problemAxes, stanceRelationHint, sharedEvidence,
suggestedType, candidateSources, candidateNotes
```

当前阈值：

- `minScore = 0.34`
- `maxPerPhilosopher = 6`

这个阈值刻意偏低。它只表示“值得送去审稿”，不表示关系成立。

## Embedding 模型建议

当前脚本默认模型是：

```txt
BAAI/bge-m3
```

理由：

- 支持多语言，适合中英文混合资料。
- 支持长上下文，适合 Wikipedia 思想摘录这类较长文本。
- 可以用 sentence-transformers / transformers / FlagEmbedding 跑本地 dense embedding。
- 对“文档级语义相似度”和检索任务通常比 MiniLM 更稳。

备选模型：

```txt
intfloat/multilingual-e5-large-instruct
```

它也很适合多语言语义匹配，但使用时最好给 query 加 instruction。我们的任务更像“文档-文档相似度 + 候选召回”，`BAAI/bge-m3` 会更直接。

建议策略：

- 开发快速试验：可以临时传 `--embedding-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。
- 正式生成候选：使用 `BAAI/bge-m3`。
- 如果机器内存或速度吃紧，再退回 MiniLM。

## 第七步：LLM 关系审稿

脚本：

```bash
conda run -n philophany python scripts/review_local_graph_candidates.py --model openai/gpt-5.5
```

输出：

```txt
data/generated/reviewed_graph_relations.json
```

LLM 输入包含：

- 当前候选 pair。
- 两位哲学家的已确认角色卡。
- Wikidata 字段。
- Wikipedia 思想摘录。
- 本地候选分数。
- 共享证据。
- 已确认关系，用于避免重复。

LLM 输出：

```json
{
  "source": "kant",
  "target": "sartre",
  "decision": "accept",
  "proposedRelation": {
    "type": "tension",
    "weight": 0.82,
    "reason": "康德把自由系于普遍理性法则，萨特则把自由理解为无预设本质下的自我选择。"
  },
  "confidence": 0.83,
  "llmReason": "这条边能帮助圆桌比较义务法则与存在主义选择。",
  "evidenceBasis": ["coreConcepts", "summary", "philosophical common knowledge"]
}
```

允许的 `decision`：

- `accept`
- `revise`
- `reject`

LLM review 不是最终结论。它只是把本地候选转化为更接近产品图谱的人工审核项。

## 第八步：人工确认关系

`reviewed_graph_relations.json` 中每条 review 默认都是：

```json
"humanDecision": "pending"
```

人工确认采用时，改成：

```json
"humanDecision": "approve"
```

人工审核重点：

- `type` 是否合适。
- `reason` 是否准确、具体、适合圆桌。
- 是否把宽泛词重合误判成关系。
- 是否伪造历史影响。
- 是否存在过度解释。
- 是否和已有关系重复。

## 第九步：生成最终 data.js

最后一步才生成或更新：

```txt
data.js
```

当前 assemble 步骤会把已确认角色卡和已确认关系一起写成 `data.js`：

```txt
reviewed_philosopher_cards.json
+ product_graph_relations.json
        ↓
assemble_data_js.py
        ↓
data.js
```

也就是说，`data.js` 应该是最后构成的产品数据，而不是图谱生成的前置条件。

命令：

```bash
conda run -n philophany python scripts/assemble_data_js.py --cards data/generated/reviewed_philosopher_cards.json --relations data/generated/product_graph_relations.json
conda run -n philophany python scripts/assemble_data_js.py --cards data/generated/reviewed_philosopher_cards.json --relations data/generated/product_graph_relations.json --apply
```

## 质量控制

当前需要三类质量控制：

1. 角色卡质量控制
   - 每位哲学家必须有核心概念、主题、立场、摘要和圆桌语气。
   - 禁止伪造名言、具体引文、章节页码。

2. 关系候选质量控制
   - 明显不相关的 pair 不应该进入审稿池。
   - 例如 `confucius` vs `wittgenstein` 应保持低分，不进入候选池。

3. 人工最终确认
   - LLM 可以提出解释型关系，但不能直接进入 `data.js`。
   - 所有正式边都必须经过人工 approve。

运行测试：

```bash
conda run -n philophany python -m unittest scripts/test_graph_data_io.py scripts/test_generate_philosopher_cards.py scripts/test_assemble_data_js.py scripts/test_generate_local_graph_candidates.py scripts/test_review_local_graph_candidates.py
```

## 当前代码状态

当前代码已经支持零数据起步的核心文件边界：

- `generate_philosopher_cards.py` 从 Wikidata 和 Wikipedia extracts 生成角色卡候选。
- `generate_local_graph_candidates.py` 默认读取 `reviewed_philosopher_cards.json`，不再默认依赖 `data.js`。
- `review_local_graph_candidates.py` 默认读取 `reviewed_philosopher_cards.json`，并用 GPT-5.5 审稿。
- `reviewed_graph_relations.json` 是 LLM 审稿工作台；`product_graph_relations.json` 是人工确认后的产品图谱输入。
- `assemble_data_js.py` 从已确认角色卡、产品图谱关系和每日引文生成最终 `data.js`。
- `BAAI/bge-m3` 已成为正式 sentence-transformers 默认模型。

历史 MVP 的 `data.js` 仍保留为前端可运行的产品数据，也可以通过隐藏 legacy 参数作为兼容输入，但它不再是推荐生成链路的起点。

## 推荐的下一步改进

1. 做一个 review UI
   - 不再手改 `reviewed_philosopher_cards.json` 和 `reviewed_graph_relations.json`。

2. 增加人工 curated 的“必有关系”和“禁止关系”列表
   - 例如明确保留师承关系、明确禁止只有宽泛词重合的 pair。

3. 为每条 LLM review 加 `riskFlag`
   - 例如 `broad_evidence_only`、`historical_claim`、`cross_tradition_interpretive`。

4. 引入更权威的哲学数据源
   - 例如 InPhO、SEP topic graph 或 PhilPapers taxonomy。

5. 评估是否拆出 `critiques`
   - 前提是前端和推荐逻辑准备好支持第四类关系。

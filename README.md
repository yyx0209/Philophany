# Philophany 遇见哲学家

Philophany 是一个哲学家图谱 + 思想圆桌 + 二人辩论 + 苏格拉底产婆术 MVP。它把 13 位哲学家组织成可视化知识图谱，并根据用户的问题召集最多 5 位哲学家进行动态圆桌讨论；也可以让两位哲学家围绕特定张力交锋，或让苏格拉底通过连续追问帮助用户澄清自己的困惑。

当前产品重点：

- 图谱页：D3 力导向哲学家关系图谱，节点大小按加权连接度计算，点击节点查看角色卡和关系。
- 每日哲学灵感：图谱上方按日期轮换展示一条经过人工审核的哲学家引文。
- 圆桌页：用户输入问题后召集阵容，候选哲学家默认全部可见，当前阵容初始为空且最多 5 位。
- 思想圆桌：逐位发言、动态调度、点名追问、多人 `@` 追问、后台讨论状态追踪和“回到原问题”控制。
- 辩论页：用户通过小型选择图谱或下拉框指定两位哲学家，系统推荐 3 个张力角度，再围绕选定角度逐位生成二人辩论。
- 产婆术页：用户提出困惑，苏格拉底一次只追问一个问题，并用 `socraticState` 记录关键词、前提、张力和待追问点。
- 数据管线：从 Wikidata / Wikipedia 起步，经过本地候选召回、LLM 审稿、人工确认，最终 assemble 成 `data.js`。

## 运行

复制环境变量模板：

```bash
cp .env.example .env
```

在 `.env` 中填写：

```txt
DEEPSEEK_API_KEY=...
```

启动本地服务：

```bash
node server.js
```

打开：

```txt
http://127.0.0.1:5173/
```

如果本机没有 `node`，在 Codex 桌面环境中可使用 bundled Node：

```bash
/Applications/Codex.app/Contents/Resources/node server.js
```

## 后端代理与模型

前端不保存 API key。后端通过环境变量调用模型服务，并提供这些接口：

```txt
GET  /api/health
POST /api/analyze-question
POST /api/chat
POST /api/discussion-state
POST /api/next-speaker
POST /api/debate-angles
POST /api/debate-turn
POST /api/socratic-chat
```

当前默认模型分流：

- 问题解析、选人适配分、后台讨论状态、下一位发言调度：DeepSeek 官方 API，默认 `DEEPSEEK_MODEL=deepseek-v4-pro`
- 圆桌发言、追问回应、总结：DeepSeek 官方 API，默认 `DEEPSEEK_ROUNDTABLE_MODEL=deepseek-v4-pro`
- 二人辩论角度生成：DeepSeek 官方 API，默认 `DEEPSEEK_MODEL`
- 二人辩论发言：DeepSeek 官方 API，默认 `DEEPSEEK_ROUNDTABLE_MODEL`
- 产婆术追问：默认复用 `DEEPSEEK_ROUNDTABLE_MODEL`
- 离线 `speechPersona` / `exampleStyle` 生成：DeepSeek 官方 API，读取 `DEEPSEEK_API_KEY`
- 离线图谱生成和关系审稿脚本：默认 `openai/gpt-5.5`，仍读取 `OPENROUTER_API_KEY`

后端未配置 key 或请求失败时，前端会回落到本地演示逻辑。

## 二人辩论

辩论页不是圆桌缩小版，而是把两位哲学家之间的一条张力放大。用户可以在小型图谱上点击选择两位哲学家，也可以用下拉框直接选择。

流程：

- 选择第一位哲学家后，小图谱高亮适合交锋的对手。
- 选择第二位哲学家后，`/api/debate-angles` 根据角色卡、关系图谱和立场差异生成 3 个张力角度。
- 用户选定一个角度后，`/api/debate-turn` 每次只生成一位哲学家的发言。
- 用户可以中途插入追问，支持 `@哲学家` 点名。
- 模型失败时使用本地角度和本地发言 fallback。

## 苏格拉底产婆术

产婆术页不是“让苏格拉底回答问题”，而是让他帮助用户把自己的问题想清楚。

工作方式：

- 用户先输入一个困惑。
- `/api/socratic-chat` 生成苏格拉底的一条短追问。
- 每轮只推进一个问题，优先澄清关键词、判断标准、隐藏前提、例外和内部张力。
- 用户可以点击“生成自我理解”，由苏格拉底把目前对话整理成一段第二人称的阶段性理解。
- 前端维护一份 `socraticState`，在思路板中显示当前理解、关键词、已澄清概念、用户判断、可能前提、内部张力和待追问问题。
- 模型失败时使用本地追问 fallback，避免页面中断。

产婆术 prompt 的边界：

- 不直接替用户给答案。
- 不把对话变成哲学史讲解或心理咨询。
- 不伪造苏格拉底、柏拉图或任何文本中的具体引文。
- 每 4 到 6 轮可以短小结，但小结后仍回到一个新的追问。

## 产品数据

当前网页直接读取：

```txt
data.js
```

但在最新图谱生成方法中，`data.js` 是最终产物，不是生成管线的初始输入。

正式数据来源是：

```txt
data/generated/reviewed_philosopher_cards.json
data/generated/product_graph_relations.json
data/generated/reviewed_daily_quotes.json
        ↓
scripts/assemble_data_js.py
        ↓
data.js
```

### 每日哲学灵感

图谱页的每日引文来自 `dailyQuotes`。每位哲学家可以有 1 到 5 条已审核名句；页面从整个引文池里按日期做稳定的随机式抽样，因此拥有更多名句的哲学家会自然出现得更频繁。

当前流程是：

```txt
Wikiquote / primary text candidates
        ↓
data/generated/wikiquote_quote_candidates.json
        ↓
人工复核 humanDecision
        ↓
data/generated/reviewed_daily_quotes.json
        ↓
scripts/assemble_data_js.py
        ↓
data.js
```

`scripts/generate_daily_quote_candidates.py` 会从 Wikiquote 抽取候选，并跳过明显的 `Misattributed`、`Disputed`、`Unsourced` 和 `Quotes about` 段落。它只生成候选，不自动进入产品。

`scripts/merge_daily_quotes.py` 只放行 `humanDecision: "approve"` 且没有误归、存疑、无来源标记的候选，并限制每位哲学家最多 5 条。已审核过的 `reviewed_daily_quotes.json` 可以直接由 `assemble_data_js.py` 合并进 `data.js`。

每日引文使用 v2 字段：

- `displayQuote`：给用户看的中文表达。
- `sourceText`：Wikiquote 或其他来源文本；它可能是英译或来源页转写，不在前端当“原文”展示。
- `originalQuote`：只有确认拿到原作语言文本时才填写，例如中文古籍原文、希腊文、巴利文、德文或法文原文。
- `originalLanguage`：原作语言代码，例如 `grc`、`pli`、`de`、`fr`、`en`、`zh`。
- `showOriginal`：唯一控制前端是否展示“原文”的开关。当前 Wikiquote 英文来源默认 `false`。

这部分默认不需要 LLM。若未来要批量生成中文译意、短解释或复核说明，使用 `openai/gpt-5.5`，并保留人工审核步骤；模型不能作为原始引文事实来源。

## 思想圆桌方法

完整方法见 [docs/roundtable-method.md](docs/roundtable-method.md)。

### 1. 召集阵容

用户点击“召集圆桌”后，系统先分析问题：

- `themes`：问题主题。
- `implicitConcepts`：隐含哲学概念。
- `tensions`：问题内部张力。
- `discussionNeeds`：这场讨论需要覆盖的问题维度。
- `philosopherFit`：每位哲学家的语义适配分。
- `summary`：对用户问题的自然语言理解。

然后本地算法给哲学家打分：

```txt
relevanceScore =
  语义适配分
  + 主题匹配分
  + 核心概念匹配分
  + 问题维度覆盖分
  + 问题张力匹配分

finalScore =
  relevanceScore
  + 已选阵容差异加成
  + 小的基础加成
```

当前相关性门槛：

```txt
RELEVANCE_GATE_THRESHOLD = 2.2
```

只有超过门槛的候选才进入多样性排序。这样可以避免为了“阵容差异”把不够切题的人硬推上桌。

当前阵容最多 5 位；用户也可以从候选哲学家里手动加入或移出。

### 2. 动态圆桌

圆桌不是一次性生成所有人的发言。每次点击“下一位 / 继续讨论”，系统只生成一位哲学家的发言。

动态调度默认开启：

- `/api/next-speaker` 只决定下一位是谁，不生成发言内容。
- `/api/chat` 再生成这位哲学家的具体发言。

调度器会参考：

- 上一条发言是否点名、反驳或隐性挑战了某位哲学家。
- 图谱关系：`influence`、`tension`、`affinity`。
- 后台 `discussionState` 中的未解决张力和已出现主张。
- 用户原问题和当前追问。
- 沉默补偿和最近发言惩罚。

如果需要回到旧的顺序模式，可在浏览器控制台执行：

```js
localStorage.setItem("philophany.roundScheduler", "sequential")
```

恢复动态调度：

```js
localStorage.removeItem("philophany.roundScheduler")
```

### 3. 发言协议

每条发言都应同时回应用户问题和已经可见的某个观点。哲学家可以自主选择：

- 反驳
- 赞同
- 澄清
- 补充
- 追问
- 建议
- 打断
- 重框
- 翻译成人话

约束：

- 禁止伪造名言、页码、章节或具体引文。
- 提及他人观点时，必须保留对方自己的核心概念和问题语境，不能偷换成发言者自己的概念框架。
- 可以锋利，但不能人身攻击用户。
- 可以拒绝问题，但必须给出更好的问法。
- 可以打断别人，但不能歪曲别人。

### 4. 追问

点名追问：

```txt
@庄子 什么是逍遥
@庄子 对 @孔子 反驳
@庄子@孔子 你们对成功有什么想法
```

规则：

- 第一个可识别的 `@` 默认决定发言者。
- 后续 `@` 默认作为回应对象。
- 如果多个 `@` 连在开头，或问题里出现“你们 / 二位 / 两位 / 各自 / 分别 / 都”等多人信号，会组成逐位回应队列。

非点名追问会进入临时追问进程。它会持续到：

- 调度器返回 `shouldContinue: false`。
- 达到 `DYNAMIC_ROUND_MAX_TURNS = 7`。
- 用户点击“回到原问题”。

点击“回到原问题”会清空当前追问进程；下一次继续讨论时，系统重新围绕原始问题调度下一位哲学家。

### 5. 后台讨论状态

每轮内容生成后，后台会更新 `discussionState`。它不展示在 UI 中，只作为后续 prompt 的主持人笔记：

- `claimsOnTable`
- `unresolvedTensions`
- `unquestionedAssumptions`
- `drift`

它只记录讨论状态，不输出 `nextBestMove`，也不强制规定下一位哲学家怎么说。

## 知识图谱生成方法

完整方法见 [docs/knowledge-graph-method.md](docs/knowledge-graph-method.md)。

核心原则：

- `data.js` 是最终产品数据，不是初始输入。
- 机器负责收集、抽取、初筛和提出候选。
- LLM 负责解释型审稿和补全，但不能直接写入正式图谱。
- 人工确认是进入产品图谱前的最后关口。

### 1. 环境

推荐使用 Conda：

```bash
conda env create -f environment.yml
```

如果环境已存在：

```bash
conda env update -f environment.yml --prune
```

### 2. 零数据起步流程

```txt
data/seeds/philosophers.json
        ↓
Wikidata / Wikipedia
        ↓
wikidata_graph.json
wikipedia_philosophy_extracts.json
        ↓
LLM 生成角色卡候选
        ↓
philosopher_card_candidates.json
        ↓
人工确认
        ↓
reviewed_philosopher_cards.json
        ↓
NetworkX + local embedding 关系初筛
        ↓
local_graph_candidates.json
        ↓
LLM relation review
        ↓
reviewed_graph_relations.json
        ↓
人工确认 approve
        ↓
product_graph_relations.json
        ↓
assemble_data_js.py
        ↓
data.js
```

### 3. 抓取 Wikidata 基础图谱

```bash
conda run -n philophany python scripts/generate_knowledge_graph.py --dry-run
conda run -n philophany python scripts/generate_knowledge_graph.py
```

输出：

```txt
data/generated/wikidata_graph.json
```

内容包括 QID、Wikipedia 链接、生卒时间、职业、领域、流派、受谁影响、代表作和候选关系边。

### 4. 生成角色卡候选

```bash
conda run -n philophany python scripts/generate_philosopher_cards.py --dry-run
conda run -n philophany python scripts/generate_philosopher_cards.py --model openai/gpt-5.5
```

输出：

```txt
data/generated/philosopher_card_candidates.json
```

人工审核后写入：

```txt
data/generated/reviewed_philosopher_cards.json
```

审核重点：

- 核心概念是否准确。
- 传统和时代是否合适。
- 话题是否过宽。
- 立场维度是否符合常识。
- 是否存在伪造引文、页码、章节。

### 5. 本地关系候选

本地候选生成使用 NetworkX + 本地 embedding。默认 sentence-transformers 模型：

```txt
BAAI/bge-m3
```

正式生成：

```bash
conda run -n philophany python scripts/generate_local_graph_candidates.py --cards data/generated/reviewed_philosopher_cards.json --embedding-backend sentence-transformers --max-per-philosopher 6 --min-score 0.34
```

输出：

```txt
data/generated/local_graph_candidates.json
```

本地候选来源分三类：

- `shared_evidence`：共享概念、领域、问题轴或图接近度。
- `stance_opposition`：共享问题轴上的明确立场对立，可独立生成 `tension` 候选。
- `relation_prior`：来自 `data/seeds/relation_priors.json` 的 canonical pair，强制进入审稿池，但不直接进入正式图谱。

当前召回排序：

```txt
retrievalScore =
    0.12 * semanticSimilarityScore
  + 0.28 * graphProximityScore
  + 0.30 * structuredEvidenceScore
  + 0.20 * problemAxisScore
  + 0.10 * stanceRelationScore
```

注意：embedding 相似度只作为召回信号，不能作为关系成立证据。关系是否成立，要交给 LLM review 和人工确认。

### 6. LLM 关系审稿

```bash
conda run -n philophany python scripts/review_local_graph_candidates.py --cards data/generated/reviewed_philosopher_cards.json --dry-run
conda run -n philophany python scripts/review_local_graph_candidates.py --cards data/generated/reviewed_philosopher_cards.json --model openai/gpt-5.5
```

输出：

```txt
data/generated/reviewed_graph_relations.json
```

`reviewed_graph_relations.json` 是关系审稿工作台，不直接作为产品图谱默认输入。人工确认后的稳定产品图谱写入：

```txt
data/generated/product_graph_relations.json
```

允许的 LLM `decision`：

- `accept`
- `revise`
- `reject`

每条 review 默认：

```json
"humanDecision": "pending"
```

人工确认采用时改为：

```json
"humanDecision": "approve"
```

正式关系类型只接受：

- `influence`
- `affinity`
- `tension`

### 7. Assemble 产品数据

Dry-run：

```bash
conda run -n philophany python scripts/assemble_data_js.py --cards data/generated/reviewed_philosopher_cards.json --relations data/generated/product_graph_relations.json
```

写入 `data.js`：

```bash
conda run -n philophany python scripts/assemble_data_js.py --cards data/generated/reviewed_philosopher_cards.json --relations data/generated/product_graph_relations.json --apply
```

## 发言人格和例子风格

`speechPersona` 和 `exampleStyle` 都属于角色卡增强数据，不属于关系图谱。

生成发言人格候选：

```bash
conda run -n philophany python scripts/generate_speech_personas.py --dry-run
conda run -n philophany python scripts/generate_speech_personas.py
```

审核后合并：

```bash
conda run -n philophany python scripts/merge_speech_personas.py --apply
```

生成例子风格候选：

```bash
conda run -n philophany python scripts/generate_example_styles.py
```

审核后合并：

```bash
conda run -n philophany python scripts/merge_example_styles.py --apply
```

合并后重新 assemble：

```bash
conda run -n philophany python scripts/assemble_data_js.py --cards data/generated/reviewed_philosopher_cards.json --relations data/generated/product_graph_relations.json --apply
```

## 测试

运行全量测试：

```bash
conda run -n philophany python -m unittest discover scripts
```

常用分组：

```bash
conda run -n philophany python -m unittest scripts/test_graph_data_io.py scripts/test_generate_philosopher_cards.py scripts/test_assemble_data_js.py scripts/test_generate_local_graph_candidates.py scripts/test_review_local_graph_candidates.py
conda run -n philophany python -m unittest scripts/test_roundtable_selection.py scripts/test_dynamic_roundtable_scheduler.py scripts/test_incremental_intervention_round.py scripts/test_roundtable_lineup_state.py
```

## 文档

- [docs/knowledge-graph-method.md](docs/knowledge-graph-method.md)：零数据起步的图谱生成方法。
- [docs/roundtable-method.md](docs/roundtable-method.md)：思想圆桌的选人、发言、追问和动态调度方法。
- [docs/graph-codex-collaboration-notes.md](docs/graph-codex-collaboration-notes.md)：图谱部分的协作记录和问题复盘。

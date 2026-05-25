# 图谱部分协作复盘：从哲学关系到和 Codex 一起工作

这份文档记录 Philophany 知识图谱这一部分的协作过程。它不是单纯的技术说明，而是一次“如何和 Codex 一起把模糊产品想法推进成可审稿系统”的复盘。

核心结论：

- 哲学图谱不能只靠 embedding 或 LLM 一步生成。
- `data.js` 必须是最终产物，不是起始事实源。
- 本地算法适合做高召回初筛，LLM 适合做解释型审稿，人工 curator 必须保留最终判断权。
- Codex 容易把“看起来合理”当成“已经成立”，所以需要不断追问输入、证据、方向、阈值、反例和合并条件。

## 我们最终形成的图谱流水线

当前相对稳妥的流程是：

```txt
data/seeds/philosophers.json
        ↓
Wikidata / Wikipedia 抓取
        ↓
data/generated/wikidata_graph.json
data/generated/wikipedia_philosophy_extracts.json
        ↓
LLM 生成哲学家角色卡候选
        ↓
data/generated/reviewed_philosopher_cards.json
        ↓
本地关系初筛
        ↓
data/generated/local_graph_candidates.json
        ↓
OpenRouter / GPT-5.5 relation review
        ↓
data/generated/reviewed_graph_relations*.json
        ↓
人工 approve / reject / curator override
        ↓
scripts/assemble_data_js.py
        ↓
data.js
```

这个流程背后的分工是：

- Wikidata / Wikipedia：提供基础事实和思想文本素材。
- 本地算法：负责高召回候选，不负责最终哲学判断。
- Embedding：只作为召回信号，不作为关系成立证据。
- LLM：负责把候选审成 `accept / revise / reject`，并补写理由。
- 人工：负责最终确认，尤其处理 LLM 保守、过度联想或概念误分的情况。

## 发现并修正的问题

### 1. 一开始误把 `data.js` 当成输入

我们一度默认 `data.js` 已经存在，并把它当成后续生成的输入。这和“零数据起步”的目标冲突。

修正后：

- `data.js` 是最终产品数据。
- 起点应是哲学家 seed list、Wikidata、Wikipedia 和审核后的中间文件。
- 角色卡和关系都必须先在 `data/generated/` 中经过候选、审稿、人工确认，再 assemble。

协作经验：如果 Codex 默认引用了一个现成数据文件，要追问“这个文件从哪里来？它是输入还是产物？”

### 2. Wikipedia summary 太像生平简介

最早的 Wikipedia 摘要偏人物生平，不足以支撑哲学概念和关系判断。

修正后：

- 增加 `wikipedia_philosophy_extracts.json`。
- 优先抓取标题包含“思想、哲学、学说、伦理、认识论、形而上、政治哲学”等 section。
- 中文不足时补英文 Wikipedia 的 philosophy / thought / doctrine / ethics / epistemology 等 section。

经验：资料抓取不能只看“页面摘要”，要抓和产品目标相关的 section。

### 3. Embedding 相似度被误当成哲学关系证据

我们发现一个根本缺陷：文本相似不等于思想关系成立。

例子：

- 康德和休谟都谈经验、知识、因果，但他们之间既有影响，也有重要分歧。
- 庄子和维特根斯坦都可能谈语言边界，但思想背景完全不同。
- 高相似度可能只是用词相似，低相似度也不代表没有影响关系。

修正后：

- `semanticSimilarityScore` 只作为 `retrieval_signal_only`。
- 关系证据主要来自 `structuredEvidenceScore`、`problemAxisScore`、`graphProximityScore`、`stanceRelationHint`、`relation_prior`、`wikidata_influenced_by`。
- `local_graph_candidates.json` 明确写出：embedding 不能作为 affinity / tension / influence 成立证据。

经验：当 Codex 给出一个分数公式时，要问“这个分数的哲学含义是什么？它证明了什么，没证明什么？”

### 4. `problemAxes` 混入了乔治·伯克利这类人物名

一版候选里，休谟和康德的 `problemAxes` 出现了“乔治·伯克利”。这暴露出问题轴的定义太宽，把 influence / work / movement 也混进了“问题维度”。

修正后：

- `problemAxes` 只来自 `concept`、`field`、非宽泛 `topic`。
- `movement`、`influence`、`work` 仍可进入 `sharedEvidence`，但不再作为问题轴展示。

经验：字段名字会影响用户理解。`problemAxes` 这种字段必须只放真正的问题轴，不能放所有共享证据。

### 5. 本地算法更擅长找亲缘，不擅长找对立

初版本地算法主要靠共享证据和 embedding，所以更容易找到“相似者”，不容易找到“同一问题上的对立者”。

这导致中国哲学家关系缺失：

- 孔子和庄子应有儒道张力。
- 孔子和王阳明应有儒家传统谱系关系。

修正后：

- 把 `stance_opposition` 升为独立候选来源。
- 增加 `data/seeds/relation_priors.json`，把高质量 curated relation priors 强制送入 LLM review。
- 区分候选来源：`shared_evidence`、`stance_opposition`、`relation_prior`、`wikidata_influenced_by`。

经验：不要期待一个统一相似度算法同时发现亲缘、张力和历史影响。不同关系类型需要不同召回机制。

### 6. `source` / `target` 被字母序反转

我们发现一条严重方向错误：柏拉图 `source`，苏格拉底 `target`，关系却是 `influence`。

根因：

```python
person_ids = sorted(people)
for source, target in combinations(person_ids, 2):
    ...
```

这一步用字母序生成 pair，适合去重，但不适合表示影响方向。`plato < socrates`，所以 `socrates -> plato` 被洗成了 `plato -> socrates`。

修正后：

- `pair_key` 仍可用排序后的 unordered pair 去重。
- `influence` 的方向必须来自显式方向证据。
- `relation_prior` 中的 `influence` 保留 prior 的方向。
- Wikidata `P737 influenced by` 单独作为 directed candidate source。

关键映射：

```txt
Wikidata: Plato influencedBy Socrates
产品关系: socrates -> plato influence
```

经验：`source/target` 对无方向关系只是数据结构，对 `influence` 却是语义本身。要把“去重顺序”和“关系方向”分开。

### 7. LLM 能发现方向问题，但未必能结构化修正

有一次 LLM 在理由里说“方向应该是苏格拉底影响柏拉图”，但输出结构里仍然保留了原来的 top-level `source/target`。

这说明：

- 让 LLM “在自然语言里指出问题”不等于让系统修正了问题。
- 如果 schema 不允许 LLM 输出 corrected source/target，最终 assemble 仍会沿用错误方向。

后续应继续改进：

- `proposedRelation` 可以包含 `source` / `target`。
- assemble 时应优先使用经过校验的 proposed direction。
- 对 `influence` 增加方向回归测试。

经验：LLM 的自然语言理由不能替代结构化数据修正。

### 8. LLM review 一开始过度拒绝

早期 review 里连苏格拉底和柏拉图这样的关系都被拒绝，说明问题不只是数据，也是 prompt 和模型。

调整包括：

- 从较弱模型换到 GPT-5.5。
- 在 prompt 中明确：本地算法是高召回初筛，不是事实来源。
- `affinity` 和 `tension` 不要求直接历史影响，只要同一核心问题上的互补或冲突清楚即可。
- 禁止编造具体引文、页码、章节。
- 明确 weak candidate 需要更高 confidence。

经验：当 LLM 表现奇怪，不要只怪模型，也要检查 prompt 是否把审稿标准写得过窄或过宽。

### 9. LLM 仍可能和 curator 判断不同

例子：

- 我们把 `confucius -> wang-yangming` 作为 `influence` prior。
- GPT-5.5 把它 revise 成 `affinity`，理由是“不是直接师承”。
- 但人工 curator 判断：孔子作为儒家经典传统源头，对王阳明心学有传统谱系中的深层影响，应保留为 `influence`。

最终处理：

- 对这条做 `curatorOverride`。
- `proposedRelation.type` 改回 `influence`。
- 所有 accept / revise approve，reject 保持 reject。
- assemble 到正式 `data.js`。

经验：LLM 适合作为审稿助手，不是哲学 curator。尤其是“传统影响”和“直接师承”的边界，需要人工定规则。

### 10. 图谱 UI 的视觉语义也需要审稿

我们后来发现，图谱视觉本身也有语义问题。

原先：

- 点大小只表示是否在圆桌阵容里。
- 背景有类似水印的 “Philophany / influence · tension · affinity”。
- 用户很容易误以为点大小代表图谱重要性，但实际不是。

修正后：

- 点大小 = 加权连接强度。
- 圆桌阵容 = 外圈高亮。
- 当前选中 = 描边发光。
- 去掉图谱背景水印。

经验：可视化不是装饰。每个视觉编码都应该有明确语义，否则会误导用户理解图谱。

## 当前关系类型的语义

目前正式保留三类：

- `influence`：历史影响、师承、思想谱系。应有方向。
- `affinity`：思想亲缘、互补关系、共享问题结构。通常无方向。
- `tension`：同一核心问题上的张力、冲突或可辩论分歧。通常无方向。

一个尚未完全解决的问题是：数据结构里所有关系都有 `source/target`，但 `affinity` 和 `tension` 本质上应是无方向边。下一步可以考虑增加：

```json
{
  "directed": true
}
```

或在前端中只对 `influence` 显示箭头，把其他关系明确视为无方向。

## Codex 在这类任务中容易犯的错误

### 1. 过早把临时数据当成正式数据

如果不提醒，Codex 容易把已有的 `data.js`、旧 JSON 或一轮 LLM 输出当作可信输入。

应对方式：

- 追问“这个文件从哪里来？”
- 明确哪些是 seed、candidate、reviewed、approved、final。
- 要求每一步写 metadata。

### 2. 用技术相似性替代专业判断

Codex 很容易认为“embedding 相似 + shared topics”就等于哲学关系成立。

应对方式：

- 要求区分 retrieval signal 和 evidence。
- 要求列出反例。
- 要求说明某个字段的哲学含义。

### 3. 把 prompt 当成万能修复

方向错误、重复 pair、非法 type、人工 approve gate 这些问题，不能只靠 prompt。

应对方式：

- 能用 schema / validation / tests 解决的，不交给 LLM 自由发挥。
- LLM 负责判断，程序负责约束。

### 4. 忽略方向语义

Codex 初期把 `source/target` 当成普通 pair，没有意识到 `influence` 的方向就是关系本身。

应对方式：

- 对所有 directed relation 写方向测试。
- 用具体例子检验：`socrates -> plato`，`hume -> kant`。
- 明确 Wikidata `influencedBy` 的反向映射。

### 5. 给出看似完整但不可审计的结果

如果只让 Codex “生成图谱”，它可能直接给一份关系列表，看起来顺眼，但无法追踪来源。

应对方式：

- 要求输出 candidate source。
- 要求保留 `localEvidence`、`candidateNotes`、`llmReason`、`humanDecision`。
- 只允许 approve 后 assemble。

### 6. 对跨传统关系过度自信

比如柏拉图和庄子、黑格尔和庄子、孔子和萨特，这些关系作为圆桌张力有启发性，但不应和休谟到康德这种历史影响放在同一层理解。

应对方式：

- 区分 historical influence、tradition influence、problem affinity、comparative tension。
- 如果暂时只有三类关系，就在 reason 里写清楚这是比较性张力，不是历史关系。

## 和 Codex 协作的有效做法

### 1. 不断要求 Codex 解释“输入是什么”

非常有用的问题：

- “这一步的输入是什么？”
- “这个字段从哪里来？”
- “source card 和 target card 为什么结构不一样？”
- “给 LLM 判断的 input data 是什么，给一个例子。”

这类问题能及时暴露管线里的隐含假设。

### 2. 要求 Codex 给反例测试

我们加入过类似反例：

```txt
confucius vs wittgenstein 应该 score < 0.45
buddha vs wittgenstein 不应进入候选池
zhuangzi vs hume 不应只因宽泛主题被连上
```

反例比正例更能防止算法膨胀。

### 3. 把“哲学判断”和“工程判断”分开

工程上可以：

- 降阈值提高召回。
- 用 BGE-M3 做 embedding。
- 用 NetworkX 计算图接近度。
- 用 GPT-5.5 review。

但哲学上仍要问：

- 这条边是历史影响，还是问题亲缘？
- 是直接对立，还是比较性张力？
- 是否只是因为共享大词？
- 是否对圆桌讨论有实际价值？

### 4. 让 Codex 先承认不确定性，再做自动化

我们没有直接把 LLM review 写入 `data.js`，而是设计：

```txt
local candidates
  -> LLM review
  -> humanDecision: pending
  -> approve / reject
  -> assemble
```

这种设计让自动化变得可控。

### 5. 人工 override 是必要功能，不是失败

`confucius -> wang-yangming` 是一个好例子。LLM 的判断有道理，但不完全符合产品里的关系定义。人工 override 让系统保留 curator 的哲学立场。

协作原则：

- LLM 可以建议。
- Codex 可以实现流程。
- 人工定义关系语义和最终边界。

### 6. 让 Codex 用可见产物收尾

每次关键修改后，都应该要求：

- 重新生成文件。
- 跑测试。
- 检查关键 JSON 条目。
- 用浏览器或 loader 验证页面。

仅仅说“应该好了”不够。

## 目前仍值得后续改进的地方

### 1. 增加更细的关系类型

目前三类关系够 MVP，但语义偏粗。后续可以考虑：

- `direct_influence`
- `tradition_influence`
- `problem_affinity`
- `comparative_tension`
- `critique`

这样能避免把“孔子到王阳明”和“休谟到康德”都塞进同一个 `influence` 而不加区分。

### 2. 为无方向关系增加 `directed: false`

当前 `affinity` 和 `tension` 仍有 `source/target`，这只是数据结构需要，不是语义方向。最好显式标记：

```json
{
  "source": "confucius",
  "target": "zhuangzi",
  "type": "tension",
  "directed": false
}
```

### 3. 把 curator override 做成正式工作台

现在 override 是通过编辑 reviewed JSON 完成的。后续可以做一个简单审核界面：

- 查看候选。
- 看本地证据和 LLM reason。
- accept / revise / reject。
- 手动改 type、weight、reason。
- 一键 assemble。

### 4. 为每条关系保留证据层级

可考虑增加：

```json
{
  "evidenceBasis": "wikidata_influenced_by | curated_prior | llm_review | curator_override",
  "confidence": 0.9,
  "reviewNotes": "..."
}
```

这样用户点击图谱边时，不只看到一句 reason，还能知道这条关系来自哪里。

### 5. 区分“产品圆桌有用”和“哲学史严格成立”

Philophany 是产品，不是哲学百科。某些跨传统关系虽然不是历史关系，但对圆桌辩论有价值。

建议以后明确两层：

- `historicalLayer`：更严格的影响、学派、文本谱系。
- `dialogueLayer`：为圆桌讨论服务的比较、张力、互补。

## 可以保留下来的协作模板

以后遇到类似任务，可以这样和 Codex 协作：

1. 先问目标：这是百科事实图谱，还是圆桌讨论图谱？
2. 要求 Codex 写出数据流，而不是直接生成最终文件。
3. 要求每一步标明输入、输出、是否可自动合并。
4. 让本地算法只做候选，不做最终判断。
5. 要求 LLM 输出结构化 review，而不是散文解释。
6. 加反例测试，尤其是明显不相关 pair。
7. 对方向性关系写专门测试。
8. 让人工 approve 成为最终 gate。
9. 每次改规则后重新生成候选、重新 review、重新 assemble。
10. 页面视觉也要问“这个视觉编码是什么意思？”

## 最重要的一句话

和 Codex 协作做哲学图谱时，最重要的不是让它“一次性生成正确答案”，而是把它放进一个可追问、可审计、可回滚、可人工修正的流程里。

Codex 最适合做的是：

- 快速搭管线。
- 写脚本和测试。
- 解释数据结构。
- 暴露隐含假设。
- 反复跑生成和验证。

人最应该守住的是：

- 哲学语义。
- 关系类型边界。
- 哪些证据算数。
- 哪些边值得进入产品。
- 用户看到图谱时会如何理解它。

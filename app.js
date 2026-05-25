(function () {
  const { philosophers, relations, dimensions, topics } = window.PHILOSOPHANY_DATA;
  const byId = Object.fromEntries(philosophers.map((person) => [person.id, person]));
  let graphSimulation = null;
  let discussionStateRefreshToken = 0;
  const DEFAULT_ANALYSIS_MODEL = "deepseek/deepseek-v4-pro";
  const DEFAULT_ROUNDTABLE_MODEL = "deepseek/deepseek-v4-pro";
  const DEFAULT_ROUND_SCHEDULER_MODE = "llm";
  const ROUND_SCHEDULER_STORAGE_KEY = "philophany.roundScheduler";
  const DYNAMIC_ROUND_MAX_TURNS = 7;
  const MAX_LINEUP_SIZE = 5;
  const RELEVANCE_GATE_THRESHOLD = 2.2;
  const GRAPH_NODE_MIN_RADIUS = 22;
  const GRAPH_NODE_MAX_RADIUS = 42;
  const speakerAliasOverrides = {
    buddha: ["佛陀", "释迦", "释迦牟尼"],
  };

  const state = {
    question: "努力真的有意义吗，还是我们只是在说服自己？",
    lineup: [],
    selectedId: "nietzsche",
    conversation: [],
    isGenerating: false,
    isSummoningLineup: false,
    analysis: null,
    recommendations: {},
    discussionState: createEmptyDiscussionState(),
    openingTurnIndex: 0,
    interventionRound: null,
    dynamicRound: createEmptyDynamicRound(),
    currentView: "graph",
    provider: {
      model: DEFAULT_ANALYSIS_MODEL,
      roundtableModel: DEFAULT_ROUNDTABLE_MODEL,
      backendReady: false,
      checked: false,
    },
  };

  const topicLexicon = {
    成功: ["成功", "事业", "成就", "上岸", "赚钱", "名声", "认可", "竞争", "优秀"],
    自由: ["自由", "选择", "束缚", "独立", "限制", "责任"],
    幸福: ["幸福", "快乐", "满足", "生活", "安宁"],
    道德: ["道德", "应该", "善", "义务", "原则", "良知", "内疚"],
    欲望: ["欲望", "想要", "贪", "执着", "焦虑", "比较"],
    痛苦: ["痛苦", "失败", "焦虑", "恐惧", "孤独", "失去"],
    死亡: ["死亡", "有限", "虚无", "告别", "生命"],
    意义: ["意义", "价值", "人生", "虚无", "目标", "方向"],
    真理: ["真理", "真实", "知识", "确定", "怀疑", "事实"],
    行动: ["行动", "选择", "实践", "改变", "拖延", "决定", "做"],
  };

  const examples = [
    "努力真的有意义吗，还是我们只是在说服自己？",
    "我们能真正理解另一个人吗？",
    "如果死后什么都没有，现在做的事还有意义吗？",
    "爱一个人，到底是爱他这个人，还是爱我需要他？",
    "我们记住的过去，是真实的过去吗？",
    "一个人可以因为'大局'而被牺牲吗？",
  ];

  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function createEmptyDiscussionState() {
    return {
      claimsOnTable: [],
      unresolvedTensions: [],
      unquestionedAssumptions: [],
      drift: {
        level: "none",
        note: "",
      },
    };
  }

  function createEmptyDynamicRound() {
    return {
      turnCount: 0,
      closed: false,
      lastSchedulerReason: "",
    };
  }

  function getRoundSchedulerMode() {
    try {
      const saved = localStorage.getItem(ROUND_SCHEDULER_STORAGE_KEY);
      return saved === "sequential" ? "sequential" : DEFAULT_ROUND_SCHEDULER_MODE;
    } catch {
      return DEFAULT_ROUND_SCHEDULER_MODE;
    }
  }

  function useDynamicScheduler() {
    return getRoundSchedulerMode() === "llm" && getProviderReady();
  }

  function normalizeDiscussionState(value) {
    const stateValue = value && typeof value === "object" ? value : {};
    const allowedStatuses = new Set(["unanswered", "challenged", "clarified", "repeated"]);
    const allowedDriftLevels = new Set(["none", "mild", "serious"]);

    const claimsOnTable = Array.isArray(stateValue.claimsOnTable)
      ? stateValue.claimsOnTable
          .map((claim) => {
            if (!claim || typeof claim !== "object") return null;
            const speaker = String(claim.speaker || "").trim();
            if (!state.lineup.includes(speaker)) return null;
            const status = String(claim.status || "").trim();
            return {
              claim: String(claim.claim || "").trim().slice(0, 220),
              speaker,
              status: allowedStatuses.has(status) ? status : "unanswered",
              needsFollowUp: Boolean(claim.needsFollowUp),
            };
          })
          .filter((claim) => claim && claim.claim)
          .slice(0, 8)
      : [];

    const drift = stateValue.drift && typeof stateValue.drift === "object" ? stateValue.drift : {};
    const driftLevel = String(drift.level || "").trim();

    return {
      claimsOnTable,
      unresolvedTensions: normalizeTextList(stateValue.unresolvedTensions, 5, 180),
      unquestionedAssumptions: normalizeTextList(stateValue.unquestionedAssumptions, 5, 180),
      drift: {
        level: allowedDriftLevels.has(driftLevel) ? driftLevel : "none",
        note: String(drift.note || "").trim().slice(0, 180),
      },
    };
  }

  function normalizeTextList(value, maxItems, maxLength) {
    return Array.isArray(value)
      ? value
          .map((item) => String(item || "").trim().slice(0, maxLength))
          .filter(Boolean)
          .slice(0, maxItems)
      : [];
  }

  function detectTopics(question) {
    const normalized = question.trim().toLowerCase();
    const found = Object.entries(topicLexicon)
      .map(([topic, words]) => {
        const hits = words.filter((word) => normalized.includes(word.toLowerCase())).length;
        return { topic, hits };
      })
      .filter((item) => item.hits > 0)
      .sort((a, b) => b.hits - a.hits)
      .map((item) => item.topic);

    if (found.length > 0) {
      return found.slice(0, 4);
    }

    return ["意义", "行动"];
  }

  function stanceDistance(a, b) {
    const total = dimensions.reduce((sum, dimension) => {
      return sum + Math.abs(a.stance[dimension.id] - b.stance[dimension.id]);
    }, 0);
    return total / dimensions.length;
  }

  function relationBetween(aId, bId) {
    return relations.find((relation) => {
      return (
        (relation.source === aId && relation.target === bId) ||
        (relation.source === bId && relation.target === aId)
      );
    });
  }

  function scorePhilosopher(person, analysisContext, selected) {
    const personTerms = [
      ...person.topics,
      ...person.coreConcepts,
      person.tradition,
      person.summary,
      person.voice,
    ];
    const themeMatches = findMatches(analysisContext.themes, person.topics);
    const conceptMatches = uniqueStrings([
      ...findMatches(analysisContext.implicitConcepts, person.coreConcepts),
      ...person.coreConcepts.filter((concept) => state.question.includes(concept)),
    ]);
    const discussionNeedMatches = analysisContext.discussionNeeds
      .map((need) => ({
        label: need.label,
        matched: findMatches(need.needs, personTerms),
      }))
      .filter((need) => need.matched.length > 0);
    const tensionTerms = analysisContext.tensions.flatMap((tension) => splitTensionTerms(tension));
    const tensionMatches = findMatches(tensionTerms, personTerms);
    const fit = analysisContext.philosopherFit[person.id] || { fit: 0, reason: "" };

    const topicScore = themeMatches.length * 2.2;
    const conceptScore = conceptMatches.length * 2.5;
    const discussionNeedScore = discussionNeedMatches.reduce((sum, need) => sum + 1.35 + Math.min(need.matched.length, 3) * 0.25, 0);
    const tensionScore = Math.min(tensionMatches.length, 4) * 0.55;
    const fitScore = fit.fit * 5.2;
    const relevanceScore = fitScore + topicScore + conceptScore + discussionNeedScore + tensionScore;
    const selectedBonus =
      selected.length === 0
        ? 0
        : selected.reduce((sum, chosen) => {
            const relation = relationBetween(person.id, chosen.id);
            const relationBonus = relation
              ? relation.type === "tension"
                ? 1.8 * relation.weight
                : 0.9 * relation.weight
              : 0;
            return sum + clamp(stanceDistance(person, chosen), 0, 1.2) + relationBonus;
          }, 0) / selected.length;

    const specificity = person.topics.length > 0 ? 0.25 : 0;
    const finalScore = relevanceScore + selectedBonus + specificity;
    const reasons = buildRecommendationReasons({
      person,
      selected,
      themeMatches,
      conceptMatches,
      discussionNeedMatches,
      tensionMatches,
      fit,
    });

    return {
      score: finalScore,
      finalScore: relevanceScore + selectedBonus + specificity,
      relevanceScore,
      passesRelevanceGate: relevanceScore >= RELEVANCE_GATE_THRESHOLD,
      reasons,
      breakdown: {
        relevanceScore,
        fitScore,
        topicScore,
        conceptScore,
        discussionNeedScore,
        tensionScore,
        selectedBonus,
      },
    };
  }

  function buildRecommendationReasons({ person, selected, themeMatches, conceptMatches, discussionNeedMatches, tensionMatches, fit }) {
    const reasons = [];
    if (fit?.fit > 0) reasons.push(`语义适配 ${(fit.fit * 100).toFixed(0)}%：${fit.reason || "适合从其思想角度切入"}`);
    if (themeMatches.length > 0) reasons.push(`匹配主题：${themeMatches.slice(0, 3).join("、")}`);
    if (conceptMatches.length > 0) reasons.push(`隐含概念：${conceptMatches.slice(0, 3).join("、")}`);
    if (discussionNeedMatches.length > 0) {
      const coveredNeeds = uniqueStrings(discussionNeedMatches.flatMap((need) => need.matched)).slice(0, 4);
      reasons.push(`覆盖问题维度：${coveredNeeds.join("、")}`);
    }
    if (tensionMatches.length > 0) reasons.push(`触及张力：${tensionMatches.slice(0, 3).join("、")}`);

    const relationHint = selected
      .map((chosen) => ({ chosen, relation: relationBetween(person.id, chosen.id) }))
      .find((item) => item.relation);
    if (relationHint) {
      reasons.push(`与${relationHint.chosen.name}有${relationLabel(relationHint.relation.type)}`);
    }

    if (reasons.length === 0) {
      reasons.push(`补充视角：${person.topics.slice(0, 2).join("、")}`);
    }
    return reasons.slice(0, 4);
  }

  function uniqueStrings(values) {
    return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))];
  }

  function findMatches(needles, haystack) {
    const candidates = uniqueStrings(haystack);
    return uniqueStrings(needles).filter((needle) => candidates.some((candidate) => termsMatch(needle, candidate)));
  }

  function termsMatch(a, b) {
    const left = String(a || "").trim().toLowerCase();
    const right = String(b || "").trim().toLowerCase();
    if (!left || !right) return false;
    if (left === right) return true;
    if (left.length >= 2 && right.includes(left)) return true;
    if (right.length >= 2 && left.includes(right)) return true;
    return false;
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function speakerNameCandidates(person) {
    const normalizedName = String(person?.name || "").trim();
    if (!normalizedName) return [];
    const name = normalizedName;
    const parts = name.split(/[·・.\s]+/).map((part) => part.trim()).filter((part) => part.length >= 2);
    return uniqueStrings([normalizedName, ...parts, ...(speakerAliasOverrides[person?.id] || [])]);
  }

  function splitTensionTerms(tension) {
    return String(tension || "")
      .split(/vs|VS|与|和|、|\/|，|,|：|:|\s+/)
      .map((part) => part.trim())
      .filter((part) => part.length >= 2);
  }

  function recommendationReason(person, questionTopics) {
    const matchedTopics = person.topics.filter((topic) => questionTopics.includes(topic));
    const relationHints = state.lineup
      .map((chosenId) => relationBetween(person.id, chosenId))
      .filter(Boolean)
      .slice(0, 1);
    const topicText =
      matchedTopics.length > 0
        ? `切中${matchedTopics.join("、")}`
        : `能从${person.topics.slice(0, 2).join("、")}切入`;
    const relationText =
      relationHints.length > 0 ? `；与${byId[relationHints[0].source === person.id ? relationHints[0].target : relationHints[0].source].name}有${relationLabel(relationHints[0].type)}` : "";
    return `${topicText}${relationText}`;
  }

  function relationLabel(type) {
    if (type === "influence") return "影响关系";
    if (type === "tension") return "思想张力";
    return "相近之处";
  }

  function syncQuestionFromInput() {
    state.question = document.querySelector("#questionInput").value.trim() || "我该如何理解自己的困惑？";
  }

  async function recommendLineup() {
    syncQuestionFromInput();
    const button = document.querySelector("#recommendButton");
    state.isSummoningLineup = true;
    state.lineup = [];
    state.recommendations = {};
    state.analysis = null;
    state.discussionState = createEmptyDiscussionState();
    state.openingTurnIndex = 0;
    state.interventionRound = null;
    state.dynamicRound = createEmptyDynamicRound();
    state.conversation = [];
    renderAll();
    button.disabled = true;
    button.textContent = "解析中...";

    try {
      const analysis = await analyzeQuestion(state.question);
      const analysisContext = createAnalysisContext(analysis);
      const selected = [];
      const recommendationEntries = [];
      const targetSize = MAX_LINEUP_SIZE;

      while (selected.length < targetSize) {
        const candidates = philosophers
          .filter((person) => !selected.some((chosen) => chosen.id === person.id))
          .map((person) => ({
            person,
            result: scorePhilosopher(person, analysisContext, selected),
          }));
        const candidatePool = candidates.filter((entry) => entry.result.passesRelevanceGate);
        const rankingPool = candidatePool.length > 0 ? candidatePool : candidates;
        rankingPool.sort((a, b) => {
          const aScore = candidatePool.length > 0 ? a.result.score : a.result.relevanceScore;
          const bScore = candidatePool.length > 0 ? b.result.score : b.result.relevanceScore;
          return bScore - aScore;
        });

        const winner = rankingPool[0];
        selected.push(winner.person);
        recommendationEntries.push(winner);
      }

      state.lineup = selected.map((person) => person.id);
      state.selectedId = state.lineup[0];
      state.analysis = analysis;
      state.recommendations = Object.fromEntries(
        recommendationEntries.map((entry) => [
          entry.person.id,
          {
            score: entry.result.score,
            reasons: entry.result.reasons,
            breakdown: entry.result.breakdown,
          },
        ])
      );
      state.discussionState = createEmptyDiscussionState();
      state.openingTurnIndex = 0;
      state.interventionRound = null;
      state.dynamicRound = createEmptyDynamicRound();
      state.conversation = [
        systemMessage(
          `已围绕「${state.question}」召集：${selected.map((person) => person.name).join("、")}。${analysis.summary ? `问题理解：${analysis.summary}` : `主题判断：${analysisContext.themes.join("、")}。`}`
        ),
      ];
    } finally {
      state.isSummoningLineup = false;
      button.disabled = false;
      button.innerHTML = `<span aria-hidden="true">⌁</span>召集圆桌`;
      renderAll();
    }
  }

  async function analyzeQuestion(question) {
    const fallback = createLocalAnalysis(question);
    if (!getProviderReady()) {
      return fallback;
    }

    try {
      const response = await fetch("/api/analyze-question", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question,
          model: state.provider.model,
          referer: window.location.origin,
          knownTopics: topics,
          knownConcepts: uniqueStrings(philosophers.flatMap((person) => person.coreConcepts)),
          philosophers: philosophers.map((person) => ({
            id: person.id,
            name: person.name,
            tradition: person.tradition,
            coreConcepts: person.coreConcepts,
            topics: person.topics,
            summary: person.summary,
          })),
        }),
      });

      if (!response.ok) {
        let details = "";
        try {
          const errorBody = await response.json();
          details = errorBody?.error || JSON.stringify(errorBody);
        } catch {
          details = await response.text();
        }
        throw new Error(details || response.statusText);
      }

      const payload = await response.json();
      return normalizeAnalysis(payload.analysis, "model");
    } catch (error) {
      return {
        ...fallback,
        summary: `${fallback.summary} 模型解析失败，已使用本地关键词回退。`,
        error: error.message,
      };
    }
  }

  function createLocalAnalysis(question) {
    const localThemes = detectTopics(question);
    return normalizeAnalysis(
      {
        themes: localThemes,
        implicitConcepts: [],
        tensions: [],
        philosopherFit: {},
        discussionNeeds: localThemes.slice(0, 4).map((theme) => ({
          label: `${theme}问题维度`,
          needs: [theme],
          reason: `本地关键词命中「${theme}」。`,
        })),
        summary: `本地识别出主题：${localThemes.join("、")}。`,
      },
      "local"
    );
  }

  function normalizeAnalysis(analysis, source) {
    const normalized = analysis || {};
    return {
      source,
      themes: uniqueStrings(normalized.themes).slice(0, 6),
      implicitConcepts: uniqueStrings(normalized.implicitConcepts).slice(0, 10),
      tensions: uniqueStrings(normalized.tensions).slice(0, 6),
      philosopherFit: normalizePhilosopherFit(normalized.philosopherFit),
      discussionNeeds: Array.isArray(normalized.discussionNeeds || normalized.slots)
        ? (normalized.discussionNeeds || normalized.slots)
            .map((need) => ({
              label: String(need.label || need.role || "").trim(),
              needs: uniqueStrings(need.needs || []),
              reason: String(need.reason || "").trim(),
            }))
            .filter((need) => need.label || need.needs.length > 0)
            .slice(0, 6)
        : [],
      summary: String(normalized.summary || "").trim(),
      error: normalized.error,
    };
  }

  function createAnalysisContext(analysis) {
    const fallbackThemes = detectTopics(state.question);
    return {
      themes: uniqueStrings([...fallbackThemes, ...analysis.themes]),
      implicitConcepts: uniqueStrings(analysis.implicitConcepts),
      tensions: uniqueStrings(analysis.tensions),
      philosopherFit: analysis.philosopherFit || {},
      discussionNeeds: analysis.discussionNeeds,
    };
  }

  function normalizePhilosopherFit(value) {
    if (!value || typeof value !== "object") return {};

    return Object.fromEntries(
      Object.entries(value)
        .map(([id, item]) => {
          const fit = Number(item?.fit ?? item?.score ?? 0);
          return [
            id,
            {
              fit: clamp(Number.isFinite(fit) ? fit : 0, 0, 1),
              reason: String(item?.reason || "").trim(),
            },
          ];
        })
        .filter(([id]) => byId[id])
    );
  }

  function systemMessage(text, role = "系统") {
    return {
      id: `system-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      speakerId: "system",
      speakerName: "圆桌记录",
      role,
      text,
    };
  }

  function updateSystemMessage(id, text, role = "系统") {
    const message = state.conversation.find((item) => item.id === id);
    if (!message) return;
    message.text = text;
    message.role = role;
    renderConversation();
  }

  function getProviderReady() {
    syncProviderFromInputs();
    return (
      state.provider.backendReady &&
      state.provider.model.trim().length > 0 &&
      state.provider.roundtableModel.trim().length > 0
    );
  }

  function syncProviderFromInputs() {
    const modelInput = document.querySelector("#modelInput");
    if (!modelInput) {
      state.provider.model = state.provider.model || DEFAULT_ANALYSIS_MODEL;
      state.provider.roundtableModel = state.provider.roundtableModel || DEFAULT_ROUNDTABLE_MODEL;
      return;
    }
    state.provider.model = modelInput.value.trim() || DEFAULT_ANALYSIS_MODEL;
    state.provider.roundtableModel = state.provider.roundtableModel || DEFAULT_ROUNDTABLE_MODEL;
  }

  function saveSettings() {
    syncProviderFromInputs();
    localStorage.setItem("philophany.model", state.provider.model);
    renderProviderStatus("设置已保存。");
    checkProviderStatus();
  }

  function loadSettings() {
    localStorage.removeItem("philophany.model");
    state.provider.model = DEFAULT_ANALYSIS_MODEL;
    state.provider.roundtableModel = DEFAULT_ROUNDTABLE_MODEL;
    const modelInput = document.querySelector("#modelInput");
    if (modelInput) modelInput.value = state.provider.model;
    renderProviderStatus();
  }

  function renderProviderStatus(prefix = "") {
    const node = document.querySelector("#providerStatus");
    if (!node) return;
    const isReady = getProviderReady();
    node.classList.toggle("is-ready", isReady);
    const message = !state.provider.checked
      ? "正在检查后端代理。"
      : isReady
        ? "后端代理已连接模型服务。"
        : "后端代理未配置 API key，将使用本地演示生成。";
    node.textContent = prefix ? `${prefix} ${message}` : message;
  }

  async function checkProviderStatus() {
    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const payload = await response.json();
      state.provider.backendReady = Boolean(payload.openRouterConfigured);
      state.provider.checked = true;
      state.provider.model = payload.defaultAnalysisModel || payload.defaultModel || DEFAULT_ANALYSIS_MODEL;
      state.provider.roundtableModel = payload.defaultRoundtableModel || DEFAULT_ROUNDTABLE_MODEL;
      const modelInput = document.querySelector("#modelInput");
      if (modelInput) modelInput.value = state.provider.model;
      renderProviderStatus();
    } catch {
      state.provider.backendReady = false;
      state.provider.checked = true;
      renderProviderStatus("后端不可用。");
    }
  }

  function philosopherMessage(person, text, role) {
    return {
      id: `${person.id}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      speakerId: person.id,
      speakerName: person.name,
      role,
      text,
    };
  }

  async function generateOpeningRound() {
    syncQuestionFromInput();
    if (state.lineup.length === 0) {
      await recommendLineup();
      if (state.lineup.length === 0) return;
    }

    const nextSpeaker = nextOpeningSpeaker();
    if (!nextSpeaker) {
      state.conversation.push(systemMessage("第一轮已经完成。你可以继续追问、总结分歧，或重新召集圆桌。"));
      renderAll();
      return;
    }

    addOpeningStartMessageIfNeeded();
    if (getProviderReady()) {
      await generateWithModel({
        action: "opening_step",
        currentSpeakerId: nextSpeaker.id,
        loadingText: `正在生成下一位发言：${nextSpeaker.name}。`,
        streamLike: true,
        fallback: () => generateLocalOpeningStep(nextSpeaker),
        afterMessages: () => advanceOpeningTurn(nextSpeaker.id),
      });
      return;
    }

    generateLocalOpeningStep(nextSpeaker);
  }

  async function generateNextRoundStep() {
    if (useDynamicScheduler()) {
      await generateDynamicRoundStep();
      return;
    }

    if (state.interventionRound && nextInterventionSpeaker()) {
      await generateInterventionRoundStep();
      return;
    }

    state.interventionRound = null;
    await generateOpeningRound();
  }

  async function generateDynamicRoundStep() {
    syncQuestionFromInput();
    if (state.lineup.length === 0) {
      await recommendLineup();
      if (state.lineup.length === 0) return;
    }

    const activeIntervention = state.interventionRound?.dynamic ? state.interventionRound : null;
    const action = activeIntervention ? "intervention_step" : "opening_step";
    const intervention = activeIntervention?.text || "";

    if (activeIntervention?.turnCount >= DYNAMIC_ROUND_MAX_TURNS) {
      state.interventionRound = null;
      state.conversation.push(systemMessage("这轮追问已经充分展开。你可以继续追问、总结分歧，或让圆桌转向新的问题。"));
      renderAll();
      return;
    }

    let decision;
    const schedulerLoading = systemMessage("下一位...", "调度中");
    state.conversation.push(schedulerLoading);
    renderConversation();
    try {
      decision = await callNextSpeakerScheduler(action, intervention);
    } catch (error) {
      state.conversation = state.conversation.filter((message) => message.id !== schedulerLoading.id);
      state.conversation.push(systemMessage(`LLM 调度失败，已切回原顺序。错误：${error.message}`));
      if (activeIntervention) {
        state.interventionRound = createInterventionRound(activeIntervention.text, state.lineup.map((id) => byId[id]));
        await generateInterventionRoundStep();
      } else {
        await generateOpeningRound();
      }
      return;
    }

    if (!decision.shouldContinue || !decision.speakerId) {
      if (activeIntervention) {
        state.interventionRound = null;
        updateSystemMessage(
          schedulerLoading.id,
          decision.reason || "这轮追问暂告一段落。你可以继续追问、总结分歧，或让圆桌自然继续。",
          "圆桌暂停"
        );
      } else {
        state.dynamicRound.closed = true;
        state.dynamicRound.lastSchedulerReason = decision.reason || "";
        updateSystemMessage(
          schedulerLoading.id,
          decision.reason || "这一段讨论暂告一段落。你可以继续追问、总结分歧，或再次点击让圆桌寻找新的切入点。",
          "圆桌暂停"
        );
      }
      renderAll();
      return;
    }

    const nextSpeaker = byId[decision.speakerId];
    if (!nextSpeaker) {
      updateSystemMessage(schedulerLoading.id, "LLM 调度返回了无效发言者，已暂停本轮。", "圆桌暂停");
      renderAll();
      return;
    }

    updateSystemMessage(schedulerLoading.id, `${nextSpeaker.name}正在发言...`, "生成中");
    await generateWithModel({
      action,
      intervention,
      currentSpeakerId: nextSpeaker.id,
      loadingText: `${nextSpeaker.name}正在发言...`,
      loadingMessageId: schedulerLoading.id,
      streamLike: true,
      fallback: () => {
        if (activeIntervention) {
          generateLocalInterventionStep(intervention, nextSpeaker);
        } else {
          generateLocalOpeningStep(nextSpeaker);
        }
      },
      afterMessages: () => advanceDynamicTurn(nextSpeaker.id, Boolean(activeIntervention), decision.reason),
    });
  }

  function advanceDynamicTurn(speakerId, isIntervention, schedulerReason = "") {
    if (isIntervention && state.interventionRound?.dynamic) {
      state.interventionRound.turnCount += 1;
      state.interventionRound.lastSpeakerId = speakerId;
      state.interventionRound.lastSchedulerReason = schedulerReason;
      if (state.interventionRound.turnCount >= DYNAMIC_ROUND_MAX_TURNS) {
        state.interventionRound = null;
      }
      return;
    }

    state.dynamicRound.turnCount += 1;
    state.dynamicRound.closed = false;
    state.dynamicRound.lastSpeakerId = speakerId;
    state.dynamicRound.lastSchedulerReason = schedulerReason;
  }

  function nextOpeningSpeaker() {
    return byId[state.lineup[state.openingTurnIndex]] || null;
  }

  function addOpeningStartMessageIfNeeded() {
    if (state.openingTurnIndex !== 0) return;
    const alreadyStarted = state.conversation.some((message) => message.role === "第一轮开始");
    if (alreadyStarted) return;
    state.conversation.push(systemMessage(`第一轮开始：每次只请一位哲学家回应「${state.question}」。`));
  }

  function advanceOpeningTurn(speakerId) {
    const currentSpeakerId = state.lineup[state.openingTurnIndex];
    if (currentSpeakerId === speakerId) {
      state.openingTurnIndex += 1;
      return;
    }

    const speakerIndex = state.lineup.indexOf(speakerId);
    if (speakerIndex >= 0) {
      state.openingTurnIndex = Math.max(state.openingTurnIndex, speakerIndex + 1);
    }
  }

  function generateLocalOpeningStep(person) {
    const role = state.openingTurnIndex === 0 ? "初始立场" : "回应前文";
    state.conversation.push(philosopherMessage(person, person.opening, role));
    advanceOpeningTurn(person.id);
    renderAll();
  }

  function createInterventionRound(text, participants) {
    const targetedSpeakers = findTargetedSpeakersForText(text, participants);
    const orderedParticipants = targetedSpeakers.length > 0 ? targetedSpeakers : orderParticipantsAfterLastSpeaker(participants);
    return {
      text,
      speakerIds: orderedParticipants.map((person) => person.id),
      turnIndex: 0,
    };
  }

  function createDynamicInterventionRound(text, participants) {
    const targetedSpeakers = findTargetedSpeakersForText(text, participants);
    if (targetedSpeakers.length > 0) return createInterventionRound(text, participants);
    return {
      text,
      speakerIds: [],
      turnIndex: 0,
      turnCount: 0,
      dynamic: true,
      closed: false,
      lastSpeakerId: "",
      lastSchedulerReason: "",
    };
  }

  function findTargetedSpeakersForText(text, participants) {
    const atMentioned = extractAtMentionedSpeakers(text, participants);
    if (atMentioned.length > 0) {
      return shouldTreatAtMentionsAsSpeakerQueue(text, atMentioned) ? atMentioned : [atMentioned[0]];
    }

    const targeted = findTargetedSpeakerForText(text, participants);
    return targeted ? [targeted] : [];
  }

  function findTargetedSpeakerForText(text, participants) {
    const atMentioned = extractAtMentionedSpeakers(text, participants);
    if (atMentioned.length > 0) return atMentioned[0];

    const directlyAddressed = participants.filter((person) => {
      return speakerNameCandidates(person).some((alias) => {
        const escaped = escapeRegExp(alias);
        const patterns = directAddressPatterns(escaped);
        return patterns.some((pattern) => new RegExp(pattern).test(text));
      });
    });

    if (directlyAddressed.length === 1) return directlyAddressed[0];

    const mentioned = participants.filter((person) => speakerNameCandidates(person).some((alias) => text.includes(alias)));
    return mentioned.length === 1 ? mentioned[0] : null;
  }

  function shouldTreatAtMentionsAsSpeakerQueue(text, atMentioned) {
    if (atMentioned.length < 2) return false;
    if (/你们|二位|两位|各自|分别|都|一起|轮流/.test(text)) return true;
    return startsWithAtMentionSpeakerCluster(text);
  }

  function startsWithAtMentionSpeakerCluster(text) {
    let rest = String(text || "").trimStart();
    let count = 0;
    while (rest.startsWith("@")) {
      const match = rest.match(/^@([^@\s，,。；;：:！!？?、]+)/);
      if (!match) break;
      count += 1;
      rest = rest.slice(match[0].length).trimStart();
    }
    return count >= 2;
  }

  function extractAtMentionedSpeakers(text, participants) {
    const mentionedIds = [...String(text || "").matchAll(/@([^@\s，,。；;：:！!？?、]+)/g)]
      .map((match) => findPersonByMention(match[1], participants))
      .filter(Boolean)
      .map((person) => person.id);
    return uniqueStrings([...mentionedIds]).map((id) => byId[id]).filter(Boolean);
  }

  function findPersonByMention(rawMention, participants) {
    const mention = String(rawMention || "").trim();
    if (!mention) return null;
    const matches = participants
      .map((person) => {
        const alias = speakerNameCandidates(person)
          .sort((a, b) => b.length - a.length)
          .find((candidate) => mention === candidate || mention.startsWith(candidate));
        return alias ? { person, aliasLength: alias.length } : null;
      })
      .filter(Boolean)
      .sort((a, b) => b.aliasLength - a.aliasLength);
    return matches[0]?.person || null;
  }

  function directAddressPatterns(escaped) {
    return [
      `让${escaped}`,
      `请${escaped}`,
      `问${escaped}`,
      `追问${escaped}`,
      `针对${escaped}`,
      `${escaped}(先生|老师|教授)?[，,：:！!？?\\s]+你`,
      `${escaped}(先生|老师|教授)?[，,：:！!？?\\s]*(有什么要说|怎么看|怎么回应|解释|回答)`,
      `${escaped}怎么看`,
      `${escaped}怎么回应`,
      `${escaped}解释`,
      `${escaped}回答`,
    ];
  }

  function orderParticipantsAfterLastSpeaker(participants) {
    const lastMessage = [...state.conversation].reverse().find((message) => state.lineup.includes(message.speakerId));
    const lastIndex = participants.findIndex((person) => person.id === lastMessage?.speakerId);
    if (lastIndex < 0) return participants;
    return [...participants.slice(lastIndex + 1), ...participants.slice(0, lastIndex + 1)];
  }

  function nextInterventionSpeaker() {
    if (!state.interventionRound) return null;
    return byId[state.interventionRound.speakerIds[state.interventionRound.turnIndex]] || null;
  }

  function advanceInterventionTurn(speakerId) {
    if (!state.interventionRound) return;
    const currentSpeakerId = state.interventionRound.speakerIds[state.interventionRound.turnIndex];
    if (currentSpeakerId === speakerId) {
      state.interventionRound.turnIndex += 1;
    } else {
      const speakerIndex = state.interventionRound.speakerIds.indexOf(speakerId);
      if (speakerIndex >= 0) {
        state.interventionRound.turnIndex = Math.max(state.interventionRound.turnIndex, speakerIndex + 1);
      }
    }

    if (state.interventionRound.turnIndex >= state.interventionRound.speakerIds.length) {
      state.interventionRound = null;
    }
  }

  async function generateInterventionRoundStep() {
    const nextSpeaker = nextInterventionSpeaker();
    if (!state.interventionRound || !nextSpeaker) {
      state.interventionRound = null;
      renderAll();
      return;
    }

    if (getProviderReady()) {
      await generateWithModel({
        action: "intervention_step",
        intervention: state.interventionRound.text,
        currentSpeakerId: nextSpeaker.id,
        loadingText: `正在生成追问回应：${nextSpeaker.name}。`,
        streamLike: true,
        fallback: () => generateLocalInterventionStep(state.interventionRound?.text || "", nextSpeaker),
        afterMessages: () => advanceInterventionTurn(nextSpeaker.id),
      });
      return;
    }

    generateLocalInterventionStep(state.interventionRound.text, nextSpeaker);
  }

  async function summarizeDebate() {
    syncQuestionFromInput();
    if (state.lineup.length === 0) {
      recommendLineup();
    }

    if (getProviderReady()) {
      await generateWithModel({
        action: "summary",
        loadingText: "正在总结这一轮圆桌的核心分歧。",
        fallback: summarizeLocalDebate,
      });
      return;
    }

    summarizeLocalDebate();
  }

  function summarizeLocalDebate() {
    const participants = state.lineup.map((id) => byId[id]);
    const pairs = [];
    participants.forEach((a, index) => {
      participants.slice(index + 1).forEach((b) => {
        const relation = relationBetween(a.id, b.id);
        if (relation) pairs.push({ a, b, relation });
      });
    });

    const axes = participants
      .map((person) => {
        const strongest = dimensions
          .map((dimension) => ({
            label: person.stance[dimension.id] >= 0 ? dimension.right : dimension.left,
            value: Math.abs(person.stance[dimension.id]),
          }))
          .sort((a, b) => b.value - a.value)[0];
        return `${person.name}偏向「${strongest.label}」`;
      })
      .join("；");

    const relationText =
      pairs.length > 0
        ? pairs
            .slice(0, 3)
            .map(({ a, b, relation }) => `${a.name}与${b.name}之间有${relationLabel(relation.type)}：${relation.reason}`)
            .join(" ")
        : "这组阵容的分歧主要来自立场维度，而不是已有关系线。";

    state.conversation.push(
      systemMessage(`分歧摘要：${axes}。${relationText} 对你来说，最关键的不是马上选边，而是辨认你被哪一种理由打动。`)
    );
    renderConversation();
  }

  async function respondToIntervention(input) {
    syncQuestionFromInput();
    const text = input.trim();
    if (!text) return;
    if (state.lineup.length === 0) {
      await recommendLineup();
      if (state.lineup.length === 0) return;
    }

    const participants = state.lineup.map((id) => byId[id]);
    state.conversation.push({
      id: `user-${Date.now()}`,
      speakerId: "user",
      speakerName: "你",
      role: "追问",
      text,
    });
    if (useDynamicScheduler()) {
      state.interventionRound = createDynamicInterventionRound(text, participants);
    } else {
      state.interventionRound = createInterventionRound(text, participants);
    }

    document.querySelector("#interventionInput").value = "";
    if (state.interventionRound?.dynamic) {
      await generateDynamicRoundStep();
      return;
    }
    await generateInterventionRoundStep();
  }

  function generateLocalInterventionStep(text, target) {
    const participants = state.lineup.map((id) => byId[id]);
    const atMentioned = extractAtMentionedSpeakers(text, participants);
    const mentionedOpponent = atMentioned.find((person) => person.id !== target.id);
    const textMentionedOpponent = participants.find(
      (person) => person.id !== target.id && speakerNameCandidates(person).some((alias) => text.includes(alias)),
    );
    const opponent = mentionedOpponent || textMentionedOpponent || findBestOpponent(target, participants);

    if (text.includes("反驳") && opponent) {
      state.conversation.push(philosopherMessage(target, rebuttalText(target, opponent), `回应 ${opponent.name}`));
    } else if (text.includes("解释")) {
      state.conversation.push(philosopherMessage(target, explainText(target), "概念解释"));
    } else if (text.includes("总结")) {
      summarizeLocalDebate();
      return;
    } else if (target.id === "wang-yangming" && (text.includes("王阳明") || text.includes("知行合一") || text.includes("良知"))) {
      state.conversation.push(philosopherMessage(target, explainText(target), "实践回应"));
    } else {
      state.conversation.push(philosopherMessage(target, followUpText(target), "追问回应"));
    }

    advanceInterventionTurn(target.id);
    renderAll();
  }

  async function revealMessageText(message, fullText, options = {}) {
    const chunkSize = options.chunkSize || 3;
    const delay = options.delay || 14;
    message.text = "";
    renderConversation();

    for (let index = 0; index < fullText.length; index += chunkSize) {
      message.text = fullText.slice(0, index + chunkSize);
      renderConversation();
      await wait(delay);
    }

    message.text = fullText;
    renderConversation();
  }

  async function generateWithModel({
    action,
    intervention = "",
    currentSpeakerId = "",
    loadingText,
    loadingMessageId = "",
    streamLike = false,
    fallback,
    afterMessages = () => {},
  }) {
    let loading = loadingMessageId ? state.conversation.find((message) => message.id === loadingMessageId) : null;
    if (loading) {
      loading.text = loadingText;
      loading.role = "生成中";
    } else {
      loading = systemMessage(loadingText, "生成中");
      state.conversation.push(loading);
    }
    renderConversation();

    try {
      const messages = await callRoundtableProxy(action, intervention, currentSpeakerId);
      state.conversation = state.conversation.filter((message) => message.id !== loading.id);
      for (const message of messages) {
        if (message.speakerId === "system") {
          state.conversation.push(systemMessage(message.text));
          continue;
        }
        const person = byId[message.speakerId] || byId[state.lineup[0]];
        const nextMessage = philosopherMessage(person, streamLike ? "" : message.text, message.role || person.tradition);
        state.conversation.push(nextMessage);
        if (streamLike) {
          await revealMessageText(nextMessage, message.text);
        }
      }
      afterMessages(messages);
      renderAll();
      scheduleDiscussionStateRefresh();
    } catch (error) {
      state.conversation = state.conversation.filter((message) => message.id !== loading.id);
      state.conversation.push(systemMessage(`后端代理调用失败，已切回本地演示生成。错误：${userFacingError(error)}`));
      fallback();
      renderProviderStatus("请求失败。");
    }
  }

  async function callNextSpeakerScheduler(action, intervention = "") {
    const participants = state.lineup.map((id) => byId[id]);
    const context = {
      action,
      question: state.question,
      intervention,
      model: state.provider.model,
      schedulerMode: getRoundSchedulerMode(),
      dynamicRound: state.interventionRound?.dynamic ? state.interventionRound : state.dynamicRound,
      referer: window.location.origin,
      participants: participants.map((person) => ({
        id: person.id,
        name: person.name,
        tradition: person.tradition,
        coreConcepts: person.coreConcepts,
        topics: person.topics,
        stance: person.stance,
        voice: person.voice,
        speechPersona: person.speechPersona,
        exampleStyle: person.exampleStyle,
        summary: person.summary,
      })),
      relations: relations
        .filter((relation) => state.lineup.includes(relation.source) && state.lineup.includes(relation.target))
        .map((relation) => ({
          source: relation.source,
          target: relation.target,
          sourceName: byId[relation.source].name,
          targetName: byId[relation.target].name,
          type: relation.type,
          reason: relation.reason,
        })),
      recentConversation: state.conversation.slice(-12).map((message) => ({
        speakerId: message.speakerId,
        speaker: message.speakerName,
        role: message.role,
        text: message.text,
      })),
      discussionState: state.discussionState,
    };

    const response = await fetch("/api/next-speaker", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(context),
    });

    if (!response.ok) {
      let details = "";
      try {
        const errorBody = await response.json();
        details = errorBody?.error || JSON.stringify(errorBody);
      } catch {
        details = await response.text();
      }
      throw new Error(`${response.status} ${details || response.statusText}`);
    }

    const payload = await response.json();
    const decision = payload.decision || {};
    return {
      shouldContinue: decision.shouldContinue !== false,
      speakerId: state.lineup.includes(decision.speakerId) ? decision.speakerId : "",
      reason: String(decision.reason || "").trim(),
      advanceStyle: String(decision.advanceStyle || "").trim(),
    };
  }

  async function callRoundtableProxy(action, intervention, currentSpeakerId = "") {
    const participants = state.lineup.map((id) => byId[id]);
    const context = {
      action,
      question: state.question,
      intervention,
      currentSpeakerId,
      roundtableModel: state.provider.roundtableModel,
      referer: window.location.origin,
      participants: participants.map((person) => ({
        id: person.id,
        name: person.name,
        tradition: person.tradition,
        coreConcepts: person.coreConcepts,
        topics: person.topics,
        stance: person.stance,
        voice: person.voice,
        speechPersona: person.speechPersona,
        exampleStyle: person.exampleStyle,
        summary: person.summary,
      })),
      relations: relations
        .filter((relation) => state.lineup.includes(relation.source) && state.lineup.includes(relation.target))
        .map((relation) => ({
          source: relation.source,
          target: relation.target,
          sourceName: byId[relation.source].name,
          targetName: byId[relation.target].name,
          type: relation.type,
          reason: relation.reason,
        })),
      recentConversation: state.conversation.slice(-10).map((message) => ({
        speakerId: message.speakerId,
        speaker: message.speakerName,
        role: message.role,
        text: message.text,
      })),
      discussionState: state.discussionState,
    };

    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(context),
    });

    if (!response.ok) {
      let details = "";
      try {
        const errorBody = await response.json();
        details = errorBody?.error || JSON.stringify(errorBody);
      } catch {
        details = await response.text();
      }
      throw new Error(`${response.status} ${details || response.statusText}`);
    }

    const payload = await response.json();
    if (!Array.isArray(payload.messages) || payload.messages.length === 0) {
      throw new Error("后端返回格式缺少 messages。");
    }

    return payload.messages
      .map((message) => ({
        speakerId: state.lineup.includes(message.speakerId) ? message.speakerId : "system",
        role: String(message.role || "回应").slice(0, 16),
        text: String(message.text || "").trim(),
      }))
      .filter((message) => message.text);
  }

  function scheduleDiscussionStateRefresh() {
    const token = ++discussionStateRefreshToken;
    refreshDiscussionState()
      .then((nextState) => {
        if (token !== discussionStateRefreshToken || !nextState) return;
        state.discussionState = nextState;
      })
      .catch(() => {
        if (token !== discussionStateRefreshToken) return;
        state.discussionState = normalizeDiscussionState(state.discussionState);
      });
  }

  async function refreshDiscussionState() {
    if (!getProviderReady() || !state.lineup.length || !state.question.trim()) return null;

    const participants = state.lineup.map((id) => byId[id]);
    const response = await fetch("/api/discussion-state", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        question: state.question,
        intervention: "",
        model: state.provider.model,
        referer: window.location.origin,
        participants: participants.map((person) => ({
          id: person.id,
          name: person.name,
          tradition: person.tradition,
          coreConcepts: person.coreConcepts,
          topics: person.topics,
          stance: person.stance,
          voice: person.voice,
          speechPersona: person.speechPersona,
          exampleStyle: person.exampleStyle,
          summary: person.summary,
        })),
        relations: relations
          .filter((relation) => state.lineup.includes(relation.source) && state.lineup.includes(relation.target))
          .map((relation) => ({
            source: relation.source,
            target: relation.target,
            sourceName: byId[relation.source].name,
            targetName: byId[relation.target].name,
            type: relation.type,
            reason: relation.reason,
          })),
        recentConversation: state.conversation.slice(-12).map((message) => ({
          speakerId: message.speakerId,
          speaker: message.speakerName,
          role: message.role,
          text: message.text,
        })),
        discussionState: state.discussionState,
      }),
    });

    if (!response.ok) return null;

    const payload = await response.json();
    return normalizeDiscussionState(payload.discussionState);
  }

  function findBestOpponent(target, participants) {
    return participants
      .filter((person) => person.id !== target.id)
      .map((person) => ({
        person,
        relation: relationBetween(target.id, person.id),
        distance: stanceDistance(target, person),
      }))
      .sort((a, b) => {
        const aScore = a.distance + (a.relation?.type === "tension" ? a.relation.weight : 0);
        const bScore = b.distance + (b.relation?.type === "tension" ? b.relation.weight : 0);
        return bScore - aScore;
      })[0]?.person;
  }

  function rebuttalText(target, opponent) {
    const relation = relationBetween(target.id, opponent.id);
    const hook = target.questionHooks[0];
    const relationText = relation ? `你和${opponent.name}的分歧在于：${relation.reason}` : `你和${opponent.name}的立场距离很大。`;
    return `${relationText} ${target.name}会把问题推回这里：${hook} 对「${state.question}」而言，不能只接受${opponent.name}的答案，还要检查它是否遮蔽了${target.coreConcepts.slice(0, 2).join("、")}。`;
  }

  function explainText(person) {
    return `${person.coreConcepts[0]}不是一个装饰性概念。放到「${state.question}」里，它要求你看清：${person.questionHooks[0]} ${person.summary}`;
  }

  function followUpText(person) {
    return `${person.name}会继续追问：${person.questionHooks[1] || person.questionHooks[0]} 如果这个问题暂时没有最终答案，下一步也应当符合${person.coreConcepts.slice(0, 2).join("、")}。`;
  }

  function returnToMainQuestion() {
    if (!state.interventionRound) return;
    state.interventionRound = null;
    renderAll();
  }

  function addToLineup(id) {
    if (state.lineup.includes(id)) return;
    if (state.lineup.length >= MAX_LINEUP_SIZE) return;
    state.lineup = [...state.lineup, id];
    state.selectedId = id;
    renderAll();
  }

  function removeFromLineup(id) {
    state.lineup = state.lineup.filter((item) => item !== id);
    if (state.selectedId === id) {
      state.selectedId = state.lineup[0] || philosophers[0].id;
    }
    renderAll();
  }

  function selectPerson(id) {
    state.selectedId = id;
    renderDetail();
    if (state.currentView === "graph") renderGraph();
    openProfileModal();
  }

  function openProfileModal() {
    const modal = document.querySelector("#profileModal");
    if (!modal) return;
    modal.hidden = false;
  }

  function closeProfileModal() {
    const modal = document.querySelector("#profileModal");
    if (!modal) return;
    modal.hidden = true;
  }

  function switchView(view) {
    state.currentView = view;
    document.querySelectorAll(".tab").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.view === view);
    });
    document.querySelectorAll(".view").forEach((section) => {
      section.classList.toggle("is-active", section.id === `${view}View`);
    });
    if (view === "graph") renderGraph();
  }

  function renderAll() {
    renderTopicChips();
    renderLineup();
    renderPool();
    renderConversation();
    renderDetail();
    renderGraphInspector();
    renderOpeningControl();
    if (state.currentView === "graph") renderGraph();
  }

  function renderOpeningControl() {
    renderReturnToMainControl();
    const button = document.querySelector("#startDebateButton");
    if (!button) return;

    if (state.isGenerating) {
      button.disabled = true;
      button.title = "正在等待下一位发言";
      button.innerHTML = `<span aria-hidden="true">…</span>正在等待下一位`;
      return;
    }

    if (useDynamicScheduler()) {
      button.disabled = state.lineup.length === 0;
      if (state.interventionRound?.dynamic) {
        button.title = "让 LLM 调度下一位回应追问";
        button.innerHTML = `<span aria-hidden="true">▶</span>继续回应`;
        return;
      }
      const label = state.dynamicRound.turnCount === 0 ? "开始发言" : "继续讨论";
      button.title = state.dynamicRound.turnCount === 0 ? "让 LLM 调度第一位发言" : "让 LLM 调度下一位发言";
      button.innerHTML = `<span aria-hidden="true">▶</span>${label}`;
      return;
    }

    const nextIntervention = nextInterventionSpeaker();
    if (nextIntervention) {
      button.disabled = false;
      button.title = `下一位回应追问：${nextIntervention.name}`;
      button.innerHTML = `<span aria-hidden="true">▶</span>下一位回应`;
      return;
    }

    const nextSpeaker = nextOpeningSpeaker();
    if (!nextSpeaker) {
      button.disabled = state.lineup.length > 0;
      button.title = state.lineup.length > 0 ? "第一轮已完成" : "先召集圆桌";
      button.innerHTML = `<span aria-hidden="true">✓</span>第一轮完成`;
      return;
    }

    button.disabled = false;
    button.title = `下一位发言：${nextSpeaker.name}`;
    const label = state.openingTurnIndex === 0 ? "开始发言" : "下一位发言";
    button.innerHTML = `<span aria-hidden="true">▶</span>${label}`;
  }

  function renderReturnToMainControl() {
    const button = document.querySelector("#returnToMainButton");
    if (!button) return;
    button.hidden = !state.interventionRound;
    if (!state.interventionRound) return;
    button.disabled = state.isGenerating;
    button.title = state.isGenerating ? "当前回应生成中" : "结束当前追问，回到原问题";
  }

  function renderTopicChips() {
    const container = document.querySelector("#topicChips");
    container.innerHTML = examples
      .map((example) => `<button class="chip" type="button" data-example="${escapeHtml(example)}">${escapeHtml(example)}</button>`)
      .join("");
    container.querySelectorAll(".chip").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelector("#questionInput").value = button.dataset.example;
        recommendLineup();
      });
    });
  }

  function renderLineup() {
    const container = document.querySelector("#lineupList");
    if (state.isSummoningLineup) {
      container.innerHTML = `<div class="empty-state">正在召集哲学家阵容。</div>`;
      document.querySelector("#roundtableMeta").textContent = "正在召集哲学家阵容";
      return;
    }

    if (state.lineup.length === 0) {
      container.innerHTML = `<div class="empty-state">还没有召集哲学家。点击“召集圆桌”后，这里会出现最多五位哲学家。</div>`;
      document.querySelector("#roundtableMeta").textContent = "等待召集圆桌";
      return;
    }

    container.innerHTML = `${renderAnalysisCard()}${state.lineup
      .map((id) => {
        const person = byId[id];
        const recommendation = state.recommendations[id];
        const reasons = recommendation?.reasons || [recommendationReason(person, state.analysis?.themes || detectTopics(state.question))];
        return `
          <article class="lineup-item">
            <div class="lineup-top">
              <button class="mini-button ${state.selectedId === id ? "is-active" : ""}" type="button" data-select="${id}">${person.name}</button>
              <span class="score-pill">${recommendation ? recommendation.score.toFixed(1) : person.tradition}</span>
            </div>
            <p class="lineup-why">${escapeHtml(person.tradition)}</p>
            <ul class="reason-list">
              ${reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}
            </ul>
            <div class="lineup-controls">
              <button class="mini-button" type="button" data-remove="${id}" title="移出圆桌">移出</button>
              <button class="mini-button" type="button" data-select="${id}" title="查看人物卡">查看</button>
            </div>
          </article>
        `;
      })
      .join("")}`;

    container.querySelectorAll("[data-remove]").forEach((button) => {
      button.addEventListener("click", () => removeFromLineup(button.dataset.remove));
    });
    container.querySelectorAll("[data-select]").forEach((button) => {
      button.addEventListener("click", () => selectPerson(button.dataset.select));
    });

    document.querySelector("#roundtableMeta").textContent = `${state.lineup.length} 位哲学家正在讨论`;
  }

  function renderAnalysisCard() {
    const analysis = state.analysis;
    if (!analysis) return "";

    const themes = analysis.themes.length > 0 ? analysis.themes : detectTopics(state.question);
    const concepts = analysis.implicitConcepts.slice(0, 5);
    const tensions = analysis.tensions.slice(0, 3);
    const fitCount = Object.keys(analysis.philosopherFit || {}).length;
    return `
      <article class="analysis-card">
        <div class="analysis-top">
          <strong>问题理解</strong>
          <span>${analysis.source === "model" ? `模型解析 · ${fitCount} 个适配分` : "本地回退"}</span>
        </div>
        ${analysis.summary ? `<p>${escapeHtml(analysis.summary)}</p>` : ""}
        <div class="tag-row tag-row--compact">
          ${themes.map((theme) => `<span class="tag">${escapeHtml(theme)}</span>`).join("")}
          ${concepts.map((concept) => `<span class="tag tag--concept">${escapeHtml(concept)}</span>`).join("")}
        </div>
        ${tensions.length > 0 ? `<p class="small-copy">张力：${escapeHtml(tensions.join("；"))}</p>` : ""}
      </article>
    `;
  }

  function renderPool() {
    const container = document.querySelector("#philosopherPool");
    const pool = philosophers.filter((person) => !state.lineup.includes(person.id));
    const isLineupFull = state.lineup.length >= MAX_LINEUP_SIZE;
    container.innerHTML = pool
      .map((person) => {
        return `
          <article class="pool-item">
            <div class="pool-top">
              <span class="pool-name">${person.name}</span>
              <button class="icon-button" type="button" data-add="${person.id}" title="${isLineupFull ? "当前阵容最多五位" : "加入圆桌"}" aria-label="加入${person.name}" ${isLineupFull ? "disabled" : ""}>＋</button>
            </div>
            <p class="pool-meta">${person.tradition} · ${person.topics.slice(0, 3).join(" / ")}</p>
          </article>
        `;
      })
      .join("");
    container.querySelectorAll("[data-add]").forEach((button) => {
      button.addEventListener("click", () => addToLineup(button.dataset.add));
    });
  }

  function renderConversation() {
    const container = document.querySelector("#conversation");
    if (state.conversation.length === 0) {
      container.innerHTML = `<div class="empty-state">圆桌会在这里开始。</div>`;
      return;
    }
    container.innerHTML = state.conversation
      .map((message) => {
        const person = byId[message.speakerId];
        const avatarClass = person?.color || "teal";
        const initials = message.speakerId === "system" ? "记" : message.speakerId === "user" ? "你" : message.speakerName.slice(0, 1);
        return `
          <article class="message">
            <div class="avatar ${avatarClass}">${initials}</div>
            <div>
              <div class="message-head">
                <span class="message-name">${escapeHtml(message.speakerName)}</span>
                <span class="message-role">${escapeHtml(message.role)}</span>
              </div>
              <p>${escapeHtml(message.text)}</p>
            </div>
          </article>
        `;
      })
      .join("");
    container.scrollTop = container.scrollHeight;
  }

  function renderDetail() {
    const person = byId[state.selectedId] || byId[state.lineup[0]] || philosophers[0];
    const relationsForPerson = relations
      .filter((relation) => relation.source === person.id || relation.target === person.id)
      .slice(0, 5);
    document.querySelector("#detailCard").innerHTML = `
      <article class="profile-card">
        <div class="profile-title">
          <div>
            <h2>${person.name}</h2>
            <p>${person.era} · ${person.tradition}</p>
          </div>
          <span class="type-pill">${person.coreConcepts[0]}</span>
        </div>
        <p>${person.summary}</p>
        <div class="tag-row">
          ${person.coreConcepts.map((concept) => `<span class="tag">${concept}</span>`).join("")}
        </div>
        <h3>立场维度</h3>
        <div class="dimension-list">
          ${dimensions.map((dimension) => renderDimension(person, dimension)).join("")}
        </div>
        <h3 style="margin-top:16px">图谱关系</h3>
        ${relationsForPerson
          .map((relation) => {
            const other = byId[relation.source === person.id ? relation.target : relation.source];
            return `<div class="relation-card"><strong>${other.name}</strong> · ${relationLabel(relation.type)}<p class="small-copy">${relation.reason}</p></div>`;
          })
          .join("")}
      </article>
    `;
  }

  function renderDimension(person, dimension) {
    const value = person.stance[dimension.id];
    const width = Math.abs(value) * 50;
    const left = value < 0 ? 50 - width : 50;
    return `
      <div>
        <div class="dimension-label">
          <span>${dimension.left}</span>
          <span>${dimension.right}</span>
        </div>
        <div class="dimension-track">
          <span class="dimension-fill" style="left:${left}%; width:${width}%"></span>
        </div>
      </div>
    `;
  }

  function renderGraph() {
    const svg = document.querySelector("#knowledgeGraph");
    if (!svg) return;
    renderGraphInspector();

    if (graphSimulation) {
      graphSimulation.stop();
      graphSimulation = null;
    }

    if (window.d3?.forceSimulation) {
      renderD3Graph(svg);
      return;
    }

    renderStaticGraph(svg);
  }

  function getGraphData() {
    const strengthById = graphConnectionStrengths();
    const maxStrength = Math.max(...Object.values(strengthById), 0);
    const nodes = philosophers.map((person) => ({
      ...person,
      connectionStrength: strengthById[person.id] || 0,
      radius: graphRadiusForStrength(strengthById[person.id] || 0, maxStrength),
      inLineup: state.lineup.includes(person.id),
    }));
    const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));
    const links = relations
      .filter((relation) => nodeMap[relation.source] && nodeMap[relation.target])
      .map((relation) => ({
        ...relation,
        sourceName: nodeMap[relation.source].name,
        targetName: nodeMap[relation.target].name,
      }));
    return { nodes, links };
  }

  function graphConnectionStrengths() {
    const strengths = Object.fromEntries(philosophers.map((person) => [person.id, 0]));
    relations.forEach((relation) => {
      if (!(relation.source in strengths) || !(relation.target in strengths)) return;
      const weight = clamp(Number(relation.weight) || 0, 0, 1);
      strengths[relation.source] += weight;
      strengths[relation.target] += weight;
    });
    return strengths;
  }

  function graphRadiusForStrength(strength, maxStrength) {
    if (maxStrength <= 0) return 28;
    const normalized = clamp(strength / maxStrength, 0, 1);
    return Math.round(GRAPH_NODE_MIN_RADIUS + Math.sqrt(normalized) * (GRAPH_NODE_MAX_RADIUS - GRAPH_NODE_MIN_RADIUS));
  }

  function renderD3Graph(svgElement) {
    const d3 = window.d3;
    const stage = svgElement.parentElement;
    const rect = stage.getBoundingClientRect();
    const width = Math.max(760, Math.round(rect.width || 960));
    const height = 650;
    const selected = state.selectedId;
    const { nodes, links } = getGraphData();

    svgElement.setAttribute("viewBox", `0 0 ${width} ${height}`);
    const svg = d3.select(svgElement);
    svg.selectAll("*").remove();

    const defs = svg.append("defs");
    defs
      .append("filter")
      .attr("id", "nodeGlow")
      .append("feDropShadow")
      .attr("dx", 0)
      .attr("dy", 0)
      .attr("stdDeviation", 5)
      .attr("flood-color", "#8ee6d8")
      .attr("flood-opacity", 0.45);
    defs
      .append("marker")
      .attr("id", "graphArrow")
      .attr("markerWidth", 10)
      .attr("markerHeight", 10)
      .attr("refX", 9)
      .attr("refY", 3)
      .attr("orient", "auto")
      .attr("markerUnits", "strokeWidth")
      .append("path")
      .attr("d", "M0,0 L0,6 L7,3 z")
      .attr("fill", "#2f75b8");

    const viewport = svg.append("g").attr("class", "graph-viewport");

    const link = viewport
      .append("g")
      .attr("class", "graph-links")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("class", (d) => `graph-link ${d.type} ${isRelatedToSelected(d, selected) ? "is-related" : ""}`)
      .attr("stroke-width", (d) => 1.2 + d.weight * 2.1)
      .attr("marker-end", (d) => (d.type === "influence" ? "url(#graphArrow)" : null));

    const node = viewport
      .append("g")
      .attr("class", "graph-nodes")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .attr("class", (d) => `graph-node ${d.id === selected ? "is-selected" : ""} ${d.inLineup ? "in-lineup" : ""}`)
      .call(
        d3
          .drag()
          .on("start", (event, d) => {
            if (!event.active) graphSimulation.alphaTarget(0.24).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) graphSimulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      .on("click", (event, d) => {
        state.selectedId = d.id;
        renderDetail();
        renderGraphInspector();
        updateGraphFocus(node, link, d.id);
      });

    node.append("circle").attr("class", "node-halo").attr("r", (d) => d.radius + 10);
    node.append("circle").attr("class", "node-core").attr("r", (d) => d.radius).attr("fill", (d) => colorFor(d.color));
    node.append("text").attr("class", "node-label").attr("y", (d) => d.radius + 18).text((d) => d.name);
    node.append("text").attr("class", "node-tradition").attr("y", (d) => d.radius + 34).text((d) => d.tradition);

    svg.call(
      d3
        .zoom()
        .scaleExtent([0.62, 2.2])
        .on("zoom", (event) => {
          viewport.attr("transform", event.transform);
        })
    );

    graphSimulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink(links)
          .id((d) => d.id)
          .distance((d) => (d.type === "tension" ? 170 : d.type === "affinity" ? 105 : 128))
          .strength((d) => 0.18 + d.weight * 0.28)
      )
      .force("charge", d3.forceManyBody().strength(-520))
      .force("collide", d3.forceCollide().radius((d) => d.radius + 30))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX(width / 2).strength(0.045))
      .force("y", d3.forceY(height / 2).strength(0.045))
      .on("tick", () => {
        link
          .attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
        node.attr("transform", (d) => `translate(${d.x}, ${d.y})`);
      });
  }

  function updateGraphFocus(nodeSelection, linkSelection, selectedId) {
    nodeSelection.attr("class", (d) => `graph-node ${d.id === selectedId ? "is-selected" : ""} ${d.inLineup ? "in-lineup" : ""}`);
    linkSelection.attr("class", (d) => `graph-link ${d.type} ${isRelatedToSelected(d, selectedId) ? "is-related" : ""}`);
  }

  function isRelatedToSelected(link, selectedId) {
    const sourceId = typeof link.source === "object" ? link.source.id : link.source;
    const targetId = typeof link.target === "object" ? link.target.id : link.target;
    return sourceId === selectedId || targetId === selectedId;
  }

  function renderStaticGraph(svg) {
    const width = 960;
    const height = 620;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = 235;
    const selected = state.selectedId;

    const { nodes: graphNodes } = getGraphData();
    const nodes = graphNodes.map((person, index) => {
      const angle = (Math.PI * 2 * index) / philosophers.length - Math.PI / 2;
      return {
        ...person,
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
      };
    });
    const nodeMap = Object.fromEntries(nodes.map((node) => [node.id, node]));

    const links = relations
      .map((relation) => ({
        ...relation,
        sourceNode: nodeMap[relation.source],
        targetNode: nodeMap[relation.target],
      }))
      .filter((link) => link.sourceNode && link.targetNode);

    svg.innerHTML = `
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L6,3 z" fill="#2f75b8"></path>
        </marker>
      </defs>
      ${links
        .map((link) => {
          const color = link.type === "tension" ? "#c84b5d" : link.type === "affinity" ? "#249982" : "#2f75b8";
          const dash = link.type === "affinity" ? "7 8" : link.type === "tension" ? "3 7" : "0";
          const marker = link.type === "influence" ? "marker-end='url(#arrow)'" : "";
          const isRelated = link.source === selected || link.target === selected;
          return `<line class="graph-link ${link.type} ${isRelated ? "is-related" : ""}" x1="${link.sourceNode.x}" y1="${link.sourceNode.y}" x2="${link.targetNode.x}" y2="${link.targetNode.y}" stroke="${color}" stroke-width="${isRelated ? 2.8 : 1.5}" stroke-opacity="${isRelated ? 0.85 : 0.24}" stroke-dasharray="${dash}" ${marker}></line>`;
        })
        .join("")}
      ${nodes
        .map((node) => {
          const color = colorFor(node.color);
          const active = selected === node.id ? "is-selected" : "";
          const inLineup = state.lineup.includes(node.id);
          return `
            <g class="graph-node ${active} ${inLineup ? "in-lineup" : ""}" data-node="${node.id}" transform="translate(${node.x}, ${node.y})">
              <circle class="node-halo" r="${node.radius + 10}"></circle>
              <circle class="node-core" r="${node.radius}" fill="${color}"></circle>
              <text class="node-label" y="${node.radius + 18}">${node.name}</text>
            </g>
          `;
        })
        .join("")}
    `;

    svg.querySelectorAll("[data-node]").forEach((node) => {
      node.addEventListener("click", () => {
        state.selectedId = node.dataset.node;
        renderDetail();
        renderGraph();
      });
    });
  }

  function colorFor(name) {
    return {
      teal: "#31c6b0",
      red: "#f06a7a",
      gold: "#d59a38",
      violet: "#8d83ff",
      blue: "#65a9e8",
    }[name];
  }

  function renderGraphInspector() {
    const person = byId[state.selectedId] || philosophers[0];
    const personRelations = relations.filter((relation) => relation.source === person.id || relation.target === person.id);
    const container = document.querySelector("#graphInspector");
    if (!container) return;
    const recommendation = state.recommendations[person.id];
    const inLineup = state.lineup.includes(person.id);
    const isLineupFull = state.lineup.length >= MAX_LINEUP_SIZE;
    const addDisabled = inLineup || isLineupFull;
    container.innerHTML = `
      <article class="profile-card graph-profile">
        <div class="profile-title">
          <div>
            <h2>${person.name}</h2>
            <p>${person.era} · ${person.tradition}</p>
          </div>
          <button class="mini-button" type="button" data-add="${person.id}" title="${isLineupFull && !inLineup ? "当前阵容最多五位" : "加入圆桌"}" ${addDisabled ? "disabled" : ""}>${inLineup ? "已在圆桌" : "加入"}</button>
        </div>
        <p>${person.summary}</p>
        <p class="small-copy">${person.voice}</p>
        ${recommendation ? `<div class="graph-fit"><strong>推荐分 ${recommendation.score.toFixed(1)}</strong><p>${escapeHtml(recommendation.reasons.slice(0, 2).join("；"))}</p></div>` : ""}
        <h3>核心概念</h3>
        <div class="tag-row">
          ${person.coreConcepts.map((concept) => `<span class="tag">${escapeHtml(concept)}</span>`).join("")}
        </div>
        <h3>讨论话题</h3>
        <div class="tag-row tag-row--compact">
          ${person.topics.map((topic) => `<span class="tag tag--concept">${escapeHtml(topic)}</span>`).join("")}
        </div>
        <h3>立场维度</h3>
        <div class="dimension-list">
          ${dimensions.map((dimension) => renderDimension(person, dimension)).join("")}
        </div>
        <h3 style="margin-top:16px">图谱关系</h3>
        ${personRelations
          .map((relation) => {
            const other = byId[relation.source === person.id ? relation.target : relation.source];
            return `<div class="relation-card graph-relation"><strong>${other.name}</strong> · ${relationLabel(relation.type)}<p class="small-copy">${relation.reason}</p></div>`;
          })
          .join("")}
      </article>
    `;
    container.querySelector("[data-add]")?.addEventListener("click", () => addToLineup(person.id));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function userFacingError(error) {
    return String(error?.message || error || "");
  }

  document.querySelector("#recommendButton").addEventListener("click", recommendLineup);
  document.querySelector("#resetLineupButton").addEventListener("click", recommendLineup);
  document.querySelector("#startDebateButton").addEventListener("click", async () => {
    if (state.isGenerating) return;
    state.isGenerating = true;
    renderOpeningControl();
    try {
      await generateNextRoundStep();
    } finally {
      state.isGenerating = false;
      renderOpeningControl();
    }
  });
  document.querySelector("#summaryButton").addEventListener("click", () => {
    summarizeDebate();
  });
  document.querySelector("#returnToMainButton")?.addEventListener("click", returnToMainQuestion);
  document.querySelector("#interventionForm").addEventListener("submit", (event) => {
    event.preventDefault();
    respondToIntervention(document.querySelector("#interventionInput").value);
  });
  document.querySelector("#saveSettingsButton")?.addEventListener("click", saveSettings);
  document.querySelector("#modelInput")?.addEventListener("input", () => renderProviderStatus());
  document.querySelector("#closeProfileModal")?.addEventListener("click", closeProfileModal);
  document.querySelector("#profileModal")?.addEventListener("click", (event) => {
    if (event.target?.id === "profileModal") closeProfileModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProfileModal();
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });

  state.discussionState = createEmptyDiscussionState();
  state.interventionRound = null;
  state.dynamicRound = createEmptyDynamicRound();
  state.conversation = [];
  loadSettings();
  checkProviderStatus();
  renderAll();
})();

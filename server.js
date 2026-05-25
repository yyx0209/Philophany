const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = __dirname;
loadDotEnv(path.join(ROOT, ".env"));

const PORT = Number(process.env.PORT || 5173);
const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";
const DEFAULT_ANALYSIS_MODEL = process.env.OPENROUTER_MODEL || "deepseek/deepseek-v4-pro";
const DEFAULT_ROUNDTABLE_MODEL = process.env.OPENROUTER_ROUNDTABLE_MODEL || "deepseek/deepseek-v4-pro";
const SPEAKER_ALIAS_OVERRIDES = {
  buddha: ["佛陀", "释迦", "释迦牟尼"],
};

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
};

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, `http://${request.headers.host}`);

    if (request.method === "GET" && url.pathname === "/api/health") {
      sendJson(response, 200, {
        ok: true,
        openRouterConfigured: Boolean(getOpenRouterKey()),
        defaultModel: DEFAULT_ANALYSIS_MODEL,
        defaultAnalysisModel: DEFAULT_ANALYSIS_MODEL,
        defaultRoundtableModel: DEFAULT_ROUNDTABLE_MODEL,
      });
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/chat") {
      await handleChat(request, response);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/analyze-question") {
      await handleAnalyzeQuestion(request, response);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/discussion-state") {
      await handleDiscussionState(request, response);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/next-speaker") {
      await handleNextSpeaker(request, response);
      return;
    }

    if (request.method === "GET" || request.method === "HEAD") {
      serveStatic(url.pathname, request, response);
      return;
    }

    sendJson(response, 405, { error: "Method not allowed" });
  } catch (error) {
    sendJson(response, 500, { error: error.message || "Internal server error" });
  }
});

server.listen(PORT, () => {
  const configured = getOpenRouterKey() ? "configured" : "missing";
  console.log(`Philophany server running at http://127.0.0.1:${PORT}/`);
  console.log(`Model provider key: ${configured}`);
});

async function handleChat(request, response) {
  const apiKey = getOpenRouterKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeContext(body);
  const model = sanitizeModel(body.roundtableModel || DEFAULT_ROUNDTABLE_MODEL);
  const responseSpeakerIds = getResponseSpeakerIds(context);
  const prompt = buildRoundtablePrompt(context);

  const upstream = await fetch(OPENROUTER_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "HTTP-Referer": body.referer || `http://127.0.0.1:${PORT}`,
      "X-Title": "Philophany",
    },
    body: JSON.stringify({
      model,
      temperature: 0.72,
      max_tokens: context.action === "summary" ? 900 : 1500,
      messages: prompt,
    }),
  });

  if (!upstream.ok) {
    let details = "";
    try {
      const errorBody = await upstream.json();
      details = errorBody?.error?.message || JSON.stringify(errorBody);
    } catch {
      details = await upstream.text();
    }

    sendJson(response, upstream.status, {
      error: details || upstream.statusText,
    });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty content for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const allowedIds = new Set(responseSpeakerIds);
  const messages = Array.isArray(parsed.messages)
    ? parsed.messages
        .map((message) => {
          const speakerId = String(message.speakerId || "").trim();
          if (!allowedIds.has(speakerId)) return null;
          return {
            speakerId,
            role: String(message.role || "回应").slice(0, 18),
            text: String(message.text || "").trim(),
          };
        })
        .filter(Boolean)
        .filter((message) => message.text)
    : [];

  if (messages.length === 0) {
    sendJson(response, 502, { error: "Model JSON contained no usable messages." });
    return;
  }

  sendJson(response, 200, { messages, model });
}

async function handleAnalyzeQuestion(request, response) {
  const apiKey = getOpenRouterKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const question = safeString(body.question, 600);
  if (!question) {
    sendJson(response, 400, { error: "question is required." });
    return;
  }

  const knownTopics = safeStringArray(body.knownTopics, 30, 40);
  const knownConcepts = safeStringArray(body.knownConcepts, 120, 60);
  const philosophers = sanitizeAnalysisPhilosophers(body.philosophers);
  const model = sanitizeModel(body.model || DEFAULT_ANALYSIS_MODEL);

  const upstream = await fetch(OPENROUTER_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "HTTP-Referer": body.referer || `http://127.0.0.1:${PORT}`,
      "X-Title": "Philophany",
    },
    body: JSON.stringify({
      model,
      temperature: 0.18,
      max_tokens: 3600,
      messages: buildQuestionAnalysisPrompt({
        question,
        knownTopics,
        knownConcepts,
        philosophers,
      }),
    }),
  });

  if (!upstream.ok) {
    let details = "";
    try {
      const errorBody = await upstream.json();
      details = errorBody?.error?.message || JSON.stringify(errorBody);
    } catch {
      details = await upstream.text();
    }

    sendJson(response, upstream.status, {
      error: details || upstream.statusText,
    });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty content for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  sendJson(response, 200, {
    analysis: sanitizeAnalysis(parsed),
    model,
  });
}

async function handleDiscussionState(request, response) {
  const apiKey = getOpenRouterKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeContext({
    ...body,
    action: "intervention",
  });
  const model = sanitizeModel(body.model || DEFAULT_ANALYSIS_MODEL);

  const upstream = await fetch(OPENROUTER_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "HTTP-Referer": body.referer || `http://127.0.0.1:${PORT}`,
      "X-Title": "Philophany",
    },
    body: JSON.stringify({
      model,
      temperature: 0.12,
      max_tokens: 1200,
      messages: buildDiscussionStatePrompt(context),
    }),
  });

  if (!upstream.ok) {
    let details = "";
    try {
      const errorBody = await upstream.json();
      details = errorBody?.error?.message || JSON.stringify(errorBody);
    } catch {
      details = await upstream.text();
    }

    sendJson(response, upstream.status, {
      error: details || upstream.statusText,
    });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty discussion state for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid discussion-state JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const discussionState = sanitizeDiscussionState(parsed.discussionState || parsed, context.participants);
  sendJson(response, 200, { discussionState, model });
}

async function handleNextSpeaker(request, response) {
  const apiKey = getOpenRouterKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeContext(body);
  const model = sanitizeModel(body.model || DEFAULT_ANALYSIS_MODEL);
  const upstream = await fetch(OPENROUTER_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "HTTP-Referer": body.referer || `http://127.0.0.1:${PORT}`,
      "X-Title": "Philophany",
    },
    body: JSON.stringify({
      model,
      temperature: 0.18,
      max_tokens: 900,
      messages: buildNextSpeakerPrompt(context),
    }),
  });

  if (!upstream.ok) {
    let details = "";
    try {
      const errorBody = await upstream.json();
      details = errorBody?.error?.message || JSON.stringify(errorBody);
    } catch {
      details = await upstream.text();
    }

    sendJson(response, upstream.status, {
      error: details || upstream.statusText,
    });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty scheduler decision for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid scheduler JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const decision = sanitizeNextSpeakerDecision(parsed.decision || parsed, context.participants);
  sendJson(response, 200, { decision, model });
}

function buildQuestionAnalysisPrompt({ question, knownTopics, knownConcepts, philosophers }) {
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的问题理解器。",
        "你负责理解用户问题的思想结构，并给每位候选哲学家一个语义适配分。",
        "不要直接决定最终推荐名单；最终阵容会由本地图谱算法决定。",
        "尽量把自然语言映射到给定的受控词表，但不要牵强。",
        "必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        `用户问题：${question}`,
        "",
        `可用主题词表：${knownTopics.join("、")}`,
        `可用核心概念词表：${knownConcepts.join("、")}`,
        "",
        "候选哲学家简卡：",
        JSON.stringify(philosophers, null, 2),
        "",
        "请输出：",
        "1. themes：3 到 5 个主题，优先使用主题词表。",
        "2. implicitConcepts：3 到 8 个隐含哲学概念，优先使用核心概念词表；可以加入必要的新短语。",
        "3. tensions：2 到 4 个问题张力，格式为简短中文短语，例如「知道 vs 做到」。",
        "4. discussionNeeds：3 到 5 个这场圆桌需要覆盖的问题维度；每项包含 label、needs、reason。label 是讨论维度名称，不是哲学家角色标签；不要写成「怀疑论者角色」「道德裁判」这类功能身份。",
        "5. philosopherFit：必须覆盖每一位候选哲学家；每个 id 对应 fit 和 reason。fit 是 0 到 1 的语义适配分，只表示该哲学家是否适合讨论这个问题，不表示最终会被选中。",
        "6. summary：一句话表达你对这个问题的理解，语气自然，像是在帮用户整理问题。不要把用户问题说成某处卡住了；避免使用“不是……而是……”这类模板句式。",
        "",
        "fit 打分标准：",
        "- 0.85 到 1.00：高度适配，能直接切入问题核心。",
        "- 0.65 到 0.84：适配，能提供重要角度。",
        "- 0.40 到 0.64：有一定关联，但不是核心。",
        "- 0.00 到 0.39：弱相关。",
        "reason 必须具体说明该哲学家为什么适配或不适配，不要只复述哲学家简介；每条 reason 控制在 35 到 70 个中文字符。",
        "",
        "输出格式：",
        JSON.stringify(
          {
            themes: ["行动"],
            implicitConcepts: ["知行合一"],
            tensions: ["知道 vs 做到"],
            discussionNeeds: [
              {
                label: "行动与实践",
                needs: ["知行合一", "实践智慧"],
                reason: "这个问题需要解释为什么理解没有转化为行动。",
              },
            ],
            philosopherFit: {
              "wang-yangming": {
                fit: 0.92,
                reason: "用户问题体现知道与行动断裂，接近知行合一和事上磨炼。",
              },
            },
            summary: "一句话问题理解摘要",
          },
          null,
          2
        ),
      ].join("\n"),
    },
  ];
}

function buildDiscussionStatePrompt(context) {
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的后台讨论状态记录器，不是圆桌发言者。",
        "你的任务是从最近对话中更新主持人的后台笔记，帮助后续 prompt 理解讨论已经走到哪里。",
        "只记录已经出现的观点、未解决张力、未被追问的前提和跑题情况。",
        "不要给下一步行动建议，不生成 nextBestMove，不决定谁应该继续发言。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "后台讨论状态规则：",
        "1. claimsOnTable 只记录当前仍影响讨论的核心主张，最多 8 条。",
        "2. claim 必须是自然中文句子，不要写成哲学家标签或关键词堆砌。",
        "3. speaker 必须来自 participants 的 id。",
        "4. status 只能是 unanswered、challenged、clarified、repeated。",
        "5. needsFollowUp 表示这条主张是否仍需要回应或澄清。",
        "6. unresolvedTensions 记录还没有真正交锋的分歧，最多 5 条。",
        "7. unquestionedAssumptions 记录大家默认但尚未被追问的前提，最多 5 条。",
        "8. drift.level 只能是 none、mild、serious；drift.note 用一句话说明是否偏离用户原问题。",
        "9. 这是后台讨论状态，只作为背景笔记；不得把它当成下一步发言指令。",
        "10. 不使用 nextBestMove，不输出建议动作。",
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(
          {
            discussionState: {
              claimsOnTable: [
                {
                  claim: "一句话概括已经出现的核心主张",
                  speaker: "哲学家 id",
                  status: "unanswered | challenged | clarified | repeated",
                  needsFollowUp: true,
                },
              ],
              unresolvedTensions: ["尚未真正解决或直接交锋的分歧"],
              unquestionedAssumptions: ["被默认但尚未追问的前提"],
              drift: {
                level: "none | mild | serious",
                note: "一句话说明是否偏离原问题",
              },
            },
          },
          null,
          2
        ),
      ].join("\n"),
    },
  ];
}

function buildNextSpeakerPrompt(context) {
  const participantIds = context.participants.map((person) => person.id).join(", ");
  const speakerStats = speakerTurnStats(context);
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的圆桌发言调度器，不是圆桌发言者。",
        "你的任务是根据当前讨论状态决定下一位最有理由说话的哲学家。",
        "只决定下一位发言者，不生成圆桌发言。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "LLM 动态调度规则：",
        "1. 发言紧迫度来自：上一条发言的直接挑战、图谱关系、未解决张力、用户问题相关性、角色是否有独特推进价值。",
        "2. 如果上一条发言点名、反驳或隐性挑战了某位哲学家，这位哲学家的优先级应显著上升。",
        "3. 如果 discussionState.unresolvedTensions 存在，优先选择能直接推进这些张力的人；不是每个人都必须发言。",
        "4. 如果讨论过于一致，可以让更适合解构、追问或重框的人质疑共识前提。",
        "5. 加入沉默补偿：连续多轮未发言但仍与当前问题或张力相关的人，应获得更高优先级。",
        "6. 加入最近发言惩罚：刚刚连续发言的人不要继续主导，除非他被直接点名、直接挑战，或确实是最必要回应者。",
        "7. 如果当前核心张力已经充分回应、没有人的发言紧迫度足够高，可以 shouldContinue=false。",
        "8. 用户点名追问通常不会进入本调度器；如果上下文仍出现单一点名对象，应优先选择被点名者。",
        "9. advanceStyle 只能是 question、deconstruction、rebuttal、clarification、example、summary_pause。",
        "",
        `只允许从这些 participants 中选择 speakerId：${participantIds}`,
        "",
        "发言统计 speakerStats：",
        JSON.stringify(speakerStats, null, 2),
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(
          {
            decision: {
              shouldContinue: true,
              speakerId: "kant",
              advanceStyle: "rebuttal",
              urgencyScore: 0.82,
              reason: "康德刚被尼采直接挑战，且这条张力仍未澄清；虽然康德近轮发过言，但 direct challenge 例外成立。",
            },
          },
          null,
          2
        ),
      ].join("\n"),
    },
  ];
}

function buildRoundtablePrompt(context) {
  const responseSpeakerIds = getResponseSpeakerIds(context);
  const allowedIds = responseSpeakerIds.join(", ");
  const task = taskInstruction(context);

  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的思想圆桌导演，不是百科问答助手。",
        "你的任务是让哲学家围绕用户的问题发生真正的思想交锋。",
        "必须严格依据给定角色卡、立场维度和关系说明生成内容。",
        "不要伪造具体名言、书名章节、页码或历史事实。可以概括思想，但不要假装引用原文。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "圆桌协议：",
        "1. 这不是并列采访。后发言者应主动选择回应此前任意一位哲学家的具体观点，而不必只回应上一位。",
        "2. 回应方式由发言哲学家自己选择，可以是反驳、赞同、澄清、补充、追问或给出建议；不要由系统预先指定。",
        "3. 每条发言都要同时做两件事：回应用户问题 + 回应某个此前观点或用户刚刚插入的问题。",
        "4. 不允许只是介绍哲学家思想；不允许每个人孤立陈述自己的观点。",
        "5. 每位哲学家要保持自己的核心概念、语气和问题意识，但不要漫画化。",
        "6. 凡是提及另一位哲学家的观点，必须先保留对方自己的核心概念、问题意识或关系语境；不得直接把对方观点同化为发言者自己的概念框架。",
        "7. 如果需要转译、类比或吸收到自己的体系中，必须明确标出这是发言者的解释，例如“我会把这理解为……，但这不同于你原本的说法”。",
        "8. 如果选择反驳，必须先准确复述对方立场的强版本，再指出分歧。",
        "9. 如果选择赞同、补充、澄清或建议，也必须说明自己回应的是对方哪一个原本观点，而不是替对方换一套理论。",
        "10. 如果选择澄清，只澄清概念和前提，不急着给建议。",
        "11. 如果选择给建议，必须把哲学分歧转成可执行的下一步判断，但不要替用户做决定。",
        "12. 总结时不要替用户做最终选择；但不能把所有立场机械平等化，必须指出开放分歧、当前论证强弱、实践或规范风险，以及下一步反思问题。",
        "13. 严禁伪造名言、具体引文、书名章节、页码或历史场景；不要使用看起来像原文引语的引号句。",
        "14. 不要输出“作为某某哲学家我会说”这类舞台腔。",
        "15. role 字段要体现发言者自主选择的回应方式，例如：赞同、反驳、澄清、补充、追问、建议、总结。",
        "16. 如果角色卡包含 speechPersona，把它当作发言人格：脾气、惯用动作、遇到反对时的反应、句子节奏、容易过火的风险和样例句都要影响表达方式。",
        "17. 允许的发言动作包括：打断、反问、拒答、重框、挑衅、缓和、翻译成人话。它们可以出现在 role 字段，也可以体现在发言开头和句式里。",
        "18. 可以锋利，但不能人身攻击用户；可以不礼貌，但不能辱骂；可以拒绝问题，但必须给出更好的问法；可以打断别人，但不能歪曲别人。",
        "19. 有趣来自脾气、画面、节奏和思想摩擦，不来自卖萌、段子化或把哲学家写成刻板角色。",
        "20. 例子协议：如果角色卡包含 exampleStyle，就按它决定是否使用例子、使用什么形态的例子，以及是否适合围绕例子争论。",
        "21. 高频和中频 exampleStyle 的哲学家应尽量使用一个短例子、比喻或反例；低频者可以少用例子，但仍可分析别人例子的结构。",
        "22. 如果上一条发言包含具体例子，下一位哲学家应优先围绕这个例子推进：可以用同一个例子给出不同结论、用反例挑战、指出例子预设、或说明例子为什么误导。",
        "23. 例子不能替代论证；不得编造具体历史轶事、真实人物故事或名言；例子必须服务于用户原问题，不能劫持讨论。",
        "",
        task,
        "",
        "后台讨论状态：context.discussionState 是主持人的后台笔记，只作为背景笔记使用；它帮助你避免重复、看见未回应张力和未追问前提，但不得把它当成下一步发言指令。",
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(
          {
            messages: [
              {
                speakerId: "哲学家 id，或 system",
                role: "短标签，例如 第一轮 / 反驳 / 概念澄清 / 总结",
                text: "中文发言",
              },
            ],
          },
          null,
          2
        ),
        "",
        `只允许使用这些 speakerId：${allowedIds}。`,
        interventionSpeakerRule(context),
      ].join("\n"),
    },
  ];
}

function interventionSpeakerRule(context) {
  if (context.action === "opening_step" && context.currentSpeakerId) {
    return `本次第一轮逐位发言只能由 ${speakerName(context, context.currentSpeakerId)} 回应；不要让其他哲学家发言。`;
  }
  if (context.action === "intervention_step" && context.currentSpeakerId) {
    return `本次追问逐位回应只能由 ${speakerName(context, context.currentSpeakerId)} 回应；不要让其他哲学家发言。`;
  }
  if (context.action !== "intervention") return "";
  return context.targetedSpeakerId
    ? `本轮用户点名了 ${speakerName(context, context.targetedSpeakerId)}，只能由这位哲学家回应；不要让其他哲学家发言。`
    : "本轮没有单一点名对象时，也只输出 1 位哲学家的回应；不要一次性让多人连续发言。";
}

function taskInstruction(context) {
  if (context.action === "opening_step") {
    return [
      "任务：生成第一轮中的下一位发言。",
      `当前只能由 ${speakerName(context, context.currentSpeakerId)} 发言；只生成这位哲学家的 1 条发言；每条 90 到 150 个中文字符。`,
      "如果这是第一位发言者，应先提出清楚的初始立场，并直接回应用户问题。",
      "如果已有前文，必须回应已经可见的某个具体观点，而不是预设后面的人会说什么。",
      "role 要按这位哲学家自主选择的回应方式填写，例如初始立场、赞同、反驳、澄清、补充、追问、建议。",
    ].join("\n");
  }

  if (context.action === "intervention_step") {
    const isPointToPoint = context.targetedSpeakerIds.includes(context.currentSpeakerId);
    const responseFocus = isPointToPoint
      ? "用户点名当前发言者时，直接回应用户追问；不要强行回应前文、后台张力或其他哲学家，除非用户问题本身明确要求比较、反驳或回应某人。不得以“回应某某所说”开头。"
      : "必须回应用户追问，并可以连接已经可见的某个具体观点或后台讨论状态中的未解决张力。";
    return [
      "任务：逐位回应用户追问。",
      `用户追问：「${context.intervention || ""}」。`,
      `当前只能由 ${speakerName(context, context.currentSpeakerId)} 回应；只生成这位哲学家的 1 条回应；每条 80 到 150 个中文字符。`,
      responseFocus,
      "不要代替其他哲学家发言，不要预告其他人接下来会说什么。",
      "role 要按这位哲学家自主选择的回应方式填写，例如赞同、反驳、澄清、补充、追问、建议。",
    ].join("\n");
  }

  if (context.action === "opening") {
    return [
      "任务：生成第一轮圆桌。",
      "要求：每位哲学家必须按 participants 顺序发言一次；每条 90 到 150 个中文字符。",
      "结构：第一位先提出初始立场；后续每位哲学家可回应此前任意一位哲学家的观点。",
      "每条后续发言必须明确写出自己回应了谁的哪一点，例如「回应康德关于普遍原则的说法：……」。",
      "role 不要统一写第一轮立场，要按这位哲学家自主选择的回应方式填写，例如赞同、反驳、澄清、补充、追问、建议。",
    ].join("\n");
  }

  if (context.action === "summary") {
    return [
      "任务：总结当前圆桌。",
      "要求：只输出一条 speakerId 为 system 的总结；180 到 280 个中文字符。",
      "内容：不要替用户做最终决定；但要指出核心分歧、哪些问题仍然开放、哪些立场在当前讨论中论证更强或更弱、哪些观点带有实践风险或规范风险，以及用户下一步最该澄清的判断标准。",
    ].join("\n");
  }

  return [
    `任务：回应用户追问「${context.intervention || ""}」。`,
    context.targetedSpeakerId
      ? `要求：用户点名了 ${speakerName(context, context.targetedSpeakerId)}，只生成这位哲学家的 1 条回应；每条 80 到 150 个中文字符。`
      : "要求：没有单一点名对象时，也只生成 1 条回应；每条 80 到 150 个中文字符。",
    "策略：回应方式由发言者自己选择，可以反驳、赞同、澄清、补充、追问或建议；如果回应某个此前观点，要明确写出回应对象和观点。",
  ].join("\n");
}

function sanitizeDiscussionState(rawState, participants = []) {
  const state = rawState && typeof rawState === "object" ? rawState : {};
  const participantIds = new Set(participants.map((person) => person.id).filter(Boolean));
  const allowedStatuses = new Set(["unanswered", "challenged", "clarified", "repeated"]);
  const allowedDriftLevels = new Set(["none", "mild", "serious"]);

  const claimsOnTable = Array.isArray(state.claimsOnTable)
    ? state.claimsOnTable
        .map((claim) => {
          if (!claim || typeof claim !== "object") return null;
          const speaker = safeString(claim.speaker, 40);
          if (!participantIds.has(speaker)) return null;
          const status = safeString(claim.status, 24);
          return {
            claim: safeString(claim.claim, 220),
            speaker,
            status: allowedStatuses.has(status) ? status : "unanswered",
            needsFollowUp: Boolean(claim.needsFollowUp),
          };
        })
        .filter((claim) => claim && claim.claim)
        .slice(0, 8)
    : [];

  const rawDrift = state.drift && typeof state.drift === "object" ? state.drift : {};
  const driftLevel = safeString(rawDrift.level, 20);

  return {
    claimsOnTable,
    unresolvedTensions: safeStringArray(state.unresolvedTensions, 5, 180),
    unquestionedAssumptions: safeStringArray(state.unquestionedAssumptions, 5, 180),
    drift: {
      level: allowedDriftLevels.has(driftLevel) ? driftLevel : "none",
      note: safeString(rawDrift.note, 180),
    },
  };
}

function sanitizeNextSpeakerDecision(value, participants = []) {
  const decision = value && typeof value === "object" ? value : {};
  const participantIds = new Set(participants.map((person) => person.id).filter(Boolean));
  const allowedStyles = new Set(["question", "deconstruction", "rebuttal", "clarification", "example", "summary_pause"]);
  const speakerId = safeString(decision.speakerId, 40);
  const advanceStyle = safeString(decision.advanceStyle, 30);
  const rawShouldContinue = decision.shouldContinue;
  const wantsContinue =
    rawShouldContinue === undefined ? Boolean(speakerId) : rawShouldContinue !== false && rawShouldContinue !== "false";
  const shouldContinue = wantsContinue && participantIds.has(speakerId);

  return {
    shouldContinue,
    speakerId: shouldContinue ? speakerId : "",
    advanceStyle: allowedStyles.has(advanceStyle) ? advanceStyle : "question",
    urgencyScore: clampNumber(Number(decision.urgencyScore) || 0, 0, 1),
    reason: safeString(decision.reason, 220),
  };
}

function sanitizeDynamicRound(value) {
  const round = value && typeof value === "object" ? value : {};
  return {
    turnCount: clampNumber(Number(round.turnCount) || 0, 0, 12),
    closed: Boolean(round.closed),
    lastSpeakerId: safeString(round.lastSpeakerId, 40),
    lastSchedulerReason: safeString(round.lastSchedulerReason, 180),
  };
}

function speakerTurnStats(context) {
  const stats = Object.fromEntries(
    context.participants.map((person) => [
      person.id,
      {
        name: person.name,
        totalTurns: 0,
        turnsSinceLast: null,
        recentTurns: 0,
      },
    ])
  );
  const philosopherMessages = context.recentConversation.filter((message) => stats[message.speakerId]);
  philosopherMessages.forEach((message) => {
    stats[message.speakerId].totalTurns += 1;
  });

  const recentSpeakerIds = philosopherMessages.map((message) => message.speakerId).reverse();
  Object.keys(stats).forEach((id) => {
    const sinceLast = recentSpeakerIds.indexOf(id);
    stats[id].turnsSinceLast = sinceLast >= 0 ? sinceLast : recentSpeakerIds.length;
    stats[id].recentTurns = recentSpeakerIds.slice(0, 4).filter((speakerId) => speakerId === id).length;
  });
  return stats;
}

function sanitizeSpeechPersona(value) {
  if (!value || typeof value !== "object") return {};
  const allowedMoves = new Set(["打断", "反问", "拒答", "重框", "挑衅", "缓和", "翻译成人话"]);
  const favoriteMoves = safeStringArray(value.favoriteMoves, 7, 20).filter((move) => allowedMoves.has(move));
  const sampleLines = safeStringArray(value.sampleLines, 2, 160);
  const persona = {
    temperament: safeString(value.temperament, 120),
    favoriteMoves,
    responseToDisagreement: safeString(value.responseToDisagreement, 180),
    sentenceRhythm: safeString(value.sentenceRhythm, 120),
    overheatRisk: safeString(value.overheatRisk, 200),
    sampleLines,
  };
  return persona.temperament || favoriteMoves.length || sampleLines.length ? persona : {};
}

function sanitizeExampleStyle(value) {
  if (!value || typeof value !== "object") return {};
  const allowedModes = new Set([
    "dialogue_situation",
    "practical_scene",
    "parable",
    "ritual_relationship",
    "suffering_diagnosis",
    "daily_observation",
    "principle_test",
    "historical_mediation",
    "genealogical_scene",
    "existential_choice",
    "language_game",
    "inner_experience",
    "ascent_analogy",
  ]);
  const allowedFrequencies = new Set(["high", "medium", "low"]);
  const mode = safeString(value.mode, 60);
  const frequency = safeString(value.frequency, 20);
  const preferredExampleForms = safeStringArray(value.preferredExampleForms, 2, 80);
  const avoidExampleForms = safeStringArray(value.avoidExampleForms, 2, 80);
  const signatureExample = safeString(value.signatureExample, 180);
  const exampleStyle = {
    mode: allowedModes.has(mode) ? mode : "practical_scene",
    frequency: allowedFrequencies.has(frequency) ? frequency : "medium",
    canDebateOnExample: value.canDebateOnExample !== false,
    preferredExampleForms,
    avoidExampleForms,
    signatureExample,
  };
  return preferredExampleForms.length || avoidExampleForms.length || signatureExample ? exampleStyle : {};
}

function sanitizeContext(body) {
  const action = ["opening", "opening_step", "intervention", "intervention_step", "summary"].includes(body.action)
    ? body.action
    : "intervention";
  const participants = Array.isArray(body.participants)
    ? body.participants
        .map((person) => ({
          id: safeString(person.id, 40),
          name: safeString(person.name, 40),
          tradition: safeString(person.tradition, 80),
          coreConcepts: safeStringArray(person.coreConcepts, 8, 40),
          topics: safeStringArray(person.topics, 10, 30),
          stance: typeof person.stance === "object" && person.stance ? person.stance : {},
          voice: safeString(person.voice, 220),
          speechPersona: sanitizeSpeechPersona(person.speechPersona),
          exampleStyle: sanitizeExampleStyle(person.exampleStyle),
          summary: safeString(person.summary, 320),
        }))
        .filter((person) => person.id && person.name)
        .slice(0, 6)
    : [];

  if (participants.length === 0) {
    throw new Error("At least one participant is required.");
  }

  const context = {
    action,
    question: safeString(body.question, 500) || "我该如何理解自己的困惑？",
    intervention: safeString(body.intervention, 500),
    currentSpeakerId: "",
    participants,
    relations: Array.isArray(body.relations)
      ? body.relations
          .map((relation) => ({
            source: safeString(relation.source, 40),
            target: safeString(relation.target, 40),
            sourceName: safeString(relation.sourceName, 40),
            targetName: safeString(relation.targetName, 40),
            type: safeString(relation.type, 30),
            reason: safeString(relation.reason, 260),
          }))
          .slice(0, 20)
      : [],
    recentConversation: Array.isArray(body.recentConversation)
      ? body.recentConversation
          .map((message) => ({
            speakerId: safeString(message.speakerId, 40),
            speaker: safeString(message.speaker, 40),
            role: safeString(message.role, 30),
            text: safeString(message.text, 360),
          }))
          .slice(-12)
      : [],
    discussionState: sanitizeDiscussionState(body.discussionState, participants),
    dynamicRound: sanitizeDynamicRound(body.dynamicRound),
  };

  const requestedSpeakerId = safeString(body.currentSpeakerId, 40);
  context.currentSpeakerId = participants.some((person) => person.id === requestedSpeakerId)
    ? requestedSpeakerId
    : participants[0]?.id || "";

  context.targetedSpeakerIds = findTargetedSpeakerIds(context);
  context.targetedSpeakerId = context.targetedSpeakerIds[0] || "";
  return context;
}

function sanitizeAnalysis(value) {
  const rawDiscussionNeeds = value.discussionNeeds || value.slots;
  const discussionNeeds = Array.isArray(rawDiscussionNeeds)
    ? rawDiscussionNeeds
        .map((need) => ({
          label: safeString(need.label || need.role || need.name, 80),
          needs: safeStringArray(need.needs || need.concepts || need.keywords, 8, 60),
          reason: safeString(need.reason, 220),
        }))
        .filter((need) => need.label || need.needs.length > 0)
        .slice(0, 5)
    : [];

  return {
    themes: labelsFromMixedArray(value.themes, 5, 40),
    implicitConcepts: labelsFromMixedArray(value.implicitConcepts || value.concepts, 8, 60),
    tensions: labelsFromMixedArray(value.tensions, 5, 80),
    discussionNeeds,
    philosopherFit: sanitizePhilosopherFit(value.philosopherFit || value.fitScores || value.philosophers),
    summary: safeString(value.summary, 260),
  };
}

function sanitizePhilosopherFit(value) {
  if (!value || typeof value !== "object") return {};

  const entries = Array.isArray(value)
    ? value.map((item) => [item.id || item.philosopherId || item.name, item])
    : Object.entries(value);

  return Object.fromEntries(
    entries
      .map(([id, item]) => {
        const rawFit = typeof item === "number" ? item : item?.fit ?? item?.score ?? item?.relevance;
        const fit = clampNumber(Number(rawFit), 0, 1);
        const reason = typeof item === "string" ? item : item?.reason || item?.why || "";
        return [
          safeString(id, 60),
          {
            fit,
            reason: safeString(reason, 260),
          },
        ];
      })
      .filter(([id]) => id)
  );
}

function sanitizeAnalysisPhilosophers(value) {
  if (!Array.isArray(value)) return [];

  return value
    .map((person) => ({
      id: safeString(person.id, 60),
      name: safeString(person.name, 40),
      tradition: safeString(person.tradition, 80),
      coreConcepts: safeStringArray(person.coreConcepts, 8, 40),
      topics: safeStringArray(person.topics, 10, 30),
      summary: safeString(person.summary, 260),
    }))
    .filter((person) => person.id && person.name)
    .slice(0, 80);
}

function labelsFromMixedArray(value, maxItems, maxLength) {
  if (!Array.isArray(value)) return [];

  return value
    .map((item) => {
      if (typeof item === "string") return safeString(item, maxLength);
      if (item && typeof item === "object") {
        return safeString(item.label || item.name || item.theme || item.concept || item.text, maxLength);
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, maxItems);
}

function getResponseSpeakerIds(context) {
  if (context.action === "summary") return ["system"];
  if (context.action === "opening_step" && context.currentSpeakerId) return [context.currentSpeakerId];
  if (context.action === "intervention_step" && context.currentSpeakerId) return [context.currentSpeakerId];
  if (context.action === "intervention" && context.targetedSpeakerId) {
    return [context.targetedSpeakerId];
  }
  return context.participants.map((person) => person.id);
}

function findTargetedSpeakerId(context) {
  return findTargetedSpeakerIds(context)[0] || "";
}

function findTargetedSpeakerIds(context) {
  if (!["intervention", "intervention_step"].includes(context.action) || !context.intervention) return [];

  const text = context.intervention;
  const participants = context.participants;
  const atMentioned = extractAtMentionedSpeakers(text, participants);
  if (atMentioned.length > 0) {
    const speakers = shouldTreatAtMentionsAsSpeakerQueue(text, atMentioned) ? atMentioned : [atMentioned[0]];
    return speakers.map((person) => person.id);
  }

  const directlyAddressed = participants.filter((person) => {
    return speakerNameCandidates(person).some((alias) => {
      const escaped = escapeRegExp(alias);
      const patterns = directAddressPatterns(escaped);
      return patterns.some((pattern) => new RegExp(pattern).test(text));
    });
  });

  if (directlyAddressed.length === 1) {
    return [directlyAddressed[0].id];
  }

  const mentioned = participants.filter((person) => speakerNameCandidates(person).some((alias) => text.includes(alias)));
  return mentioned.length === 1 ? [mentioned[0].id] : [];
}

function shouldTreatAtMentionsAsSpeakerQueue(text, atMentioned) {
  if (atMentioned.length < 2) return false;
  if (/你们|二位|两位|各自|分别|都|一起|轮流/.test(text)) return true;
  return startsWithAtMentionSpeakerCluster(text);
}

function startsWithAtMentionSpeakerCluster(text) {
  let rest = safeString(text, 1000).trimStart();
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
  const seen = new Set();
  return [...safeString(text, 1000).matchAll(/@([^@\s，,。；;：:！!？?、]+)/g)]
    .map((match) => findPersonByMention(match[1], participants))
    .filter(Boolean)
    .filter((person) => {
      if (seen.has(person.id)) return false;
      seen.add(person.id);
      return true;
    });
}

function findPersonByMention(rawMention, participants) {
  const mention = safeString(rawMention, 80);
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

function speakerNameCandidates(person) {
  const normalizedName = safeString(person?.name, 80);
  if (!normalizedName) return [];
  const parts = normalizedName.split(/[·・.\s]+/).map((part) => part.trim()).filter((part) => part.length >= 2);
  return [...new Set([normalizedName, ...parts, ...(SPEAKER_ALIAS_OVERRIDES[person?.id] || [])])];
}

function speakerName(context, id) {
  return context.participants.find((person) => person.id === id)?.name || id;
}

function serveStatic(urlPath, request, response) {
  const decoded = decodeURIComponent(urlPath);
  const normalized = path.normalize(decoded === "/" ? "/index.html" : decoded);
  const filePath = path.join(ROOT, normalized);

  if (!filePath.startsWith(ROOT)) {
    sendText(response, 403, "Forbidden");
    return;
  }

  fs.stat(filePath, (statError, stat) => {
    if (statError || !stat.isFile()) {
      sendText(response, 404, "Not found");
      return;
    }

    const contentType = MIME_TYPES[path.extname(filePath).toLowerCase()] || "application/octet-stream";
    response.writeHead(200, {
      "Content-Type": contentType,
      "Content-Length": stat.size,
    });

    if (request.method === "HEAD") {
      response.end();
      return;
    }

    fs.createReadStream(filePath).pipe(response);
  });
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 120_000) {
        request.destroy();
        reject(new Error("Request body too large."));
      }
    });
    request.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error("Request body must be valid JSON."));
      }
    });
    request.on("error", reject);
  });
}

function parseModelJson(content) {
  const trimmed = content.trim();
  try {
    return JSON.parse(trimmed);
  } catch {
    const match = trimmed.match(/\{[\s\S]*\}/);
    if (!match) throw new Error("No JSON object found.");
    return JSON.parse(match[0]);
  }
}

function safeString(value, maxLength) {
  return String(value || "").trim().slice(0, maxLength);
}

function safeStringArray(value, maxItems, maxLength) {
  return Array.isArray(value) ? value.map((item) => safeString(item, maxLength)).filter(Boolean).slice(0, maxItems) : [];
}

function sanitizeModel(value) {
  const model = safeString(value, 120);
  return /^[a-zA-Z0-9._:/-]+$/.test(model) ? model : DEFAULT_ANALYSIS_MODEL;
}

function clampNumber(value, min, max) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(min, Math.min(max, value));
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getOpenRouterKey() {
  return process.env.OPENROUTER_API_KEY || "";
}

function sendJson(response, status, data) {
  const body = JSON.stringify(data);
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  response.end(body);
}

function sendText(response, status, text) {
  response.writeHead(status, {
    "Content-Type": "text/plain; charset=utf-8",
    "Content-Length": Buffer.byteLength(text),
  });
  response.end(text);
}

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return;

  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    const equalsIndex = trimmed.indexOf("=");
    if (equalsIndex === -1) continue;

    const key = trimmed.slice(0, equalsIndex).trim();
    let value = trimmed.slice(equalsIndex + 1).trim();
    if (!key || process.env[key]) continue;

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

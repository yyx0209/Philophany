const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = __dirname;
loadDotEnv(path.join(ROOT, ".env"));

const PORT = Number(process.env.PORT || 5173);
const DEEPSEEK_URL = process.env.DEEPSEEK_API_URL || "https://api.deepseek.com/chat/completions";
const DEEPSEEK_TIMEOUT_MS = Number(process.env.DEEPSEEK_TIMEOUT_MS || 45_000);
const DEFAULT_ANALYSIS_MODEL = normalizeDeepSeekModel(process.env.DEEPSEEK_MODEL || "deepseek-v4-pro");
const DEFAULT_ROUNDTABLE_MODEL = normalizeDeepSeekModel(
  process.env.DEEPSEEK_ROUNDTABLE_MODEL || "deepseek-v4-pro"
);
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
        deepSeekConfigured: Boolean(getDeepSeekKey()),
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

    if (request.method === "POST" && url.pathname === "/api/debate-angles") {
      await handleDebateAngles(request, response);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/debate-turn") {
      await handleDebateTurn(request, response);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/socratic-chat") {
      await handleSocraticChat(request, response);
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
  const configured = getDeepSeekKey() ? "configured" : "missing";
  console.log(`Philophany server running at http://127.0.0.1:${PORT}/`);
  console.log(`DeepSeek API key: ${configured}`);
});

async function handleChat(request, response) {
  const apiKey = getDeepSeekKey();
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

  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.72,
      max_tokens: context.action === "summary" ? 900 : 1500,
      messages: prompt,
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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
  const apiKey = getDeepSeekKey();
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

  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.18,
      max_tokens: 3600,
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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
  const apiKey = getDeepSeekKey();
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

  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.12,
      max_tokens: 1200,
      messages: buildDiscussionStatePrompt(context),
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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
  const apiKey = getDeepSeekKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeContext(body);
  const model = sanitizeModel(body.model || DEFAULT_ANALYSIS_MODEL);
  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.18,
      max_tokens: 900,
      messages: buildNextSpeakerPrompt(context),
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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

async function handleDebateAngles(request, response) {
  const apiKey = getDeepSeekKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeDebateContext(body);
  const model = sanitizeModel(body.model || DEFAULT_ANALYSIS_MODEL);
  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.2,
      max_tokens: 1200,
      messages: buildDebateAnglesPrompt(context),
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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
    sendJson(response, upstream.status, { error: details || upstream.statusText });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty debate angles for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid debate-angle JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const angles = sanitizeDebateAngles(parsed.angles || parsed.debateAngles || parsed);
  if (angles.length === 0) {
    sendJson(response, 502, { error: "Model JSON contained no usable debate angles." });
    return;
  }
  sendJson(response, 200, { angles, model });
}

async function handleDebateTurn(request, response) {
  const apiKey = getDeepSeekKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeDebateContext(body);
  const model = sanitizeModel(body.roundtableModel || DEFAULT_ROUNDTABLE_MODEL);
  const upstream = await fetch(DEEPSEEK_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.68,
      max_tokens: 1100,
      messages: buildDebateTurnPrompt(context),
      response_format: { type: "json_object" },
      thinking: { type: "disabled" },
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
    sendJson(response, upstream.status, { error: details || upstream.statusText });
    return;
  }

  const payload = await upstream.json();
  const content = payload?.choices?.[0]?.message?.content;
  if (!content) {
    sendJson(response, 502, {
      error: `Model provider returned empty debate turn for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid debate-turn JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const message = sanitizeDebateMessage(parsed.message || parsed, context);
  if (!message.text) {
    sendJson(response, 502, { error: "Model JSON contained no usable debate message." });
    return;
  }
  sendJson(response, 200, { message, model });
}

async function handleSocraticChat(request, response) {
  const apiKey = getDeepSeekKey();
  if (!apiKey) {
    sendJson(response, 400, {
      error: "API key is not configured on the server.",
    });
    return;
  }

  const body = await readJsonBody(request);
  const context = sanitizeSocraticContext(body);
  const model = sanitizeModel(body.model || DEFAULT_ROUNDTABLE_MODEL);

  let upstream;
  try {
    upstream = await fetchWithTimeout(
      DEEPSEEK_URL,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model,
          temperature: 0.5,
          max_tokens: 1400,
          messages: buildSocraticPrompt(context),
          response_format: { type: "json_object" },
          thinking: { type: "disabled" },
        }),
      },
      DEEPSEEK_TIMEOUT_MS
    );
  } catch (error) {
    if (isAbortError(error)) {
      sendJson(response, 504, {
        error: `Model provider timed out after ${DEEPSEEK_TIMEOUT_MS}ms for model ${model}.`,
      });
      return;
    }
    throw error;
  }

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
      error: `Model provider returned empty Socratic response for model ${model}.`,
      finishReason: payload?.choices?.[0]?.finish_reason || null,
    });
    return;
  }

  let parsed;
  try {
    parsed = parseModelJson(content);
  } catch (error) {
    sendJson(response, 502, {
      error: `Model did not return valid Socratic JSON: ${error.message}`,
      raw: content,
    });
    return;
  }

  const message = parsed.message && typeof parsed.message === "object" ? parsed.message : {};
  let role = sanitizeSocraticRole(message.role || parsed.role);
  const baseSocraticText = enforceSocraticSecondPersonText(safeString(message.text || parsed.text, 520), context, role);
  let text =
    context.userIntent === "ask_socrates_view" ? baseSocraticText : enforceSocraticDriftText(baseSocraticText, context);
  if (context.socraticControl?.shouldRedirect && role !== "自我理解" && context.userIntent !== "ask_socrates_view") {
    role = "追问";
    text = enforceSocraticRedirectText(text, context);
  } else if (
    context.socraticControl?.shouldShiftTempo &&
    role !== "自我理解" &&
    context.userIntent !== "ask_socrates_view" &&
    textLooksLikeDefinitionQuestion(text)
  ) {
    role = "例子追问";
    text = buildSocraticTempoShiftQuestion(context);
  }
  if (!text) {
    sendJson(response, 502, { error: "Model JSON contained no Socratic message text." });
    return;
  }

  sendJson(response, 200, {
    message: {
      role,
      text,
    },
    socraticState: sanitizeSocraticState(parsed.socraticState || parsed.state),
    stage: sanitizeSocraticStage(parsed.stage),
    model,
  });
}

function buildDebateAnglesPrompt(context) {
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的二人辩论策划器。",
        "辩论不是圆桌缩小版；你的任务不是让两位哲学家泛泛对谈，而是找出二者最值得正面交锋的思想张力。",
        "必须严格依据给定角色卡、pairRelations 和 stanceDifferences。",
        "不要伪造具体名言、书名章节、页码或历史事实。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "角度生成规则：",
        "1. 只推荐 3 个张力角度，不多不少。",
        "2. 每个角度必须能让两位哲学家直接互相反驳，而不是并列介绍思想。",
        "3. 优先使用已有 tension 关系、最大 stanceDifferences、核心概念冲突和影响/反影响关系。",
        "4. title 要短，像一个可点击辩题；focus 说明具体争点；reason 说明为什么这两个人会在这里冲突。",
        "5. openingQuestion 是开场时可以抛出的具体问题，不要写成口号。",
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(
          {
            angles: [
              {
                id: "morality-life",
                title: "普遍道德 vs 生命力量",
                focus: "康德要求行动准则能够普遍化，尼采怀疑普遍道德会压低生命力量。",
                reason: "这能让两人围绕道德根据而非性格标签直接交锋。",
                openingQuestion: "当一个行动让生命更强，却不能被普遍化时，它应不应该被肯定？",
              },
            ],
          },
          null,
          2
        ),
      ].join("\n"),
    },
  ];
}

function buildDebateTurnPrompt(context) {
  const participantIds = context.participants.map((person) => person.id).join(", ");
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的二人辩论导演。",
        "你只生成当前这一位哲学家的发言，不替另一位说话。",
        "必须严格依据给定角色卡、所选张力角度、pairRelations 和最近发言。",
        "不要伪造具体名言、书名章节、页码或历史事实。可以概括思想，但不要假装引用原文。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "二人辩论协议：",
        "1. 每次只生成一位哲学家的发言，speakerId 必须是 currentSpeakerId。",
        "2. 发言必须围绕 angle，不要滑向通用圆桌发言。",
        "3. 如果已有上一条哲学家发言，必须回应上一条中的一个具体主张；可以反驳、澄清、重框、追问或给例子。",
        "4. 提及对方观点时，必须保留对方自己的核心概念和问题意识，不能把对方同化成自己的概念。",
        "5. 可以锋利、有脾气，但不能辱骂或人身攻击用户。",
        "6. 高频或中频 exampleStyle 的哲学家可以用短例子；低频者可以少用例子，但仍要把分歧讲清楚。",
        "7. 如果用户插入 intervention，先回应用户插入，再接回所选张力角度。",
        "8. role 用短标签，例如 开场、反驳、澄清、重框、追问、例子检验、回应插入。",
        "",
        "风格分离协议：",
        "9. 如果当前哲学家有 debateVoiceGuardrails，必须优先服从其中的 style、mustDo 和 mustAvoid；这比通用辩论协议更具体。",
        "10. 不要让所有哲学家共享“复述对方-提出比喻-反问”的同一种辩论腔；当前发言必须听起来明显属于 currentSpeakerId。",
        "11. speechPersona.sampleLines 只用于模仿语气，绝不能当作已经发生的对话、对方观点、历史事实或可引用原文。",
        "12. 开场发言只能回应 angle.openingQuestion、pairRelations、stanceDifferences 和用户插入；不能回应角色卡样例句。",
        "",
        `只允许 speakerId 为 currentSpeakerId；participants 为：${participantIds}`,
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(
          {
            message: {
              speakerId: "kant",
              role: "反驳",
              text: "中文发言",
            },
          },
          null,
          2
        ),
      ].join("\n"),
    },
  ];
}

function buildSocraticPrompt(context) {
  const isSelfUnderstanding = context.userIntent === "synthesize_self_understanding";
  const isViewRequest = context.userIntent === "ask_socrates_view";
  const isRedirect = context.socraticControl?.shouldRedirect && !isSelfUnderstanding && !isViewRequest;
  const isTempoShift = context.socraticControl?.shouldShiftTempo && !isSelfUnderstanding && !isViewRequest && !isRedirect;
  const stanceRequestNote = isSelfUnderstanding
    ? [
        "本轮用户点击了“生成自我理解”。",
        "不要继续追问，不要给人生建议，不要补充哲学史知识。",
        "请根据当前对话生成一段阶段性的自我理解。你是苏格拉底在对用户说话，必须用第二人称称呼用户。",
        "避免使用用户自述式主语；应该写成“你真正困惑”“你可能默认”。",
        "必须包含：真正困惑的焦点、当前在乎的价值、可能前提、内部张力、还没想清楚的问题。",
      ].join("\n")
    : isViewRequest
      ? [
          "本轮用户不是在回答上一问，而是在问苏格拉底“你怎么看”。",
          "这时必须先给一个简短的苏格拉底式判断或镜像，不要立刻继续原先那一个问题。",
          "不要套用回题句式，例如“如果放回……”。",
          "格式：先用 1 到 2 句说明你目前怎么看用户的说法，再用 1 个问题把主动权交还给用户。",
        ].join("\n")
    : isTempoShift
      ? [
          "连续定义追问已经够多，本轮不要再问“X 是什么 / X 是指什么”。",
          "请换成例子、反例、判断标准或选择代价，让用户把已经澄清的概念用起来。",
          "不把原问题的直接概念链误判为偏题；直接概念可以追问，但追问节奏要变化。",
        ].join("\n")
    : isRedirect
      ? [
          "本轮需要从派生局部回到原问题直接提问。",
          "不要宣布停顿，不要做阶段小结，不要让用户先消化。",
          "直接围绕 wholeQuestionReminder 提一个自然问题，把当前 focus 接回原问题的直接部分。",
          "message.role 必须是“追问”，message.text 应以一个问题结束。",
        ].join("\n")
      : "本轮用户主要是在回答或补充自己的想法，继续按产婆术推进。";
  const outputExample = isSelfUnderstanding
    ? {
        message: {
          role: "自我理解",
          text: "目前你更清楚地看到：你真正困惑的不是要不要努力，而是你如何判断努力是否值得。你在乎的似乎是结果之外的某种不自欺；你可能默认意义必须被证明，所以一旦没有确定结果就会动摇。还没想清楚的是：什么样的努力，即使没有外部回报，你也愿意承认它不是空的？",
        },
        socraticState: {
          originalQuestion: "用户最初的问题",
          currentUnderstanding: "用户正在形成一段关于意义和判断标准的阶段性自我理解。",
          keyTerms: ["意义"],
          clarifiedTerms: ["意义：用户暂时把它和结果感联系在一起"],
          userClaims: ["用户认为努力可能只是自我说服"],
          assumptions: ["有意义的事需要某种可见结果"],
          tensions: ["怀疑努力的意义，但仍希望努力不是空的"],
          openQuestions: ["什么样的努力即使没有外部回报也不是空的？"],
          focus: "努力是否必须被结果证明",
          wholeQuestionReminder: "用户不是只在问结果，而是在问努力、意义和自我说服之间的关系。",
          driftCheck: "none",
          stage: "summarizing",
        },
        stage: "summarizing",
      }
    : isTempoShift
      ? {
          message: {
            role: "例子追问",
            text: "换个方式问：在一个具体处境里，什么时候它会让你觉得值得主动推动，什么时候又会让你觉得已经背离了自己？",
          },
          socraticState: {
            originalQuestion: "用户最初的问题",
            currentUnderstanding: "用户已经连续澄清了几个概念，现在需要把概念放回具体判断。",
            keyTerms: ["无为", "有为"],
            clarifiedTerms: ["有为：用户暂时把它和主动推动联系在一起"],
            userClaims: ["用户认为有为带有主动性"],
            assumptions: ["主动推动是否值得取决于它是否背离自己"],
            tensions: ["主动推动 vs 不背离自己"],
            openQuestions: ["什么样的主动推动仍然没有背离自己？"],
            focus: "主动推动是否背离自己",
            wholeQuestionReminder: "用户在问应该无为还是有为。",
            driftCheck: "none",
            stage: "finding_tension",
          },
          stage: "finding_tension",
        }
    : isRedirect
      ? {
          message: {
            role: "追问",
            text: "所以你是不是在重新理解“努力”：它不只是追求结果，而是某种不背离自己的行动？这个理解成立吗？",
          },
          socraticState: {
            originalQuestion: "用户最初的问题",
            currentUnderstanding: "用户正在把局部例子接回原问题的直接分歧。",
            keyTerms: ["意义"],
            clarifiedTerms: ["意义：用户暂时把它和结果感联系在一起"],
            userClaims: ["用户认为努力可能只是自我说服"],
            assumptions: ["有意义的事需要某种可见结果"],
            tensions: ["怀疑努力的意义，但仍希望努力不是空的"],
            openQuestions: ["什么样的努力即使没有外部回报也不是空的？"],
            focus: "努力是否需要被结果证明",
            wholeQuestionReminder: "用户不是只在问结果，而是在问努力、意义和自我说服之间的关系。",
            driftCheck: "none",
            stage: "finding_tension",
          },
          stage: "finding_tension",
        }
    : {
        message: {
          role: "追问",
          text: "一句短回应或追问，帮助用户继续澄清自己的判断。",
        },
        socraticState: {
          originalQuestion: "用户最初的问题",
          currentUnderstanding: "一句话说明当前理解",
          keyTerms: ["意义"],
          clarifiedTerms: ["意义：用户暂时把它和结果感联系在一起"],
          userClaims: ["用户认为努力可能只是自我说服"],
          assumptions: ["有意义的事需要某种可见结果"],
          tensions: ["怀疑努力的意义，但仍希望努力不是空的"],
          openQuestions: ["什么样的结果才算足以支撑意义？"],
          focus: "结果是否支撑意义",
          wholeQuestionReminder: "用户不是只在问结果，而是在问努力、意义和自我说服之间的关系。",
          driftCheck: "none",
          stage: "clarifying_terms",
        },
        stage: "clarifying_terms",
      };
  return [
    {
      role: "system",
      content: [
        "你是 Philophany 的苏格拉底产婆术引导者。",
        "你的目标不是替用户给答案，而是帮助用户把自己的判断、概念和前提生出来。",
        "你必须主要使用用户自己的词推进对话；不要把对话变成哲学史讲解、心理咨询或人生建议。",
        "不要伪造苏格拉底、柏拉图或任何文本中的具体名言、章节、页码、历史场景。",
        "中文输出。必须只返回合法 JSON，不要 Markdown，不要代码块。",
      ].join("\n"),
    },
    {
      role: "user",
      content: [
        "产婆术协议：",
        "1. 每次只推进一个清楚问题，不要一次抛出多个问题。",
        "2. 优先追问关键词的含义、判断标准、例外情形、隐藏前提和自相矛盾处。",
        "3. 追问要短而具体，最好引用用户刚刚说过的词。",
        "4. 不急着给建议；除非用户明确要求建议，否则不要输出行动清单。",
        "5. 如果用户表达自我否定或痛苦，可以先承认感受，但不要扮演治疗师；仍回到概念澄清。",
        "6. 如果发现矛盾，要温和指出：先复述两边，再问用户愿意修正哪一边。",
        "7. 如果当前追问已经进入原问题派生出的细枝末节，不要继续深挖该局部；应回到原问题的直接部分继续追问。",
        "8. 如果用户的问题过于抽象，要请用户给一个具体情境或例子。",
        "9. 回答长度控制在 70 到 150 个中文字符；不要长篇解释。",
        "10. 如果用户问“你觉得呢”“你怎么看”“你会怎么想”，不要机械继续上一问；先回应你的看法，再给一个追问。",
        "11. 苏格拉底的看法不是结论裁判，而是对用户说法的临时镜像：指出你听见的前提、张力或可能修正方向。",
        "12. message.role 只能是：追问、概念澄清、前提追问、温和反诘、小结、例子追问、临时判断、自我理解。",
        "13. 如果本轮意图是 synthesize_self_understanding，第 1、7、9 条让位于阶段整理：不要提出新的追问，长度可到 260 个中文字符。",
        "14. 每轮都要更新 focus、wholeQuestionReminder、driftCheck，用它们防止只抓住局部无限深挖。",
        "15. 如果 driftCheck 是 narrow，下一问必须把当前局部接回原问题全貌；但不把原问题的直接概念链误判为偏题。",
        "16. 如果 driftCheck 是 off_track，先用一句话拉回原问题，再提一个服务于原问题的问题。",
        "17. 当输入 socraticState.driftCheck 已经是 narrow 或 off_track 时，message.text 必须明确提到 wholeQuestionReminder 中的另一个维度；不能只继续定义当前 focus。",
        "18. 当 socraticControl.shouldRedirect 为 true 时，message.role 必须是“追问”，并且 message.text 要回到原问题直接提问。",
        "19. 当 socraticControl.shouldShiftTempo 为 true 时，连续定义追问已经够多；必须改问例子、反例、判断标准或选择代价。",
        "20. 用户已经提出新的区分标准时，优先追问是否要改写定义；不要反复把焦点归类到二分选项里。",
        "",
        "本轮用户意图：",
        stanceRequestNote,
        "",
        "socraticState 规则：",
        "- originalQuestion：用户最初的问题。",
        "- currentUnderstanding：一句话说明当前对用户问题的理解。",
        "- keyTerms：最多 6 个关键词。",
        "- clarifiedTerms：最多 6 个已稍微澄清的概念。",
        "- userClaims：最多 6 个用户已经表达过的判断。",
        "- assumptions：最多 6 个可能前提。",
        "- tensions：最多 5 个内部张力。",
        "- openQuestions：最多 5 个还需要继续追问的问题。",
        "- focus：这一轮正在追问的问题局部。",
        "- wholeQuestionReminder：一句话提醒原问题的整体理解。",
        "- driftCheck：只能是 none、narrow、off_track。none 表示仍服务于原问题；narrow 表示正在局部深挖，需要接回全貌；off_track 表示已经偏离，需要先拉回。",
        "- stage 只能是 starting、clarifying_terms、testing_assumptions、finding_tension、summarizing。",
        "",
        "上下文 JSON：",
        JSON.stringify(context, null, 2),
        "",
        "输出格式：",
        JSON.stringify(outputExample, null, 2),
      ].join("\n"),
    },
  ];
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

function sanitizeSocraticContext(body) {
  const input = safeString(body.input || body.message || body.reply, 900);
  const question = safeString(body.question, 700) || input;
  if (!input && !question) {
    throw new Error("question or input is required.");
  }
  const history = sanitizeSocraticHistory(body.history);
  const socraticState = sanitizeSocraticState(body.socraticState || body.state);

  return {
    question: question || "我想把自己的困惑想清楚。",
    input: input || question,
    userIntent: sanitizeSocraticUserIntent(body.userIntent || inferSocraticUserIntent(input)),
    history,
    socraticState,
    socraticControl: sanitizeSocraticControl(body.socraticControl, history, socraticState),
  };
}

function inferSocraticUserIntent(input) {
  return /你觉得呢|你怎么看|你认为呢|你会怎么想|你说呢|你的看法|给我一点判断|直接说/.test(input)
    ? "ask_socrates_view"
    : "answer";
}

function sanitizeSocraticUserIntent(value) {
  const intent = safeString(value, 40);
  return ["ask_socrates_view", "synthesize_self_understanding"].includes(intent) ? intent : "answer";
}

function sanitizeSocraticHistory(value) {
  const allowedSpeakers = new Set(["user", "socrates"]);
  return Array.isArray(value)
    ? value
        .map((message) => {
          const speaker = safeString(message.speaker || message.speakerId, 30);
          return {
            speaker: allowedSpeakers.has(speaker) ? speaker : "user",
            role: safeString(message.role, 30),
            text: safeString(message.text, 520),
          };
        })
        .filter((message) => message.text)
        .slice(-16)
    : [];
}

function sanitizeSocraticControl(value, history, socraticState) {
  const control = value && typeof value === "object" ? value : {};
  const userAnswerCount = userAnswerCountSinceSocraticRedirect(history);
  const explicitRedirect = control.shouldRedirect === true;
  const shouldShiftTempo = isDefinitionChainStale(history);
  const shouldRedirect = shouldRedirectSocraticThread(history, socraticState, explicitRedirect);
  const reason = explicitRedirect
    ? "requested"
    : ["narrow", "off_track"].includes(socraticState.driftCheck)
      ? "drift"
      : shouldShiftTempo
        ? "definition_chain"
      : isDerivativeSocraticFocus(socraticState) && userAnswerCount >= 2
        ? "derivative_focus"
        : "";
  return {
    shouldRedirect,
    shouldShiftTempo,
    reason,
    userAnswerCountSinceRedirect: userAnswerCount,
  };
}

function shouldRedirectSocraticThread(history, socraticState, explicitRedirect = false) {
  const directConceptFocus = hasDirectSocraticConceptFocus(socraticState);
  const driftRedirect =
    socraticState.driftCheck === "off_track" || (socraticState.driftCheck === "narrow" && !directConceptFocus);
  return (
    explicitRedirect ||
    driftRedirect ||
    (isDerivativeSocraticFocus(socraticState) && !directConceptFocus && userAnswerCountSinceSocraticRedirect(history) >= 2)
  );
}

function userAnswerCountSinceSocraticRedirect(history) {
  let count = 0;
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    if (message.speaker === "socrates" && ["自我理解"].includes(message.role)) break;
    if (message.speaker === "socrates" && textLooksLikeSocraticRedirect(message.text)) break;
    if (message.speaker === "user") count += 1;
  }
  return count;
}

function isDerivativeSocraticFocus(socraticState) {
  if (hasDirectSocraticConceptFocus(socraticState)) return false;
  const state = socraticState || {};
  const focus = safeString(state.focus, 160);
  const original = safeString(state.originalQuestion || state.wholeQuestionReminder, 260);
  if (!focus || !original) return false;
  const focusTerms = importantSocraticTerms(focus);
  if (focusTerms.length === 0) return false;
  const originalTerms = new Set(importantSocraticTerms(original));
  const sharedTerms = focusTerms.filter((term) => originalTerms.has(term));
  return sharedTerms.length === 0;
}

function hasDirectSocraticConceptFocus(socraticState) {
  const state = socraticState || {};
  const focus = safeString(state.focus, 160);
  const original = safeString(state.originalQuestion || state.wholeQuestionReminder, 260);
  if (!focus || !original) return false;
  const focusTerms = new Set(importantSocraticTerms(focus));
  const originalTerms = importantSocraticTerms(original);
  if (originalTerms.some((term) => focusTerms.has(term))) return true;
  const definitionalFocus = /含义|意思|是指|定义|关系|标准|作用/.test(focus);
  if (!definitionalFocus) return false;
  return directSocraticConceptTerms(state).some((term) => {
    if (concreteSocraticExampleTerm(term)) return false;
    return focus.includes(term) || term.includes(focus.replace(/的?(含义|意思|定义|关系|标准|作用).*/, ""));
  });
}

function directSocraticConceptTerms(socraticState) {
  const state = socraticState || {};
  const choice = splitSocraticChoice(state.originalQuestion || state.wholeQuestionReminder || "");
  const values = [
    choice?.left,
    choice?.right,
    ...(state.keyTerms || []),
    ...(state.clarifiedTerms || []),
    ...(state.tensions || []),
  ];
  return [...new Set(values.flatMap((value) => importantSocraticTerms(value)).filter((term) => term.length >= 2))];
}

function concreteSocraticExampleTerm(term) {
  return /项目|工作|例子|动作|场景|职业|任务|事情|细节/.test(term);
}

function isDefinitionChainStale(history) {
  return recentSocraticDefinitionQuestionCount(history) >= 2;
}

function recentSocraticDefinitionQuestionCount(history) {
  let count = 0;
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const message = history[index];
    if (message.speaker === "user") continue;
    if (message.speaker !== "socrates") continue;
    if (textLooksLikeSocraticRedirect(message.text)) break;
    if (!textLooksLikeDefinitionQuestion(message.text)) break;
    count += 1;
  }
  return count;
}

function textLooksLikeDefinitionQuestion(text) {
  return /(是什么|什么是|是指什么|指什么|什么意思|含义|定义)/.test(safeString(text, 260));
}

function importantSocraticTerms(value) {
  const segments = safeString(value, 260).match(/[\u4e00-\u9fffA-Za-z0-9]{2,}/g) || [];
  const stopWords = new Set([
    "是否",
    "什么",
    "一个",
    "一些",
    "怎么",
    "如何",
    "还是",
    "因为",
    "这个",
    "那个",
    "问题",
    "判断",
    "标准",
    "具体",
    "动作",
    "需要",
    "可以",
  ]);
  const terms = new Set();
  for (const segment of segments) {
    const trimmed = segment.trim();
    if (trimmed.length <= 4 && !stopWords.has(trimmed)) terms.add(trimmed);
    for (let index = 0; index <= trimmed.length - 2; index += 1) {
      const term = trimmed.slice(index, index + 2);
      if (!stopWords.has(term)) terms.add(term);
    }
  }
  return [...terms];
}

function textLooksLikeSocraticRedirect(text) {
  const value = safeString(text, 260);
  return /分界线|更接近.+还是|更像.+还是|最初在问/.test(value);
}

function sanitizeSocraticRole(value) {
  const role = safeString(value, 30);
  const allowedRoles = new Set(["追问", "概念澄清", "前提追问", "温和反诘", "小结", "例子追问", "临时判断", "自我理解"]);
  return allowedRoles.has(role) ? role : "追问";
}

function enforceSocraticDriftText(text, context) {
  if (!text) return "";
  const driftCheck = context?.socraticState?.driftCheck;
  const reminder = safeString(context?.socraticState?.wholeQuestionReminder, 180);
  if (!["narrow", "off_track"].includes(driftCheck) || !reminder) return text;
  if (hasDirectSocraticConceptFocus(context?.socraticState)) return text;
  if (text.includes(reminder) || reminder.includes(text)) return text;
  return safeString(`如果放回「${reminder}」里看，${text}`, 520);
}

function enforceSocraticRedirectText(text, context) {
  const state = context?.socraticState || {};
  const reminder = stripSentenceEnd(toSecondPersonSocraticLine(state.wholeQuestionReminder || context?.question, 180)) || "原问题仍需要被整体看见";
  const focus = stripSentenceEnd(toSecondPersonSocraticLine(state.focus, 120)) || "刚才这一点";
  return safeString(buildSocraticRedirectQuestion(context, reminder, focus), 520);
}

function buildSocraticRedirectQuestion(context, reminder, focus) {
  if (shouldAskForSocraticDefinitionRevision(context)) {
    return buildSocraticDefinitionRevisionQuestion(context, reminder, focus);
  }
  const choice = splitSocraticChoice(reminder);
  if (choice) {
    return `那「${focus}」更像是在支持「${choice.left}」，还是支持「${choice.right}」？决定它的关键细节是什么？`;
  }
  return `那「${focus}」和你最初在问的「${reminder}」之间，哪一步关系最需要分清？`;
}

function shouldAskForSocraticDefinitionRevision(context) {
  const state = context?.socraticState || {};
  const material = [
    state.focus,
    state.currentUnderstanding,
    ...(state.clarifiedTerms || []),
    ...(state.userClaims || []),
    ...(state.assumptions || []),
    ...(state.tensions || []),
  ].join(" ");
  return /区分|区别|标准|界限|不违背|背离|自然状态|内在|攀比|强迫|刻意/.test(material);
}

function buildSocraticDefinitionRevisionQuestion(context, reminder, focus) {
  const state = context?.socraticState || {};
  const choice = splitSocraticChoice(reminder);
  const standard = normalizeSocraticDefinitionStandard(extractSocraticDefinitionStandard(state) || focus);
  if (choice) {
    return `所以你是不是在重新理解「${choice.left}」：它不是完全不行动，而是「${standard}」？那「${choice.right}」和它的真正分界在哪里？`;
  }
  return `所以你是不是在重新理解原问题：关键不在「${focus}」本身，而在「${standard}」这个标准是否成立？`;
}

function extractSocraticDefinitionStandard(state) {
  const candidates = [
    ...(state.userClaims || []),
    ...(state.clarifiedTerms || []),
    ...(state.assumptions || []),
    state.focus,
    ...(state.tensions || []),
  ].map((value) => stripSentenceEnd(toSecondPersonSocraticLine(value, 120)));
  return (
    candidates.find((value) => /争取但不违背|不违背自然状态|违背自然状态|背离自己|攀比|强迫|刻意/.test(value)) ||
    candidates.find((value) => /区分|区别|标准|界限/.test(value)) ||
    ""
  );
}

function normalizeSocraticDefinitionStandard(value) {
  return stripSentenceEnd(toSecondPersonSocraticLine(value, 120))
    .replace(/^.+?[：:]\s*/, "")
    .replace(/可以是(无为|有为)$/g, "")
    .replace(/仍可算(无为|有为)$/g, "")
    .replace(/可能代表(无为|有为)$/g, "")
    .replace(/^(用户认为|你认为|你开始理解为|你暂时理解为)/, "")
    .replace(/^主动争取但/, "争取但")
    .trim();
}

function buildSocraticTempoShiftQuestion(context) {
  const state = context?.socraticState || {};
  const reminder = stripSentenceEnd(toSecondPersonSocraticLine(state.wholeQuestionReminder || context?.question, 180)) || "原问题";
  const focus = stripSentenceEnd(toSecondPersonSocraticLine(state.focus, 100)) || "刚才这个判断";
  const choice = splitSocraticChoice(reminder);
  if (choice) {
    return safeString(
      `换个方式问：在一个具体处境里，什么会让「${focus}」仍然属于「${choice.left}」，什么又会让它变成「${choice.right}」？`,
      520
    );
  }
  return safeString(`换个方式问：你能不能举一个具体处境，让「${focus}」真正影响你的选择？`, 520);
}

function splitSocraticChoice(value) {
  const text = stripSentenceEnd(safeString(value, 180).replace(/[？?]/g, ""));
  const match = text.match(/(.+?)(?:还是|或是|或者)(.+)/);
  if (!match) return null;
  const left = cleanSocraticChoicePart(match[1]);
  const right = cleanSocraticChoicePart(match[2]);
  return left && right ? { left, right } : null;
}

function cleanSocraticChoicePart(value) {
  return safeString(value, 80)
    .replace(/^(你|我|我们|到底|究竟|应该|应当|要不要|能不能|是否|是不是|该不该)/, "")
    .replace(/[，,。；;：:]+$/g, "")
    .trim();
}

function toSecondPersonSocraticLine(value, maxLength) {
  return safeString(value, maxLength).replaceAll("用户", "你");
}

function stripSentenceEnd(value) {
  return safeString(value, 220).replace(/[。！？!?]+$/g, "");
}

function enforceSocraticSecondPersonText(text, context, role) {
  if (!text || context?.userIntent !== "synthesize_self_understanding" || role !== "自我理解") return text;
  return text
    .replaceAll("目前我更清楚地看到", "目前你更清楚地看到")
    .replaceAll("我真正", "你真正")
    .replaceAll("我如何", "你如何")
    .replaceAll("我在乎", "你在乎")
    .replaceAll("我可能", "你可能")
    .replaceAll("我已经", "你已经")
    .replaceAll("我还", "你还")
    .replaceAll("我需要", "你需要")
    .replaceAll("我也", "你也")
    .replaceAll("我愿意", "你愿意");
}

function sanitizeSocraticStage(value) {
  const stage = safeString(value, 40);
  const allowedStages = new Set([
    "starting",
    "clarifying_terms",
    "testing_assumptions",
    "finding_tension",
    "summarizing",
  ]);
  return allowedStages.has(stage) ? stage : "clarifying_terms";
}

function sanitizeSocraticState(value) {
  const state = value && typeof value === "object" ? value : {};
  const driftCheck = safeString(state.driftCheck, 30);
  const allowedDriftChecks = new Set(["none", "narrow", "off_track"]);
  return {
    originalQuestion: safeString(state.originalQuestion, 220),
    currentUnderstanding: safeString(state.currentUnderstanding, 260),
    keyTerms: safeStringArray(state.keyTerms, 6, 40),
    clarifiedTerms: safeStringArray(state.clarifiedTerms, 6, 120),
    userClaims: safeStringArray(state.userClaims, 6, 140),
    assumptions: safeStringArray(state.assumptions, 6, 140),
    tensions: safeStringArray(state.tensions, 5, 140),
    openQuestions: safeStringArray(state.openQuestions, 5, 140),
    focus: safeString(state.focus, 120),
    wholeQuestionReminder: safeString(state.wholeQuestionReminder, 180),
    driftCheck: allowedDriftChecks.has(driftCheck) ? driftCheck : "none",
    stage: sanitizeSocraticStage(state.stage),
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

function sanitizeDebateVoiceGuardrails(value) {
  if (!value || typeof value !== "object") return {};
  const mustDo = safeStringArray(value.mustDo, 4, 110);
  const mustAvoid = safeStringArray(value.mustAvoid, 4, 110);
  const guardrails = {
    style: safeString(value.style, 180),
    mustDo,
    mustAvoid,
  };
  return guardrails.style || mustDo.length || mustAvoid.length ? guardrails : {};
}

function sanitizeDebateContext(body) {
  const participants = Array.isArray(body.participants)
    ? body.participants
        .map(sanitizeDebateParticipant)
        .filter((person) => person.id && person.name)
        .slice(0, 2)
    : [];
  if (participants.length !== 2) {
    throw new Error("Debate requires exactly two participants.");
  }
  const participantIds = new Set(participants.map((person) => person.id));
  const requestedSpeakerId = safeString(body.currentSpeakerId, 40);
  const currentSpeakerId = participantIds.has(requestedSpeakerId) ? requestedSpeakerId : participants[0].id;
  return {
    participants,
    currentSpeakerId,
    angle: sanitizeDebateAngle(body.angle),
    intervention: safeString(body.intervention, 500),
    pairRelations: Array.isArray(body.pairRelations)
      ? body.pairRelations
          .map((relation) => ({
            source: safeString(relation.source, 40),
            target: safeString(relation.target, 40),
            sourceName: safeString(relation.sourceName, 40),
            targetName: safeString(relation.targetName, 40),
            type: safeString(relation.type, 30),
            weight: clampNumber(Number(relation.weight), 0, 1),
            reason: safeString(relation.reason, 260),
          }))
          .filter((relation) => participantIds.has(relation.source) && participantIds.has(relation.target))
          .slice(0, 8)
      : [],
    stanceDifferences: Array.isArray(body.stanceDifferences)
      ? body.stanceDifferences
          .map((axis) => ({
            dimensionId: safeString(axis.dimensionId, 40),
            label: safeString(axis.label, 80),
            firstPosition: safeString(axis.firstPosition, 60),
            secondPosition: safeString(axis.secondPosition, 60),
            gap: clampNumber(Number(axis.gap), 0, 2),
          }))
          .filter((axis) => axis.label)
          .slice(0, 5)
      : [],
    recentConversation: Array.isArray(body.recentConversation)
      ? body.recentConversation
          .map((message) => ({
            speakerId: safeString(message.speakerId, 40),
            speaker: safeString(message.speaker, 40),
            role: safeString(message.role, 30),
            text: safeString(message.text, 420),
          }))
          .slice(-10)
      : [],
  };
}

function sanitizeDebateParticipant(person) {
  return {
    id: safeString(person.id, 40),
    name: safeString(person.name, 40),
    tradition: safeString(person.tradition, 80),
    coreConcepts: safeStringArray(person.coreConcepts, 8, 40),
    topics: safeStringArray(person.topics, 10, 30),
    stance: typeof person.stance === "object" && person.stance ? person.stance : {},
    voice: safeString(person.voice, 220),
    speechPersona: sanitizeSpeechPersona(person.speechPersona),
    exampleStyle: sanitizeExampleStyle(person.exampleStyle),
    debateVoiceGuardrails: sanitizeDebateVoiceGuardrails(person.debateVoiceGuardrails),
    summary: safeString(person.summary, 320),
    questionHooks: safeStringArray(person.questionHooks, 6, 120),
  };
}

function sanitizeDebateAngles(value) {
  const rawAngles = Array.isArray(value?.angles) ? value.angles : Array.isArray(value) ? value : [];
  return rawAngles
    .map((angle, index) => sanitizeDebateAngle({ ...angle, id: angle?.id || `angle-${index + 1}` }))
    .filter((angle) => angle.title && angle.focus)
    .slice(0, 3);
}

function sanitizeDebateAngle(value) {
  const angle = value && typeof value === "object" ? value : {};
  return {
    id: safeString(angle.id, 40),
    title: safeString(angle.title, 60),
    focus: safeString(angle.focus, 220),
    reason: safeString(angle.reason, 260),
    openingQuestion: safeString(angle.openingQuestion, 180),
  };
}

function sanitizeDebateMessage(value, context) {
  const raw = value && typeof value === "object" ? value : {};
  const speakerId = safeString(raw.speakerId, 40);
  const allowedId = context.participants.some((person) => person.id === speakerId) ? speakerId : context.currentSpeakerId;
  return {
    speakerId: allowedId,
    role: safeString(raw.role, 18) || "回应",
    text: safeString(raw.text, 900),
  };
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

async function fetchWithTimeout(url, options = {}, timeoutMs = 30_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

function isAbortError(error) {
  return error?.name === "AbortError" || error?.code === "ABORT_ERR";
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
  const model = normalizeDeepSeekModel(value);
  return /^deepseek-[a-z0-9._-]+$/i.test(model) ? model : DEFAULT_ANALYSIS_MODEL;
}

function normalizeDeepSeekModel(value) {
  const model = safeString(value, 120).replace(/^deepseek\//, "");
  return model || "deepseek-v4-pro";
}

function clampNumber(value, min, max) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(min, Math.min(max, value));
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function getDeepSeekKey() {
  return process.env.DEEPSEEK_API_KEY || "";
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

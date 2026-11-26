const maxCallsPerRound = 20;
const retainedRounds = 6;

function toolMessage(call, result, limit) {
  let content = JSON.stringify(result ?? null);
  if (content.length > limit) {
    if (typeof result?.text === "string") {
      const { text, ...metadata } = result;
      content = JSON.stringify({ ...metadata, text: text.slice(0, limit - 500), clipped: true });
    } else {
      content = JSON.stringify({ excerpt: content.slice(0, limit - 100), clipped: true });
    }
  }
  return { role: "tool", tool_call_id: call.id, content };
}

function upstream(initialMessages, rounds, facts) {
  const messages = [...initialMessages];
  if (facts) messages.push({ role: "user", content: "Recorded progress for this job: " + facts });
  for (const [i, round] of rounds.entries()) {
    const latest = i === rounds.length - 1;
    messages.push(round.assistant, ...round.outputs.map(({ call, result }) => toolMessage(call, result, latest ? round.limit : 850)));
    if (latest && round.images.length) {
      messages.push({
        role: "user",
        content: [{ type: "text", text: "Review these screenshots in capture order." }, ...round.images],
      });
    }
  }
  return messages;
}

function usableCalls(message) {
  const calls = message?.tool_calls;
  if (!Array.isArray(calls) || !calls.length) return [];
  const ids = new Set();
  for (const call of calls) {
    if (typeof call?.id !== "string" || !call.id || ids.has(call.id)
      || call.type !== "function" || typeof call.function?.name !== "string"
      || typeof call.function.arguments !== "string") return [];
    ids.add(call.id);
  }
  return calls;
}

export async function runWorker({
  initialMessages, tools, chat, model: requested, signal,
  progress = async () => {}, getProgress = () => "", redact = String, roundLimit = 20,
}) {
  const automatic = !requested || requested === "auto";
  let model = automatic ? "deepseek" : requested;
  const specs = Object.values(tools).map((tool) => tool.specification);
  const usage = { calls: 0, prompt_tokens: 0, completion_tokens: 0 };
  const fail = (reason, message) => ({
    model, finish: null, failure: { reason, message: redact(message).slice(0, 380) }, usage,
  });
  let history = [];
  let lastError = "";
  let repeating = 0;
  const notify = async (round) => { try { await progress(round, model); } catch { /* optional telemetry */ } };

  for (let round = 0; round < roundLimit; ) {
    if (signal.aborted) {
      return fail(signal.reason?.name === "TimeoutError" ? "job_timeout" : "cancelled", "Flash job interrupted.");
    }
    const messages = upstream(initialMessages, history, redact(getProgress()).slice(0, 1000));
    let reply;
    let calls;
    try {
      usage.calls++;
      reply = await chat(model, messages, specs, signal);
      usage.prompt_tokens += Number(reply.usage?.prompt_tokens) || 0;
      usage.completion_tokens += Number(reply.usage?.completion_tokens) || 0;
      calls = usableCalls(reply.message);
      if (!calls.length) {
        const error = new Error("Flash returned no usable tool calls (" + (reply.reason ?? "unknown") + ").");
        error.code = "no_tool_calls";
        throw error;
      }
    } catch (error) {
      if (signal.aborted) {
        return fail(signal.reason?.name === "TimeoutError" ? "job_timeout" : "cancelled", "Flash job interrupted.");
      }
      if (automatic && model === "deepseek") {
        model = "glm";
        history = [];
        await notify(round);
        continue;
      }
      return fail(error.code ?? (error.name === "TimeoutError" ? "model_timeout" : "provider_failure"), error.message);
    } finally {
      if (history.length) history.at(-1).images = [];
    }
    round++;
    if (calls.length > maxCallsPerRound) return fail("too_many_calls", "Flash requested too many tools in one round.");
    const assistant = {
      role: "assistant", content: reply.message.content ?? null, tool_calls: calls,
      ...(typeof reply.message.reasoning_content === "string" ? { reasoning_content: reply.message.reasoning_content } : {}),
    };
    const outputs = [];
    const images = [];
    const groupedFinish = calls.length !== 1 && calls.some((call) => call.function.name === "finish");
    for (const call of calls) {
      if (signal.aborted) {
        return fail(signal.reason?.name === "TimeoutError" ? "job_timeout" : "cancelled", "Flash stopped before the next action.");
      }
      const name = call.function.name;
      let result;
      try {
        if (groupedFinish) throw new Error("Call finish alone once the other actions have returned.");
        const tool = Object.hasOwn(tools, name) ? tools[name] : null;
        if (!tool) throw new Error("Unknown Flash tool: " + name);
        const args = tool.schema.parse(JSON.parse(call.function.arguments));
        const data = await tool.run(args);
        if (name === "finish") {
          await notify(round);
          return { model, finish: data, failure: null, usage };
        }
        if (name === "capture_screenshot") {
          images.push({ type: "image_url", image_url: { url: "data:" + data.image.mime + ";base64," + data.image.bytes.toString("base64") } });
          result = data.evidence;
        } else {
          result = data;
        }
      } catch (error) {
        result = { error: redact(error.message).slice(0, 380) };
      }
      outputs.push({ call, result });
    }
    const errors = outputs.every(({ result }) => result?.error)
      ? JSON.stringify(outputs.map(({ call, result }) => [call.function.name, result.error])) : "";
    repeating = errors && errors === lastError ? repeating + 1 : 0;
    lastError = errors;
    if (repeating >= 2) return fail("stalled", "Flash repeated the same unsuccessful actions.");
    history.push({ assistant, outputs, images, limit: Math.min(18000, Math.floor(32000 / calls.length)) });
    if (history.length > retainedRounds) history.shift();
    if (round === 1 || round % 2 === 0) await notify(round);
  }
  return fail("rounds_exhausted", "Flash reached its tool-round limit. Continue using this job ID.");
}

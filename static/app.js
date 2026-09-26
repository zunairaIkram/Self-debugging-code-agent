const thread = document.getElementById("thread");
const composer = document.getElementById("composer");
const promptEl = document.getElementById("prompt");
const sendBtn = document.getElementById("send");
const statusPill = document.getElementById("statusPill");
const statusLabel = document.getElementById("statusLabel");
const pipeline = document.getElementById("pipeline");

const STAGE_LABELS = {
  planning: "Planning",
  plan_ready: "Planning",
  critiquing: "Critiquing",
  replanning: "Replanning",
  plan_approved: "Plan approved",
  generating_code: "Generating code",
  calling_tool: "Calling tool",
  tests_complete: "Tests",
  done: "Final answer",
  error: "Error",
};

const PIPELINE_ORDER = [
  "planning",
  "critiquing",
  "replanning",
  "generating_code",
  "calling_tool",
  "tests_complete",
  "done",
];

const WELCOME = `Drop a single-function coding problem in the box.

The agent will:
1. Draft pseudocode and tests
2. Critique / replan if needed
3. Generate code
4. Call test_code until cases pass
5. Return the final function here`;

seedWelcome();

document.getElementById("chips").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-prompt]");
  if (!button) return;
  promptEl.value = button.dataset.prompt;
  promptEl.focus();
});

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const prompt = promptEl.value.trim();
  if (!prompt || sendBtn.disabled) return;
  promptEl.value = "";
  await runPrompt(prompt);
});

function seedWelcome() {
  appendBubble("agent", WELCOME);
  setStatus("idle", "Idle");
}

async function runPrompt(prompt) {
  appendBubble("user", prompt);
  setBusy(true);
  resetPipeline();
  setStatus("running", "Planning");
  appendStatus("Connecting to the agent…");

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({ error: response.statusText }));
      throw new Error(err.error || "Request failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk
          .split("\n")
          .filter((part) => part.startsWith("data:"))
          .map((part) => part.slice(5).trim())
          .join("");
        if (!line) continue;
        const event = JSON.parse(line);
        handleEvent(event);
      }
    }
  } catch (error) {
    setPipeline("error", true);
    setStatus("error", "Error");
    appendStatus(error.message);
    appendBubble("agent", error.message);
  } finally {
    setBusy(false);
  }
}

function handleEvent(event) {
  if (event.stage === "closed") return;

  const label = STAGE_LABELS[event.stage] || event.stage;
  setStatus(event.stage === "error" ? "error" : event.stage === "done" ? "done" : "running", label);
  setPipeline(event.stage);

  if (event.message) {
    appendStatus(event.message);
  }

  if (event.stage === "plan_ready" && event.plan) {
    appendPlan(event.plan);
  }

  if (event.stage === "replanning" && event.flaws?.length) {
    appendBubble("agent", `Critic flaws:\n${event.flaws.map((flaw) => `• ${flaw}`).join("\n")}`);
  }

  if (event.stage === "tests_complete" && event.tests) {
    appendTests(event.tests);
  }

  if ((event.stage === "done" || event.stage === "error") && event.result) {
    appendBubble("agent", event.result, { final: event.stage === "done" });
    if (event.stage === "done") setPipeline("done");
  }
}

function setBusy(busy) {
  sendBtn.disabled = busy;
  promptEl.disabled = busy;
}

function setStatus(state, label) {
  statusPill.dataset.state = state;
  statusLabel.textContent = label;
}

function resetPipeline() {
  for (const item of pipeline.querySelectorAll("li")) {
    item.classList.remove("active", "done", "error");
  }
}

function setPipeline(stage, isError = false) {
  const mapped =
    stage === "plan_ready" || stage === "plan_approved"
      ? "planning"
      : stage;
  const current = pipeline.querySelector(`[data-stage="${mapped}"]`);
  if (!current) return;

  if (isError || stage === "error") {
    current.classList.add("error");
    current.classList.remove("active");
    return;
  }

  const index = PIPELINE_ORDER.indexOf(mapped);
  pipeline.querySelectorAll("li").forEach((item) => {
    const itemStage = item.dataset.stage;
    const itemIndex = PIPELINE_ORDER.indexOf(itemStage);
    item.classList.remove("active", "error");
    if (itemIndex < index) item.classList.add("done");
    else item.classList.remove("done");
  });
  current.classList.add("active");
  if (stage === "done") {
    current.classList.remove("active");
    current.classList.add("done");
  }
}

function appendBubble(who, text, options = {}) {
  const bubble = document.createElement("article");
  bubble.className = `bubble ${who}`;
  const label = document.createElement("div");
  label.className = "who";
  label.textContent = who === "user" ? "You" : "Agent";
  const body = document.createElement("div");
  body.className = "body";
  renderBody(body, text, options.final);
  bubble.append(label, body);
  thread.append(bubble);
  thread.scrollTop = thread.scrollHeight;
  return bubble;
}

function appendStatus(text) {
  const bubble = document.createElement("div");
  bubble.className = "bubble status";
  bubble.textContent = text;
  thread.append(bubble);
  thread.scrollTop = thread.scrollHeight;
  return bubble;
}

function appendPlan(plan) {
  const bubble = appendBubble(
    "agent",
    `Approved-path plan for \`${plan.function_name || "function"}\`.`
  );
  const card = document.createElement("div");
  card.className = "plan-card";
  const tests = (plan.testCases || [])
    .map((test, index) => `${index + 1}. ${JSON.stringify(test.args)} → ${JSON.stringify(test.expected)}`)
    .join("\n");
  card.innerHTML = `<div>Pseudocode</div>`;
  const pre = document.createElement("pre");
  pre.textContent = plan.pseudocode || "";
  const testsEl = document.createElement("pre");
  testsEl.textContent = tests || "No test cases";
  card.append(pre, document.createTextNode("Test cases"), testsEl);
  bubble.append(card);
}

function appendTests(tests) {
  const bubble = appendBubble("agent", tests.all_passed ? "All test cases passed." : "Some tests failed. The agent will retry.");
  const card = document.createElement("div");
  card.className = "test-card";
  if (tests.error) {
    const err = document.createElement("div");
    err.className = "fail";
    err.textContent = tests.error;
    card.append(err);
  }
  for (const result of tests.results || []) {
    const row = document.createElement("div");
    row.className = "test-row";
    const left = document.createElement("span");
    left.textContent = `${JSON.stringify(result.args)} → ${JSON.stringify(result.actual)}`;
    const right = document.createElement("span");
    right.className = result.passed ? "pass" : "fail";
    right.textContent = result.passed ? "PASS" : "FAIL";
    row.append(left, right);
    card.append(row);
  }
  bubble.append(card);
}

function renderBody(target, text, isFinal) {
  const fenced = /```(?:\w+)?\n([\s\S]*?)```/g;
  let last = 0;
  let match;
  let found = false;
  while ((match = fenced.exec(text))) {
    found = true;
    if (match.index > last) {
      const p = document.createElement("div");
      p.textContent = text.slice(last, match.index).trim();
      if (p.textContent) target.append(p);
    }
    const code = document.createElement("pre");
    code.className = "code-block";
    code.textContent = match[1].trimEnd();
    target.append(code);
    last = match.index + match[0].length;
  }
  const rest = text.slice(last).trim();
  if (!found) {
    if (isFinal && looksLikeCode(text)) {
      const code = document.createElement("pre");
      code.className = "code-block";
      code.textContent = text;
      target.append(code);
      return;
    }
    target.textContent = text;
    return;
  }
  if (rest) {
    const p = document.createElement("div");
    p.textContent = rest;
    target.append(p);
  }
}

function looksLikeCode(text) {
  return /^(def |class |import |from )/m.test(text);
}

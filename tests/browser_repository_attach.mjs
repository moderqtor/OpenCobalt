import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const chrome = process.env.OPENCOBALT_CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const python = process.env.OPENCOBALT_PYTHON || path.join(root, ".venv", "bin", "python");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "opencobalt-browser-attach-"));
const alternateRepo = path.join(temp, "alternate-repository");
fs.mkdirSync(path.join(alternateRepo, ".git"), { recursive: true });

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function unusedPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function waitFor(description, operation, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = await operation();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ""}`);
}

async function stop(child) {
  if (!child || child.exitCode != null) return;
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGTERM");
  const stopped = await Promise.race([
    exited.then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 3_000)),
  ]);
  if (!stopped && child.exitCode == null) {
    child.kill("SIGKILL");
    await exited;
  }
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result || {});
    });
  }

  send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
}

let apiProcess;
let viteProcess;
let chromeProcess;
let socket;

try {
  assert(fs.existsSync(chrome), `Chrome not found at ${chrome}`);
  assert(fs.existsSync(python), `Python not found at ${python}`);
  const [apiPort, uiPort, debugPort] = await Promise.all([unusedPort(), unusedPort(), unusedPort()]);
  const env = {
    ...process.env,
    OPENCOBALT_ENABLE_DEVELOPMENT_MOCK: "1",
    PYTHONPATH: [path.join(root, "src"), process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
  };
  apiProcess = spawn(python, ["-m", "uvicorn", "opencobalt.api_server:app", "--host", "127.0.0.1", "--port", String(apiPort), "--log-level", "warning"], {
    cwd: temp,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  viteProcess = spawn("npm", ["run", "dev", "--", "--host", "127.0.0.1", "--port", String(uiPort)], {
    cwd: path.join(root, "ui"),
    env: { ...env, OPENCOBALT_API_ORIGIN: `http://127.0.0.1:${apiPort}` },
    stdio: ["ignore", "pipe", "pipe"],
  });
  await waitFor("the UI server", async () => (await fetch(`http://127.0.0.1:${uiPort}`)).ok);

  chromeProcess = spawn(chrome, [
    "--headless=new",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    `--remote-debugging-port=${debugPort}`,
    `--user-data-dir=${path.join(temp, "chrome-profile")}`,
    "about:blank",
  ], { stdio: ["ignore", "pipe", "pipe"] });
  const version = await waitFor("Chrome DevTools", async () => {
    const response = await fetch(`http://127.0.0.1:${debugPort}/json/version`);
    return response.ok ? response.json() : null;
  });
  socket = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  const cdp = new CdpClient(socket);
  const target = await cdp.send("Target.createTarget", { url: `http://127.0.0.1:${uiPort}/#chat` });
  const attached = await cdp.send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
  const session = attached.sessionId;
  await cdp.send("Runtime.enable", {}, session);
  await cdp.send("Page.enable", {}, session);

  async function evaluate(expression) {
    const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, session);
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
    return result.result?.value;
  }

  async function browserWait(description, expression) {
    return waitFor(description, () => evaluate(expression));
  }

  async function setInput(selector, value) {
    const encodedSelector = JSON.stringify(selector);
    const encodedValue = JSON.stringify(value);
    const changed = await evaluate(`(() => {
      const input = document.querySelector(${encodedSelector});
      if (!input) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(input, ${encodedValue});
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    assert(changed, `Input not found: ${selector}`);
  }

  async function clickButton(text, scope = "document") {
    const clicked = await evaluate(`(() => {
      const root = ${scope};
      const button = [...root.querySelectorAll("button")].find((node) => node.textContent.trim() === ${JSON.stringify(text)});
      if (!button) return false;
      button.click();
      return true;
    })()`);
    assert(clicked, `Button not found: ${text}`);
  }

  await browserWait("Chat workspace", `document.querySelector(".chat-layout") !== null`);
  const newClicked = await evaluate(`(() => { const button = document.querySelector('button[aria-label="New conversation"]'); if (!button) return false; button.click(); return true; })()`);
  assert(newClicked, "New conversation button was not available");
  await clickButton("Controls");
  await browserWait("draft repository input", `document.querySelector(".repo-compact-form input") !== null`);
  assert(await evaluate(`document.querySelector(".composer form.repo-compact-form") === null`), "Repository controls must not nest a form inside the composer form");
  await setInput(".repo-compact-form input", "~/dev/OpenCobalt");
  const draftBefore = await evaluate(`(async () => ({ href: location.href, selected: document.querySelector('.conversation-item-select[aria-current="true"]')?.textContent || null, count: (await (await fetch('/api/v1/conversations')).json()).length }))()`);
  await clickButton("Attach", `document.querySelector(".repo-compact-form")`);
  const expectedRepository = fs.realpathSync(root);
  await browserWait("canonical draft repository chip", `document.querySelector(".repo-chip")?.title === ${JSON.stringify(expectedRepository)}`);
  if (process.env.OPENCOBALT_BROWSER_SCREENSHOT) {
    const screenshot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false }, session);
    fs.writeFileSync(process.env.OPENCOBALT_BROWSER_SCREENSHOT, Buffer.from(screenshot.data, "base64"));
  }
  const draftAfter = await evaluate(`(async () => ({ href: location.href, selected: document.querySelector('.conversation-item-select[aria-current="true"]')?.textContent || null, count: (await (await fetch('/api/v1/conversations')).json()).length }))()`);
  assert(draftAfter.href === draftBefore.href, "Draft repository attach changed window.location");
  assert(draftAfter.selected === draftBefore.selected, "Draft repository attach changed the selected conversation");
  assert(draftAfter.count === draftBefore.count, "Draft repository attach created a durable conversation");

  const longTitle = "Repository acceptance conversation with a deliberately readable long rail title";
  const created = await evaluate(`(async () => {
    const create = (title) => fetch('/api/v1/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }).then((response) => response.json());
    return { older: await create('Older unrelated conversation'), target: await create(${JSON.stringify(longTitle)}) };
  })()`);
  await evaluate(`location.reload(); true`);
  await browserWait("long conversation in rail", `[...document.querySelectorAll(".conversation-item-select b")].some((node) => node.textContent === ${JSON.stringify(longTitle)})`);
  const titleState = await evaluate(`(() => {
    const button = [...document.querySelectorAll('.conversation-item-select')].find((node) => node.querySelector('b')?.textContent === ${JSON.stringify(longTitle)});
    const title = button?.querySelector('b');
    const style = title ? getComputedStyle(title) : null;
    return { tooltip: button?.title || '', clamp: style?.webkitLineClamp || '', whiteSpace: style?.whiteSpace || '' };
  })()`);
  assert(titleState.tooltip === longTitle, "Rail conversation does not expose the full title");
  assert(titleState.clamp === "2", "Rail conversation title is not clamped to two lines");
  assert(titleState.whiteSpace !== "nowrap", "Rail conversation title is still forced to one line");
  const targetClicked = await evaluate(`(() => { const button = [...document.querySelectorAll('.conversation-item-select')].find((node) => node.querySelector('b')?.textContent === ${JSON.stringify(longTitle)}); if (!button) return false; button.click(); return true; })()`);
  assert(targetClicked, "Target conversation could not be selected");
  await browserWait("target selection", `document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`);
  await clickButton("Controls");
  await browserWait("existing repository input", `document.querySelector(".repo-compact-form input") !== null`);
  await setInput(".repo-compact-form input", "~/dev/OpenCobalt");
  const existingLocation = await evaluate("location.href");
  await clickButton("Attach", `document.querySelector(".repo-compact-form")`);
  await browserWait("existing canonical repository chip", `document.querySelector(".repo-chip")?.title === ${JSON.stringify(expectedRepository)}`);
  assert(await evaluate(`document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`), "Existing attach changed the selected conversation");
  assert(await evaluate("location.href") === existingLocation, "Existing attach changed window.location");
  assert(await evaluate(`fetch('/api/v1/conversations/${created.target.conversation_id}').then((response) => response.json()).then((record) => record.project_path)`) === expectedRepository, "Existing attach was not persisted");

  await evaluate("location.reload(); true");
  await browserWait("attached repository after reload", `document.querySelector(".repo-chip")?.title === ${JSON.stringify(expectedRepository)} && document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`);
  await evaluate(`document.querySelector(".repo-chip").click(); true`);
  await browserWait("repository change input", `document.querySelector(".repo-compact-form input") !== null`);
  await setInput(".repo-compact-form input", alternateRepo);
  await clickButton("Attach", `document.querySelector(".repo-compact-form")`);
  const expectedAlternate = fs.realpathSync(alternateRepo);
  await browserWait("changed repository chip", `document.querySelector(".repo-chip")?.title === ${JSON.stringify(expectedAlternate)}`);
  assert(await evaluate(`document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`), "Repository change changed the selected conversation");
  assert(await evaluate("location.href") === existingLocation, "Repository change changed window.location");

  await evaluate("location.reload(); true");
  await browserWait("changed repository after reload", `document.querySelector(".repo-chip")?.title === ${JSON.stringify(expectedAlternate)} && document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`);
  await clickButton("Controls");
  await browserWait("detach control", `[...document.querySelectorAll("button")].some((node) => node.textContent.trim() === "Detach")`);
  await clickButton("Detach");
  await browserWait("repository detach", `document.querySelector(".repo-chip") === null`);
  assert(await evaluate(`document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`), "Repository detach changed the selected conversation");
  assert(await evaluate("location.href") === existingLocation, "Repository detach changed window.location");
  assert(await evaluate(`fetch('/api/v1/conversations/${created.target.conversation_id}').then((response) => response.json()).then((record) => record.project_path)`) === null, "Repository detach was not persisted");
  await evaluate("location.reload(); true");
  await browserWait("detached repository after reload", `document.querySelector(".repo-chip") === null && document.querySelector('.conversation-item-select[aria-current="true"] b')?.textContent === ${JSON.stringify(longTitle)}`);

  console.log("browser repository regression: draft attach and existing attach/change/detach passed");
} finally {
  try { socket?.close(); } catch { /* best effort */ }
  await Promise.all([stop(chromeProcess), stop(viteProcess), stop(apiProcess)]);
  if (path.dirname(temp) === os.tmpdir() && path.basename(temp).startsWith("opencobalt-browser-attach-")) {
    fs.rmSync(temp, { recursive: true, force: true });
  }
}

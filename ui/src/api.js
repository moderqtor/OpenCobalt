const API_ROOT = "/api/v1";

export class ApiError extends Error {
  constructor(message, { status = 0, detail = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function endpoint(path) {
  return `${API_ROOT}${path.startsWith("/") ? path : `/${path}`}`;
}

function messageFor(response, body) {
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) {
    const details = body.detail.map((item) => item?.msg).filter(Boolean);
    if (details.length) return details.join("; ");
  }
  if (typeof body?.message === "string") return body.message;
  return response.status === 0
    ? "OpenCobalt could not be reached. Start the local app and try again."
    : `Request failed (${response.status}).`;
}

export async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(endpoint(path), {
      ...options,
      headers: { Accept: "application/json", ...options.headers },
    });
  } catch {
    throw new ApiError("OpenCobalt could not be reached. Start the local app and try again.");
  }

  const raw = await response.text();
  let body = null;
  try {
    body = raw ? JSON.parse(raw) : null;
  } catch {
    body = raw || null;
  }
  if (!response.ok) {
    throw new ApiError(messageFor(response, body), { status: response.status, detail: body });
  }
  return body;
}

export function listOf(value, keys = ["items", "data", "results"]) {
  if (Array.isArray(value)) return value;
  for (const key of keys) {
    if (Array.isArray(value?.[key])) return value[key];
  }
  throw new ApiError("OpenCobalt returned an invalid list response.", { detail: value });
}

function recordOf(value, description = "record") {
  if (value && !Array.isArray(value) && typeof value === "object") return value;
  throw new ApiError(`OpenCobalt returned an invalid ${description} response.`, { detail: value });
}

function jsonOptions(method, body) {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

function parseNDJSONLine(line) {
  const payload = line.startsWith("data:") ? line.slice(5).trim() : line.trim();
  if (!payload || payload === "[DONE]") return null;
  let event;
  try {
    event = JSON.parse(payload);
  } catch {
    throw new ApiError("OpenCobalt returned malformed streaming data.", { detail: payload });
  }
  if (!event || Array.isArray(event) || typeof event !== "object" || typeof event.event_type !== "string" || !event.payload || Array.isArray(event.payload) || typeof event.payload !== "object") {
    throw new ApiError("OpenCobalt returned an invalid streaming event.", { detail: event });
  }
  return event;
}

export async function streamChat(payload, onEvent, signal) {
  let response;
  try {
    response = await fetch(endpoint("/chat/stream"), {
      ...jsonOptions("POST", payload),
      headers: { Accept: "application/x-ndjson, application/json", "Content-Type": "application/json" },
      signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError("OpenCobalt could not be reached. Start the local app and try again.");
  }
  if (!response.ok) {
    let body = null;
    try { body = await response.json(); } catch { /* response body is optional */ }
    throw new ApiError(messageFor(response, body), { status: response.status, detail: body });
  }
  if (!response.body) throw new ApiError("OpenCobalt returned no streaming response body.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let eventCount = 0;
  let lastEvent = null;
  try {
    while (true) {
      const { done, value } = await reader.read();
      pending += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = pending.split(/\r?\n/);
      pending = done ? "" : lines.pop() || "";
      for (const line of lines) {
        const event = parseNDJSONLine(line);
        if (event) {
          eventCount += 1;
          lastEvent = event;
          onEvent(event);
        }
      }
      if (done) break;
    }
    const finalEvent = parseNDJSONLine(pending);
    if (finalEvent) {
      eventCount += 1;
      lastEvent = finalEvent;
      onEvent(finalEvent);
    }
  } finally {
    reader.releaseLock();
  }
  return { eventCount, lastEvent };
}

export const api = {
  conversations: () => request("/conversations").then((value) => listOf(value, ["conversations", "items", "data", "results"])),
  createConversation: (input = {}) => request("/conversations", jsonOptions("POST", input)),
  messages: (conversationId) => request(`/conversations/${encodeURIComponent(conversationId)}/messages`).then((value) => listOf(value, ["messages", "items", "data", "results"])),
  routes: () => request("/routes").then((value) => listOf(value, ["routes", "items", "data", "results"])),
  route: (routeId) => request(`/routes/${encodeURIComponent(routeId)}`).then((value) => recordOf(value, "route")),
  rerunRoute: (routeId, input = {}) => request(`/routes/${encodeURIComponent(routeId)}/rerun`, jsonOptions("POST", input)).then((value) => recordOf(value, "route rerun")),
  promoteRoute: (routeId) => request(`/routes/${encodeURIComponent(routeId)}/promote`, jsonOptions("POST")).then((value) => recordOf(value, "route promotion")),
  cancelExecution: (executionId) => request(`/executions/${encodeURIComponent(executionId)}/cancel`, jsonOptions("POST")).then((value) => recordOf(value, "cancellation")),
  personas: () => request("/personas").then((value) => listOf(value, ["personas", "items", "data", "results"])),
  duplicatePersona: (personaId, input) => request(`/personas/${encodeURIComponent(personaId)}/duplicate`, jsonOptions("POST", input)).then((value) => recordOf(value, "persona")),
  updatePersona: (personaId, input) => request(`/personas/${encodeURIComponent(personaId)}`, jsonOptions("PATCH", input)).then((value) => recordOf(value, "persona")),
  testPersona: (personaId, input) => request(`/personas/${encodeURIComponent(personaId)}/test`, jsonOptions("POST", input)).then((value) => recordOf(value, "persona test")),
  resetPersona: (personaId) => request(`/personas/${encodeURIComponent(personaId)}/reset`, jsonOptions("POST")).then((value) => recordOf(value, "persona")),
  providers: () => request("/providers").then((value) => listOf(value, ["providers", "items", "data", "results"])),
  providerHealth: (providerId) => request(`/providers/${encodeURIComponent(providerId)}/health`, jsonOptions("POST")).then((value) => recordOf(value, "provider health")),
  providerModels: (providerId) => request(`/providers/${encodeURIComponent(providerId)}/models`).then((value) => recordOf(value, "provider models")),
  updateProviderPreference: (providerId, input) => request(`/providers/${encodeURIComponent(providerId)}/preference`, jsonOptions("PATCH", input)).then((value) => recordOf(value, "provider preference")),
  memory: () => request("/memory").then((value) => listOf(value, ["memories", "memory", "items", "data", "results"])),
  createMemory: (input) => request("/memory", jsonOptions("POST", input)),
  updateMemory: (memoryId, input) => request(`/memory/${encodeURIComponent(memoryId)}`, jsonOptions("PATCH", input)),
  deleteMemory: (memoryId) => request(`/memory/${encodeURIComponent(memoryId)}`, { method: "DELETE" }),
  missions: () => request("/missions").then((value) => listOf(value, ["missions", "items", "data", "results"])),
  skills: () => request("/skills").then((value) => listOf(value, ["skills", "items", "data", "results"])),
  skill: (skillId) => request(`/skills/${encodeURIComponent(skillId)}`).then((value) => recordOf(value, "skill")),
  updateSkill: (skillId, input) => request(`/skills/${encodeURIComponent(skillId)}`, jsonOptions("PATCH", input)).then((value) => recordOf(value, "skill")),
  previewSkillImport: (sourcePath) => request("/skills/import/preview", jsonOptions("POST", { source_path: sourcePath })).then((value) => recordOf(value, "skill import preview")),
  installSkillImport: (previewId, approvalRequestId) => request("/skills/import/install", jsonOptions("POST", { preview_id: previewId, ...(approvalRequestId ? { approval_request_id: approvalRequestId } : {}) })).then((value) => recordOf(value, "installed skill")),
  approveSkillAction: (approvalRequestId, reason) => request(`/skills/approvals/${encodeURIComponent(approvalRequestId)}/approve`, jsonOptions("POST", { reason })).then((value) => recordOf(value, "skill approval")),
  requestSkillVersionAction: (skillId, skillVersionId, action) => request(`/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(skillVersionId)}/actions`, jsonOptions("POST", { action })).then((value) => recordOf(value, "skill version approval request")),
  rollbackSkillVersion: (skillId, skillVersionId, approvalRequestId) => request(`/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(skillVersionId)}/rollback`, jsonOptions("POST", { approval_request_id: approvalRequestId })).then((value) => recordOf(value, "skill rollback")),
  removeSkillVersion: (skillId, skillVersionId, approvalRequestId) => request(`/skills/${encodeURIComponent(skillId)}/versions/${encodeURIComponent(skillVersionId)}/remove`, jsonOptions("POST", { approval_request_id: approvalRequestId })).then((value) => recordOf(value, "skill removal")),
  receipts: () => request("/ledger/receipts").then((value) => listOf(value, ["receipts", "items", "data", "results"])),
  compareMessages: (firstMessageId, secondMessageId) => request("/messages/compare", jsonOptions("POST", { first_message_id: firstMessageId, second_message_id: secondMessageId })).then((value) => listOf(value, ["responses", "comparisons", "items", "data", "results"])),
  settings: () => request("/settings").then((value) => recordOf(value, "settings")),
  updateSettings: (input) => request("/settings", jsonOptions("PUT", input)).then((value) => recordOf(value, "settings")),
  exportData: () => request("/data/export").then((value) => recordOf(value, "data export")),
  retention: () => request("/data/retention").then((value) => recordOf(value, "retention")),
};

export function eventType(event) {
  return event?.event_type || "event";
}

export function eventPayload(event) {
  return event?.payload && typeof event.payload === "object" ? event.payload : {};
}

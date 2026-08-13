import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ArrowRight, Check, ChevronDown, CircleStop, Loader2, MessageSquareText,
  PanelRightOpen, RefreshCw, Save, Send, SlidersHorizontal,
} from "lucide-react";
import { ApiError, api, eventPayload, eventType, streamChat } from "./api";
import Markdown from "./Markdown";
import SkillImport from "./SkillImport";
import {
  ConversationRail, EmptyState, ErrorState, IconButton, Loading, Navigation,
  PageTitle, Pill, RouteInspector, RouteSpine,
} from "./components";

const NAV_IDS = new Set(["chat", "routes", "missions", "skills", "memory", "ledger", "providers", "settings"]);
const DEFAULT_SETTINGS = {
  default_routing_mode: "automatic",
  default_persona_id: "analytical",
  local_only_default: false,
  privacy_policy: "standard",
  theme: "system",
  cost_ceiling_category: "standard",
  approval_policy: "ask_for_risk",
  skill_permissions: "ask",
  provider_priority: [],
  memory_behavior: "propose",
  verification_preference: "task_appropriate",
};
const TERMINAL_EVENTS = new Set(["completed", "cancelled", "error", "route_failed"]);
const ERROR_EVENTS = new Set(["error", "route_failed"]);
const COGNITIVE_POLICIES = ["fast_answer", "deep_analysis", "skeptical_review", "creative_divergence", "decision_support", "emotional_reflection", "implementation", "research_synthesis", "research"];
const CONTROL_LEVELS = ["very_low", "low", "balanced", "high", "very_high"];
const PERSONA_CONTROLS = ["directness", "warmth", "formality", "verbosity", "challenge_level", "emotional_attunement", "speculation_tolerance", "question_frequency", "citation_preference", "uncertainty_explicitness"];

function initialPage() {
  const page = window.location.hash.replace("#", "");
  return NAV_IDS.has(page) ? page : "chat";
}

const conversationIdOf = (record) => record?.conversation_id || record?.id;
const messageIdOf = (record) => record?.message_id || record?.id;
const routeIdOf = (record) => record?.route_id || record?.id;
const missionIdOf = (record) => record?.mission_id || record?.id;
const skillIdOf = (record) => record?.skill_id || record?.id;
const memoryIdOf = (record) => record?.memory_id || record?.id;
const receiptIdOf = (record) => record?.receipt_id || record?.id;

function label(value) {
  return String(value || "—").replaceAll("_", " ");
}

function relativeTime(value) {
  if (!value) return "local";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "recorded";
  const seconds = Math.round((date.valueOf() - Date.now()) / 1000);
  const unit = Math.abs(seconds) < 60
    ? [seconds, "second"]
    : Math.abs(seconds) < 3600
      ? [Math.round(seconds / 60), "minute"]
      : [Math.round(seconds / 3600), "hour"];
  return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(unit[0], unit[1]);
}

function errorMessage(payload, fallback = "The route did not complete.") {
  return payload?.error?.message || payload?.message || fallback;
}

function routeFromDetail(detail) {
  if (!detail?.route) return detail;
  return {
    ...detail.route,
    actual_provider_id: detail.actual_provider || detail.route.actual_provider_id,
    actual_model_id: detail.actual_model || detail.route.actual_model_id,
    verification: detail.verification || detail.route.verification,
    receipt_id: detail.receipt_id || detail.route.receipt_id,
    executions: detail.executions || detail.route.executions,
    stream_events: detail.stream_events || detail.route.stream_events,
    request_message: detail.request_message || detail.route.request_message,
  };
}

function useLoad(loader) {
  const requestRef = useRef(0);
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const reload = useCallback(async () => {
    const requestId = ++requestRef.current;
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const data = await loader();
      if (requestRef.current === requestId) setState({ loading: false, error: null, data });
      return data;
    } catch (error) {
      if (requestRef.current === requestId) setState({ loading: false, error, data: null });
      throw error;
    }
  }, [loader]);
  useEffect(() => {
    reload().catch(() => undefined);
    return () => { requestRef.current += 1; };
  }, [reload]);
  return { ...state, reload };
}

function SelectField({ label: fieldLabel, value, onChange, children, disabled = false, describedBy }) {
  const selectId = useId();
  const labelId = `${selectId}-label`;
  return <div className="select-field">
    <label id={labelId} htmlFor={selectId}>{fieldLabel}</label>
    <div><select id={selectId} aria-labelledby={labelId} value={value || ""} onChange={(event) => onChange(event.target.value)} disabled={disabled} aria-describedby={describedBy}>{children}</select><ChevronDown size={14} aria-hidden="true" /></div>
  </div>;
}

function Toggle({ label: toggleLabel, checked, onChange, note, disabled = false }) {
  return <label className="toggle"><span><b>{toggleLabel}</b>{note && <small>{note}</small>}</span><input type="checkbox" checked={Boolean(checked)} onChange={(event) => onChange(event.target.checked)} disabled={disabled} /><i aria-hidden="true" /></label>;
}

function providerName(provider) {
  return provider?.display_name || provider?.name || provider?.provider_id || provider?.id || "Unknown provider";
}

function providerModels(provider) {
  const models = provider?.models || provider?.discovered_models || provider?.model_catalog?.models || [];
  return Array.isArray(models) ? models : [];
}

function modelId(model) {
  return typeof model === "string" ? model : model?.model_id || model?.id;
}

function allowedPolicies(persona) {
  const policies = persona?.allowed_cognitive_policies
    || persona?.active_version?.allowed_cognitive_policies
    || persona?.version?.allowed_cognitive_policies
    || [];
  return Array.isArray(policies) && policies.length ? policies : COGNITIVE_POLICIES;
}

function Composer({ controls, personas, providers, models: discoveredModels, modelError, onChange, onSend, busy, cancelling = false, onCancel }) {
  const [expanded, setExpanded] = useState(false);
  const [text, setText] = useState("");
  const selectedProvider = providers.find((provider) => (provider.provider_id || provider.id) === controls.providerId);
  const selectedPersona = personas.find((persona) => (persona.persona_id || persona.id) === controls.personaId);
  const cognitivePolicies = allowedPolicies(selectedPersona);
  const models = discoveredModels.length ? discoveredModels : providerModels(selectedProvider);
  const manualProviderMissing = !controls.automatic && !controls.providerId;
  const manualProviderUnavailable = !controls.automatic && Boolean(controls.providerId) && (!selectedProvider?.installed || !selectedProvider?.execution_supported || !selectedProvider?.capabilities?.answer_only_isolation || selectedProvider?.enabled === false);
  const validationMessage = manualProviderMissing
    ? "Choose an installed, executable provider before sending in manual mode."
    : manualProviderUnavailable
      ? "The selected provider is not currently eligible for isolated answer-only Chat execution."
      : "";
  const canSend = Boolean(text.trim()) && !busy && !validationMessage;

  useEffect(() => {
    if (!controls.automatic) setExpanded(true);
  }, [controls.automatic]);

  const submit = (event) => {
    event.preventDefault();
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };

  return <form className="composer" onSubmit={submit}>
    <textarea
      value={text}
      rows="2"
      aria-label="Message OpenCobalt"
      aria-describedby={validationMessage ? "composer-provider-validation" : undefined}
      placeholder="Ask once. OpenCobalt records the route."
      onChange={(event) => setText(event.target.value)}
      onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
      }}
      disabled={busy}
    />
    <div className="composer-foot">
      <div className="control-strip">
        <SelectField label="Persona" value={controls.personaId} onChange={(personaId) => onChange({ personaId })}>
          {personas.map((persona) => <option key={persona.persona_id || persona.id} value={persona.persona_id || persona.id}>{persona.name || persona.display_name || persona.persona_id || persona.id}</option>)}
        </SelectField>
        <button type="button" className={`mode-toggle ${controls.automatic ? "is-on" : ""}`} onClick={() => onChange({ automatic: !controls.automatic })}>{controls.automatic ? "Automatic" : "Manual"}</button>
        <button type="button" className="control-more" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded} aria-controls="composer-advanced"><SlidersHorizontal size={15} aria-hidden="true" /> Controls</button>
      </div>
      {busy
        ? <button className="button stop" type="button" onClick={onCancel} disabled={cancelling}><CircleStop size={15} aria-hidden="true" /> {cancelling ? "Cancelling…" : "Cancel"}</button>
        : <button className="button primary" type="submit" disabled={!canSend}><Send size={15} aria-hidden="true" /> Send</button>}
    </div>
    {validationMessage && <p id="composer-provider-validation" className="composer-validation" role="status">{validationMessage}</p>}
    {expanded && <div id="composer-advanced" className="composer-advanced">
      <SelectField label="Cognitive policy" value={controls.cognitivePolicy} onChange={(cognitivePolicy) => onChange({ cognitivePolicy })}>{cognitivePolicies.map((policy) => <option key={policy} value={policy}>{label(policy)}</option>)}</SelectField>
      {(controls.cognitivePolicy === "research" || controls.cognitivePolicy === "research_synthesis") && <p className="composer-validation">Research launches an evidence-backed mission: OpenCobalt retrieves public HTTPS sources, stores structured evidence, and links citations. It does not prove factual truth.</p>}
      <SelectField label="Reasoning effort" value={controls.reasoningEffort} onChange={(reasoningEffort) => onChange({ reasoningEffort })}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">Extra high</option></SelectField>
      <SelectField label="Privacy" value={controls.privacy} onChange={(privacy) => onChange({ privacy })}><option value="standard">Standard</option><option value="private">Private</option><option value="sensitive">Sensitive</option></SelectField>
      <Toggle label="Local only" checked={controls.localOnly} onChange={(localOnly) => onChange({ localOnly })} note="Excludes routes whose capability record requires network access." />
      <Toggle label="Allow fallback" checked={controls.allowFallback} onChange={(allowFallback) => onChange({ allowFallback })} note="Permits the next eligible route. Every fallback is recorded with its reason." />
      {!controls.automatic && <>
        <SelectField label="Provider" value={controls.providerId} onChange={(providerId) => onChange({ providerId, modelId: "" })} describedBy={validationMessage ? "composer-provider-validation" : undefined}>
          <option value="">Choose provider</option>
          {providers.map((provider) => {
            const providerId = provider.provider_id || provider.id;
            const executable = Boolean(provider.installed && provider.execution_supported && provider.capabilities?.answer_only_isolation && provider.enabled !== false);
            return <option key={providerId} value={providerId} disabled={!executable}>{providerName(provider)}{executable ? "" : " — unavailable in Chat"}</option>;
          })}
        </SelectField>
        <SelectField label="Model" value={controls.modelId} onChange={(nextModelId) => onChange({ modelId: nextModelId })} disabled={!controls.providerId}>
          <option value="">Provider default</option>
          {models.map((model) => <option key={modelId(model)} value={modelId(model)}>{typeof model === "string" ? model : model.display_name || model.name || modelId(model)}</option>)}
        </SelectField>
        {modelError && <p className="inline-error model-error" role="alert">Model catalog unavailable: {modelError.message}</p>}
      </>}
    </div>}
  </form>;
}

const MESSAGE_STATUS = {
  streaming: ["routing", "streaming"],
  failed: ["failed", "failed"],
  cancelled: ["cancelled", "cancelled"],
  cancel_requested: ["cancel requested", "pending"],
};

function MessageBubble({ message, route, onInspect, events = [] }) {
  const assistant = message.role === "assistant";
  const status = MESSAGE_STATUS[message.status];
  return <article className={`message ${assistant ? "assistant" : "user"}`}>
    <div className="message-meta">
      <span>{assistant ? "OpenCobalt" : "You"}</span>
      <time dateTime={message.created_at || undefined}>{relativeTime(message.created_at)}</time>
      {status && <span className={`message-status ${status[1]}`} role="status">{message.status === "streaming" && <i aria-hidden="true" />}{status[0]}</span>}
    </div>
    <Markdown content={message.content} />
    {assistant && route && <RouteSpine route={route} onInspect={onInspect} />}
    {events.length > 0 && <div className="event-strip" aria-label="Execution events">{events.map((event) => <Pill key={`${event.event_type}-${event.sequence}`} tone={event.event_type === "approval_required" ? "amber" : "neutral"}>{label(event.event_type)}</Pill>)}</div>}
  </article>;
}

function ChatPage({ conversations, refreshConversations, personas, providers, settings, settingsReady, openRoute, refreshSignal = 0 }) {
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem("opencobalt.activeConversation") || "");
  const [messages, setMessages] = useState([]);
  const [messageState, setMessageState] = useState({ loading: false, error: null });
  const [notice, setNotice] = useState(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [streamEvents, setStreamEvents] = useState([]);
  const [streamRoute, setStreamRoute] = useState(null);
  const [routeCache, setRouteCache] = useState({});
  const [routeHydrationErrors, setRouteHydrationErrors] = useState({});
  const [conversationOpen, setConversationOpen] = useState(false);
  const [modelCatalog, setModelCatalog] = useState([]);
  const [modelError, setModelError] = useState(null);
  const [comparison, setComparison] = useState({ loading: false, error: null, data: null });
  const abortRef = useRef(null);
  const executionRef = useRef(null);
  const runRef = useRef(null);
  const runGenerationRef = useRef(0);
  const routeLoadsRef = useRef(new Set());
  const routeGenerationRef = useRef(0);
  const settingsAppliedRef = useRef(false);
  const scrollRef = useRef(null);
  const shouldAutoScrollRef = useRef(true);
  const interactionBusy = busy || cancelling;
  const [controls, setControls] = useState({
    personaId: DEFAULT_SETTINGS.default_persona_id,
    automatic: true,
    providerId: "",
    modelId: "",
    privacy: DEFAULT_SETTINGS.privacy_policy,
    localOnly: DEFAULT_SETTINGS.local_only_default,
    allowFallback: false,
    cognitivePolicy: "deep_analysis",
    reasoningEffort: "medium",
  });
  const closeConversations = useCallback(() => setConversationOpen(false), []);

  useEffect(() => {
    if (!settingsReady || settingsAppliedRef.current) return;
    setControls((current) => ({
      ...current,
      personaId: settings.default_persona_id || DEFAULT_SETTINGS.default_persona_id,
      automatic: settings.default_routing_mode !== "manual",
      privacy: settings.privacy_policy || DEFAULT_SETTINGS.privacy_policy,
      localOnly: Boolean(settings.local_only_default),
    }));
    settingsAppliedRef.current = true;
  }, [settings, settingsReady]);

  useEffect(() => {
    const persona = personas.find((record) => (record.persona_id || record.id) === controls.personaId);
    const policies = allowedPolicies(persona);
    if (!policies.includes(controls.cognitivePolicy)) {
      setControls((current) => ({ ...current, cognitivePolicy: policies[0] }));
    }
  }, [controls.cognitivePolicy, controls.personaId, personas]);

  useEffect(() => {
    if (controls.automatic || !controls.providerId) {
      setModelCatalog([]);
      setModelError(null);
      return undefined;
    }
    let alive = true;
    setModelCatalog([]);
    setModelError(null);
    api.providerModels(controls.providerId)
      .then((result) => {
        if (alive) setModelCatalog(Array.isArray(result.models) ? result.models : []);
      })
      .catch((error) => {
        if (alive) setModelError(error);
      });
    return () => { alive = false; };
  }, [controls.automatic, controls.providerId]);

  useEffect(() => {
    if (interactionBusy) return;
    const exists = conversations.some((conversation) => conversationIdOf(conversation) === selectedId);
    if (exists) return;
    const nextId = conversations.length ? conversationIdOf(conversations[0]) : "";
    setSelectedId(nextId);
  }, [interactionBusy, conversations, selectedId]);

  useEffect(() => {
    if (selectedId) localStorage.setItem("opencobalt.activeConversation", selectedId);
    else localStorage.removeItem("opencobalt.activeConversation");
    shouldAutoScrollRef.current = true;
  }, [selectedId]);

  useEffect(() => () => {
    abortRef.current?.abort();
    const executionId = executionRef.current;
    if (executionId) api.cancelExecution(executionId).catch(() => undefined);
    runRef.current = null;
  }, []);

  useEffect(() => {
    if (interactionBusy) return undefined;
    routeGenerationRef.current += 1;
    routeLoadsRef.current = new Set();
    if (!selectedId) {
      setMessages([]);
      setRouteCache({});
      setRouteHydrationErrors({});
      setMessageState({ loading: false, error: null });
      return undefined;
    }
    let alive = true;
    setNotice(null);
    setStreamEvents([]);
    setStreamRoute(null);
    setMessages([]);
    setRouteCache({});
    setRouteHydrationErrors({});
    setMessageState({ loading: true, error: null });
    api.messages(selectedId)
      .then((data) => {
        if (!alive) return;
        setMessages(data);
        setMessageState({ loading: false, error: null });
      })
      .catch((error) => {
        if (alive) setMessageState({ loading: false, error });
      });
    return () => { alive = false; };
  }, [selectedId, refreshSignal, interactionBusy]); // Active sends refresh their own authoritative message state.

  useEffect(() => {
    const generation = routeGenerationRef.current;
    const routeIds = [...new Set(messages
      .filter((message) => message.message_id !== "local-stream" && message.role === "assistant" && message.route_id)
      .map((message) => message.route_id))];
    routeIds.forEach((routeId) => {
      if (routeCache[routeId] || routeHydrationErrors[routeId] || routeLoadsRef.current.has(routeId)) return;
      routeLoadsRef.current.add(routeId);
      api.route(routeId)
        .then((detail) => {
          if (routeGenerationRef.current !== generation) return;
          setRouteCache((current) => ({ ...current, [routeId]: routeFromDetail(detail) }));
        })
        .catch((error) => {
          if (routeGenerationRef.current === generation) setRouteHydrationErrors((current) => ({ ...current, [routeId]: error }));
        });
    });
  }, [messages, routeCache, routeHydrationErrors]);

  useEffect(() => {
    if (!shouldAutoScrollRef.current || !scrollRef.current) return undefined;
    const frame = window.requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [messages, comparison.data, comparison.loading]);

  const createConversation = async (input = {}) => {
    if (interactionBusy) return false;
    setCreating(true);
    setMessageState((current) => ({ ...current, error: null }));
    try {
      const conversation = await api.createConversation({ title: "New conversation", ...input });
      const createdId = conversationIdOf(conversation);
      if (!createdId) throw new ApiError("OpenCobalt created a conversation without an identifier.", { detail: conversation });
      await refreshConversations();
      setSelectedId(createdId);
      setConversationOpen(false);
      return true;
    } catch (error) {
      setMessageState({ loading: false, error });
      return false;
    } finally {
      setCreating(false);
    }
  };

  const ensureConversation = async () => {
    if (selectedId && conversations.some((conversation) => conversationIdOf(conversation) === selectedId)) return selectedId;
    const currentConversation = conversations.find((conversation) => conversationIdOf(conversation) === selectedId);
    const input = { title: "New conversation", ...(currentConversation?.project_path ? { project_path: currentConversation.project_path } : {}) };
    const conversation = await api.createConversation(input);
    const createdId = conversationIdOf(conversation);
    if (!createdId) throw new ApiError("OpenCobalt created a conversation without an identifier.", { detail: conversation });
    await refreshConversations();
    setSelectedId(createdId);
    return createdId;
  };

  const updateControls = (patch) => setControls((current) => ({ ...current, ...patch }));

  const send = async (content) => {
    if (interactionBusy) return;
    const generation = runGenerationRef.current + 1;
    runGenerationRef.current = generation;
    shouldAutoScrollRef.current = true;
    setBusy(true);
    setNotice(null);
    setStreamEvents([]);
    setStreamRoute(null);
    setMessageState({ loading: false, error: null });
    executionRef.current = null;
    try {
      const conversationId = await ensureConversation();
      const localUser = { message_id: `local-user-${Date.now()}`, conversation_id: conversationId, role: "user", content, status: "complete", created_at: new Date().toISOString() };
      const localAssistant = { message_id: "local-stream", conversation_id: conversationId, role: "assistant", content: "", status: "streaming", created_at: new Date().toISOString() };
      setMessages((current) => [...current, localUser, localAssistant]);
      const controller = new AbortController();
      abortRef.current = controller;
      const run = { conversationId, requestId: null, generation };
      runRef.current = run;

      const handleEvent = (event) => {
        if (runRef.current !== run) return;
        if (event.conversation_id !== conversationId) return;
        if (run.requestId && event.request_id !== run.requestId) return;
        run.requestId ||= event.request_id;
        const type = eventType(event);
        const payload = eventPayload(event);
        setStreamEvents((current) => [...current, event]);
        if (event.execution_id) executionRef.current = event.execution_id;

        const routeId = event.route_id || payload.route?.route_id || payload.route?.id;
        const route = payload.route
          ? { ...payload.route, route_id: routeId || payload.route.route_id }
          : routeId
            ? { route_id: routeId, receipt_id: payload.receipt_id }
            : null;
        if (route) {
          setStreamRoute((current) => ({ ...(current || {}), ...route }));
          setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, route_id: routeId || message.route_id, receipt_id: payload.receipt_id || route.receipt_id || message.receipt_id } : message));
        }

        if (type === "text_delta" && typeof payload.text_delta === "string") {
          setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, content: `${message.content}${payload.text_delta}`, status: "streaming", route_id: routeId || message.route_id } : message));
        }
        if (String(type).startsWith("research_")) {
          const step = payload.step || type.replace("research_", "");
          setMessages((current) => current.map((message) => message.message_id === "local-stream" ? {
            ...message,
            status: "streaming",
            route_id: routeId || message.route_id,
            content: payload.synthesis || `Research ${label(step)}${payload.retrieved_count != null ? ` · ${payload.retrieved_count} sources retrieved` : ""}${payload.evidence_count != null ? ` · ${payload.evidence_count} evidence records` : ""}`,
            metadata: { ...(message.metadata || {}), research_id: payload.research_id, mission_id: payload.mission_id },
          } : message));
        }

        if (type === "completed") {
          const finalMessage = payload.message;
          if (finalMessage && messageIdOf(finalMessage)) {
            setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...finalMessage, route_id: finalMessage.route_id || routeId, receipt_id: payload.receipt_id || finalMessage.receipt_id } : message));
          } else {
            setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, status: "complete", route_id: routeId || message.route_id, receipt_id: payload.receipt_id || message.receipt_id } : message));
          }
        } else if (type === "cancelled") {
          setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, status: "cancelled", content: message.content || "The execution was cancelled." } : message));
          setNotice({ tone: "neutral", text: "The local API confirmed cancellation." });
        } else if (ERROR_EVENTS.has(type)) {
          const messageText = errorMessage(payload);
          setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, status: "failed", content: message.content || messageText, route_id: routeId || message.route_id } : message));
          setNotice({ tone: "error", text: messageText });
        }
      };

      const result = await streamChat({
        conversation_id: conversationId,
        message: content,
        persona_id: controls.personaId,
        cognitive_policy: controls.cognitivePolicy,
        reasoning_effort: controls.reasoningEffort,
        privacy_mode: controls.privacy,
        local_only: controls.localOnly,
        provider_override: controls.automatic ? undefined : controls.providerId,
        model_override: controls.automatic ? undefined : controls.modelId || undefined,
        allow_fallback: controls.allowFallback,
      }, handleEvent, controller.signal);

      const terminalType = eventType(result?.lastEvent);
      if (!result?.eventCount || !TERMINAL_EVENTS.has(terminalType)) {
        throw new ApiError("The chat stream ended without a terminal event.", { detail: result });
      }
      if (TERMINAL_EVENTS.has(terminalType)) {
        const fresh = await api.messages(conversationId);
        if (runRef.current === run) setMessages(fresh);
      }
      await refreshConversations();
    } catch (error) {
      if (error?.name !== "AbortError") {
        setMessageState({ loading: false, error });
        setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, status: "failed", content: message.content || error.message } : message));
      }
    } finally {
      if (runRef.current?.generation === generation) {
        setBusy(false);
        executionRef.current = null;
        abortRef.current = null;
        runRef.current = null;
      }
    }
  };

  const cancel = async () => {
    if (cancelling) return;
    setCancelling(true);
    const cancelledRun = runRef.current;
    const cancelledGeneration = cancelledRun?.generation ?? runGenerationRef.current;
    const cancelledController = abortRef.current;
    const executionId = executionRef.current;
    const conversationId = cancelledRun?.conversationId || selectedId;
    setMessages((current) => current.map((message) => message.message_id === "local-stream" ? { ...message, status: "cancel_requested", content: message.content || "The local stream was closed." } : message));
    if (!executionId) {
      cancelledController?.abort();
      setNotice({ tone: "warning", text: "The browser stream closed before an execution ID arrived. If the server accepted the request, disconnect cleanup will finalize it as cancelled." });
      setCancelling(false);
      return;
    }
    let cancellationResult = null;
    let cancellationError = null;
    try {
      cancellationResult = await api.cancelExecution(executionId);
    } catch (error) {
      cancellationError = error;
    } finally {
      // Preserve explicit user intent at the API before closing the transport.
      cancelledController?.abort();
    }

    let freshMessages = null;
    let terminalCancellation = false;
    if (conversationId) {
      try {
        for (let attempt = 0; attempt < 8; attempt += 1) {
          freshMessages = await api.messages(conversationId);
          const latest = freshMessages.at(-1);
          terminalCancellation = latest?.role === "assistant" && latest?.status === "cancelled";
          if (terminalCancellation) break;
          await new Promise((resolve) => window.setTimeout(resolve, 50 * (attempt + 1)));
        }
        if (runGenerationRef.current === cancelledGeneration) {
          if (freshMessages) setMessages(freshMessages);
          await refreshConversations();
        }
      } catch (refreshError) {
        cancellationError ||= refreshError;
      }
    }

    const state = cancellationResult?.state || cancellationResult?.status;
    if (runGenerationRef.current === cancelledGeneration) {
      if (terminalCancellation || state === "cancelled") {
        setNotice({ tone: "neutral", text: `Cancellation confirmed for execution ${executionId}.` });
      } else if (cancellationError) {
        setNotice({ tone: "error", text: `The stream closed, but the local API did not confirm terminal cancellation: ${cancellationError.message}` });
      } else {
        setNotice({ tone: "warning", text: `Cancellation was requested for execution ${executionId}; terminal cancellation is not yet confirmed.` });
      }
    }
    setCancelling(false);
  };

  const compareLastTwo = async () => {
    const responses = messages.filter((message) => message.role === "assistant" && message.status === "complete").slice(-2);
    if (responses.length !== 2) return;
    setComparison({ loading: true, error: null, data: null });
    try {
      const data = await api.compareMessages(messageIdOf(responses[0]), messageIdOf(responses[1]));
      if (data.length !== 2) throw new ApiError("OpenCobalt returned an incomplete comparison.", { detail: data });
      setComparison({ loading: false, error: null, data });
    } catch (error) {
      setComparison({ loading: false, error, data: null });
    }
  };

  const selected = conversations.find((conversation) => conversationIdOf(conversation) === selectedId);
  const activePersona = personas.find((persona) => (persona.persona_id || persona.id) === controls.personaId);
  const comparableResponses = messages.filter((message) => message.role === "assistant" && message.status === "complete");
  const executionEvents = streamEvents.filter((event) => ["tool", "tool_event", "tool_started", "tool_completed", "approval_required", "fallback_started", "research_planning", "research_retrieving", "research_extracting", "research_reviewing", "research_synthesizing", "research_complete"].includes(event.event_type));
  const liveStatus = interactionBusy
    ? cancelling
      ? "OpenCobalt is finalizing cancellation and refreshing the durable record."
      : `OpenCobalt is routing the current request${executionRef.current ? ` with execution ${executionRef.current}` : ""}.`
    : notice?.text || "";

  return <div className="chat-layout">
    {conversationOpen && <button type="button" className="drawer-backdrop conversation-backdrop" aria-label="Close conversations" onClick={closeConversations} />}
    <ConversationRail conversations={conversations} selectedId={selectedId} onSelect={setSelectedId} onCreate={createConversation} isCreating={creating} disabled={interactionBusy} mobileOpen={conversationOpen} onClose={closeConversations} />
    <section className="chat-main" aria-labelledby="chat-title">
      <header className="chat-header">
        <div className="chat-heading"><IconButton className="conversation-open" label="Open conversations" aria-expanded={conversationOpen} aria-controls="conversation-navigation" onClick={() => setConversationOpen(true)}><MessageSquareText size={17} /></IconButton><div><p className="eyebrow">Chat</p><h1 id="chat-title">{selected?.title || "New conversation"}</h1><p className="project-path" title={selected?.project_path || undefined}>{selected?.project_path ? `Project: ${selected.project_path}` : "No project path attached"}</p></div></div>
        <div className="active-policy"><span>Active persona</span><b>{activePersona?.name || activePersona?.display_name || controls.personaId || "not selected"}</b></div>
      </header>
      <div ref={scrollRef} className="chat-scroll" onScroll={(event) => {
        const node = event.currentTarget;
        shouldAutoScrollRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 72;
      }}>
        {messageState.loading && <Loading label="Opening conversation" />}
        {messageState.error && <ErrorState error={messageState.error} retry={selectedId ? () => api.messages(selectedId).then((data) => { setMessages(data); setMessageState({ loading: false, error: null }); }) : undefined} />}
        {!messageState.loading && !messages.length && <EmptyState title="One request. An inspectable route.">Choose a persona if it matters, then write naturally. OpenCobalt keeps the decision, response, and any execution receipt with the conversation.</EmptyState>}
        {messages.map((message) => {
          const messageId = message.message_id || message.id;
          const matchingStreamRoute = message.route_id && streamRoute?.route_id === message.route_id ? streamRoute : null;
          const hydratedRoute = message.route_id ? routeCache[message.route_id] : null;
          const route = message.route_id ? { route_id: message.route_id, receipt_id: message.receipt_id || message.work_receipt_id, verification_status: message.verification_status, provenance_error: Boolean(routeHydrationErrors[message.route_id]), ...(hydratedRoute || {}), ...(matchingStreamRoute || {}) } : null;
          return <MessageBubble key={messageId} message={message} route={route} events={messageId === "local-stream" ? executionEvents : []} onInspect={() => route && openRoute(route.route_id, route)} />;
        })}
        {comparableResponses.length >= 2 && <div className="compare-action"><button type="button" className="button secondary" onClick={compareLastTwo} disabled={comparison.loading}>{comparison.loading ? "Comparing…" : "Compare last two responses"}</button><span>Uses each response’s stored message and independent route record.</span></div>}
        {comparison.error && <div className="compare-state"><ErrorState error={comparison.error} title="The responses could not be compared." /></div>}
        {comparison.data && <section className="comparison" aria-labelledby="comparison-title"><div className="comparison-heading"><h2 id="comparison-title">Stored response comparison</h2><button type="button" className="text-button" onClick={() => setComparison({ loading: false, error: null, data: null })}>Close</button></div><div className="comparison-grid">{comparison.data.map((entry, index) => {
        const comparedMessage = entry.message || {};
        const comparedRoute = entry.route || null;
        return <article key={messageIdOf(comparedMessage) || index}><p className="eyebrow">Response {index + 1}</p><Markdown content={comparedMessage.content} />{comparedRoute && <RouteSpine route={comparedRoute} onInspect={() => openRoute(routeIdOf(comparedRoute), comparedRoute)} />}</article>;
        })}</div></section>}
      </div>
      <div className="chat-live" aria-live="polite" aria-atomic="true">{liveStatus}</div>
      {notice && <div className={`stream-notice ${notice.tone}`} role={notice.tone === "error" ? "alert" : "status"}>{notice.text}</div>}
      <Composer controls={controls} personas={personas} providers={providers} models={modelCatalog} modelError={modelError} onChange={updateControls} onSend={send} busy={interactionBusy} cancelling={cancelling} onCancel={cancel} />
    </section>
  </div>;
}

function RoutesPage({ openRoute }) {
  const routes = useLoad(api.routes);
  if (routes.loading) return <section className="page"><PageTitle eyebrow="Routes" title="Decision history">Each score is a transparent heuristic, not a probability.</PageTitle><Loading /></section>;
  if (routes.error) return <section className="page"><PageTitle eyebrow="Routes" title="Decision history">Each score is a transparent heuristic, not a probability.</PageTitle><ErrorState error={routes.error} retry={routes.reload} /></section>;
  return <section className="page"><PageTitle eyebrow="Routes" title="Decision history">Each score is a transparent heuristic, not a probability.</PageTitle>{!routes.data.length ? <EmptyState title="No route decisions yet">Send a message in Chat to create the first route record.</EmptyState> : <div className="record-list">{routes.data.map((route) => <button type="button" className="route-row" key={routeIdOf(route)} onClick={() => openRoute(routeIdOf(route), route)}><span className="route-status" aria-hidden="true" /><div><b>{label(route.task_class)}</b><small>{route.selected_provider || "provider not recorded"} · {route.selected_model || "default model"}</small></div><div className="route-row-meta"><span>{route.route_score ?? "—"} pts</span><small>{relativeTime(route.created_at)}</small></div><ArrowRight size={16} aria-hidden="true" /></button>)}</div>}</section>;
}

function CollectionPage({ kind, title, description, loader, render }) {
  const state = useLoad(loader);
  if (state.loading) return <section className="page"><PageTitle eyebrow={kind} title={title}>{description}</PageTitle><Loading /></section>;
  if (state.error) return <section className="page"><PageTitle eyebrow={kind} title={title}>{description}</PageTitle><ErrorState error={state.error} retry={state.reload} /></section>;
  return <section className="page"><PageTitle eyebrow={kind} title={title}>{description}</PageTitle>{state.data.length ? <div className="record-list">{state.data.map(render)}</div> : <EmptyState title={`No ${kind.toLowerCase()} records yet`}>{description}</EmptyState>}</section>;
}

function MissionsPage() {
  return <CollectionPage kind="Missions" title="Durable work" description="Longer objectives stay resumable with their checkpoints, approvals, artifacts, and outcomes." loader={api.missions} render={(mission) => {
    const steps = Array.isArray(mission.steps) ? mission.steps : [];
    const research = mission.research && typeof mission.research === "object" ? mission.research : null;
    const coding = mission.coding && typeof mission.coding === "object" ? mission.coding : null;
    const sources = Array.isArray(research?.sources) ? research.sources : [];
    const evidence = Array.isArray(research?.evidence) ? research.evidence : [];
    const citations = Array.isArray(research?.citations) ? research.citations : [];
    const disagreements = Array.isArray(research?.disagreements) ? research.disagreements : [];
    const roles = research?.model_roles && typeof research.model_roles === "object" ? Object.entries(research.model_roles) : [];
    return <article className="record-card mission-card" key={missionIdOf(mission)}><div className="card-top"><div className="pill-row"><Pill tone={mission.status === "complete" || mission.status === "completed" ? "green" : mission.status === "blocked" ? "amber" : "neutral"}>{label(mission.status || "planned")}</Pill><Pill>{label(mission.mission_type || "mission")}</Pill>{research && <Pill>{sources.length} sources</Pill>}{research && <Pill>{evidence.length} evidence</Pill>}{coding && <Pill>{label(coding.capability_role || "coding")}</Pill>}</div><small className="mono">{mission.mission_id || mission.id}</small></div><h2>{mission.goal || mission.title || "Untitled mission"}</h2><p>{mission.current_state || mission.summary || research?.synthesis || coding?.outcome || "No current state has been recorded."}</p><details><summary>Inspect plan, checkpoints, and provenance</summary><div className="mission-detail"><dl><dt>Active plan</dt><dd>{mission.active_plan_id || "not recorded"}</dd><dt>Last receipt</dt><dd>{mission.last_receipt_id || "not recorded"}</dd><dt>Source route</dt><dd>{mission.route_id || research?.route_id || "not promoted from chat"}</dd><dt>Outcome</dt><dd>{mission.outcome || "not final"}</dd></dl>{steps.length ? <ol>{steps.map((step) => <li key={step.step_id}><b>{step.title}</b><span>{label(step.execution_state)} · approval {label(step.approval_state)} · risk {label(step.risk_level)}</span>{step.receipt_id && <code>{step.receipt_id}</code>}</li>)}</ol> : <p>No durable steps were returned for this mission.</p>}</div></details>{research && <details><summary>Inspect research sources, evidence, and citations</summary><div className="mission-detail research-detail"><p>{research.question}</p>{Array.isArray(research.limitations) && research.limitations.length > 0 && <ul>{research.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}{roles.length > 0 && <section><h3>Model roles</h3><dl>{roles.map(([role, value]) => <React.Fragment key={role}><dt>{label(role)}</dt><dd>{value?.display_name || value?.model_id || value?.provider_id} · {value?.reason || "role assigned"}</dd></React.Fragment>)}</dl></section>}{sources.length > 0 && <section><h3>Sources</h3><ol>{sources.map((source) => <li key={source.source_id}><b>{source.title || source.url}</b><span>{label(source.source_type)} · {label(source.retrieval_status)}</span><code>{source.url}</code></li>)}</ol></section>}{evidence.length > 0 && <section><h3>Evidence</h3><ol>{evidence.map((item) => <li key={item.evidence_id}><b>{item.claim}</b><span>{label(item.causal_class)} · {label(item.relation)} · {label(item.verification_status)}</span>{item.limitations && <span>{item.limitations}</span>}<code>{item.evidence_id}</code></li>)}</ol></section>}{disagreements.length > 0 && <section><h3>Disagreements preserved</h3><ol>{disagreements.map((item) => <li key={item.disagreement_id}><b>{item.topic}</b><span>{(item.positions || []).join(" · ")}</span></li>)}</ol></section>}{citations.length > 0 && <section><h3>Citations</h3><ol>{citations.map((item) => <li key={item.citation_id}><b>{item.claim_span || "claim"}</b><span>{label(item.verification_status)} · {item.verification_note}</span><code>{item.evidence_id || "no evidence id"}</code></li>)}</ol></section>}{research.synthesis && <section><h3>Final synthesis</h3><p>{research.synthesis}</p></section>}</div></details>}{coding && <details><summary>Inspect coding mission, ACP session, and approvals</summary><div className="mission-detail"><dl><dt>Repository</dt><dd><code>{coding.repository_path || "not recorded"}</code></dd><dt>ACP session</dt><dd><code>{coding.acp_session_id || "not recorded"}</code></dd><dt>Provider</dt><dd>{coding.provider_id || "not recorded"}{coding.model_id ? ` · ${coding.model_id}` : ""}</dd><dt>Receipt</dt><dd><code>{coding.receipt_id || "not recorded"}</code></dd></dl>{Array.isArray(coding.approvals) && coding.approvals.length > 0 && <section><h3>Approvals</h3><ol>{coding.approvals.map((item, index) => <li key={item.approval_request_id || index}><b>{item.tool || item.policy_decision || "permission"}</b><span>{label(item.risk_level)} · {label(item.policy_decision)}</span></li>)}</ol></section>}</div></details>}</article>;
  }} />;
}

function SkillsPage() {
  const state = useLoad(api.skills);
  const [actions, setActions] = useState({});
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const toggleSkill = async (skill) => {
    const skillId = skill.skill_id || skill.id;
    setActions((current) => ({ ...current, [skillId]: { loading: true, error: null } }));
    try {
      await api.updateSkill(skillId, { enabled: skill.enabled === false });
      setActions((current) => ({ ...current, [skillId]: { loading: false, error: null } }));
      await state.reload();
    } catch (error) {
      setActions((current) => ({ ...current, [skillId]: { loading: false, error } }));
    }
  };
  if (state.loading) return <section className="page"><PageTitle eyebrow="Skills" title="Procedural knowledge">Installed skills remain inspectable. Imported content is never executed merely by inspection.</PageTitle><Loading /></section>;
  if (state.error) return <section className="page"><PageTitle eyebrow="Skills" title="Procedural knowledge">Installed skills remain inspectable. Imported content is never executed merely by inspection.</PageTitle><ErrorState error={state.error} retry={state.reload} /></section>;
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = state.data.filter((skill) => {
    const matchesQuery = !normalizedQuery || [skill.name, skill.description, skill.source_ref].some((value) => String(value || "").toLowerCase().includes(normalizedQuery));
    const matchesFilter = filter === "all"
      || (filter === "enabled" && skill.enabled !== false)
      || (filter === "disabled" && skill.enabled === false)
      || (filter === "imported" && skill.source_kind === "imported")
      || (filter === "builtin" && skill.source_kind === "builtin");
    return matchesQuery && matchesFilter;
  });
  return <section className="page"><PageTitle eyebrow="Skills" title="Procedural knowledge">Installed skills remain inspectable. Imported content is never executed merely by inspection.</PageTitle><details className="skill-management-shell"><summary>Import or manage pinned local skills</summary><SkillImport onChanged={state.reload} /></details><div className="collection-tools"><label><span>Search skills</span><input type="search" value={query} placeholder="Name, description, or source" onChange={(event) => setQuery(event.target.value)} /></label><SelectField label="Filter" value={filter} onChange={setFilter}><option value="all">All skills</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option><option value="builtin">Built-in</option><option value="imported">Imported</option></SelectField></div>{filtered.length ? <div className="record-list">{filtered.map((skill) => {
    const versions = Array.isArray(skill.versions) ? skill.versions : skill.active_version ? [skill.active_version] : [];
    const permissions = Array.isArray(skill.requested_permissions) ? skill.requested_permissions : [];
    const compatibility = skill.compatibility && typeof skill.compatibility === "object" ? skill.compatibility : {};
    const skillId = skill.skill_id || skill.id;
    const action = actions[skillId];
    const mutable = skill.source_kind !== "builtin";
    return <article className="record-card skill-card" key={skillIdOf(skill)}><div className="card-top"><div className="pill-row"><Pill tone={skill.enabled === false ? "neutral" : "green"}>{skill.enabled === false ? "installed disabled" : "enabled"}</Pill><Pill>{skill.source_kind || "local"}</Pill><Pill tone={skill.trust_level === "builtin" ? "green" : "amber"}>{skill.trust_level || "unassessed"}</Pill></div><span className="mono">{skill.active_version_id || "no active version"}</span></div><h2>{skill.name}</h2><p>{skill.description || "No description supplied."}</p>{action?.error && <p className="inline-error" role="alert">Activation change failed: {action.error.message}</p>}<details className="skill-detail"><summary>Inspect permissions, provenance, and versions</summary><div><h3>Provenance</h3><p><b>Source:</b> <code>{skill.source_ref || "not recorded"}</code></p><p><b>Install state:</b> {skill.enabled === false ? "disabled; no activation is implied" : "enabled in the skill registry"}</p><h3>Requested permissions</h3>{permissions.length ? <div className="pill-row">{permissions.map((permission) => <Pill key={permission} tone="amber">{permission}</Pill>)}</div> : <p>No permissions requested.</p>}<h3>Compatibility</h3>{Object.keys(compatibility).length ? <dl>{Object.entries(compatibility).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{String(value)}</dd></React.Fragment>)}</dl> : <p>No compatibility claims recorded.</p>}<h3>Versions</h3>{versions.length ? <div className="skill-versions">{versions.map((version) => <article key={version.skill_version_id || version.version}><b>{version.version || "unversioned"}</b><code>{version.content_hash || "hash not recorded"}</code><span>Receipt: {version.receipt_id || "not recorded"}</span><span>Installed: {version.installed ? "verified local path" : "not currently verified installed"}</span></article>)}</div> : <p>No version records returned.</p>}<div className="skill-activation"><button type="button" className="button secondary" disabled={!mutable || action?.loading} onClick={() => toggleSkill(skill)}>{action?.loading ? "Saving…" : !mutable ? "Built-in enabled" : skill.enabled === false ? "Enable pinned skill" : "Disable skill"}</button><span>{mutable ? "This explicit registry change does not execute skill content. Imported activation requires its pinned install path to verify." : "Built-in activation is not mutable through the imported-skill endpoint."}</span></div></div></details></article>;
  })}</div> : <EmptyState title={state.data.length ? "No skills match this view" : "No skills records yet"}>{state.data.length ? "Change the search or filter. No skill state was modified." : "Install or discover a skill through an approved local workflow; this page does not execute imported content."}</EmptyState>}</section>;
}

function MemoryRecord({ memory, onUpdate, onRemove }) {
  const persistedDraft = () => ({
    content: memory.content,
    reason: memory.reason,
    scope: memory.scope,
    status: memory.status,
    sensitivity: memory.sensitivity,
  });
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [draft, setDraft] = useState(persistedDraft);

  useEffect(() => {
    setDraft({ content: memory.content, reason: memory.reason, scope: memory.scope, status: memory.status, sensitivity: memory.sensitivity });
  }, [memory.content, memory.reason, memory.scope, memory.status, memory.sensitivity]);

  const save = async (event) => {
    event.preventDefault();
    if (!draft.content.trim() || !draft.reason.trim()) return;
    setSaving(true);
    const saved = await onUpdate(memory, { ...draft, content: draft.content.trim(), reason: draft.reason.trim() });
    setSaving(false);
    if (saved) setEditing(false);
  };

  const cancelEdit = () => {
    setDraft(persistedDraft());
    setEditing(false);
  };

  if (editing) return <article className="memory-row memory-edit"><form onSubmit={save}><label><span>Memory</span><textarea rows="3" maxLength="20000" value={draft.content} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} /></label><label><span>Why it exists</span><input maxLength="1000" value={draft.reason} onChange={(event) => setDraft((current) => ({ ...current, reason: event.target.value }))} /></label><div className="memory-edit-grid"><SelectField label="Scope" value={draft.scope} onChange={(scope) => setDraft((current) => ({ ...current, scope }))}><option value="user">User</option><option value="project" disabled>Project — requires a bound project</option><option value="conversation" disabled>Conversation — requires a bound conversation</option><option value="temporary">Temporary</option></SelectField><SelectField label="State" value={draft.status} onChange={(status) => setDraft((current) => ({ ...current, status }))}><option value="proposed">Proposed</option><option value="active">Active</option><option value="rejected">Rejected</option></SelectField><SelectField label="Sensitivity" value={draft.sensitivity} onChange={(sensitivity) => setDraft((current) => ({ ...current, sensitivity }))}><option value="normal">Normal</option><option value="sensitive">Sensitive</option></SelectField></div><div className="memory-edit-actions"><button type="button" className="text-button" onClick={cancelEdit}>Cancel</button><button type="submit" className="button primary" disabled={saving || !draft.content.trim() || !draft.reason.trim()}>{saving ? "Saving…" : "Save changes"}</button></div></form></article>;

  return <article className="memory-row"><div><div className="card-top"><div className="pill-row"><Pill tone={memory.pinned ? "amber" : "neutral"}>{memory.pinned ? "pinned" : memory.scope || "user"}</Pill>{memory.sensitivity === "sensitive" && <Pill tone="amber">sensitive</Pill>}</div><span>{label(memory.status)}</span></div><h2>{memory.content}</h2><p>Why: {memory.reason || "No reason recorded."}</p><small>Source: {memory.source_ref || memory.source_type || "explicit"} · {relativeTime(memory.updated_at || memory.created_at)}</small></div><div className="memory-actions"><button type="button" className="text-button" onClick={() => setEditing(true)}>Edit</button><button type="button" className="text-button" onClick={() => onUpdate(memory, { pinned: !memory.pinned })}>{memory.pinned ? "Unpin" : "Pin"}</button>{confirmDelete ? <><span className="delete-confirm">Delete permanently?</span><button type="button" className="text-button danger" onClick={() => onRemove(memory)}>Confirm delete</button><button type="button" className="text-button" onClick={() => setConfirmDelete(false)}>Keep</button></> : <button type="button" className="text-button danger" onClick={() => setConfirmDelete(true)}>Delete</button>}</div></article>;
}

function MemoryPage() {
  const state = useLoad(api.memory);
  const [draft, setDraft] = useState({ content: "", scope: "user", sensitivity: "normal" });
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState(null);
  const add = async (event) => {
    event.preventDefault();
    if (!draft.content.trim()) return;
    setSaving(true);
    setActionError(null);
    try {
      await api.createMemory({ content: draft.content.trim(), reason: "Saved explicitly from the Memory page", source_type: "explicit_user_save", scope: draft.scope, sensitivity: draft.sensitivity, status: "active" });
      setDraft({ content: "", scope: "user", sensitivity: "normal" });
      await state.reload();
    } catch (error) {
      setActionError(error);
    } finally {
      setSaving(false);
    }
  };
  const update = async (memory, patch) => {
    setActionError(null);
    try {
      await api.updateMemory(memory.memory_id || memory.id, patch);
      await state.reload();
      return true;
    } catch (error) {
      setActionError(error);
      return false;
    }
  };
  const remove = async (memory) => {
    setActionError(null);
    try {
      await api.deleteMemory(memory.memory_id || memory.id);
      await state.reload();
    } catch (error) {
      setActionError(error);
    }
  };
  if (state.loading) return <section className="page"><PageTitle eyebrow="Memory" title="Curated, not scraped">Each memory remains attributable, scoped, and under your control.</PageTitle><Loading /></section>;
  if (state.error) return <section className="page"><PageTitle eyebrow="Memory" title="Curated, not scraped">Each memory remains attributable, scoped, and under your control.</PageTitle><ErrorState error={state.error} retry={state.reload} /></section>;
  return <section className="page"><PageTitle eyebrow="Memory" title="Curated, not scraped">Each memory remains attributable, scoped, and under your control.</PageTitle>{actionError && <ErrorState error={actionError} title="The memory change was not saved." />}<form className="memory-add" onSubmit={add}><input value={draft.content} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} placeholder="Save a fact or preference explicitly" aria-label="New memory" /><SelectField label="Scope" value={draft.scope} onChange={(scope) => setDraft((current) => ({ ...current, scope }))}><option value="user">User</option><option value="project" disabled>Project — requires a bound project</option><option value="conversation" disabled>Conversation — requires a bound conversation</option><option value="temporary">Temporary</option></SelectField><SelectField label="Sensitivity" value={draft.sensitivity} onChange={(sensitivity) => setDraft((current) => ({ ...current, sensitivity }))}><option value="normal">Normal</option><option value="sensitive">Sensitive</option></SelectField><button type="submit" className="button primary" disabled={saving || !draft.content.trim()}>{saving ? "Saving…" : "Save memory"}</button></form>{state.data.length ? <div className="record-list">{state.data.map((memory) => <MemoryRecord key={memoryIdOf(memory)} memory={memory} onUpdate={update} onRemove={remove} />)}</div> : <EmptyState title="No curated memory yet">OpenCobalt proposes memory from explicit requests. You decide what persists.</EmptyState>}</section>;
}

function LedgerPage() {
  return <CollectionPage kind="Ledger" title="Receipts" description="Normalized execution evidence is kept locally and redacted before it reaches this view." loader={api.receipts} render={(receipt) => <article className="record-card receipt-card" key={receiptIdOf(receipt)}><div className="card-top"><Pill tone={receipt.status === "complete" || receipt.ok ? "green" : receipt.status === "failed" ? "coral" : "neutral"}>{label(receipt.status || (receipt.ok ? "complete" : "recorded"))}</Pill><span className="mono">{receipt.receipt_id || receipt.id}</span></div><h2>{receipt.summary || receipt.action || receipt.provider_id || "Execution receipt"}</h2><p>{receipt.verification_status ? `Receipt integrity: ${label(receipt.verification_status)}` : "No receipt-integrity result was recorded."}</p><small>{relativeTime(receipt.created_at || receipt.finished_at)}</small></article>} />;
}

function ProvidersPage({ providers, reloadProviders }) {
  const [health, setHealth] = useState({});
  const [preferences, setPreferences] = useState({});
  const [catalogs, setCatalogs] = useState({});
  const check = async (provider) => {
    const providerId = provider.provider_id || provider.id;
    setHealth((current) => ({ ...current, [providerId]: { loading: true } }));
    try {
      const result = await api.providerHealth(providerId);
      setHealth((current) => ({ ...current, [providerId]: { result } }));
      await reloadProviders();
    } catch (error) {
      setHealth((current) => ({ ...current, [providerId]: { error } }));
    }
  };
  const updatePreference = async (provider, patch) => {
    const providerId = provider.provider_id || provider.id;
    setPreferences((current) => ({ ...current, [providerId]: { loading: true, error: null, note: null } }));
    try {
      await api.updateProviderPreference(providerId, patch);
      setPreferences((current) => ({ ...current, [providerId]: { loading: false, error: null, note: "Preference saved by the local API." } }));
      await reloadProviders();
    } catch (error) {
      setPreferences((current) => ({ ...current, [providerId]: { loading: false, error, note: null } }));
    }
  };
  const discoverModels = async (provider) => {
    const providerId = provider.provider_id || provider.id;
    setCatalogs((current) => ({ ...current, [providerId]: { loading: true, error: null, models: current[providerId]?.models || [] } }));
    try {
      const result = await api.providerModels(providerId);
      setCatalogs((current) => ({ ...current, [providerId]: { loading: false, error: null, models: Array.isArray(result.models) ? result.models : [], receiptId: result.receipt_id, limitations: Array.isArray(result.limitations) ? result.limitations : [] } }));
    } catch (error) {
      setCatalogs((current) => ({ ...current, [providerId]: { loading: false, error, models: current[providerId]?.models || [] } }));
    }
  };
  return <section className="page"><PageTitle eyebrow="Providers" title="Capability, not assumption">Installation, authentication, health, and executable support remain separate facts.</PageTitle>{!providers.length ? <EmptyState title="No providers discovered">Refresh after installing or starting a supported runtime. No provider availability is inferred here.</EmptyState> : <div className="record-list">{providers.map((provider) => {
    const providerId = provider.provider_id || provider.id;
    const state = health[providerId];
    const capabilities = provider.capabilities || {};
    const installed = Boolean(provider.installed);
    const executable = Boolean(provider.execution_supported);
    const enabled = provider.enabled !== false;
    const ready = provider.health === "ready";
    const requiresNetwork = Boolean(capabilities.requires_network);
    const localOnlyEligible = Boolean(capabilities.local_only_eligible);
    const chatEligible = executable && Boolean(capabilities.answer_only_isolation);
    const catalog = catalogs[providerId];
    const models = catalog?.models?.length ? catalog.models : providerModels(provider);
    const profile = provider.routing_profile || {};
    const preference = preferences[providerId];
    return <article className="provider-row" key={providerId}>
      <span className={`provider-dot ${ready && executable && enabled ? "available" : ""}`} aria-hidden="true" />
      <div className="provider-main">
        <div className="card-top"><h2>{providerName(provider)}</h2><div className="pill-row"><Pill tone={installed ? "green" : "neutral"}>{installed ? "installed" : "not installed"}</Pill><Pill tone={enabled ? "green" : "neutral"}>{enabled ? "enabled" : "disabled"}</Pill><Pill tone={requiresNetwork ? "amber" : "neutral"}>{requiresNetwork ? "network required" : "network not required"}</Pill><Pill tone={localOnlyEligible ? "green" : "neutral"}>{localOnlyEligible ? "local-only eligible" : "not local-only eligible"}</Pill><Pill tone={chatEligible ? "green" : "amber"}>{chatEligible ? "Chat eligible" : "Chat approval unavailable"}</Pill>{capabilities.acp ? <Pill tone="green">ACP</Pill> : null}{capabilities.coding_analysis ? <Pill tone="green">coding-analysis</Pill> : null}{capabilities.coding_agent ? <Pill tone="amber">coding-agent</Pill> : null}</div></div>
        <p>{provider.runtime_id || "runtime not detected"} · auth {label(provider.authentication)} · health {label(provider.health)} · execution {executable ? "supported" : "unsupported"}</p>
        <p className="provider-contract">{label(profile.adapter_type || "adapter unknown")} · {label(profile.billing_classification || "billing unknown")} · {label(profile.quality_tier || "quality unknown")} quality · {label(capabilities.streaming || "no streaming")} streaming · {label(capabilities.cancellation || "no cancellation")} cancellation</p>
        {models.length > 0 && <div className="pill-row">{models.slice(0, 4).map((model) => <Pill key={modelId(model)}>{typeof model === "string" ? model : `${model.display_name || model.name || modelId(model)}${model.execution_location === "local" ? " · local" : ""}`}</Pill>)}</div>}
        {catalog && !catalog.loading && !catalog.error && !models.length && <p className="provider-evidence">The runtime returned no model records.</p>}
        {catalog?.limitations?.length > 0 && <ul className="provider-limitations">{catalog.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>}
        {catalog?.receiptId && <p className="provider-evidence">Model discovery receipt: <code>{catalog.receiptId}</code></p>}
        <details className="provider-evidence"><summary>Inspect capability and outcome evidence</summary><dl><dt>Completion</dt><dd>{capabilities.completion ? "supported" : "unsupported"}</dd><dt>ACP</dt><dd>{capabilities.acp ? "discovered" : "not discovered"}</dd><dt>Coding analysis</dt><dd>{capabilities.coding_analysis ? "eligible" : "not eligible"}</dd><dt>Coding agent</dt><dd>{capabilities.coding_agent ? "eligible" : "not eligible"}</dd><dt>Declared roles</dt><dd>{profile.capability_roles?.length ? profile.capability_roles.map(label).join(", ") : "none declared"}</dd><dt>Tool support</dt><dd>{profile.tool_names?.length ? profile.tool_names.join(", ") : "none declared"}</dd><dt>Task capabilities</dt><dd>{profile.task_capabilities?.length ? profile.task_capabilities.map(label).join(", ") : "none declared"}</dd><dt>Last successful invocation</dt><dd>{provider.last_successful_invocation ? new Date(provider.last_successful_invocation).toLocaleString() : "not proven"}</dd></dl>{provider.recent_errors?.length > 0 && <div><h3>Recent redacted errors</h3><ul className="provider-limitations">{provider.recent_errors.map((recentError, index) => <li key={`${recentError.category}-${index}`}>{label(recentError.category)}: {recentError.message}</li>)}</ul></div>}</details>
        {provider.limitations?.length > 0 && <ul className="provider-limitations">{provider.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>}
        {state?.error && <p className="inline-error" role="alert">{state.error.message}</p>}
        {state?.result && <p className={state.result.state === "ready" ? "health-result" : "provider-evidence"} role="status">Last health check: {label(state.result.state)} · auth {label(state.result.authentication)}{state.result.successful_invocation_proven ? " · successful invocation proven" : " · successful invocation not proven"}</p>}
        {catalog?.error && <p className="inline-error" role="alert">Model discovery failed: {catalog.error.message}</p>}
        {preference?.error && <p className="inline-error" role="alert">Preference change failed: {preference.error.message}</p>}
        {preference?.note && <p className="health-result" role="status">{preference.note}</p>}
        <div className="provider-preferences"><Toggle label="Enabled for routing" checked={enabled} onChange={(nextEnabled) => updatePreference(provider, { enabled: nextEnabled })} note="Registry preference only; it does not prove execution readiness." disabled={preference?.loading} /><SelectField label="Routing priority" value={String(provider.priority ?? 50)} onChange={(priority) => updatePreference(provider, { priority: Number(priority) })} disabled={preference?.loading}>{![0, 25, 50, 75, 100].includes(Number(provider.priority ?? 50)) && <option value={String(provider.priority)}>{provider.priority} · custom</option>}<option value="0">0 · last</option><option value="25">25 · low</option><option value="50">50 · normal</option><option value="75">75 · high</option><option value="100">100 · first</option></SelectField><SelectField label="Cost policy" value={provider.cost_policy || "prefer_subscription"} onChange={(cost_policy) => updatePreference(provider, { cost_policy })} disabled={preference?.loading}><option value="free_only">Free only</option><option value="prefer_subscription">Prefer subscription</option><option value="allow_billed">Allow billed</option></SelectField></div>
      </div>
      <div className="provider-actions"><button type="button" className="button secondary" onClick={() => check(provider)} disabled={state?.loading}>{state?.loading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />} Check health</button><button type="button" className="button secondary" onClick={() => discoverModels(provider)} disabled={catalog?.loading || !capabilities.model_discovery}>{catalog?.loading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />} Discover models</button></div>
    </article>;
  })}</div>}<p className="endpoint-note" role="note">Provider preferences affect route eligibility and scoring only. Installation, authentication, health, and successful invocation remain separate evidence.</p></section>;
}

function ProviderPriorityField({ value, providers, onChange }) {
  const priority = Array.isArray(value) ? value : [];
  const providerIds = providers.map((provider) => provider.provider_id || provider.id).filter(Boolean);
  const available = providerIds.filter((providerId) => !priority.includes(providerId));
  const move = (index, offset) => {
    const nextIndex = index + offset;
    if (nextIndex < 0 || nextIndex >= priority.length) return;
    const next = [...priority];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    onChange(next);
  };
  return <div className="priority-field">
    <span>Provider priority</span>
    {priority.length > 0
      ? <ol>{priority.map((providerId, index) => <li key={providerId}><code>{providerId}</code><span><button type="button" className="text-button" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`Move ${providerId} earlier`}>Earlier</button><button type="button" className="text-button" onClick={() => move(index, 1)} disabled={index === priority.length - 1} aria-label={`Move ${providerId} later`}>Later</button><button type="button" className="text-button danger" onClick={() => onChange(priority.filter((id) => id !== providerId))} aria-label={`Remove ${providerId} from provider priority`}>Remove</button></span></li>)}</ol>
      : <small>No explicit provider order. The router uses its recorded scoring policy.</small>}
    <label><span className="visually-hidden">Add provider to priority</span><select value="" onChange={(event) => event.target.value && onChange([...priority, event.target.value])} disabled={!available.length}><option value="">{available.length ? "Add discovered provider…" : "No discovered providers to add"}</option>{available.map((providerId) => <option key={providerId} value={providerId}>{providerName(providers.find((provider) => (provider.provider_id || provider.id) === providerId))}</option>)}</select></label>
  </div>;
}

function PersonaEditor({ personas, providers, defaultPersonaId, reloadPersonas }) {
  const [selectedId, setSelectedId] = useState(defaultPersonaId || personas[0]?.persona_id || "");
  const [duplicateName, setDuplicateName] = useState("");
  const [draft, setDraft] = useState(null);
  const [sample, setSample] = useState({ prompt: "", cognitivePolicy: "" });
  const [testResult, setTestResult] = useState(null);
  const [action, setAction] = useState({ kind: null, error: null, note: null });
  const persona = personas.find((record) => (record.persona_id || record.id) === selectedId) || personas[0];
  const version = persona?.active_version || persona?.version || null;
  const editable = Boolean(persona && !persona.built_in && version);

  useEffect(() => {
    if (!persona) return;
    const policies = allowedPolicies(persona);
    setDraft({
      name: persona.name || "",
      controls: { ...(version?.controls || {}) },
      providerAffinities: { ...(version?.provider_affinities || {}) },
      customInstructions: version?.custom_instructions || "",
      allowedCognitivePolicies: policies,
    });
    setDuplicateName(`${persona.name || "Persona"} Custom`);
    setSample({ prompt: "", cognitivePolicy: policies[0] || "" });
    setTestResult(null);
    setAction({ kind: null, error: null, note: null });
  }, [persona, version]);

  useEffect(() => {
    if (persona) return;
    setSelectedId(personas[0]?.persona_id || personas[0]?.id || "");
  }, [persona, personas]);

  useEffect(() => {
    if (!draft?.allowedCognitivePolicies?.length || draft.allowedCognitivePolicies.includes(sample.cognitivePolicy)) return;
    setSample((current) => ({ ...current, cognitivePolicy: draft.allowedCognitivePolicies[0] }));
  }, [draft?.allowedCognitivePolicies, sample.cognitivePolicy]);

  if (!persona || !draft) return <div className="unavailable-panel" role="note">No persona version record is available to edit.</div>;

  const runAction = async (kind, operation, note) => {
    setAction({ kind, error: null, note: null });
    try {
      const result = await operation();
      await reloadPersonas();
      setAction({ kind: null, error: null, note });
      return result;
    } catch (error) {
      setAction({ kind: null, error, note: null });
      return null;
    }
  };

  const duplicate = async () => {
    if (!duplicateName.trim()) return;
    const created = await runAction("duplicate", () => api.duplicatePersona(persona.persona_id || persona.id, { name: duplicateName.trim() }), "Custom persona created as a new versioned profile.");
    if (created) setSelectedId(created.persona_id || created.id);
  };

  const save = async () => {
    if (!editable || !draft.name.trim() || !draft.allowedCognitivePolicies.length) return;
    await runAction("save", () => api.updatePersona(persona.persona_id || persona.id, {
      name: draft.name.trim(),
      controls: draft.controls,
      provider_affinities: draft.providerAffinities,
      custom_instructions: draft.customInstructions,
      allowed_cognitive_policies: draft.allowedCognitivePolicies,
    }), "Persona changes saved as a new immutable version.");
  };

  const reset = () => runAction("reset", () => api.resetPersona(persona.persona_id || persona.id), "Built-in persona reset as a new version.");

  const test = async () => {
    if (!sample.prompt.trim() || !sample.cognitivePolicy) return;
    setAction({ kind: "test", error: null, note: null });
    try {
      const result = await api.testPersona(persona.persona_id || persona.id, { prompt: sample.prompt.trim(), cognitive_policy: sample.cognitivePolicy });
      setTestResult(result);
      setAction({ kind: null, error: null, note: result.executed === false ? "Sample policy rendered without provider execution." : "Sample test returned a result." });
    } catch (error) {
      setAction({ kind: null, error, note: null });
    }
  };

  const affinityIds = [...new Set([
    ...Object.keys(draft.providerAffinities),
    ...providers.map((provider) => provider.provider_id || provider.id).filter(Boolean),
  ])];

  return <div className="persona-editor">
    <div className="persona-editor-head"><SelectField label="Persona to inspect" value={persona.persona_id || persona.id} onChange={setSelectedId}>{personas.map((record) => <option key={record.persona_id || record.id} value={record.persona_id || record.id}>{record.name || record.persona_id || record.id}</option>)}</SelectField><Pill tone={persona.built_in ? "green" : "amber"}>{persona.built_in ? "built-in · duplicate or reset" : "custom · editable"}</Pill></div>
    <p>{persona.description || "No persona description was supplied."} {version ? `Active version ${version.version}.` : "No active version was supplied."}</p>
    {action.error && <ErrorState error={action.error} title="The persona action did not complete." />}
    {action.note && <p className="save-note" role="status"><Check size={14} aria-hidden="true" /> {action.note}</p>}
    <section className="persona-duplicate"><label><span>Duplicate name</span><input value={duplicateName} onChange={(event) => setDuplicateName(event.target.value)} /></label><button type="button" className="button secondary" disabled={!duplicateName.trim() || Boolean(action.kind)} onClick={duplicate}>{action.kind === "duplicate" ? "Duplicating…" : "Duplicate persona"}</button></section>
    {version ? <>
      <section><h3>Structured communication controls</h3><label className="persona-name"><span>Name</span><input value={draft.name} disabled={!editable} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label><div className="persona-control-grid">{PERSONA_CONTROLS.map((control) => <SelectField key={control} label={label(control)} value={draft.controls[control] || "balanced"} disabled={!editable} onChange={(value) => setDraft((current) => ({ ...current, controls: { ...current.controls, [control]: value } }))}>{CONTROL_LEVELS.map((level) => <option key={level} value={level}>{label(level)}</option>)}</SelectField>)}</div></section>
      <section><h3>Provider affinities</h3>{affinityIds.length ? <div className="affinity-grid">{affinityIds.map((providerId) => <label key={providerId}><span>{providerId}</span><input type="number" min="-10" max="10" value={draft.providerAffinities[providerId] ?? 0} disabled={!editable} onChange={(event) => setDraft((current) => ({ ...current, providerAffinities: { ...current.providerAffinities, [providerId]: Number(event.target.value) } }))} /></label>)}</div> : <p>No provider affinities are recorded.</p>}</section>
      <section><h3>Policies and instructions</h3><div className="policy-grid">{COGNITIVE_POLICIES.map((policy) => <label key={policy}><input type="checkbox" checked={draft.allowedCognitivePolicies.includes(policy)} disabled={!editable} onChange={(event) => setDraft((current) => ({ ...current, allowedCognitivePolicies: event.target.checked ? [...current.allowedCognitivePolicies, policy] : current.allowedCognitivePolicies.filter((item) => item !== policy) }))} /><span>{label(policy)}</span></label>)}</div><label className="instructions-field"><span>Custom instructions</span><textarea rows="4" maxLength="2000" value={draft.customInstructions} disabled={!editable} onChange={(event) => setDraft((current) => ({ ...current, customInstructions: event.target.value }))} /></label>{editable && !draft.allowedCognitivePolicies.length && <p className="inline-error" role="alert">Select at least one allowed cognitive policy.</p>}</section>
      <div className="persona-actions">{editable && <button type="button" className="button primary" onClick={save} disabled={Boolean(action.kind) || !draft.name.trim() || !draft.allowedCognitivePolicies.length}>{action.kind === "save" ? "Saving…" : "Save new persona version"}</button>}{persona.built_in && <button type="button" className="button secondary" onClick={reset} disabled={Boolean(action.kind)}>{action.kind === "reset" ? "Resetting…" : "Reset built-in as new version"}</button>}</div>
      <section className="persona-test"><h3>Sample test</h3><p>Renders the selected policy for inspection; it does not invoke a provider.</p><textarea rows="2" value={sample.prompt} placeholder="Sample request" aria-label="Persona sample request" onChange={(event) => setSample((current) => ({ ...current, prompt: event.target.value }))} /><SelectField label="Sample cognitive policy" value={sample.cognitivePolicy} onChange={(cognitivePolicy) => setSample((current) => ({ ...current, cognitivePolicy }))}>{draft.allowedCognitivePolicies.map((policy) => <option key={policy} value={policy}>{label(policy)}</option>)}</SelectField><button type="button" className="button secondary" onClick={test} disabled={!sample.prompt.trim() || !sample.cognitivePolicy || Boolean(action.kind)}>{action.kind === "test" ? "Rendering…" : "Render sample policy"}</button>{testResult?.rendered_policy && <pre className="policy-result"><code>{testResult.rendered_policy}</code></pre>}</section>
    </> : <div className="unavailable-panel" role="note">This persona response did not include an active version, so structured editing is unavailable.</div>}
  </div>;
}

function DataControls() {
  const retention = useLoad(api.retention);
  const [exportState, setExportState] = useState({ loading: false, error: null, note: null });
  const download = async () => {
    setExportState({ loading: true, error: null, note: null });
    try {
      const data = await api.exportData();
      const blob = new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "opencobalt-personal-ai-export.json";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      setExportState({ loading: false, error: null, note: "Downloaded the private local snapshot. Execution receipt fields were redacted by the API." });
    } catch (error) {
      setExportState({ loading: false, error, note: null });
    }
  };
  return <section className="data-controls"><h2>Data export and retention</h2><p>The explicit export is private and contains local personal-AI records, including conversation and memory text. Execution receipt fields are redacted by the API, and the endpoint does not create a server-side export file.</p>{exportState.error && <ErrorState error={exportState.error} title="The data export did not complete." />}<button type="button" className="button secondary" onClick={download} disabled={exportState.loading}>{exportState.loading ? "Preparing download…" : "Download private JSON snapshot"}</button>{exportState.note && <p className="save-note" role="status"><Check size={14} aria-hidden="true" /> {exportState.note}</p>}{retention.loading && <Loading label="Loading retention limitations" />}{retention.error && <ErrorState error={retention.error} retry={retention.reload} title="Retention limitations could not be loaded." />}{retention.data && <div className="retention-note" role="note"><div className="pill-row"><Pill tone="neutral">bulk deletion unavailable</Pill><Pill tone="neutral">conversation deletion unavailable</Pill><Pill tone="green">individual curated memory deletion available</Pill></div><p>{retention.data.reason}</p><small>Memory deletion endpoint: <code>{retention.data.memory_deletion_endpoint}</code></small></div>}</section>;
}

function SettingsPage({ settings, onSettingsChange, personas, providers, reloadPersonas }) {
  const [draft, setDraft] = useState(settings);
  const [saveState, setSaveState] = useState({ saving: false, saved: false, error: null });
  useEffect(() => setDraft(settings), [settings]);
  const save = async (event) => {
    event.preventDefault();
    setSaveState({ saving: true, saved: false, error: null });
    try {
      const next = await api.updateSettings(draft);
      const savedSettings = { ...DEFAULT_SETTINGS, ...draft, ...(next || {}) };
      onSettingsChange(savedSettings);
      setSaveState({ saving: false, saved: true, error: null });
    } catch (error) {
      setSaveState({ saving: false, saved: false, error });
    }
  };
  return <section className="page"><PageTitle eyebrow="Settings" title="Local operating policy">Defaults shape a route; they do not grant authority or create an implicit fallback.</PageTitle>{saveState.error && <ErrorState error={saveState.error} title="Local settings were not saved." />}<form className="settings-form" onSubmit={save}>
    <section><h2>Interaction defaults</h2><SelectField label="Default persona" value={draft.default_persona_id} onChange={(default_persona_id) => setDraft({ ...draft, default_persona_id })}>{personas.map((persona) => <option key={persona.persona_id || persona.id} value={persona.persona_id || persona.id}>{persona.name || persona.display_name || persona.persona_id || persona.id}</option>)}</SelectField><SelectField label="Routing mode" value={draft.default_routing_mode} onChange={(default_routing_mode) => setDraft({ ...draft, default_routing_mode })}><option value="automatic">Automatic</option><option value="manual">Manual</option></SelectField><SelectField label="Theme" value={draft.theme} onChange={(theme) => setDraft({ ...draft, theme })}><option value="system">System</option><option value="dark">Dark</option><option value="light">Light</option></SelectField></section>
    <section><h2>Safety and retention</h2><Toggle label="Local-only by default" checked={draft.local_only_default} onChange={(local_only_default) => setDraft({ ...draft, local_only_default })} note="Blocks providers whose capability record requires network access." /><SelectField label="Privacy policy" value={draft.privacy_policy} onChange={(privacy_policy) => setDraft({ ...draft, privacy_policy })}><option value="standard">Standard</option><option value="private">Private</option><option value="sensitive">Sensitive</option></SelectField><SelectField label="Memory behavior" value={draft.memory_behavior} onChange={(memory_behavior) => setDraft({ ...draft, memory_behavior })}><option value="off">Off</option><option value="propose">Propose</option><option value="explicit_only">Explicit only</option></SelectField><SelectField label="Verification" value={draft.verification_preference} onChange={(verification_preference) => setDraft({ ...draft, verification_preference })}><option value="minimal">Minimal</option><option value="task_appropriate">Task appropriate</option><option value="strict">Strict</option></SelectField></section>
    <section><h2>Authority and cost</h2><SelectField label="Approval policy" value={draft.approval_policy} onChange={(approval_policy) => setDraft({ ...draft, approval_policy })}><option value="ask_for_risk">Ask for risk</option><option value="always_ask">Always ask</option><option value="deny_tools">Deny tools</option></SelectField><p className="setting-boundary">Chat is answer-only: tool and skill execution is blocked. “Always ask” also blocks model execution until an approval-resume lifecycle exists.</p><SelectField label="Cost ceiling" value={draft.cost_ceiling_category} onChange={(cost_ceiling_category) => setDraft({ ...draft, cost_ceiling_category })}><option value="free">Free</option><option value="low">Low</option><option value="standard">Standard</option><option value="high">High</option></SelectField><SelectField label="Skill permissions" value={draft.skill_permissions} onChange={(skill_permissions) => setDraft({ ...draft, skill_permissions })}><option value="deny">Deny</option><option value="ask">Ask</option><option value="allow_builtin">Allow built-in</option></SelectField><ProviderPriorityField value={draft.provider_priority} providers={providers} onChange={(provider_priority) => setDraft({ ...draft, provider_priority })} /></section>
    <div className="settings-save"><button className="button primary" type="submit" disabled={saveState.saving}><Save size={15} aria-hidden="true" /> {saveState.saving ? "Saving…" : "Save local settings"}</button>{saveState.saved && <span className="save-note" role="status"><Check size={14} aria-hidden="true" /> Saved by the local API</span>}</div>
  </form><section className="persona-note"><h2>Persona profiles</h2><p>Built-in profiles are versioned records. A provider-native profile is only applied when that provider is selected; another provider is disclosed as an approximation.</p><PersonaEditor personas={personas} providers={providers} defaultPersonaId={draft.default_persona_id} reloadPersonas={reloadPersonas} /></section><DataControls /></section>;
}

function CoreUnavailable({ error, retry, title = "Local API unavailable" }) {
  return <section className="page"><PageTitle eyebrow="Connection" title={title}>This view needs records from the local OpenCobalt API. No empty or successful state is inferred while that request is failing.</PageTitle><ErrorState error={error} retry={retry} title="The local API did not provide the required records." /></section>;
}

export default function App() {
  const [page, setPage] = useState(initialPage);
  const [navOpen, setNavOpen] = useState(false);
  const conversations = useLoad(api.conversations);
  const personas = useLoad(api.personas);
  const providers = useLoad(api.providers);
  const settingsRecord = useLoad(api.settings);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [dataEpoch, setDataEpoch] = useState(0);
  const [inspector, setInspector] = useState({ open: false, route: null, candidates: [], loading: false, error: null, rerunning: false, promoting: false, promoted: null });
  const inspectorRequestRef = useRef(0);
  const closeNavigation = useCallback(() => setNavOpen(false), []);

  useEffect(() => {
    if (settingsRecord.data) setSettings({ ...DEFAULT_SETTINGS, ...settingsRecord.data });
  }, [settingsRecord.data]);
  useEffect(() => {
    document.documentElement.dataset.theme = settings.theme || "system";
  }, [settings.theme]);
  useEffect(() => {
    const sync = () => setPage(initialPage());
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  const selectPage = useCallback((next) => {
    window.location.hash = next;
    setPage(next);
    setNavOpen(false);
  }, []);

  const closeInspector = useCallback(() => {
    inspectorRequestRef.current += 1;
    setInspector({ open: false, route: null, candidates: [], loading: false, error: null, rerunning: false, promoting: false, promoted: null });
  }, []);

  const openRoute = useCallback(async (routeId, optimisticRoute = null) => {
    const requestId = ++inspectorRequestRef.current;
    const route = optimisticRoute || { route_id: routeId || "not supplied" };
    setInspector({ open: true, route, candidates: optimisticRoute?.candidates || [], loading: Boolean(routeId), error: null, rerunning: false, promoting: false, promoted: null });
    if (!routeId) {
      setInspector((current) => ({ ...current, loading: false, error: new ApiError("No route identifier was supplied for inspection.") }));
      return;
    }
    try {
      const detail = await api.route(routeId);
      if (inspectorRequestRef.current !== requestId) return;
      const detailedRoute = routeFromDetail(detail);
      setInspector((current) => ({ ...current, route: detailedRoute, candidates: detail.candidates || detail.route_candidates || [], loading: false, error: null }));
    } catch (error) {
      if (inspectorRequestRef.current === requestId) setInspector((current) => ({ ...current, loading: false, error }));
    }
  }, []);

  const rerun = async (overrides = {}) => {
    const routeId = routeIdOf(inspector.route);
    if (!routeId) return;
    setInspector((current) => ({ ...current, rerunning: true, error: null }));
    try {
      const result = await api.rerunRoute(routeId, { allow_fallback: false, ...overrides });
      const rerunRoute = result?.route || result;
      const rerunRouteId = routeIdOf(rerunRoute);
      if (!rerunRouteId) throw new ApiError("The rerun response did not include a route identifier.", { detail: result });
      await openRoute(rerunRouteId, rerunRoute);
      await conversations.reload();
      setDataEpoch((current) => current + 1);
    } catch (error) {
      setInspector((current) => ({ ...current, error }));
    } finally {
      setInspector((current) => ({ ...current, rerunning: false }));
    }
  };

  const promote = async () => {
    const routeId = routeIdOf(inspector.route);
    if (!routeId) return;
    setInspector((current) => ({ ...current, promoting: true, error: null }));
    try {
      const result = await api.promoteRoute(routeId);
      if (!result.mission && !result.mission_id) throw new ApiError("The promotion response did not include a mission record.", { detail: result });
      setInspector((current) => ({ ...current, promoting: false, promoted: result }));
    } catch (error) {
      setInspector((current) => ({ ...current, promoting: false, error }));
    }
  };

  const coreRecords = [conversations, personas, providers, settingsRecord];
  const coreLoading = coreRecords.some((record) => record.loading && record.data === null);
  const coreError = coreRecords.find((record) => record.error)?.error || null;
  const controlPlaneStatus = coreLoading ? "connecting" : coreError ? "unavailable" : "connected";
  const retryCore = () => Promise.all(coreRecords.map((record) => record.reload().catch(() => undefined)));
  const chatError = conversations.error || personas.error || providers.error || settingsRecord.error;
  const chatLoading = coreRecords.some((record) => record.loading && record.data === null);

  let view;
  if (page === "chat") {
    view = chatLoading
      ? <Loading label="Opening local control plane" />
      : chatError
        ? <CoreUnavailable error={chatError} retry={retryCore} />
        : <ChatPage conversations={conversations.data || []} refreshConversations={conversations.reload} personas={personas.data || []} providers={providers.data || []} settings={settings} settingsReady={Boolean(settingsRecord.data)} openRoute={openRoute} refreshSignal={dataEpoch} />;
  } else if (page === "routes") {
    view = <RoutesPage key={`routes-${dataEpoch}`} openRoute={openRoute} />;
  } else if (page === "missions") {
    view = <MissionsPage />;
  } else if (page === "skills") {
    view = <SkillsPage />;
  } else if (page === "memory") {
    view = <MemoryPage />;
  } else if (page === "ledger") {
    view = <LedgerPage />;
  } else if (page === "providers") {
    view = providers.loading
      ? <Loading label="Loading provider capability records" />
      : providers.error
        ? <CoreUnavailable error={providers.error} retry={providers.reload} title="Provider records unavailable" />
        : <ProvidersPage providers={providers.data || []} reloadProviders={providers.reload} />;
  } else {
    const settingsError = settingsRecord.error || personas.error;
    view = settingsRecord.loading || personas.loading
      ? <Loading label="Loading local settings" />
      : settingsError
        ? <CoreUnavailable error={settingsError} retry={retryCore} title="Settings records unavailable" />
        : <SettingsPage settings={settings} onSettingsChange={setSettings} personas={personas.data || []} providers={providers.data || []} reloadPersonas={personas.reload} />;
  }

  return <div className="app-shell">
    <Navigation active={page} onSelect={selectPage} open={navOpen} onClose={closeNavigation} status={controlPlaneStatus} />
    {navOpen && <button type="button" className="drawer-backdrop nav-backdrop" aria-label="Close navigation" onClick={closeNavigation} />}
    <div className="mobile-nav"><IconButton label="Open navigation" aria-expanded={navOpen} aria-controls="primary-navigation" onClick={() => setNavOpen(true)}><PanelRightOpen size={18} /></IconButton><span>OpenCobalt</span><span className="mobile-status"><span className="live-dot" data-state={controlPlaneStatus} aria-hidden="true" /><span className="visually-hidden">{controlPlaneStatus === "connected" ? "Local API connected" : controlPlaneStatus === "unavailable" ? "Local API unavailable" : "Checking local API"}</span></span></div>
    {coreError && <div className="api-banner" role="alert"><div><strong>Local API degraded</strong><span>{coreError.message}</span></div><button type="button" className="text-button" onClick={retryCore}>Retry core records</button></div>}
    <main className={`app-content ${inspector.open ? "inspector-open" : ""}`}>{view}</main>
    {inspector.open && <><button type="button" className="inspector-backdrop" aria-label="Close route inspector" onClick={closeInspector} /><RouteInspector route={inspector.route} candidates={inspector.candidates} providers={providers.data || []} personas={personas.data || []} onClose={closeInspector} onRerun={rerun} rerunning={inspector.rerunning} onPromote={promote} promoting={inspector.promoting} promoted={inspector.promoted} loading={inspector.loading} error={inspector.error} /></>}
  </div>;
}

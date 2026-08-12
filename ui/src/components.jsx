import React, { useEffect, useRef, useState } from "react";
import {
  BookOpen, Bot, BrainCircuit, ChevronRight, Clock3, Database,
  FileKey2, Layers3, MessageSquareText, Network, PanelRight, Plus,
  Route, Settings2, ShieldCheck, Sparkles, Wrench, X,
} from "lucide-react";

export const NAVIGATION = [
  ["chat", "Chat", MessageSquareText],
  ["routes", "Routes", Route],
  ["missions", "Missions", Layers3],
  ["skills", "Skills", Wrench],
  ["memory", "Memory", BrainCircuit],
  ["ledger", "Ledger", Database],
  ["providers", "Providers", Network],
  ["settings", "Settings", Settings2],
];

export function CobaltMark() {
  return <div className="cobalt-mark" role="img" aria-label="OpenCobalt">OC</div>;
}

export function IconButton({ label, children, className = "", ...props }) {
  return <button type="button" className={`icon-button ${className}`} aria-label={label} title={label} {...props}>{children}</button>;
}

const CONTROL_PLANE_LABELS = {
  connected: "local API connected",
  connecting: "checking local API",
  unavailable: "local API unavailable",
};

export function Navigation({ active, onSelect, open = false, onClose, status = "connecting" }) {
  const navigationRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = document.activeElement;
    const navigation = navigationRef.current;
    navigation?.querySelector(".nav-link")?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !navigation) return;
      const focusable = [...navigation.querySelectorAll("button:not([disabled]), [href], [tabindex]:not([tabindex='-1'])")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [open, onClose]);

  const select = (id) => {
    onSelect(id);
    onClose?.();
  };

  return <nav ref={navigationRef} id="primary-navigation" className={`navigation ${open ? "is-open" : ""}`} aria-label="Primary navigation">
    <div className="brand"><CobaltMark /><span>OpenCobalt</span><IconButton className="nav-close" label="Close navigation" onClick={onClose}><X size={17} /></IconButton></div>
    <div className="nav-links">
      {NAVIGATION.map(([id, navLabel, Icon]) => (
        <button type="button" key={id} className={`nav-link ${active === id ? "is-active" : ""}`} aria-current={active === id ? "page" : undefined} onClick={() => select(id)}>
          <Icon aria-hidden="true" size={16} /><span>{navLabel}</span>
        </button>
      ))}
    </div>
    <div className="rail-foot" role="status" aria-live="polite"><span className="live-dot" data-state={status} aria-hidden="true" />{CONTROL_PLANE_LABELS[status] || CONTROL_PLANE_LABELS.connecting}</div>
  </nav>;
}

export function PageTitle({ eyebrow, title, children }) {
  return <header className="page-title"><p className="eyebrow">{eyebrow}</p><div><h1>{title}</h1>{children}</div></header>;
}

export function EmptyState({ title, children, action }) {
  return <div className="empty-state"><Sparkles size={18} aria-hidden="true" /><h2>{title}</h2>{children && <p>{children}</p>}{action}</div>;
}

export function ErrorState({ error, retry, title = "Could not load this local record." }) {
  const tryAgain = () => Promise.resolve(retry?.()).catch(() => undefined);
  return <div className="error-state" role="alert"><strong>{title}</strong><p>{error?.message || "The request did not complete."}</p>{retry && <button type="button" className="text-button" onClick={tryAgain}>Try again</button>}</div>;
}

export function Loading({ label = "Loading local records" }) {
  return <div className="loading-state" role="status" aria-live="polite"><span className="loading-rule" aria-hidden="true" />{label}</div>;
}

export function Pill({ tone = "neutral", children }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

export function DetailRow({ label, value, mono = false }) {
  if (value === undefined || value === null || value === "") return null;
  return <div className="detail-row"><span>{label}</span><strong className={mono ? "mono" : ""}>{String(value)}</strong></div>;
}

function compact(value) {
  if (!value) return "not recorded";
  return String(value).replaceAll("_", " ");
}

function compactId(value) {
  if (!value) return "not recorded";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-5)}` : text;
}

export function RouteSpine({ route, onInspect }) {
  if (!route) return null;
  const routeId = route.route_id || route.id;
  const receipt = route.receipt_id || route.work_receipt_id;
  const verificationRecord = route.verification || route.metadata?.verification;
  const verification = route.provenance_error ? "unavailable" : route.verification_status || verificationRecord?.status || route.verification_strategy;
  const receiptLabel = receipt ? compactId(receipt) : route.provenance_error ? "unavailable" : "not recorded";
  return <button type="button" className="route-spine" onClick={onInspect} aria-label={`Inspect route ${routeId || "decision"}`}>
    <span className="spine-node"><MessageSquareText size={12} aria-hidden="true" /></span>
    <span><small>request</small><b>{compact(route.task_class || route.request_classification || "recorded")}</b></span>
    <ChevronRight size={14} aria-hidden="true" />
    <span><small>route</small><b title={routeId || undefined}>{compactId(routeId)}</b></span>
    <ChevronRight size={14} aria-hidden="true" />
    <span><small>receipt integrity · {compact(verification)}</small><b title={receipt || undefined}>{receiptLabel}</b></span>
  </button>;
}

export function RouteInspector({ route, candidates = [], providers = [], personas = [], onClose, onRerun, rerunning, onPromote, promoting, promoted, loading = false, error = null }) {
  const dialogRef = useRef(null);
  const isOpen = Boolean(route);
  const [rerunOptions, setRerunOptions] = useState({
    persona_id: "",
    provider_id: "",
    model_id: "",
    reasoning_effort: "",
    cognitive_policy: "",
    local_only: "",
    allow_fallback: false,
  });

  useEffect(() => {
    setRerunOptions({
      persona_id: "",
      provider_id: "",
      model_id: "",
      reasoning_effort: "",
      cognitive_policy: "",
      local_only: "",
      allow_fallback: false,
    });
  }, [route?.route_id]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const previouslyFocused = document.activeElement;
    const dialog = dialogRef.current;
    dialog?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = [...dialog.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [isOpen, onClose]);

  if (!route) return null;
  const reasons = route.reasons || route.selection_reasons || [];
  const tools = route.selected_tools || route.tools || [];
  const skills = route.selected_skills || route.skills || [];
  const receipt = route.receipt_id || route.work_receipt_id;
  const verificationRecord = route.verification || route.metadata?.verification;
  const verification = route.verification_status || verificationRecord?.status || route.verification_strategy;
  const verificationChecks = verificationRecord?.checks_performed || verificationRecord?.checks || [];
  const verificationLimitations = verificationRecord?.limitations || [];
  const actualPersona = route.actual_persona_id || route.selected_persona_id || route.persona_id;
  const executions = Array.isArray(route.executions) ? route.executions : [];
  const actualProvider = route.actual_provider_id
    || route.metadata?.actual_provider_id
    || route.execution?.provider_id
    || executions.at(-1)?.provider_id;
  const actualModel = route.actual_model_id
    || route.metadata?.actual_model_id
    || route.execution?.model_id
    || executions.at(-1)?.model_id;
  const approvalRequirements = route.approval_requirements || [];
  const fallbackEvents = Array.isArray(route.fallback_events) ? route.fallback_events : [];
  const streamEvents = Array.isArray(route.stream_events) ? route.stream_events : [];
  const actualUsage = route.actual_usage && Object.keys(route.actual_usage).length
    ? Object.entries(route.actual_usage).map(([key, value]) => `${compact(key)}: ${String(value)}`).join(" · ")
    : "not reported";
  const providerIsChatEligible = (provider) => Boolean(
    provider?.installed
    && provider?.execution_supported
    && provider?.capabilities?.answer_only_isolation
    && provider?.enabled !== false
  );
  const recordedProviderId = route.selected_provider || route.provider_id;
  const effectiveRerunProviderId = rerunOptions.provider_id || recordedProviderId;
  const effectiveRerunProvider = providers.find(
    (provider) => (provider.provider_id || provider.id) === effectiveRerunProviderId
  );
  const rerunProviderEligible = providerIsChatEligible(effectiveRerunProvider);
  const rerunPayload = Object.fromEntries(
    Object.entries(rerunOptions)
      .map(([key, value]) => [key, typeof value === "string" ? value.trim() : value])
      .filter(([, value]) => value !== "")
  );

  return <div ref={dialogRef} className="route-inspector" role="dialog" aria-modal="true" aria-labelledby="route-inspector-title" tabIndex="-1">
    <div className="inspector-heading"><div><p className="eyebrow">{receipt ? "Route and receipt" : "Route decision"}</p><h2 id="route-inspector-title">Decision record</h2></div><IconButton label="Close inspector" onClick={onClose}><X size={17} /></IconButton></div>
    <div className="route-sequence" aria-label={receipt ? "Request to route to receipt" : "Request to recorded route without execution receipt"}><span>request</span><ChevronRight size={13} aria-hidden="true"/><span>route</span><ChevronRight size={13} aria-hidden="true"/><span>{receipt ? "receipt" : "not executed"}</span></div>
    {loading && <Loading label="Loading route provenance" />}
    {error && <ErrorState error={error} title="Could not load full route provenance." />}
    {route.request_message?.content && <section className="route-request" aria-label="Original request"><h3>Original request</h3><p>{route.request_message.content}</p></section>}
    <section aria-label="Route provenance">
      <DetailRow label="Route ID" value={route.route_id || route.id} mono />
      <DetailRow label="Request ID" value={route.request_id} mono />
      <DetailRow label="Conversation ID" value={route.conversation_id} mono />
      <DetailRow label="Receipt ID" value={receipt || "not recorded"} mono />
      <DetailRow label="Integrity result" value={compact(verification)} />
      <DetailRow label="Task" value={compact(route.task_class)} />
      <DetailRow label="Complexity" value={compact(route.task_complexity)} />
      <DetailRow label="Selected provider" value={route.selected_provider || route.provider_id} />
      <DetailRow label="Actual provider" value={actualProvider || "not recorded"} />
      <DetailRow label="Selected model" value={route.selected_model || route.model_id || "not specified"} />
      <DetailRow label="Actual model" value={actualModel || "not recorded"} />
      <DetailRow label="Agent runtime" value={route.selected_runtime || "direct provider adapter"} />
      <DetailRow label="Requested persona" value={route.requested_persona_id} />
      <DetailRow label="Requested persona version" value={route.requested_persona_version_id} mono />
      <DetailRow label="Actual persona" value={actualPersona} />
      <DetailRow label="Actual persona version" value={route.actual_persona_version_id} mono />
      <DetailRow label="Privacy" value={compact(route.privacy_classification || route.privacy_mode)} />
      <DetailRow label="Autonomy" value={compact(route.autonomy_level)} />
      <DetailRow label="Estimated cost" value={compact(route.estimated_cost_category)} />
      <DetailRow label="Known usage" value={actualUsage} />
      <DetailRow label="Expected latency" value={compact(route.expected_latency_category)} />
      <DetailRow label="Outcome" value={compact(route.outcome_status)} />
      <DetailRow label="Heuristic points" value={route.route_score} mono />
      <DetailRow label="Created" value={route.created_at ? new Date(route.created_at).toLocaleString() : null} />
      <DetailRow label="Updated" value={route.updated_at ? new Date(route.updated_at).toLocaleString() : null} />
    </section>
    {route.persona_provider_mismatch && <div className="notice amber" role="note">{route.persona_provider_mismatch}</div>}
    {approvalRequirements.length > 0 && <section><h3>Approval boundary</h3><ul className="reason-list">{approvalRequirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul></section>}
    {reasons.length > 0 && <section><h3>Why this route</h3><ul className="reason-list">{reasons.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}</ul></section>}
    <section><h3>Verification boundary</h3><p className="route-note">Strategy: {compact(route.verification_strategy || "not recorded")}</p>{verificationChecks.length > 0 && <ul className="reason-list">{verificationChecks.map((check, index) => <li key={`${check}-${index}`}>{typeof check === "string" ? compact(check) : JSON.stringify(check)}</li>)}</ul>}{verificationLimitations.length > 0 && <ul className="reason-list">{verificationLimitations.map((limitation, index) => <li key={`${limitation}-${index}`}>{limitation}</li>)}</ul>}{verificationLimitations.length === 0 && route.verification_strategy === "response_integrity" && <p className="route-note">Response integrity does not verify factual correctness.</p>}</section>
    {fallbackEvents.length > 0 && <section><h3>Fallback history</h3><div className="event-history">{fallbackEvents.map((fallback, index) => <article key={`${fallback.created_at || "fallback"}-${index}`}><b>{fallback.from_provider || "unknown"} → {fallback.to_provider || "unknown"}</b><span>{fallback.reason_category ? `${compact(fallback.reason_category)} · ` : ""}{fallback.reason || "No reason recorded"}</span><code>{fallback.failed_receipt_id || "failed receipt not recorded"}</code></article>)}</div></section>}
    {streamEvents.length > 0 && <section><h3>Durable execution events</h3><div className="event-history">{streamEvents.map((event) => <article key={event.event_id || `${event.execution_id}-${event.sequence}`}><b>{compact(event.event_type)}</b><span>Execution {compactId(event.execution_id)} · sequence {event.sequence}</span><code>{event.created_at ? new Date(event.created_at).toLocaleString() : "time not recorded"}</code></article>)}</div></section>}
    {(tools.length > 0 || skills.length > 0) && <section><h3>Tools and skills</h3><div className="pill-row">{tools.map((tool) => <Pill key={`tool-${tool}`}>{tool}</Pill>)}{skills.map((skill) => <Pill key={`skill-${skill}`}>{skill}</Pill>)}</div></section>}
    {candidates.length > 0 && <section><h3>Alternatives considered</h3>{candidates.map((candidate) => <details className="candidate" key={candidate.candidate_id || `${candidate.provider_id}-${candidate.model_id || "default"}`}><summary><span>{candidate.provider_id}{candidate.model_id ? ` · ${candidate.model_id}` : ""}</span><b>{candidate.eligible === false ? "not eligible" : `${candidate.score ?? "—"} pts`}</b></summary><div>{candidate.rejection_reason && <p className="inline-error">{candidate.rejection_reason}</p>}{candidate.score_components && <dl className="score-components">{Object.entries(candidate.score_components).map(([name, points]) => <React.Fragment key={name}><dt>{compact(name)}</dt><dd>{points} pts</dd></React.Fragment>)}</dl>}{candidate.reasons?.length > 0 && <ul className="reason-list">{candidate.reasons.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}</ul>}</div></details>)}</section>}
    {!receipt && <div className="notice amber" role="note">This decision stopped before provider execution, so it has no execution receipt. The route and rejection reasons remain recorded.</div>}
    {promoted && <div className="notice success" role="status">Planning mission {promoted.mission?.mission_id || promoted.mission_id || "created"} was created. No mission step was executed.</div>}
    <section className="rerun-controls" aria-labelledby="rerun-heading"><h3 id="rerun-heading">Rerun controls</h3><p>Blank choices preserve the recorded route. A rerun creates a new decision and links an execution receipt only when a provider invocation starts.</p><div className="rerun-grid"><label><span>Persona</span><select aria-label="Rerun persona" value={rerunOptions.persona_id} onChange={(event) => setRerunOptions((current) => ({ ...current, persona_id: event.target.value }))}><option value="">Keep {route.requested_persona_id || "recorded persona"}</option>{personas.map((persona) => <option key={persona.persona_id || persona.id} value={persona.persona_id || persona.id}>{persona.name || persona.persona_id || persona.id}</option>)}</select></label><label><span>Provider</span><select aria-label="Rerun provider" value={rerunOptions.provider_id} onChange={(event) => setRerunOptions((current) => ({ ...current, provider_id: event.target.value, model_id: "" }))}><option value="" disabled={!providerIsChatEligible(providers.find((provider) => (provider.provider_id || provider.id) === recordedProviderId))}>Keep {recordedProviderId || "recorded provider"}{providerIsChatEligible(providers.find((provider) => (provider.provider_id || provider.id) === recordedProviderId)) ? "" : " — Chat unavailable"}</option>{providers.map((provider) => { const providerId = provider.provider_id || provider.id; const chatEligible = providerIsChatEligible(provider); return <option key={providerId} value={providerId} disabled={!chatEligible}>{provider.display_name || providerId}{chatEligible ? "" : " — Chat unavailable"}</option>; })}</select></label><label><span>Model override</span><input aria-label="Rerun model override" value={rerunOptions.model_id} maxLength="200" placeholder="Keep provider default" onChange={(event) => setRerunOptions((current) => ({ ...current, model_id: event.target.value }))} /></label><label><span>Cognitive policy</span><select aria-label="Rerun cognitive policy" value={rerunOptions.cognitive_policy} onChange={(event) => setRerunOptions((current) => ({ ...current, cognitive_policy: event.target.value }))}><option value="">Keep recorded policy</option><option value="fast_answer">Fast answer</option><option value="deep_analysis">Deep analysis</option><option value="skeptical_review">Skeptical review</option><option value="creative_divergence">Creative divergence</option><option value="decision_support">Decision support</option><option value="emotional_reflection">Emotional reflection</option><option value="implementation">Implementation</option><option value="research_synthesis">Research synthesis</option></select></label><label><span>Reasoning effort</span><select aria-label="Rerun reasoning effort" value={rerunOptions.reasoning_effort} onChange={(event) => setRerunOptions((current) => ({ ...current, reasoning_effort: event.target.value }))}><option value="">Keep recorded effort</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">Extra high</option></select></label><label><span>Local-only policy</span><select aria-label="Rerun local-only policy" value={rerunOptions.local_only} onChange={(event) => setRerunOptions((current) => ({ ...current, local_only: event.target.value === "" ? "" : event.target.value === "true" }))}><option value="">Keep recorded boundary</option><option value="true">Require local only</option><option value="false">Allow eligible cloud routes</option></select></label></div><label className="check-control"><input type="checkbox" checked={rerunOptions.allow_fallback} onChange={(event) => setRerunOptions((current) => ({ ...current, allow_fallback: event.target.checked }))} /><span>Allow an explicit, recorded fallback</span></label>{!rerunProviderEligible && <div className="notice amber" role="note">Choose a provider with a proven answer-only Chat boundary before rerunning this recorded route.</div>}</section>
    <div className="inspector-actions"><button type="button" className="button secondary" onClick={() => onRerun(rerunPayload)} disabled={rerunning || promoting || loading || !rerunProviderEligible}>{rerunning ? "Rerunning…" : "Rerun with controls"}</button><button type="button" className="button secondary" onClick={onPromote} disabled={promoting || rerunning || loading || Boolean(promoted)}>{promoting ? "Creating plan…" : promoted ? "Planning mission created" : "Promote to planning mission"}</button></div>
  </div>;
}

export function ConversationRail({ conversations, selectedId, onSelect, onCreate, isCreating, disabled = false, mobileOpen = false, onClose }) {
  const railRef = useRef(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [draft, setDraft] = useState({ title: "New conversation", project_path: "" });
  useEffect(() => {
    if (!mobileOpen) return undefined;
    const previouslyFocused = document.activeElement;
    railRef.current?.querySelector("button")?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !railRef.current) return;
      const focusable = [...railRef.current.querySelectorAll("button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [mobileOpen, onClose]);

  const select = (conversationId) => {
    onSelect(conversationId);
    onClose?.();
  };

  const create = async (event) => {
    event.preventDefault();
    const created = await onCreate({
      title: draft.title.trim() || "New conversation",
      project_path: draft.project_path.trim() || null,
    });
    if (created !== false) {
      setCreateOpen(false);
      setDraft({ title: "New conversation", project_path: "" });
    }
  };

  return <aside ref={railRef} id="conversation-navigation" className={`conversation-rail ${mobileOpen ? "is-mobile-open" : ""}`} role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen ? "true" : undefined} aria-label="Conversations">
    <div className="rail-heading"><div><p className="eyebrow">Conversations</p><h2>Working set</h2></div><div className="rail-actions"><IconButton label="New conversation" aria-expanded={createOpen} aria-controls="conversation-create" onClick={() => setCreateOpen((current) => !current)} disabled={isCreating || disabled}><Plus size={17} /></IconButton><IconButton className="conversation-close" label="Close conversations" onClick={onClose}><X size={17} /></IconButton></div></div>
    {createOpen && <form id="conversation-create" className="conversation-create" onSubmit={create}><label><span>Title</span><input value={draft.title} maxLength="200" onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} /></label><label><span>Workspace path</span><input value={draft.project_path} maxLength="4096" placeholder="Current workspace or a subdirectory" onChange={(event) => setDraft((current) => ({ ...current, project_path: event.target.value }))} /></label><small>Paths are canonicalized and must stay inside the workspace where OpenCobalt was started.</small><div><button type="button" className="text-button" onClick={() => setCreateOpen(false)}>Cancel</button><button type="submit" className="button primary" disabled={isCreating || !draft.title.trim()}>{isCreating ? "Creating…" : "Create"}</button></div></form>}
    <div className="conversation-list">{conversations.map((conversation) => {
      const conversationId = conversation.conversation_id || conversation.id;
      const selected = conversationId === selectedId;
      return <button type="button" key={conversationId} className={`conversation-item ${selected ? "is-selected" : ""}`} aria-current={selected ? "true" : undefined} disabled={disabled} onClick={() => select(conversationId)}><b>{conversation.title || "Untitled conversation"}</b><span>{conversation.updated_at ? new Date(conversation.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "local"}</span></button>;
    })}</div>
    {!conversations.length && <p className="rail-empty">Create a conversation to keep each decision, response, and any execution receipt together.</p>}
  </aside>;
}

export const panelIcons = { missions: Layers3, skills: Wrench, memory: BrainCircuit, ledger: FileKey2, providers: Network, settings: Settings2, route: Route, privacy: ShieldCheck, time: Clock3, persona: Bot, book: BookOpen, right: PanelRight };

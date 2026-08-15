import React, { useEffect, useRef, useState } from "react";
import {
  BookOpen, Bot, BrainCircuit, Clock3, Database,
  FileKey2, Layers3, MessageSquareText, Network, PanelRight, Plus,
  Route, Settings2, ShieldCheck, Wrench, X,
} from "lucide-react";

export const WORK_NAVIGATION = [
  ["chat", "Chat", MessageSquareText],
  ["missions", "Missions", Layers3],
  ["memory", "Memory", BrainCircuit],
];

export const SYSTEM_NAVIGATION = [
  ["routes", "Routes", Route],
  ["ledger", "Ledger", Database],
  ["skills", "Skills", Wrench],
  ["providers", "Providers", Network],
  ["settings", "Settings", Settings2],
];

export const NAVIGATION = [...WORK_NAVIGATION, ...SYSTEM_NAVIGATION];
const SYSTEM_IDS = new Set(SYSTEM_NAVIGATION.map(([id]) => id));

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

export function Navigation({ active, onSelect, open = false, onClose, onCollapse, status = "connecting" }) {
  const navigationRef = useRef(null);
  const [systemOpen, setSystemOpen] = useState(() => SYSTEM_IDS.has(active));
  useEffect(() => {
    if (SYSTEM_IDS.has(active)) setSystemOpen(true);
  }, [active]);
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
    <div className="brand"><CobaltMark /><span>OpenCobalt</span><IconButton className="nav-collapse" label="Collapse navigation" onClick={onCollapse}><PanelRight size={17} /></IconButton><IconButton className="nav-close" label="Close navigation" onClick={onClose}><X size={17} /></IconButton></div>
    <div className="nav-links">
      <p className="nav-section-label">Work</p>
      {WORK_NAVIGATION.map(([id, navLabel, Icon]) => (
        <button type="button" key={id} className={`nav-link ${active === id ? "is-active" : ""}`} aria-current={active === id ? "page" : undefined} onClick={() => select(id)}>
          <Icon aria-hidden="true" size={16} /><span>{navLabel}</span>
        </button>
      ))}
      <details className="nav-system" open={systemOpen} onToggle={(event) => setSystemOpen(event.currentTarget.open)}>
        <summary>System</summary>
        {SYSTEM_NAVIGATION.map(([id, navLabel, Icon]) => (
          <button type="button" key={id} className={`nav-link ${active === id ? "is-active" : ""}`} aria-current={active === id ? "page" : undefined} onClick={() => select(id)}>
            <Icon aria-hidden="true" size={16} /><span>{navLabel}</span>
          </button>
        ))}
      </details>
    </div>
    <div className="rail-foot" role="status" aria-live="polite"><span className="live-dot" data-state={status} aria-hidden="true" />{CONTROL_PLANE_LABELS[status] || CONTROL_PLANE_LABELS.connecting}</div>
  </nav>;
}

export function PageTitle({ eyebrow, title, children }) {
  return <header className="page-title"><p className="eyebrow">{eyebrow}</p><div><h1>{title}</h1>{children}</div></header>;
}

export function EmptyState({ title, children, action }) {
  return <div className="empty-state"><h2>{title}</h2>{children && <p>{children}</p>}{action}</div>;
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
  if (value === 0) return "0";
  if (!value) return "not recorded";
  return String(value).replaceAll("_", " ");
}

function formatPoints(points) {
  const value = Number(points);
  if (!Number.isFinite(value)) return String(points);
  const signed = value > 0 ? `+${value}` : String(value);
  return `${signed} pts`;
}

function scoreComponentEntries(components) {
  if (!components || typeof components !== "object" || Array.isArray(components)) return [];
  return Object.entries(components).filter(([, points]) => {
    const value = Number(points);
    return Number.isFinite(value) && value !== 0;
  });
}

function visibleReasons(reasons) {
  if (!Array.isArray(reasons)) return [];
  return reasons.map((reason) => String(reason || "").trim()).filter(Boolean);
}

function compactId(value) {
  if (!value) return "not recorded";
  const text = String(value);
  return text.length > 18 ? `${text.slice(0, 10)}…${text.slice(-5)}` : text;
}

const TASK_LABELS = {
  general_reasoning: "General",
  research: "Research",
  coding: "Coding",
  repository_execution: "Repository",
  security_review: "Security review",
  multi_step_mission: "Multi-step",
  tool_operation: "Tool",
  data_analysis: "Data",
  file_analysis: "Document",
  personal_reflection: "Reflection",
  consequential_decision: "Decision",
};

const BILLING_LABELS = {
  local: "Local",
  subscription_backed: "Subscription",
  api_billed: "API billed",
};

function taskLabel(value) {
  const key = String(value || "");
  return TASK_LABELS[key] || compact(value);
}

function billingLabel(route) {
  const billing = route?.metadata?.billing_classification;
  return BILLING_LABELS[billing] || "";
}

function usedProvider(route) {
  return route.actual_provider_id
    || route.metadata?.actual_provider_id
    || route.execution?.provider_id
    || route.selected_provider
    || route.provider_id
    || "";
}

function usedModel(route) {
  return route.actual_model_id
    || route.metadata?.actual_model_id
    || route.execution?.model_id
    || route.selected_model
    || route.model_id
    || "";
}

function integrityLabel(value) {
  const text = compact(value);
  if (text === "passed" || text === "ok") return "Receipt integrity passed";
  if (text === "unavailable") return "Receipt integrity unavailable";
  if (text === "not recorded") return "Receipt not recorded";
  return `Receipt integrity: ${text}`;
}

export function RouteSpine({ route, onInspect, missionId, onOpenMission }) {
  if (!route) return null;
  const routeId = route.route_id || route.id;
  const provider = usedProvider(route) || "OpenCobalt";
  const model = usedModel(route);
  const fallback = Array.isArray(route.fallback_events) && route.fallback_events.length > 0;
  const failed = ["failed", "route_failed", "policy_denied"].includes(String(route.outcome_status || ""));
  const billing = billingLabel(route);
  const localOnly = Boolean(route.metadata?.local_only);
  const secondary = [
    taskLabel(route.task_class || route.request_classification),
    billing,
    localOnly ? "Local only" : "",
    fallback ? "Fallback" : "",
    failed ? "Failed" : "",
  ].filter(Boolean).join(" · ");
  return <div className="route-affordance">
    <button type="button" className={`route-spine${failed ? " is-alert" : ""}${fallback ? " is-fallback" : ""}`} onClick={onInspect} aria-label={`Inspect how OpenCobalt handled this response`}>
      <span className="spine-primary">{provider}{model ? ` · ${model}` : ""}</span>
      <span className="spine-secondary">{secondary}</span>
      <span className="spine-action">Details</span>
    </button>
    {missionId && onOpenMission ? <button type="button" className="text-button mission-link" onClick={() => onOpenMission(missionId)}>Open Mission</button> : null}
  </div>;
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
  const reasons = visibleReasons(route.reasons || route.selection_reasons);
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
  const acpPermissions = Array.isArray(route.metadata?.acp_permissions) ? route.metadata.acp_permissions : [];
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

  const billing = billingLabel(route);
  const summaryReasons = reasons.slice(0, 3);

  return <div ref={dialogRef} className="route-inspector" role="dialog" aria-modal="true" aria-labelledby="route-inspector-title" tabIndex="-1">
    <div className="inspector-heading"><div><p className="eyebrow">{receipt ? "How this was handled" : "Route decision"}</p><h2 id="route-inspector-title">Details</h2></div><IconButton label="Close inspector" onClick={onClose}><X size={17} /></IconButton></div>
    {loading && <Loading label="Loading route provenance" />}
    {error && <ErrorState error={error} title="Could not load full route provenance." />}
    {route.request_message?.content && <section className="route-request" aria-label="Original request"><h3>Request</h3><p>{route.request_message.content}</p></section>}
    <section className="inspector-summary" aria-label="Summary">
      <DetailRow label="Used" value={[actualProvider || recordedProviderId || "not recorded", actualModel].filter(Boolean).join(" · ")} />
      <DetailRow label="Task" value={taskLabel(route.task_class)} />
      <DetailRow label="Outcome" value={compact(route.outcome_status)} />
      <DetailRow label="Privacy" value={compact(route.privacy_classification || route.privacy_mode)} />
      {billing ? <DetailRow label="Cost" value={billing} /> : <DetailRow label="Cost category" value={compact(route.estimated_cost_category)} />}
      <DetailRow label="Local only" value={route.metadata?.local_only ? "Yes" : "No"} />
      <DetailRow label="Receipt" value={receipt ? "Execution recorded" : "Not recorded"} />
      <DetailRow label="Integrity" value={integrityLabel(route.provenance_error ? "unavailable" : verification)} />
    </section>
    {summaryReasons.length > 0 && <section><h3>Why this route</h3><ul className="reason-list">{summaryReasons.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}</ul>{reasons.length > 3 ? <p className="route-note">{reasons.length - 3} additional recorded reasons are in routing details.</p> : null}</section>}
    {fallbackEvents.length > 0 && <section><h3>Fallback</h3><div className="event-history">{fallbackEvents.map((fallback, index) => <article key={`${fallback.created_at || "fallback"}-${index}`}><b>{fallback.from_provider || "unknown"} → {fallback.to_provider || "unknown"}</b><span>{fallback.reason_category ? `${compact(fallback.reason_category)} · ` : ""}{fallback.reason || "No reason recorded"}</span></article>)}</div></section>}
    {route.persona_provider_mismatch && <div className="notice amber" role="note">{route.persona_provider_mismatch}</div>}
    {!receipt && <div className="notice amber" role="note">This decision stopped before provider execution, so it has no execution receipt. The route and rejection reasons remain recorded.</div>}
    <p className="route-note">Receipt integrity checks that a response is linked to a recorded execution. It does not prove the answer is factually true.</p>
    <details className="inspector-block"><summary>Routing details</summary><div>
      <DetailRow label="Selected provider" value={route.selected_provider || route.provider_id} />
      <DetailRow label="Actual provider" value={actualProvider || "not recorded"} />
      <DetailRow label="Selected model" value={route.selected_model || route.model_id || "not specified"} />
      <DetailRow label="Actual model" value={actualModel || "not recorded"} />
      <DetailRow label="Persona" value={actualPersona} />
      <DetailRow label="Complexity" value={compact(route.task_complexity)} />
      <DetailRow label="Capability role" value={compact(route.metadata?.capability_role || route.capability_role)} />
      <DetailRow label="Domain" value={compact(route.metadata?.domain)} />
      <DetailRow label="Reasoning quality need" value={compact(route.metadata?.reasoning_quality)} />
      <DetailRow label="Factual sensitivity" value={compact(route.metadata?.factual_sensitivity)} />
      <DetailRow label="Freshness need" value={compact(route.metadata?.freshness_requirement)} />
      <DetailRow label="Known usage" value={actualUsage} />
      <DetailRow label="Heuristic points" value={route.route_score} mono />
      {reasons.length > 3 && <ul className="reason-list">{reasons.slice(3).map((reason, index) => <li key={`${reason}-extra-${index}`}>{reason}</li>)}</ul>}
      {candidates.length > 0 && <div className="inspector-candidates">{candidates.map((candidate) => {
        const componentEntries = scoreComponentEntries(candidate.score_components);
        const reasonItems = visibleReasons(candidate.reasons);
        return <details className="candidate" key={candidate.candidate_id || `${candidate.provider_id}-${candidate.model_id || "default"}`}><summary><span>{candidate.provider_id}{candidate.model_id ? ` · ${candidate.model_id}` : ""}</span><b>{candidate.eligible === false ? "not eligible" : `${candidate.score ?? "—"} pts`}</b></summary><div>{candidate.rejection_reason && <p className="inline-error">{candidate.rejection_reason}</p>}{componentEntries.length > 0 && <dl className="score-components">{componentEntries.map(([name, points]) => <React.Fragment key={name}><dt>{compact(name)}</dt><dd>{formatPoints(points)}</dd></React.Fragment>)}</dl>}{reasonItems.length > 0 && <ul className="reason-list">{reasonItems.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}</ul>}{!candidate.rejection_reason && componentEntries.length === 0 && reasonItems.length === 0 && <p className="route-note">No inspectable score components were recorded for this candidate.</p>}</div></details>;
      })}</div>}
    </div></details>
    <details className="inspector-block"><summary>Authority</summary><div>
      <DetailRow label="Autonomy" value={compact(route.autonomy_level)} />
      {approvalRequirements.length > 0 && <ul className="reason-list">{approvalRequirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>}
      {acpPermissions.length > 0 && <ul className="reason-list">{acpPermissions.map((item, index) => <li key={item.approval_request_id || index}>{compact(item.tool || "permission")} · {compact(item.risk_level)} · {compact(item.policy_decision)} · {compact(item.option_id)}</li>)}</ul>}
      {approvalRequirements.length === 0 && acpPermissions.length === 0 && <p className="route-note">No additional approval boundary was recorded for this route.</p>}
    </div></details>
    <details className="inspector-block"><summary>Verification</summary><div>
      <p className="route-note">Strategy: {compact(route.verification_strategy || "not recorded")}</p>
      {verificationChecks.length > 0 && <ul className="reason-list">{verificationChecks.map((check, index) => <li key={`${check}-${index}`}>{typeof check === "string" ? compact(check) : JSON.stringify(check)}</li>)}</ul>}
      {verificationLimitations.length > 0 && <ul className="reason-list">{verificationLimitations.map((limitation, index) => <li key={`${limitation}-${index}`}>{limitation}</li>)}</ul>}
      {route.verification_strategy === "response_integrity" && <p className="route-note">Response integrity does not verify factual correctness.</p>}
    </div></details>
    {streamEvents.length > 0 && <details className="inspector-block"><summary>Lifecycle</summary><div className="event-history">{streamEvents.map((event) => <article key={event.event_id || `${event.execution_id}-${event.sequence}`}><b>{compact(event.event_type)}</b><span>Execution {compactId(event.execution_id)} · sequence {event.sequence}</span><code>{event.created_at ? new Date(event.created_at).toLocaleString() : "time not recorded"}</code></article>)}</div></details>}
    {(tools.length > 0 || skills.length > 0) && <details className="inspector-block"><summary>Tools and skills</summary><div className="pill-row">{tools.map((tool) => <Pill key={`tool-${tool}`}>{tool}</Pill>)}{skills.map((skill) => <Pill key={`skill-${skill}`}>{skill}</Pill>)}</div></details>}
    <details className="inspector-block"><summary>Record IDs</summary><div>
      <DetailRow label="Route ID" value={route.route_id || route.id} mono />
      <DetailRow label="Request ID" value={route.request_id} mono />
      <DetailRow label="Conversation ID" value={route.conversation_id} mono />
      <DetailRow label="Receipt ID" value={receipt || "not recorded"} mono />
      <DetailRow label="Persona version" value={route.actual_persona_version_id || route.requested_persona_version_id} mono />
      <DetailRow label="Runtime" value={route.selected_runtime || "direct provider adapter"} />
      <DetailRow label="Created" value={route.created_at ? new Date(route.created_at).toLocaleString() : null} />
    </div></details>
    {promoted && <div className="notice success" role="status">Planning Mission created. No Mission step was executed.</div>}
    <details className="inspector-block rerun-controls" aria-labelledby="rerun-heading"><summary id="rerun-heading">Rerun</summary><div>
      <p>Blank choices preserve the recorded route. A rerun creates a new decision and links an execution receipt only when a provider invocation starts.</p>
      <div className="rerun-grid"><label><span>Persona</span><select aria-label="Rerun persona" value={rerunOptions.persona_id} onChange={(event) => setRerunOptions((current) => ({ ...current, persona_id: event.target.value }))}><option value="">Keep {route.requested_persona_id || "recorded persona"}</option>{personas.map((persona) => <option key={persona.persona_id || persona.id} value={persona.persona_id || persona.id}>{persona.name || persona.persona_id || persona.id}</option>)}</select></label><label><span>Provider</span><select aria-label="Rerun provider" value={rerunOptions.provider_id} onChange={(event) => setRerunOptions((current) => ({ ...current, provider_id: event.target.value, model_id: "" }))}><option value="" disabled={!providerIsChatEligible(providers.find((provider) => (provider.provider_id || provider.id) === recordedProviderId))}>Keep {recordedProviderId || "recorded provider"}{providerIsChatEligible(providers.find((provider) => (provider.provider_id || provider.id) === recordedProviderId)) ? "" : " — Chat unavailable"}</option>{providers.map((provider) => { const providerId = provider.provider_id || provider.id; const chatEligible = providerIsChatEligible(provider); return <option key={providerId} value={providerId} disabled={!chatEligible}>{provider.display_name || providerId}{chatEligible ? "" : " — Chat unavailable"}</option>; })}</select></label><label><span>Model override</span><input aria-label="Rerun model override" value={rerunOptions.model_id} maxLength="200" placeholder="Keep provider default" onChange={(event) => setRerunOptions((current) => ({ ...current, model_id: event.target.value }))} /></label><label><span>Cognitive policy</span><select aria-label="Rerun cognitive policy" value={rerunOptions.cognitive_policy} onChange={(event) => setRerunOptions((current) => ({ ...current, cognitive_policy: event.target.value }))}><option value="">Keep recorded policy</option><option value="fast_answer">Fast answer</option><option value="deep_analysis">Deep analysis</option><option value="skeptical_review">Skeptical review</option><option value="creative_divergence">Creative divergence</option><option value="decision_support">Decision support</option><option value="emotional_reflection">Emotional reflection</option><option value="implementation">Implementation</option><option value="research_synthesis">Research synthesis</option></select></label><label><span>Reasoning effort</span><select aria-label="Rerun reasoning effort" value={rerunOptions.reasoning_effort} onChange={(event) => setRerunOptions((current) => ({ ...current, reasoning_effort: event.target.value }))}><option value="">Keep recorded effort</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="xhigh">Extra high</option></select></label><label><span>Local-only policy</span><select aria-label="Rerun local-only policy" value={rerunOptions.local_only} onChange={(event) => setRerunOptions((current) => ({ ...current, local_only: event.target.value === "" ? "" : event.target.value === "true" }))}><option value="">Keep recorded boundary</option><option value="true">Require local only</option><option value="false">Allow eligible cloud routes</option></select></label></div>
      <label className="check-control"><input type="checkbox" checked={rerunOptions.allow_fallback} onChange={(event) => setRerunOptions((current) => ({ ...current, allow_fallback: event.target.checked }))} /><span>Allow an explicit, recorded fallback</span></label>
      {!rerunProviderEligible && <div className="notice amber" role="note">Choose a provider with a proven answer-only Chat boundary before rerunning this recorded route.</div>}
    </div></details>
    <div className="inspector-actions"><button type="button" className="button secondary" onClick={() => onRerun(rerunPayload)} disabled={rerunning || promoting || loading || !rerunProviderEligible}>{rerunning ? "Rerunning…" : "Rerun"}</button><button type="button" className="button secondary" onClick={onPromote} disabled={promoting || rerunning || loading || Boolean(promoted)}>{promoting ? "Creating plan…" : promoted ? "Planning Mission created" : "Continue as Mission"}</button></div>
    <p className="route-note">Continue as Mission creates a durable planning record. It does not execute the work.</p>
  </div>;
}

export function ConversationRail({ conversations, selectedId, onSelect, onCreate, isCreating, disabled = false, mobileOpen = false, onClose }) {
  const railRef = useRef(null);
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

  return <aside ref={railRef} id="conversation-navigation" className={`conversation-rail ${mobileOpen ? "is-mobile-open" : ""}`} role={mobileOpen ? "dialog" : undefined} aria-modal={mobileOpen ? "true" : undefined} aria-label="Conversations">
    <div className="rail-heading"><div><p className="eyebrow">Chat</p><h2>Conversations</h2></div><div className="rail-actions"><IconButton label="New conversation" onClick={() => onCreate({})} disabled={isCreating || disabled}><Plus size={17} /></IconButton><IconButton className="conversation-close" label="Collapse conversations" onClick={onClose}><X size={17} /></IconButton></div></div>
    <div className="conversation-list">{conversations.map((conversation) => {
      const conversationId = conversation.conversation_id || conversation.id;
      const selected = conversationId === selectedId;
      return <button type="button" key={conversationId} className={`conversation-item ${selected ? "is-selected" : ""}`} aria-current={selected ? "true" : undefined} disabled={disabled} onClick={() => onSelect(conversationId)}><b>{conversation.title || "Untitled conversation"}</b><span>{conversation.updated_at ? new Date(conversation.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "local"}</span></button>;
    })}</div>
    {!conversations.length && <p className="rail-empty">Write a goal below, or click New. Conversations stay on this machine.</p>}
  </aside>;
}

export const panelIcons = { missions: Layers3, skills: Wrench, memory: BrainCircuit, ledger: FileKey2, providers: Network, settings: Settings2, route: Route, privacy: ShieldCheck, time: Clock3, persona: Bot, book: BookOpen, right: PanelRight };

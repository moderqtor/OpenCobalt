import React, { useCallback, useEffect, useId, useState } from "react";
import { api } from "./api";

function readable(value) {
  return String(value || "not recorded").replaceAll("_", " ");
}

function notifyChanged(onChanged, event) {
  try {
    Promise.resolve(onChanged?.(event)).catch(() => undefined);
  } catch {
    // The backend mutation already completed; a parent refresh failure must not rewrite it.
  }
}

function ErrorMessage({ error }) {
  if (!error) return null;
  return <p className="inline-error" role="alert">{error.message || "The skill action did not complete."}</p>;
}

function StatusMessage({ children }) {
  if (!children) return null;
  return <p className="save-note" role="status" aria-live="polite">{children}</p>;
}

function Fact({ term, children, mono = false }) {
  return <div className="detail-row"><span>{term}</span><strong className={mono ? "mono" : ""}>{children}</strong></div>;
}

function PreviewDetails({ preview }) {
  return <article className="record-card" aria-label={`Inspected skill ${preview.name}`}>
    <div className="card-top"><div><p className="eyebrow">Pinned local preview</p><h3>{preview.name} · {preview.version}</h3></div><span className={`pill ${preview.requires_approval ? "pill-amber" : "pill-green"}`}>{preview.requires_approval ? "approval required" : "approval not required"}</span></div>
    <p>{preview.description || "No description supplied."}</p>
    <Fact term="Preview ID" mono>{preview.preview_id}</Fact>
    <Fact term="Content hash" mono>{preview.content_hash}</Fact>
    <Fact term="Source name">{preview.source_name}</Fact>
    <Fact term="Inspection trust">{readable(preview.trust_level)}</Fact>
    <section>
      <h4>Requested permissions</h4>
      {preview.requested_permissions?.length
        ? <div className="pill-row">{preview.requested_permissions.map((permission) => <span className="pill pill-amber" key={permission}>{permission}</span>)}</div>
        : <p>No permissions requested.</p>}
    </section>
    <section>
      <h4>Files inspected</h4>
      <ul>{preview.files.map((file) => <li key={file}><code>{file}</code>{preview.executable_files.includes(file) ? " — executable suffix" : ""}</li>)}</ul>
      {!preview.executable_files.length && <p>No executable-suffix files were identified. This is not a claim that the content is safe.</p>}
    </section>
    {Object.keys(preview.compatibility || {}).length > 0 && <section><h4>Declared compatibility</h4><dl>{Object.entries(preview.compatibility).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{String(value)}</dd></React.Fragment>)}</dl></section>}
    {preview.trust_reasons?.length > 0 && <section><h4>Inspection reasons</h4><ul>{preview.trust_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></section>}
    <p className="notice amber" role="note">Previewing reads and hashes the local tree for inspection. It does not execute imported content. Installation revalidates the pinned tree and installs the skill disabled.</p>
  </article>;
}

function ImportPanel({ onInstalled }) {
  const sourceId = useId();
  const reasonId = useId();
  const [sourcePath, setSourcePath] = useState("");
  const [preview, setPreview] = useState(null);
  const [approval, setApproval] = useState(null);
  const [reason, setReason] = useState("");
  const [installed, setInstalled] = useState(null);
  const [state, setState] = useState({ action: null, error: null, note: null });

  const changeSource = (value) => {
    setSourcePath(value);
    setPreview(null);
    setApproval(null);
    setReason("");
    setInstalled(null);
    setState({ action: null, error: null, note: null });
  };

  const inspect = async (event) => {
    event.preventDefault();
    if (!sourcePath.trim()) return;
    setState({ action: "preview", error: null, note: null });
    setPreview(null);
    setApproval(null);
    setInstalled(null);
    try {
      const result = await api.previewSkillImport(sourcePath.trim());
      setPreview(result);
      setState({ action: null, error: null, note: "Inspection completed without executing imported content." });
    } catch (error) {
      setState({ action: null, error, note: null });
    }
  };

  const approve = async () => {
    if (!preview?.approval_request_id || !reason.trim()) return;
    setState({ action: "approve", error: null, note: null });
    try {
      const result = await api.approveSkillAction(preview.approval_request_id, reason.trim());
      setApproval(result);
      setState({ action: null, error: null, note: "Approval was recorded. The skill has not been installed yet." });
    } catch (error) {
      setState({ action: null, error, note: null });
    }
  };

  const install = async () => {
    if (!preview || (preview.requires_approval && !approval)) return;
    setState({ action: "install", error: null, note: null });
    try {
      const result = await api.installSkillImport(
        preview.preview_id,
        preview.requires_approval ? approval.approval_request_id : undefined,
      );
      setInstalled(result);
      const disabled = result.skill?.enabled === false;
      setState({
        action: null,
        error: null,
        note: disabled
          ? "Pinned files were installed and the skill remains disabled. No imported content was executed."
          : "The API returned an unexpected enabled state; inspect the installed record before use.",
      });
      onInstalled(result);
    } catch (error) {
      setState({ action: null, error, note: null });
    }
  };

  const canInstall = Boolean(preview && !installed && (!preview.requires_approval || approval));
  return <section aria-labelledby={`${sourceId}-title`}>
    <header><p className="eyebrow">Local import</p><h2 id={`${sourceId}-title`}>Inspect, approve when required, then install disabled</h2></header>
    <form className="skill-import-form" onSubmit={inspect}>
      <label htmlFor={sourceId} className="visually-hidden">Local skill directory path</label>
      <input id={sourceId} value={sourcePath} onChange={(event) => changeSource(event.target.value)} placeholder="Absolute path to a local skill directory" autoComplete="off" spellCheck="false" />
      <button type="submit" className="button secondary" disabled={!sourcePath.trim() || Boolean(state.action)}>{state.action === "preview" ? "Inspecting…" : "Preview local directory"}</button>
    </form>
    <ErrorMessage error={state.error} />
    <StatusMessage>{state.note}</StatusMessage>
    {preview && <PreviewDetails preview={preview} />}
    {preview?.requires_approval && !approval && <fieldset className="record-card">
      <legend>Explicit import approval</legend>
      <p>The inspection found executable content or high-risk permissions. Approval authorizes only this pinned import request; it does not install or execute the skill.</p>
      <label htmlFor={reasonId}>Approval reason</label>
      <textarea id={reasonId} rows="2" maxLength="1000" value={reason} onChange={(event) => setReason(event.target.value)} />
      <button type="button" className="button secondary" onClick={approve} disabled={!reason.trim() || Boolean(state.action)}>{state.action === "approve" ? "Recording approval…" : "Approve this inspected import"}</button>
    </fieldset>}
    {approval && <p className="notice amber" role="status">Approval request <code>{approval.approval_request_id}</code> is approved. Installation remains a separate explicit action.</p>}
    {preview && <div className="inspector-actions"><button type="button" className="button primary" onClick={install} disabled={!canInstall || Boolean(state.action)}>{state.action === "install" ? "Installing…" : installed ? "Installed disabled" : "Install pinned skill disabled"}</button>{preview.requires_approval && !approval && <span>Approval is required before installation.</span>}</div>}
    {installed && <article className="record-card"><h3>Installation receipt</h3><Fact term="Skill">{installed.skill?.name}</Fact><Fact term="Installed version">{installed.version?.version}</Fact><Fact term="Content hash" mono>{installed.version?.content_hash}</Fact><Fact term="Receipt ID" mono>{installed.receipt_id}</Fact><Fact term="Registry state">{installed.skill?.enabled === false ? "disabled" : readable(installed.skill?.enabled)}</Fact></article>}
  </section>;
}

function VersionManager({ skills, loading, error, onReload, onChanged }) {
  const headingId = useId();
  const [flow, setFlow] = useState(null);
  const [state, setState] = useState({ action: null, error: null, note: null });
  const imported = skills.filter((skill) => skill.source_kind === "imported");

  const requestAction = async (skill, version, action) => {
    setState({ action: "request", error: null, note: null });
    setFlow(null);
    try {
      const result = await api.requestSkillVersionAction(skill.skill_id, version.skill_version_id, action);
      setFlow({ ...result, reason: "", approved: false });
      setState({ action: null, error: null, note: `${readable(action)} approval requested. No version state changed.` });
    } catch (requestError) {
      setState({ action: null, error: requestError, note: null });
    }
  };

  const approve = async () => {
    if (!flow?.approval_request_id || !flow.reason.trim()) return;
    setState({ action: "approve", error: null, note: null });
    try {
      await api.approveSkillAction(flow.approval_request_id, flow.reason.trim());
      setFlow((current) => ({ ...current, approved: true }));
      setState({ action: null, error: null, note: "Approval recorded. Rollback or removal has not run yet." });
    } catch (approvalError) {
      setState({ action: null, error: approvalError, note: null });
    }
  };

  const execute = async () => {
    if (!flow?.approved) return;
    setState({ action: "execute", error: null, note: null });
    try {
      const result = flow.action === "rollback"
        ? await api.rollbackSkillVersion(flow.skill_id, flow.skill_version_id, flow.approval_request_id)
        : await api.removeSkillVersion(flow.skill_id, flow.skill_version_id, flow.approval_request_id);
      setState({
        action: null,
        error: null,
        note: flow.action === "rollback"
          ? `Rollback confirmed. Active version: ${result.active_version_id || flow.skill_version_id}.`
          : `Removal confirmed with receipt ${result.receipt_id}. The version record remains for provenance.`,
      });
      notifyChanged(onChanged, { type: flow.action, result, skillId: flow.skill_id, skillVersionId: flow.skill_version_id });
      setFlow(null);
      await onReload();
    } catch (actionError) {
      setState({ action: null, error: actionError, note: null });
    }
  };

  return <section aria-labelledby={headingId}>
    <header><p className="eyebrow">Installed versions</p><h2 id={headingId}>Approval-bound rollback and removal</h2></header>
    <p>These controls operate only on imported, pinned local versions. Requesting or approving an action does not execute imported skill content.</p>
    {loading && <p role="status">Loading installed skill records…</p>}
    <ErrorMessage error={error || state.error} />
    <StatusMessage>{state.note}</StatusMessage>
    {!loading && !error && !imported.length && <p>No imported skill versions are installed.</p>}
    <div className="record-list">{imported.map((skill) => <article className="record-card" key={skill.skill_id}>
      <div className="card-top"><div><h3>{skill.name}</h3><code>{skill.skill_id}</code></div><span className={`pill ${skill.enabled ? "pill-green" : ""}`}>{skill.enabled ? "enabled" : "disabled"}</span></div>
      {(skill.versions || []).map((version) => {
        const active = skill.active_version_id === version.skill_version_id;
        const installed = Boolean(version.installed);
        const selected = flow?.skill_id === skill.skill_id && flow?.skill_version_id === version.skill_version_id;
        return <section className="record-card" key={version.skill_version_id} aria-label={`${skill.name} version ${version.version}`}>
          <div className="card-top"><strong>Version {version.version}</strong><div className="pill-row"><span className="pill">{installed ? "installed" : "files removed"}</span>{active && <span className="pill pill-green">active</span>}</div></div>
          <Fact term="Version ID" mono>{version.skill_version_id}</Fact>
          <Fact term="Content hash" mono>{version.content_hash}</Fact>
          <Fact term="Install receipt" mono>{version.receipt_id || "not recorded"}</Fact>
          <div className="inspector-actions">
            <button type="button" className="button secondary" onClick={() => requestAction(skill, version, "rollback")} disabled={!installed || active || Boolean(state.action)}>Request rollback approval</button>
            <button type="button" className="button stop" onClick={() => requestAction(skill, version, "remove")} disabled={!installed || active || Boolean(state.action)}>Request removal approval</button>
          </div>
          {active && <p>This active version cannot be removed. Roll back to another installed version first.</p>}
          {selected && <fieldset>
            <legend>{readable(flow.action)} approval for this exact pinned version</legend>
            <Fact term="Approval request" mono>{flow.approval_request_id}</Fact>
            <p>{flow.action === "remove" ? "Removal deletes this version’s bounded local installed files and records a receipt; the provenance record remains." : "Rollback changes only the active pinned version and records a receipt."}</p>
            {!flow.approved && <><label htmlFor={`${flow.approval_request_id}-reason`}>Human approval reason</label><textarea id={`${flow.approval_request_id}-reason`} rows="2" maxLength="1000" value={flow.reason} onChange={(event) => setFlow((current) => ({ ...current, reason: event.target.value }))} /><div className="inspector-actions"><button type="button" className="button secondary" onClick={approve} disabled={!flow.reason.trim() || Boolean(state.action)}>{state.action === "approve" ? "Approving…" : `Approve ${flow.action}`}</button><button type="button" className="text-button" onClick={() => setFlow(null)} disabled={Boolean(state.action)}>Dismiss; leave request pending</button></div></>}
            {flow.approved && <div className="notice amber" role="status"><p>Approval is recorded. The action has not run.</p><button type="button" className={`button ${flow.action === "remove" ? "stop" : "primary"}`} onClick={execute} disabled={Boolean(state.action)}>{state.action === "execute" ? "Applying…" : flow.action === "remove" ? "Remove approved local files" : "Apply approved rollback"}</button></div>}
          </fieldset>}
        </section>;
      })}
    </article>)}</div>
  </section>;
}

export default function SkillImport({ onChanged }) {
  const titleId = useId();
  const [skillsState, setSkillsState] = useState({ loading: true, error: null, data: [] });

  const loadSkills = useCallback(async () => {
    setSkillsState((current) => ({ ...current, loading: true, error: null }));
    try {
      const data = await api.skills();
      setSkillsState({ loading: false, error: null, data });
      return data;
    } catch (error) {
      setSkillsState({ loading: false, error, data: [] });
      throw error;
    }
  }, []);

  useEffect(() => {
    loadSkills().catch(() => undefined);
  }, [loadSkills]);

  const installed = async (result) => {
    notifyChanged(onChanged, { type: "installed", result });
    await loadSkills().catch(() => undefined);
  };

  return <section className="skill-management" aria-labelledby={titleId}>
    <header className="skill-management-head"><p className="eyebrow">Secure skills</p><h2 id={titleId}>Local skill management</h2><p>Inspection, human approval, installation, activation, rollback, and removal are separate operations. This surface never executes imported skill content.</p></header>
    <ImportPanel onInstalled={installed} />
    <VersionManager skills={skillsState.data} loading={skillsState.loading} error={skillsState.error} onReload={loadSkills} onChanged={onChanged} />
  </section>;
}

import React from "react";

function Panel({ title, children, placeholder }) {
  return (
    <div className="border border-slate-700 rounded bg-slate-900 flex flex-col min-h-0">
      <div className="px-4 py-2 border-b border-slate-700 flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
          {title}
        </span>
        {placeholder && (
          <span className="text-xs text-slate-600 ml-auto">planned</span>
        )}
      </div>
      <div className="flex-1 p-4 overflow-auto">{children}</div>
    </div>
  );
}

function StatusRow({ label, value, ok }) {
  return (
    <div className="flex items-center gap-3 py-1">
      <span
        className={`text-xs ${ok ? "text-green-400" : "text-yellow-400"}`}
        aria-hidden="true"
      >
        ●
      </span>
      <span className="text-xs text-slate-400 w-24 shrink-0">{label}</span>
      <span className="text-xs text-slate-300">{value}</span>
    </div>
  );
}

function CommandCenter() {
  const commands = [
    "opencobalt status",
    "opencobalt route \"design the auth module\"",
    "opencobalt context",
    "opencobalt verify",
    "opencobalt agents list",
    "opencobalt cost status",
  ];
  return (
    <Panel title="Command Center">
      <p className="text-xs text-slate-500 mb-3">
        Common commands. Run from the terminal -- not yet wired to the UI.
      </p>
      <div className="space-y-1">
        {commands.map((cmd) => (
          <div
            key={cmd}
            className="text-xs font-mono text-cobalt bg-slate-800 px-3 py-1.5 rounded"
          >
            $ {cmd}
          </div>
        ))}
      </div>
    </Panel>
  );
}

function ContextPackViewer() {
  return (
    <Panel title="Context Pack Viewer" placeholder>
      <p className="text-xs text-slate-500">
        Shows the latest compiled context pack from{" "}
        <code className="text-slate-400">.opencobalt/context/latest.md</code>.
        Run{" "}
        <code className="text-cobalt">opencobalt context</code> to build it.
      </p>
      <div className="mt-4 border border-slate-700 rounded p-3">
        <p className="text-xs text-slate-600 italic">
          Backend not wired. Future phase.
        </p>
      </div>
    </Panel>
  );
}

function SessionLedger() {
  const mockEvents = [
    { time: "13:45", type: "manual_log", summary: "reviewed auth module" },
    { time: "13:40", type: "route_decision", summary: "routed to codex-cli" },
    { time: "13:31", type: "verification", summary: "58 tests passed" },
  ];
  return (
    <Panel title="Session Ledger">
      <p className="text-xs text-slate-500 mb-3">
        Recent events from SQLite ledger. Placeholder data shown.
      </p>
      <div className="space-y-2">
        {mockEvents.map((e, i) => (
          <div
            key={i}
            className="flex gap-3 text-xs border-b border-slate-800 pb-2"
          >
            <span className="text-slate-600 shrink-0">{e.time}</span>
            <span className="text-slate-500 w-28 shrink-0">{e.type}</span>
            <span className="text-slate-300">{e.summary}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function AgentRouter() {
  const tiers = [
    {
      tier: "executive",
      color: "text-cobalt",
      tools: ["claude-code", "gemini-cli"],
    },
    {
      tier: "manager",
      color: "text-yellow-400",
      tools: ["codex-cli", "cursor"],
    },
    { tier: "worker", color: "text-slate-400", tools: ["ollama"] },
  ];
  return (
    <Panel title="Agent Router">
      <p className="text-xs text-slate-500 mb-3">
        Routing tiers. Decisions are deterministic -- no LLM calls.
      </p>
      <div className="space-y-3">
        {tiers.map((t) => (
          <div key={t.tier}>
            <p className={`text-xs font-semibold ${t.color} mb-1`}>
              {t.tier}
            </p>
            <div className="flex gap-2 flex-wrap">
              {t.tools.map((tool) => (
                <span
                  key={tool}
                  className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-slate-400"
                >
                  {tool}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function VerificationReceipts() {
  return (
    <Panel title="Verification Receipts">
      <div className="space-y-2">
        <StatusRow label="pytest" value="58 passed (placeholder)" ok />
        <StatusRow label="public-check" value="clean (placeholder)" ok />
      </div>
      <p className="text-xs text-slate-600 mt-4 italic">
        Live results not wired. Run{" "}
        <code className="text-slate-500">opencobalt verify</code> in terminal.
      </p>
    </Panel>
  );
}

function DesignLabPlaceholder() {
  return (
    <Panel title="DesignLab" placeholder>
      <p className="text-xs text-slate-500">
        Visual compiler and design token engine. Planned future phase.
      </p>
      <p className="text-xs text-slate-600 mt-2">
        See <code>docs/DESIGNLAB.md</code> for the design.
      </p>
    </Panel>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-700 px-6 py-3 flex items-center gap-4">
        <span className="text-cobalt font-bold text-sm tracking-widest uppercase">
          OpenCobalt
        </span>
        <span className="text-slate-500 text-xs">
          local-first AI orchestration control plane
        </span>
        <span className="ml-auto text-xs text-slate-600 border border-slate-700 rounded px-2 py-0.5">
          UI shell stub -- backend not wired
        </span>
      </header>

      {/* Main grid */}
      <main className="flex-1 grid grid-cols-3 grid-rows-2 gap-3 p-4 overflow-hidden">
        <CommandCenter />
        <ContextPackViewer />
        <SessionLedger />
        <AgentRouter />
        <VerificationReceipts />
        <DesignLabPlaceholder />
      </main>
    </div>
  );
}

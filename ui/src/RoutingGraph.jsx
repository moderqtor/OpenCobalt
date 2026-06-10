import React, { useEffect, useMemo, useRef, useState } from "react";

const GRAPH_CSS = `
@keyframes rg-flow{to{stroke-dashoffset:-48}}
@keyframes rg-node-in{from{opacity:.35;transform:translate(-50%,-50%) scale(.96)}to{opacity:1;transform:translate(-50%,-50%) scale(1)}}
.rg-wrap{width:100%;padding-top:88px}
.rg-shell{position:relative;width:100%;min-height:520px;border:1px solid var(--ln);border-radius:8px;background:linear-gradient(180deg,rgba(13,17,23,.92),rgba(8,10,15,.96));overflow:hidden}
.rg-shell::before{content:'';position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.055) 1px,transparent 1px);background-size:22px 22px;mask-image:linear-gradient(to bottom,rgba(0,0,0,.9),rgba(0,0,0,.45));pointer-events:none}
.rg-stage{position:relative;height:480px}
.rg-edge{stroke:rgba(255,255,255,.12);stroke-width:1.5;fill:none;stroke-linecap:round;stroke-dasharray:8 8}
.rg-edge.is-hot{stroke:var(--acc);stroke-width:2;filter:drop-shadow(0 0 8px rgba(123,158,255,.42));animation:rg-flow 1s linear infinite}
.rg-node{position:absolute;width:132px;min-height:76px;padding:12px;border:1px solid rgba(255,255,255,.08);border-radius:8px;background:rgba(13,17,23,.88);transform:translate(-50%,-50%);opacity:.42;transition:opacity .18s ease,border-color .18s ease,box-shadow .18s ease,background .18s ease;animation:rg-node-in .18s ease both}
.rg-node.is-active{opacity:1;border-color:rgba(123,158,255,.72);box-shadow:0 0 0 1px rgba(123,158,255,.15),0 0 28px rgba(123,158,255,.24);background:rgba(18,27,48,.92)}
.rg-node.is-winner{opacity:1;border-color:rgba(61,255,160,.7);box-shadow:0 0 0 1px rgba(61,255,160,.14),0 0 28px rgba(61,255,160,.24);background:rgba(12,31,24,.92)}
.rg-node.is-runner{opacity:.34;border-color:rgba(255,209,102,.34);box-shadow:0 0 18px rgba(255,209,102,.08)}
.rg-kicker{font-family:var(--fmo);font-size:9px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--t3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rg-title{margin-top:8px;font-size:14px;font-weight:600;color:var(--t0);line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rg-meta{margin-top:8px;font-family:var(--fmo);font-size:10.5px;color:var(--t2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rg-pill{position:absolute;right:8px;top:8px;width:7px;height:7px;border-radius:50%;background:var(--t3)}
.rg-node.is-active .rg-pill{background:var(--acc)}
.rg-node.is-winner .rg-pill{background:var(--ok)}
.rg-node.is-runner .rg-pill{background:var(--wn)}
.rg-foot{position:absolute;left:20px;right:20px;bottom:18px;display:flex;align-items:center;gap:12px;min-width:0}
.rg-task{flex:1;min-width:0;font-size:13px;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rg-time{font-family:var(--fmo);font-size:10.5px;color:var(--t3);flex-shrink:0}
.rg-empty{padding-top:32px;color:var(--t2);font-size:13px}
@media (max-width:720px){
  .rg-wrap{padding-top:72px}
  .rg-shell{min-height:500px}
  .rg-stage{height:460px}
  .rg-node{width:112px;padding:10px}
  .rg-title{font-size:12px}
}
`;

const POSITIONS = {
  prompt: { x: 18, y: 48 },
  router: { x: 50, y: 48 },
  tools: [
    { x: 82, y: 20 },
    { x: 82, y: 48 },
    { x: 82, y: 76 },
    { x: 50, y: 78 },
    { x: 18, y: 78 },
  ],
};

const DEFAULT_TOOLS = ["google-antigravity", "claude-code", "codex-cli", "cursor", "ollama"];

function routeTime(event) {
  const stamp = event?.timestamp ? new Date(event.timestamp).getTime() : 0;
  return Number.isFinite(stamp) ? stamp : 0;
}

function newestRoute(timeline) {
  if (!Array.isArray(timeline)) return null;
  return timeline
    .filter((event) => event?.type === "route")
    .reduce((latest, event) => {
      if (!latest) return event;
      return routeTime(event) >= routeTime(latest) ? event : latest;
    }, null);
}

function scoreValue(value) {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  if (value && typeof value === "object") {
    return scoreValue(value.score ?? value.value ?? value.total);
  }
  return 0;
}

function normalizeScores(scores, fallbackTool) {
  let entries = [];
  if (Array.isArray(scores)) {
    entries = scores
      .map((entry) => {
        if (Array.isArray(entry)) return { name: String(entry[0] ?? ""), score: scoreValue(entry[1]) };
        return {
          name: String(entry?.tool ?? entry?.agent ?? entry?.id ?? entry?.name ?? ""),
          score: scoreValue(entry?.score ?? entry?.value ?? entry?.total),
        };
      })
      .filter((entry) => entry.name);
  } else if (scores && typeof scores === "object") {
    entries = Object.entries(scores).map(([name, score]) => ({ name, score: scoreValue(score) }));
  }

  if (entries.length === 0 && fallbackTool) {
    entries = [{ name: fallbackTool, score: 0 }];
  }

  return entries.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
}

function formatScore(value) {
  if (!Number.isFinite(value)) return "score n/a";
  return value % 1 === 0 ? `score ${value}` : `score ${value.toFixed(2)}`;
}

function Node({ kind, label, meta, x, y, state }) {
  const className = ["rg-node"];
  if (state) className.push(`is-${state}`);
  return (
    <div className={className.join(" ")} style={{ left: `${x}%`, top: `${y}%` }}>
      <span className="rg-pill" />
      <div className="rg-kicker">{kind}</div>
      <div className="rg-title" title={label}>{label}</div>
      <div className="rg-meta" title={meta}>{meta}</div>
    </div>
  );
}

export default function RoutingGraph({ timeline, loading, error }) {
  const routeEvent = useMemo(() => newestRoute(timeline), [timeline]);
  const ranked = useMemo(
    () => normalizeScores(routeEvent?.scores, routeEvent?.model),
    [routeEvent],
  );
  const routeId = routeEvent
    ? String(routeEvent.id ?? `${routeEvent.timestamp ?? ""}:${routeEvent.model ?? ""}:${routeEvent.title ?? ""}`)
    : "";
  const [stage, setStage] = useState("idle");
  const seenRoute = useRef("");

  useEffect(() => {
    if (!routeId || routeId === seenRoute.current) return undefined;
    seenRoute.current = routeId;
    setStage("prompt");
    const timers = [
      setTimeout(() => setStage("route"), 100),
      setTimeout(() => setStage("rank"), 300),
      setTimeout(() => setStage("hold"), 700),
      setTimeout(() => setStage("idle"), 2700),
    ];
    return () => timers.forEach(clearTimeout);
  }, [routeId]);

  if (error) {
    return (
      <div className="rg-wrap">
        <style>{GRAPH_CSS}</style>
        <div className="rg-empty">API offline.</div>
      </div>
    );
  }

  if (!loading && !routeEvent) {
    return (
      <div className="rg-wrap">
        <style>{GRAPH_CSS}</style>
        <div className="rg-empty">No route events yet.</div>
      </div>
    );
  }

  const winner = ranked[0]?.name ?? routeEvent?.model ?? "";
  const runners = new Set(ranked.slice(1, 3).map((entry) => entry.name));
  const tools = [...new Set([...ranked.map((entry) => entry.name), ...DEFAULT_TOOLS])].slice(0, 5);
  const scoreMap = new Map(ranked.map((entry) => [entry.name, entry.score]));
  const routeHot = stage === "route";
  const resultHot = stage === "rank" || stage === "hold";
  const promptState = stage === "prompt" ? "active" : "";
  const routerState = routeHot ? "active" : "";
  const task = routeEvent?.title || "route task";
  const stamp = (routeEvent?.timestamp || "").slice(11, 19);

  return (
    <div className={`rg-wrap view${loading ? " loading" : ""}`}>
      <style>{GRAPH_CSS}</style>
      <div className="lbl" style={{ marginBottom: 20 }}>Routing graph</div>
      <div className="rg-shell">
        <div className="rg-stage">
          <svg width="100%" height="100%" viewBox="0 0 640 480" preserveAspectRatio="none" aria-hidden="true">
            <path className={`rg-edge${routeHot ? " is-hot" : ""}`} d="M118 230 C180 230 224 230 294 230" />
            {tools.map((tool, index) => {
              const pos = POSITIONS.tools[index] || POSITIONS.tools[POSITIONS.tools.length - 1];
              const isWinner = tool === winner;
              const isRunner = runners.has(tool);
              const hot = resultHot && (isWinner || isRunner);
              const y = (pos.y / 100) * 480;
              return (
                <path
                  key={tool}
                  className={`rg-edge${hot ? " is-hot" : ""}`}
                  d={`M346 230 C430 230 438 ${y} ${pos.x * 6.4 - 66} ${y}`}
                />
              );
            })}
          </svg>

          <Node
            kind="input"
            label="Prompt"
            meta={routeEvent?.tier || "deterministic"}
            x={POSITIONS.prompt.x}
            y={POSITIONS.prompt.y}
            state={promptState}
          />
          <Node
            kind="router"
            label="Keyword scorer"
            meta={ranked.length ? `${ranked.length} candidates` : "awaiting scores"}
            x={POSITIONS.router.x}
            y={POSITIONS.router.y}
            state={routerState}
          />
          {tools.map((tool, index) => {
            const pos = POSITIONS.tools[index] || POSITIONS.tools[POSITIONS.tools.length - 1];
            const isWinner = tool === winner;
            const isRunner = runners.has(tool);
            let state = "";
            if (resultHot && isWinner) state = "winner";
            if (resultHot && isRunner) state = "runner";
            return (
              <Node
                key={tool}
                kind={isWinner ? "winner" : isRunner ? "runner up" : "candidate"}
                label={tool}
                meta={scoreMap.has(tool) ? formatScore(scoreMap.get(tool)) : "score n/a"}
                x={pos.x}
                y={pos.y}
                state={state}
              />
            );
          })}
        </div>
        <div className="rg-foot">
          <div className="rg-task" title={task}>{task}</div>
          <div className="rg-time">{stamp}</div>
        </div>
      </div>
    </div>
  );
}

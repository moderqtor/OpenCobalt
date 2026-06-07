import React, { useState, useEffect, useRef } from "react";
import {
  Terminal, Layers, ScrollText, Network, CheckSquare,
  Palette, Trophy, GitBranch, ChevronRight, Plus, ExternalLink, Gauge
} from "lucide-react";
import RoutingGraph from "./RoutingGraph";

const CSS = `
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#090B10;
  --sf:#10151D;
  --sf2:#151C27;
  --ink:#F6F8FC;
  --paper:#EAF1FF;
  --paper-ink:#132033;
  --ln:rgba(255,255,255,.07);
  --t0:#FFFFFF;
  --t1:rgba(255,255,255,.55);
  --t2:rgba(255,255,255,.28);
  --t3:rgba(255,255,255,.12);
  --acc:#7B9EFF;
  --ok:#3DFFA0;
  --er:#FF5577;
  --wn:#FFD166;
  --vio:#B98CFF;
  --fui:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --fmo:"SF Mono","Cascadia Code","Roboto Mono",ui-monospace,monospace;
}
html,body,#root{height:100%;background:var(--bg);color:var(--t0);font-family:var(--fui);-webkit-font-smoothing:antialiased}
@keyframes in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}
@keyframes ping{0%{transform:scale(1);opacity:.9}70%,100%{transform:scale(2.4);opacity:0}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.view{animation:in .24s ease both}
.mono{font-family:var(--fmo)}
.lbl{font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--t2)}
.cur{display:inline-block;width:2px;height:15px;background:var(--acc);border-radius:1px;animation:blink 1s step-end infinite;vertical-align:middle;margin-left:2px}
.dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;position:relative}
.dot.on{background:var(--ok)}.dot.on::after{content:'';position:absolute;inset:0;border-radius:50%;background:var(--ok);animation:ping 2.4s cubic-bezier(0,0,.2,1) infinite}
.dot.off{background:var(--t3)}
.dot.sm{width:5px;height:5px}
.row{display:flex;align-items:center;gap:16px;padding:24px 0;border-top:1px solid var(--ln)}
.row:last-child{border-bottom:1px solid var(--ln)}
.nb{background:none;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;transition:color .15s ease}
.scr::-webkit-scrollbar{display:none}
.scr{scrollbar-width:none}
.cmd-input{
  width:100%;background:var(--paper);color:var(--paper-ink);
  border:1px solid rgba(123,158,255,.32);border-radius:8px;
  padding:16px 18px;display:flex;align-items:center;gap:12px;
  box-shadow:0 18px 44px rgba(0,0,0,.24),0 0 0 1px rgba(255,255,255,.04) inset;
  transition:border-color .15s,box-shadow .15s;cursor:text;
}
.cmd-input:hover{border-color:rgba(123,158,255,.58);box-shadow:0 22px 54px rgba(0,0,0,.28),0 0 0 1px rgba(123,158,255,.12) inset}
.cmd-input input::placeholder{color:rgba(19,32,51,.42)}
.score-track{height:4px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden}
.score-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--acc),var(--ok))}
.tag{font-family:var(--fmo);font-size:11px;color:var(--t2);padding:0}
.int-row{display:flex;align-items:center;gap:20px;padding:22px 0;border-top:1px solid var(--ln)}
.int-row:last-child{border-bottom:1px solid var(--ln)}
.int-row:hover .int-name{color:var(--t0)}
.int-name{color:var(--t1);transition:color .12s}
.loading{animation:pulse 1.6s ease infinite;pointer-events:none}
@media (max-width:720px){
  .cmd-input{align-items:flex-start;flex-wrap:wrap;padding:14px}
  .cmd-input input{flex-basis:100%;margin-left:22px}
}
`;

const API = "http://localhost:8000";


const StatusDot = ({s, sm}) => {
  const color = s==="ok"?"var(--ok)":s==="er"?"var(--er)":s==="if"?"var(--acc)":"var(--t3)";
  return <div style={{width:sm?5:6,height:sm?5:6,borderRadius:"50%",background:color,flexShrink:0}}/>;
};

const Offline = () => (
  <div style={{paddingTop:88,color:"var(--t2)",fontSize:13}}>
    API offline — run <span className="mono" style={{color:"var(--acc)"}}>opencobalt ui</span>
  </div>
);

const Empty = ({msg}) => (
  <div style={{color:"var(--t2)",fontSize:13,paddingTop:32}}>{msg || "No data yet."}</div>
);

function CommandView({sessions, loading, error, onRoute}) {
  const [input, setInput] = useState("");
  const [routing, setRouting] = useState(false);
  const [lastResult, setLastResult] = useState(null);
  const inputRef = useRef(null);

  const cmds = sessions.map(s => ({
    c: s.task,
    t: s.ts.slice(0,5),
    s: s.ok ? "ok" : "er",
  }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    const task = input.trim();
    if (!task || routing) return;
    setRouting(true);
    setLastResult(null);
    try {
      const res = await fetch(`${API}/api/route`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({task}),
      });
      const data = await res.json();
      setLastResult(data);
      setInput("");
      if (onRoute) onRoute();
    } catch {
      setLastResult({error: "API offline"});
    } finally {
      setRouting(false);
    }
  };

  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:56}}>
        <div className="lbl" style={{marginBottom:20}}>Command center</div>
        <form onSubmit={handleSubmit}>
          <div className="cmd-input" onClick={()=>inputRef.current?.focus()}
            style={{borderColor: routing ? "var(--acc)" : undefined}}>
            <span className="mono" style={{color:"rgba(19,32,51,.45)",fontSize:14,flexShrink:0}}>$</span>
            <span className="mono" style={{color:"#2856B8",fontSize:14,fontWeight:600,flexShrink:0}}>opencobalt</span>
            <span className="mono" style={{color:"rgba(19,32,51,.42)",fontSize:14,marginLeft:2,flexShrink:0}}>›</span>
            <input
              ref={inputRef}
              value={input}
              onChange={e=>setInput(e.target.value)}
              placeholder="type a task to route…"
              disabled={routing}
              style={{
                flex:1, background:"none", border:"none", outline:"none",
                color:"var(--paper-ink)", fontFamily:"var(--fmo)", fontSize:14,
                minWidth:0,
              }}
            />
            {routing && <span className="cur"/>}
            <span className="mono" style={{marginLeft:"auto",color:"rgba(19,32,51,.38)",fontSize:11,flexShrink:0}}>
              {routing ? "routing..." : "local control plane"}
            </span>
          </div>
        </form>
        {lastResult && !lastResult.error && (
          <div style={{marginTop:12,padding:"12px 16px",background:"rgba(123,158,255,.06)",borderRadius:8,border:"1px solid rgba(123,158,255,.12)"}}>
            <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:6}}>
              <span className="mono" style={{color:"var(--acc)",fontSize:13,fontWeight:600}}>→ {lastResult.tool}</span>
              <span className="mono" style={{color:"var(--t3)",fontSize:11}}>{lastResult.tier} · score {lastResult.score}</span>
            </div>
            <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--fmo)"}}>{lastResult.reasoning}</div>
          </div>
        )}
        {lastResult?.error && (
          <div style={{marginTop:8,color:"var(--er)",fontSize:12}}>{lastResult.error}</div>
        )}
      </div>

      <div className="lbl" style={{marginBottom:0}}>Recent</div>
      {error && <Offline/>}
      {!error && cmds.length === 0 && <Empty msg="No route decisions yet — type a task above"/>}
      {cmds.map((c,i) => (
        <div key={i} className="row">
          <StatusDot s={c.s} sm/>
          <span className="mono" style={{flex:1,fontSize:13,color:"var(--t1)"}}>
            <span style={{color:"var(--t0)"}}>opencobalt </span>{c.c}
          </span>
          <span className="mono" style={{color:"var(--t3)",fontSize:11,flexShrink:0}}>{c.t}</span>
        </div>
      ))}
    </div>
  );
}

function AgentsView({agents, loading, error}) {
  const active = agents.filter(a=>a.on).length;
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:64}}>
        <div className="lbl" style={{marginBottom:20}}>Agents</div>
        {error ? <Offline/> : (
          <>
            <div style={{display:"flex",alignItems:"flex-end",gap:12}}>
              <span style={{fontSize:52,fontWeight:300,letterSpacing:"-.02em",lineHeight:1}}>{active}</span>
              <span style={{fontSize:18,color:"var(--t2)",fontWeight:400,marginBottom:6}}>/ {agents.length} active</span>
            </div>
            <div style={{marginTop:10,color:"var(--t2)",fontSize:13}}>
              {agents.filter(a=>a.on).map(a=>a.id).join(", ") || "all idle"}
            </div>
          </>
        )}
      </div>

      {!error && agents.map((a,i) => (
        <div key={i} className="row" style={{gap:0,flexWrap:"wrap"}}>
          <div style={{display:"flex",alignItems:"center",gap:12,flex:1,minWidth:0}}>
            <div className={`dot${a.on?" on":" off"}`}/>
            <div>
              <div style={{fontSize:17,fontWeight:500,marginBottom:6}}>{a.id}</div>
              <div style={{display:"flex",flexWrap:"wrap",gap:12}}>
                {a.caps.map(c=>(
                  <span key={c} className="tag">{c}</span>
                ))}
              </div>
            </div>
          </div>
          <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:6}}>
            <span style={{
              fontFamily:"var(--fmo)",fontSize:10,fontWeight:600,letterSpacing:".10em",
              color:a.on?"var(--ok)":"var(--t3)"
            }}>{a.on?"ACTIVE":"IDLE"}</span>
            <span style={{
              fontFamily:"var(--fmo)",fontSize:10,color:"var(--t3)",
              letterSpacing:".06em",textTransform:"uppercase"
            }}>{a.tier}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

const TYPE_COLORS = {
  route:     "var(--acc)",
  note:      "var(--t2)",
  commit:    "var(--ok)",
  benchmark: "var(--wn)",
  verify:    "#3DFFC8",
};

const TYPE_SHAPES = {
  route:     "circle",
  benchmark: "diamond",
  note:      "square",
};

function TimelineNode({event, expanded, onToggle}) {
  const color = TYPE_COLORS[event.type] || "var(--t2)";
  const shape = TYPE_SHAPES[event.type] || "circle";
  const ts = (event.timestamp || "").slice(11,16);
  const shapeStyle = {
    width:10, height:10, flexShrink:0,
    background: color, opacity:.85,
    borderRadius: shape==="circle" ? "50%" : shape==="diamond" ? 0 : 2,
    transform: shape==="diamond" ? "rotate(45deg)" : "none",
  };
  return (
    <div style={{display:"flex",gap:16,marginBottom:20,alignItems:"flex-start",cursor:"pointer"}} onClick={onToggle}>
      <div style={{display:"flex",flexDirection:"column",alignItems:"center",paddingTop:4}}>
        <div style={shapeStyle}/>
        <div style={{width:1,height:expanded?32:16,background:"var(--ln)",marginTop:4}}/>
      </div>
      <div style={{flex:1,minWidth:0}}>
        <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:4}}>
          <span className="mono" style={{color:"var(--t3)",fontSize:10}}>{ts}</span>
          <span style={{
            fontFamily:"var(--fmo)",fontSize:9,fontWeight:600,letterSpacing:".12em",
            textTransform:"uppercase",color,
          }}>{event.type}</span>
          {event.model && <span className="mono" style={{fontSize:11,color:"var(--t2)"}}>{event.model}</span>}
        </div>
        <div style={{fontSize:13,color:"var(--t1)",lineHeight:1.45}}>{event.title}</div>
        {expanded && event.detail && (
          <div style={{marginTop:8,fontSize:11,color:"var(--t2)",lineHeight:1.5,fontFamily:"var(--fmo)"}}>{event.detail}</div>
        )}
      </div>
    </div>
  );
}

function TimelineView({events, loading, error}) {
  const [expandedId, setExpandedId] = useState(null);
  if (error) return <Offline/>;
  if (!loading && events.length === 0) return <Empty msg="No timeline events yet."/>;
  return (
    <div style={{paddingTop:8}}>
      {events.map(e => (
        <TimelineNode
          key={e.id}
          event={e}
          expanded={expandedId===e.id}
          onToggle={() => setExpandedId(expandedId===e.id ? null : e.id)}
        />
      ))}
    </div>
  );
}

function LedgerView({sessions, timeline, loading, error}) {
  const [viewMode, setViewMode] = useState("timeline");
  const total = sessions.reduce((s,r)=>s+parseFloat(r.cost.replace("$","")),0);
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:40}}>
        <div className="lbl" style={{marginBottom:20}}>Session ledger</div>
        {error ? <Offline/> : (
          <>
            <div style={{fontSize:56,fontWeight:300,letterSpacing:"-.02em",lineHeight:1}}>
              ${total.toFixed(3)}
            </div>
            <div style={{marginTop:12,color:"var(--t2)",fontSize:13}}>
              this session · {sessions.length} tasks
            </div>
          </>
        )}
      </div>

      {!error && (
        <div style={{display:"flex",gap:2,marginBottom:24}}>
          {["timeline","table"].map(m => (
            <button key={m} onClick={()=>setViewMode(m)} style={{
              background: viewMode===m ? "rgba(123,158,255,.1)" : "none",
              border:"1px solid " + (viewMode===m ? "var(--acc)" : "var(--ln)"),
              color: viewMode===m ? "var(--acc)" : "var(--t2)",
              borderRadius:6, padding:"4px 12px",
              fontFamily:"var(--fmo)", fontSize:11, cursor:"pointer",
              letterSpacing:".08em", textTransform:"uppercase",
            }}>{m}</button>
          ))}
        </div>
      )}

      {!error && viewMode==="timeline" && <TimelineView events={timeline} loading={loading} error={error}/>}

      {!error && viewMode==="table" && (
        <>
          {sessions.length === 0 && <Empty msg="No route decisions yet."/>}
          {sessions.map((s,i) => (
            <div key={i} className="row">
              <span className="mono" style={{color:"var(--t3)",fontSize:11,flexShrink:0,width:64}}>{s.ts}</span>
              <span style={{flex:1,fontSize:14,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",paddingRight:16}}>{s.task}</span>
              <span className="mono" style={{color:"var(--acc)",fontSize:12,flexShrink:0,marginRight:16}}>{s.model}</span>
              <span className="mono" style={{color:"var(--t1)",fontSize:13,flexShrink:0}}>{s.cost}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function BenchmarksView({benchmarks, loading, error}) {
  const top = benchmarks[0] || null;
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:64}}>
        <div className="lbl" style={{marginBottom:20}}>Top performer</div>
        {error && <Offline/>}
        {!error && !top && <Empty msg="No benchmark records yet — run opencobalt benchmark record"/>}
        {!error && top && (
          <>
            <div style={{fontSize:32,fontWeight:500,marginBottom:8}}>{top.name}</div>
            <div style={{fontSize:64,fontWeight:300,letterSpacing:"-.02em",color:"var(--acc)",lineHeight:1}}>
              {top.wins}%
            </div>
            <div style={{marginTop:12,color:"var(--t2)",fontSize:13}}>
              win rate · {top.tasks} tasks · avg {top.lat}
            </div>
          </>
        )}
      </div>

      {!error && benchmarks.length > 0 && (
        <>
          <div className="lbl" style={{marginBottom:0}}>Leaderboard</div>
          {benchmarks.map((b,i) => (
            <div key={i} className="row">
              <span className="mono" style={{
                color:i===0?"var(--te, var(--wn))":"var(--t3)",
                fontSize:12,fontWeight:600,width:20,flexShrink:0
              }}>{b.rank}</span>
              <span style={{flex:1,fontSize:14,fontWeight:i===0?500:400}}>{b.name}</span>
              <div style={{width:80,height:3,borderRadius:100,background:"var(--sf)",overflow:"hidden",marginRight:12,flexShrink:0}}>
                <div style={{width:`${b.wins}%`,height:"100%",borderRadius:100,background:i===0?"var(--acc)":"var(--t3)"}}/>
              </div>
              <span className="mono" style={{color:i===0?"var(--t0)":"var(--t2)",fontSize:12,width:36,flexShrink:0,textAlign:"right"}}>{b.wins}%</span>
              <span className="mono" style={{color:"var(--t3)",fontSize:11,width:36,flexShrink:0,textAlign:"right"}}>{b.lat}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function TelemetryView({telemetry, loading, error}) {
  const recent = telemetry?.recent || [];
  const scored = telemetry?.scored_runs || 0;
  const total = telemetry?.total_runs || 0;
  const average = telemetry?.average_overall || 0;
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:56}}>
        <div className="lbl" style={{marginBottom:20}}>Telemetry intelligence</div>
        {error ? <Offline/> : (
          <>
            <div style={{display:"flex",alignItems:"flex-end",gap:14}}>
              <span style={{fontSize:58,fontWeight:300,lineHeight:1,color:"var(--acc)"}}>{average}</span>
              <span style={{fontSize:18,color:"var(--t2)",marginBottom:7}}>/ 100 average</span>
            </div>
            <div style={{marginTop:12,color:"var(--t2)",fontSize:13}}>
              {scored} scored of {total} runs
              {telemetry?.top_agent ? ` · top agent ${telemetry.top_agent}` : ""}
            </div>
          </>
        )}
      </div>

      {!error && recent.length === 0 && <Empty msg="No scored telemetry yet. Run opencobalt telemetry score <run_id>."/>}
      {!error && recent.length > 0 && (
        <>
          <div className="lbl" style={{marginBottom:0}}>Recent scored runs</div>
          {recent.map((run) => (
            <div key={run.id} className="row" style={{alignItems:"flex-start"}}>
              <span className="mono" style={{color:"var(--t3)",fontSize:11,width:54,flexShrink:0}}>{run.id}</span>
              <div style={{flex:1,minWidth:0}}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
                  <span style={{fontSize:14,fontWeight:500,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{run.prompt}</span>
                </div>
                <div style={{display:"flex",gap:10,flexWrap:"wrap",color:"var(--t2)",fontSize:11}}>
                  <span className="mono">{run.run_type}</span>
                  <span className="mono">{run.agent}</span>
                  <span className="mono">{run.judge}</span>
                  <span className="mono">{run.tool_count} tools</span>
                </div>
                <div className="score-track" style={{marginTop:14}}>
                  <div className="score-fill" style={{width:`${Math.max(0, Math.min(100, run.overall))}%`}}/>
                </div>
              </div>
              <span className="mono" style={{color:"var(--t0)",fontSize:18,fontWeight:600,width:42,textAlign:"right",flexShrink:0}}>
                {run.overall}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function IntegrationsView({integrations, loading, error}) {
  const active = integrations.filter(i=>i.on).length;
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{display:"flex",alignItems:"flex-end",justifyContent:"space-between",marginBottom:56}}>
        <div>
          <div className="lbl" style={{marginBottom:20}}>Integrations</div>
          {error ? <Offline/> : (
            <>
              <div style={{fontSize:52,fontWeight:300,letterSpacing:"-.02em",lineHeight:1}}>
                {active}
              </div>
              <div style={{marginTop:10,color:"var(--t2)",fontSize:13}}>
                of {integrations.length} connected
              </div>
            </>
          )}
        </div>
        <button style={{
          display:"flex",alignItems:"center",gap:8,
          background:"none",border:"1px solid var(--ln)",borderRadius:8,
          color:"var(--t1)",cursor:"pointer",padding:"10px 16px",
          fontFamily:"var(--fui)",fontSize:13,transition:"all .12s"
        }}>
          <Plus size={14}/> Add integration
        </button>
      </div>

      {!error && integrations.map((it,i) => (
        <div key={i} className="int-row">
          <div style={{width:6,height:6,borderRadius:"50%",background:it.on?"var(--ok)":"var(--t3)",flexShrink:0}}/>
          <div style={{flex:1}}>
            <div className="int-name" style={{fontSize:15,fontWeight:500,marginBottom:4}}>{it.name}</div>
            <div style={{display:"flex",alignItems:"center",gap:6}}>
              <ExternalLink size={10} style={{color:"var(--t3)"}}/>
              <span className="mono" style={{fontSize:10.5,color:"var(--t3)"}}>{it.repo}</span>
            </div>
          </div>
          <div style={{display:"flex",gap:12}}>
            {it.caps.map(c=>(
              <span key={c} className="mono" style={{fontSize:11,color:"var(--t3)"}}>{c}</span>
            ))}
          </div>
          <span style={{
            fontFamily:"var(--fmo)",fontSize:10,fontWeight:600,letterSpacing:".08em",
            color:it.on?"var(--ok)":"var(--t3)"
          }}>{it.on?"ACTIVE":"STUB"}</span>
        </div>
      ))}
    </div>
  );
}

function ReceiptsView() {
  const [open, setOpen] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/receipts`)
      .then(r => r.json())
      .then(data => { setReceipts(data); setLoading(false); })
      .catch(() => { setOffline(true); setLoading(false); });
  }, []);

  const passed = receipts.filter(r => r.ok).length;
  const failed = receipts.filter(r => !r.ok).length;

  return (
    <div className="view" style={{paddingTop:88}}>
      <div style={{marginBottom:64}}>
        <div className="lbl" style={{marginBottom:20}}>Verification receipts</div>
        {offline ? <Offline/> : loading ? (
          <div style={{color:"var(--t2)",fontSize:13}}>Loading…</div>
        ) : receipts.length === 0 ? (
          <Empty msg="No verification runs yet — run opencobalt verify"/>
        ) : (
          <>
            <div style={{display:"flex",alignItems:"flex-end",gap:12}}>
              <span style={{fontSize:52,fontWeight:300,letterSpacing:"-.02em",lineHeight:1}}>{passed}</span>
              <span style={{fontSize:18,color:"var(--t2)",fontWeight:400,marginBottom:6}}>/ {receipts.length} passed</span>
            </div>
            {failed > 0 && (
              <div style={{marginTop:12,color:"var(--er)",fontSize:13}}>
                {failed} check{failed>1?"s":""} failed
              </div>
            )}
          </>
        )}
      </div>

      {!offline && receipts.map((r,i) => (
        <div key={i}>
          <div className="row" style={{cursor:"pointer"}} onClick={()=>setOpen(open===i?null:i)}>
            <div style={{width:6,height:6,borderRadius:"50%",background:r.ok?"var(--ok)":"var(--er)",flexShrink:0}}/>
            <span className="mono" style={{color:"var(--t2)",fontSize:12,flexShrink:0}}>#{r.id}</span>
            <span style={{flex:1,fontSize:14}}>{r.desc}</span>
            <span className="mono" style={{color:"var(--t3)",fontSize:11,flexShrink:0}}>{r.ts}</span>
            <ChevronRight size={13} style={{color:"var(--t3)",transform:open===i?"rotate(90deg)":"none",transition:"transform .15s",flexShrink:0}}/>
          </div>
          {open===i && (
            <div style={{padding:"0 22px 20px",marginTop:-4}}>
              <div className="mono" style={{fontSize:11,color:"var(--t2)",marginBottom:6}}>
                exit code: <span style={{color:"var(--t1)"}}>{r.exit_code}</span>
              </div>
              <div className="mono" style={{fontSize:10.5,color:"var(--t3)",wordBreak:"break-all"}}>{r.detail}</div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ContextView({context, loading, error}) {
  const files = context?.files || [];
  const total = context?.total_tokens || 0;
  const count = context?.file_count || 0;
  return (
    <div className={`view${loading?" loading":""}`} style={{paddingTop:88}}>
      <div style={{marginBottom:64}}>
        <div className="lbl" style={{marginBottom:20}}>Context pack</div>
        {error ? <Offline/> : (
          <>
            <div style={{fontSize:32,fontWeight:500,color:"var(--acc)",marginBottom:8}}>
              {context?.project || "opencobalt"}
            </div>
            <div style={{display:"flex",gap:24,color:"var(--t2)",fontSize:13}}>
              <span>{count} files</span>
              <span>·</span>
              <span>{total.toLocaleString()} tokens total</span>
            </div>
          </>
        )}
      </div>

      {!error && files.length === 0 && <Empty msg="No context pack — run opencobalt context"/>}
      {!error && files.map((f,i) => (
        <div key={i} className="row" style={{gap:16,flexWrap:"wrap"}}>
          <span className="mono" style={{flex:1,fontSize:13,color:"var(--t1)"}}>{f.n}</span>
          <div style={{width:120,height:2,borderRadius:100,background:"var(--sf)",overflow:"hidden",flexShrink:0}}>
            <div style={{width:`${f.pct}%`,height:"100%",borderRadius:100,background:"var(--acc)",opacity:.5}}/>
          </div>
          <span className="mono" style={{color:"var(--t3)",fontSize:11,width:64,textAlign:"right",flexShrink:0}}>
            {f.tok.toLocaleString()} tok
          </span>
        </div>
      ))}
    </div>
  );
}

function DesignLabView() {
  return (
    <div className="view" style={{paddingTop:88}}>
      <div className="lbl" style={{marginBottom:20}}>DesignLab</div>
      <div style={{fontSize:32,fontWeight:300,letterSpacing:"-.01em",marginBottom:16,lineHeight:1.3}}>
        Design token management<br/>
        <span style={{color:"var(--t2)"}}>and critique tooling.</span>
      </div>
      <div style={{color:"var(--t2)",fontSize:14,lineHeight:1.7,maxWidth:440}}>
        Screenshot critique loop, visual regression tests, image generation prompt adapter,
        icon and logo generation, diagram hooks, and project design memory.
      </div>
      <div style={{marginTop:48,display:"inline-flex",padding:"10px 20px",border:"1px solid var(--ln)",borderRadius:8,fontSize:13,color:"var(--t3)"}}>
        Coming in Phase 4
      </div>
    </div>
  );
}

const OcLogo = () => (
  <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
    <path d="M11 2L19 6.5V15.5L11 20L3 15.5V6.5L11 2Z"
      fill="var(--acc)" fillOpacity=".12" stroke="var(--acc)" strokeWidth="1" strokeLinejoin="round"/>
    <path d="M11 6L15.5 8.5V13.5L11 16L6.5 13.5V8.5L11 6Z" fill="var(--acc)" fillOpacity=".2"/>
    <circle cx="11" cy="11" r="2.4" fill="var(--acc)"/>
  </svg>
);

const NAV = [
  {id:"command",      Icon:Terminal,    label:"Command"},
  {id:"agents",       Icon:Network,     label:"Agents"},
  {id:"telemetry",    Icon:Gauge,       label:"Telemetry"},
  {id:"graph",        Icon:GitBranch,   label:"Graph"},
  {id:"ledger",       Icon:ScrollText,  label:"Ledger"},
  {id:"benchmarks",   Icon:Trophy,      label:"Benchmarks"},
  {id:"integrations", Icon:GitBranch,   label:"Integrations"},
  {id:"context",      Icon:Layers,      label:"Context"},
  {id:"receipts",     Icon:CheckSquare, label:"Receipts"},
  {id:"designlab",    Icon:Palette,     label:"DesignLab"},
];

function initialView() {
  const id = window.location.hash.replace("#", "");
  return NAV.some((item) => item.id === id) ? id : "command";
}

const _EMPTY_DATA = {
  sessions: [],
  agents: [],
  benchmarks: [],
  integrations: [],
  context: null,
  timeline: [],
  telemetry: null,
};

export default function App() {
  const [active, setActive] = useState(initialView);
  const [data, setData] = useState(_EMPTY_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const selectView = (id) => {
    setActive(id);
    window.location.hash = id;
  };

  const fetchAll = () => {
    Promise.all([
      fetch(`${API}/api/sessions`).then(r=>r.json()),
      fetch(`${API}/api/agents`).then(r=>r.json()),
      fetch(`${API}/api/benchmarks`).then(r=>r.json()),
      fetch(`${API}/api/integrations`).then(r=>r.json()),
      fetch(`${API}/api/context`).then(r=>r.json()),
      fetch(`${API}/api/timeline`).then(r=>r.json()),
      fetch(`${API}/api/telemetry`).then(r=>r.json()),
    ]).then(([sessions, agents, benchmarks, integrations, context, timeline, telemetry]) => {
      setData({sessions, agents, benchmarks, integrations, context, timeline, telemetry});
      setError(false);
      setLoading(false);
    }).catch(() => {
      setError(true);
      setLoading(false);
    });
  };

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 2000);
    return () => clearInterval(id);
  }, []);

  const views = {
    command:      <CommandView      sessions={data.sessions}      loading={loading} error={error} onRoute={fetchAll}/>,
    agents:       <AgentsView       agents={data.agents}           loading={loading} error={error}/>,
    telemetry:    <TelemetryView    telemetry={data.telemetry}     loading={loading} error={error}/>,
    graph:        <RoutingGraph     timeline={data.timeline}       loading={loading} error={error}/>,
    ledger:       <LedgerView       sessions={data.sessions} timeline={data.timeline} loading={loading} error={error}/>,
    benchmarks:   <BenchmarksView   benchmarks={data.benchmarks}   loading={loading} error={error}/>,
    integrations: <IntegrationsView integrations={data.integrations} loading={loading} error={error}/>,
    context:      <ContextView      context={data.context}         loading={loading} error={error}/>,
    receipts:     <ReceiptsView/>,
    designlab:    <DesignLabView/>,
  };

  return (
    <div style={{display:"flex",height:"100vh",background:"var(--bg)",overflow:"hidden"}}>
      <style>{CSS}</style>

      {/* Icon rail sidebar */}
      <div style={{
        width:56, flexShrink:0,
        display:"flex", flexDirection:"column", alignItems:"center",
        paddingTop:20, paddingBottom:20,
        borderRight:"1px solid var(--ln)",
        position:"sticky", top:0, height:"100vh", gap:4
      }}>
        <div style={{marginBottom:24}}><OcLogo/></div>
        {NAV.map(({id,Icon,label}) => (
          <button key={id} className="nb" title={label}
            onClick={()=>selectView(id)}
            style={{
              width:36, height:36, borderRadius:9,
              color: active===id ? "var(--acc)" : "rgba(255,255,255,.22)",
              background: active===id ? "rgba(123,158,255,.08)" : "none",
              border:"none"
            }}
          >
            <Icon size={16}/>
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="scr" style={{
        flex:1, overflowY:"auto",
        padding:"0 72px",
      }}>
        <div style={{maxWidth:640, margin:"0 auto", paddingBottom:80}}>
          {views[active]}
        </div>
      </div>
    </div>
  );
}

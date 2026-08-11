import React from "react";

function Inline({ children }) {
  const parts = String(children || "").split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    return part;
  });
}

function Prose({ text }) {
  const lines = text.split("\n");
  const nodes = [];
  let list = [];
  const flushList = () => {
    if (!list.length) return;
    nodes.push(<ul key={`list-${nodes.length}`}>{list.map((item, index) => <li key={index}><Inline>{item}</Inline></li>)}</ul>);
    list = [];
  };
  lines.forEach((line) => {
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) { list.push(bullet[1]); return; }
    flushList();
    if (!line.trim()) return;
    if (line.startsWith("### ")) nodes.push(<h4 key={`h-${nodes.length}`}><Inline>{line.slice(4)}</Inline></h4>);
    else if (line.startsWith("## ")) nodes.push(<h3 key={`h-${nodes.length}`}><Inline>{line.slice(3)}</Inline></h3>);
    else if (line.startsWith("# ")) nodes.push(<h2 key={`h-${nodes.length}`}><Inline>{line.slice(2)}</Inline></h2>);
    else nodes.push(<p key={`p-${nodes.length}`}><Inline>{line}</Inline></p>);
  });
  flushList();
  return nodes;
}

export default function Markdown({ content = "" }) {
  const pieces = String(content).split(/```([^\n]*)\n?([\s\S]*?)```/g);
  return (
    <div className="markdown">
      {pieces.map((piece, index) => {
        if (index % 3 === 1) return null;
        if (index % 3 === 2) {
          const language = pieces[index - 1] || "text";
          return <pre key={index}><span>{language}</span><code>{piece}</code></pre>;
        }
        return <Prose key={index} text={piece} />;
      })}
    </div>
  );
}

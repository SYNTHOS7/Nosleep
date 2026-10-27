"""Generate current Mermaid documentation and an offline SVG viewer from one specification."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "architecture.json"


def mermaid(diagram):
    lines = ["flowchart LR"]
    for node in diagram["nodes"]:
        lines.append(f'    {node["id"]}["{node["label"]}"]')
        if node.get("status") == "pending":
            lines.append(f'    style {node["id"]} stroke-dasharray: 5 5,fill:#263344')
    for edge in diagram["edges"]:
        lines.append(f'    {edge[0]} --> {edge[1]}')
    return "\n".join(lines)


def svg(diagram):
    nodes = {node["id"]: node for node in diagram["nodes"]}
    width = (max(n["x"] for n in nodes.values()) + 1) * 280 + 30
    height = (max(n["y"] for n in nodes.values()) + 1) * 120 + 30
    parts = [f'<svg role="img" aria-label="{html.escape(diagram["title"])}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">',
             '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#647c99"/></marker></defs>']
    for source, target in diagram["edges"]:
        a, b = nodes[source], nodes[target]
        ax, ay, bx, by = a["x"] * 280 + 140, a["y"] * 120 + 55, b["x"] * 280 + 140, b["y"] * 120 + 55
        if ax != bx:
            ax += 125 if bx > ax else -125
            bx += -125 if bx > ax else 125
        else:
            ay += 36 if by > ay else -36
            by += -36 if by > ay else 36
        parts.append(f'<path d="M{ax},{ay} L{bx},{by}" fill="none" stroke="#647c99" stroke-width="2" marker-end="url(#arrow)"/>')
    for node in nodes.values():
        x, y = node["x"] * 280 + 15, node["y"] * 120 + 20
        pending = node.get("status") == "pending"
        border = '#e7b96d' if pending else '#5ecac3'
        dash = ' stroke-dasharray="6 4"' if pending else ''
        parts.append(f'<rect x="{x}" y="{y}" width="250" height="72" rx="9" fill="#172438" stroke="{border}"{dash}/>')
        words, lines, current = node["label"].split(), [], ""
        for word in words:
            if len(current + " " + word) > 31:
                lines.append(current)
                current = word
            else:
                current = (current + " " + word).strip()
        lines.append(current)
        for index, line in enumerate(lines):
            parts.append(f'<text x="{x+125}" y="{y+30+index*18}" fill="#edf4ff" font-size="14" font-family="system-ui,sans-serif" text-anchor="middle">{html.escape(line)}</text>')
    return "".join(parts) + "</svg>"


def generate():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    markdown = ["# AegisGraph — current architecture and flowcharts", "", spec["summary"], "",
                "Solid boxes: implemented. Dashed boxes: configured or planned; live verification may still be pending.", ""]
    sections = []
    for diagram in spec["diagrams"]:
        code = mermaid(diagram)
        markdown += [f'## {diagram["title"]}', "", diagram["description"], "", "```mermaid", code, "```", ""]
        sections.append(f'<section id="{diagram["id"]}"><h2>{html.escape(diagram["title"])}</h2><p>{html.escape(diagram["description"])}</p><div class="chart">{svg(diagram)}</div><details><summary>Mermaid source</summary><pre>{html.escape(code)}</pre></details></section>')
    markdown += ["## Upstream projects", ""] + [f'- [{p["name"]}]({p["url"]}): {p["usage"]}' for p in spec["projects"]]
    content = "\n".join(markdown) + "\n"
    (ROOT / "CYBERSECURITY_SYSTEM_FLOWCHARTS.md").write_text(content, encoding="utf-8")
    (ROOT / "interactive_knowledge_base_architecture_phase1_phase2_v2.md").write_text(content, encoding="utf-8")
    links = " · ".join(f'<a href="#{d["id"]}">{html.escape(d["title"])}</a>' for d in spec["diagrams"])
    projects = "".join(f'<li><a href="{p["url"]}">{html.escape(p["name"])}</a> — {html.escape(p["usage"])}</li>' for p in spec["projects"])
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AegisGraph architecture</title><style>body{margin:0;background:#0e1726;color:#edf4ff;font:16px/1.6 system-ui,sans-serif}main{max-width:1280px;margin:auto;padding:32px}a{color:#81dcd6}nav{display:flex;gap:12px;flex-wrap:wrap}section{margin:32px 0;padding:24px;border:1px solid #34475f;border-radius:12px;background:#121e30}h1{font-size:38px;letter-spacing:-1px}h2{font-size:24px}p{color:#bacbdd}.chart{overflow-x:auto}svg{width:100%;min-width:760px;display:block}pre{white-space:pre-wrap;font-size:13px}.badge{border-left:4px solid #5ecac3;padding:12px 18px;background:#172438}@media(max-width:640px){main{padding:16px}section{padding:14px}h1{font-size:29px}}</style><main><header><p>AEGISGRAPH / ENGINEERING MAP / 27 OCTOBER 2026</p><h1>From evidence to investigation</h1><p>' + html.escape(spec["summary"]) + '</p><p class="badge">Solid boxes: implemented locally. Dashed boxes: configured or planned. No external fonts, scripts or diagram services are required.</p><nav>' + links + '</nav></header>' + ''.join(sections) + '<section><h2>Upstream projects and boundaries</h2><ul>' + projects + '</ul></section></main></html>'
    (ROOT / "flowcharts.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    generate()

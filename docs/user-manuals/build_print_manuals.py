#!/usr/bin/env python3
"""Build dependency-free print HTML from the two reviewed Markdown manuals."""

from __future__ import annotations

import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def inline(value: str) -> str:
    value = html.escape(value, quote=False)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    return value


def render_markdown(source: str) -> str:
    lines = source.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    in_code = False
    code_lines: list[str] = []
    h1_count = 0
    index = 0

    def close_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            output.append(f"</{list_type}>")
            list_type = None

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()

        if stripped.startswith("```"):
            close_paragraph()
            close_list()
            if in_code:
                output.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(raw)
            index += 1
            continue

        if stripped.startswith("|") and index + 1 < len(lines):
            separator = lines[index + 1].strip()
            if separator.startswith("|") and re.fullmatch(r"[|:\- ]+", separator):
                close_paragraph()
                close_list()
                rows: list[list[str]] = []
                while index < len(lines) and lines[index].strip().startswith("|"):
                    cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                    rows.append(cells)
                    index += 1
                header = rows[0]
                body = rows[2:]
                output.append("<table><thead><tr>" + "".join(f"<th>{inline(cell)}</th>" for cell in header) + "</tr></thead><tbody>")
                for row in body:
                    output.append("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>")
                output.append("</tbody></table>")
                continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            close_paragraph()
            close_list()
            level = len(heading.group(1))
            if level == 1:
                h1_count += 1
            css_class = (
                "cover-title" if level == 1 and h1_count == 1
                else "cover-subtitle" if level == 1 and h1_count == 2
                else ""
            )
            output.append(f'<h{level} class="{css_class}">{inline(heading.group(2))}</h{level}>')
            index += 1
            continue

        if stripped == "---":
            close_paragraph()
            close_list()
            output.append("<hr>")
            index += 1
            continue

        item = re.match(r"^\s*([-*])\s+(.+)$", raw)
        numbered = re.match(r"^\s*\d+\.\s+(.+)$", raw)
        if item or numbered:
            close_paragraph()
            wanted = "ul" if item else "ol"
            if list_type != wanted:
                close_list()
                list_type = wanted
                output.append(f"<{wanted}>")
            content = item.group(2) if item else numbered.group(1)
            output.append(f"<li>{inline(content)}</li>")
            index += 1
            continue

        if not stripped:
            close_paragraph()
            close_list()
        else:
            paragraph.append(stripped)
        index += 1

    close_paragraph()
    close_list()
    return "\n".join(output)


STYLE = """
@page {
  size: A4;
  margin: 18mm 16mm 19mm;
  @bottom-center { content: "__FOOTER__ — Page " counter(page) " of " counter(pages); color: #526259; font-size: 8pt; }
}
* { box-sizing: border-box; }
html { font-family: Arial, Helvetica, sans-serif; color: #1c2520; font-size: 10.5pt; line-height: 1.42; }
body { margin: 0; }
h1 { color: #174f38; font-size: 22pt; border-bottom: 2px solid #174f38; padding-bottom: 5mm; margin: 0 0 7mm; break-before: page; }
h1.cover-title { break-before: auto; border: 0; font-size: 31pt; margin: 22mm 0 4mm; padding: 0; text-align: center; }
h1.cover-subtitle { break-before: auto; border: 0; font-size: 24pt; margin: 10mm 0 10mm; padding: 0; text-align: center; }
h2 { color: #174f38; font-size: 16pt; margin: 7mm 0 3mm; break-after: avoid; }
h3 { color: #2f654b; font-size: 12.5pt; margin: 5mm 0 2mm; break-after: avoid; }
h4, h5, h6 { color: #2f654b; break-after: avoid; }
p { margin: 0 0 3.2mm; orphans: 3; widows: 3; }
strong { color: #14271d; }
ul, ol { margin: 1.5mm 0 4mm 6mm; padding-left: 5mm; }
li { margin-bottom: 1.2mm; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0 6mm; font-size: 8.8pt; break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { color: #fff; background: #174f38; text-align: left; }
th, td { border: 0.25mm solid #aebdb4; padding: 2mm; vertical-align: top; }
tbody tr:nth-child(even) { background: #f2f6f3; }
pre { white-space: pre-wrap; border: 0.25mm solid #b8c7be; background: #f4f7f5; padding: 4mm; break-inside: avoid; font-size: 8.5pt; }
code { font-family: "DejaVu Sans Mono", monospace; background: #eef3f0; padding: 0 .7mm; }
hr { border: 0; border-top: .25mm solid #b8c7be; margin: 8mm 0; }
p:has(strong:first-child) { break-inside: avoid; }
p:has(strong:first-child):has(strong:last-child) { padding: 3mm; border: .35mm solid #8aa596; background: #f4f8f5; }
"""


def main() -> None:
    for source_path in sorted(ROOT.glob("GoHMoTech_*_User_Manual.md")):
        title = source_path.stem.replace("_", " ")
        body = render_markdown(source_path.read_text(encoding="utf-8"))
        footer = "Administrator Manual" if "Administrator" in title else "Farm Owner Manual"
        document = (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(title)}</title><style>{STYLE.replace('__FOOTER__', footer)}</style></head>"
            f"<body>{body}</body></html>"
        )
        source_path.with_suffix(".html").write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()

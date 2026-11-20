"""Convert the small Markdown subset used by docs/GRADING_CRITERIA.md into Typst.

Supported: #/##/### headings, paragraphs, bullet and numbered lists, pipe tables,
fenced code blocks, **bold**, *italic* and `code`. All text is emitted as Typst string
literals, so nothing in the source can be mistaken for Typst markup.

Usage: python tools/md_to_typst.py <input.md> <output.typ>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PREAMBLE = """#set document(title: {title})
#set page(paper: "a4", margin: (x: 1.8cm, y: 2cm), numbering: "1 / 1",
  header: context {{ if counter(page).get().first() > 1 [#text(8pt, fill: luma(110))[{header}] #h(1fr) #text(8pt, fill: luma(110))[Unofficial teaching rubric]] }})
#set text(font: "Libertinus Serif", size: 9.5pt, lang: "en")
#set par(justify: false, leading: 0.6em)
#show heading.where(level: 1): it => block(below: 0.5em)[#text(20pt, weight: "bold")[#it.body]]
#show heading.where(level: 2): it => block(above: 1.3em, below: 0.6em)[#text(13pt, weight: "bold")[#it.body]]
#show heading.where(level: 3): it => block(above: 1em, below: 0.5em)[#text(10.5pt, weight: "bold")[#it.body]]
#show raw: set text(font: "DejaVu Sans Mono", size: 8pt)
#set table(stroke: 0.4pt + luma(170), inset: (x: 5pt, y: 4pt))
#show table.cell.where(y: 0): set text(weight: "bold")
"""

_INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*\s][^*]*\*|`[^`]+`)")


def string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def inline(text: str) -> str:
    parts = []
    for token in _INLINE.split(text):
        if not token:
            continue
        if token.startswith("**"):
            parts.append(f"#strong({string(token[2:-2].replace('`', ''))});")
        elif token.startswith("*"):
            parts.append(f"#emph({string(token[1:-1])});")
        elif token.startswith("`"):
            parts.append(f"#raw({string(token[1:-1])});")
        else:
            parts.append(f"#{string(token)};")
    return "".join(parts)


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table(rows: list[list[str]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    columns = ", ".join("auto" if width <= 14 else f"{max(1.0, width**0.5 / 4):.2f}fr" for width in widths)
    header = ", ".join(f"[{inline(cell)}]" for cell in rows[0])
    body = ",\n  ".join(", ".join(f"[{inline(cell)}]" for cell in row) for row in rows[1:])
    return f"#table(columns: ({columns}),\n  table.header({header}),\n  {body},\n)"


def convert(markdown: str) -> str:
    lines = markdown.splitlines()
    title = next((line[2:] for line in lines if line.startswith("# ")), "Document")
    out = [PREAMBLE.format(title=string(title), header=title)]
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            end = next((i for i in range(index + 1, len(lines)) if lines[i].startswith("```")), None)
            if end is None:
                raise ValueError(f"code fence opened on line {index + 1} is never closed")
            out.append(f"#raw(block: true, {string(chr(10).join(lines[index + 1 : end]))})")
            index = end + 1
        elif line.startswith("|"):
            end = index
            while end < len(lines) and lines[end].startswith("|"):
                end += 1
            rows = [cells(row) for row in lines[index:end] if not re.fullmatch(r"\|[-| ]+\|", row.strip())]
            out.append(table(rows))
            index = end
        elif match := re.match(r"(#{1,3}) (.+)", line):
            out.append(f"{'=' * len(match.group(1))} {inline(match.group(2))}")
            index += 1
        elif match := re.match(r"(- |\d+\. )(.+)", line):
            out.append(f"{'-' if match.group(1) == '- ' else '+'} {inline(match.group(2))}")
            index += 1
        elif not line.strip():
            out.append("")
            index += 1
        else:
            end = index
            while end < len(lines) and lines[end].strip() and not re.match(r"(#|\||```|- |\d+\. )", lines[end]):
                end += 1
            out.append(inline(" ".join(part.strip() for part in lines[index:end])))
            index = end
    return "\n".join(out) + "\n"


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write(__doc__ or "")
        return 2
    Path(sys.argv[2]).write_text(convert(Path(sys.argv[1]).read_text(encoding="utf-8")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

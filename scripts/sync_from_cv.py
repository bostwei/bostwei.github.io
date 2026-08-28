#!/usr/bin/env python3
"""Sync GitHub Pages markdown from the Overleaf CV.

Source of truth: the LaTeX CV (Dropbox/Overleaf).
This repo: presentation layer (theme, coauthor links, news).

Usage:
  python3 scripts/sync_from_cv.py
  python3 scripts/sync_from_cv.py --check-google
  python3 scripts/sync_from_cv.py --cv "/path/to/Shiyan_Wei_CV.tex"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).resolve().parent / "site_config.json"


def load_config(cv_override: str | None = None) -> dict:
    data = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else _fallback_config()
    if cv_override:
        data["cv_tex"] = cv_override
    return data


def _fallback_config() -> dict:
    return {
        "cv_tex": "/Users/shiyan/Library/CloudStorage/Dropbox/Apps/Overleaf/Shiyan CV/Shiyan_Wei_CV.tex",
        "google_sites": {
            "home": "https://sites.google.com/view/shiyanwei/home",
            "research": "https://sites.google.com/view/shiyanwei/research",
            "teaching": "https://sites.google.com/view/shiyanwei/teaching",
        },
        "cv_download": "https://www.dropbox.com/scl/fi/6c18vqjr0tv0atf17jxrp/Shiyan_CV.pdf?rlkey=6x4ku0p8tjca74opp8wdwfgz2&st=utjgjd3c&dl=0",
        "coauthors": {
            "Chong Huang": "https://chonghuang.weebly.com/",
            "Erica Moszkowski": "https://www.ericamoszkowski.com/home",
            "Gregor Schubert": "https://sites.google.com/view/gregorschubert",
        },
        "paper_overrides": {
            "Data Ownership, Data Production, and Lending Market Competition": {
                "ssrn": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6562338",
            },
            "Large Investor, Information Advantage and the Fragility of the Asset Market": {
                "subtitle": "Job Market Paper",
            },
            "The Behavior of Generative AI Assists Investors and its Impact on the Asset Pricing": {
                "presentations": 'FMA "New Ideas" Session (2025)',
            },
            "Age Structure and Housing Affordability": {
                "coauthor_note": "* presented by coauthors",
            },
        },
        "nav": "[Home](/) | [Research](/research) | [Teaching](/teaching) | [CV](/cv)",
    }


def extract_balanced(text: str, start: int) -> tuple[str, int]:
    """text[start] must be '{'. Return inner content and index after the closing brace."""
    assert text[start] == "{"
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
    raise ValueError("unbalanced brace")


def find_commands(text: str, command: str) -> list[tuple[int, str, int]]:
    """Return (start_index, inner, end_index) for each \\command{...}."""
    needle = "\\" + command + "{"
    out = []
    i = 0
    while True:
        j = text.find(needle, i)
        if j == -1:
            break
        inner, end = extract_balanced(text, j + len(command) + 1)
        out.append((j, inner, end))
        i = end
    return out


def strip_tex(text: str) -> str:
    text = text.replace("~", " ")
    # unwrap nested commands repeatedly
    for _ in range(6):
        text = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\(?:textbf|textit|emph|small|textbf)\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\{\\small\s*([^{}]*)\}", r"\1", text)
    text = text.replace("\\&", "&")
    text = text.replace("\\%", "%")
    text = text.replace("\\,", " ")
    text = text.replace("``", '"').replace("''", '"')
    text = text.replace("\\newline", " ")
    text = text.replace("\\\\", " ")
    text = re.sub(r"%.*", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", " ", text)
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n+ *", " ", text)
    return re.sub(r"\s+", " ", text).strip(" \t\n;")


def section_body(tex: str, name: str) -> str:
    pattern = rf"\\section\*?{{{re.escape(name)}}}(.*?)(?=\\section|\Z)"
    match = re.search(pattern, tex, re.S)
    return match.group(1) if match else ""


def extract_resume_items(block: str) -> list[str]:
    items = []
    for _, inner, _ in find_commands(block, "resumeItem"):
        items.append(strip_tex(inner.rstrip(".")))
    return items


def split_subheadings(block: str) -> list[tuple[str, str, str]]:
    matches = list(re.finditer(r"\\resumeSubheading\s*", block))
    results = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        part = block[start:end]
        args = []
        i = 0
        while i < len(part) and len(args) < 4:
            if part[i] == "{":
                inner, nxt = extract_balanced(part, i)
                args.append(inner)
                i = nxt
            else:
                i += 1
        institution = strip_tex(args[0]) if args else ""
        role = strip_tex(args[2]) if len(args) > 2 else ""
        results.append((institution, role, part))
    return results


def is_uci_undergrad(course: str) -> bool:
    return bool(re.match(r"MGMT\s+\d{3}\b", course)) and not course.upper().startswith("MGMT FE")


def render_course_group(title: str, courses: list[str]) -> str:
    if not courses:
        return ""
    lines = [f"*{title}*", ""]
    for course in courses:
        lines.append(f"* {course}")
    lines.append("")
    return "\n".join(lines)


def build_teaching_md(tex: str, nav: str) -> str:
    body = section_body(tex, "Teaching Experience")
    chunks = []
    for institution, role, inner in split_subheadings(body):
        instructor, ta = [], []
        if role.lower().startswith("instructor"):
            ta_split = re.search(r"Teaching Assistant", inner)
            if ta_split:
                instructor = extract_resume_items(inner[: ta_split.start()])
                ta = extract_resume_items(inner[ta_split.start() :])
            else:
                instructor = extract_resume_items(inner)
        else:
            ta = extract_resume_items(inner)

        lines = [f"### {institution}", ""]
        if instructor:
            lines += ["**Instructor**", "", render_course_group("Graduate Level", instructor)]
        if ta:
            lines.append("**Teaching Assistant**")
            lines.append("")
            if "Wisconsin" in institution:
                undergrad = [c for c in ta if re.search(r"\(Undergraduate\)", c, re.I)]
                grad = [c for c in ta if c not in undergrad]
                lines.append(render_course_group("Undergraduate Level", undergrad))
                lines.append(render_course_group("Graduate Level", grad))
            else:
                undergrad = [c for c in ta if is_uci_undergrad(c)]
                grad = [c for c in ta if c not in undergrad]
                lines.append(render_course_group("Undergraduate Level", undergrad))
                lines.append(render_course_group("Graduate Level", grad))
        chunks.append("\n".join(lines).rstrip() + "\n")

    return "\n".join(
        [
            "---",
            "layout: default",
            "---",
            "",
            nav,
            "",
            "## Teaching",
            "",
            "\n".join(chunks).rstrip(),
            "",
        ]
    )


def extract_paper_blocks(section: str) -> list[str]:
    body = re.sub(r"^.*?\\begin\{enumerate\}", "", section, flags=re.S)
    body = re.sub(r"\\end\{enumerate\}.*", "", body, flags=re.S)
    parts = re.split(
        r"(?=\\item\s+(?:\\href|\\textbf\{(?!Award|Abstract|Abstrct|Presented)))",
        body,
    )
    return [p.strip() for p in parts if p.strip() and re.search(r"\\textbf\{", p)]


def parse_paper(block: str) -> dict:
    hrefs = find_commands(block, "href")
    url, title = "", ""
    if hrefs:
        url = hrefs[0][1]
        title_inner = re.search(r"\\textbf\{([^{}]*)\}", block[hrefs[0][0] : hrefs[0][2]])
        title = strip_tex(title_inner.group(1) if title_inner else "")
    if not title:
        bolds = find_commands(block, "textbf")
        if bolds:
            title = strip_tex(bolds[0][1])

    with_m = re.search(r"with\s*\\textit\{([^}]*)\}", block)
    coauthors = []
    if with_m:
        names = strip_tex(with_m.group(1)).replace(", and ", ", ").replace(" and ", ", ")
        names = names.replace("Gregor Schuber", "Gregor Schubert")
        coauthors = [n.strip(" ,") for n in names.split(",") if n.strip(" ,")]

    status = ""
    status_m = re.search(r"\\small\{?\s*\(([^)]*)\)\}?", block.split("\\begin{itemize}")[0])
    if status_m:
        status = strip_tex(status_m.group(1))

    def field(*labels: str) -> str:
        for label in labels:
            m = re.search(
                rf"\\textbf\{{{re.escape(label)}\}}\s*:?\s*(.*?)(?=\\item\s*\\textbf|\\end\{{itemize\}}|\Z)",
                block,
                re.S | re.I,
            )
            if m:
                return strip_tex(m.group(1))
        return ""

    return {
        "title": title,
        "url": url,
        "coauthors": coauthors,
        "status": status,
        "award": field("Award"),
        "abstract": field("Abstract", "Abstrct"),
        "presentations": field("Presented at", "Presentations"),
    }


def link_coauthors(names: list[str], urls: dict) -> str:
    linked = []
    for name in names:
        url = urls.get(name)
        linked.append(f"[{name}]({url})" if url else name)
    if not linked:
        return ""
    if len(linked) == 1:
        return f"*with {linked[0]}*"
    return "*with " + ", ".join(linked[:-1]) + " and " + linked[-1] + "*"


def render_paper(paper: dict, config: dict) -> str:
    overrides = (config.get("paper_overrides") or {}).get(paper["title"], {})
    urls = config.get("coauthors") or {}
    title = paper["title"]
    ssrn = overrides.get("ssrn") or paper.get("url")
    subtitle = overrides.get("subtitle")
    if subtitle:
        title_line = f"### {title} ({subtitle})"
    elif ssrn:
        title_line = f"### [{title}]({ssrn})"
    else:
        title_line = f"### {title}"

    lines = [title_line]
    coauthor_line = link_coauthors(paper["coauthors"], urls)
    extras = []
    if paper.get("status"):
        extras.append(f"({paper['status']})")
    if ssrn and (paper["coauthors"] or paper.get("status")):
        extras.append(f"([SSRN]({ssrn}))")
    if coauthor_line:
        lines.append(coauthor_line + ((" " + " ".join(extras)) if extras else ""))
    elif extras:
        lines.append(" ".join(extras))

    award = paper.get("award")
    abstract = paper.get("abstract")
    presentations = overrides.get("presentations") or paper.get("presentations")
    if award:
        lines.append(f"* **Award:** {award}")
    if abstract:
        lines.append(f"* **Abstract:** {abstract}")
    if presentations:
        note = overrides.get("coauthor_note")
        if note and "*" in presentations:
            presentations = f"{presentations} ({note})"
        lines.append(f"* **Presentations:** {presentations}")
    return "\n".join(lines) + "\n"


def build_research_md(tex: str, config: dict) -> str:
    nav = config.get("nav", "")
    working = [parse_paper(b) for b in extract_paper_blocks(section_body(tex, "Working Paper"))]
    progress = [parse_paper(b) for b in extract_paper_blocks(section_body(tex, "Research Work in Progress"))]
    pubs_body = section_body(tex, "Publications (in Chinese)")
    pubs = []
    for raw in re.findall(r"\\item\s+(.*?)(?=\\item|\\end\{enumerate\}|\Z)", pubs_body, re.S):
        text = strip_tex(raw)
        if text:
            pubs.append(text)

    parts = [
        "---",
        "layout: default",
        "---",
        "",
        nav,
        "",
        "## Research",
        "",
        "**Working Paper**",
        "",
    ]
    for paper in working:
        parts.append(render_paper(paper, config))
        parts.append("")
    parts += ["**Research in Progress**", ""]
    for paper in progress:
        parts.append(render_paper(paper, config))
        parts.append("")
    parts += ["## Publications (in Chinese)"]
    for pub in pubs:
        parts.append(f"* {pub}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def parse_service(tex: str) -> dict[str, str]:
    body = section_body(tex, "Professional Activity and Service")
    body = re.split(r"\\end\{itemize\}", body, maxsplit=1)[0]
    body = re.sub(r"%.*", "", body)
    items = {}
    for label, raw in re.findall(
        r"\\item\s+\\textbf\{([^}]*)\}\s*:?\s*(.*?)(?=\\item|\Z)",
        body,
        re.S,
    ):
        items[strip_tex(label)] = strip_tex(raw)
    return items


def update_readme_service(readme: str, service: dict[str, str]) -> str:
    if not service:
        return readme
    block_lines = ["## Professional Activity", ""]
    for key in ("Referee", "Discussant", "Seminar Co-Organizer"):
        if key in service:
            block_lines.append(f"* **{key}:** {service[key]}")
    block = "\n".join(block_lines) + "\n\n---\n"
    if "## Professional Activity" in readme:
        return re.sub(
            r"## Professional Activity\n.*?(?=\n## |\Z)",
            block,
            readme,
            flags=re.S,
        )
    if "## Follow me on" in readme:
        return readme.replace("## Follow me on", block + "\n## Follow me on")
    return readme.rstrip() + "\n\n" + block


def build_cv_md(config: dict) -> str:
    url = config.get("cv_download", "")
    nav = config.get("nav", "")
    return (
        "---\nlayout: default\n---\n\n"
        f"{nav}\n\n"
        "## CV\n\n"
        f"You can download my CV [here]({url}).\n"
    )


def write_if_changed(path: Path, content: str) -> bool:
    old = path.read_text() if path.exists() else None
    if old == content:
        return False
    path.write_text(content)
    return True


def check_google(config: dict) -> None:
    urls = config.get("google_sites") or {}
    try:
        import urllib.request
    except ImportError:
        print("urllib unavailable; skip Google Sites check", file=sys.stderr)
        return
    print("Google Sites snapshot:")
    for name, url in urls.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text)
            print(f"  {name}: {len(text)} chars from {url}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {name}: could not fetch ({exc})")
    print(
        "Google Sites cannot be written automatically. "
        "Treat the Overleaf CV as the source of truth and this GitHub site as the public copy."
    )


def debounce_if_needed(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync GitHub Pages content from the Overleaf CV.")
    parser.add_argument("--cv", help="Path to Shiyan_Wei_CV.tex")
    parser.add_argument("--check-google", action="store_true", help="Fetch Google Sites and print a drift notice")
    parser.add_argument("--debounce", type=float, default=0, help="Seconds to wait before reading the CV")
    args = parser.parse_args()

    debounce_if_needed(args.debounce)
    config = load_config(args.cv)
    cv_path = Path(config["cv_tex"]).expanduser()
    if not cv_path.exists():
        print(f"CV not found: {cv_path}", file=sys.stderr)
        return 1

    tex = cv_path.read_text(encoding="utf-8")
    changed = []
    if write_if_changed(ROOT / "teaching.md", build_teaching_md(tex, config.get("nav", ""))):
        changed.append("teaching.md")
    if write_if_changed(ROOT / "research.md", build_research_md(tex, config)):
        changed.append("research.md")
    if write_if_changed(ROOT / "cv.md", build_cv_md(config)):
        changed.append("cv.md")

    readme_path = ROOT / "README.md"
    new_readme = update_readme_service(readme_path.read_text(), parse_service(tex))
    if write_if_changed(readme_path, new_readme):
        changed.append("README.md")

    if changed:
        print("Updated: " + ", ".join(changed))
    else:
        print("Already in sync with the CV.")

    if args.check_google:
        check_google(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())

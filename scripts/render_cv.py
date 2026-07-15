#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime
import html
import pathlib
import subprocess
import sys
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable
from reportlab.platypus import ListItem
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer


ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "profile.yaml"
VARIANTS_DIR = ROOT / "variants"
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_MARKDOWN_DIR = ROOT / "output" / "markdown"
OUTPUT_PDF_DIR = ROOT / "output" / "pdf"
TMP_HTML_DIR = ROOT / "tmp" / "rendered_html"
PLAYWRIGHT_RENDERER = ROOT / "scripts" / "render_pdf_playwright.js"


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def format_date_label(start: str, end: str) -> str:
    return f"{humanize_month_period(start)} - {humanize_month_period(end)}"


def humanize_month_period(value: str) -> str:
    if value == "present":
        return "Present"
    year, month = value.split("-")
    names = {
        "01": "Jan",
        "02": "Feb",
        "03": "Mar",
        "04": "Apr",
        "05": "May",
        "06": "Jun",
        "07": "Jul",
        "08": "Aug",
        "09": "Sep",
        "10": "Oct",
        "11": "Nov",
        "12": "Dec",
    }
    return f"{names[month]} {year}"


def humanize_year_period(value: str) -> str:
    if value == "present":
        return "Present"
    return value


def format_period_text(value: str) -> str:
    value = str(value)
    if " to " in value:
        start, end = value.split(" to ", 1)
        return f"{humanize_month_period(start)} - {humanize_month_period(end)}"
    if "-" in value and value.count("-") == 1:
        start, end = value.split("-", 1)
        return f"{humanize_year_period(start)} - {humanize_year_period(end)}"
    return value


def pick_by_ids(items: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in items}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def pick_education(profile: dict[str, Any], variant: dict[str, Any]) -> list[dict[str, Any]]:
    if variant.get("show_full_education"):
        return [enrich_education_item(item) for item in profile["education"]]

    wanted = set(variant.get("education_ids", []))
    if not wanted:
        return [enrich_education_item(item) for item in profile["education"]]
    return [enrich_education_item(item) for item in profile["education"] if item["degree"] in wanted]


def enrich_education_item(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    enriched["period"] = format_period_text(item["period"])
    details = []
    for detail in item.get("details", []):
        if ":" in detail:
            label, value = detail.split(":", 1)
            details.append({"label": label.strip(), "value": value.strip()})
        elif detail.startswith("GPA "):
            details.append({"label": "GPA", "value": detail.replace("GPA ", "", 1).strip()})
        else:
            details.append({"label": "", "value": detail})
    enriched["detail_rows"] = details
    return enriched


def format_skill_entry(entry: Any) -> dict[str, str] | None:
    if isinstance(entry, str):
        return {"markdown": entry, "html": entry, "pdf": html.escape(entry)}

    name = entry["name"]
    status = entry.get("status", "current")
    note = entry.get("note")

    if status == "review_remove":
        return None

    if status == "past":
        suffix = f" (past: {note})" if note else " (past)"
        return {
            "markdown": f"{name}{suffix}",
            "html": (
                f'<span class="skill-past">{html.escape(name)}</span>'
                f'<span class="skill-note">{html.escape(suffix)}</span>'
            ),
            "pdf": (
                f"{html.escape(name)}"
                f'<font color="#5b6472"><i>{html.escape(suffix)}</i></font>'
            ),
        }

    return {"markdown": name, "html": html.escape(name), "pdf": html.escape(name)}


def collect_skill_entries(entries: list[Any]) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    for entry in entries:
        formatted = format_skill_entry(entry)
        if formatted is not None:
            collected.append(formatted)
    return collected


def build_skill_sections(group_value: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section_name, entries in group_value.items():
        if isinstance(entries, dict):
            subsections = []
            for subsection_name, subsection_entries in entries.items():
                formatted_entries = collect_skill_entries(subsection_entries)
                if formatted_entries:
                    subsections.append({"name": subsection_name, "entries": formatted_entries})
            if subsections:
                sections.append(
                    {
                        "name": section_name,
                        "type": "nested",
                        "subsections": subsections,
                    }
                )
            continue

        formatted_entries = collect_skill_entries(entries)
        if formatted_entries:
            sections.append(
                {
                    "name": section_name,
                    "type": "flat",
                    "entries": formatted_entries,
                }
            )
    return sections


def build_skill_group(group_value: Any) -> dict[str, Any]:
    if isinstance(group_value, dict):
        return {
            "type": "sectioned",
            "sections": build_skill_sections(group_value),
        }
    return {
        "type": "flat",
        "entries": collect_skill_entries(group_value),
    }


def build_selected_groups(profile: dict[str, Any], group_names: list[str]) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for group_name in group_names:
        built_group = build_skill_group(profile["skills"][group_name])
        if built_group["type"] == "sectioned" and not built_group["sections"]:
            continue
        if built_group["type"] == "flat" and not built_group["entries"]:
            continue
        selected[group_name] = built_group
    return selected


def flatten_group_for_sidebar(group: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if group["type"] == "flat":
        if group["entries"]:
            lines.append(join_skill_entries(group["entries"], "html"))
        return lines

    for section in group["sections"]:
        if section["type"] == "flat":
            if section["entries"]:
                lines.append(join_skill_entries(section["entries"], "html"))
            continue

        for subsection in section["subsections"]:
            if subsection["entries"]:
                lines.append(join_skill_entries(subsection["entries"], "html"))
    return lines


def strip_past_markers(text: str) -> str:
    return text.replace(" (past)", "")


def collect_sidebar_lines(group: dict[str, Any], include_past: bool) -> list[str]:
    lines: list[str] = []
    if group["type"] == "flat":
        if group["entries"]:
            filtered = []
            for entry in group["entries"]:
                is_past = " (past" in entry["markdown"]
                if is_past == include_past:
                    filtered.append(strip_past_markers(entry["html"]))
            if filtered:
                lines.append(", ".join(filtered))
        return lines

    for section in group["sections"]:
        if section["type"] == "flat":
            filtered = []
            for entry in section["entries"]:
                is_past = " (past" in entry["markdown"]
                if is_past == include_past:
                    filtered.append(strip_past_markers(entry["html"]))
            if filtered:
                lines.append(", ".join(filtered))
            continue

        for subsection in section["subsections"]:
            filtered = []
            for entry in subsection["entries"]:
                is_past = " (past" in entry["markdown"]
                if is_past == include_past:
                    filtered.append(strip_past_markers(entry["html"]))
            if filtered:
                lines.append(", ".join(filtered))
    return lines


def condense_sidebar_lines(group_name: str, lines: list[str]) -> list[str]:
    return lines


def build_sidebar_group(group_name: str, group: dict[str, Any]) -> list[str]:
    if group_name == "Selected Frameworks and Tools" and group["type"] == "sectioned":
        grouped_lines: list[str] = []
        for section in group["sections"]:
            current_entries: list[str] = []
            past_entries: list[str] = []

            if section["type"] == "flat":
                for entry in section["entries"]:
                    is_past = " (past" in entry["markdown"]
                    if is_past:
                        past_entries.append(strip_past_markers(entry["html"]))
                    else:
                        current_entries.append(strip_past_markers(entry["html"]))
            else:
                for subsection in section["subsections"]:
                    for entry in subsection["entries"]:
                        is_past = " (past" in entry["markdown"]
                        if is_past:
                            past_entries.append(strip_past_markers(entry["html"]))
                        else:
                            current_entries.append(strip_past_markers(entry["html"]))

            if current_entries:
                grouped_lines.append(
                    f"<strong>{html.escape(section['name'])}</strong><br>{', '.join(current_entries)}"
                )
            if past_entries:
                grouped_lines.append(
                    f"<strong>{html.escape(section['name'])} (Earlier)</strong><br>{', '.join(past_entries)}"
                )

        if grouped_lines:
            return grouped_lines

    current_lines = collect_sidebar_lines(group, include_past=False)
    past_lines = collect_sidebar_lines(group, include_past=True)

    condensed = condense_sidebar_lines(group_name, current_lines)

    if past_lines:
        label = "Past Experience" if group_name == "Machine Learning, Speech, and Signal Processing" else "Past Tools"
        condensed.append(f"<strong>{label}:</strong><br>{' '.join(past_lines)}")

    return condensed


def build_context(profile: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    experiences = []
    for item in pick_by_ids(profile["experience"], variant["experience_ids"]):
        enriched = dict(item)
        enriched["date_label"] = format_date_label(item["start"], item["end"])
        experiences.append(enriched)

    selected_skills = build_selected_groups(profile, variant["skill_groups"])
    selected_tools = build_selected_groups(profile, variant.get("tool_groups", []))

    projects = []
    if variant.get("show_projects"):
        selected_projects = [enrich_project_item(item) for item in pick_by_ids(profile.get("projects", []), variant.get("project_ids", []))]
        projects = group_projects_for_display(selected_projects)

    publications = []
    if variant.get("show_publications"):
        if variant.get("show_all_publications"):
            publications = profile.get("publications", [])
        else:
            publications = pick_by_ids(profile.get("publications", []), variant.get("publication_ids", []))

    patents = []
    if variant.get("show_patents"):
        if variant.get("show_all_patents"):
            patents = profile.get("patents", [])
        else:
            patents = pick_by_ids(profile.get("patents", []), variant.get("patent_ids", []))

    return {
        "basics": profile["basics"],
        "summary": profile["summaries"][variant["summary_key"]],
        "education": pick_education(profile, variant),
        "awards_and_memberships": profile.get("awards_and_memberships", []),
        "experience": experiences,
        "selected_skills": selected_skills,
        "selected_skills_sidebar": {
            group_name: build_sidebar_group(group_name, group)
            for group_name, group in selected_skills.items()
        },
        "selected_tools": selected_tools,
        "selected_tools_sidebar": {
            group_name: build_sidebar_group(group_name, group)
            for group_name, group in selected_tools.items()
        },
        "projects": projects,
        "publications": publications,
        "patents": patents,
        "generated_date": datetime.now().strftime("%B %d, %Y").replace(" 0", " "),
        "variant": variant,
    }


def enrich_project_item(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    enriched["period"] = format_period_text(item["period"])
    summary = item.get("summary") or item.get("description", "")
    highlights = item.get("highlights", [])
    enriched["summary"] = summary
    enriched["highlights"] = highlights
    enriched["project_type"] = item.get("project_type", "")
    enriched["parent_project_id"] = item.get("parent_project_id")
    enriched["status"] = item.get("status", "")
    enriched["project_links"] = item.get("project_links", [])
    enriched["project_links_html"] = render_project_links(item.get("project_links", []), "html")
    enriched["project_links_markdown"] = render_project_links(item.get("project_links", []), "markdown")
    enriched["related_experience_ids"] = item.get("related_experience_ids", [])
    enriched["related_skill_groups"] = item.get("related_skill_groups", [])
    enriched["tags"] = item.get("tags", [])
    enriched["children"] = []
    enriched["badges"] = derive_project_badges(item)
    enriched["badges_html"] = render_project_badges(enriched["badges"], "html")
    enriched["badges_markdown"] = render_project_badges(enriched["badges"], "markdown")
    return enriched


def render_project_links(links: list[dict[str, str]], mode: str) -> str:
    public_links = [link for link in links if link.get("kind") != "local"]
    if not public_links:
        return ""

    rendered: list[str] = []
    for link in public_links:
        target = link.get("target", "")
        if not target:
            continue
        if mode == "html":
            rendered.append(f'<a href="{html.escape(target)}">{html.escape(target)}</a>')
        else:
            rendered.append(target)

    return " · ".join(rendered)


def derive_project_badges(item: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    status = str(item.get("status", "")).lower().strip()

    if status == "work_in_progress":
        badges.append("Work in Progress")
    elif status == "active":
        badges.append("Active")
    elif status == "past":
        badges.append("Past")

    return badges


def render_project_badges(badges: list[str], mode: str) -> str:
    if not badges:
        return ""
    if mode == "html":
        return " ".join(f'<span class="badge">{html.escape(badge)}</span>' for badge in badges)
    return " ".join(f"[{badge}]" for badge in badges)


def group_projects_for_display(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {project["id"]: dict(project) for project in projects}
    ordered_ids = [project["id"] for project in projects]

    for project in by_id.values():
        project["children"] = []

    top_level: list[dict[str, Any]] = []
    for project_id in ordered_ids:
        project = by_id[project_id]
        parent_id = project.get("parent_project_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(project)
            continue
        top_level.append(project)

    return top_level


def render_template(template_name: str, context: dict[str, Any], autoescape: bool) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]) if autoescape else False,
    )
    template = environment.get_template(template_name)
    return template.render(**context)


def write_outputs(
    variant_name: str,
    output_name: str,
    html: str,
    markdown: str,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    OUTPUT_MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PDF_DIR.mkdir(parents=True, exist_ok=True)
    TMP_HTML_DIR.mkdir(parents=True, exist_ok=True)
    html_path = TMP_HTML_DIR / f"{variant_name}.html"
    markdown_path = OUTPUT_MARKDOWN_DIR / f"{variant_name}.md"
    html_path.write_text(html, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    pdf_path = OUTPUT_PDF_DIR / f"{output_name}.pdf"
    return html_path, markdown_path, pdf_path


def render_pdf_with_playwright(html_path: pathlib.Path, pdf_path: pathlib.Path) -> None:
    command = [
        "node",
        str(PLAYWRIGHT_RENDERER),
        str(html_path.resolve()),
        str(pdf_path.resolve()),
    ]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Playwright PDF render failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def join_skill_entries(entries: list[dict[str, str]], key: str) -> str:
    return ", ".join(entry[key] for entry in entries)


def build_pdf_styles() -> StyleSheet1:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ResumeName",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=26,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResumeHeadline",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#5b6472"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubsectionTitle",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=colors.HexColor("#1f2937"),
            spaceBefore=4,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResumeBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResumeMeta",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.5,
            textColor=colors.HexColor("#5b6472"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ResumeMetaRight",
            parent=styles["ResumeMeta"],
            alignment=TA_RIGHT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletBody",
            parent=styles["ResumeBody"],
            leftIndent=12,
            firstLineIndent=0,
            spaceAfter=0,
        )
    )
    return styles


def render_pdf_with_reportlab(pdf_path: pathlib.Path, context: dict[str, Any]) -> None:
    styles = build_pdf_styles()
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
        title=context["variant"]["title"],
        author=context["basics"]["preferred_name"],
    )

    story = [
        Paragraph(context["basics"]["preferred_name"], styles["ResumeName"]),
        Paragraph(context["basics"]["headline"], styles["ResumeHeadline"]),
        Paragraph(
            " | ".join(
                [
                    html.escape(context["basics"]["email"]),
                    html.escape(context["basics"]["location"]),
                    html.escape(context["basics"]["github"]),
                    html.escape(context["basics"]["linkedin"]),
                    html.escape(context["basics"]["consulting"]),
                    html.escape(context["basics"]["legal_status"]),
                ]
            ),
            styles["ResumeMeta"],
        ),
        Spacer(1, 4),
        Paragraph("Summary", styles["SectionTitle"]),
        Paragraph(html.escape(context["summary"]), styles["ResumeBody"]),
    ]

    story.extend(build_pdf_skill_sections("Skills", context["selected_skills"], styles))
    story.extend(build_pdf_skill_sections("Frameworks and Tools", context["selected_tools"], styles))

    if context["projects"]:
        story.append(Paragraph("Projects", styles["SectionTitle"]))
        for project in context["projects"]:
            story.append(Paragraph(html.escape(project["name"]), styles["SubsectionTitle"]))
            story.append(Paragraph(html.escape(project["period"]), styles["ResumeMeta"]))
            if project.get("project_type"):
                story.append(Paragraph(html.escape(project["project_type"]), styles["ResumeMeta"]))
            story.append(Paragraph(html.escape(project["summary"]), styles["ResumeBody"]))
            for bullet in project.get("highlights", []):
                story.append(Paragraph(f"• {html.escape(bullet)}", styles["ResumeBody"]))
            for child in project.get("children", []):
                child_line = f"{child['name']}: {child['summary']}"
                story.append(Paragraph(f"• {html.escape(child_line)}", styles["ResumeBody"]))
            story.append(Spacer(1, 4))

    story.append(Paragraph("Experience", styles["SectionTitle"]))
    for item in context["experience"]:
        story.append(Paragraph(f'{html.escape(item["role"])} | {html.escape(item["company"])}', styles["SubsectionTitle"]))
        story.append(Paragraph(html.escape(item["date_label"]), styles["ResumeMeta"]))
        bullets = [
            ListItem(Paragraph(html.escape(bullet), styles["BulletBody"]))
            for bullet in item["bullets"]
        ]
        story.append(
            ListFlowable(
                bullets,
                bulletType="bullet",
                start="circle",
                leftIndent=8,
            )
        )
        story.append(Spacer(1, 4))

    story.append(Paragraph("Education", styles["SectionTitle"]))
    for item in context["education"]:
        story.append(Paragraph(html.escape(item["degree"]), styles["SubsectionTitle"]))
        story.append(
            Paragraph(
                f'{html.escape(item["school"])} | {html.escape(item["period"])}',
                styles["ResumeMeta"],
            )
        )
        for detail in item["details"]:
            story.append(Paragraph(f"• {html.escape(detail)}", styles["ResumeBody"]))

    if context["publications"]:
        story.append(Paragraph("Publications", styles["SectionTitle"]))
        for item in context["publications"]:
            story.append(Paragraph(f"• {html.escape(item['citation'])}", styles["ResumeBody"]))

    if context["patents"]:
        story.append(Paragraph("Patents", styles["SectionTitle"]))
        for item in context["patents"]:
            story.append(Paragraph(f"• {html.escape(item['citation'])}", styles["ResumeBody"]))

    if context["awards_and_memberships"]:
        story.append(Paragraph("Memberships", styles["SectionTitle"]))
        for item in context["awards_and_memberships"]:
            story.append(Paragraph(f"• {html.escape(item)}", styles["ResumeBody"]))

    story.append(Spacer(1, 6))
    story.append(Paragraph("References available upon request.", styles["ResumeMeta"]))
    doc.build(story)


def render_pdf(html_path: pathlib.Path, pdf_path: pathlib.Path, context: dict[str, Any], variant_name: str) -> None:
    try:
        render_pdf_with_playwright(html_path, pdf_path)
    except Exception as exc:
        print(
            "Warning: styled HTML PDF render failed; falling back to plain ReportLab output.\n"
            f"{exc}",
            file=sys.stderr,
        )
        render_pdf_with_reportlab(pdf_path, context)


def build_pdf_skill_sections(
    title: str,
    selected_groups: dict[str, dict[str, Any]],
    styles: StyleSheet1,
) -> list[Any]:
    if not selected_groups:
        return []

    flowables: list[Any] = [Paragraph(title, styles["SectionTitle"])]
    for group_name, entries in selected_groups.items():
        show_group_name = group_name != "Selected Frameworks and Tools"
        if show_group_name:
            flowables.append(Paragraph(html.escape(group_name), styles["SubsectionTitle"]))

        if entries["type"] == "sectioned":
            for section in entries["sections"]:
                flowables.append(Paragraph(html.escape(section["name"]), styles["SubsectionTitle"]))
                if section["type"] == "nested":
                    for subsection in section["subsections"]:
                        flowables.append(Paragraph(html.escape(subsection["name"]), styles["ResumeMeta"]))
                        flowables.append(Paragraph(join_skill_entries(subsection["entries"], "pdf"), styles["ResumeBody"]))
                else:
                    flowables.append(Paragraph(join_skill_entries(section["entries"], "pdf"), styles["ResumeBody"]))
        else:
            flowables.append(Paragraph(join_skill_entries(entries["entries"], "pdf"), styles["ResumeBody"]))
    return flowables


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a tailored resume variant to Markdown and PDF.")
    parser.add_argument("variant", help="Variant name from the variants directory, without .yaml")
    parser.add_argument("--markdown-only", action="store_true", help="Render Markdown only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    variant_path = VARIANTS_DIR / f"{args.variant}.yaml"
    if not variant_path.exists():
        print(f"Variant not found: {variant_path}", file=sys.stderr)
        return 1

    profile = load_yaml(DATA_PATH)
    variant = load_yaml(variant_path)
    context = build_context(profile, variant)
    html_template = variant.get("html_template", "resume.html.j2")
    markdown_template = variant.get("markdown_template", "resume.md.j2")
    html = render_template(html_template, context, autoescape=True)
    markdown = render_template(markdown_template, context, autoescape=False)
    html_path, markdown_path, pdf_path = write_outputs(args.variant, variant["output_name"], html, markdown)

    if not args.markdown_only:
        render_pdf(html_path, pdf_path, context, args.variant)

    print(f"Rendered Markdown: {markdown_path}")
    if not args.markdown_only:
        print(f"Rendered PDF: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
export_docx.py — 把简历 JSON 导出为 ATS 友好的 .docx。

用法:
    python export_docx.py <resume.json> <output.docx>

ATS 友好规范 (本脚本严格遵守):
    - 单栏布局，不用表格、不用文本框、不用图标
    - 联系方式放正文最顶部，不放在 Word 页眉/页脚
    - 标准章节标题（"工作经历" / "Work Experience"）
    - 标准字体: Calibri (英) / PingFang SC (中)
    - 11pt 正文，14pt 章节标题
    - 黑色 + 一种点缀色（深蓝 #1F3864）
    - 日期统一格式 YYYY.MM
    - 只用一种 bullet 符号: •

依赖:
    pip install python-docx
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List


def export(resume: Dict[str, Any], output_path: Path) -> None:
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        sys.exit("需要安装 python-docx: pip install python-docx")

    doc = Document()

    # 全局样式
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    # 中文字体
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

    # 页边距
    for section in doc.sections:
        section.top_margin = Cm(1.5)
        section.bottom_margin = Cm(1.5)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    ACCENT = RGBColor(0x1F, 0x38, 0x64)  # 深蓝点缀色

    def add_heading(text: str):
        """章节标题：14pt 加粗，深蓝色，下方画一条横线。"""
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(10)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(text)
        run.font.size = Pt(14)
        run.font.bold = True
        run.font.color.rgb = ACCENT
        run.font.name = "Calibri"
        run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

        # 下边框
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "1F3864")
        pBdr.append(bottom)
        pPr.append(pBdr)

    def add_bullet(text: str):
        """• bullet 段落，固定使用•符号，避免列表样式被 ATS 识别为表格。"""
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.first_line_indent = Cm(-0.5)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.25
        run = p.add_run("• " + text)
        run.font.size = Pt(11)
        run.font.name = "Calibri"
        run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

    def add_exp_header(left: str, right: str):
        """两端对齐的经历标题：左边公司+职位，右边时间。"""
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(2)
        # 用制表符让两端对齐
        from docx.shared import Inches
        from docx.enum.text import WD_TAB_ALIGNMENT
        tab_stops = p.paragraph_format.tab_stops
        tab_stops.add_tab_stop(Inches(6.5), WD_TAB_ALIGNMENT.RIGHT)

        left_run = p.add_run(left)
        left_run.font.bold = True
        left_run.font.size = Pt(11)
        left_run.font.name = "Calibri"
        left_run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

        p.add_run("\t")

        right_run = p.add_run(right)
        right_run.font.size = Pt(11)
        right_run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        right_run.font.name = "Calibri"

    # ========== 1. 顶部基础信息（不放页眉！） ==========
    bi = resume.get("basic_info", {})
    name = bi.get("name", "")
    target = bi.get("target_position", "")
    years = bi.get("years_experience")

    if name:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(name)
        run.font.size = Pt(22)
        run.font.bold = True
        run.font.color.rgb = ACCENT
        run.font.name = "Calibri"
        run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

    if target or years:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(4)
        line = target
        if years:
            line += f"  |  {years}+ 年经验"
        run = p.add_run(line)
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        run.font.name = "Calibri"
        run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

    # 联系方式
    contact_parts = []
    for key in ("phone", "email", "city", "linkedin", "github", "portfolio"):
        if bi.get(key):
            contact_parts.append(bi[key])
    if contact_parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(8)
        run = p.add_run("  ·  ".join(contact_parts))
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # ========== 2. Summary ==========
    summary = resume.get("summary")
    if summary:
        add_heading("个人定位 / Summary")
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(summary)
        run.font.size = Pt(11)
        run.font.name = "Calibri"
        run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

    # ========== 3. 工作经历 ==========
    experiences = resume.get("experience", [])
    if experiences:
        add_heading("工作经历 / Work Experience")
        for exp in experiences:
            company = exp.get("company", "")
            position = exp.get("position", "")
            start = exp.get("start_date", "")
            end = exp.get("end_date", "")
            location = exp.get("location", "")

            left = f"{company}  |  {position}"
            right = f"{start} - {end}"
            if location:
                right = f"{location}  |  {right}"
            add_exp_header(left, right)

            for b in exp.get("bullets", []):
                text = b.get("text", "") if isinstance(b, dict) else str(b)
                if text:
                    add_bullet(text)

    # ========== 4. 项目经历 ==========
    projects = resume.get("projects", [])
    if projects:
        add_heading("项目经历 / Projects")
        for proj in projects:
            name_p = proj.get("name") or proj.get("company", "")
            role = proj.get("role") or proj.get("position", "")
            start = proj.get("start_date", "")
            end = proj.get("end_date", "")
            tech = proj.get("tech_stack", [])
            left = name_p
            if role:
                left += f"  |  {role}"
            right = f"{start} - {end}" if start else ""
            add_exp_header(left, right)
            if tech:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.5)
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run("技术栈: " + ", ".join(tech))
                run.font.size = Pt(10)
                run.font.italic = True
                run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            for b in proj.get("bullets", []):
                text = b.get("text", "") if isinstance(b, dict) else str(b)
                if text:
                    add_bullet(text)

    # ========== 5. 教育背景 ==========
    educations = resume.get("education", [])
    if educations:
        add_heading("教育背景 / Education")
        for edu in educations:
            school = edu.get("school", "")
            degree = edu.get("degree", "")
            major = edu.get("major", "")
            start = edu.get("start_date", "")
            end = edu.get("end_date", "")
            gpa = edu.get("gpa", "")
            honors = edu.get("honors", []) or []

            left = school
            if degree or major:
                left += f"  |  {degree} {major}".rstrip()
            right = f"{start} - {end}" if start else ""
            add_exp_header(left, right)

            extras = []
            if gpa:
                extras.append(f"GPA: {gpa}")
            if honors:
                extras.extend(honors)
            if extras:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.5)
                p.paragraph_format.space_after = Pt(2)
                run = p.add_run("  ·  ".join(extras))
                run.font.size = Pt(10)

    # ========== 6. 技能 ==========
    skills = resume.get("skills", {}) or {}
    has_skills = any(skills.get(k) for k in ("hard_skills", "soft_skills",
                                              "languages", "certifications"))
    if has_skills:
        add_heading("技能 / Skills")

        def add_skill_line(label: str, items: List[str]):
            if not items:
                return
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.first_line_indent = Cm(-0.5)
            p.paragraph_format.space_after = Pt(2)

            label_run = p.add_run(f"• {label}: ")
            label_run.font.bold = True
            label_run.font.size = Pt(11)
            label_run.font.name = "Calibri"
            label_run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

            content_run = p.add_run(", ".join(items))
            content_run.font.size = Pt(11)
            content_run.font.name = "Calibri"
            content_run.element.rPr.rFonts.set(qn("w:eastAsia"), "PingFang SC")

        add_skill_line("硬技能 / Hard Skills", skills.get("hard_skills", []) or [])
        add_skill_line("软技能 / Soft Skills", skills.get("soft_skills", []) or [])
        add_skill_line("语言 / Languages", skills.get("languages", []) or [])
        add_skill_line("证书 / Certifications", skills.get("certifications", []) or [])

    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))


def export_pdf(resume: Dict[str, Any], output_path: Path) -> None:
    """纯 Python PDF 导出（基于 fpdf2），无需 MS Word 或 LibreOffice。"""
    try:
        from fpdf import FPDF
    except ImportError:
        sys.exit("需要安装 fpdf2: pip install fpdf2")

    ACCENT_HEX = (31, 56, 100)
    GRAY = (85, 85, 85)
    BLACK = (0, 0, 0)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 15, 18)

    # 尝试加载中文字体
    font_loaded = False
    for font_path in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]:
        if Path(font_path).exists():
            try:
                pdf.add_font("CJK", "", font_path, uni=True)
                pdf.add_font("CJK", "B", font_path, uni=True)
                font_loaded = True
                break
            except Exception:
                continue

    fn = "CJK" if font_loaded else "Helvetica"
    fnb = "CJK" if font_loaded else "Helvetica"

    def set_font(size, bold=False, color=BLACK):
        pdf.set_font(fnb if bold else fn, "B" if bold and not font_loaded else "", size)
        pdf.set_text_color(*color)

    def add_section_heading(title):
        pdf.ln(4)
        set_font(13, bold=True, color=ACCENT_HEX)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*ACCENT_HEX)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(2)

    def add_exp_header(left, right):
        set_font(10, bold=True)
        left_w = pdf.w - pdf.l_margin - pdf.r_margin - pdf.get_string_width(right) - 4
        pdf.cell(left_w, 6, left)
        set_font(10, color=GRAY)
        pdf.cell(0, 6, right, align="R", new_x="LMARGIN", new_y="NEXT")

    def add_bullet(text):
        set_font(10)
        pdf.set_x(pdf.l_margin + 5)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 5, 5,
                        f"\u2022  {text}", new_x="LMARGIN", new_y="NEXT")

    # === Header ===
    bi = resume.get("basic_info", {})
    name = bi.get("name", "")
    target = bi.get("target_position", "")

    if name:
        set_font(20, bold=True, color=ACCENT_HEX)
        pdf.cell(0, 10, name, align="C", new_x="LMARGIN", new_y="NEXT")

    if target:
        set_font(11, color=GRAY)
        pdf.cell(0, 6, target, align="C", new_x="LMARGIN", new_y="NEXT")

    contact_parts = [bi.get(k, "") for k in ("phone", "email", "city", "linkedin", "github") if bi.get(k)]
    if contact_parts:
        set_font(9, color=GRAY)
        pdf.cell(0, 6, "  |  ".join(contact_parts), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # === Summary ===
    summary = resume.get("summary")
    if summary:
        add_section_heading("个人定位 / Summary")
        set_font(10)
        pdf.multi_cell(0, 5, summary, new_x="LMARGIN", new_y="NEXT")

    # === Experience ===
    experiences = resume.get("experience", [])
    if experiences:
        add_section_heading("工作经历 / Work Experience")
        for exp in experiences:
            company = exp.get("company", "")
            position = exp.get("position", "")
            left = f"{company}  |  {position}" if position else company
            right = f"{exp.get('start_date', '')} - {exp.get('end_date', '')}"
            add_exp_header(left, right)
            for b in exp.get("bullets", []):
                text = b.get("text", "") if isinstance(b, dict) else str(b)
                if text:
                    add_bullet(text)
            pdf.ln(1)

    # === Projects ===
    projects = resume.get("projects", [])
    if projects:
        add_section_heading("项目经历 / Projects")
        for proj in projects:
            name_p = proj.get("name") or proj.get("company", "")
            role = proj.get("role") or proj.get("position", "")
            left = f"{name_p}  |  {role}" if role else name_p
            right = f"{proj.get('start_date', '')} - {proj.get('end_date', '')}"
            add_exp_header(left, right)
            for b in proj.get("bullets", []):
                text = b.get("text", "") if isinstance(b, dict) else str(b)
                if text:
                    add_bullet(text)
            pdf.ln(1)

    # === Education ===
    educations = resume.get("education", [])
    if educations:
        add_section_heading("教育背景 / Education")
        for edu in educations:
            school = edu.get("school", "")
            degree = edu.get("degree", "")
            major = edu.get("major", "")
            left = school
            if degree or major:
                left += f"  |  {degree} {major}".rstrip()
            right = f"{edu.get('start_date', '')} - {edu.get('end_date', '')}"
            add_exp_header(left, right)
            gpa = edu.get("gpa", "")
            if gpa:
                set_font(9, color=GRAY)
                pdf.cell(0, 5, f"GPA: {gpa}", new_x="LMARGIN", new_y="NEXT")

    # === Skills ===
    skills = resume.get("skills", {}) or {}
    has_skills = any(skills.get(k) for k in ("hard_skills", "soft_skills", "languages", "certifications"))
    if has_skills:
        add_section_heading("技能 / Skills")
        for label, key in [("硬技能", "hard_skills"), ("软技能", "soft_skills"),
                           ("语言", "languages"), ("证书", "certifications")]:
            items = skills.get(key, []) or []
            if items:
                set_font(10, bold=True)
                pdf.cell(pdf.get_string_width(f"\u2022  {label}: ") + 2, 5, f"\u2022  {label}: ")
                set_font(10)
                pdf.multi_cell(0, 5, ", ".join(items), new_x="LMARGIN", new_y="NEXT")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", type=Path)
    parser.add_argument("output", type=Path, help="输出文件 (.docx 或 .pdf)")
    args = parser.parse_args()

    resume = json.loads(args.resume.read_text(encoding="utf-8"))
    if args.output.suffix.lower() == ".pdf":
        export_pdf(resume, args.output)
    else:
        export(resume, args.output)
    print(f"已导出: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()

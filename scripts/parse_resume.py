#!/usr/bin/env python3
"""
parse_resume.py — 把 .docx / .pdf 简历解析成标准 schema 的 JSON。

用法:
    python parse_resume.py <input_file> [--lang zh|en|auto] > resume.json

输出: 符合 templates/resume_schema.json 的 JSON。

依赖:
    pip install python-docx PyMuPDF

注意:
    1. 启发式解析，章节识别可能出错。Claude 必须把解析结果展示给用户确认。
    2. 章节误判的话，让用户手动改 JSON 再继续往下传。
    3. 中英文混合简历能处理，但优先支持纯中文/纯英文。
"""

import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any


# 章节关键词词典（中英都识别）
SECTION_KEYWORDS = {
    "experience": [
        r"工作经历", r"工作经验", r"职业经历", r"实习经历", r"实习经验",
        r"work\s*experience", r"professional\s*experience", r"employment",
        r"experience$", r"career\s*history",
    ],
    "education": [
        r"教育背景", r"教育经历", r"学历",
        r"education", r"academic\s*background",
    ],
    "skills": [
        r"技能", r"专业技能", r"技术栈", r"能力",
        r"skills", r"technical\s*skills", r"core\s*competencies",
    ],
    "projects": [
        r"项目经历", r"项目经验",
        r"projects?", r"project\s*experience",
    ],
    "summary": [
        r"个人简介", r"个人总结", r"自我评价", r"职业目标",
        r"summary", r"profile", r"objective", r"about\s*me",
    ],
    "certifications": [
        r"证书", r"资格证书", r"专业认证",
        r"certifications?", r"licenses?",
    ],
}

# 职位关键词（用于拆分公司名和职位）
POSITION_KEYWORDS = re.compile(
    r"(?:高级|资深|初级|中级|首席|实习)?"
    r"(?:工程师|架构师|开发|经理|总监|负责人|合伙人|设计师|产品经理|分析师|"
    r"运营|顾问|专员|主管|总裁|VP|CTO|CEO|COO|CFO|"
    r"Engineer|Architect|Developer|Manager|Director|Lead|Analyst)",
    re.IGNORECASE,
)

# bullet 起始标记
BULLET_MARKER = re.compile(r"^[●•·\-▪◆■\*]")

DATE_PATTERN = re.compile(
    r"(\d{4})[./\-年]\s*(\d{1,2})[月]?\s*[-–~至到]\s*"
    r"(?:(\d{4})[./\-年]\s*(\d{1,2})[月]?|至今|present|now|current)",
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(r"[\w._-]+@[\w.-]+\.\w+")
PHONE_PATTERN = re.compile(r"(?:\+?86[-\s]?)?1[3-9]\d{9}|\d{3}[-\s]?\d{3,4}[-\s]?\d{4}")
URL_PATTERN = re.compile(r"https?://[^\s,，;]+|(?:linkedin|github)\.com/[\w/-]+", re.IGNORECASE)

# 学位关键词
DEGREE_KEYWORDS = re.compile(
    r"本科|学士|硕士|研究生|博士|大专|专科|MBA|EMBA|"
    r"Bachelor|Master|PhD|Doctor|Associate",
    re.IGNORECASE,
)


def detect_lang(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[a-zA-Z]{2,}", text))
    if chinese_chars > english_words * 2:
        return "zh"
    if english_words > chinese_chars * 3:
        return "en"
    return "mixed"


def extract_text_from_docx(path: Path) -> List[str]:
    """从 .docx 提取段落文本，保留顺序。"""
    try:
        from docx import Document
    except ImportError:
        sys.exit("需要安装 python-docx: pip install python-docx")
    doc = Document(str(path))
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append(text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.strip()
                if text:
                    paragraphs.append(text)
    return paragraphs


def extract_text_from_pdf(path: Path) -> List[str]:
    """从 .pdf 提取行级文本（使用 PyMuPDF，sort=True 保证视觉阅读顺序）。"""
    try:
        import fitz
    except ImportError:
        sys.exit("需要安装 PyMuPDF: pip install PyMuPDF")
    lines = []
    doc = fitz.open(str(path))
    for page in doc:
        text = page.get_text(sort=True)
        for line in text.split("\n"):
            # 去掉前后空白，把多个连续空格压缩（但保留 2+ 空格作为分隔符的能力）
            line = line.strip()
            if line:
                lines.append(line)
    doc.close()
    return lines


def extract_basic_info(lines: List[str]) -> Dict[str, Any]:
    """提取姓名、联系方式等基础信息（一般在前 10 行）。"""
    info: Dict[str, Any] = {"name": ""}
    head = " \n ".join(lines[:15])

    m = EMAIL_PATTERN.search(head)
    if m:
        info["email"] = m.group(0)
    m = PHONE_PATTERN.search(head)
    if m:
        info["phone"] = m.group(0)
    urls = URL_PATTERN.findall(head)
    for u in urls:
        if "linkedin" in u.lower():
            info["linkedin"] = u
        elif "github" in u.lower():
            info["github"] = u
        else:
            info["portfolio"] = u

    for line in lines[:5]:
        cleaned = re.sub(r"\s+", "", line)
        if (
            len(cleaned) <= 20
            and not EMAIL_PATTERN.search(line)
            and not PHONE_PATTERN.search(line)
            and not URL_PATTERN.search(line)
            and not any(re.search(kw, cleaned, re.IGNORECASE)
                        for kws in SECTION_KEYWORDS.values() for kw in kws)
        ):
            info["name"] = cleaned
            break

    return info


def is_section_header(line: str) -> str:
    """判断是不是章节标题；返回章节 key 或 ''。"""
    line_clean = re.sub(r"[【】\[\]:：·\-\s]", "", line).lower()
    if not line_clean or len(line_clean) > 30:
        return ""
    for section, patterns in SECTION_KEYWORDS.items():
        for p in patterns:
            if re.fullmatch(p, line_clean, re.IGNORECASE):
                return section
            if re.search(p, line, re.IGNORECASE) and len(line) < 20:
                return section
    return ""


def split_by_section(lines: List[str]) -> Dict[str, List[str]]:
    """按章节切分。"""
    sections: Dict[str, List[str]] = {"_header": []}
    current = "_header"
    for line in lines:
        sec = is_section_header(line)
        if sec:
            current = sec
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return sections


def _is_position_line(line: str) -> bool:
    """判断是否是独立的职位/角色描述行（如 "Golang工程师"、"（Golang）"）。"""
    stripped = line.strip()
    # 括号包裹的技术栈标注，如 "（Golang）"
    if re.fullmatch(r"[（(].+[)）]", stripped):
        return True
    # 短行 + 含职位关键词
    if len(stripped) <= 20 and POSITION_KEYWORDS.search(stripped):
        return True
    return False


def _split_company_position(text: str) -> tuple:
    """从一行文本中拆分公司名和职位。
    优先用多空格分隔，其次用 | · - — 分隔，最后用职位关键词匹配。
    """
    # 尝试按多空格分隔（PyMuPDF 常见模式）
    parts = re.split(r"\s{2,}", text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        # 修复 PyMuPDF 偶尔在中文字符间插入的单空格（如"月 之暗面"→"月之暗面"）
        company = re.sub(r"(?<=[\u4e00-\u9fff])\s(?=[\u4e00-\u9fff])", "", parts[0])
        return company, " ".join(parts[1:])

    # 尝试按 | · - — 分隔
    parts = re.split(r"[|·—]+", text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1]

    # 尝试用职位关键词拆分
    m = POSITION_KEYWORDS.search(text)
    if m and m.start() > 2:
        company = text[:m.start()].strip()
        position = text[m.start():].strip()
        return company, position

    return text, ""


def parse_experience_block(block: List[str]) -> List[Dict[str, Any]]:
    """把工作经历章节切成多段经历。"""
    experiences: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}

    for line in block:
        date_match = DATE_PATTERN.search(line)
        if date_match:
            if current:
                experiences.append(current)
            current = {
                "company": "",
                "position": "",
                "start_date": f"{date_match.group(1)}.{int(date_match.group(2)):02d}",
                "end_date": (
                    f"{date_match.group(3)}.{int(date_match.group(4)):02d}"
                    if date_match.group(3) else "Present"
                ),
                "bullets": [],
            }
            non_date = DATE_PATTERN.sub("", line).strip(" |·\\-—")
            company, position = _split_company_position(non_date)
            # 修复 PyMuPDF 偶尔在中文字符间插入的单空格
            current["company"] = re.sub(r"(?<=[\u4e00-\u9fff])\s(?=[\u4e00-\u9fff])", "", company)
            current["position"] = position
        elif BULLET_MARKER.match(line):
            # bullet 行（优先于 position 检测，避免 "● xxx" 被误判为职位）
            if not current:
                current = {"company": "", "position": "", "start_date": "",
                           "end_date": "", "bullets": []}
            line_stripped = re.sub(r"^[●•·\-▪◆■\*\d.\s]+", "", line).strip()
            if line_stripped:
                current["bullets"].append({
                    "text": line_stripped,
                    "metrics": extract_metrics(line_stripped),
                    "keywords": [],
                    "xyz_grade": "",
                })
        elif _is_position_line(line) and current:
            # 独立的职位行，合并到当前经历的 position
            existing = current.get("position", "")
            addon = line.strip()
            if existing:
                current["position"] = f"{existing} {addon}"
            else:
                current["position"] = addon
        else:
            if not current:
                current = {"company": "", "position": "", "start_date": "",
                           "end_date": "", "bullets": []}

            line_stripped = line.strip()
            if not line_stripped:
                continue

            if current["bullets"]:
                # 续行：追加到上一个 bullet
                prev = current["bullets"][-1]
                prev["text"] = prev["text"].rstrip() + line_stripped
                prev["metrics"] = extract_metrics(prev["text"])
            else:
                # 没有前置 bullet，作为新 bullet
                current["bullets"].append({
                    "text": line_stripped,
                    "metrics": extract_metrics(line_stripped),
                    "keywords": [],
                    "xyz_grade": "",
                })

    if current:
        experiences.append(current)
    return experiences


def extract_metrics(text: str) -> List[str]:
    """从 bullet 文本里抽数字指标。"""
    patterns = [
        r"\d+%",
        r"\d+[.,]?\d*\s*[万千KMB]\+?",
        r"\d+[.,]?\d*\s*[人个条次篇天周月年]\+?",
        r"\$\d+[.,]?\d*[KMB]?",
        r"¥\d+[.,]?\d*[万千KMB]?",
        r"\d+x",
        r"\d+qps",
        r"\d+ms",
    ]
    metrics = []
    for p in patterns:
        metrics.extend(re.findall(p, text, re.IGNORECASE))
    return metrics


def parse_education_block(block: List[str]) -> List[Dict[str, Any]]:
    """解析教育背景。"""
    educations = []
    current: Dict[str, Any] = {}
    for line in block:
        date_match = DATE_PATTERN.search(line)
        if date_match:
            if current:
                educations.append(current)
            current = {
                "school": "",
                "degree": "",
                "major": "",
                "start_date": f"{date_match.group(1)}.{int(date_match.group(2)):02d}",
                "end_date": (
                    f"{date_match.group(3)}.{int(date_match.group(4)):02d}"
                    if date_match.group(3) else "Present"
                ),
            }
            non_date = DATE_PATTERN.sub("", line).strip(" |·\\-—")
            # 用多空格 or 分隔符切分
            parts = re.split(r"\s{2,}|[|·—]+", non_date)
            parts = [p.strip() for p in parts if p.strip()]

            # 智能分配 school / degree / major
            school_parts = []
            for p in parts:
                if DEGREE_KEYWORDS.search(p):
                    current["degree"] = p
                elif current["degree"] and not current["major"]:
                    current["major"] = p
                else:
                    school_parts.append(p)

            if school_parts:
                current["school"] = school_parts[0]
                # 如果有剩余 parts 且 major 为空，第二个可能是 major
                if len(school_parts) > 1 and not current["major"]:
                    current["major"] = school_parts[1]

            # 如果上面没识别到 degree，尝试在整行里搜索
            if not current["degree"]:
                dm = DEGREE_KEYWORDS.search(non_date)
                if dm:
                    current["degree"] = dm.group(0)
        else:
            if not current:
                current = {"school": "", "degree": "", "major": "",
                           "start_date": "", "end_date": ""}
            gpa_match = re.search(r"GPA[：:\s]*([\d.]+\s*/\s*[\d.]+|[\d.]+)", line, re.IGNORECASE)
            if gpa_match:
                current["gpa"] = gpa_match.group(1)
    if current:
        educations.append(current)
    return educations


def parse_skills_block(block: List[str]) -> Dict[str, List[str]]:
    """解析技能区。"""
    skills: Dict[str, List[str]] = {
        "hard_skills": [],
        "soft_skills": [],
        "languages": [],
        "certifications": [],
    }
    for line in block:
        items = re.split(r"[,，、/|；;]+", line)
        items = [i.strip(" ●•·") for i in items if i.strip()]
        for item in items:
            if re.search(r"语|english|chinese|japanese|cet|toefl|ielts", item, re.IGNORECASE):
                skills["languages"].append(item)
            elif re.search(r"证|certified|license|pmp|cfa|aws|cpa", item, re.IGNORECASE):
                skills["certifications"].append(item)
            else:
                skills["hard_skills"].append(item)
    return skills


def estimate_years(resume: Dict) -> float:
    """从工作经历粗略估计年限（共享工具函数）。"""
    total_months = 0
    for exp in resume.get("experience", []):
        start = exp.get("start_date", "")
        end = exp.get("end_date", "")
        sm = re.match(r"(\d{4})\.(\d{1,2})", start)
        if not sm:
            continue
        sy, smo = int(sm.group(1)), int(sm.group(2))
        if end and end.lower() not in ("present", "至今", "now"):
            em = re.match(r"(\d{4})\.(\d{1,2})", end)
            if em:
                ey, emo = int(em.group(1)), int(em.group(2))
            else:
                continue
        else:
            from datetime import datetime
            now = datetime.now()
            ey, emo = now.year, now.month
        total_months += (ey - sy) * 12 + (emo - smo)
    return round(total_months / 12, 1)


def parse(input_path: Path, lang_hint: str = "auto") -> Dict[str, Any]:
    """主解析函数。"""
    suffix = input_path.suffix.lower()
    if suffix == ".docx":
        lines = extract_text_from_docx(input_path)
    elif suffix == ".pdf":
        lines = extract_text_from_pdf(input_path)
    else:
        sys.exit(f"不支持的文件类型: {suffix}（仅支持 .docx / .pdf）")

    if not lines:
        sys.exit("解析失败：文件没有可提取文本（可能是扫描件 PDF，需要 OCR）")

    full_text = "\n".join(lines)
    lang = lang_hint if lang_hint != "auto" else detect_lang(full_text)

    sections = split_by_section(lines)

    resume = {
        "basic_info": extract_basic_info(sections.get("_header", [])),
        "summary": "\n".join(sections.get("summary", [])).strip() or None,
        "experience": parse_experience_block(sections.get("experience", [])),
        "projects": parse_experience_block(sections.get("projects", [])),
        "education": parse_education_block(sections.get("education", [])),
        "skills": parse_skills_block(sections.get("skills", [])),
        "_meta": {
            "source_file": str(input_path),
            "lang": lang,
            "diagnose_score": None,
            "diagnose_issues": [],
            "tailored_for_jd": None,
        },
    }

    if not resume["summary"]:
        resume.pop("summary")

    return resume


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--lang", default="auto", choices=["auto", "zh", "en", "mixed"])
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"文件不存在: {args.input}")

    resume = parse(args.input, args.lang)
    print(json.dumps(resume, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

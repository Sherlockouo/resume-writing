#!/usr/bin/env python3
"""
extract_jd.py — 把岗位 JD 文本解析成结构化关键词表。

用法:
    python extract_jd.py <jd_file_or_text> > jd.json

输出 JSON 字段:
    job_title           目标岗位名（关键，简历必须包含）
    must_have_skills    JD 中出现 ≥2 次的硬技能（必命中）
    nice_to_have_skills JD 中出现 1 次的技能（加分项）
    soft_skills         软技能要求
    years_required      年限门槛（如 "5+"）
    education_required  学历门槛
    keywords_freq       全词频统计（用于二次分析）
    raw_text            原始 JD 文本（调试用）
"""

import sys
import json
import re
import argparse
from pathlib import Path
from collections import Counter
from typing import Dict, List, Any


# 常见硬技能词典（覆盖技术、运营、数据、设计、金融、产品、销售、人力等高频岗）
COMMON_HARD_SKILLS = {
    # 编程语言
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#",
    "Swift", "Kotlin", "PHP", "Ruby", "Scala", "R", "MATLAB",
    # 前端
    "React", "Vue", "Angular", "Next.js", "Nuxt", "HTML", "CSS", "Sass",
    "Tailwind", "Webpack", "Vite",
    # 后端 / 框架
    "Spring", "SpringBoot", "Django", "Flask", "FastAPI", "Express", "Node.js",
    "Gin", "Rails", "Laravel",
    # 数据库
    "MySQL", "PostgreSQL", "Oracle", "SQL Server", "MongoDB", "Redis",
    "Elasticsearch", "Cassandra", "ClickHouse", "Neo4j",
    # 云 / 运维
    "AWS", "Azure", "GCP", "Aliyun", "阿里云", "腾讯云", "Docker", "Kubernetes",
    "K8s", "Jenkins", "GitLab", "Terraform", "Ansible", "Linux",
    # 大数据
    "Hadoop", "Spark", "Flink", "Kafka", "Hive", "Airflow", "Presto",
    # 数据 / AI
    "TensorFlow", "PyTorch", "Scikit-learn", "Pandas", "NumPy", "LLM", "RAG",
    "Transformer", "BERT", "GPT", "机器学习", "深度学习", "NLP", "CV",
    # 设计
    "Figma", "Sketch", "Photoshop", "Illustrator", "Axure", "Sketch", "XD",
    "Premiere", "AfterEffects", "C4D", "Blender",
    # 数据分析 / BI
    "SQL", "Tableau", "PowerBI", "Excel", "VBA", "SPSS", "SAS", "Looker",
    # 营销 / 运营
    "SEO", "SEM", "GA", "Google Analytics", "投放", "信息流", "私域",
    # 项目管理
    "Jira", "Confluence", "Notion", "Trello", "Asana", "Scrum", "Agile",
    "敏捷", "PMP", "PRINCE2",
    # 金融 / 财会
    "CPA", "CFA", "FRM", "ACCA", "GAAP", "IFRS", "SOX",
}

# 软技能（出现就标记，不主导评分）
SOFT_SKILLS = {
    "沟通", "协作", "团队", "领导力", "执行力", "学习能力", "抗压", "推动力",
    "responsibility", "communication", "leadership", "teamwork", "problem-solving",
    "ownership", "collaboration", "adaptability",
}

# 停用词（不进关键词频）
STOPWORDS = {
    "的", "和", "及", "或", "在", "与", "等", "对", "为", "是", "有", "可", "以",
    "能", "会", "要", "需", "工作", "岗位", "职位", "公司", "我们", "你将", "你需要",
    "the", "and", "or", "to", "of", "in", "for", "with", "on", "at", "as", "by",
    "an", "a", "be", "is", "are", "this", "that", "you", "your", "we", "our",
    "will", "can", "should", "must", "have", "has",
}


def extract_job_title(text: str) -> str:
    """启发式抽取岗位名：通常在 JD 第一行或"岗位名称"后面。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    # 看前 8 行有没有"岗位名称:"或"职位:"或"招聘:"
    for line in lines[:8]:
        m = re.search(
            r"(?:岗位名称|岗位|职位名称|职位|招聘|Position|Job\s*Title|Role)[：:\s]+(.+)",
            line, re.IGNORECASE,
        )
        if m:
            title = m.group(1).strip()
            # 先去掉括号里的英文翻译，再 strip
            title = re.sub(r"\s*[（(][^()（）]*[)）]\s*", "", title)
            title = title.strip(" |·-—")
            return title[:50]
    # 否则取第一行（如果不太长）
    if lines and len(lines[0]) < 60:
        return lines[0]
    return ""


def extract_years(text: str) -> str:
    """抽年限要求，如 '3年以上' / '5+ years'。"""
    patterns = [
        r"(\d+)\s*年\s*以上",
        r"(\d+)\s*\+?\s*年",
        r"(\d+)\+?\s*years?\s*(?:of\s*)?experience",
        r"(\d+)\+\s*years?",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return f"{m.group(1)}+"
    return ""


def extract_education(text: str) -> str:
    """抽学历要求。"""
    if re.search(r"博士|PhD|Doctor", text, re.IGNORECASE):
        return "博士/PhD"
    if re.search(r"硕士|Master|研究生", text, re.IGNORECASE):
        return "硕士/Master+"
    if re.search(r"本科|学士|Bachelor|Undergraduate", text, re.IGNORECASE):
        return "本科/Bachelor+"
    if re.search(r"大专|专科|Associate", text, re.IGNORECASE):
        return "大专+"
    return ""


def split_required_vs_preferred(text: str) -> tuple:
    """把 JD 切成 (必备段, 加分段)。
    通过"加分项 / Nice to have / Preferred / Bonus / Plus"等关键词识别。
    """
    split_patterns = [
        r"加\s*分\s*项",
        r"加\s*分",
        r"优先",
        r"Nice\s*to\s*have",
        r"Preferred",
        r"Bonus",
        r"Plus(?:\s*es)?",
        r"Good\s*to\s*have",
    ]
    pattern = "|".join(split_patterns)
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return text[: m.start()], text[m.start():]
    return text, ""


def find_skills(text: str, skill_dict: set) -> Counter:
    """找词典命中（区分大小写时不敏感，但保留原始大小写）。"""
    counts: Counter = Counter()
    for skill in skill_dict:
        # 用 \b 边界匹配，避免 Java 误中 JavaScript
        if any(c.isalpha() and ord(c) < 128 for c in skill):
            pattern = r"\b" + re.escape(skill) + r"\b"
        else:
            # 中文不需要 \b
            pattern = re.escape(skill)
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            counts[skill] = len(matches)
    return counts


def extract_general_keywords(text: str, top_n: int = 30) -> List[tuple]:
    """通用关键词频率（用于补充词典外的术语）。"""
    # 抽 2–4 字中文词 + 英文单词
    tokens = []
    # 中文 2-4 字（粗暴用 jieba 更准但避免依赖）
    for m in re.finditer(r"[\u4e00-\u9fff]{2,4}", text):
        word = m.group(0)
        if word not in STOPWORDS and len(word) >= 2:
            tokens.append(word)
    # 英文词组（连续大写开头单词组合，常是技术名词）
    for m in re.finditer(r"\b[A-Z][a-zA-Z0-9.+-]{2,}(?:\s+[A-Z][a-zA-Z0-9.+-]{2,})?", text):
        word = m.group(0).strip()
        if word.lower() not in STOPWORDS:
            tokens.append(word)
    counts = Counter(tokens)
    return counts.most_common(top_n)


def parse_jd(text: str) -> Dict[str, Any]:
    """主解析。"""
    job_title = extract_job_title(text)
    years = extract_years(text)
    edu = extract_education(text)

    # 切分必备段和加分段
    required_text, preferred_text = split_required_vs_preferred(text)

    required_hits = find_skills(required_text, COMMON_HARD_SKILLS)
    preferred_hits = find_skills(preferred_text, COMMON_HARD_SKILLS) if preferred_text else Counter()

    # 必备技能：在必备段出现的；加分技能：仅在加分段出现的
    must_have = sorted(required_hits.keys())
    nice_to_have = sorted(s for s in preferred_hits if s not in required_hits)

    soft_skill_counts = find_skills(text, SOFT_SKILLS)
    hard_skill_counts = required_hits + preferred_hits  # 全部命中
    general_kw = extract_general_keywords(text)

    return {
        "job_title": job_title,
        "must_have_skills": must_have,
        "nice_to_have_skills": nice_to_have,
        "soft_skills": sorted(soft_skill_counts.keys()),
        "years_required": years,
        "education_required": edu,
        "keywords_freq": dict(hard_skill_counts.most_common()),
        "general_keywords_top30": [{"word": w, "freq": c} for w, c in general_kw],
        "raw_text_length": len(text),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="JD 文件路径，或 '-' 表示从 stdin 读")
    args = parser.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    else:
        path = Path(args.input)
        if path.exists():
            text = path.read_text(encoding="utf-8")
        else:
            # 当成直接传文本
            text = args.input

    if not text.strip():
        sys.exit("JD 内容为空")

    result = parse_jd(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

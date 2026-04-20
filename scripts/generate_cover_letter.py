#!/usr/bin/env python3
"""
generate_cover_letter.py — 根据简历 + JD 生成求职信草稿。

用法:
    python generate_cover_letter.py <resume.json> <jd.json> [--tone formal|warm|startup] [--lang zh|en]

输出: Markdown 草稿，让 Claude 后续个性化润色。

注意:
    - 这是模板填充，不是 AI 生成。Claude 应该把输出当成"骨架"，
      然后基于用户的真实意图补血肉，特别是第一段的"为什么对这家公司感兴趣"。
    - 模板里 [需 Claude 个性化] 的标记必须替换。
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict


TEMPLATES = {
    "zh": {
        "formal": """\
尊敬的{company}招聘负责人：

您好。我从{channel}得知贵公司{company}正在招聘 {job_title}，对此非常感兴趣。

[需 Claude 个性化：写 1-2 句你为什么对这家公司、这个具体岗位感兴趣。提到一个该公司的具体事实——比如最近发布的产品、技术博客观点、行业动作。证明你不是群发。]

我有 {years}+ 年{job_title}相关经验，{strongest_match}。具体到 JD 里提到的几项核心能力：

{evidence_block}

[需 Claude 个性化：选 1 段最相关的经历展开 1-2 句，说明为什么这段经历对这个岗位特别有用。]

随简历附上，希望有机会和您进一步沟通。{contact}

此致
敬礼

{name}
{date}
""",
        "warm": """\
您好，

看到{company}在招 {job_title}，第一反应是想聊聊——[需 Claude 个性化：1-2 句你和这家公司/这个岗位的真实连接，可以是用户、关注者、被某个产品/观点触动。]

我做了 {years}+ 年{job_title}，最近主要在做 [需 Claude 补 1 句]。{strongest_match}。

简单说几个我觉得和这个岗位最相关的：

{evidence_block}

如果觉得有可以聊的地方，期待进一步沟通。

{name}
{contact}
""",
        "startup": """\
Hi {company} 团队，

我对 {job_title} 这个岗位很感兴趣，{years} 年相关经验，简历附上。

直接说重点，几个和你们这个岗位最对得上的事：

{evidence_block}

[需 Claude 个性化：1 句话说你为什么相信这家公司在做的方向。]

随时可以聊。

{name}
{contact}
""",
    },
    "en": {
        "formal": """\
Dear Hiring Manager at {company},

I am writing to apply for the {job_title} position at {company}, which I learned about through {channel}.

[Claude personalize: 1-2 sentences on why this company, this role specifically. Reference one concrete fact about the company—a recent launch, a tech blog post, a public position. Prove this isn't a mass-send.]

With {years}+ years of experience in {job_title}-related roles, {strongest_match}. Mapped against the core requirements in your JD:

{evidence_block}

[Claude personalize: pick 1 experience and expand 1-2 sentences on why it's particularly transferable to this role.]

I have attached my resume and would welcome the opportunity to discuss further. {contact}

Best regards,
{name}
{date}
""",
        "warm": """\
Hi {company} team,

Saw the opening for {job_title} and wanted to reach out—[Claude personalize: 1-2 sentences on a real connection: as a user, a follower of someone on the team, etc.]

I've spent {years}+ years in {job_title} work, most recently focused on [Claude fill]. {strongest_match}.

A few things I think map well:

{evidence_block}

Happy to chat if there's a fit.

{name}
{contact}
""",
        "startup": """\
Hi {company},

Interested in the {job_title} role. {years} years of relevant experience, resume attached.

Cutting to the chase, the things I think map best to what you need:

{evidence_block}

[Claude personalize: 1 sentence on why you believe in what this company is building.]

Available to chat anytime.

{name}
{contact}
""",
    },
}


def build_evidence_block(resume: Dict, jd: Dict, lang: str) -> str:
    """从简历里挑 2-3 条最相关的 bullet 作为证据。"""
    must_have = jd.get("must_have_skills", [])
    nice_to_have = jd.get("nice_to_have_skills", [])
    target = set(s.lower() for s in must_have + nice_to_have)

    candidates = []
    for exp in resume.get("experience", []) + resume.get("projects", []):
        for b in exp.get("bullets", []):
            text = b.get("text", "") if isinstance(b, dict) else str(b)
            if len(text.strip()) < 15:
                continue  # 过滤 "(Golang)" 等短/垃圾文本
            grade = b.get("xyz_grade", "") if isinstance(b, dict) else ""
            kw_count = sum(1 for kw in target if kw in text.lower())
            score = kw_count * 10 + {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}.get(grade, 0)
            if score > 0:
                candidates.append((score, text, exp.get("company", "")))

    candidates.sort(reverse=True)
    top3 = candidates[:3]

    if not top3:
        return ("- [需 Claude 补：从简历里挑 2-3 条最相关的成就，"
                "用 XYZ 公式重新组织]" if lang == "zh"
                else "- [Claude fill: pick 2-3 most relevant achievements, restate with XYZ]")

    lines = []
    for _, text, company in top3:
        lines.append(f"- {text}（{company}）" if lang == "zh"
                     else f"- {text} ({company})")
    return "\n".join(lines)


def estimate_years(resume: Dict) -> int:
    bi = resume.get("basic_info", {})
    if bi.get("years_experience"):
        return int(bi["years_experience"])
    from parse_resume import estimate_years as _est
    return max(1, round(_est(resume)))


def generate(resume: Dict, jd: Dict, tone: str, lang: str) -> str:
    template = TEMPLATES[lang][tone]
    bi = resume.get("basic_info", {})

    company_name = "[需补充：公司名]"
    # 从 JD raw 里粗略抽取，这里留给 Claude 填
    job_title = jd.get("job_title", "[需补充岗位名]")

    must_have = jd.get("must_have_skills", [])
    resume_str_lower = str(resume).lower()
    matched = [s for s in must_have if s.lower() in resume_str_lower]

    if matched and lang == "zh":
        strongest_match = f"在 {'、'.join(matched[:3])} 等领域有完整项目落地经验"
    elif matched:
        strongest_match = f"with hands-on delivery experience in {', '.join(matched[:3])}"
    else:
        strongest_match = "[Claude 补：你最强的相关经验一句话]" if lang == "zh" \
            else "[Claude fill: your strongest relevant qualification in one sentence]"

    contact_parts = []
    for k in ("phone", "email"):
        if bi.get(k):
            contact_parts.append(bi[k])
    contact = (
        ("可通过 " if lang == "zh" else "Reach me at ")
        + (" / ".join(contact_parts) if contact_parts else "[contact]")
        + ("。" if lang == "zh" else ".")
    )

    from datetime import date
    return template.format(
        company=company_name,
        job_title=job_title,
        channel="[投递渠道，如 LinkedIn / 官网 / 内推]" if lang == "zh"
                else "[source, e.g. LinkedIn / careers page / referral]",
        years=estimate_years(resume),
        strongest_match=strongest_match,
        evidence_block=build_evidence_block(resume, jd, lang),
        contact=contact,
        name=bi.get("name", "[Name]"),
        date=date.today().isoformat(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", type=Path)
    parser.add_argument("jd", type=Path)
    parser.add_argument("--tone", default="formal", choices=["formal", "warm", "startup"])
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    args = parser.parse_args()

    resume = json.loads(args.resume.read_text(encoding="utf-8"))
    jd = json.loads(args.jd.read_text(encoding="utf-8"))

    print(generate(resume, jd, args.tone, args.lang))


if __name__ == "__main__":
    main()

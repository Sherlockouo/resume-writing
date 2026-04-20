#!/usr/bin/env python3
"""
tailor_resume.py — 按 JD 重排和适配简历。

用法:
    python tailor_resume.py <resume.json> <jd.json> > resume_tailored.json

做了什么 (机械式重排，不编数据):
    1. 把 target_position 改成 JD 的 job_title
    2. Skills 区按 JD 关键词重新排序，命中 JD 的放前面
    3. 把 JD 必备但简历 Skills 缺失的关键词加进 Skills（仅当 Experience 里实际出现过）
    4. 每段经历内，含目标关键词的 bullet 顶到第一条
    5. 工作经历段排序：含 JD 关键词多的段往前
    6. 标记需要 Claude/用户手动改写的 bullet（评分 D 或 F）
    7. 重写 Summary 为针对该岗位的版本

不做的事:
    - 编造数字
    - 编造未发生的经历
    - 把不熟悉的关键词硬塞进经历

所有改动都记录在 _meta.tailored_changes 里，方便用户审核。
"""

import sys
import json
import re
import argparse
import copy
from pathlib import Path
from typing import Dict, List, Any


def text_of(bullet) -> str:
    if isinstance(bullet, dict):
        return bullet.get("text", "")
    return str(bullet)


def keywords_in(text: str, keywords: List[str]) -> List[str]:
    hits = []
    for kw in keywords:
        if any(c.isalpha() and ord(c) < 128 for c in kw):
            p = r"\b" + re.escape(kw) + r"\b"
        else:
            p = re.escape(kw)
        if re.search(p, text, re.IGNORECASE):
            hits.append(kw)
    return hits


def grade_bullet(text: str) -> str:
    """给 bullet 打 XYZ 等级。"""
    has_number = bool(re.search(r"\d", text))
    has_action_verb = bool(re.search(
        r"^[（\(]*(?:主导|负责|完成|实现|搭建|设计|开发|优化|推动|组织|策划|管理|建立|"
        r"提升|降低|提出|推出|发布|上线|"
        r"Led|Built|Designed|Developed|Implemented|Managed|Improved|Reduced|"
        r"Increased|Launched|Created|Drove|Architected)",
        text, re.IGNORECASE,
    ))
    has_method = bool(re.search(r"通过|by\s+(?:doing|using|implementing|building)", text, re.IGNORECASE))

    if has_number and has_action_verb and has_method:
        return "A"
    if has_number and has_action_verb:
        return "B"
    if has_action_verb:
        return "C"
    if has_number:
        return "D"
    return "F"


def reorder_bullets_by_relevance(bullets: List, target_keywords: List[str]) -> List:
    """每段经历内，含目标关键词的 bullet 顶到前面，其次按 XYZ 等级。"""
    def score(b):
        text = text_of(b)
        kw_count = len(keywords_in(text, target_keywords))
        grade = grade_bullet(text)
        grade_score = {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}[grade]
        return (kw_count * 10 + grade_score)
    return sorted(bullets, key=score, reverse=True)


def reorder_experiences_by_relevance(experiences: List, target_keywords: List[str]) -> List:
    """工作经历段：保持时间倒序的同时，把含关键词更多的近期经历往前。
    策略：所有 'Present' / 至今 的经历放最前；其余按 (时间, 关键词命中数) 排序。
    """
    def keyword_density(exp):
        all_text = " ".join(text_of(b) for b in exp.get("bullets", []))
        return len(keywords_in(all_text, target_keywords))

    def sort_key(exp):
        end = exp.get("end_date", "")
        is_current = end.lower() in ("present", "至今", "now", "current")
        # 解析开始日期
        sm = re.match(r"(\d{4})\.?(\d{1,2})?", exp.get("start_date", ""))
        if sm:
            year = int(sm.group(1))
            month = int(sm.group(2)) if sm.group(2) else 1
        else:
            year, month = 0, 0
        return (
            0 if is_current else 1,    # 当前在职的优先
            -(year * 12 + month),      # 然后时间倒序
            -keyword_density(exp),     # 同时间内，关键词多的优先
        )

    return sorted(experiences, key=sort_key)


def update_skills_section(skills: Dict, jd_must_have: List[str], jd_nice: List[str],
                           resume_text: str) -> Dict:
    """重排 Skills，命中 JD 的放前面；仅在 Experience 里实际出现过的，才补到 Skills。"""
    skills = copy.deepcopy(skills) or {}
    hard = skills.get("hard_skills", []) or []
    hard_set = {s.lower() for s in hard}

    # 把 JD 命中且 Experience 里实际出现过的、但 Skills 缺的，补进去
    for kw in jd_must_have + jd_nice:
        if kw.lower() in hard_set:
            continue
        # 检查 Experience 里有没有
        if re.search(re.escape(kw), resume_text, re.IGNORECASE):
            hard.append(kw)
            hard_set.add(kw.lower())

    # 排序：先列 JD 必备命中的、再 JD 加分命中的、再其他
    must_set = {s.lower() for s in jd_must_have}
    nice_set = {s.lower() for s in jd_nice}

    def skill_priority(s):
        sl = s.lower()
        if sl in must_set:
            return 0
        if sl in nice_set:
            return 1
        return 2

    hard.sort(key=skill_priority)
    skills["hard_skills"] = hard
    return skills


def rewrite_summary(resume: Dict, jd: Dict) -> str:
    """生成针对该岗位的 Summary。"""
    bi = resume.get("basic_info", {})
    name = bi.get("name", "")
    years = bi.get("years_experience") or estimate_years(resume)
    job_title = jd.get("job_title", "")
    must_have = jd.get("must_have_skills", [])

    # 找简历里命中的最强技能
    resume_text = " ".join([
        " ".join(b.get("text", "") if isinstance(b, dict) else str(b)
                 for b in exp.get("bullets", []))
        for exp in resume.get("experience", []) + resume.get("projects", [])
    ])
    matched_skills = keywords_in(resume_text, must_have)[:3]

    if matched_skills:
        skill_str = "、".join(matched_skills)
        return (f"{int(years)}+ 年{job_title}经验，擅长 {skill_str}。"
                f"[此处由 Claude 补一句最强成就，需用户确认数据]")
    else:
        return (f"{int(years)}+ 年相关经验，正在转向 {job_title} 方向。"
                f"[此处由 Claude 根据用户实际情况补 1-2 句]")


def estimate_years(resume: Dict) -> float:
    from parse_resume import estimate_years as _est
    return _est(resume)


def annotate_bullets(experiences: List, target_keywords: List[str]) -> List:
    """给每条 bullet 打 XYZ 等级和命中关键词，便于 Claude 后续改写。"""
    for exp in experiences:
        new_bullets = []
        for b in exp.get("bullets", []):
            if isinstance(b, dict):
                text = b.get("text", "")
                b["xyz_grade"] = grade_bullet(text)
                b["keywords"] = keywords_in(text, target_keywords)
                new_bullets.append(b)
            else:
                new_bullets.append({
                    "text": str(b),
                    "xyz_grade": grade_bullet(str(b)),
                    "keywords": keywords_in(str(b), target_keywords),
                    "metrics": [],
                })
        exp["bullets"] = new_bullets
    return experiences


def tailor(resume: Dict, jd: Dict) -> Dict:
    tailored = copy.deepcopy(resume)
    changes = []

    must_have = jd.get("must_have_skills", [])
    nice_to_have = jd.get("nice_to_have_skills", [])
    target_keywords = must_have + nice_to_have
    job_title = jd.get("job_title", "")

    # 1. 设置 target_position
    bi = tailored.setdefault("basic_info", {})
    if job_title and bi.get("target_position") != job_title:
        old = bi.get("target_position", "(无)")
        bi["target_position"] = job_title
        changes.append(f"target_position: {old} → {job_title}")

    # 2. Summary 重写
    if jd.get("job_title"):
        tailored["summary"] = rewrite_summary(resume, jd)
        changes.append("Summary 已重写为针对该岗位的版本（含 [需补充] 标记）")

    # 3. 经历段排序
    tailored["experience"] = reorder_experiences_by_relevance(
        tailored.get("experience", []), target_keywords
    )
    changes.append("工作经历段已按相关度重排")

    # 4. 每段 bullet 重排 + 标注
    for exp in tailored["experience"]:
        before = [text_of(b) for b in exp.get("bullets", [])]
        exp["bullets"] = reorder_bullets_by_relevance(exp.get("bullets", []), target_keywords)
        after = [text_of(b) for b in exp["bullets"]]
        if before != after:
            changes.append(f"{exp.get('company', '')} 段 bullet 重排")
    tailored["experience"] = annotate_bullets(tailored["experience"], target_keywords)

    # 5. Skills 重排+补充
    resume_text = " ".join([
        text_of(b)
        for exp in tailored.get("experience", []) + tailored.get("projects", [])
        for b in exp.get("bullets", [])
    ])
    old_skills = (tailored.get("skills") or {}).get("hard_skills", []) or []
    tailored["skills"] = update_skills_section(
        tailored.get("skills", {}), must_have, nice_to_have, resume_text
    )
    new_skills = tailored["skills"].get("hard_skills", []) or []
    added = set(new_skills) - set(old_skills)
    if added:
        changes.append(f"Skills 区补充: {', '.join(sorted(added))}")

    # 6. 标记需要手动改写的低分 bullet
    todo = []
    for exp in tailored["experience"]:
        for b in exp.get("bullets", []):
            if b.get("xyz_grade") in ("D", "F"):
                todo.append({
                    "company": exp.get("company"),
                    "bullet": b.get("text"),
                    "grade": b.get("xyz_grade"),
                    "suggestion": "用 XYZ 公式改写：动词+做了什么+数字+方法",
                })

    # 元数据
    meta = tailored.setdefault("_meta", {})
    meta["tailored_for_jd"] = jd.get("job_title", "")
    meta["tailored_changes"] = changes
    meta["bullets_need_rewrite"] = todo
    meta["jd_must_have_keywords"] = must_have
    meta["jd_nice_to_have_keywords"] = nice_to_have

    return tailored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", type=Path)
    parser.add_argument("jd", type=Path)
    args = parser.parse_args()

    resume = json.loads(args.resume.read_text(encoding="utf-8"))
    jd = json.loads(args.jd.read_text(encoding="utf-8"))

    tailored = tailor(resume, jd)
    print(json.dumps(tailored, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

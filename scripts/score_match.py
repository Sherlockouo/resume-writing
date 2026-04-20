#!/usr/bin/env python3
"""
score_match.py — 简历 vs JD 匹配评分（模拟 ATS）。

用法:
    python score_match.py <resume.json> <jd.json> [--format json|md]

输出:
    - 总分 (0–100)
    - 必备关键词命中率
    - 缺失关键词清单
    - 硬性门槛是否满足
    - 改进建议（按优先级）

评分权重:
    必备硬技能命中:  50 分
    加分技能命中:    15 分
    Job Title 出现:  10 分
    年限/学历门槛:   10 分
    量化指标覆盖率:  10 分
    通用关键词覆盖:   5 分
"""

import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple


def resume_to_text(resume: Dict) -> str:
    """把简历 JSON 拍平成大字符串，方便关键词搜索。"""
    parts = []
    bi = resume.get("basic_info", {})
    parts.append(bi.get("name", ""))
    parts.append(bi.get("target_position", ""))
    parts.append(resume.get("summary", "") or "")
    for exp in resume.get("experience", []) + resume.get("projects", []):
        parts.append(f"{exp.get('company', '')} {exp.get('position', '')}")
        for b in exp.get("bullets", []):
            parts.append(b.get("text", "") if isinstance(b, dict) else str(b))
    for edu in resume.get("education", []):
        parts.append(f"{edu.get('school', '')} {edu.get('degree', '')} {edu.get('major', '')}")
    skills = resume.get("skills", {})
    for k in ("hard_skills", "soft_skills", "languages", "certifications"):
        parts.extend(skills.get(k, []) or [])
    return "\n".join(p for p in parts if p)


def keyword_hits(resume_text: str, keywords: List[str]) -> Tuple[List[str], List[str]]:
    """返回 (命中, 缺失)。"""
    hits, missing = [], []
    for kw in keywords:
        if any(c.isalpha() and ord(c) < 128 for c in kw):
            pattern = r"\b" + re.escape(kw) + r"\b"
        else:
            pattern = re.escape(kw)
        if re.search(pattern, resume_text, re.IGNORECASE):
            hits.append(kw)
        else:
            missing.append(kw)
    return hits, missing


def check_skills_section_coverage(resume: Dict, must_have: List[str]) -> Dict[str, bool]:
    """检查必备技能是否同时出现在 Skills 区和 Experience 区（向量匹配 + 上下文验证）。"""
    skills_text = " ".join(resume.get("skills", {}).get("hard_skills", []) or [])
    exp_text_parts = []
    for exp in resume.get("experience", []) + resume.get("projects", []):
        for b in exp.get("bullets", []):
            exp_text_parts.append(b.get("text", "") if isinstance(b, dict) else str(b))
    exp_text = "\n".join(exp_text_parts)

    coverage = {}
    for kw in must_have:
        if any(c.isalpha() and ord(c) < 128 for c in kw):
            p = r"\b" + re.escape(kw) + r"\b"
        else:
            p = re.escape(kw)
        in_skills = bool(re.search(p, skills_text, re.IGNORECASE))
        in_exp = bool(re.search(p, exp_text, re.IGNORECASE))
        coverage[kw] = in_skills and in_exp
    return coverage


def check_years(resume: Dict, years_req: str) -> Tuple[bool, float]:
    """检查年限门槛。"""
    if not years_req:
        return True, 0
    m = re.search(r"\d+", years_req)
    if not m:
        return True, 0
    required = int(m.group(0))
    actual = resume.get("basic_info", {}).get("years_experience")
    if actual is None:
        # 从经历计算
        actual = estimate_years_from_experience(resume)
    return actual >= required, actual


def estimate_years_from_experience(resume: Dict) -> float:
    """从工作经历粗略估计年限。"""
    from parse_resume import estimate_years
    return estimate_years(resume)


def check_education(resume: Dict, edu_req: str) -> bool:
    if not edu_req:
        return True
    rank = {"大专+": 1, "本科/Bachelor+": 2, "硕士/Master+": 3, "博士/PhD": 4}
    required = rank.get(edu_req, 0)
    actual = 0
    for edu in resume.get("education", []):
        deg = edu.get("degree", "")
        if re.search(r"博士|PhD|Doctor", deg, re.IGNORECASE):
            actual = max(actual, 4)
        elif re.search(r"硕士|Master|研究生", deg, re.IGNORECASE):
            actual = max(actual, 3)
        elif re.search(r"本科|学士|Bachelor", deg, re.IGNORECASE):
            actual = max(actual, 2)
        elif re.search(r"大专|专科|Associate", deg, re.IGNORECASE):
            actual = max(actual, 1)
    return actual >= required


def check_quantification(resume: Dict) -> Tuple[float, int, int]:
    """计算 bullet 的量化覆盖率。返回 (比例, 含数字 bullet 数, 总 bullet 数)。"""
    total, with_metrics = 0, 0
    for exp in resume.get("experience", []) + resume.get("projects", []):
        for b in exp.get("bullets", []):
            total += 1
            if isinstance(b, dict):
                if b.get("metrics") or re.search(r"\d", b.get("text", "")):
                    with_metrics += 1
            else:
                if re.search(r"\d", str(b)):
                    with_metrics += 1
    if total == 0:
        return 0.0, 0, 0
    return with_metrics / total, with_metrics, total


def check_job_title_in_top(resume: Dict, job_title: str) -> bool:
    """目标 Job Title 是否在简历顶部出现。"""
    if not job_title:
        return True
    bi = resume.get("basic_info", {})
    top = " ".join([
        bi.get("target_position", "") or "",
        resume.get("summary", "") or "",
    ])
    return bool(re.search(re.escape(job_title), top, re.IGNORECASE))


def score(resume: Dict, jd: Dict) -> Dict[str, Any]:
    """主评分函数。"""
    resume_text = resume_to_text(resume)

    must_have = jd.get("must_have_skills", [])
    nice_to_have = jd.get("nice_to_have_skills", [])
    job_title = jd.get("job_title", "")

    # 1. 必备技能命中
    must_hits, must_missing = keyword_hits(resume_text, must_have)
    must_score = (len(must_hits) / len(must_have) * 50) if must_have else 50

    # 2. 加分技能命中
    nice_hits, nice_missing = keyword_hits(resume_text, nice_to_have)
    nice_score = (len(nice_hits) / len(nice_to_have) * 15) if nice_to_have else 10

    # 3. Job Title 在顶部
    title_score = 10 if check_job_title_in_top(resume, job_title) else 0

    # 4. 年限 + 学历门槛
    years_ok, actual_years = check_years(resume, jd.get("years_required", ""))
    edu_ok = check_education(resume, jd.get("education_required", ""))
    threshold_score = 5 if years_ok else 0
    threshold_score += 5 if edu_ok else 0

    # 5. 量化覆盖率
    qratio, qhits, qtotal = check_quantification(resume)
    quant_score = qratio * 10

    # 6. 通用关键词覆盖
    general_kws = [item["word"] for item in jd.get("general_keywords_top30", [])][:15]
    general_hits, general_missing = keyword_hits(resume_text, general_kws)
    general_score = (len(general_hits) / len(general_kws) * 5) if general_kws else 0

    # 7. 上下文交叉验证
    coverage = check_skills_section_coverage(resume, must_hits)
    cross_verified = sum(1 for v in coverage.values() if v)

    total = round(must_score + nice_score + title_score + threshold_score
                  + quant_score + general_score, 1)

    # 优先级建议
    recommendations = []
    if must_missing:
        recommendations.append({
            "priority": "P0-必修",
            "issue": f"缺失 {len(must_missing)} 个必备硬技能",
            "items": must_missing,
            "action": "如果你确实有这些经验，原词加进 Experience 和 Skills；没有就放弃这个岗或先补技能",
        })
    if not years_ok:
        recommendations.append({
            "priority": "P0-硬伤",
            "issue": f"年限不足，要求 {jd.get('years_required')}，实际约 {actual_years} 年",
            "action": "实习/项目经验补全；或换岗位",
        })
    if not edu_ok:
        recommendations.append({
            "priority": "P0-硬伤",
            "issue": f"学历不达标，要求 {jd.get('education_required')}",
            "action": "如果在读，注明预期毕业时间",
        })
    if not check_job_title_in_top(resume, job_title):
        recommendations.append({
            "priority": "P1-高优",
            "issue": f"目标职位 '{job_title}' 没出现在简历顶部",
            "action": "在 basic_info.target_position 或 Summary 里加入原词",
        })
    if qratio < 0.5:
        recommendations.append({
            "priority": "P1-高优",
            "issue": f"量化覆盖率仅 {round(qratio*100)}%（{qhits}/{qtotal}），低于 50%",
            "action": "用 XYZ 公式改写 bullet，每条至少加一个数字",
        })
    weak_coverage = [kw for kw, v in coverage.items() if not v]
    if weak_coverage:
        recommendations.append({
            "priority": "P2-建议",
            "issue": f"{len(weak_coverage)} 个关键词只在 Skills 区出现，Experience 里无支撑",
            "items": weak_coverage,
            "action": "每个核心关键词应同时出现在 Skills + Experience，向量匹配会降权孤立词",
        })
    if nice_missing:
        recommendations.append({
            "priority": "P3-加分",
            "issue": f"{len(nice_missing)} 个加分技能可补",
            "items": nice_missing[:10],
            "action": "如果确实有，加进 Skills 区",
        })

    return {
        "total_score": total,
        "verdict": (
            "🟢 强匹配，建议立刻投递" if total >= 80
            else "🟡 中匹配，先补优先级问题再投" if total >= 65
            else "🔴 弱匹配，建议先补技能或换岗位"
        ),
        "breakdown": {
            "必备技能": {"score": round(must_score, 1), "max": 50,
                       "hits": len(must_hits), "total": len(must_have)},
            "加分技能": {"score": round(nice_score, 1), "max": 15,
                       "hits": len(nice_hits), "total": len(nice_to_have)},
            "Job Title 在顶部": {"score": title_score, "max": 10},
            "硬性门槛(年限+学历)": {"score": threshold_score, "max": 10,
                                "years_ok": years_ok, "edu_ok": edu_ok,
                                "actual_years": actual_years},
            "量化覆盖": {"score": round(quant_score, 1), "max": 10,
                       "ratio": round(qratio, 2), "hits": qhits, "total": qtotal},
            "通用关键词": {"score": round(general_score, 1), "max": 5,
                        "hits": len(general_hits), "total": len(general_kws)},
        },
        "must_have_hit": must_hits,
        "must_have_missing": must_missing,
        "nice_to_have_hit": nice_hits,
        "nice_to_have_missing": nice_missing,
        "cross_verified_count": cross_verified,
        "weak_coverage_keywords": weak_coverage,
        "recommendations": recommendations,
    }


def format_md(result: Dict, jd: Dict) -> str:
    """Markdown 格式输出，方便贴给用户。"""
    lines = [
        f"# 匹配评分报告\n",
        f"**目标岗位**：{jd.get('job_title', 'N/A')}\n",
        f"**总分**：**{result['total_score']} / 100**　{result['verdict']}\n",
        "## 分项得分",
        "| 项目 | 得分 | 满分 | 详情 |",
        "| --- | --- | --- | --- |",
    ]
    for name, info in result["breakdown"].items():
        detail = ""
        if "hits" in info and "total" in info:
            detail = f"{info['hits']}/{info['total']}"
        elif "ratio" in info:
            detail = f"{info['ratio']*100:.0f}%"
        elif "years_ok" in info:
            detail = f"年限 {'✓' if info['years_ok'] else '✗'}, 学历 {'✓' if info['edu_ok'] else '✗'}"
        lines.append(f"| {name} | {info['score']} | {info['max']} | {detail} |")

    lines.append("\n## 必修缺口（P0）")
    if result["must_have_missing"]:
        lines.append("缺失这些必备技能（JD 出现 ≥2 次）：")
        for kw in result["must_have_missing"]:
            lines.append(f"- ❌ `{kw}`")
    else:
        lines.append("✅ 必备技能全部命中")

    lines.append("\n## 改进建议")
    for r in result["recommendations"]:
        lines.append(f"### [{r['priority']}] {r['issue']}")
        if r.get("items"):
            lines.append("涉及：" + ", ".join(f"`{i}`" for i in r["items"][:10]))
        lines.append(f"→ {r['action']}\n")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", type=Path)
    parser.add_argument("jd", type=Path)
    parser.add_argument("--format", default="json", choices=["json", "md"])
    args = parser.parse_args()

    resume = json.loads(args.resume.read_text(encoding="utf-8"))
    jd = json.loads(args.jd.read_text(encoding="utf-8"))

    result = score(resume, jd)
    if args.format == "md":
        print(format_md(result, jd))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

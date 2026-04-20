#!/usr/bin/env python3
"""
batch_apply.py — 一份简历 × N 个 JD → N 份适配后的 .docx + 评分汇总。

用法:
    python batch_apply.py <resume.json> <jds_folder/> <output_folder/>

输入:
    resume.json     已经解析好的简历 JSON
    jds_folder/     文件夹，里面每个 .txt 文件是一个 JD
                    文件名格式: 公司_岗位.txt （如 腾讯_高级后端.txt）

输出:
    output_folder/
    ├── 张三_高级后端_腾讯.docx        # 适配后的简历
    ├── 张三_高级后端_字节.docx
    ├── 张三_高级后端_美团.docx
    ├── coverletter_腾讯.md            # 求职信草稿
    ├── coverletter_字节.md
    ├── coverletter_美团.md
    ├── summary.csv                     # 汇总评分表
    └── changes_log.md                  # 每份简历的修改记录

依赖: 同其他脚本
"""

import sys
import json
import csv
import argparse

from pathlib import Path
from typing import List


# 引用同目录下其他脚本
SCRIPT_DIR = Path(__file__).parent

# 直接 import 模块（同目录），避免每次 subprocess
sys.path.insert(0, str(SCRIPT_DIR))
from extract_jd import parse_jd
from score_match import score
from tailor_resume import tailor
from export_docx import export
from generate_cover_letter import generate as gen_cover


def apply_to_jd(resume: dict, jd_text: str, jd_label: str,
                output_dir: Path, name: str, lang: str) -> dict:
    """对单个 JD 完整跑一遍：解析 JD → 评分 → 适配 → 导出 → 求职信。"""
    jd = parse_jd(jd_text)

    # 评分（基于原始简历，反映"如果不改"的状态）
    pre_score = score(resume, jd)

    # 适配
    tailored = tailor(resume, jd)

    # 适配后再评分（反映"机械适配后"的状态，距离最高分还差 Claude 手动改写）
    post_score = score(tailored, jd)

    # 导出 .docx
    safe_label = jd_label.replace("/", "_").replace(" ", "_")
    docx_path = output_dir / f"{name}_{safe_label}.docx"
    export(tailored, docx_path)

    # 求职信草稿
    cl_path = output_dir / f"coverletter_{safe_label}.md"
    cl_path.write_text(gen_cover(tailored, jd, "formal", lang), encoding="utf-8")

    # 适配后的 JSON（方便用户检查/手改）
    json_path = output_dir / f"{name}_{safe_label}.tailored.json"
    json_path.write_text(json.dumps(tailored, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    return {
        "jd_label": jd_label,
        "job_title": jd.get("job_title", ""),
        "pre_score": pre_score["total_score"],
        "post_score": post_score["total_score"],
        "verdict": post_score["verdict"],
        "must_have_total": len(jd.get("must_have_skills", [])),
        "must_have_hit": len(post_score["must_have_hit"]),
        "must_have_missing": post_score["must_have_missing"],
        "p0_issues": [r for r in post_score["recommendations"]
                      if r["priority"].startswith("P0")],
        "bullets_to_rewrite": len(tailored.get("_meta", {}).get("bullets_need_rewrite", [])),
        "docx_path": str(docx_path),
        "cover_letter_path": str(cl_path),
    }


def write_summary_csv(results: List[dict], output_path: Path):
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "JD", "岗位名", "原始分", "适配后分", "判断",
            "必备技能命中", "必备技能缺失数", "P0 硬伤数",
            "需手改 bullet 数", "简历文件", "求职信文件",
            "建议优先级",
        ])
        # 按适配后分降序
        results.sort(key=lambda r: -r["post_score"])
        for r in results:
            priority = "🟢 立刻投" if r["post_score"] >= 80 else \
                       "🟡 补完再投" if r["post_score"] >= 65 else \
                       "🔴 暂缓 / 换岗"
            writer.writerow([
                r["jd_label"],
                r["job_title"],
                r["pre_score"],
                r["post_score"],
                r["verdict"],
                f"{r['must_have_hit']}/{r['must_have_total']}",
                len(r["must_have_missing"]),
                len(r["p0_issues"]),
                r["bullets_to_rewrite"],
                Path(r["docx_path"]).name,
                Path(r["cover_letter_path"]).name,
                priority,
            ])


def write_changes_log(results: List[dict], output_path: Path):
    lines = ["# 批量适配修改记录\n"]
    for r in results:
        lines.append(f"## {r['jd_label']} → {r['job_title']}")
        lines.append(f"- 原始匹配分: **{r['pre_score']}** → 适配后: **{r['post_score']}**")
        lines.append(f"- 必备技能命中: {r['must_have_hit']}/{r['must_have_total']}")
        if r["must_have_missing"]:
            lines.append(f"- 缺失必备技能: {', '.join('`'+k+'`' for k in r['must_have_missing'])}")
        if r["p0_issues"]:
            lines.append("- P0 硬伤:")
            for issue in r["p0_issues"]:
                lines.append(f"  - {issue['issue']} → {issue['action']}")
        if r["bullets_to_rewrite"] > 0:
            lines.append(f"- ⚠️ 还有 {r['bullets_to_rewrite']} 条 bullet 评分 D/F，"
                         "需要 Claude/用户手动用 XYZ 公式改写")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resume", type=Path)
    parser.add_argument("jds_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    resume = json.loads(args.resume.read_text(encoding="utf-8"))
    name = resume.get("basic_info", {}).get("name", "Resume")

    jd_files = sorted(args.jds_dir.glob("*.txt"))
    if not jd_files:
        sys.exit(f"未在 {args.jds_dir} 找到任何 .txt JD 文件")

    print(f"找到 {len(jd_files)} 个 JD，开始批量适配...", file=sys.stderr)

    results = []
    for jd_file in jd_files:
        label = jd_file.stem  # 公司_岗位
        print(f"  → {label}", file=sys.stderr)
        try:
            jd_text = jd_file.read_text(encoding="utf-8")
            result = apply_to_jd(resume, jd_text, label, args.output_dir, name, args.lang)
            results.append(result)
        except Exception as e:
            print(f"    失败: {e}", file=sys.stderr)
            results.append({
                "jd_label": label, "job_title": "", "pre_score": 0,
                "post_score": 0, "verdict": f"❌ 失败: {e}",
                "must_have_total": 0, "must_have_hit": 0, "must_have_missing": [],
                "p0_issues": [], "bullets_to_rewrite": 0,
                "docx_path": "", "cover_letter_path": "",
            })

    summary_path = args.output_dir / "summary.csv"
    write_summary_csv(results, summary_path)

    changes_path = args.output_dir / "changes_log.md"
    write_changes_log(results, changes_path)

    print(f"\n✅ 完成。汇总: {summary_path}", file=sys.stderr)
    print(f"   修改记录: {changes_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

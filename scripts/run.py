#!/usr/bin/env python3
"""
run.py — 一键完成 Skill 全流程。

最简用法（一份原始简历 + 一个 JD 文件）:
    python run.py --resume /path/to/简历.pdf --jd /path/to/jd.txt --out ./output/

批量投递（一份原始简历 + 多个 JD）:
    python run.py --resume /path/to/简历.pdf --jds-dir /path/to/jds/ --out ./output/

参数:
    --resume       原始简历，.docx 或 .pdf
    --jd           单个 JD 文件（与 --jds-dir 二选一）
    --jds-dir      JD 文件夹，里面每个 .txt 是一个 JD（推荐文件名: 公司_岗位.txt）
    --out          输出目录
    --lang         zh | en，默认 zh
    --tone         formal | warm | startup，求职信风格，默认 formal
    --skip-cover   不生成求职信
    --report       打印 markdown 评分报告到 stderr

输出（在 --out 下）:
    parsed_resume.json                       原始简历解析结果（让用户/Claude 检查）
    {name}_{jd_label}.docx                   每个 JD 一份适配后的 .docx
    {name}_{jd_label}.tailored.json          适配后的 JSON
    coverletter_{jd_label}.md                求职信草稿
    summary.csv                              汇总评分
    changes_log.md                           修改记录

工作流（内部串联了所有脚本）:
    parse_resume → extract_jd → score → tailor → export → cover_letter → summary
"""

import sys
import json
import argparse
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from parse_resume import parse as parse_resume
from extract_jd import parse_jd
from score_match import score, format_md as format_score_md
from tailor_resume import tailor
from export_docx import export, export_pdf
from generate_cover_letter import generate as gen_cover


def run_one(resume: dict, jd_text: str, jd_label: str, out_dir: Path,
            lang: str, tone: str, generate_cover: bool, print_report: bool) -> dict:
    """对单个 JD 跑全流程。"""
    jd = parse_jd(jd_text)
    name = resume.get("basic_info", {}).get("name") or "Resume"
    safe_label = jd_label.replace("/", "_").replace(" ", "_")

    pre_score = score(resume, jd)
    if print_report:
        print(f"\n{'='*60}\n📊 {jd_label} 适配前评分:", file=sys.stderr)
        print(format_score_md(pre_score, jd), file=sys.stderr)

    tailored = tailor(resume, jd)
    post_score = score(tailored, jd)

    docx_path = out_dir / f"{name}_{safe_label}.docx"
    export(tailored, docx_path)

    pdf_path = out_dir / f"{name}_{safe_label}.pdf"
    try:
        export_pdf(tailored, pdf_path)
    except Exception as e:
        print(f"      PDF 导出失败: {e}（.docx 仍可用）", file=sys.stderr)

    json_path = out_dir / f"{name}_{safe_label}.tailored.json"
    json_path.write_text(json.dumps(tailored, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    cl_path = None
    if generate_cover:
        cl_path = out_dir / f"coverletter_{safe_label}.md"
        cl_path.write_text(gen_cover(tailored, jd, tone, lang), encoding="utf-8")

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
        "cover_letter_path": str(cl_path) if cl_path else "",
    }


def write_summary(results: list, out_dir: Path):
    import csv
    summary_path = out_dir / "summary.csv"
    results = sorted(results, key=lambda r: -r["post_score"])
    with summary_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["JD", "岗位名", "原始分", "适配后分", "判断",
                    "必备技能命中", "缺失数", "P0 硬伤数", "需手改 bullet",
                    "简历文件", "求职信文件", "建议"])
        for r in results:
            priority = ("🟢 立刻投" if r["post_score"] >= 80
                        else "🟡 补完再投" if r["post_score"] >= 65
                        else "🔴 暂缓 / 换岗")
            w.writerow([
                r["jd_label"], r["job_title"], r["pre_score"], r["post_score"],
                r["verdict"],
                f"{r['must_have_hit']}/{r['must_have_total']}",
                len(r["must_have_missing"]),
                len(r["p0_issues"]),
                r["bullets_to_rewrite"],
                Path(r["docx_path"]).name,
                Path(r["cover_letter_path"]).name if r["cover_letter_path"] else "",
                priority,
            ])

    log_path = out_dir / "changes_log.md"
    lines = ["# 一键投递修改记录\n"]
    for r in results:
        lines.append(f"## {r['jd_label']} → {r['job_title']}")
        lines.append(f"- 原始分: **{r['pre_score']}** → 适配后: **{r['post_score']}**")
        lines.append(f"- 必备技能命中: {r['must_have_hit']}/{r['must_have_total']}")
        if r["must_have_missing"]:
            lines.append(f"- 缺失: {', '.join('`'+k+'`' for k in r['must_have_missing'])}")
        if r["p0_issues"]:
            lines.append("- P0 硬伤:")
            for issue in r["p0_issues"]:
                lines.append(f"  - {issue['issue']}")
                lines.append(f"    → {issue['action']}")
        if r["bullets_to_rewrite"] > 0:
            lines.append(f"- ⚠️ 还有 {r['bullets_to_rewrite']} 条 bullet 评分 D/F，"
                         "需要手动用 XYZ 公式改写")
        lines.append("")
    log_path.write_text("\n".join(lines), encoding="utf-8")

    return summary_path, log_path


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("--resume", type=Path, required=True, help="原始简历 .docx/.pdf 或已解析 .json")
    parser.add_argument("--jd", type=Path, help="单个 JD 文件")
    parser.add_argument("--jds-dir", type=Path, help="JD 文件夹（每个 .txt 一个 JD）")
    parser.add_argument("--out", type=Path, required=True, help="输出目录")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    parser.add_argument("--tone", default="formal", choices=["formal", "warm", "startup"])
    parser.add_argument("--skip-cover", action="store_true", help="不生成求职信")
    parser.add_argument("--report", action="store_true", help="到 stderr 打印评分报告")
    args = parser.parse_args()

    if not args.jd and not args.jds_dir:
        sys.exit("必须指定 --jd 或 --jds-dir")
    if args.jd and args.jds_dir:
        sys.exit("--jd 和 --jds-dir 二选一")

    args.out.mkdir(parents=True, exist_ok=True)

    # Step 1: 解析简历
    print(f"\n📥 解析简历: {args.resume}", file=sys.stderr)
    if args.resume.suffix.lower() == ".json":
        resume = json.loads(args.resume.read_text(encoding="utf-8"))
    elif args.resume.suffix.lower() in (".docx", ".pdf"):
        resume = parse_resume(args.resume)
    else:
        sys.exit(f"不支持的简历格式: {args.resume.suffix}")

    # 保存解析结果，供用户/Claude 检查
    parsed_path = args.out / "parsed_resume.json"
    parsed_path.write_text(json.dumps(resume, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(f"   ✓ 已保存解析结果: {parsed_path}", file=sys.stderr)
    print(f"   ⚠️  请检查 parsed_resume.json，章节识别错误时手动修正后再继续",
           file=sys.stderr)

    # Step 2-6: 对每个 JD 跑全流程
    results = []
    if args.jd:
        jd_text = args.jd.read_text(encoding="utf-8")
        label = args.jd.stem
        print(f"\n🎯 处理 JD: {label}", file=sys.stderr)
        results.append(run_one(resume, jd_text, label, args.out,
                               args.lang, args.tone,
                               not args.skip_cover, args.report))
    else:
        jd_files = sorted(args.jds_dir.glob("*.txt"))
        if not jd_files:
            sys.exit(f"在 {args.jds_dir} 没找到任何 .txt 文件")
        print(f"\n🎯 批量处理 {len(jd_files)} 个 JD", file=sys.stderr)
        for jd_file in jd_files:
            label = jd_file.stem
            print(f"   → {label}", file=sys.stderr)
            try:
                jd_text = jd_file.read_text(encoding="utf-8")
                results.append(run_one(resume, jd_text, label, args.out,
                                       args.lang, args.tone,
                                       not args.skip_cover, args.report))
            except Exception as e:
                print(f"      ❌ 失败: {e}", file=sys.stderr)

    # Step 7: 汇总
    summary_path, log_path = write_summary(results, args.out)
    print(f"\n✅ 全部完成", file=sys.stderr)
    print(f"   📊 评分汇总: {summary_path}", file=sys.stderr)
    print(f"   📝 修改记录: {log_path}", file=sys.stderr)
    print(f"   📁 全部产物: {args.out}", file=sys.stderr)
    print(f"\n建议下一步:", file=sys.stderr)
    print(f"   1. 打开 summary.csv 看每个岗位的匹配分", file=sys.stderr)
    print(f"   2. 对 🟡/🔴 的岗位，看 changes_log.md 列出的 P0 硬伤", file=sys.stderr)
    print(f"   3. 让 Claude 帮你手动改写 D/F 等级的 bullet（用 XYZ 公式）",
           file=sys.stderr)


if __name__ == "__main__":
    main()

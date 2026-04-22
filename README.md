# 简历.Skill

一站式简历助手 —— 解析、诊断、优化、按 JD 批量适配、导出 ATS 友好的 `.docx` / `.pdf`。

基于 2025-2026 年 HR 与 ATS（Applicant Tracking System）筛选的真实机制反向设计，作为 [Claude Code](https://claude.ai/claude-code) 的 Skill 运行。

## 能做什么

```
原始简历 (.docx/.pdf) + 目标 JD  →  针对性适配的 .docx/.pdf + 匹配评分 + 求职信
```

完整流水线：

```
解析 → 诊断 → JD 提取 → 匹配评分 → 优化适配 → 导出 → 求职信
```

## 快速开始

### 作为 Claude Code Skill 使用

在 Claude Code 中直接对话即可触发，例如：

- 上传简历 + 贴 JD，说"帮我改简历"
- "一键投 3 个岗位"
- "帮我写求职信"

### 命令行使用

```bash
# 单岗位
python scripts/run.py --resume 简历.pdf --jd jd.txt --out output/

# 批量投递
python scripts/run.py --resume 简历.pdf --jds-dir jds/ --out output/
```

### 参数说明

| 参数           | 说明                                      |
| -------------- | ----------------------------------------- |
| `--resume`     | 原始简历，`.docx` / `.pdf` / `.json`      |
| `--jd`         | 单个 JD 文件（与 `--jds-dir` 二选一）     |
| `--jds-dir`    | JD 文件夹，每个 `.txt` 一个 JD            |
| `--out`        | 输出目录                                  |
| `--lang`       | `zh` / `en`，默认 `zh`                    |
| `--tone`       | `formal` / `warm` / `startup`，求职信风格 |
| `--skip-cover` | 不生成求职信                              |
| `--report`     | 打印评分报告到 stderr                     |

## 输出物

| 文件                  | 说明                   |
| --------------------- | ---------------------- |
| `parsed_resume.json`  | 简历解析结果（供检查） |
| `{姓名}_{JD}.docx`    | 适配后的简历           |
| `{姓名}_{JD}.pdf`     | PDF 版本               |
| `coverletter_{JD}.md` | 求职信草稿             |
| `summary.csv`         | 所有岗位的匹配评分汇总 |
| `changes_log.md`      | 修改记录               |

## 项目结构

```
resume-writing/
├── SKILL.md                        # Skill 定义（完整规则与知识库）
├── scripts/
│   ├── run.py                      # 一键入口
│   ├── parse_resume.py             # .docx/.pdf → JSON
│   ├── extract_jd.py               # JD 文本 → 关键词/门槛 JSON
│   ├── score_match.py              # 简历 vs JD → 匹配分 + 缺口
│   ├── tailor_resume.py            # 按 JD 重排 + 改写
│   ├── export_docx.py              # JSON → .docx / .pdf
│   ├── generate_cover_letter.py    # 简历 + JD → 求职信
│   └── batch_apply.py              # 一份简历 × N 个 JD
├── templates/
│   ├── resume_schema.json          # 结构化简历 JSON Schema
│   ├── ats_template_zh.md          # 中文简历模板
│   ├── ats_template_en.md          # 英文简历模板
│   └── cover_letter_templates.md   # 求职信模板
└── reference/
    ├── action_verbs.md             # 强动词词库（中英）
    ├── ats_killers.md              # ATS 解析杀手清单
    └── industry_keywords.md        # 分行业关键词
```

## 核心原则

简历的真正读者顺序：**ATS（机器）→ HR（6 秒）→ 面试官**。75% 的简历死在第一关。

1. **关键词原则** — JD 出现 >=2 次的技能必须原词进简历
2. **6 秒动线** — 第一屏 = 姓名 + 目标职位 + 最强成就
3. **量化原则（XYZ 公式）** — `Accomplished [X] as measured by [Y] by doing [Z]`
4. **相关性原则** — 一岗一简历，最相关放最前
5. **可信度原则** — 时间线连续，数字真实
6. **可解析原则** — 单栏、无表格、无图标、文本型 PDF / .docx

## 依赖

- Python 3.10+
- `python-docx` — .docx 读写
- `fpdf2` — PDF 导出
- `pdfplumber` — PDF 解析

```bash
pip install python-docx fpdf2 pdfplumber
```

## License

MIT

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify_questions.py — 题型分类整理器

用法:
    python3 classify_questions.py <bank.json 或 题库.zip> [--out <输出目录>]
        [--title 标题] [--filter-grade 六年级,八年级]
        [--filter-subject 数学] [--no-source]

功能:
    1. 读取题库（bank.json 或直接传 zip，自动先解析）
    2. 按 年级 → 学科 → 知识点（题型）三级分门别类
    3. 每个题型分类内部，按难度从易到难（1→5）递增排列
    4. 输出单份新文档（题型分类整理.md）：含分类目录 + 难度层级标注
    5. 题目原文完整保留，不改动内容；多知识点题按主知识点（第一个）归类

说明:
    - 年级 / 学科来自题目解析结果（题库标签【年级：】【学科：】或文件名推断，如
      "六年级数学_有理数.txt" → 六年级 / 数学）；缺失时归入"未标注"。
    - 每道题的"主知识点"取 knowledge_points 的第一个，用于归类；其余知识点在题内保留。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DIFF_LABEL = {1: "易", 2: "较易", 3: "中", 4: "较难", 5: "难"}
DIFF_STARS = {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}

# 年级排序（从低到高），未命中或"未标注"排最后
GRADE_RANK = {
    "小学": 0,
    "一年级": 1, "二年级": 2, "三年级": 3, "四年级": 4, "五年级": 5,
    "预备班": 6, "预初": 6, "六年级": 6,
    "初中": 7, "初一": 7, "七年级": 7,
    "初二": 8, "八年级": 8,
    "初三": 9, "九年级": 9,
    "高中": 10, "高一": 11, "高二": 12, "高三": 13,
}
# 学科排序（常见主科/理科在前），未命中排最后
SUBJECT_ORDER = [
    "语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
    "道法", "科学", "信息科技", "信息技术", "体育", "音乐", "美术",
]


def grade_key(g):
    for k, v in GRADE_RANK.items():
        if k in (g or ""):
            return (v, g or "")
    return (99, g or "未标注")


def subject_key(s):
    for i, k in enumerate(SUBJECT_ORDER):
        if k in (s or ""):
            return (i, s or "")
    return (99, s or "未标注")


def diff_key(q):
    d = q.get("difficulty")
    return (d if d is not None else 99, q.get("id", ""))


def load_questions(inp, out_dir):
    """读取题目：bank.json 直接读；.zip 先调用 parse_bank.py 解析。"""
    if inp.lower().endswith(".zip"):
        tmp = tempfile.mkdtemp(dir=out_dir)
        r = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "parse_bank.py"), inp, "--out", tmp],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print("解析题库失败：\n%s" % r.stderr, file=sys.stderr)
            sys.exit(1)
        bank = json.load(open(os.path.join(tmp, "bank.json"), encoding="utf-8"))
    else:
        bank = json.load(open(inp, encoding="utf-8"))
    return bank.get("questions", [])


def fmt_source(q):
    parts = []
    if q.get("school"):
        parts.append(q["school"])
    if q.get("year"):
        parts.append("%s年" % q["year"])
    if q.get("exam_type"):
        parts.append("%s试卷" % q["exam_type"])
    if q.get("number"):
        parts.append("原卷第%s题" % q["number"])
    return " · ".join(parts) if parts else "待补充（题库未标注）"


def build_tree(questions, f_grades, f_subjects):
    """构建 年级 → 学科 → 知识点(主) → [题目] 树。"""
    fg = set(x.strip() for x in (f_grades or "").split(",") if x.strip())
    fs = set(x.strip() for x in (f_subjects or "").split(",") if x.strip())
    tree = {}
    for q in questions:
        grade = q.get("grade") or "未标注"
        subject = q.get("subject") or "未标注"
        if fg and grade not in fg:
            continue
        if fs and subject not in fs:
            continue
        kps = q.get("knowledge_points") or []
        kp = kps[0] if kps else "未分类知识点"
        tree.setdefault(grade, {}).setdefault(subject, {}).setdefault(kp, []).append(q)
    return tree


def diff_dist_str(qs):
    cnt = {DIFF_LABEL[d]: 0 for d in range(1, 6)}
    cnt["待定级"] = 0
    for q in qs:
        d = q.get("difficulty")
        key = DIFF_LABEL.get(d, "待定级")
        cnt[key] += 1
    order = ["易", "较易", "中", "较难", "难", "待定级"]
    return "·".join("%s%d" % (k, cnt[k]) for k in order if cnt[k])


def render(questions, title, tree, show_source):
    today = date.today().strftime("%Y-%m-%d")
    total = sum(len(qs) for g in tree.values() for s in g.values() for qs in s.values())
    n_sections = sum(len(s) for g in tree.values() for s in g.values())

    L = []
    L.append("# %s" % title)
    L.append("")
    L.append("> 整理日期：%s　|　题目总数：**%d**　|　分类数（题型）：**%d**　|　分类维度：年级 · 学科 · 知识点" % (today, total, n_sections))
    L.append("")
    L.append("本文档由题库自动分类整理生成：按 **年级 → 学科 → 知识点（题型）** 三级归类，每个题型分类内的题目按**难度从易到难**递增排列；题目原文完整保留，多知识点题目按其**主知识点**归类。")
    L.append("")

    # 难度层级标注说明
    L.append("## 难度层级标注说明")
    L.append("")
    L.append("| 难度值 | 星级 | 层级 |")
    L.append("|--------|------|------|")
    for d in range(1, 6):
        L.append("| %d | %s | %s |" % (d, DIFF_STARS[d], DIFF_LABEL[d]))
    L.append("| 未标注 | — | 待定级（题库未标注难度，按原卷顺序列于该题型末尾） |")
    L.append("")

    # 分类目录
    L.append("## 分类目录")
    L.append("")
    for grade in sorted(tree.keys(), key=grade_key):
        for subject in sorted(tree[grade].keys(), key=subject_key):
            L.append("- **%s · %s**" % (grade, subject))
            for kp in sorted(tree[grade][subject].keys(), key=lambda x: -len(tree[grade][subject][x])):
                qs = tree[grade][subject][kp]
                L.append("  - %s题型（共 %d 题｜%s）" % (kp, len(qs), diff_dist_str(qs)))
    L.append("")

    # 正文分章节
    for grade in sorted(tree.keys(), key=grade_key):
        for subject in sorted(tree[grade].keys(), key=subject_key):
            L.append("## %s · %s" % (grade, subject))
            L.append("")
            for kp in sorted(tree[grade][subject].keys(), key=lambda x: -len(tree[grade][subject][x])):
                qs = sorted(tree[grade][subject][kp], key=diff_key)
                L.append("### %s题型（共 %d 题）" % (kp, len(qs)))
                L.append("")
                L.append("> 本题型按难度从易到难排列；难度标注见文首《难度层级标注说明》。")
                L.append("")
                for i, q in enumerate(qs, 1):
                    d = q.get("difficulty")
                    stars = DIFF_STARS.get(d, "—")
                    label = DIFF_LABEL.get(d, "待定级")
                    head = "**【题%d】难度：%s（%s）**" % (i, stars, label)
                    if show_source:
                        head += "　📌 来源：%s" % fmt_source(q)
                    L.append(head)
                    L.append("")
                    L.append(q.get("stem", "").strip())
                    L.append("")
            L.append("---")
            L.append("")

    return "\n".join(L).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="题型分类整理器（年级·学科·知识点三级分类）")
    ap.add_argument("input", help="bank.json 或 题库.zip")
    ap.add_argument("--out", default=None, help="输出目录（默认与输入同目录）")
    ap.add_argument("--title", default="题型分类整理", help="文档标题")
    ap.add_argument("--filter-grade", default="", help="仅包含这些年级（逗号分隔）")
    ap.add_argument("--filter-subject", default="", help="仅包含这些学科（逗号分隔）")
    ap.add_argument("--no-source", action="store_true", help="不输出题目来源标注")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(os.path.abspath(args.input))
    os.makedirs(out_dir, exist_ok=True)

    questions = load_questions(args.input, out_dir)
    if not questions:
        print("错误：题库为空或解析失败。", file=sys.stderr)
        sys.exit(1)

    tree = build_tree(questions, args.filter_grade, args.filter_subject)
    if not tree:
        print("错误：按过滤条件未匹配到任何题目。", file=sys.stderr)
        sys.exit(1)

    md = render(questions, args.title, tree, not args.no_source)
    out_path = os.path.join(out_dir, "题型分类整理.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print("✅ 题型分类整理完成：%d 题，%d 个题型分类" % (
        sum(len(qs) for g in tree.values() for s in g.values() for qs in s.values()),
        sum(len(s) for g in tree.values() for s in g.values())))
    print("   输出文档：%s" % out_path)


if __name__ == "__main__":
    main()

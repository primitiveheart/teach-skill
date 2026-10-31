#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""organize_bank.py — 题库智能整理器

用法:
    python3 organize_bank.py <bank.json 或 题库.zip> [--out <输出目录>]
        [--filter-type 选择题,填空题] [--filter-kp 知识点A,知识点B]
        [--filter-diff 易,中,难] [--dedupe]

功能:
    1. 自动按 题型 / 知识点 / 难度 / 来源文档 四个维度整理归类题库
    2. 输出: 目录总览、题型分类目录、知识点分类目录、文档来源索引
    3. 可选相似题检测（--dedupe），输出去重报告，方便合并重复题

说明:
    - 输入可直接传 zip（自动先调 parse_bank.py 解析），也可传已解析的 bank.json
    - 全部使用 Python 标准库，无第三方依赖
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher

CN_NUM = "一二三四五六七八九十"
DIFF_NAME = {1: "易", 2: "较易", 3: "中", 4: "较难", 5: "难"}
LEVEL_TAG = {1: "基础", 2: "基础", 3: "中档", 4: "挑战", 5: "挑战"}


def load_bank(path, out_dir):
    """加载 bank.json；传入 zip 时先自动解析。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        print("错误: 找不到文件 %s" % path, file=sys.stderr)
        sys.exit(1)
    if path.lower().endswith(".zip"):
        tmp = os.path.join(out_dir, ".tmp_parse")
        os.makedirs(tmp, exist_ok=True)
        try:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parse_bank.py")
            subprocess.run([sys.executable, script, path, "--out", tmp], check=True)
            bank_path = os.path.join(tmp, "bank.json")
            with open(bank_path, encoding="utf-8") as f:
                bank = json.load(f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return bank
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def diff_name(d):
    return DIFF_NAME.get(d, "未标注")


def level_tag(d):
    return LEVEL_TAG.get(d, "未标注")


def stem_summary(q, limit=42):
    s = re.sub(r"\s+", " ", q["stem"]).strip()
    return s if len(s) <= limit else s[:limit] + "…"


def kp_list(q):
    return q["knowledge_points"] or ["未标注"]


def type_of(q):
    return q["type"] or "未标注"


def apply_filters(questions, ftype, fkp, fdiff):
    out = []
    for q in questions:
        if ftype and type_of(q) not in ftype:
            continue
        if fkp and not (set(q["knowledge_points"]) & fkp):
            continue
        if fdiff:
            d = diff_name(q["difficulty"]) if q["difficulty"] else "未标注"
            if d not in fdiff:
                continue
        out.append(q)
    return out


def dedupe_detect(questions, threshold=0.88):
    """归一化题干后做相似度检测，返回相似题对列表。"""
    def norm(s):
        s = re.sub(r"[\s\u3000、。，,．.！？!?（）()【】\[\]“”\"':：;；/\\\-—_+*]", "", s)
        return s.lower()

    norms = [(q["id"], norm(q["stem"])) for q in questions if q["stem"]]
    pairs = []
    for i in range(len(norms)):
        ida, sa = norms[i]
        for j in range(i + 1, len(norms)):
            idb, sb = norms[j]
            if not sa or not sb:
                continue
            big, small = max(len(sa), len(sb)), min(len(sa), len(sb))
            if big / small > 1.35 or big < 12:
                continue
            r = SequenceMatcher(None, sa, sb).ratio()
            if r >= threshold:
                pairs.append((ida, idb, r))
    return pairs


def build_overview(qs, meta, filters_desc):
    usable = [q for q in qs if not q["untagged"]]
    no_answer = sum(1 for q in qs if not q["answer"])

    def dist(key_fn):
        d = {}
        for q in qs:
            for v in (key_fn(q) or ["未标注"]):
                d[v] = d.get(v, 0) + 1
        return dict(sorted(d.items(), key=lambda x: (-x[1], x[0])))

    lines = ["# 题库整理 · 目录总览", ""]
    if filters_desc:
        lines.append("> 本次整理过滤条件：" + "；".join(filters_desc))
        lines.append("")
    lines.append("- 题目总数：**%d**（已标注 %d / 未标注 %d）" % (len(qs), len(usable), len(qs) - len(usable)))
    lines.append("- 无答案题目：**%d**（整理时标注\"答案待补\"）" % no_answer)
    if meta.get("subject"):
        lines.append("- 学科：**%s**" % meta["subject"])
    if meta.get("grade"):
        lines.append("- 年级：**%s**" % meta["grade"])
    lines.append("")
    lines.append("## 题型分布")
    lines.append("| 题型 | 题数 | 占比 |")
    lines.append("|------|------|------|")
    for k, v in dist(lambda q: [type_of(q)]).items():
        lines.append("| %s | %d | %.0f%% |" % (k, v, v * 100.0 / len(qs)))
    lines.append("")
    lines.append("## 难度分布")
    lines.append("| 难度档 | 题数 |")
    lines.append("|--------|------|")
    for k, v in dist(lambda q: [diff_name(q["difficulty"])]).items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 知识点覆盖（按题数排序）")
    lines.append("| 知识点 | 题数 |")
    lines.append("|--------|------|")
    for k, v in dist(kp_list).items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 文档来源分布")
    lines.append("| 来源文档 | 题数 |")
    lines.append("|----------|------|")
    for k, v in dist(lambda q: [q["source"]]).items():
        lines.append("| %s | %d |" % (k, v))
    return "\n".join(lines) + "\n"


def build_type_catalog(qs):
    groups = {}
    for q in qs:
        groups.setdefault(type_of(q), []).append(q)
    lines = ["# 题库整理 · 题型分类目录", ""]
    lines.append("> 按题型归类，方便按考试结构选取题目。")
    lines.append("")
    for gi, (t, group) in enumerate(sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])), 1):
        lines.append("## %s、%s（%d 题）" % (CN_NUM[gi - 1] if gi <= 10 else gi, t, len(group)))
        lines.append("")
        lines.append("| 题号 | 难度 | 知识点 | 来源 | 题干摘要 |")
        lines.append("|------|------|--------|------|---------|")
        for q in group:
            lines.append("| %s | %s | %s | %s | %s |" % (
                q["id"], diff_name(q["difficulty"]), "、".join(kp_list(q)),
                q["source"], stem_summary(q)))
        lines.append("")
    return "\n".join(lines) + "\n"


def build_kp_catalog(qs):
    groups = {}
    for q in qs:
        for k in kp_list(q):
            groups.setdefault(k, []).append(q)
    lines = ["# 题库整理 · 知识点分类目录", ""]
    lines.append("> 按知识点归类，是\"按孩子薄弱点挑题\"的索引底稿：每个知识点下的题量、难度构成一目了然。")
    lines.append("")
    for k, group in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        n_easy = sum(1 for q in group if q["difficulty"] and q["difficulty"] <= 2)
        n_mid = sum(1 for q in group if q["difficulty"] == 3)
        n_hard = sum(1 for q in group if q["difficulty"] and q["difficulty"] >= 4)
        lines.append("## %s（%d 题 · 基础 %d / 中档 %d / 挑战 %d）" % (k, len(group), n_easy, n_mid, n_hard))
        lines.append("")
        lines.append("| 题号 | 题型 | 难度 | 来源 | 题干摘要 |")
        lines.append("|------|------|------|------|---------|")
        for q in sorted(group, key=lambda x: (x["difficulty"] or 9, x["id"])):
            lines.append("| %s | %s | %s | %s | %s |" % (
                q["id"], type_of(q), diff_name(q["difficulty"]), q["source"], stem_summary(q)))
        lines.append("")
    return "\n".join(lines) + "\n"


def build_source_index(qs):
    groups = {}
    for q in qs:
        groups.setdefault(q["source"], []).append(q)
    lines = ["# 题库整理 · 文档来源索引", ""]
    lines.append("> 按原始文档归档，可以看到每个文件贡献了哪些题、题型构成如何。")
    lines.append("")
    for src, group in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        type_dist = {}
        kp_dist = {}
        for q in group:
            type_dist[type_of(q)] = type_dist.get(type_of(q), 0) + 1
            for k in kp_list(q):
                kp_dist[k] = kp_dist.get(k, 0) + 1
        lines.append("## %s（%d 题）" % (src, len(group)))
        lines.append("")
        lines.append("- 题型构成：" + " ｜ ".join("%s×%d" % (k, v) for k, v in sorted(type_dist.items(), key=lambda x: -x[1])))
        lines.append("- 知识点 Top5：" + "、".join("%s(%d)" % (k, v) for k, v in sorted(kp_dist.items(), key=lambda x: -x[1])[:5]))
        lines.append("")
        lines.append("| 题号 | 题型 | 难度 | 知识点 |")
        lines.append("|------|------|------|--------|")
        for q in group:
            lines.append("| %s | %s | %s | %s |" % (q["id"], type_of(q), diff_name(q["difficulty"]), "、".join(kp_list(q))))
        lines.append("")
    return "\n".join(lines) + "\n"


def build_dedupe_report(pairs):
    lines = ["# 题库整理 · 相似题检测报告", ""]
    lines.append("> 依据题干归一化后的字符相似度（阈值 ≥88%）标记疑似重复题，供合并题库时参考。")
    lines.append("")
    if not pairs:
        lines.append("未发现疑似重复题。✅")
        return "\n".join(lines) + "\n"
    involved = set()
    for a, b, r in pairs:
        involved.add(a)
        involved.add(b)
    lines.append("- 疑似重复题对：**%d** 对" % len(pairs))
    lines.append("- 涉及题目：**%d** 题" % len(involved))
    lines.append("")
    for i, (a, b, r) in enumerate(pairs, 1):
        lines.append("### 第 %d 组：%s 与 %s（相似度 %.0f%%）" % (i, a, b, r * 100))
        lines.append("")
    lines.append("> 建议：保留答案/解析更完整的一题，另一题在题库中标注\"疑似重复\"或删除。")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="题库智能整理器")
    ap.add_argument("input", help="bank.json 或 题库.zip")
    ap.add_argument("--out", default=None, help="输出目录（默认与输入同目录）")
    ap.add_argument("--filter-type", default="", help="只整理指定题型，逗号分隔")
    ap.add_argument("--filter-kp", default="", help="只整理指定知识点，逗号分隔")
    ap.add_argument("--filter-diff", default="", help="只整理指定难度档：易/较易/中/较难/难，逗号分隔")
    ap.add_argument("--dedupe", action="store_true", help="开启相似题检测")
    args = ap.parse_args()

    input_path = os.path.abspath(args.input)
    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(input_path)
    org_dir = os.path.join(out_dir, "organized")
    os.makedirs(org_dir, exist_ok=True)

    bank = load_bank(input_path, out_dir)
    questions = bank.get("questions", [])
    if not questions:
        print("错误: 题库为空，请先确认题库解析结果", file=sys.stderr)
        sys.exit(1)

    ftype = {s.strip() for s in args.filter_type.split(",") if s.strip()}
    fkp = {s.strip() for s in args.filter_kp.split(",") if s.strip()}
    fdiff = {s.strip() for s in args.filter_diff.split(",") if s.strip()}
    filters_desc = []
    if ftype:
        filters_desc.append("题型 ∈ {%s}" % "、".join(sorted(ftype)))
    if fkp:
        filters_desc.append("知识点 ∈ {%s}" % "、".join(sorted(fkp)))
    if fdiff:
        filters_desc.append("难度 ∈ {%s}" % "、".join(sorted(fdiff)))

    qs = apply_filters(questions, ftype, fkp, fdiff)
    if not qs:
        print("错误: 过滤后无题目，请检查过滤条件", file=sys.stderr)
        sys.exit(1)

    files = {
        "目录总览.md": build_overview(qs, bank, filters_desc),
        "题型分类目录.md": build_type_catalog(qs),
        "知识点分类目录.md": build_kp_catalog(qs),
        "文档来源索引.md": build_source_index(qs),
    }
    if args.dedupe:
        pairs = dedupe_detect(qs)
        files["相似题检测报告.md"] = build_dedupe_report(pairs)

    for name, content in files.items():
        with open(os.path.join(org_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    print("✅ 题库整理完成：%d 道题 → 已按 题型/知识点/难度/来源文档 四维归类" % len(qs))
    print("   整理目录：%s" % org_dir)
    for name in files:
        print("   - %s" % name)
    if args.dedupe:
        print("   相似题检测：%d 对疑似重复（详见相似题检测报告）" % len(dedupe_detect(qs)))


if __name__ == "__main__":
    main()

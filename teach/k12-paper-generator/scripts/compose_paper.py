#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compose_paper.py — 智能组卷引擎

用法:
    python3 compose_paper.py <bank.json> --type daily|weekly|monthly|midterm|final|topic
        [--weak "kp1,kp2"] [--mastered "kp3"] [--kp "kpA,kpB"]
        [--count N] [--ratio 4:1:1] [--exclude id1,id2]
        [--title 标题] [--duration 30] [--subject 数学] [--grade 八年级] [--out 输出目录]

输出:
    paper_学生卷.md / paper_答案解析卷.md / paper_组卷报告.md
"""
import argparse
import datetime
import json
import os
import random
import re
import sys

SCENES = {
    "daily":    {"name": "每日打卡练习", "count": 6,  "ratio": (4, 1, 1), "duration": 30,  "note": "每日打卡建议"},
    "weekly":   {"name": "周测",         "count": 15, "ratio": (6, 6, 3), "duration": 60,  "note": None},
    "monthly":  {"name": "月测",         "count": 25, "ratio": (5, 3, 2), "duration": 90,  "note": None},
    "midterm":  {"name": "期中模拟测试", "count": 30, "ratio": (5, 3, 2), "duration": 90,  "note": "评分参考"},
    "final":    {"name": "期末模拟测试", "count": 30, "ratio": (4, 4, 2), "duration": 120, "note": "评分参考"},
    "topic":    {"name": "专题训练",     "count": 12, "ratio": (3, 5, 4), "duration": 60,  "note": None},
}
CN_NUM = "一二三四五六七八九十"


def diff_band(d):
    if d is None:
        return None
    return 0 if d <= 2 else (1 if d == 3 else 2)  # 0易 1中 2难


def parse_ratio(s):
    parts = [int(x) for x in re.split(r"[:：,，/]", s.strip())]
    if len(parts) != 3 or any(p < 0 for p in parts) or sum(parts) == 0:
        raise ValueError("难度配比格式应为 易:中:难，如 4:1:1")
    return tuple(parts)


def question_weight(q, weak, mastered, kp_scope):
    w = 1.0
    kps = set(q["knowledge_points"])
    if kps & weak:
        w *= 3.0
    if kps & mastered:
        w *= 0.5
    if kp_scope and (kps & kp_scope):
        w *= 1.5
    return w


def pick_from_bucket(bucket, n, seed):
    """桶内按权重降序分组，同权重随机取。"""
    if len(bucket) <= n:
        return list(bucket)
    rng = random.Random(seed)
    bucket = sorted(bucket, key=lambda q: -q["_w"])
    # 权重相近（差<1e-9）视为同组，组间顺序保留、组内随机
    out, i = [], 0
    remain = n
    while i < len(bucket) and remain > 0:
        j = i
        while j < len(bucket) and abs(bucket[j]["_w"] - bucket[i]["_w"]) < 1e-9:
            j += 1
        group = bucket[i:j]
        take = min(remain, len(group))
        out.extend(rng.sample(group, take))
        remain -= take
        i = j
    return out


def select_questions(questions, scene, count, ratio, weak, mastered, kp_scope, exclude, seed):
    """选题：过滤 → 加权分桶 → 按配比取题 → 借题补足。"""
    cand = []
    for q in questions:
        if q.get("untagged"):
            continue
        if q["id"] in exclude:
            continue
        if kp_scope and not (set(q["knowledge_points"]) & kp_scope):
            continue
        q = dict(q)
        q["_w"] = question_weight(q, weak, mastered, kp_scope)
        cand.append(q)
    if not cand:
        return [], [], []

    buckets = {0: [], 1: [], 2: []}
    for q in cand:
        buckets[diff_band(q["difficulty"])].append(q)

    total = sum(ratio)
    target = [max(1, round(count * r / total)) if r > 0 else 0 for r in ratio]
    # 修正总数
    while sum(target) > count:
        for i in (2, 1):
            if target[i] > 0:
                target[i] -= 1
                break
    while sum(target) < count:
        for i in (0, 1, 2):
            if len(buckets[i]) > target[i]:
                target[i] += 1
                break
        else:
            break

    chosen, borrow_notes = [], []
    for b in (0, 1, 2):
        if target[b] <= 0:
            continue
        pool = buckets[b]
        if len(pool) < target[b]:
            take = pick_from_bucket(pool, len(pool), seed)
            need = target[b] - len(pool)
            # 向相邻桶借题
            for nb in ((b + 1, b - 1) if b < 2 else (b - 1, b - 2)):
                if need <= 0:
                    break
                if 0 <= nb <= 2 and len(buckets[nb]) > target[nb]:
                    extra_n = min(need, len(buckets[nb]) - target[nb])
                    extra = pick_from_bucket([q for q in buckets[nb] if q not in take], extra_n, seed + 1)
                    take.extend(extra)
                    target[nb] += extra_n
                    need -= extra_n
            if need > 0:
                borrow_notes.append("难度档 %s 题量不足，实际少 %d 题" % (["易", "中", "难"][b], need))
            chosen.extend(take)
        else:
            chosen.extend(pick_from_bucket(pool, target[b], seed))

    # 薄弱点覆盖检查
    weak_miss = [kp for kp in weak if not any(kp in q["knowledge_points"] for q in chosen)]

    # 排序
    def sort_key(q):
        if scene in ("daily", "topic"):
            return (q["difficulty"] or 3,)
        return (TYPE_ORDER.get(q["type"], 50), q["difficulty"] or 3)

    chosen.sort(key=sort_key)
    return chosen, borrow_notes, weak_miss


def fmt_score(s):
    return str(int(s)) if s is not None and float(s).is_integer() else (str(s) if s is not None else "—")


def format_source(q, with_file=False):
    """拼装题目来源描述：如 '川沙中学 · 2024年期中试卷 · 原卷第18题'。"""
    parts = []
    if q.get("school"):
        parts.append(str(q["school"]))
    if q.get("year"):
        parts.append("%s 年" % q["year"])
    et = q.get("exam_type")
    if et:
        et = str(et)
        parts.append(et if et.endswith(("卷", "试")) else "%s试卷" % et)
    num = q.get("number")
    if num:
        parts.append("原卷第 %s 题" % num)
    if parts:
        return " · ".join(parts)
    if with_file and q.get("source"):
        return "文件 %s" % q["source"]
    return None


def source_note(q):
    """试卷中的来源标注行；无来源时提示待补充。"""
    s = format_source(q)
    return "📌 来源：%s" % s if s else "📌 来源：待补充（题库未标注）"


TYPE_ORDER = {"选择题": 0, "判断题": 1, "填空题": 2, "计算题": 3, "解答题": 4, "证明题": 5, "应用题": 6, "实验题": 7, "作图题": 8, "阅读理解": 9, "写作": 10}


def build_paper(chosen, title, subject, grade, duration, total_score, scene, note):
    today = datetime.date.today().strftime("%Y-%m-%d")
    lines = ["# %s" % title, ""]
    lines.append("**年级学科**：%s %s　|　**时长**：%d 分钟　|　**总分**：%s 分　|　**组卷日期**：%s" % (
        grade or "—", subject or "—", duration, fmt_score(total_score), today))
    lines.append("")
    lines.append("---")
    lines.append("")

    qnum = 0
    if scene in ("daily", "topic"):
        # 打卡卷/专题卷：平铺编号，难度递进
        for q in chosen:
            qnum += 1
            lines.append("> %s" % source_note(q))
            lines.append("%d.（%s 分）%s" % (qnum, fmt_score(q["score"]), q["stem"]))
            lines.append("")
    else:
        # 测试卷：按题型全局分大题，大题内难度递增
        by_type = {}
        for q in chosen:
            by_type.setdefault(q["type"] or "其他", []).append(q)
        groups = sorted(by_type.items(), key=lambda kv: TYPE_ORDER.get(kv[0], 50))
        for gi, (t, qs) in enumerate(groups):
            sec_score = sum(q["score"] or 0 for q in qs)
            per = "每题 %s 分" % fmt_score(qs[0]["score"]) if len({q["score"] for q in qs}) == 1 else "共 %s 分" % fmt_score(sec_score)
            lines.append("## %s、%s（共 %d 题，%s）" % (CN_NUM[gi] if gi < 10 else str(gi + 1), t, len(qs), per))
            lines.append("")
            for q in qs:
                qnum += 1
                lines.append("> %s" % source_note(q))
                lines.append("%d.（%s 分）%s" % (qnum, fmt_score(q["score"]), q["stem"]))
                lines.append("")
            lines.append("---")
            lines.append("")

    if scene == "daily":
        kps = sorted({kp for q in chosen for kp in q["knowledge_points"]})
        lines.append("**今日打卡建议**：预计用时 %d 分钟内完成；重点关注知识点——%s；做完先对答案，错题标记出来，明天打卡卷会安排同类题巩固。" % (duration, "、".join(kps) if kps else "—"))
    elif note == "评分参考":
        lines.append("**评分参考**：请按上海本地考试评分标准给分；建议完成后对照目标校分数线定位薄弱环节。")
    if lines[-1]:
        lines.append("")
    return "\n".join(lines)


def build_answer_sheet(chosen, title):
    lines = ["# %s — 答案解析卷" % title, ""]
    lines.append("| 题号 | 答案 | 题目来源 | 解析 |")
    lines.append("|------|------|---------|------|")
    for i, q in enumerate(chosen, 1):
        ans = (q["answer"] or "❓待补充").replace("\n", " ")
        expl = (q["explanation"] or "解析待补充").replace("\n", " ")
        src = format_source(q, with_file=True) or "待补充"
        lines.append("| %d | %s | %s | %s |" % (i, ans, src, expl))
    lines.append("")
    return "\n".join(lines)


def build_report(chosen, bank_questions, title, scene_name, ratio, weak, mastered, borrow_notes, weak_miss, no_answer):
    total = len(chosen)
    total_score = sum(q["score"] or 0 for q in chosen)
    bands = [diff_band(q["difficulty"]) for q in chosen]
    band_names = ["易（1-2）", "中（3）", "难（4-5）"]
    ratio_total = sum(ratio)

    lines = ["# 组卷报告：%s" % title, ""]
    lines.append("**组卷时间**：%s　|　**场景**：%s　|　**题量**：%d　|　**总分**：%s" % (
        datetime.date.today().strftime("%Y-%m-%d"), scene_name, total, fmt_score(total_score)))
    lines.append("")
    lines.append("## 一、选题清单")
    lines.append("| 序号 | 题目ID | 题型 | 难度 | 知识点 | 分值 | 有答案 | 题目来源 |")
    lines.append("|------|--------|------|------|--------|------|--------|---------|")
    for i, q in enumerate(chosen, 1):
        lines.append("| %d | %s | %s | %s | %s | %s | %s | %s |" % (
            i, q["id"], q["type"], q["difficulty"], "、".join(q["knowledge_points"]),
            fmt_score(q["score"]), "✅" if q["answer"] else "❌",
            format_source(q, with_file=True) or "待补充"))
    lines.append("")
    lines.append("## 二、难度分布")
    lines.append("| 难度档 | 题数 | 占比 | 目标配比 |")
    lines.append("|--------|------|------|---------|")
    for b in (0, 1, 2):
        n = bands.count(b)
        lines.append("| %s | %d | %.0f%% | %.0f%% |" % (band_names[b], n, 100.0 * n / max(total, 1), 100.0 * ratio[b] / ratio_total))
    lines.append("")
    lines.append("## 三、知识点覆盖")
    lines.append("| 知识点 | 题数 | 分值占比 | 状态 |")
    lines.append("|--------|------|---------|------|")
    kp_stat = {}
    for q in chosen:
        sc = q["score"] or 0
        for kp in q["knowledge_points"]:
            s = kp_stat.setdefault(kp, [0, 0])
            s[0] += 1
            s[1] += sc
    for kp, (n, sc) in sorted(kp_stat.items(), key=lambda x: -x[1][1]):
        status = "薄弱点（加权）" if kp in weak else ("已掌握（降权）" if kp in mastered else "常规")
        lines.append("| %s | %d | %.0f%% | %s |" % (kp, n, 100.0 * sc / max(total_score, 1), status))
    lines.append("")
    lines.append("## 四、选题逻辑说明")
    logic = []
    if weak:
        logic.append("- 薄弱知识点（%s）选题权重 ×3，优先覆盖" % "、".join(sorted(weak)))
    if mastered:
        logic.append("- 已掌握知识点（%s）权重 ×0.5，降低重复" % "、".join(sorted(mastered)))
    logic.append("- 难度配比目标 易:中:难 = %d:%d:%d" % ratio)
    logic.append("- 同权重题目随机选取，重跑一次可获得同结构的换题版本")
    for b in borrow_notes:
        logic.append("- ⚠️ %s" % b)
    for kp in weak_miss:
        logic.append("- ⚠️ 薄弱点「%s」在当前可选题中无题目覆盖，建议补充该知识点题目" % kp)
    lines.extend(logic)
    lines.append("")
    lines.append("## 五、无答案题目提醒")
    if no_answer:
        lines.append("共 %d 题无答案（题号：%s），建议补充答案后交给学生使用。" % (len(no_answer), "、".join(str(i + 1) for i, q in enumerate(chosen) if not q["answer"])))
    else:
        lines.append("全部题目均有答案。")
    lines.append("")
    src_missing = [i + 1 for i, q in enumerate(chosen) if not format_source(q)]
    lines.append("## 六、题目来源标注情况")
    lines.append("")
    lines.append("- 本卷共 %d 题，**已标注来源 %d 题**（学校 · 年份 · 试卷类型 · 原卷题号，详见选题清单）" % (
        total, total - len(src_missing)))
    if src_missing:
        lines.append("- ⚠️ %d 题来源待补充（题号：%s），建议在题库中按 `【学校：X】【试卷类型：X】【年份：X】【题号：X】` 标注后重新解析，即可自动溯源。" % (
            len(src_missing), "、".join(str(i) for i in src_missing)))
    else:
        lines.append("- 所有题目来源完整，可直接追溯出处。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="智能组卷引擎")
    ap.add_argument("bank")
    ap.add_argument("--type", required=True, choices=list(SCENES))
    ap.add_argument("--weak", default="")
    ap.add_argument("--mastered", default="")
    ap.add_argument("--kp", default="")
    ap.add_argument("--count", type=int, default=None)
    ap.add_argument("--ratio", default=None)
    ap.add_argument("--exclude", default="")
    ap.add_argument("--title", default=None)
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--subject", default=None)
    ap.add_argument("--grade", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.bank, encoding="utf-8") as f:
        bank = json.load(f)
    questions = bank.get("questions", [])
    usable = [q for q in questions if not q.get("untagged")]
    if not usable:
        print("错误: 题库中没有可组卷的已标注题目，请先检查 bank_stats.md", file=sys.stderr)
        sys.exit(1)

    scene = SCENES[args.type]
    count = args.count or min(scene["count"], len(usable))
    ratio = parse_ratio(args.ratio) if args.ratio else scene["ratio"]
    duration = args.duration or scene["duration"]
    subject = args.subject or bank.get("subject") or ""
    grade = args.grade or bank.get("grade") or ""
    title = args.title or "%s %s%s" % (grade, subject, scene["name"])
    seed = args.seed if args.seed is not None else datetime.date.today().toordinal()

    weak = {s.strip() for s in re.split(r"[,，、;；]", args.weak) if s.strip()}
    mastered = {s.strip() for s in re.split(r"[,，、;；]", args.mastered) if s.strip()}
    kp_scope = {s.strip() for s in re.split(r"[,，、;；]", args.kp) if s.strip()} or None
    exclude = {s.strip() for s in re.split(r"[,，、;；]", args.exclude) if s.strip()}

    if kp_scope:
        covered = {kp for q in usable for kp in q["knowledge_points"]}
        missing = kp_scope - covered
        if missing:
            print("错误: 指定知识点在题库中无题目：%s" % "、".join(sorted(missing)), file=sys.stderr)
            sys.exit(1)

    chosen, borrow_notes, weak_miss = select_questions(
        usable, args.type, count, ratio, weak, mastered, kp_scope, exclude, seed)

    if not chosen:
        print("错误: 没有符合条件的题目（检查 --exclude / --kp 过滤条件）", file=sys.stderr)
        sys.exit(1)

    total_score = sum(q["score"] or 0 for q in chosen)
    no_answer = [q for q in chosen if not q["answer"]]

    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(os.path.abspath(args.bank))
    os.makedirs(out_dir, exist_ok=True)

    paper = build_paper(chosen, title, subject, grade, duration, total_score, args.type, scene["note"])
    answer = build_answer_sheet(chosen, title)
    report = build_report(chosen, questions, title, scene["name"], ratio, weak, mastered, borrow_notes, weak_miss, no_answer)

    p1 = os.path.join(out_dir, "paper_学生卷.md")
    p2 = os.path.join(out_dir, "paper_答案解析卷.md")
    p3 = os.path.join(out_dir, "paper_组卷报告.md")
    for path, content in ((p1, paper), (p2, answer), (p3, report)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content + "\n")

    band_names = ["易", "中", "难"]
    bands = [diff_band(q["difficulty"]) for q in chosen]
    dist = " / ".join("%s%d题" % (band_names[b], bands.count(b)) for b in (0, 1, 2))
    print("✅ 组卷完成：%s" % title)
    print("   题量 %d 题，总分 %s 分，时长 %d 分钟，难度分布 %s" % (len(chosen), fmt_score(total_score), duration, dist))
    if no_answer:
        print("   ⚠️ %d 题无答案" % len(no_answer))
    print("   学生卷：%s" % p1)
    print("   答案卷：%s" % p2)
    print("   组卷报告：%s" % p3)


if __name__ == "__main__":
    main()

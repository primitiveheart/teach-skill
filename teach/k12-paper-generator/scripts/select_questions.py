#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""select_questions.py — 按学情挑题整理器

用法:
    python3 select_questions.py <bank.json> --weak "知识点1,知识点2"
        [--grade 八年级] [--subject 数学] [--student 小明]
        [--mastered "知识点3,知识点4"] [--level 基础|进阶|冲刺]
        [--score 75] [--per-kp 5] [--exclude id1,id2]
        [--title 整理册标题] [--out 输出目录]

功能:
    基于学生画像（年级 / 薄弱知识点 / 已掌握知识点 / 当前水平）从题库中
    智能挑题，按知识点分组生成"个性化整理册"，区别于标准试卷：
    - 学生版：按薄弱知识点分章节，组内 基础→中档→挑战 难度递进
    - 答案版：与章节一一对应，含答案与解析
    - 整理报告：挑选逻辑、知识点覆盖、难度配比、题库缺口提示
"""
import argparse
import datetime
import json
import os
import random
import re
import sys

CN_NUM = "一二三四五六七八九十"
LEVELS = {
    "基础": (5, 3, 2),   # 易:中:难
    "进阶": (3, 5, 2),
    "冲刺": (2, 3, 5),
}
DIFF_NAME = {1: "易", 2: "较易", 3: "中", 4: "较难", 5: "难"}


def split_csv(s):
    if not s:
        return []
    return [x.strip() for x in re.split(r"[,，、;；]", s) if x.strip()]


def diff_band(d):
    if d is None:
        return None
    return 0 if d <= 2 else (1 if d == 3 else 2)


def diff_name(d):
    return DIFF_NAME.get(d, "未标注")


def level_tag(d):
    return "基础" if d <= 2 else ("中档" if d == 3 else "挑战")


def score_to_level(score):
    if score >= 80:
        return "冲刺"
    if score >= 60:
        return "进阶"
    return "基础"


def kp_match(q, target):
    """知识点匹配：精确相等或双向子串包含（长度>1 防误伤）。"""
    for k in q["knowledge_points"]:
        if k == target:
            return True
        if len(k) > 1 and len(target) > 1 and (target in k or k in target):
            return True
    return False


def pick_from_pool(pool, ratio, n, seed):
    """章节内按 易:中:难 配比取题；某档不足向相邻档借。返回 (chosen, borrow_notes)。"""
    buckets = {0: [], 1: [], 2: []}
    for q in pool:
        b = diff_band(q["difficulty"])
        if b is not None:
            buckets[b].append(q)
    total = sum(ratio)
    target = [max(1, round(n * r / total)) if r > 0 else 0 for r in ratio]
    while sum(target) > n:
        for i in (2, 1):
            if target[i] > 0:
                target[i] -= 1
                break
    while sum(target) < n:
        for i in (0, 1, 2):
            if len(buckets[i]) > target[i]:
                target[i] += 1
                break
        else:
            break

    rng = random.Random(seed)
    chosen, notes = [], []
    for b in (0, 1, 2):
        if target[b] <= 0:
            continue
        pool_b = sorted([q for q in buckets[b] if q not in chosen], key=lambda q: (q["difficulty"], q["id"]))
        if len(pool_b) >= target[b]:
            chosen.extend(rng.sample(pool_b, target[b]))
            continue
        chosen.extend(pool_b)
        need = target[b] - len(pool_b)
        for nb in (1, 0, 2):
            if nb == b or need <= 0:
                continue
            spare = [q for q in buckets[nb] if q not in chosen]
            take = min(need, len(spare))
            if take > 0:
                chosen.extend(rng.sample(spare, take))
                notes.append("%s档题量不足，从%s档借题 %d 道" % (
                    ["基础", "中档", "挑战"][b], ["基础", "中档", "挑战"][nb], take))
                need -= take
    return chosen, notes


def build_student_book(chapters, mastered_sec, profile_lines, title, grade, subject, student, note):
    today = datetime.date.today().strftime("%Y-%m-%d")
    lines = ["# %s" % title, ""]
    head = "> 为「%s」定制" % student
    if grade:
        head += " · %s" % grade
    if subject:
        head += " %s" % subject
    head += "　|　整理日期：%s" % today
    lines.append(head)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 本次整理说明")
    lines.append("")
    for p in profile_lines:
        lines.append("- %s" % p)
    lines.append("- 每个薄弱知识点按「基础 → 中档 → 挑战」递进编排，先巩固再提升")
    lines.append("- 建议先独立完成，错题在题号旁做记号，讲评时重点分析")
    lines.append("")
    lines.append("---")
    lines.append("")

    qnum = 0
    for gi, (kp, qs) in enumerate(chapters, 1):
        n_easy = sum(1 for q in qs if q["difficulty"] and q["difficulty"] <= 2)
        n_mid = sum(1 for q in qs if q["difficulty"] == 3)
        n_hard = sum(1 for q in qs if q["difficulty"] and q["difficulty"] >= 4)
        total_score = sum(q["score"] or 0 for q in qs)
        sec = "## %s、%s（薄弱点 · %d 题 · 基础 %d / 中档 %d / 挑战 %d" % (
            CN_NUM[gi - 1] if gi <= 10 else gi, kp, len(qs), n_easy, n_mid, n_hard)
        if total_score:
            sec += " · 共 %s 分" % fmt_score(total_score)
        sec += "）"
        lines.append(sec)
        lines.append("")
        for q in qs:
            qnum += 1
            lines.append("> %s" % source_note(q))
            lines.append("%d. **[%s]**（难度%s%s）%s" % (
                qnum, level_tag(q["difficulty"]), diff_name(q["difficulty"]),
                " · %s 分" % fmt_score(q["score"]) if q["score"] else "",
                q["stem"]))
            lines.append("")
        lines.append("---")
        lines.append("")

    if mastered_sec:
        lines.append("## 复习巩固（已掌握知识点抽查）")
        lines.append("")
        lines.append("> 已掌握知识点各配 1 题保持手感，不设题量压力。")
        lines.append("")
        for kp, qs in mastered_sec:
            lines.append("### %s" % kp)
            lines.append("")
            for q in qs:
                qnum += 1
                lines.append("> %s" % source_note(q))
                lines.append("%d. **[%s]**（难度%s）%s" % (
                    qnum, level_tag(q["difficulty"]), diff_name(q["difficulty"]), q["stem"]))
                lines.append("")

    lines.append("---")
    lines.append("")
    if note:
        lines.append("> 💡 %s" % note)
    lines.append("")
    lines.append("> 完成情况：基础题正确率 / 中档题正确率 / 挑战题正确率（下次整理时告诉我，我会动态调整难度）")
    return "\n".join(lines) + "\n"


def build_answer_book(chapters, mastered_sec, title):
    today = datetime.date.today().strftime("%Y-%m-%d")
    lines = ["# %s · 答案解析" % title, ""]
    lines.append("> 与整理册题号一一对应　|　整理日期：%s" % today)
    lines.append("")
    lines.append("---")
    lines.append("")

    qnum = 0
    for gi, (kp, qs) in enumerate(chapters, 1):
        lines.append("## %s、%s" % (CN_NUM[gi - 1] if gi <= 10 else gi, kp))
        lines.append("")
        for q in qs:
            qnum += 1
            lines.append("**%d.（%s）%s**" % (qnum, level_tag(q["difficulty"]), q["stem"]))
            lines.append("")
            lines.append("- **答案**：%s" % (q["answer"] or "答案待补充"))
            lines.append("- **解析**：%s" % (q["explanation"] or "解析待补充"))
            lines.append("- **来源**：%s" % (format_source(q, with_file=True) or "待补充（题库未标注）"))
            lines.append("")
        lines.append("---")
        lines.append("")

    if mastered_sec:
        lines.append("## 复习巩固（已掌握知识点抽查）")
        lines.append("")
        for kp, qs in mastered_sec:
            lines.append("### %s" % kp)
            lines.append("")
            for q in qs:
                qnum += 1
                lines.append("**%d. %s**" % (qnum, q["stem"]))
                lines.append("")
                lines.append("- **答案**：%s" % (q["answer"] or "答案待补充"))
                lines.append("- **解析**：%s" % (q["explanation"] or "解析待补充"))
                lines.append("- **来源**：%s" % (format_source(q, with_file=True) or "待补充（题库未标注）"))
                lines.append("")
    return "\n".join(lines) + "\n"


def build_report(profile_lines, chapters, mastered_sec, gaps, borrow_notes, all_ids, questions):
    lines = ["# 整理说明报告", ""]
    lines.append("## 学生画像")
    lines.append("")
    for p in profile_lines:
        lines.append("- %s" % p)
    lines.append("")
    lines.append("## 挑选逻辑")
    lines.append("")
    lines.append("1. 只从**已标注**题目中挑选（缺题型/难度/知识点标签的题目不入选）")
    lines.append("2. 薄弱知识点按「基础→中档→挑战」递进配题，先保正确率再上强度")
    lines.append("3. 已掌握知识点各抽查 1 题，保持手感、不做题海")
    lines.append("4. 已做过的题目（--exclude）自动排除，支持连续多轮整理不重题")
    lines.append("")
    lines.append("## 知识点覆盖")
    lines.append("")
    lines.append("| 知识点 | 性质 | 题数 | 难度构成（易/中/难） | 题目 id |")
    lines.append("|--------|------|------|---------------------|---------|")
    for kp, qs in chapters:
        n_easy = sum(1 for q in qs if q["difficulty"] and q["difficulty"] <= 2)
        n_mid = sum(1 for q in qs if q["difficulty"] == 3)
        n_hard = sum(1 for q in qs if q["difficulty"] and q["difficulty"] >= 4)
        lines.append("| %s | 薄弱点 | %d | %d/%d/%d | %s |" % (
            kp, len(qs), n_easy, n_mid, n_hard, "、".join(q["id"] for q in qs)))
    for kp, qs in mastered_sec:
        lines.append("| %s | 已掌握·抽查 | %d | — | %s |" % (kp, len(qs), "、".join(q["id"] for q in qs)))
    lines.append("")
    lines.append("### 结构偏差说明")
    if borrow_notes:
        for n in borrow_notes:
            lines.append("- %s" % n)
    else:
        lines.append("- 无（各难度档题量充足）")
    lines.append("")
    lines.append("### 题库缺口提示")
    if gaps:
        lines.append("以下薄弱知识点在题库中**没有找到可用的题目**，本次未能覆盖：")
        for g in gaps:
            lines.append("- %s" % g)
        lines.append("")
        lines.append("建议补充对应题源后重新整理。")
    else:
        lines.append("- 无（所有薄弱知识点均已覆盖）✅")
    lines.append("")
    lines.append("## 题库总体情况")
    lines.append("")
    lines.append("- 题库题量：**%d**（已标注 %d / 未标注 %d）" % (
        len(questions),
        sum(1 for q in questions if not q["untagged"]),
        sum(1 for q in questions if q["untagged"])))
    lines.append("")
    lines.append("## 来源标注情况")
    lines.append("")
    picked = [q for _, qs in chapters for q in qs] + [q for _, qs in mastered_sec for q in qs]
    src_ok = sum(1 for q in picked if format_source(q))
    lines.append("- 本次整理 **%d** 题，**已标注来源 %d 题**（学校 · 年份 · 试卷类型 · 原卷题号）" % (len(picked), src_ok))
    if src_ok < len(picked):
        lines.append("- ⚠️ %d 题来源待补充（见整理册中的\"来源：待补充\"标注），建议在题库中按 `【学校：X】【试卷类型：X】【年份：X】【题号：X】` 标注后重新解析。" % (len(picked) - src_ok))
    else:
        lines.append("- 所有题目来源完整，每道题均可追溯出处。")
    lines.append("")
    lines.append("## 可复用建议")
    lines.append("")
    if all_ids:
        lines.append("下次整理（如 Day2 / 第二轮）可直接排除本次题目避免重复：")
        lines.append("")
        lines.append("```bash")
        lines.append("python3 scripts/select_questions.py bank.json --weak \"%s\" --exclude %s" % (
            ",".join(sorted({kp for kp, _ in chapters})) if chapters else "薄弱点1",
            ",".join(all_ids)))
        lines.append("```")
    lines.append("")
    lines.append("> 学情动态调整规则：本次正确率 <60% → 下次降一档难度；正确率 >80% → 下次升一档并减少基础题。")
    return "\n".join(lines) + "\n"


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
    """整理册中的来源标注行；无来源时提示待补充。"""
    s = format_source(q)
    return "📌 来源：%s" % s if s else "📌 来源：待补充（题库未标注）"


def main():
    ap = argparse.ArgumentParser(description="按学情挑题整理器")
    ap.add_argument("bank_path")
    ap.add_argument("--weak", required=True, help="薄弱知识点，逗号分隔（必填）")
    ap.add_argument("--grade", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--student", default="同学")
    ap.add_argument("--mastered", default="", help="已掌握知识点，逗号分隔（抽查用）")
    ap.add_argument("--level", choices=["基础", "进阶", "冲刺"], default=None)
    ap.add_argument("--score", type=float, default=None, help="近期考试分数（百分制），可自动推断水平")
    ap.add_argument("--per-kp", type=int, default=5, help="每个薄弱知识点配题数（默认 5）")
    ap.add_argument("--exclude", default="", help="排除已做题目 id，逗号分隔")
    ap.add_argument("--title", default="")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    bank_path = os.path.abspath(args.bank_path)
    if not os.path.isfile(bank_path):
        print("错误: 找不到文件 %s" % bank_path, file=sys.stderr)
        sys.exit(1)
    with open(bank_path, encoding="utf-8") as f:
        bank = json.load(f)
    questions = bank.get("questions", [])
    if not questions:
        print("错误: 题库为空", file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(bank_path)
    os.makedirs(out_dir, exist_ok=True)

    weak_list = split_csv(args.weak)
    mastered_list = split_csv(args.mastered)
    exclude_set = set(split_csv(args.exclude))

    level = args.level or (score_to_level(args.score) if args.score is not None else "基础")
    ratio = LEVELS[level]

    cand = [q for q in questions if not q["untagged"] and q["id"] not in exclude_set]

    chapters, borrow_notes, gaps, all_ids = [], [], [], []
    seed = hash((args.weak, args.exclude)) & 0xffffffff
    for w in weak_list:
        pool = [q for q in cand if kp_match(q, w) and q not in sum((c[1] for c in chapters), [])]
        if not pool:
            gaps.append(w)
            continue
        picked, notes = pick_from_pool(pool, ratio, args.per_kp, seed)
        chapters.append((w, picked))
        borrow_notes.extend(notes)
        all_ids.extend(q["id"] for q in picked)

    mastered_sec = []
    if mastered_list:
        used = {q["id"] for _, qs in chapters for q in qs}
        for m in mastered_list:
            pool = [q for q in cand if kp_match(q, m) and q["id"] not in used]
            if not pool:
                continue
            picked, _ = pick_from_pool(pool, ratio, 1, seed)
            if picked:
                mastered_sec.append((m, picked))
                all_ids.extend(q["id"] for q in picked)

    if not chapters and not mastered_sec:
        print("错误: 没有为任何知识点找到可用题目。题库中已有的知识点：%s" % (
            "、".join(sorted({k for q in questions for k in q["knowledge_points"]})[:20])), file=sys.stderr)
        sys.exit(1)

    grade = args.grade or bank.get("grade") or ""
    subject = args.subject or bank.get("subject") or ""
    title = args.title or ("个性化整理册%s" % (" · " + subject if subject else ""))
    student = args.student or "同学"

    profile_lines = []
    if weak_list:
        profile_lines.append("薄弱知识点：**%s**" % "、".join(weak_list))
    if mastered_list:
        profile_lines.append("已掌握知识点（抽查保持）：**%s**" % "、".join(mastered_list))
    if args.score is not None:
        profile_lines.append("近期成绩：**%s 分** → 当前水平「%s」" % (args.score, level))
    else:
        profile_lines.append("当前水平：「%s」（难度配比 易:中:难 = %d:%d:%d）" % (level, *ratio))
    if exclude_set:
        profile_lines.append("已排除已做题目 **%d** 道（--exclude）" % len(exclude_set))

    note = "薄弱点建议连续巩固 3-5 天：正确率稳定后，下次整理可把该知识点移入\"已掌握\"。"
    if len(weak_list) > 1:
        note += "一次聚焦 2-3 个薄弱点即可，贪多嚼不烂。"

    student_book = build_student_book(chapters, mastered_sec, profile_lines, title, grade, subject, student, note)
    answer_book = build_answer_book(chapters, mastered_sec, title)
    report = build_report(profile_lines, chapters, mastered_sec, gaps, borrow_notes, all_ids, questions)

    paths = {
        "整理册_学生版.md": student_book,
        "整理册_答案版.md": answer_book,
        "整理报告.md": report,
    }
    for name, content in paths.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    total_picked = len(all_ids)
    print("✅ 整理完成：共挑 %d 题（薄弱点 %d 个 + 抽查 %d 题）" % (
        total_picked, len(chapters), len(mastered_sec)))
    if gaps:
        print("⚠️ 未覆盖薄弱点（题库缺题）：%s" % "、".join(gaps))
    print("   学生版：%s" % os.path.join(out_dir, "整理册_学生版.md"))
    print("   答案版：%s" % os.path.join(out_dir, "整理册_答案版.md"))
    print("   报告：  %s" % os.path.join(out_dir, "整理报告.md"))


if __name__ == "__main__":
    main()

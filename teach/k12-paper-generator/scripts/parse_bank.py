#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_bank.py — 题库压缩包解析器

用法:
    python3 parse_bank.py <题库.zip> [--out <输出目录>]

功能:
    1. 解压 zip 题库（支持嵌套目录）
    2. 解析 .json / .txt / .md / .docx 题目文件
    3. 规范化为统一 schema（见 references/bank-format-spec.md）
    4. 输出 bank.json（结构化题库）与 bank_stats.md（统计报告）
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

DIFF_WORDS = {"易": 1, "较易": 2, "简单": 1, "中": 3, "中等": 3, "较难": 4, "难": 5, "困难": 5}
DEFAULT_SCORE = {"选择题": 4, "填空题": 4, "判断题": 3, "解答题": 8}
# 题号行: "1." "1、" "1）" "【题1】" "题1:" 等
QNUM_RE = re.compile(r"^\s*(?:【)?(?:题)?(\d{1,3})(?:】)?\s*[\.、．\)）:：]\s*\S")
# 标签: 【题型：X】【知识点：X,Y】【难度：X】【分值：X】【答案：X】/【答案】X【解析：X】/【解析】X
# 来源标签: 【学校：X】【试卷类型：X】【年份：X】【题号：X】（含别名 卷型/学年/原题号/原卷题号）
# 年级/学科标签: 【年级：X】【学科：X】
TAG_RES = {
    "type": re.compile(r"【\s*题型\s*[:：]?\s*([^】]+)】"),
    "kp": re.compile(r"【\s*知识点\s*[:：]?\s*([^】]+)】"),
    "diff": re.compile(r"【\s*难度\s*[:：]?\s*([^】]+)】"),
    "score": re.compile(r"【\s*分值\s*[:：]?\s*([^】]+)】"),
    "answer": re.compile(r"【\s*答案\s*[:：]?\s*([^】]*)】"),
    "expl": re.compile(r"【\s*解析\s*[:：]?\s*([^】]*)】"),
    "school": re.compile(r"【\s*(?:学校|出处|来源学校)\s*[:：]?\s*([^】]+)】"),
    "exam_type": re.compile(r"【\s*(?:试卷类型|卷型|试卷名称|考试类型)\s*[:：]?\s*([^】]+)】"),
    "year": re.compile(r"【\s*(?:年份|学年|考试年份)\s*[:：]?\s*([^】]+)】"),
    "number": re.compile(r"【\s*(?:题号|原题号|原卷题号)\s*[:：]?\s*([^】]+)】"),
    "grade": re.compile(r"【\s*年级\s*[:：]?\s*([^】]+)】"),
    "subject": re.compile(r"【\s*(?:学科|科目)\s*[:：]?\s*([^】]+)】"),
}
ANSWER_LINE = re.compile(r"^\s*(?:【\s*)?答案\s*(?:[】\]]\s*)?[:：]?\s*\S")
EXPL_LINE = re.compile(r"^\s*(?:【\s*)?解析\s*(?:[】\]]\s*)?[:：]?\s*\S")
ANSWER_VAL = re.compile(r"答案\s*(?:[】\]]\s*)?[:：]?\s*(.*)")
EXPL_VAL = re.compile(r"解析\s*(?:[】\]]\s*)?[:：]?\s*(.*)")
OPTION_LINE = re.compile(r"^\s*[A-D][\.、．\)）]")


def normalize_diff(v):
    if v is None or v == "":
        return None
    s = str(v).strip()
    if s in DIFF_WORDS:
        return DIFF_WORDS[s]
    m = re.search(r"\d", s)
    if m:
        try:
            d = int(float(s))
            return min(5, max(1, d))
        except ValueError:
            return None
    return None


def split_kp(v):
    if not v:
        return []
    parts = re.split(r"[,，、;；/]", str(v))
    return [p.strip() for p in parts if p.strip()]


def norm_score(v, qtype):
    if v is not None:
        try:
            return float(re.sub(r"[^\d\.]", "", str(v)) or "")
        except ValueError:
            pass
    return DEFAULT_SCORE.get(qtype or "", None)


def make_question(qid, stem_lines, tags, source):
    stem = "\n".join(stem_lines).strip()
    qtype = (tags.get("type") or "").strip() or None
    diff = normalize_diff(tags.get("diff"))
    kps = split_kp(tags.get("kp"))
    score = norm_score(tags.get("score"), qtype)
    answer = (tags.get("answer") or "").strip() or None
    expl = (tags.get("expl") or "").strip() or None
    src = infer_source_from_filename(source)
    for key in ("school", "exam_type", "year", "number"):
        v = (tags.get(key) or "").strip()
        if v:
            src[key] = v
    g_fn, s_fn = infer_grade_subject_from_filename(source)
    grade = (tags.get("grade") or "").strip() or g_fn
    subject = (tags.get("subject") or "").strip() or s_fn
    return {
        "id": qid,
        "type": qtype,
        "stem": stem,
        "difficulty": diff,
        "knowledge_points": kps,
        "score": score,
        "answer": answer,
        "explanation": expl,
        "source": source,
        "school": src.get("school"),
        "exam_type": src.get("exam_type"),
        "year": src.get("year"),
        "number": src.get("number"),
        "grade": grade,
        "subject": subject,
        "untagged": qtype is None or diff is None or not kps,
    }


# 文件名中常见的试卷类型词
EXAM_TYPE_WORDS = ["期中", "期末", "模拟", "升学", "月考", "单元测", "周测", "一模", "二模", "三模", "中考", "高考", "会考", "小升初", "入学", "阶段测"]
# 学校名后缀，用于从文件名提取（须先剥离年份 token，避免"2024年川沙中学"被整体吞入）
SCHOOL_SUFFIX = re.compile(r"([\u4e00-\u9fa5A-Za-z]{2,10}?(?:中学|小学|学校|附中|实验学校|学院|职校))")
# 年级关键词（从具体到宽泛，匹配时取首个命中）
GRADE_KEYWORDS = ["预备班", "预初", "六年级", "七年级", "八年级", "九年级", "初一", "初二", "初三",
                  "高一", "高二", "高三", "一年级", "二年级", "三年级", "四年级", "五年级",
                  "小学", "初中", "高中"]
# 学科关键词（从文件名匹配）
SUBJECT_KEYWORDS = ["语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理",
                    "道法", "道德与法治", "科学", "信息科技", "信息技术", "体育", "音乐", "美术"]


def infer_grade_subject_from_filename(fn):
    """从文件名推断年级与学科：如 '六年级数学_有理数.txt' → ('六年级', '数学')。"""
    base = os.path.splitext(os.path.basename(fn))[0]
    grade = next((g for g in GRADE_KEYWORDS if g in base), None)
    subject = next((s for s in SUBJECT_KEYWORDS if s in base), None)
    return grade, subject


def infer_source_from_filename(fn):
    """从文件名推断来源：如 '2024年川沙中学初二数学期中试卷.txt'。"""
    base = os.path.splitext(os.path.basename(fn))[0]
    src = {"school": None, "exam_type": None, "year": None, "number": None}
    if not base:
        return src
    m = re.search(r"(19|20)\d{2}", base)
    if m:
        src["year"] = m.group(0)
    clean = re.sub(r"(19|20)\d{2}", "", base).lstrip("年").strip("-_ ")
    m = SCHOOL_SUFFIX.search(clean)
    if m:
        src["school"] = m.group(1)
    for word in EXAM_TYPE_WORDS:
        if word in base:
            src["exam_type"] = word
            break
    return src


def parse_text_bank(text, source):
    """启发式解析文本题库。"""
    questions = []
    cur_lines, cur_tags, in_q = [], {}, False
    cur_answer_lines, cur_expl_lines = [], []

    def flush():
        if not in_q or not (cur_lines or cur_tags):
            return
        tags = dict(cur_tags)
        if cur_answer_lines:
            tags["answer"] = " ".join(cur_answer_lines)
        if cur_expl_lines:
            tags["expl"] = " ".join(cur_expl_lines)
        qid = "q%03d" % (len(questions) + 1)
        questions.append(make_question(qid, cur_lines, tags, source))

    for raw in text.splitlines():
        line = raw.rstrip()
        if QNUM_RE.match(line) and not ANSWER_LINE.match(line) and not EXPL_LINE.match(line):
            flush()
            cur_lines, cur_tags = [], {}
            cur_answer_lines, cur_expl_lines = [], []
            in_q = True
            head = line
            # 行内标签
            for key, rx in TAG_RES.items():
                m = rx.search(head)
                if m:
                    cur_tags[key] = m.group(1)
                    head = rx.sub("", head, count=1).rstrip()
            if not cur_tags.get("answer"):
                m = re.match(r"^\s*(?:【)?(?:题)?\d{1,3}(?:】)?\s*[\.、．\)）:：]", head)
                head = head[m.end():].strip() if m else head.strip()
            if head:
                cur_lines.append(head)
            continue
        if not in_q:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        # 标签行（可能一行多个标签，含来源/年级/学科标签）
        if any(rx.search(stripped) for k, rx in TAG_RES.items() if k in ("type", "kp", "diff", "score", "school", "exam_type", "year", "number", "grade", "subject")):
            for key, rx in TAG_RES.items():
                for m in rx.finditer(stripped):
                    cur_tags[key] = m.group(1)
            continue
        if ANSWER_LINE.match(stripped) or TAG_RES["answer"].search(stripped):
            m = ANSWER_VAL.search(stripped)
            if m and m.group(1).strip():
                cur_answer_lines.append(m.group(1).strip())
            continue
        if EXPL_LINE.match(stripped) or TAG_RES["expl"].search(stripped):
            m = EXPL_VAL.search(stripped)
            if m and m.group(1).strip():
                cur_expl_lines.append(m.group(1).strip())
            continue
        cur_lines.append(stripped)
    flush()
    return questions


def parse_json_bank(data, source, meta=None):
    """解析 JSON 题库（对象或数组，字段别名兼容）。meta 提供文件级 subject/grade 兜底。"""
    meta = meta or {}
    if isinstance(data, dict):
        items = data.get("questions") or data.get("items") or data.get("data") or []
        meta = {
            "subject": data.get("subject") or meta.get("subject"),
            "grade": data.get("grade") or meta.get("grade"),
        }
    else:
        items = data
    questions = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        stem = item.get("stem") or item.get("question") or item.get("body") or ""
        qtype = item.get("type") or item.get("question_type") or None
        kps = item.get("knowledge_points")
        if kps is None:
            kps = item.get("kp") or item.get("tags") or item.get("points") or []
        if isinstance(kps, str):
            kps = split_kp(kps)
        diff = normalize_diff(item.get("difficulty", item.get("level")))
        score = norm_score(item.get("score", item.get("points")), qtype)
        g_subject = item.get("subject") or meta.get("subject")
        g_grade = item.get("grade") or meta.get("grade")
        src = infer_source_from_filename(source)
        for key, aliases in (("school", ("school", "school_name")),
                             ("exam_type", ("exam_type", "paper_type")),
                             ("year", ("year", "paper_year")),
                             ("number", ("number", "original_no", "qno"))):
            v = item.get(key)
            if v in (None, ""):
                for a in aliases:
                    v = item.get(a)
                    if v not in (None, ""):
                        break
            if v not in (None, ""):
                src[key] = str(v).strip()
        questions.append({
            "id": str(item.get("id") or "q%03d" % (i + 1)),
            "type": qtype,
            "stem": str(stem),
            "difficulty": diff,
            "knowledge_points": [str(k).strip() for k in kps if str(k).strip()],
            "score": score,
            "answer": item.get("answer") if item.get("answer") not in (None, "") else None,
            "explanation": item.get("explanation") or item.get("analysis") or None,
            "source": source,
            "school": src.get("school"),
            "exam_type": src.get("exam_type"),
            "year": src.get("year"),
            "number": src.get("number"),
            "grade": g_grade,
            "subject": g_subject,
            "untagged": qtype is None or diff is None or not kps,
        })
    return questions, meta


def docx_to_text(path):
    """纯标准库提取 docx 正文文本。"""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    lines = []
    for p in root.iter("{%s}p" % ns["w"]):
        texts = [t.text or "" for t in p.iter("{%s}t" % ns["w"])]
        line = "".join(texts)
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def fix_zip_name(name):
    """修复 zip 中文文件名被 cp437 误解码的问题。"""
    try:
        fixed = name.encode("cp437").decode("utf-8")
        return fixed if fixed != name else name
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def main():
    ap = argparse.ArgumentParser(description="题库压缩包解析器")
    ap.add_argument("zip_path")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    zip_path = os.path.abspath(args.zip_path)
    if not os.path.isfile(zip_path):
        print("错误: 找不到文件 %s" % zip_path, file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(zip_path)
    os.makedirs(out_dir, exist_ok=True)

    questions, unrecog = [], []
    meta = {"subject": None, "grade": None}
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for root, _dirs, files in os.walk(tmp):
            for fn in sorted(files):
                path = os.path.join(root, fn)
                rel = fix_zip_name(os.path.relpath(path, tmp))
                ext = os.path.splitext(fn)[1].lower()
                try:
                    if ext == ".json":
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                        qs, m = parse_json_bank(data, rel, meta)
                        for k in ("subject", "grade"):
                            if m.get(k) and not meta.get(k):
                                meta[k] = m[k]
                        questions.extend(qs)
                    elif ext in (".txt", ".md"):
                        with open(path, encoding="utf-8", errors="replace") as f:
                            questions.extend(parse_text_bank(f.read(), rel))
                    elif ext == ".docx":
                        questions.extend(parse_text_bank(docx_to_text(path), rel))
                    else:
                        unrecog.append(rel)
                except Exception as e:  # noqa: BLE001
                    unrecog.append("%s（解析失败: %s）" % (rel, e))

    # 重新编号避免冲突
    for i, q in enumerate(questions, 1):
        q["id"] = "q%04d" % i

    bank = {
        "subject": meta.get("subject"),
        "grade": meta.get("grade"),
        "questions": questions,
    }
    bank_path = os.path.join(out_dir, "bank.json")
    with open(bank_path, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)

    # ---- 统计报告 ----
    n_total = len(questions)
    usable = [q for q in questions if not q["untagged"]]
    def count_by(key_fn):
        d = {}
        for q in usable:
            for v in (key_fn(q) or ["未标注"]):
                d[v] = d.get(v, 0) + 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))

    type_dist = count_by(lambda q: [q["type"]])
    diff_dist = {str(k): v for k, v in sorted(count_by(lambda q: [q["difficulty"]]).items(), key=lambda x: int(x[0]))}
    kp_dist = count_by(lambda q: q["knowledge_points"])
    no_answer = [q["id"] for q in questions if not q["answer"]]

    lines = ["# 题库解析统计", ""]
    lines.append("- 题目总数：**%d**（可组卷 %d，未标注 %d）" % (n_total, len(usable), n_total - len(usable)))
    lines.append("- 无答案题目：**%d**" % len(no_answer))
    lines.append("")
    lines.append("## 题型分布")
    lines.append("| 题型 | 题数 |")
    lines.append("|------|------|")
    for k, v in type_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 难度分布（1 最易 - 5 最难）")
    lines.append("| 难度 | 题数 |")
    lines.append("|------|------|")
    for k, v in diff_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 知识点覆盖")
    lines.append("| 知识点 | 题数 |")
    lines.append("|--------|------|")
    for k, v in kp_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 题目来源覆盖")
    lines.append("- 已标注来源：**%d** 题 / 未标注来源：**%d** 题（组卷时标注\"待补充\"）" % (
        sum(1 for q in questions if q.get("school") or q.get("exam_type") or q.get("year")),
        sum(1 for q in questions if not (q.get("school") or q.get("exam_type") or q.get("year")))))
    lines.append("")
    lines.append("### 按学校统计")
    lines.append("| 学校 | 题数 |")
    lines.append("|------|------|")
    school_dist = count_by(lambda q: [q["school"] or "未标注"])
    for k, v in school_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("### 按试卷类型统计")
    lines.append("| 试卷类型 | 题数 |")
    lines.append("|----------|------|")
    et_dist = count_by(lambda q: [q["exam_type"] or "未标注"])
    for k, v in et_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("## 年级 / 学科覆盖")
    lines.append("| 年级 | 题数 |")
    lines.append("|------|------|")
    grade_dist = count_by(lambda q: [q["grade"] or "未标注"])
    for k, v in grade_dist.items():
        lines.append("| %s | %d |" % (k, v))
    lines.append("")
    lines.append("| 学科 | 题数 |")
    lines.append("|------|------|")
    subject_dist = count_by(lambda q: [q["subject"] or "未标注"])
    for k, v in subject_dist.items():
        lines.append("| %s | %d |" % (k, v))
    if unrecog:
        lines.append("")
        lines.append("## 未识别文件")
        for u in unrecog:
            lines.append("- %s" % u)
    stats_path = os.path.join(out_dir, "bank_stats.md")
    with open(stats_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("✅ 解析完成：%d 道题（可组卷 %d，未标注 %d，无答案 %d）" % (n_total, len(usable), n_total - len(usable), len(no_answer)))
    print("   题库文件：%s" % bank_path)
    print("   统计报告：%s" % stats_path)


if __name__ == "__main__":
    main()

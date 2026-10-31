#!/usr/bin/env python3
"""Validate shared references and required document structure before rendering."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
TASK_KEY = re.compile(r"^t\d+$")
STUDENT_LABELS = re.compile(r"差生|学困组|低层|低水平|简单版|培优组|诊断报告|IEP")
IDENTITY_KEYS = {
    "education_stage",
    "grade",
    "subject",
    "duration",
    "curriculum_standard",
    "standard_basis",
    "textbook",
}
COMMON_DIFFERENTIATION_KEYS = {"exit_ticket", "anchor_activity", "reflect_prompt"}


def walk(value):
    """Yield every nested mapping."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def refs(document: dict) -> set[str]:
    return {
        str(block.get("key"))
        for block in walk(document)
        if block.get("type") == "from_shared" and block.get("key")
    }


def all_text(value) -> str:
    parts: list[str] = []
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            parts.append(all_text(child))
    elif isinstance(value, list):
        for child in value:
            parts.append(all_text(child))
    return "\n".join(part for part in parts if part)


def validate(path: Path, mode: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"无法读取有效 UTF-8 JSON：{exc}"], warnings

    shared = source.get("shared")
    documents = source.get("documents")
    if not isinstance(shared, dict):
        return ["顶层 shared 必须是对象。"], warnings
    if not isinstance(documents, list) or not documents:
        return ["顶层 documents 必须是非空数组。"], warnings

    missing_identity = sorted(IDENTITY_KEYS - set(shared))
    if missing_identity:
        errors.append("shared 缺少课程身份字段：" + ", ".join(missing_identity))

    ids: list[str] = []
    for index, document in enumerate(documents, 1):
        if not isinstance(document, dict):
            errors.append(f"documents[{index}] 不是对象。")
            continue
        doc_id = str(document.get("id", ""))
        ids.append(doc_id)
        if not doc_id or not SAFE_ID.fullmatch(doc_id):
            errors.append(f"文档 ID 不安全或为空：{doc_id!r}")
        if document.get("audience") not in {"teacher", "student"}:
            errors.append(f"{doc_id or index} 的 audience 必须是 teacher 或 student。")
        if not isinstance(document.get("sections"), list) or not document["sections"]:
            errors.append(f"{doc_id or index} 缺少非空 sections。")

    if len(ids) != len(set(ids)):
        errors.append("documents[].id 必须唯一。")

    shared_keys = set(shared)
    for document in documents:
        doc_id = str(document.get("id", "<unknown>"))
        missing_refs = sorted(refs(document) - shared_keys)
        if missing_refs:
            errors.append(f"{doc_id} 引用了不存在的 shared 键：" + ", ".join(missing_refs))

    detected_mode = mode
    if mode == "auto":
        detected_mode = "differentiation" if "teacher_plan" in ids else "planning"

    if detected_mode == "planning":
        required = {"lesson_plan", "observation_template"}
        missing = sorted(required - set(ids))
        if missing:
            errors.append("课程设计缺少文档：" + ", ".join(missing))
        lesson_plan = next((doc for doc in documents if doc.get("id") == "lesson_plan"), None)
        if lesson_plan and isinstance(shared.get("duration"), (int, float)):
            minutes = sum(
                block.get("minutes", 0)
                for block in walk(lesson_plan)
                if block.get("type") == "phase_header"
                and isinstance(block.get("minutes"), (int, float))
            )
            if minutes and minutes != shared["duration"]:
                errors.append(
                    f"教学环节共 {minutes} 分钟，与 shared.duration={shared['duration']} 不一致。"
                )

    elif detected_mode == "differentiation":
        required = {
            "teacher_plan",
            "worksheet_group_a",
            "worksheet_group_b",
            "worksheet_group_c",
        }
        missing = sorted(required - set(ids))
        if missing:
            errors.append("差异化方案缺少文档：" + ", ".join(missing))
        common_missing = sorted(COMMON_DIFFERENTIATION_KEYS - shared_keys)
        if common_missing:
            errors.append("shared 缺少共同任务：" + ", ".join(common_missing))
        task_keys = {key for key in shared_keys if TASK_KEY.fullmatch(key)}
        if not task_keys:
            warnings.append("未发现 t1、t2 等共享核心任务键。")
        expected_refs = task_keys | COMMON_DIFFERENTIATION_KEYS
        for document in documents:
            if document.get("audience") != "student":
                continue
            doc_id = str(document.get("id"))
            missing_refs = sorted(expected_refs - refs(document))
            if missing_refs:
                errors.append(f"{doc_id} 未引用共同任务：" + ", ".join(missing_refs))
            found = sorted(set(STUDENT_LABELS.findall(all_text(document))))
            if found:
                errors.append(f"{doc_id} 含学生能力/诊断标签：" + ", ".join(found))
    else:
        errors.append(f"未知 mode：{detected_mode}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--mode",
        choices=["auto", "planning", "differentiation"],
        default="auto",
    )
    args = parser.parse_args()
    errors, warnings = validate(args.input, args.mode)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"valid: {args.input} ({args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

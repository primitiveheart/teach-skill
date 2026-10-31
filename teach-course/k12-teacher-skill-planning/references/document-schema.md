# 教学材料 JSON 结构

## 顶层

```text
shared:
  education_stage, grade, subject, duration
  curriculum_standard, standard_basis, textbook
  <复用键>: string | block | block[] | {teacher, student, stimulus?}
documents[]:
  id, audience: teacher|student, eyebrow, title, meta?, theme?
  sections[]: {heading, blocks[]}
```

最低文档：

- `lesson_plan`，教师；
- `observation_template`，教师；
- `student_materials`，学生有纸面任务时。

## Block

```text
{type: from_shared, key, label?}
{type: paragraph, text}
{type: labeled, label, text}
{type: callout, kind: special|student-task|teacher-note|student-note, label, text}
{type: h2|h3, text}
{type: list, label?, ordered?, items[]}
{type: checklist, label?, items[]}
{type: phase_header, name, minutes}
{type: table, headers[]?, rows[[]]}
{type: fill_table, headers[], blank_rows, row_height_pt?}
{type: number_line, min, max, ticks?, marks[]?}
{type: source_card, title, author?, date?, origin?, excerpt}
{type: cards, items[{title, text}]}
{type: workspace, size: small|med|large, height_pt?}
{type: group, blocks[]}
{type: columns, left[], right[]}
{type: page_break}
```

## 规则

- 标准依据只完整呈现一次，其他位置用简短概括。
- 重复任务必须注册到 `shared` 并用 `from_shared` 引用。
- 学生作答任务后必须有作答载体。
- 表格使用 `table`，不要在 `text` 中写 Markdown pipe table。
- `group` 包住题目、材料、支架和作答空间，避免跨页。
- `documents[].id` 使用英文字母、数字、下划线或连字符。

渲染前运行：

```bash
python scripts/validate_material_source.py lesson.json --mode planning
```

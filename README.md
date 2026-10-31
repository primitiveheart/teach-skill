# teach-skill

教育场景的 Agent Skills 合集，按使用对象和任务边界分成四组：自主学习工作区、教师出卷与论文、课堂备课、家长居家辅导。每个 skill 以各自目录下的 `SKILL.md` 为入口。

除 `learning/teach` 外，其余 skill 来自 [SkillHub「teach」检索（按分数排序）](https://skillhub.cn/skills?keyword=teach&sortBy=score)。各目录的页面、版本和核对记录：

- 教师出卷与论文：[teach/NOTES.md](teach/NOTES.md)
- 课堂备课：[teach-course/SOURCES.md](teach-course/SOURCES.md)
- 家长辅导：[teach-parent/SOURCES.md](teach-parent/SOURCES.md)

## 自主学习工作区 `learning/`

| 目录 | 作用 | 版本 |
| --- | --- | --- |
| [teach](learning/teach/SKILL.md) | 按学习动机拆成多轮课程、练习和参考文档 | — |

## 教师出卷与论文 `teach/`

本组面向教师的出卷、题库、试卷排版、错题诊断和论文写作任务。

| 目录 | 作用 | 版本 |
| --- | --- | --- |
| [edu-paper-builder](teach/edu-paper-builder/SKILL.md) | 按知识点和难度智能组卷，产出试卷、答案和评分标准 | 1.2.1 |
| [k12-paper-generator](teach/k12-paper-generator/SKILL.md) | 整理题库，并按打卡、周测、学情挑题组卷 | 1.0.0 |
| [exam-paper-formater](teach/exam-paper-formater/SKILL.md) | 把已有题目排成可印刷 PDF（试卷、答案卷、答题卡） | 1.0.1 |
| [exam-paper-error-analysis](teach/exam-paper-error-analysis/SKILL.md) | 单题或整卷错题分析、变式题和讲评建议 | 0.1.0 |
| [teacher-paper-coach](teach/teacher-paper-coach/SKILL.md) | 帮中小学教师把公开课、教研和课题整理成论文 | 1.0.0 |

## 课堂备课 `teach-course/`

| 目录 | 作用 | 版本 |
| --- | --- | --- |
| [china-k12-lesson-planning](teach-course/china-k12-lesson-planning/SKILL.md) | 按国家课程方案和教材进度生成教学设计、学习单和课堂观察表 | 1.0.0 |
| [teach-mat](teach-course/teach-mat/SKILL.md) | 检索教案、课件、习题、学案、试卷等中小学教学资料 | 1.0.1 |
| [edu-teacher-ai-toolbox](teach-course/edu-teacher-ai-toolbox/SKILL.md) | 备课、作业批改辅助、家校沟通、课件和学生数据整理的提示词脚手架 | 1.0.0 |

## 家长辅导 `teach-parent/`

| 目录 | 作用 | 版本 |
| --- | --- | --- |
| [primary-school](teach-parent/primary-school/SKILL.md) | 面向家长的小学到初中居家学习辅助：复习卡、写作引导、错题讲解、学习与作息规划和科创表达支持 | 1.1.0 |

## 使用

把对应 skill 目录交给支持 Agent Skills 的客户端加载，从该目录的 `SKILL.md` 开始。需要看来源页面时，打开该组目录里的 `SOURCES.md` 或 `NOTES.md`。

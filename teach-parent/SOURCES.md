# Skill 来源

`teach-parent/` 下的 skill 来自 SkillHub 检索页，按分数排序：

https://skillhub.cn/skills?keyword=teach&sortBy=score

记录日期：2026-10-31。原始收录版本与来源页核对如下；仓库中的本地 Skill 可能在此基础上继续维护，当前版本以本地 `_meta.json` 和 `SKILL.md` 为准。

| 本地目录 | SkillHub 名称 | 版本 | 页面 |
| --- | --- | --- | --- |
| `primary-school` | 中小学生全科助学辅导助手 | 原始版本 1.0.0；本地维护版 1.1.0 | https://skillhub.cn/skills/user_fca74304/primary-school |

检索核对：该页当时共 255 个结果，接口按每页 50 条只返回前 200 条。`primary-school` 在 SkillHub 有同 slug、同版本的详情页（下载 1889，收藏 9），没有出现在这前 200 条里。

本地 1.1.0 将原 1085 行单文件拆分为主路由和按需参考模块，并修正教材版本、作业时长、户外活动、教育诚信、隐私与科创真实性等边界。合集下载地址：https://github.com/primitiveheart/teach-skill

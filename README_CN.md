# cclog

[English](README.md) | **中文**

在终端里浏览、总结和回顾你的 [Claude Code](https://claude.ai/code) 会话记录。

[![PyPI](https://img.shields.io/pypi/v/cclog?style=for-the-badge)](https://pypi.org/project/cclog/)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

---

## 功能一览

| 命令 | 功能 |
|------|------|
| `cclog index` | 扫描并索引所有 Claude Code 会话到本地数据库 |
| `cclog list` | 列出会话，支持按项目、日期、分类过滤 |
| `cclog show <id>` | 查看某条会话的详细信息（token 用量、使用工具、修改文件） |
| `cclog stats` | 汇总统计：总时长、token 消耗、项目数量 |
| `cclog summarize` | 用 AI 对会话生成摘要、分类和学习要点 |
| `cclog digest` | 生成每日或每周的 Markdown 工作报告 |
| `cclog clean` | 查找并删除无效/空会话（默认预览模式） |
| `cclog delete <id>` | 从索引和磁盘删除指定会话 |
| `cclog site` | 生成可在浏览器中浏览的静态 HTML 网站 |

![cclog demo](docs/screenshots/demo.svg)

---

## 安装

```bash
pip install cclog
```

## 快速开始

```bash
# 建立索引（首次运行，或有新会话后运行）
cclog index

# 查看今天做了什么
cclog list --date 2026-03-30

# 查看某条会话的详细内容
cclog show abc123

# 查看 token 使用统计
cclog stats

# 生成本周工作报告
cclog digest --week

# 让 AI 总结最近 10 条会话
cclog summarize --limit 10

# 在浏览器里浏览所有会话
cclog site --open
```

## 示例输出

```
$ cclog stats
=== cclog Statistics ===

  Sessions:     142
  Projects:     18
  Summarized:   87
  Total time:   63.4 hours
  Input tokens:  12.3M
  Output tokens: 4.1M
  Date range:   2026-01-05 ~ 2026-03-30
```

## 使用场景

- **每日站会** — `cclog digest` 输出昨天的会话摘要
- **每周复盘** — `cclog digest --week` 汇总本周完成的工作
- **费用追踪** — `cclog stats` 查看所有项目的 token 消耗
- **清理垃圾会话** — `cclog clean` 删除误开的一分钟短会话
- **知识归档** — `cclog summarize` + `cclog site` 把会话变成可搜索的知识库

## 环境要求

- Python 3.11+
- 已安装 [Claude Code](https://claude.ai/code)（提供会话数据来源）

## License

MIT

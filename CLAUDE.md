# cclog — Claude Code 会话浏览与分析工具

## Quick Reference

| 项目 | 路径/值 |
|------|---------|
| 源码入口 | `src/cclog/cli.py` |
| CLI 入口 | `cclog` (安装后全局可用) |
| Static site server | `src/cclog/server.py` |
| DB 位置 | `~/.cclog/` (自动创建) |
| 凭证 | `~/.personal_env` → `ANTHROPIC_API_KEY`（summarize 功能需要） |

## 常用命令

```bash
# 开发模式安装（本地修改立即生效）
pip install -e ".[all]"

# 基础工作流
cclog index                    # 扫描 ~/.claude/projects/ 建立索引
cclog list                     # 列出所有会话
cclog list --project cclog     # 按项目过滤
cclog list --date 2026-03-31   # 按日期过滤
cclog show <id>                # 查看会话详情（token/工具/文件）

# 统计与摘要
cclog stats                    # 总时长、token、项目数
cclog digest                   # 今日 Markdown digest
cclog digest --week            # 本周 digest

# AI 功能（需要 ANTHROPIC_API_KEY）
cclog summarize --limit 10     # AI 生成最近 10 个会话摘要

# 静态站点
cclog site --open              # 生成 HTML 站点并在浏览器打开

# 清理
cclog clean                    # 找出空/无效会话（dry-run）
cclog clean --confirm          # 确认删除
cclog delete <id>              # 删除单条会话

# 测试
pytest tests/
```

## MCP Server

cclog 通过 MCP 向 Claude Code 暴露会话搜索能力，CC 在对话中可直接调用。

| 项目 | 值 |
|------|-----|
| 入口 | `src/cclog/mcp_server.py` |
| 注册方式 | `claude mcp add --scope user cclog -- uv run --directory /Users/tianli/Dev/cclog python src/cclog/mcp_server.py` |
| 配置写入 | `~/.claude.json` 的 `mcpServers.cclog`（**不是** `.mcp.json`） |
| 验证 | `claude mcp list` 应显示 `cclog: ✓ Connected` |

**提供的 MCP 工具**：

| 工具 | 用途 |
|------|------|
| `search_sessions` | 按项目名/关键词/日期/分类搜索会话 |
| `get_session_detail` | 按 session_id（前缀匹配）获取完整详情 |
| `get_session_stats` | 总体统计（会话数、项目数、时长、token） |
| `get_daily_digest` | 指定日期的 Markdown 格式日报 |

**注意**：添加/修改 MCP 后需重启 CC 会话才能使用新工具。

## 项目结构

```
src/cclog/
├── cli.py          # 所有子命令入口（main()）
├── mcp_server.py   # MCP server（FastMCP，4 tools）
├── server.py       # cclog site 的本地 HTTP server
└── __main__.py     # python -m cclog 支持

tests/              # pytest 测试套件
docs/screenshots/   # README 截图资源
pyproject.toml      # hatchling 构建，optional-dep: api/dev/all
```

## 开发注意

- Python 3.11+，使用 `match` 语句等新特性
- `anthropic` 是 optional dep，`import` 前需检查是否安装（`pip install cclog[api]`）
- 会话数据源：`~/.claude/projects/**/*.jsonl`，index 写入本地 SQLite
- 修改 CLI 子命令后跑 `cclog --help` 快速验证注册是否生效

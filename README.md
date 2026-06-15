# Claude Harness

围绕 **Claude Code / Claude Agent SDK** 的长时运行（long-running）自主编码 Agent 的实验与参考实现集合。

本仓库包含三套相互独立、可互相借鉴的 harness 工程，以及若干篇关于 long-running agent 设计原则的参考资料。

---

## 目录结构

```
claude-harness/
├── autonomous-coding/          # Anthropic 官方双 Agent 自主编码 demo
├── claude-code-config/         # Claude Code 原生 hooks 实现的长时运行原语
├── combined-harness/           # 合并以上两者：Builder + Evaluator 反馈闭环
├── autonomous-coding-quickstart.md
├── effective-harnesses-for-long-running-agents.md
└── harness-design-long-running-apps.md
```

---

## 子项目一览

### 1. [autonomous-coding/](autonomous-coding/)

Anthropic 官方提供的最小可运行 demo：用 **Initializer + Coding Agent** 双 Agent 模式，通过多 Session 持续构建完整应用。

- **原始出处**：[anthropics/claude-quickstarts — autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding)
- **入口**：[autonomous-coding/autonomous_agent_demo.py](autonomous-coding/autonomous_agent_demo.py)
- **核心思想**：每个 Session 拿一个全新的 context window；进度通过 `feature_list.json` + git commit 持久化；按 200 个 test case 逐个推进。
- **安全模型**：OS sandbox + 文件系统权限白名单 + Bash 命令白名单（详见 [autonomous-coding/security.py](autonomous-coding/security.py)）。
- **详细说明**：见 [autonomous-coding/README.md](autonomous-coding/README.md)。

启动示例：
```bash
cd autonomous-coding
pip install -r requirements.txt
python autonomous_agent_demo.py --project-dir ./my_project
```

---

### 2. [claude-code-config/](claude-code-config/)

把长时运行所需的几条「原语」用 **Claude Code 原生 hooks** 实现，不依赖 Python harness，直接拷贝 `.claude/` 即可生效。

| 文件 | 原语 |
|---|---|
| `.claude/hooks/kill-switch.sh` | 存在 `./AGENT_STOP` 时阻断所有工具调用 |
| `.claude/hooks/steer.sh` | 把 `./STEER.md` 内容一次性注入给 Agent 后清空 |
| `.claude/hooks/track-read.sh` + `verify-gate.sh` | 没读取过证据（截图/控制台日志）前，不允许把 test 标记为通过 |
| `.claude/hooks/commit-on-stop.sh` | 每个 Session 结束时自动 commit |
| `.claude/CLAUDE.md` | 「PROGRESS.md 约定 / 一次只做一个 feature / 通过前必须有证据」等规约 |

- **详细说明**：见 [claude-code-config/README.md](claude-code-config/README.md)。

启用方式：
```bash
cp -r claude-code-config/.claude/ /path/to/your/project/
chmod +x /path/to/your/project/.claude/hooks/*.sh
cd /path/to/your/project && claude
```

---

### 3. [combined-harness/](combined-harness/)（推荐起点）

把 `autonomous-coding` 的 Python 自动循环 与 `claude-code-config` 的 hooks 原语 **合并**，并新增 **独立 Evaluator Agent**，构成完整的反馈闭环：

```
BUILD  → Builder Agent 实现一个 feature
COMMIT → 自动 git checkpoint
EVAL   → 独立 Evaluator Agent 从零上下文审查（只读权限）
FEED   → Evaluator 的 NEEDS_WORK 反馈注入下一轮 Builder prompt
```

- **入口**：[combined-harness/main.py](combined-harness/main.py)
- **核心实现**：
  - 主循环：[combined-harness/loop.py](combined-harness/loop.py)
  - Builder（全权工具 + Puppeteer）：[combined-harness/builder.py](combined-harness/builder.py)
  - Evaluator（仅 Read/Glob/Grep/Bash）：[combined-harness/evaluator.py](combined-harness/evaluator.py)
  - 所有 hooks：[combined-harness/hooks.py](combined-harness/hooks.py)
- **目标应用规格**：[combined-harness/prompts/app_spec.txt](combined-harness/prompts/app_spec.txt) —— 一个包含 5 个工具（JSON / Base64 / 密码生成 / URL 编解码 / 时间戳）的 DevTools 网站。

启动示例：
```bash
cd combined-harness
pip install -r requirements.txt
python main.py --project-dir ./my_project
```

运行时控制：
```bash
touch generations/my_project/AGENT_STOP                   # 紧急停止
echo "改用 TypeScript" > generations/my_project/STEER.md  # 向 Agent 注入新指令
```

---

## 参考资料

仓库根目录下三篇 Markdown 文档是对 Anthropic 官方文章的本地化总结，原文链接如下：

| 本地文档 | Anthropic 官方原文 |
|---|---|
| [effective-harnesses-for-long-running-agents.md](effective-harnesses-for-long-running-agents.md) | [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| [harness-design-long-running-apps.md](harness-design-long-running-apps.md) | [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) |
| [autonomous-coding-quickstart.md](autonomous-coding-quickstart.md) | [anthropics/claude-quickstarts — autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding) |

核心思路（贯穿三个子项目）：
1. **Session 隔离**：每次执行用全新 context，把状态持久化到磁盘（`PROGRESS.md` / `feature_list.json` / git）。
2. **证据驱动**：不依赖 Agent 自述「我搞定了」，必须有截图 / 日志被读取过才能标记通过。
3. **独立审查**：Evaluator 不能 Write，也看不到 Builder 的思路，单独审查产出。
4. **可干预**：通过 `AGENT_STOP` 紧急停止、`STEER.md` 注入指令，实现人在回路控制。

---

## 环境要求

- **Python**：3.10+
- **Node.js**：用于 `@anthropic-ai/claude-code` CLI 与 Puppeteer MCP
- **Claude Code CLI**：`npm install -g @anthropic-ai/claude-code`
- **Claude Agent SDK**：`pip install claude-code-sdk>=0.0.25`
- **环境变量**：`export ANTHROPIC_API_KEY='...'`

---

## 选哪个？

| 我想…… | 用 |
|---|---|
| 跑 Anthropic 官方原版 demo 看一下效果 | [autonomous-coding/](autonomous-coding/) |
| 给现有项目加上 long-running 必备的几条规约 | [claude-code-config/](claude-code-config/) |
| 看完整的 Builder + Evaluator 闭环、并以此为基础改造自己的 harness | [combined-harness/](combined-harness/) |
| 先读原理再决定 | 仓库根目录的三篇 `.md` |

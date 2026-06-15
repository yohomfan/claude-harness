# Claude Harness

围绕 **Claude Code / Claude Agent SDK** 的长时运行（long-running）自主编码 Agent 的实验与参考实现集合。

本仓库包含三套相互独立、可互相借鉴的 harness 工程，以及几篇关于 long-running agent 设计原则的参考资料。

> **核心问题**：当你想让 Agent 跑几小时甚至几天、跨多个 Session 连续构建一个真实应用时，光靠 `claude` 单次会话是不够的——会撞 context 上限、会"自我感觉良好但其实坏了"、会在你睡觉时跑偏。本仓库提供的几套 harness 就是用来解决这些问题的。

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
- **核心思想**：每个 Session 拿一个全新的 context window；进度通过 `feature_list.json` + git commit 持久化；按 ~200 个 test case 逐个推进。
- **安全模型**：OS sandbox + 文件系统权限白名单 + Bash 命令白名单（详见 [autonomous-coding/security.py](autonomous-coding/security.py)）。
- **详细说明**：见 [autonomous-coding/README.md](autonomous-coding/README.md)。

### 2. [claude-code-config/](claude-code-config/)

把长时运行所需的几条「原语」用 **Claude Code 原生 hooks** 实现，不依赖 Python harness，直接拷贝 `.claude/` 即可生效。

| 文件 | 原语 |
|---|---|
| `.claude/hooks/kill-switch.sh` | 存在 `./AGENT_STOP` 时阻断所有工具调用 |
| `.claude/hooks/steer.sh` | 把 `./STEER.md` 内容一次性注入给 Agent 后清空 |
| `.claude/hooks/track-read.sh` + `verify-gate.sh` | 没读取过证据（截图/控制台日志）前，不允许把 test 标记为通过 |
| `.claude/hooks/commit-on-stop.sh` | 每个 Session 结束时自动 commit |
| `.claude/CLAUDE.md` | 「PROGRESS.md 约定 / 一次只做一个 feature / 通过前必须有证据」等规约 |

详细说明见 [claude-code-config/README.md](claude-code-config/README.md)。

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
- **示例规格**：[combined-harness/prompts/app_spec.txt](combined-harness/prompts/app_spec.txt) —— 一个包含 5 个工具（JSON / Base64 / 密码生成 / URL 编解码 / 时间戳）的 DevTools 网站。

---

## 如何套用到你自己的项目

> 先澄清一个常见误区：**Claude Code 的 "skill" 和 "subagent" 都是单 Session 内的原语**（skill = 可调用的专家流程，subagent = 一个会话里 spawn 出的子 Agent），它们解决不了"跨 Session、跑几小时"这件事。本仓库提供的是更外层的编排，正确的问法不是"装哪个 skill"，而是"用哪一档 harness"。

### 选哪条路径

| 你的场景 | 走哪条 | 介入程度 |
|---|---|---|
| 已有项目，只想加上"通过前必须看证据""紧急停止""自动 commit"这几条约束，平时还是交互式 `claude` 在用 | **路径 A**（[claude-code-config/](claude-code-config/)） | 轻 |
| **全新项目**，扔一份 spec 进去，希望几小时后回来看完整产物，且要有 Evaluator 互相制衡 | **路径 B**（[combined-harness/](combined-harness/)） | 中（推荐） |
| 只是想跑通 Anthropic 官方原版 demo 学习一下 | 路径 C（[autonomous-coding/](autonomous-coding/)） | 中 |

主要权衡：**B 比 A 烧 token 多得多**（每个 feature 都会跑一遍独立 Evaluator），但产物质量稳定很多。

### 前置准备（所有路径通用）

```bash
# 1. Claude Code CLI（最新版）
npm install -g @anthropic-ai/claude-code
claude --version

# 2. API key
export ANTHROPIC_API_KEY='sk-ant-...'

# 3. Python 3.10+（路径 B、C 需要）
python3 --version

# 4. （可选）Chrome——路径 B 的 Puppeteer MCP 用来截图
```

---

### 路径 A：给已有项目加约束（最轻量）

适合：你打算自己开着 `claude` 交互式干活，只想要那几条规约兜底。

**初始化步骤：**

```bash
# 1. 拷 .claude/ 进你的项目根目录
cd /path/to/your-existing-project
cp -r /path/to/claude-harness/claude-code-config/.claude/ ./
chmod +x .claude/hooks/*.sh

# 2. 建两个 handoff 文件（hooks 依赖它们）
cat > PROGRESS.md <<'EOF'
## Done

## In progress

## Next

## Notes
EOF

echo '{}' > test-results.json   # 形状自定，hook 只校验"是否读过证据后再写"

# 3. 启动
claude
```

**之后每次新 Session**：Agent 会先读 `PROGRESS.md`，做一件事，更新 `PROGRESS.md`，commit；想标 test 通过必须先用 Read 工具打开截图/日志才能写 `test-results.json`。

**无人值守循环跑**：套上官方 [`ralph-loop`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/ralph-loop) 插件，或者最朴素一句：

```bash
while true; do claude -p "continue from PROGRESS.md"; done
```

---

### 路径 B：全新项目 + 完整闭环（推荐）

适合：扔一份产品 spec 进去，让 harness 自己跑几小时，回来看可运行的产物。

> **关键**：这条路径的 init 是"半自动"的——你只写一份产品规格文本（`app_spec.txt`），剩下的 80~200 条 end-to-end test case、项目骨架、`init.sh` 启动脚本都是 **Initializer Agent 在第一次运行时自动生成的**。

**初始化步骤：**

```bash
# 1. 装依赖
cd /path/to/claude-harness/combined-harness
pip install -r requirements.txt

# 2. 改 prompts/app_spec.txt 描述你想要的应用（这是唯一必改的文件）
#    当前是 DevTools 网站的 spec，照着 XML 结构改成你的产品
vim prompts/app_spec.txt

# 3. （可选）调整 Initializer 生成的 test case 规模
vim prompts/initializer_prompt.md
#    把里面的 "80 tests" 改成你想要的数量（小项目 20-30，大项目 200+）

# 4. （可选）调整 Evaluator 的审查侧重
vim prompts/evaluator_prompt.md

# 5. 启动（第一次跑会自动初始化）
python main.py --project-dir ./my_new_app
#    生成产物会落在 combined-harness/generations/my_new_app/
#    如想放别处，传绝对路径：--project-dir /abs/path/to/my_new_app
```

**第一次运行（Initializer 阶段）会发生什么：**

1. harness 把 `prompts/app_spec.txt` 拷到 `generations/my_new_app/app_spec.txt`
2. Initializer Agent 启动、读 spec
3. 生成 `feature_list.json`（80~200 条带步骤的 e2e test case）—— **这步要 10~20 分钟**，看起来像卡住了其实在写
4. 生成 `init.sh`（项目启动脚本）
5. `git init` + 首次 commit
6. 搭建项目骨架（`package.json`、目录结构等）

**之后每轮（Build → Evaluate → Feedback）：**

1. **Build**：Builder Agent 全新 context，读 `feature_list.json`，挑一个 `passes: false` 的 feature 实现，截图为证
2. **Commit**：harness 自动 `git commit -am "session checkpoint: <时间>"`
3. **Evaluate**：Evaluator Agent 全新 context，只有 Read/Glob/Grep/Bash 权限，输出第一行 `PASS` 或 `NEEDS_WORK`
4. **Feedback**：如果 NEEDS_WORK，详细反馈会拼到下一轮 Builder 的 prompt 开头
5. 循环直到所有 test 通过，或你 `Ctrl+C` 中断

**中断与恢复**：直接 `Ctrl+C`，跑相同命令即可继续——状态全在 `feature_list.json` + git 里。

**运行时操作**（Path A、B 都适用，文件放在 `--project-dir` 下）：

```bash
PROJECT=combined-harness/generations/my_new_app

# 紧急停止（下一次工具调用就被拒绝）
touch $PROJECT/AGENT_STOP

# 解除停止
rm $PROJECT/AGENT_STOP

# 注入新指令——下次工具调用前会被插到 Agent 上下文里，读完自动清空
echo "改用 TypeScript，并加上单元测试" > $PROJECT/STEER.md

# 看当前进度
python -c "import json; d=json.load(open('$PROJECT/feature_list.json')); print(sum(t['passes'] for t in d),'/',len(d))"

# 看 commit 历史
git -C $PROJECT log --oneline
```

**跑完后启动生成的应用：**

```bash
cd combined-harness/generations/my_new_app
./init.sh         # Initializer 已经为你写好这个脚本
# 或手动 npm install && npm run dev
```

---

### 路径 C：跑原版 Anthropic demo

跟路径 B 类似但没有 Evaluator 闭环，逻辑最少，适合学习。

```bash
cd /path/to/claude-harness/autonomous-coding
pip install -r requirements.txt

vim prompts/app_spec.txt           # 改 spec（或保留默认看效果）

python autonomous_agent_demo.py --project-dir ./my_project
# 限制最多 3 轮快速看效果：
python autonomous_agent_demo.py --project-dir ./my_project --max-iterations 3
```

详见 [autonomous-coding/README.md](autonomous-coding/README.md)。

---

## 核心设计原则（贯穿三个子项目）

1. **Session 隔离**：每轮执行用全新 context，把状态持久化到磁盘（`PROGRESS.md` / `feature_list.json` / git）。Context 大小不再是天花板。
2. **证据驱动**：不依赖 Agent 自述"我搞定了"，必须有截图 / 日志被读取过才能标记通过。`verify-gate` hook 强制执行。
3. **独立审查**：Evaluator 不能 Write、不能跑 Puppeteer、看不到 Builder 的思路，单独审查产出，避免"自我评分"。
4. **可干预**：通过 `AGENT_STOP` 紧急停止、`STEER.md` 注入指令，实现人在回路控制。

---

## 参考资料

仓库根目录下三篇 Markdown 文档是对 Anthropic 官方文章的本地化总结，原文链接如下：

| 本地文档 | Anthropic 官方原文 |
|---|---|
| [effective-harnesses-for-long-running-agents.md](effective-harnesses-for-long-running-agents.md) | [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| [harness-design-long-running-apps.md](harness-design-long-running-apps.md) | [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) |
| [autonomous-coding-quickstart.md](autonomous-coding-quickstart.md) | [anthropics/claude-quickstarts — autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding) |

---

## 环境要求速查

| 项 | 版本 / 说明 |
|---|---|
| Python | 3.10+ |
| Node.js | 用于 Claude Code CLI 与 Puppeteer MCP |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Claude Agent SDK | `pip install claude-code-sdk>=0.0.25` |
| Chrome | 路径 B 的 Puppeteer 截图需要（macOS 默认路径 `/Applications/Google Chrome.app`）|
| 环境变量 | `ANTHROPIC_API_KEY` |

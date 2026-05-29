# Effective Harnesses for Long-Running Agents

> 来源：[Anthropic Engineering Blog](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
> 作者：Justin Young
> 发布日期：2025 年 11 月 26 日
> 配套代码：[anthropics/cwc-long-running-agents](https://github.com/anthropics/cwc-long-running-agents)

## 文章概述

本文聚焦于一个关键挑战：**如何让 AI 智能体在多个上下文窗口间保持一致的工作进度**。核心问题类似于轮班工程师之间没有交接文档——每个新会话的智能体对之前的工作一无所知。

## 核心问题：两种典型失败模式

1. **过度雄心（Overambition）**：智能体试图在单次会话中完成整个项目，在实现过程中耗尽上下文窗口，留下不完整、无文档的功能给下一个会话。
2. **过早宣告完成（Premature Completion）**：后续会话的智能体看到部分进度后，错误地宣布项目已完成。

## 解决方案：两阶段智能体架构

### 1. Initializer Agent（初始化智能体）

首次会话使用专门提示词建立基础设施：

- **`init.sh` 脚本**：用于启动开发环境
- **`claude-progress.txt` 文件**：记录已完成的工作
- **初始 Git 提交**：显示已添加的文件
- **完整功能清单**：可包含 200+ 项功能条目

### 2. Coding Agent（编码智能体）

后续会话遵循结构化流程：

- 立即读取进度文件和 Git 历史
- 选择**单个**未完成的功能来实现
- 使用描述性消息提交更改
- 在会话结束前更新进度文档

## 关键设计策略

### 功能清单架构

- 使用 **JSON 格式**而非 Markdown 定义功能规格
- 原因：模型不太容易不当修改 JSON 结构
- 每个功能包含：步骤（steps）、描述（description）、通过状态（`"passes": boolean`）

### 增量式进度管理

- **逐功能推进**，防止上下文耗尽
- 确保代码库始终处于"可合并状态"（merge-ready）——干净、有文档、无 Bug

### 测试协议

- 明确提示使用端到端浏览器自动化（通过 **Puppeteer MCP**）
- 比单元测试的验证准确性**显著提高**

## 每次会话的初始化清单

每个编码智能体会话开始时执行：

1. 运行 `pwd` 确认工作目录
2. 读取 Git 日志和进度文件
3. 选择最高优先级的未完成功能
4. 通过 `init.sh` 启动开发服务器
5. 运行基础端到端验证测试

## 失败模式与解决方案对照

| 问题 | 初始化智能体的做法 | 编码智能体的做法 |
|------|-------------------|-----------------|
| 过早宣告完成 | 创建结构化功能清单，200+ 项标记为"failing" | 读取功能清单，逐项完成 |
| 环境不稳定 | 编写 Git 仓库初始化和进度记录 | 每次会话先验证系统状态，提交更改 |
| 功能标记不完整 | 建立功能需求框架 | 通过测试自行验证后再标记完成 |
| 环境搭建复杂 | 生成可执行的 `init.sh` 脚本 | 读取并执行初始化脚本 |

## 技术洞察

- **上下文压缩本身不足以解决长周期任务**——需要借鉴人类软件工程实践的显式环境脚手架
- 清晰的文档、增量进度跟踪、结构化交接协议是关键
- 本质上是将"团队协作的最佳实践"应用到多会话智能体编排中

## 未来方向

- 单一通用智能体 vs 专业化多智能体架构（测试、QA、清理等角色）哪个更好？仍是开放问题
- 这些原则可能从 Web 开发推广到科学研究和金融建模等领域

## 核心结论

有效的长时间运行智能体 Harness 需要：

1. **结构化的进度追踪**（JSON 功能清单 + 进度文件）
2. **增量式工作模式**（每次只做一个功能）
3. **明确的会话交接协议**（读取历史 → 选择任务 → 完成 → 更新记录）
4. **端到端测试验证**（而非仅靠自我评估）

---

## 附录：配套代码参考实现

> 以下代码来自 Anthropic 官方仓库 [anthropics/cwc-long-running-agents](https://github.com/anthropics/cwc-long-running-agents)，是 Code with Claude 2026 活动的教学示例。

### 整体架构

三个原语构成**质量循环（Quality Loop）**：

| 原语 | Claude Code 实现 | Agent SDK 等价物 |
|------|-----------------|-----------------|
| **Default-FAIL 合约** | `hooks/track-read.sh` + `hooks/verify-gate.sh` | `PreToolUse` 回调 |
| **Fresh-context 评估器** | `agents/evaluator.md` 子智能体（无 Write/Edit 权限） | `evaluator_optimizer.ipynb` |
| **智能体维护的交接** | `CLAUDE.md` + `hooks/commit-on-stop.sh` | system prompt + `Stop` 回调 |

两个额外的**操作员控制 Hook**：

| Hook | 功能 |
|------|------|
| `hooks/kill-switch.sh` | `touch AGENT_STOP` 暂停所有工具调用，`rm AGENT_STOP` 恢复 |
| `hooks/steer.sh` | 写入 `STEER.md` 向智能体注入新指令，读取后自动清空 |

### settings.json — Hook 注册配置

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/kill-switch.sh" },
          { "type": "command", "command": ".claude/hooks/steer.sh" }
        ]
      },
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/track-read.sh" }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          { "type": "command", "command": ".claude/hooks/verify-gate.sh" }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": ".claude/hooks/commit-on-stop.sh" }
        ]
      }
    ]
  }
}
```

### CLAUDE.md — 长时间运行约定

```markdown
# Long-running conventions for this project

## Always start here
Before doing anything else, read `PROGRESS.md`. It is your handoff note from the previous session.
If it doesn't exist yet, create it now with four sections (`## Done`, `## In progress`,
`## Next`, `## Notes`) and leave them empty. Then run `git log --oneline -10` to see what
was just committed, and run the project's smoke test once so you know you're starting from
a working tree, not a broken handoff.

## One feature at a time
Work on exactly one item from `PROGRESS.md` per session. Finish it (tests passing,
screenshot verified) before starting another.

## Proof before passing
A test is only "passing" after you have:
1. Run it against the live app (Playwright screenshot or equivalent)
2. Opened the resulting screenshot or console log with the Read tool
3. Confirmed it shows what it should

The `verify-gate` hook will deny writes to `test-results.json` until you have opened evidence.

## Keep `PROGRESS.md` current
After each completed item, update `PROGRESS.md`: check off what's done, add what you
learned, note what's next.

## Commit often
The `Stop` hook commits tracked changes at session end, but also `git add` new files and
commit yourself at meaningful checkpoints with descriptive messages.
```

### Hook 1: track-read.sh — 记录证据文件读取

```bash
#!/usr/bin/env bash
# 记录智能体读取了哪些证据文件（截图、控制台日志）
# verify-gate.sh 会查询此列表来决定是否允许标记测试通过
log="${VERIFY_READ_LOG:-./.claude/.evidence-reads}"
path=$(cat | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' \
  2>/dev/null)
case "$path" in
  *screenshots/*|*-console.txt|*-result.txt|*.png)
    [ -f "$path" ] && echo "$path" >> "$log" ;;
esac
exit 0
```

### Hook 2: verify-gate.sh — 写入结果前必须先看证据

```bash
#!/usr/bin/env bash
# 在智能体读取至少一个证据文件之前，拒绝对结果文件的任何写入
log="${VERIFY_READ_LOG:-./.claude/.evidence-reads}"
results="${RESULTS_FILE:-test-results.json}"

input=$(cat)
target=$(printf '%s' "$input" | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' \
  2>/dev/null)

# 只守护结果文件
case "$target" in "$results"|*/"$results") ;; *) exit 0 ;; esac

if [ ! -s "$log" ]; then
  cat <<'JSON'
{"decision":"block","reason":"Cannot modify the results file: no screenshot or console-log evidence has been Read this session. Open the evidence file with the Read tool first, then retry."}
JSON
  exit 0
fi
# 消耗证据，下次修改需要新的证明
: > "$log"
```

### Hook 3: kill-switch.sh — 紧急停止

```bash
#!/usr/bin/env bash
# touch AGENT_STOP 暂停；rm AGENT_STOP 恢复
if [ -e "${AGENT_STOP_FILE:-./AGENT_STOP}" ]; then
  cat <<'JSON'
{"decision":"block","reason":"Kill switch engaged: AGENT_STOP file exists. Agent is halted. Remove the file to resume."}
JSON
fi
```

### Hook 4: steer.sh — 运行中注入指令

```bash
#!/usr/bin/env bash
# 写入 STEER.md 可在运行中重定向智能体，内容读取后自动清空
f="${AGENT_STEER_FILE:-./STEER.md}"
if [ -s "$f" ]; then
  note=$(cat "$f")
  reason=$(python3 -c \
    'import json,sys; print(json.dumps("OPERATOR STEERING: " + sys.argv[1]))' \
    "$note" 2>/dev/null) || exit 0
  printf '{"decision":"block","reason":%s}\n' "$reason"
  : > "$f"
fi
```

### Hook 5: commit-on-stop.sh — 会话结束自动提交

```bash
#!/usr/bin/env bash
# 每次会话结束时提交已跟踪的更改，作为安全兜底
if git rev-parse --git-dir >/dev/null 2>&1; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git commit -am "session checkpoint: $(date '+%Y-%m-%d %H:%M')" >/dev/null 2>&1
  fi
fi
exit 0
```

### evaluator.md — 独立评估器子智能体

```markdown
---
name: evaluator
description: Skeptical second-opinion reviewer. Has no Write/Edit tools.
tools: Read, Glob, Grep, Bash
---

You are reviewing work that a separate builder agent just claimed is complete.
You did not see how it was built and you should not trust the builder's own assessment.

1. Read the spec or acceptance criteria for the feature under review.
2. Run `git diff` against the baseline to see exactly what changed.
3. Open every screenshot or console log and look at what they actually show,
   not what the filenames imply.
4. Decide.

Begin your reply with the bare word `PASS` or `NEEDS_WORK` on its own line.
- PASS: one line stating what evidence convinced you.
- NEEDS_WORK: a bullet list of specific, fixable findings.
```

### test-results.json — Default-FAIL 合约文件

```json
{ "feature-1": { "passes": false }, "feature-2": { "passes": false } }
```

所有功能默认为 `false`，智能体必须先读取证据才能将其改为 `true`。

### 运行质量循环

**方式一：使用内置 `/goal` 命令**

```
/goal every feature in PROGRESS.md is implemented, committed, and its tests pass
```

**方式二：自定义 Bash 循环脚本**

```bash
while grep -q '"passes": false' test-results.json; do
  claude -p "Read PROGRESS.md and build the next unfinished feature per CLAUDE.md."
  VERDICT=$(claude --agent evaluator -p "Review the most recent commit against its spec.")
  [ "$(echo "$VERDICT" | head -1)" = "PASS" ] || echo "$VERDICT" > NEXT_FINDINGS.md
done
```

### 实时监控

```bash
watch -n 2 'tail -20 PROGRESS.md'                          # 智能体笔记
watch -n 5 'git log --oneline -8'                          # 已保存的工作
watch -n 5 'find screenshots -name "*.png" | tail -5'      # 智能体看到的截图
watch -n 2 'wc -l < .claude/.evidence-reads 2>/dev/null'   # 证据读取计数
```

### 快速启动

```bash
# 克隆并复制到你的项目
git clone https://github.com/anthropics/cwc-long-running-agents.git /tmp/cwc
cp -r /tmp/cwc/claude-code-config/.claude /path/to/your/project/
chmod +x /path/to/your/project/.claude/hooks/*.sh

# 创建初始合约文件
echo '{ "feature-1": { "passes": false } }' > /path/to/your/project/test-results.json

# 启动
cd /path/to/your/project && claude
```

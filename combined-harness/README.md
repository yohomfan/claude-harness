# Combined Harness — Autonomous Coding with Feedback Loop

让 Claude 自主编码数小时：写一份 spec，启动 harness，回来看成品。

```
BUILD  →  COMMIT  →  EVALUATE  →  FEEDBACK  →  循环
 Builder     git       Evaluator     注入下轮
  Agent    checkpoint    Agent       Builder prompt
```

---

## Quick Start（3 步开始）

### 0. 前置准备

```bash
npm install -g @anthropic-ai/claude-code    # Claude Code CLI
export ANTHROPIC_API_KEY='sk-ant-...'        # API Key
cd combined-harness && pip install -r requirements.txt
```

### 1. 初始化项目

```bash
python harness.py init my-app
```

这会在 `generations/my-app/` 下创建项目目录，并拷贝一份 spec 模板。

### 2. 编写你的 spec

打开 `generations/my-app/app_spec.txt`，按模板填写你的产品规格。**这是唯一需要你手写的文件**，写得越详细，Agent 生成的测试和代码质量越高。

> 模板说明见 [prompts/app_spec.template.txt](prompts/app_spec.template.txt)

### 3. 启动

```bash
python harness.py run my-app
```

第一次运行会自动：生成测试用例（`feature_list.json`）→ 搭建项目骨架 → 开始逐个实现 feature。

**想看实时进度？** 另开一个终端：

```bash
python harness.py dashboard my-app
# 浏览器打开 http://localhost:8077
```

---

## 所有命令一览

| 命令 | 作用 |
|---|---|
| `python harness.py init <project>` | 创建新项目，拷贝 spec 模板 |
| `python harness.py run <project>` | 启动 Build → Evaluate → Feedback 循环 |
| `python harness.py dashboard <project>` | 打开 Web 看板（实时监控） |
| `python harness.py stop <project> [action]` | 暂停 / 恢复 / 退出 / 查看状态 |
| `python harness.py steer <project> <message>` | 运行中注入新指令 |

### run 参数

```bash
python harness.py run my-app \
  --max-iterations 10 \      # 最多跑 10 轮
  --max-runtime 4h \          # 最多跑 4 小时
  --max-stall 3 \             # 连续 3 次 NEEDS_WORK 就停
  --model claude-opus-4-7 \   # 用更强的模型
  --puppeteer                  # 启用浏览器测试（Web 项目）
```

### stop 操作

```bash
python harness.py stop my-app pause    # 暂停（60s 内生效，可恢复）
python harness.py stop my-app resume   # 恢复
python harness.py stop my-app quit     # 跑完当前轮后退出
python harness.py stop my-app status   # 查看当前状态
python harness.py stop my-app          # 默认 = status
```

### steer（运行中改方向）

```bash
python harness.py steer my-app "改用 TypeScript，并补单元测试"
```

Agent 会在下次工具调用时读到这条指令并调整行为。

---

## 运行控制（启动后怎么管）

### 原理：控制和「怎么启动」无关

控制的本质是往 `--project-dir` 目录里写**信号文件**，`run_loop` 每轮都会轮询读取：

| 信号文件 | 作用 | 生效时机 |
|---|---|---|
| `AGENT_STOP` | 暂停（不退出，循环原地轮询） | ≤60s |
| `AGENT_QUIT` | 跑完当前轮后**优雅退出** | 当前轮结束 |
| `STEER.md` | 注入新指令给 Agent，读后自动清空 | 下次工具调用 |

所以无论你用 `main.py` 还是 `harness.py` 启动，都能控制——区别只是 `harness.py` 把「写信号文件」封装成了子命令，`main.py` 需要你手动 `touch`。

### main.py ↔ harness.py 可混用

两者**目录解析完全一致**（相对路径 → `generations/<name>`，绝对路径原样），所以即使用 `main.py` 启动，也能用 `harness.py` 控制**同一个目录**：

```bash
# 用 main.py 启动……
python main.py --project-dir ./my-app

# ……另开终端，用 harness.py 控制同一任务：
python harness.py stop      my-app pause     # 暂停
python harness.py stop      my-app status    # 看状态
python harness.py dashboard my-app           # 看板
python harness.py steer     my-app "改用 xxx" # 注入指令
```

### 限制运行时长（先到先停）

`run` 支持 4 种自动停条件，可叠加，哪个先满足先停（详见上方 [run 参数](#run-参数)）：

| 参数 | 含义 |
|---|---|
| `--max-iterations N` | 最多跑 N 轮 |
| `--max-runtime T` | 最多跑多久（`2h` / `30m` / `90s`） |
| `--max-stall N` | 连续 N 轮 NEEDS_WORK 就停（防卡死） |
| （自然完成） | 所有 test 通过 |

```bash
# 最多 10 轮，但连续卡 3 轮就别浪费了
python harness.py run my-app --max-iterations 10 --max-stall 3
```

### ⚠️ Windows 注意

`main.py` 在 Windows 上无法注册 SIGTERM 处理器（`add_signal_handler` 不可用，代码已 `pass`），所以 **`kill <pid>` / SIGTERM 不会优雅退出**。Windows 下请用 `AGENT_QUIT`（跑完本轮退出）或终端 `Ctrl+C`。

### 外部绝对路径目录

项目不在 `generations/` 下时，直接传绝对路径即可：

```bash
python harness.py run       D:/Project/github/MaoJi-uni --max-iterations 5 --puppeteer
python harness.py stop      D:/Project/github/MaoJi-uni pause
python harness.py dashboard D:/Project/github/MaoJi-uni
```

---

## Web 看板（Dashboard）

```bash
python harness.py dashboard my-app
# 或指定端口：python harness.py dashboard my-app --port 9000
```

看板展示：
- **状态卡片**：当前轮次、阶段（BUILD/EVALUATE/PAUSED）、通过率、运行时长
- **趋势图**：通过率变化曲线 + 每轮 Build 耗时（Chart.js）
- **评估时间线**：每轮 PASS/NEEDS_WORK 结果及反馈摘要
- **Feature 列表**：所有测试用例，支持 All/Passing/Failing 筛选
- **Git 时间线**：最近 30 条 commit

数据每 5 秒自动刷新。看板是只读的，不影响 harness 运行。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                       run_loop() in loop.py                  │
│                                                              │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌────────┐ │
│   │  BUILD   │ →  │  COMMIT  │ →  │ EVALUATE │ →  │  FEED  │ │
│   │ Builder  │    │ git ckpt │    │Evaluator │    │反馈注入│ │
│   │   Agent  │    │          │    │  Agent   │    │下轮prompt │
│   └──────────┘    └──────────┘    └──────────┘    └────┬───┘ │
│        ↑                                               │     │
│        └───────────────── 循环 ────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

- **Builder Agent**：全权工具（Read / Write / Edit / Bash），可选 Puppeteer MCP
- **Evaluator Agent**：**只读权限**（Read / Glob / Grep / Bash），独立审查，第一行输出 `PASS` 或 `NEEDS_WORK`
- **反馈注入**：`NEEDS_WORK` 反馈拼到下一轮 Builder prompt 开头

### 安全机制（Hooks）

| Hook | 作用 |
|---|---|
| `kill_switch_hook` | `AGENT_STOP` 文件存在时阻断所有工具调用 |
| `steer_hook` | 读取 `STEER.md` 注入指令后清空 |
| `bash_security_hook` | Bash 命令白名单（npm/node/git/ls/cat 等） |
| `track_read_hook` | 记录证据文件（截图/日志）读取记录 |
| `verify_gate_hook` | 未读证据前不允许标记测试通过 |

---

## 退出方式

| 方式 | 语义 | 可恢复 |
|---|---|---|
| `Ctrl+C` | 立即中断 | ✓ 跑 `run` 续上 |
| `harness.py stop ... pause` | 暂停，60s 轮询 | ✓ `resume` 恢复 |
| `harness.py stop ... quit` / `AGENT_QUIT` | 跑完当前轮**优雅退出**（跨平台） | ✗ |
| `--max-iterations N` | 跑满 N 轮 | ✗ |
| `--max-runtime 4h` | 墙钟时间到 | ✗ |
| `--max-stall N` | 连续 N 次 NEEDS_WORK | ✗ |
| 全部 test PASS | 自然完成 | ✗ |

所有退出都会做最终 git commit，不会留烂尾。

---

## 定制

| 想改什么 | 怎么改 |
|---|---|
| 模型 | `--model claude-opus-4-7` |
| 启用浏览器测试 | `--puppeteer` |
| Bash 白名单 | 编辑 `hooks.py` 的 `ALLOWED_COMMANDS` |
| Evaluator 工具 | 编辑 `evaluator.py` 的 `EVALUATOR_TOOLS`（不建议加 Write/Edit） |
| Agent 行为/性格 | 编辑 `prompts/` 下的 `.md` 文件 |

---

## 常见问题

**"第一次跑了 10 分钟还没动静"**
正常。Initializer 在生成测试用例，期间没有可见输出。看到 `[Builder Tool: Write]` 才说明在落盘。

**"Builder 卡在某个 feature 反复跑不过"**
`python harness.py stop my-app pause`，手动改一下 `feature_list.json` 中该 feature 的描述，然后 `resume`。

**"Evaluator 总是 PASS / 总是 NEEDS_WORK"**
编辑 `prompts/evaluator_prompt.md` 调整审查严格度。

**"想看完整的 Agent 输出"**
`python harness.py run my-app 2>&1 | tee run.log`

---

## 文件结构

```
combined-harness/
├── harness.py         # 统一入口（init / run / dashboard / stop / steer）
├── main.py            # 底层入口（harness.py run 的实现）
├── stop.sh            # Shell 版停止脚本（可选）
├── dashboard.py       # Web 看板服务器
├── loop.py            # 主循环：BUILD → COMMIT → EVAL → FEED
├── tracker.py         # 状态/历史数据采集（.harness/ 目录）
├── builder.py         # Builder Agent 工厂
├── evaluator.py       # Evaluator Agent 工厂
├── hooks.py           # PreToolUse hooks（安全 + 证据门 + 操作员控制）
├── progress.py        # feature_list.json 统计
├── prompts.py         # prompt 加载工具
├── prompts/
│   ├── app_spec.template.txt   # spec 模板
│   ├── initializer_prompt.md   # 首次 Session 指令
│   ├── coding_prompt.md        # 后续 Builder 指令
│   └── evaluator_prompt.md     # Evaluator 审查指令
├── requirements.txt
└── generations/                # 项目产物输出目录
```

# Combined Harness — Builder + Evaluator + Feedback Loop

把 [autonomous-coding](../autonomous-coding/) 的 Python 自动循环与 [claude-code-config](../claude-code-config/) 的 hooks 原语**合并**，并新增**独立 Evaluator Agent**，构成完整的反馈闭环。

> 📖 总览与三个 harness 的对比请看 [上层 README](../README.md)。

---

## 架构一览

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

- **Builder Agent**（`builder.py`）：全权工具（Read / Write / Edit / Bash + Puppeteer MCP），系统 Prompt 中明确告诉它"有独立 Evaluator 会审查你的工作"
- **Evaluator Agent**（`evaluator.py`）：**只读权限**（Read / Glob / Grep / Bash），不会被 Builder 自述影响，第一行输出 `PASS` 或 `NEEDS_WORK`
- **反馈注入**：`NEEDS_WORK` 的反馈会拼到下一轮 Builder prompt 开头，强制先修问题再做新 feature

---

## 快速开始

### 前置准备

```bash
# 1. Claude Code CLI（最新版）
npm install -g @anthropic-ai/claude-code

# 2. API Key
export ANTHROPIC_API_KEY='sk-ant-...'

# 3. Python 依赖
cd combined-harness
pip install -r requirements.txt

# 4. Chrome（macOS 默认路径在 builder.py 中已配置）
ls "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

### 初始化新项目（核心三步）

```bash
# Step 1：基于模板写你的 spec
cp prompts/app_spec.template.txt prompts/app_spec.txt
vim prompts/app_spec.txt   # 填充你的产品规格

# Step 2：（可选）调整 Initializer 期望的测试规模
vim prompts/initializer_prompt.md
#  把 "80 tests" 改成 20-30（小项目）/ 200+（大项目）

# Step 3：启动
python main.py --project-dir ./my_new_app
#  生成产物默认落在 combined-harness/generations/my_new_app/
#  绝对路径示例：--project-dir /Users/you/projects/my_app
```

> 📄 写 spec 的模板与规则见 [prompts/app_spec.template.txt](prompts/app_spec.template.txt)。  
> 当前 [prompts/app_spec.txt](prompts/app_spec.txt) 是一份"DevTools 网站"的实际 spec，可参考。

---

## 第一次运行会发生什么（Initializer 阶段）

1. 把 `prompts/app_spec.txt` 拷到 `generations/my_new_app/app_spec.txt`
2. **Initializer Agent** 启动、读 spec
3. 生成 `feature_list.json`（80~200 条带步骤的 e2e test case）—— **这步要 10~20 分钟**，看起来像卡住了其实在写
4. 生成 `init.sh`（项目启动脚本，未来 Agent 用它一键起项目）
5. `git init` + 首次 commit
6. 搭建项目骨架（package.json、目录结构等）

第一次跑完之后，`generations/my_new_app/` 长这样：

```
my_new_app/
├── app_spec.txt              # 拷自 prompts/ 的产品规格
├── feature_list.json         # 单一真源：所有测试用例
├── init.sh                   # Initializer 写的启动脚本
├── claude-progress.txt       # Session 间的进度笔记
├── .claude_settings.json     # Builder 用的安全设置（auto-generated）
├── .claude_evaluator_settings.json  # Evaluator 用的安全设置
├── .git/                     # 第一次 commit 已完成
└── (项目骨架文件，如 package.json、src/ 等)
```

---

## 之后每轮（Build → Evaluate → Feedback）

每个循环 iteration 跑这四个 phase：

| Phase | 谁 | 做什么 |
|---|---|---|
| **BUILD** | Builder Agent（全新 context） | 读 `feature_list.json`，挑一个 `passes: false` 的 feature 实现，用 Puppeteer 截图作证据 |
| **COMMIT** | harness | 自动 `git commit -am "session checkpoint: <时间>"` |
| **EVALUATE** | Evaluator Agent（全新 context） | 只能 Read / Glob / Grep / Bash，第一行输出 `PASS` 或 `NEEDS_WORK` + 详细反馈 |
| **FEEDBACK** | harness | `NEEDS_WORK` 时，反馈拼进下一轮 Builder prompt 开头 |

循环条件：所有 test 通过 / 你 Ctrl+C / 达到 `--max-iterations`。

**中断与恢复**：直接 `Ctrl+C`，跑相同命令即可继续——状态在 `feature_list.json` + git 里。

---

## 运行时操作

文件都放在 `--project-dir` 下。

```bash
PROJECT=combined-harness/generations/my_new_app

# 紧急停止（下次工具调用前就被 kill-switch hook 拒绝）
touch $PROJECT/AGENT_STOP

# 解除停止
rm $PROJECT/AGENT_STOP

# 注入新指令——会通过 steer hook 插到 Agent 上下文里，读完自动清空
echo "改用 TypeScript，并补单元测试" > $PROJECT/STEER.md

# 看当前进度
python -c "import json; d=json.load(open('$PROJECT/feature_list.json')); print(sum(t['passes'] for t in d),'/',len(d))"

# 看 commit 历史
git -C $PROJECT log --oneline

# 跑完后启动生成的应用
cd $PROJECT && ./init.sh
```

---

## 命令行参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `--project-dir` | 项目生成目录；相对路径会拼到 `generations/` 下 | `./project` |
| `--max-iterations` | 最大循环轮数 | 无限 |
| `--model` | Claude 模型 ID | `claude-sonnet-4-5-20250929` |

---

## 文件结构

```
combined-harness/
├── main.py            # 入口：参数解析 + asyncio.run(run_loop)
├── loop.py            # 主循环：BUILD → COMMIT → EVAL → FEED
├── builder.py         # Builder Agent 工厂（全权工具 + Puppeteer + 全 hooks）
├── evaluator.py       # Evaluator Agent 工厂（只读 + 验证输出格式）
├── hooks.py           # 6 个 PreToolUse hooks（见下）
├── progress.py        # feature_list.json 统计 + UI 输出
├── prompts.py         # prompt 文件加载工具
├── prompts/
│   ├── app_spec.template.txt   # spec 模板（你的起点）
│   ├── app_spec.txt            # 当前实际 spec（DevTools 示例）
│   ├── initializer_prompt.md   # 首次 Session 指令
│   ├── coding_prompt.md        # 后续 Builder Session 指令
│   └── evaluator_prompt.md     # Evaluator 审查指令
├── requirements.txt
└── generations/                # 所有产物默认输出到这里
```

---

## Hooks 一览（防御纵深）

`hooks.py` 注册了 6 个 `PreToolUse` hook，按工具匹配：

| Hook | 匹配工具 | 作用 |
|---|---|---|
| `kill_switch_hook` | `*` | 存在 `./AGENT_STOP` 时阻断所有工具调用 |
| `steer_hook` | `*` | 把 `./STEER.md` 内容一次性注入给 Agent 后清空 |
| `bash_security_hook` | `Bash` | Bash 命令白名单（npm / node / git / ls / cat / 等） |
| `track_read_hook` | `Read` | 记录哪些证据文件（截图、日志）被读过 |
| `verify_gate_hook` | `Write\|Edit` | 没读过证据前，不允许修改 `feature_list.json` 的 `passes: true` |
| (Builder-only) | — | 上面这些都加到 Builder；Evaluator 只装 kill_switch + bash_security |

---

## 定制点

### 1. 改模型
```bash
python main.py --project-dir ./my_app --model claude-opus-4-7
```
或在 `main.py:21` 改 `DEFAULT_MODEL`。

### 2. 调测试规模
[prompts/initializer_prompt.md](prompts/initializer_prompt.md) 第 16 行附近的 "80 tests" 改成你想要的数量。

### 3. 放宽/收紧 Bash 白名单
[hooks.py](hooks.py) 的 `ALLOWED_BASH_PREFIXES` 列表。注意：放太宽 = 失去安全保证；放太紧 = Agent 卡住。

### 4. 给 Evaluator 多/少给工具
[evaluator.py:20](evaluator.py) 的 `EVALUATOR_TOOLS`。强烈建议**不要**给 `Write` / `Edit`，否则 Evaluator 会被诱惑去改代码而不是审查。

### 5. 换 Puppeteer 用的浏览器
[builder.py:88-95](builder.py) 的 `PUPPETEER_EXECUTABLE_PATH` 环境变量。

### 6. 改 Initializer / Builder / Evaluator 的"性格"
分别改 [prompts/initializer_prompt.md](prompts/initializer_prompt.md) / [prompts/coding_prompt.md](prompts/coding_prompt.md) / [prompts/evaluator_prompt.md](prompts/evaluator_prompt.md)。

---

## 常见问题

**"第一次跑了 10 分钟还没动静，是不是卡了？"**  
没。Initializer 在写 80~200 条 test case，期间不会有可见的工具输出。看到 `[Builder Tool: Write]` 才说明 feature_list.json 在落盘。

**"Builder 卡在某个 feature 反复跑不过怎么办？"**  
`touch AGENT_STOP` 暂停，手动改一下 feature 描述或 `feature_list.json`，删掉 `AGENT_STOP` 继续。

**"Evaluator 总是 PASS，是不是太宽松？"**  
改 [prompts/evaluator_prompt.md](prompts/evaluator_prompt.md) 强化"对抗式审查"的指令，例如"默认 NEEDS_WORK，除非有明确截图证据"。

**"想看 Builder 和 Evaluator 互相吵了什么？"**  
两个 Session 的全文都在 stdout，可以 `python main.py ... 2>&1 | tee run.log`。

**"Puppeteer 报错 找不到 Chrome"**  
改 [builder.py](builder.py) 的 `PUPPETEER_EXECUTABLE_PATH`。Linux 上一般是 `/usr/bin/google-chrome`。

---

## 与其他 harness 的对比

| | autonomous-coding | claude-code-config | **combined-harness** |
|---|---|---|---|
| 多 Session 自动循环 | ✓ | ✗（需自己写 loop） | ✓ |
| 独立 Evaluator | ✗ | ✗ | ✓ |
| Hooks（kill / steer / verify-gate） | 部分 | ✓ | ✓ |
| 反馈闭环 | ✗ | ✗ | ✓ |
| Token 消耗 | 中 | 低 | 高 |
| 适合 | 学习 / Demo | 已有项目加约束 | **全新项目，无人值守** |

# Autonomous Coding Agent Quickstart

> 来源：[anthropics/claude-quickstarts/autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding)
> 这是 Anthropic 官方提供的**基于 Claude Agent SDK 的自主编码智能体**最小可运行示例

---

## 项目概述

一个最小化的长时间运行自主编码 Harness，实现了**两阶段智能体模式（Initializer + Coding Agent）**，可以跨多个会话构建完整应用。

**示例任务**：自主构建一个 claude.ai 克隆（全栈 Chat 界面），包含 200+ 功能测试用例，耗时数小时自动完成。

## 项目结构

```
autonomous-coding/
├── autonomous_agent_demo.py  # 主入口，解析参数并启动循环
├── agent.py                  # 智能体会话逻辑（核心循环）
├── client.py                 # Claude SDK 客户端配置（安全 + 工具 + MCP）
├── security.py               # Bash 命令白名单与安全校验
├── progress.py               # 进度追踪工具（读取 feature_list.json）
├── prompts.py                # Prompt 加载工具
├── test_security.py          # 安全 Hook 测试
├── requirements.txt          # 依赖：claude-code-sdk>=0.0.25
└── prompts/
    ├── app_spec.txt           # 应用规格说明（要构建什么）
    ├── initializer_prompt.md  # 第一次会话的 Prompt
    └── coding_prompt.md       # 后续会话的 Prompt
```

## 运行方式

```bash
# 安装依赖
npm install -g @anthropic-ai/claude-code
pip install -r requirements.txt

# 设置 API Key
export ANTHROPIC_API_KEY='your-api-key-here'

# 启动（完整运行）
python autonomous_agent_demo.py --project-dir ./my_project

# 限制迭代次数（测试用）
python autonomous_agent_demo.py --project-dir ./my_project --max-iterations 3
```

---

## 核心架构详解

### 1. 主入口 — `autonomous_agent_demo.py`

```python
# 解析参数后启动异步循环
asyncio.run(run_autonomous_agent(
    project_dir=project_dir,
    model=args.model,              # 默认 claude-sonnet-4-5-20250929
    max_iterations=args.max_iterations,  # None 表示无限
))
```

- 项目自动放入 `generations/` 目录下
- `Ctrl+C` 中断后可重新运行同一命令恢复

### 2. 智能体循环 — `agent.py`

核心是一个 **while True 循环**，每次迭代创建全新上下文：

```python
async def run_autonomous_agent(project_dir, model, max_iterations=None):
    # 判断是首次运行还是继续
    tests_file = project_dir / "feature_list.json"
    is_first_run = not tests_file.exists()

    iteration = 0
    while True:
        iteration += 1
        if max_iterations and iteration > max_iterations:
            break

        # 每次创建新的 client（全新上下文窗口）
        client = create_client(project_dir, model)

        # 首次用 initializer prompt，之后用 coding prompt
        if is_first_run:
            prompt = get_initializer_prompt()
            is_first_run = False
        else:
            prompt = get_coding_prompt()

        # 运行单次会话
        async with client:
            status, response = await run_agent_session(client, prompt, project_dir)

        # 3 秒后自动继续下一个会话
        await asyncio.sleep(AUTO_CONTINUE_DELAY_SECONDS)
```

**关键设计**：
- 每次循环创建 **全新 client** = 全新上下文窗口
- 进度通过 `feature_list.json` 和 Git 持久化到磁盘
- 首次运行用 Initializer Prompt，后续用 Coding Prompt
- 会话之间 3 秒延迟自动继续

### 3. 客户端配置 — `client.py`

**三层纵深防御安全模型**：

```python
def create_client(project_dir, model):
    # 安全设置
    security_settings = {
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)", "Write(./**)", "Edit(./**)",
                "Glob(./**)", "Grep(./**)",
                "Bash(*)",           # 实际由 security hook 校验
                *PUPPETEER_TOOLS,    # 浏览器自动化
            ],
        },
    }

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt="You are an expert full-stack developer...",
            allowed_tools=[*BUILTIN_TOOLS, *PUPPETEER_TOOLS],
            mcp_servers={
                "puppeteer": {"command": "npx", "args": ["puppeteer-mcp-server"]}
            },
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                ],
            },
            max_turns=1000,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )
```

**安全层次**：

| 层级 | 机制 | 说明 |
|------|------|------|
| 1 | OS 沙箱 | `sandbox: enabled` — 操作系统级 Bash 隔离 |
| 2 | 文件系统限制 | `Read(./**)` 等 — 只允许访问项目目录 |
| 3 | Bash 白名单 Hook | `bash_security_hook` — 只允许预定义命令 |

**工具集**：
- 内置工具：Read, Write, Edit, Glob, Grep, Bash
- MCP 工具：Puppeteer（浏览器自动化，用于端到端测试）

### 4. 安全 Hook — `security.py`

**白名单方式**——只允许明确列出的命令：

```python
ALLOWED_COMMANDS = {
    # 文件检查
    "ls", "cat", "head", "tail", "wc", "grep",
    # 文件操作
    "cp", "mkdir", "chmod",
    # 目录
    "pwd",
    # Node.js 开发
    "npm", "node",
    # 版本控制
    "git",
    # 进程管理
    "ps", "lsof", "sleep", "pkill",
    # 脚本执行
    "init.sh",
}

# 需要额外验证的命令
COMMANDS_NEEDING_EXTRA_VALIDATION = {"pkill", "chmod", "init.sh"}
```

**敏感命令额外校验**：

- **pkill**：只允许杀 dev 进程（node, npm, npx, vite, next）
- **chmod**：只允许 `+x`（添加执行权限），禁止 `777`、`+w` 等
- **init.sh**：只允许 `./init.sh` 或路径以 `/init.sh` 结尾

**命令解析流程**：

```python
async def bash_security_hook(input_data, tool_use_id=None, context=None):
    command = input_data.get("tool_input", {}).get("command", "")

    # 1. 提取所有命令（处理管道、链式、子 shell）
    commands = extract_commands(command)

    # 2. 解析失败 → 阻止（fail-safe）
    if not commands:
        return {"decision": "block", "reason": "Could not parse command"}

    # 3. 逐一检查白名单
    for cmd in commands:
        if cmd not in ALLOWED_COMMANDS:
            return {"decision": "block", "reason": f"'{cmd}' not allowed"}

        # 4. 敏感命令额外校验
        if cmd in COMMANDS_NEEDING_EXTRA_VALIDATION:
            # pkill / chmod / init.sh 各有专门的验证函数
            ...

    return {}  # 空 dict = 允许执行
```

### 5. 进度追踪 — `progress.py`

```python
def count_passing_tests(project_dir):
    """从 feature_list.json 统计通过/总数"""
    tests_file = project_dir / "feature_list.json"
    tests = json.load(open(tests_file))
    total = len(tests)
    passing = sum(1 for t in tests if t.get("passes", False))
    return passing, total

# 输出示例：Progress: 45/200 tests passing (22.5%)
```

---

## Prompt 设计

### Initializer Prompt（首次会话）

第一个会话的职责——**只做基础设施搭建，不急着写功能**：

```
1. 读取 app_spec.txt（应用规格说明）
2. 创建 feature_list.json — 200 个详细测试用例，全部 "passes": false
3. 创建 init.sh — 环境启动脚本
4. 初始化 Git 仓库并首次提交
5. 搭建项目基本结构
6. （可选）开始实现最高优先级功能
7. 创建 claude-progress.txt 记录进度
```

**feature_list.json 格式**：

```json
[
  {
    "category": "functional",
    "description": "用户可以发送消息并收到流式响应",
    "steps": [
      "Step 1: 导航到聊天页面",
      "Step 2: 在输入框输入消息",
      "Step 3: 点击发送",
      "Step 4: 验证响应逐字流式显示"
    ],
    "passes": false
  }
]
```

**关键规则**：
- 最少 200 个功能，按优先级排序
- 全部 `"passes": false`
- 至少 25 个测试有 10+ 步骤
- **永远不能删除或修改功能描述，只能改 passes 字段**

### Coding Prompt（后续会话）

每个后续会话遵循严格的 **10 步流程**：

```
Step 1: GET YOUR BEARINGS（定位）
  → pwd, ls, cat app_spec.txt, cat feature_list.json, cat claude-progress.txt, git log

Step 2: START SERVERS
  → chmod +x init.sh && ./init.sh

Step 3: VERIFICATION TEST（回归测试 — 必须！）
  → 验证 1-2 个已通过的核心功能仍然正常
  → 发现问题 → 立即标记 passes: false → 先修再做新功能

Step 4: CHOOSE ONE FEATURE
  → 从 feature_list.json 找最高优先级的 passes: false

Step 5: IMPLEMENT THE FEATURE

Step 6: VERIFY WITH BROWSER AUTOMATION（通过 Puppeteer 端到端验证）
  → 必须通过 UI 交互验证，不能只用 curl
  → 截图验证功能和视觉效果

Step 7: UPDATE feature_list.json
  → 只修改 "passes": false → "passes": true
  → 永远不要删除、编辑描述或重排测试

Step 8: COMMIT YOUR PROGRESS

Step 9: UPDATE PROGRESS NOTES
  → 更新 claude-progress.txt

Step 10: END SESSION CLEANLY
  → 提交所有代码，确保无未提交更改
```

### app_spec.txt（应用规格示例）

示例是构建一个 **claude.ai 克隆**，包含：

- React + Vite 前端 / Node.js + Express + SQLite 后端
- 核心功能：流式聊天、Artifact 渲染、对话管理、项目组织、模型选择
- 完整 UI 布局规格、设计系统、API 端点
- 数据库 Schema（users, conversations, messages, artifacts 等 10+ 表）

---

## 生成的项目结构

运行后项目目录内容：

```
my_project/
├── feature_list.json         # 测试用例（真相之源）
├── app_spec.txt              # 应用规格
├── init.sh                   # 环境启动脚本
├── claude-progress.txt       # 跨会话进度记录
├── .claude_settings.json     # 安全配置
└── [application files]       # 生成的应用代码
```

---

## 核心设计模式总结

| 模式 | 实现方式 | 解决的问题 |
|------|----------|-----------|
| **两阶段智能体** | Initializer（搭建） + Coding（编码） | 首次运行 vs 后续运行的不同需求 |
| **全新上下文循环** | 每次迭代 `create_client()` | 上下文窗口耗尽 |
| **JSON 功能合约** | `feature_list.json`，只能改 passes | 防止智能体篡改需求 |
| **纵深防御安全** | 沙箱 + 文件系统限制 + Bash 白名单 | 自主运行时的安全保障 |
| **端到端浏览器验证** | Puppeteer MCP 截图 + 交互 | 防止"自我欺骗"式的假通过 |
| **磁盘持久化进度** | feature_list.json + claude-progress.txt + Git | 跨会话状态传递 |
| **回归测试优先** | Coding Prompt Step 3 强制验证已通过功能 | 防止新功能破坏旧功能 |
| **单功能聚焦** | 每次会话只做一个功能 | 防止上下文耗尽和半成品 |

---

## 与 cwc-long-running-agents 的对比

| 维度 | autonomous-coding（本项目） | cwc-long-running-agents |
|------|---------------------------|------------------------|
| **运行方式** | Python 脚本 + Agent SDK | Claude Code Hooks + Bash 循环 |
| **安全模型** | Python 函数级 Hook（白名单） | Shell 脚本 Hook |
| **评估方式** | 智能体自行用 Puppeteer 验证 | 独立评估器子智能体（无 Write 权限） |
| **合约文件** | `feature_list.json`（数组） | `test-results.json`（对象） |
| **操作员控制** | Ctrl+C 中断 | kill-switch.sh + steer.sh |
| **适用场景** | 完整的自动化编码管线 | 可组合的原语积木 |

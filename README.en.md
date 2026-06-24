# Claude Harness — Best Practices for Long-Running Autonomous Coding Agents

Best practices and reference implementations for building **long-running autonomous coding agents** with **Claude Code** and the **Claude Agent SDK**.

This repository contains three independent harness implementations and several reference guides on agent harness design. If you want Claude to code autonomously for hours or days — across multiple sessions, with evidence-driven testing, independent evaluation, and human-in-the-loop control — these harnesses solve the hard problems: context window exhaustion, self-grading bias, unattended drift, and session handoff.

> **[中文版 README](README.md)**

---

## Best Practices Covered

| Practice | How it works |
|---|---|
| **Session isolation** | Fresh context window per iteration; state persisted to disk via `PROGRESS.md`, `feature_list.json`, and git commits — no context window ceiling |
| **Evidence-driven testing** | Agent must Read screenshot / console log evidence before marking a test as passing; enforced by a `verify-gate` hook |
| **Independent evaluation (Builder-Evaluator pattern)** | A separate Evaluator agent (read-only, no Write/Edit) reviews Builder output — prevents self-grading bias (generator-evaluator architecture) |
| **Human-in-the-loop control** | `AGENT_STOP` kill switch halts all tool calls; `STEER.md` injects operator instructions mid-run |
| **Feedback loop** | `NEEDS_WORK` findings from the Evaluator are injected into the next Builder prompt, driving iterative improvement |
| **Structured handoff protocol** | Each session reads progress → picks one feature → implements → commits → updates handoff notes for the next session |
| **Defense-in-depth security** | OS sandbox + filesystem restrictions + Bash command allowlist — safe for unattended autonomous coding |
| **Incremental progress** | One feature per session; codebase stays merge-ready at every checkpoint |

---

## Repository Structure

```
claude-harness/
├── autonomous-coding/          # Anthropic's official two-agent autonomous coding demo
├── claude-code-config/         # Long-running primitives via native Claude Code hooks
├── combined-harness/           # Merged: Builder + Evaluator feedback loop (recommended)
├── autonomous-coding-quickstart.md
├── effective-harnesses-for-long-running-agents.md
└── harness-design-long-running-apps.md
```

---

## Sub-projects

### 1. [autonomous-coding/](autonomous-coding/) — Anthropic Official Demo

A minimal harness from [anthropics/claude-quickstarts](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding): **Initializer + Coding Agent** two-agent pattern that builds complete applications over multiple sessions.

- Each session gets a fresh context window
- Progress tracked via `feature_list.json` (200+ test cases) and git commits
- Defense-in-depth security: OS sandbox + filesystem allowlist + Bash command allowlist
- Entry point: [autonomous-coding/autonomous_agent_demo.py](autonomous-coding/autonomous_agent_demo.py)

### 2. [claude-code-config/](claude-code-config/) — Claude Code Hooks Primitives

Long-running agent primitives implemented as **native Claude Code hooks** — no Python harness needed, just copy `.claude/` into your project:

| Hook | What it does |
|---|---|
| `kill-switch.sh` | Halts all tool calls while `AGENT_STOP` file exists |
| `steer.sh` | Injects `STEER.md` content into the agent, then clears the file |
| `track-read.sh` + `verify-gate.sh` | Blocks marking tests as passing until evidence (screenshot/log) has been Read |
| `commit-on-stop.sh` | Auto-commits tracked changes at session end |
| `CLAUDE.md` | Conventions: read PROGRESS.md first, one feature at a time, proof before passing |

### 3. [combined-harness/](combined-harness/) — Full Feedback Loop (Recommended)

Merges the Python automation loop with Claude Code hooks and adds an **independent Evaluator Agent**:

```
BUILD  → Builder Agent implements one feature (full tools + Puppeteer)
COMMIT → Automatic git checkpoint
EVAL   → Independent Evaluator Agent reviews from scratch (read-only)
FEED   → NEEDS_WORK feedback injected into next Builder prompt
```

Entry point: [combined-harness/main.py](combined-harness/main.py)

---

## Which Path to Choose

| Scenario | Path | Effort |
|---|---|---|
| Existing project — just want kill switch, verify-gate, auto-commit constraints | **Path A** ([claude-code-config/](claude-code-config/)) | Light |
| **New project** — drop in a spec, come back hours later to a working app with Evaluator checks | **Path B** ([combined-harness/](combined-harness/)) | Medium (recommended) |
| Learning — run Anthropic's official demo as-is | Path C ([autonomous-coding/](autonomous-coding/)) | Medium |

Trade-off: **Path B burns significantly more tokens** (every feature gets an independent Evaluator pass), but output quality is much more stable.

---

## Quick Start (Path B — Recommended)

```bash
# Prerequisites
npm install -g @anthropic-ai/claude-code
export ANTHROPIC_API_KEY='sk-ant-...'

# Setup
cd combined-harness
pip install -r requirements.txt

# Write your spec
cp prompts/app_spec.template.txt prompts/app_spec.txt
# Edit prompts/app_spec.txt with your product specification

# Launch (first run auto-generates project skeleton + 80-200 e2e test cases)
python main.py --project-dir ./my_new_app
```

Full documentation: [combined-harness/README.md](combined-harness/README.md)

---

## Runtime Controls

All controls operate via files in the project directory — no restart needed:

```bash
# Pause (agent polls every 60s; remove file to resume)
touch AGENT_STOP
rm AGENT_STOP

# Graceful exit after current iteration
touch AGENT_QUIT

# Inject new instructions mid-run (auto-cleared after read)
echo "Switch to TypeScript and add unit tests" > STEER.md

# Check progress
python -c "import json; d=json.load(open('feature_list.json')); print(sum(t['passes'] for t in d),'/',len(d))"
```

---

## Core Design Principles

1. **Session isolation** — fresh context per iteration; state on disk (`PROGRESS.md` / `feature_list.json` / git). Context size is no longer a ceiling.
2. **Evidence-driven** — agent cannot self-report "done"; screenshots/logs must be Read before marking tests passing. `verify-gate` hook enforces this.
3. **Independent review** — Evaluator has no Write/Edit, no Puppeteer, no access to Builder's reasoning. Prevents self-grading.
4. **Human-in-the-loop** — `AGENT_STOP` for emergency halt, `STEER.md` for mid-run instruction injection.

---

## Reference Materials

Summarized from Anthropic Engineering blog posts:

| Local document | Original |
|---|---|
| [effective-harnesses-for-long-running-agents.md](effective-harnesses-for-long-running-agents.md) | [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) |
| [harness-design-long-running-apps.md](harness-design-long-running-apps.md) | [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) |
| [autonomous-coding-quickstart.md](autonomous-coding-quickstart.md) | [anthropics/claude-quickstarts — autonomous-coding](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding) |

---

## Requirements

| Item | Version / Notes |
|---|---|
| Python | 3.10+ |
| Node.js | For Claude Code CLI and Puppeteer MCP |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Claude Agent SDK | `pip install claude-code-sdk>=0.0.25` |
| Chrome | Required for Puppeteer screenshots in Path B |
| Environment variable | `ANTHROPIC_API_KEY` |

---

## Keywords

claude code harness, claude agent sdk, long running agent, autonomous coding agent, AI coding agent, agentic coding, multi-agent orchestration, builder evaluator pattern, generator evaluator architecture, claude code best practices, claude code hooks, context window management, session management, agent session handoff, evidence driven testing, kill switch, agent steering, human in the loop, unattended coding, claude code automation, agent harness design, multi-session agent, autonomous app development

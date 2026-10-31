# Introducing Forthmark

**English** · [中文](introduction.zh-CN.md)

## In one sentence

**Forthmark is a project layer above your coding agents. Agents jot down conclusions as they work, so you can see where every project stands, who it's blocked on and what's next — without opening a session or digging through docs — and handle what's waiting on you right from the panel. Sessions and execution stay with your own agent.**

## Summary

When you push real work forward with agents (Claude Code and others), what you know lives in two places: inside sessions and in markdown files. To find out where a project stands, you either open a session and ask the agent to reread everything (tokens and waiting), or dig through PLAN / TODO / PROGRESS yourself. With several projects, long timelines, clients and teammates to wait on, and constant interruptions, things quietly stop moving.

Forthmark doesn't change how you use your agent. It has the agent record **conclusions** with a few commands at the moment it learns them — tasks, waiting items, bugs, decisions, the next step — and hands that status to you as a panel, a menu bar count, a terminal status line and reminders. Decisions you make in the panel flow back into the running session. No LLM is called and nothing is written into your projects; choosing sessions, talking and changing code remain the agent's job.

## At a glance

**See it**
- What's being worked on, progress, phase and next step — per project, at a glance
- Who's blocking: waiting on your decision / your action / a client / a teammate / someone external — for how long, and which tasks it blocks
- Cadence: whether the project moved each day of the last three weeks, day N of the project, active days so far, and done vs. scope over time
- A map of docs: scattered markdown and scripts grouped by purpose, progress sources pinned, changed files flagged

**Remember it**
- The agent records as it works (commands, a few hundred tokens); a hook checks that it did
- Interruptions pause the task with a resume note, so you see exactly where it stopped
- Finished items can be verified against files, so "marked done" means done
- Resolved waits, closed bugs and past decisions stay browsable

**Act on it**
- Record a decision, "I'm done" or "they replied" in the panel; the running session hears about it
- ＋ New project: folder, tracking, and your agent opened in a terminal; the first message is yours
- ＋ / ▶ / ☰: new session, most recent session, the agent's own session picker — shortcuts to the agent's native features

**Stay out of the way**
- A number in the menu bar, one line in the terminal, notifications only when something is overdue
- Zero intrusion: nothing written into projects, git only read
- No LLM calls; its own overhead is visible ("tool overhead N+")

## In detail

### 1. The pains

| Pain | What it looks like |
|---|---|
| You must open a session to learn the status | Ask the agent "where are we?" and it rereads the markdown and git log — tens of thousands of tokens, plus waiting |
| Markdown multiplies, the big picture disappears | PLAN / TODO / PROGRESS / specs spread across the repo; which are current, which still matter? |
| Blocked on someone, then forgotten | Waiting on a client's confirmation, a teammate's access, your own call — buried in docs and chats until work stops |
| Interrupted, never back | Something cuts in halfway; days later you can't remember where you were |
| Re-explaining context | Every new session needs the project's state explained again |
| Ideas are expensive to start | Terminal, folder, agent, explaining the idea, setting up tracking |

### 2. Design principles

1. **A project layer that leaves the agent alone.** The unit is the project (a git repository root) and the things in it, not the session. Session lists, naming, conversation and code changes are the agent's core features; we don't duplicate them.
2. **Record at the moment of knowing, not summarize afterwards.** The agent knows best what just happened while it's working; recording one conclusion then is cheapest and most accurate. We never read session content or call an LLM to summarize, so we don't depend on any agent's internal formats either.
3. **Helpful, but restrained.** The agent only gets two things from us: the user's own words and the project's factual state. We don't instruct it on the user's behalf and don't repeat what it already knows.
4. **Zero intrusion.** All data lives in `~/.forthmark/`; nothing is written into projects; git is read-only.
5. **Visible, not noisy.** Information shows up where you already look (menu bar, terminal status line); reminders only when something is overdue.
6. **Transparent cost.** No LLM calls; the extra turns caused by hooks are counted exactly and shown.

### 3. How it works

```
Your agent (Claude Code …)
  ├─ Session start: a hook injects the recording rules + the project's status (not again when resuming)
  ├─ While working: runs forthmark.py op … (add a task, record a wait, fix a bug, decide, pause…)
  ├─ Each message you send: a hook passes on what you did in the panel
  └─ End of each turn: a hook checks the status kept up (asks the agent to catch up if not), verifies, archives, refreshes the panel
                         │
             ~/.forthmark/projects/<project>/status.json
                         │
  Panel (menu bar popover / window / browser) · menu bar count · terminal status line · notifications
                         │
  You: check progress, handle what waits on you, start projects, open sessions ──→ back to the agent
```

### 4. Features

| Area | What it does |
|---|---|
| Now | Tasks in progress and bugs being fixed (urgent ones marked ⚡), paused tasks with resume notes, long-running warnings, recently done |
| Who's blocking | Grouped by whom you wait on, sorted by how many tasks each unblocks, nudge suggestions after 3 days with a ready-to-send message, record decision / I'm done / they replied, resolved items browsable |
| Next | The most valuable task that isn't blocked right now |
| Cadence | 21-day activity strip (drawn from the project's first day), day N / active days, burn-up of done vs. total tasks |
| Tasks / Bugs | In progress / paused / to do / done; blocked tasks show what blocks them and link to it; closed bugs list |
| Activity | Timeline; changes since you last looked are marked new |
| Docs | Docs map, progress sources, purposes, tags / notes / pin / hide, preview (own window) |
| Menu bar app | Count, popover (auto height), window, launch at login, notifications |
| Terminal status line | Current task, items waiting on you, paused, progress |
| Entry points | ＋ new project; ＋ / ▶ / ☰ new / most recent / session picker |

### 5. Non-goals

- No session management (lists, naming, search) — agent clients do it better
- No scheduling or orchestrating multiple agents in parallel
- No instructions on the user's behalf, no judgments on the agent's behalf
- No reading session content, no LLM calls
- No writing into projects, no touching their git
- Not a full project management tool (permissions, team collaboration, Gantt charts)

### 6. Relationship to agent clients

Clients such as the Claude desktop app and Codex are organized around **sessions**: great at conversation, reviewing changes and managing sessions. Forthmark is organized around **projects and the things in them**, adding project state that spans sessions and days — and "waiting", which clients don't track at all. They don't compete; they stack: use whichever client you like, and the project's state lives in one place.

### 7. Who it's for

| A good fit | An agent client alone may be enough |
|---|---|
| Several projects in parallel, long timelines | One or two projects, a single rhythm |
| Often blocked on others (clients, teammates, reviews) | No external dependencies |
| Frequent interruptions and switching | Rarely switching |
| Don't want to open sessions and spend tokens just to see progress | Happy to ask the agent any time |

### 8. Status and limits

Early preview (v0.1):

- Full support for **macOS + Claude Code (CLI)**; the Claude desktop app's Code tab should share the same settings but is not verified
- Codex / Cursor etc. can use the "new project / open session" shortcuts (commands are configurable); recording waits for the MCP entry point
- English and Chinese interface, following the macOS language
- Windows: a preview after v0.1 (core recording, hooks, browser panel, status line)
- Full scope: [README → Scope and limits](../README.md#scope-and-limits)

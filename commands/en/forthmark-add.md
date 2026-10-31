---
description: Track this project with Forthmark (nothing is written into the project)
allowed-tools: Bash({CLI}:*)
---

!`{CLI} add . 2>&1`

Above are the result and the recording rules. Once tracked:

1. From now on, maintain the status file (path in the output) following the rules above; don't create or change any status-related files in the project folder.
2. If the status file still has only its initial content, initialize it now: skim the project's README, docs, todo / bug / plan markdown and the last 20 git log entries, and distill the goal, phases, tasks, waiting items, bugs, decisions and next step. Write only what a person needs to see at a glance; less is more. Don't invent what you can't tell; leave it empty. For past events recovered from git log or docs where only the date is known, use `T00:00` of that day with the time zone; don't guess the time.
3. Run `{CLI} docs` to list the project's docs, and run `forthmark.py doc` once for each main one (plans, specs, guides, progress, to-do, AGENTS.md, …) to record its role and a one-sentence purpose; README and minor files can be skipped.
4. Run the validation command, then `{CLI} show .` and show its output as-is in a code block.
5. Finally tell the user the panel is at `~/.forthmark/panel.html` and refreshes at the end of every turn.

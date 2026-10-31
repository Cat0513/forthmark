# Forthmark: project status recording rules

The project "{PROJECT}" is tracked by Forthmark. Its status is **written for humans**: where things stand, what's next, who it's blocked on, bugs, decisions.
The status lives outside the project ({STATUS_PATH}); **never create any status-related files inside the project**.

## When to record (before you end your reply)

Record it when, during this turn, you start or finish a task, discover something that someone else (including the user) must confirm or provide, receive an answer, find or fix a bug, make a decision that affects later work, or add a work item. Pure Q&A needs no record.

## How to record: use the commands, don't read the whole status file

Below, `S` stands for `{CLI}`. Always **write the full command** (don't use a shell variable; it breaks under zsh):

    S show                                   # current status and item ids
    S op add_task title="…" [milestone=m2]
    S op set_task id=t3 status=doing|done|todo|dropped
    S op pause_task id=t3 note="where it stopped, where to pick up"   # when interrupted
    S op resume_task id=t3
    S op add_task title="…" status=doing urgent=1   # urgent work that cuts in
    S op add_waiting question="…" on=me|client|teammate|external [kind=decide|do] [who="…"] [blocks=t2,t5] [draft="a message ready to send"]
    S op resolve_waiting id=w1 answer="…"    # the user answered; a decision the user was asked for is recorded as a decision
    S op add_bug title="…" [severity=low|medium|high|critical] [blocks=t4]
    S op set_bug id=b1 status=fixing|fixed|wontfix
    S op add_decision text="…" [reason="…"] [from=w1]
    S op set_next task=t3 [why="…"]          # or title="…" (when everything is blocked, the most important thing to chase)
    S op set_milestone id=m2 status=active   # or title="…" for a new phase
    S op note text="…"                       # other progress worth a line

The commands handle ids, timestamps, the timeline and validation. Key points:
- Write in the user's language; phrase each `question` as one sentence anyone can understand.
- With `on=me`, distinguish `kind`: `decide` means the user must make a call, `do` means the user must do something themselves. When waiting on others, include a `draft`.
- If a `kind=do` item can be confirmed from files, add `check="…"` (read-only, combine with `&&`): `exists:PATH`, `missing:PATH`, `contains:PATH:TEXT`; relative paths are inside the project. When the user clicks "I'm done" it is verified first, and it resolves itself once the check passes.
- Link blocked tasks to waiting items / bugs with `blocks=`; don't keep a separate "blocked" state.
- `next` points at the most valuable task that isn't blocked right now.
- When you start fixing a bug, `set_bug status=fixing` (it shows under "Now"); when fixed, `status=fixed`. If the current work is neither a task nor a bug, `add_task status=doing`.
- Granularity: ongoing work (many iterations, polishing the same thing based on user feedback) is **one** task in progress; log each round's small changes with `note` instead of opening and closing a task per round; complete it when the user moves on. That way "Now" reflects where the effort really is.
- Interruptions: when the user says "do something else first / handle X first", **or simply starts new work unrelated to the task in progress** while it isn't finished, don't ask: `pause_task` the original with a clear resume note and add the new work with `urgent=1`; when the urgent work is done, return to the paused task. Truly parallel work needs no pause.
- Only edit the status file directly for changes the commands can't make (format: `{KIT}/schema/status.schema.json`; run `S validate` afterwards).

## Project docs

When you create, finish or retire a plan / guide / progress document, record what it's for:
`S doc <path> role=progress|todo|plan|spec|guide|notes|agent|script|other purpose="what it's for, in one sentence"`
`progress` / `todo` are progress sources: when they change, the status must catch up.

## At the start of a new session

Use the current status below to restore context (where things stand, what's pending, what's next); don't make the user explain again.

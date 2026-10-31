---
description: Show this project's progress, who it's blocked on, and what's next (Forthmark)
allowed-tools: Bash({CLI}:*)
---

!`{CLI} show . 2>&1`

Show the output above to the user as-is in a code block; don't rewrite it or add analysis.
If the output starts with "not tracked", tell the user this project isn't tracked yet and that `/forthmark-add` will track it (nothing in the project is changed).

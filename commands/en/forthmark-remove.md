---
description: Stop tracking this project with Forthmark (status data is kept)
allowed-tools: Bash({CLI}:*)
---

!`{CLI} remove . 2>&1`

Relay the output above to the user: the project is no longer tracked, its status data is still kept in the central folder, and `/forthmark-add` brings it back.

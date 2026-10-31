---
description: 停止用 Forthmark 跟踪当前项目（状态数据保留）
allowed-tools: Bash({CLI}:*)
---

!`{CLI} remove . 2>&1`

把上面的输出转述给用户：项目已停止跟踪，状态数据仍保留在集中目录，以后 `/forthmark-add` 可以恢复。

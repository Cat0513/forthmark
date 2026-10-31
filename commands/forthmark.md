---
description: 查看当前项目的进度、卡在谁、下一步（Forthmark）
allowed-tools: Bash({CLI}:*)
---

!`{CLI} show . 2>&1`

把上面的输出原样放进一个代码块展示给用户，不要改写、不要补充分析。
如果输出以 "not tracked" 开头，告诉用户当前项目还没接入，输入 `/forthmark-add` 即可（不会改动项目里的任何文件）。

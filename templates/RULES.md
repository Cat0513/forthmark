# Forthmark：项目状态记录规则

项目「{PROJECT}」由 Forthmark 跟踪，状态是**给人看的**：做到哪、下一步、卡在谁、bug、决定。
状态存在项目之外（{STATUS_PATH}），**不要在项目里建任何状态相关文件**。

## 何时记录（结束本轮回复前）

本轮开始/完成任务、发现要别人（含用户）确认或提供的事、得到答复、发现/修复 bug、做出影响后续的决定、新增工作项时，记录下来。纯问答不用记。

## 怎么记录：用命令，不要读整个状态文件

下面的 `S` 代表 `{CLI}`，执行时**写完整命令**（不要用 shell 变量，zsh 下会失败）：

    S show                                   # 看当前状态和各项 id
    S op add_task title="…" [milestone=m2]
    S op set_task id=t3 status=doing|done|todo|dropped
    S op pause_task id=t3 note="做到哪、回来从哪继续"   # 被别的事打断时
    S op resume_task id=t3
    S op add_task title="…" status=doing urgent=1   # 插队的事
    S op add_waiting question="…" on=me|client|teammate|external [kind=decide|do] [who="…"] [blocks=t2,t5] [draft="可直接发给对方的话"]
    S op resolve_waiting id=w1 answer="…"    # 用户给了答复；等你决定的会自动记成决策
    S op add_bug title="…" [severity=low|medium|high|critical] [blocks=t4]
    S op set_bug id=b1 status=fixing|fixed|wontfix
    S op add_decision text="…" [reason="…"] [from=w1]
    S op set_next task=t3 [why="…"]          # 或 title="…"（全被卡住时写最该催的事）
    S op set_milestone id=m2 status=active   # 或 title="…" 新建阶段
    S op note text="…"                       # 其他值得记一笔的进展

id、时间、时间线、格式校验都由命令完成。要点：
- 用用户的语言写；`question` 写成能直接看懂的一句话。
- `on=me` 时分清 `kind`：`decide` 要用户拍板，`do` 要用户亲自去做。等别人时写 `draft`。
- `kind=do` 的事项如果能从文件判断是否做完，加 `check="…"`（只读，可用 `&&` 组合）：`exists:路径`、`missing:路径`、`contains:路径:文字`；相对路径在项目内。用户点「我做完了」时会先核实，满足了也会自动标完成。
- 任务被卡住用 `blocks=` 关联到等待项 / bug，不要另存"阻塞"状态。
- `next` 指向当前没被卡住、最值得做的任务。
- 开始修一个 bug 时 `set_bug status=fixing`，它会出现在「现在在做」里；修完 `status=fixed`。正在做的事既不是任务也不是 bug 时，`add_task status=doing`。
- 记录的粒度：持续性的工作（多轮迭代、根据用户反馈反复打磨同一块）记成**一个**进行中的任务，每轮的小修改用 `note` 记一笔，不要每轮各开一个任务再当场完成；用户转去做别的事时再把它完成。这样「现在在做」能反映真实的工作重心。
- 被打断时：用户说"先做别的 / 先处理一下 X"，**或者直接开始了一件与正在做的任务无关的新工作**，而原来的任务还没完成——不用问，把原任务 `pause_task` 并写清恢复要点，新事用 `urgent=1` 插队；插队的事完成后回到被暂停的任务。真是并行推进的就不用暂停。
- 命令覆盖不到的修改，才直接编辑状态文件（格式见 `{KIT}/schema/status.schema.json`，改完运行 `S validate`）。

## 项目文档

新建、完成或废弃方案 / 指南 / 进度类文档时，登记作用：
`S doc <路径> role=progress|todo|plan|spec|guide|notes|agent|script|other purpose="一句话作用"`
`progress` / `todo` 是进度来源：它们更新了，状态也要跟上。

## 新会话开始时

用下面的当前状态恢复上下文（做到哪、在等什么、下一步），不要让用户重新解释。

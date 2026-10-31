#!/usr/bin/env python3
"""Fictional demo projects, for screenshots and trying the panel without touching real data.

  python3 tools/demo.py [DIR] [--lang=en]   build the demo in DIR (default ~/.forthmark-demo), then show how to open it

Everything lives under DIR: a separate data dir (DIR/data) and the fake project folders with backdated git
history (DIR/projects). Your real ~/.forthmark and ~/.claude are never touched. Dates are relative to
today, so the panel always looks current; run it again to refresh.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
LANG = "en" if "--lang=en" in sys.argv else "zh"
ROOT = Path(ARGS[0] if ARGS else "~/.forthmark-demo").expanduser().resolve()
MARKER = ROOT / ".forthmark-demo"
os.environ["FORTHMARK_HOME"] = str(ROOT / "data")  # before importing forthmark: it reads HOME at import
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forthmark  # noqa: E402

TODAY = date.today()


def day(n):
    return (TODAY - timedelta(days=n)).isoformat()


def at(n, hour=15, minute=0):
    t = datetime.combine(TODAY - timedelta(days=n), datetime.min.time()).replace(hour=hour, minute=minute)
    return t.astimezone().isoformat(timespec="seconds")


PROJECTS = [
    {
        "folder": "order-export",
        "goal": "运营可以按条件筛选订单并导出报表，月中上线",
        "name": "订单后台 · 报表导出",
        "deadline": day(-12),
        "started": 19,
        "commit_days": [19, 18, 16, 15, 14, 12, 11, 9, 8, 7, 5, 4, 2, 1, 0],
        "docs": {"docs/export-spec.md": "# 报表导出方案\n\n## 字段\n\n订单号、下单时间、金额（仅财务可见）、状态。\n\n## 待确认\n\n- 是否需要 Excel\n",
                 "TODO.md": "# TODO\n\n- [x] 导出任务队列\n- [ ] 报表模板\n- [ ] 前端筛选面板\n",
                 "README.md": "# order-export\n"},
        "milestones": [{"id": "m1", "title": "方案", "status": "done"},
                       {"id": "m2", "title": "开发", "status": "active", "due": day(-5)},
                       {"id": "m3", "title": "联调验收", "status": "pending", "due": day(-12)}],
        "tasks": [("t1", "梳理导出字段与权限", "done", "m1", 17), ("t2", "导出任务队列", "done", "m2", 9),
                  ("t3", "报表模板（Excel）", "todo", "m2", None), ("t4", "订单筛选接口加分页", "doing", "m2", 1),
                  ("t5", "导出文件下载与过期清理", "todo", "m2", None), ("t6", "前端筛选面板", "todo", "m2", None),
                  ("t7", "测试环境联调", "todo", "m3", None), ("t8", "金额字段权限控制", "done", "m2", 5),
                  ("t9", "导出进度提示", "done", "m2", 2),
                  ("t10", "导出操作审计日志", "paused", "m2", 4)],
        "paused_note": {"t10": "表结构已定，写入还没做；回来先接导出完成时的写入"},
        "next": {"task": "t6", "why": "t4 被跨月漏数据 bug 卡住，前端可以先按接口约定开发"},
        "waiting": [
            {"id": "w1", "question": "导出是否需要支持 Excel，还是只要 CSV？", "waiting_on": "client", "who": "甲方产品 王经理",
             "since": day(6), "blocks": ["t3"], "status": "open", "ref": "docs/export-spec.md",
             "message_draft": "王经理您好，关于订单报表导出想确认一下：只需要 CSV，还是也需要 Excel（含多 sheet 与格式）？这会影响报表模板的实现，麻烦这两天给个答复，谢谢！"},
            {"id": "w2", "question": "测试环境的对象存储权限", "waiting_on": "teammate", "who": "运维 小陈", "since": day(2),
             "blocks": ["t5", "t7"], "status": "open",
             "message_draft": "小陈，报表导出需要测试环境 OSS 的读写权限（bucket: report-test），方便的时候帮开一下，影响下载功能联调，谢谢～"},
            {"id": "w3", "question": "导出文件保留几天？", "waiting_on": "me", "kind": "decide", "since": day(1),
             "blocks": ["t5"], "status": "open"},
            {"id": "w4", "question": "导出是否需要按角色限制字段？", "waiting_on": "client", "who": "甲方产品 王经理",
             "since": day(14), "status": "resolved", "answer": "财务角色可见金额字段，其他角色隐藏", "resolved_at": day(11)},
        ],
        "bugs": [{"id": "b1", "title": "筛选时间跨月时漏数据", "severity": "high", "status": "fixing", "blocks": ["t4"]},
                 {"id": "b2", "title": "导出文件名中文乱码", "severity": "low", "status": "fixed", "closed_at": day(3)}],
        "decisions": [{"date": day(11), "decision": "金额字段仅财务角色可见", "from_waiting": "w4"},
                      {"date": day(13), "decision": "导出走异步任务队列，不同步生成", "reason": "大数据量会超时"}],
        "events": [(1, "waiting", "新增等待：导出文件保留几天（等你决定）"), (1, "bug", "发现 bug：筛选时间跨月漏数据"),
                   (2, "waiting", "等运维开测试环境 OSS 权限"), (2, "done", "完成：导出进度提示"),
                   (3, "bug", "修复：导出文件名中文乱码"), (4, "note", "暂停：导出操作审计日志"), (5, "done", "完成：金额字段权限控制"),
                   (6, "waiting", "向甲方确认是否需要 Excel"), (9, "done", "完成：导出任务队列"),
                   (11, "decision", "决策：金额字段仅财务角色可见"), (13, "decision", "决策：导出走异步任务队列"),
                   (17, "done", "完成：梳理导出字段与权限"), (19, "note", "开始记录项目状态")],
    },
    {
        "folder": "booking-miniapp",
        "goal": "门店预约小程序：用户选时间、门店确认、到店核销",
        "name": "预约小程序",
        "deadline": None,
        "started": 12,
        "commit_days": [12, 11, 10, 8, 7, 6, 3, 2, 0],
        "docs": {"PLAN.md": "# 计划\n\n1. 预约流程\n2. 门店端确认\n3. 核销\n", "docs/api.md": "# 接口\n\n- POST /bookings\n",
                 "AGENTS.md": "# 给 agent 的说明\n\n用 TypeScript，接口写在 docs/api.md。\n"},
        "milestones": [{"id": "m1", "title": "用户端", "status": "active"}, {"id": "m2", "title": "门店端", "status": "pending"}],
        "tasks": [("t1", "预约时间选择", "done", "m1", 8), ("t2", "预约提交与通知", "doing", "m1", 0),
                  ("t3", "我的预约列表", "paused", "m1", 3), ("t4", "门店确认页", "todo", "m2", None),
                  ("t5", "到店核销", "todo", "m2", None), ("t6", "登录与手机号授权", "done", "m1", 10)],
        "paused_note": {"t3": "列表接口已通，分页还没做；回来先补下拉加载"},
        "urgent": ["t2"],
        "next": {"task": "t4", "why": "用户端提交做完后，门店端可以并行开始"},
        "waiting": [
            {"id": "w1", "question": "小程序订阅消息模板谁来申请？", "waiting_on": "me", "kind": "do", "since": day(2),
             "blocks": ["t2"], "status": "open"},
            {"id": "w2", "question": "门店营业时间数据从哪里来", "waiting_on": "external", "who": "门店系统供应商", "since": day(4),
             "blocks": ["t4"], "status": "open",
             "message_draft": "您好，我们在做门店预约，需要拿到各门店的营业时间，请问有没有接口或导出文件可以提供？"},
        ],
        "bugs": [{"id": "b1", "title": "iOS 上时间选择器滚动卡顿", "severity": "medium", "status": "fixing"}],
        "decisions": [{"date": day(9), "decision": "先只做微信小程序，不做 H5", "reason": "门店客户主要在微信里"}],
        "events": [(0, "note", "插队：预约提交与通知（门店要先演示）"), (2, "waiting", "新增等待：订阅消息模板谁来申请（等你去做）"),
                   (3, "note", "暂停：我的预约列表"), (4, "waiting", "等供应商提供门店营业时间"),
                   (6, "bug", "发现 bug：iOS 上时间选择器滚动卡顿"), (8, "done", "完成：预约时间选择"),
                   (9, "decision", "决策：先只做微信小程序"), (10, "done", "完成：登录与手机号授权"), (12, "note", "开始记录项目状态")],
    },
    {
        "folder": "blog-redesign",
        "goal": "个人博客换成静态站，文章迁移，加订阅",
        "name": "博客改版",
        "deadline": None,
        "started": 20,
        "commit_days": [20, 19, 15, 14, 9, 8],
        "docs": {"notes/ideas.md": "# 想法\n\n- 深色模式\n- RSS\n", "README.md": "# blog\n"},
        "milestones": [{"id": "m1", "title": "迁移", "status": "done"}, {"id": "m2", "title": "订阅", "status": "active"}],
        "tasks": [("t1", "选静态站框架", "done", "m1", 19), ("t2", "迁移旧文章", "done", "m1", 14),
                  ("t3", "邮件订阅", "todo", "m2", None), ("t4", "RSS", "done", "m2", 8), ("t5", "评论系统", "dropped", "m2", 8)],
        "next": {"task": "t3", "why": "迁移完成，只差订阅"},
        "waiting": [{"id": "w1", "question": "邮件订阅用 Buttondown 还是自建？", "waiting_on": "me", "kind": "decide",
                     "since": day(8), "blocks": ["t3"], "status": "open"}],
        "bugs": [],
        "decisions": [{"date": day(8), "decision": "不做评论系统", "reason": "维护成本高，读者用邮件回复就够"}],
        "events": [(8, "waiting", "新增等待：邮件订阅用哪个服务（等你决定）"), (8, "done", "完成：RSS"),
                   (8, "decision", "决策：不做评论系统"), (14, "done", "完成：迁移旧文章"),
                   (19, "done", "完成：选静态站框架"), (20, "note", "开始记录项目状态")],
    },
]


# English version of every text above (python3 tools/demo.py --lang=en), for English screenshots.
EN = {
    '运营可以按条件筛选订单并导出报表，月中上线': 'Ops can filter orders and export reports; launch mid-month',
    '订单后台 · 报表导出': 'Order admin · report export',
    '# 报表导出方案\n\n## 字段\n\n订单号、下单时间、金额（仅财务可见）、状态。\n\n## 待确认\n\n- 是否需要 Excel\n': '# Report export plan\n\n## Fields\n\nOrder id, order time, amount (finance only), status.\n\n## Open questions\n\n- Excel needed?\n',
    '# TODO\n\n- [x] 导出任务队列\n- [ ] 报表模板\n- [ ] 前端筛选面板\n': '# TODO\n\n- [x] Export job queue\n- [ ] Report template\n- [ ] Filter panel UI\n',
    '方案': 'Plan',
    '开发': 'Build',
    '联调验收': 'Integration & sign-off',
    '梳理导出字段与权限': 'Map export fields and permissions',
    '导出任务队列': 'Export job queue',
    '报表模板（Excel）': 'Report template (Excel)',
    '订单筛选接口加分页': 'Paginate the order filter API',
    '导出文件下载与过期清理': 'Export download and expiry cleanup',
    '前端筛选面板': 'Filter panel UI',
    '测试环境联调': 'Integration on staging',
    '金额字段权限控制': 'Restrict the amount field',
    '导出进度提示': 'Export progress indicator',
    't4 被跨月漏数据 bug 卡住，前端可以先按接口约定开发': 't4 is blocked by the cross-month bug; the UI can go ahead against the API contract',
    '导出是否需要支持 Excel，还是只要 CSV？': 'Do exports need Excel, or is CSV enough?',
    '甲方产品 王经理': 'Dana (client PM)',
    '王经理您好，关于订单报表导出想确认一下：只需要 CSV，还是也需要 Excel（含多 sheet 与格式）？这会影响报表模板的实现，麻烦这两天给个答复，谢谢！': 'Hi Dana, quick question on the order report export: is CSV enough, or do you also need Excel (multiple sheets and formatting)? It changes how we build the template, so an answer in the next couple of days would really help. Thanks!',
    '测试环境的对象存储权限': 'Object storage access on staging',
    '运维 小陈': 'Sam (DevOps)',
    '小陈，报表导出需要测试环境 OSS 的读写权限（bucket: report-test），方便的时候帮开一下，影响下载功能联调，谢谢～': 'Hey Sam, the report export needs read/write access to the staging bucket (report-test). Could you grant it when you get a chance? It blocks testing downloads. Thanks!',
    '导出文件保留几天？': 'How many days do we keep export files?',
    '导出是否需要按角色限制字段？': 'Should fields be restricted by role?',
    '财务角色可见金额字段，其他角色隐藏': "Finance sees amounts; other roles don't",
    '筛选时间跨月时漏数据': 'Filtering across months drops rows',
    '导出文件名中文乱码': 'Garbled non-ASCII export file names',
    '金额字段仅财务角色可见': 'Amounts visible to finance only',
    '导出走异步任务队列，不同步生成': 'Exports run in an async job queue, not inline',
    '大数据量会超时': 'Large exports time out',
    '新增等待：导出文件保留几天（等你决定）': 'Waiting w3: How many days do we keep export files? (your call)',
    '发现 bug：筛选时间跨月漏数据': 'Bug b1: Filtering across months drops rows',
    '等运维开测试环境 OSS 权限': 'Waiting on DevOps for staging bucket access',
    '导出操作审计日志': 'Audit log for exports',
    '表结构已定，写入还没做；回来先接导出完成时的写入': 'Schema is settled, writes not done; pick up by logging when an export finishes',
    '暂停：导出操作审计日志': 'Paused: Audit log for exports',
    '完成：导出进度提示': 'Done: Export progress indicator',
    '修复：导出文件名中文乱码': 'Fixed bug: Garbled non-ASCII export file names',
    '完成：金额字段权限控制': 'Done: Restrict the amount field',
    '向甲方确认是否需要 Excel': 'Asked the client whether Excel is needed',
    '完成：导出任务队列': 'Done: Export job queue',
    '决策：金额字段仅财务角色可见': 'Decision: Amounts visible to finance only',
    '决策：导出走异步任务队列': 'Decision: Exports run in an async job queue',
    '完成：梳理导出字段与权限': 'Done: Map export fields and permissions',
    '开始记录项目状态': 'Started tracking this project',
    '门店预约小程序：用户选时间、门店确认、到店核销': 'Store booking app: customers pick a time, the store confirms, check-in on arrival',
    '预约小程序': 'Booking app',
    '# 计划\n\n1. 预约流程\n2. 门店端确认\n3. 核销\n': '# Plan\n\n1. Booking flow\n2. Store confirmation\n3. Check-in\n',
    '# 接口\n\n- POST /bookings\n': '# API\n\n- POST /bookings\n',
    '# 给 agent 的说明\n\n用 TypeScript，接口写在 docs/api.md。\n': '# Notes for agents\n\nUse TypeScript; the API is in docs/api.md.\n',
    '用户端': 'Customer app',
    '门店端': 'Store app',
    '预约时间选择': 'Time slot picker',
    '预约提交与通知': 'Booking submission and notifications',
    '我的预约列表': 'My bookings list',
    '门店确认页': 'Store confirmation screen',
    '到店核销': 'Check-in on arrival',
    '登录与手机号授权': 'Sign-in with phone number',
    '列表接口已通，分页还没做；回来先补下拉加载': 'List API works, pagination not done yet; pick up with infinite scroll',
    '用户端提交做完后，门店端可以并行开始': 'Once booking submission is done, the store app can start in parallel',
    '小程序订阅消息模板谁来申请？': 'Who sets up the push notification certificate?',
    '门店营业时间数据从哪里来': 'Where do store opening hours come from?',
    '门店系统供应商': 'POS vendor',
    '您好，我们在做门店预约，需要拿到各门店的营业时间，请问有没有接口或导出文件可以提供？': "Hi, we're building store bookings and need each store's opening hours. Is there an API or an export you could share?",
    'iOS 上时间选择器滚动卡顿': 'Time picker stutters when scrolling on iOS',
    '先只做微信小程序，不做 H5': 'iOS first; Android later',
    '门店客户主要在微信里': 'Most store customers are on iPhone',
    '插队：预约提交与通知（门店要先演示）': 'Urgent: Booking submission and notifications (store demo first)',
    '新增等待：订阅消息模板谁来申请（等你去做）': 'Waiting w1: Who sets up the push notification certificate? (your action)',
    '暂停：我的预约列表': 'Paused: My bookings list',
    '等供应商提供门店营业时间': 'Waiting on the POS vendor for opening hours',
    '发现 bug：iOS 上时间选择器滚动卡顿': 'Bug b1: Time picker stutters when scrolling on iOS',
    '完成：预约时间选择': 'Done: Time slot picker',
    '决策：先只做微信小程序': 'Decision: iOS first',
    '完成：登录与手机号授权': 'Done: Sign-in with phone number',
    '个人博客换成静态站，文章迁移，加订阅': 'Move the personal blog to a static site, migrate posts, add subscriptions',
    '博客改版': 'Blog redesign',
    '# 想法\n\n- 深色模式\n- RSS\n': '# Ideas\n\n- Dark mode\n- RSS\n',
    '迁移': 'Migration',
    '订阅': 'Subscriptions',
    '选静态站框架': 'Pick a static site generator',
    '迁移旧文章': 'Migrate old posts',
    '邮件订阅': 'Email subscriptions',
    '评论系统': 'Comments',
    '迁移完成，只差订阅': 'Migration done; only subscriptions left',
    '邮件订阅用 Buttondown 还是自建？': 'Email subscriptions: Buttondown or self-hosted?',
    '不做评论系统': 'No comments',
    '维护成本高，读者用邮件回复就够': 'Too much upkeep; readers can reply by email',
    '新增等待：邮件订阅用哪个服务（等你决定）': 'Waiting w1: Buttondown or self-hosted? (your call)',
    '完成：RSS': 'Done: RSS',
    '决策：不做评论系统': 'Decision: No comments',
    '完成：迁移旧文章': 'Done: Migrate old posts',
    '完成：选静态站框架': 'Done: Pick a static site generator',
}


def translate(o):
    if isinstance(o, str):
        return EN.get(o, o)
    if isinstance(o, dict):
        return {translate(k): translate(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return type(o)(translate(v) for v in o)
    return o


def git(path, *args, when=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="demo", GIT_AUTHOR_EMAIL="demo@example.com",
               GIT_COMMITTER_NAME="demo", GIT_COMMITTER_EMAIL="demo@example.com")
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    subprocess.run(["git", *args], cwd=path, env=env, check=True, capture_output=True)


def build_folder(p):
    path = ROOT / "projects" / p["folder"]
    path.mkdir(parents=True)
    git(path, "init", "-q")
    for rel, text in p["docs"].items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    for n in sorted(p["commit_days"], reverse=True):
        (path / "CHANGELOG.md").open("a", encoding="utf-8").write(f"- {day(n)}\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", f"work {day(n)}", when=at(n, 11))
    return path


def build_status(p):
    tasks = []
    for tid, title, st, ms, n in p["tasks"]:
        t = {"id": tid, "title": title, "status": st, "milestone": ms}
        if n is not None:
            t["changed_at"] = day(n)
        if st == "paused":
            t["paused_at"] = day(n)
            t["note"] = p["paused_note"][tid]
        if tid in p.get("urgent", []):
            t["urgent"] = True
        tasks.append(t)
    nxt = dict(p["next"], title=next(t["title"] for t in tasks if t["id"] == p["next"]["task"]))
    timeline = [{"at": at(n, 18 - i % 6), "type": kind, "text": text} for i, (n, kind, text) in enumerate(p["events"])]
    return {"version": 1, "project": {"name": p["name"], "goal": p["goal"]}, "updated_at": timeline[0]["at"],
            "deadline": p["deadline"], "milestones": p["milestones"], "next": nxt, "tasks": tasks,
            "waiting": p["waiting"], "bugs": p["bugs"], "decisions": p["decisions"], "timeline": timeline}


def history(p, status):
    """A plausible burn-up: scope grows early, completions follow the 'done' days."""
    live = [t for t in p["tasks"] if t[2] != "dropped"]
    rows = []
    for n in range(p["started"], -1, -1):
        total = sum(1 for t in live if t[4] is None or t[4] >= n or n <= p["started"] // 2) if n else len(live)
        done = sum(1 for t in live if t[2] == "done" and t[4] is not None and t[4] >= n)
        rows.append({"date": day(n), "done": done, "total": max(total, done),
                     "waiting": sum(w["status"] == "open" and w["since"] <= day(n) for w in status["waiting"]),
                     "bugs": 0})
    return rows


def main():
    if ROOT.exists():
        if not MARKER.exists():
            sys.exit(f"{ROOT} exists and is not a demo folder; pick another directory")
        shutil.rmtree(ROOT)
    ROOT.mkdir(parents=True)
    MARKER.write_text("built by tools/demo.py\n", encoding="utf-8")
    (ROOT / "data").mkdir(parents=True)
    forthmark.write_json(ROOT / "data" / "config.json", {"lang": LANG})  # the demo panel speaks the demo's language
    for p in (translate(PROJECTS) if LANG == "en" else PROJECTS):
        path = build_folder(p)
        pid, _ = forthmark.register_project(path)
        reg = forthmark.load_registry()
        reg["projects"][pid]["added_at"] = at(p["started"], 10)
        forthmark.save_registry(reg)
        status = build_status(p)
        forthmark.write_json(forthmark.status_path(pid), status)
        rows = history(p, status)
        (forthmark.data_dir(pid) / "history.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        errors, _ = forthmark.validate_project(pid)
        if errors:
            sys.exit(f"{p['name']}: " + "; ".join(errors))
    forthmark.render_panel()
    cli = shlex.quote(str(Path(__file__).resolve().parent / "forthmark.py"))
    print(f"demo built in {ROOT}\nopen it:  FORTHMARK_HOME={shlex.quote(str(ROOT / 'data'))} python3 {cli} open")


if __name__ == "__main__":
    main()

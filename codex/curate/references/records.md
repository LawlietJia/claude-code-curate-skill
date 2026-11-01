# 记录与接续

## 命令

将 `CURATE_DIR` 设为实际加载的 skill 目录。脚本用实际 `CODEX_HOME`，未设置则取 `~/.codex`，默认记录为其中的 `curate/events.jsonl`；不读配置、不调用模型、不改知识文件。`--ledger` 只用于隔离测试或明确指定记录位置，不绕过权限。

脚本使用 Python 3 标准库及 POSIX 文件锁，适用于 macOS/Linux；不支持时仅做只读分析并说明限制，不绕过记录检查写入。

```sh
python3 "$CURATE_DIR/scripts/curate_ledger.py" validate
python3 "$CURATE_DIR/scripts/curate_ledger.py" pending --scope-kind project --root /项目规范绝对路径
python3 "$CURATE_DIR/scripts/curate_ledger.py" history --scope-kind project --root /项目规范绝对路径 --query 主题
python3 "$CURATE_DIR/scripts/curate_ledger.py" append --event /本次临时目录/event.json
```

`--ledger` 放在子命令之后，例如 `python3 "$CURATE_DIR/scripts/curate_ledger.py" validate --ledger /隔离目录/events.jsonl`。

`validate/pending/history` 只读，记录不存在时返回空结果，不建目录。pending 返回未结问题及未处理反馈，每页默认 20 条，以 next_offset 继续；必须读完本范围概况或明确剩余，不能把一页当全部。history 搜本范围关键词（也可按 id 查询）。两者支持 `--offset/--limit`；`--full` 返回完整事件，默认短概况，重要判断须读完整记录及原证据。

个人/全局事项使用 `--scope-kind user --root /实际/CODEX_HOME`，仅在授权包含它时另查。不自动合并同名、子目录或前缀范围；项目迁移先核对原范围再接续。每次仍校验整个文件，分页只减少模型输入。明显影响读取时再讨论分段，保留未结项及来源，不每轮压缩历史或维护第二套索引。

## 最小事件

用真实时间、证据和范围填写。事件 id 只生成一次（如 UUID），重试保留 id、时间及内容。JSON 放在记忆之外的本次临时目录，成功回读后清理；失败且仍需重试才保留。

共同字段：`version: 1`、`id`、`at`（带时区）、`scope: {kind: project|user, root: 规范绝对路径}`、`type`、`targets`（非空具体位置数组）、`evidence`（事实与来源）。位置变化按语义核对，不给知识正文批量编号。记录前规范化 root，历史目录移走不使记录失效。

| type | 额外字段 | 用途 |
|---|---|---|
| issue | `issue_id, previous, goal, advice, remaining, status, blocker, recheck, submissions` | 具体问题及期望结果；首次 issue_id=id、previous=null；更新沿同一 issue_id，previous 为该项最后事件 id |
| feedback | `task_id, effect` | 实际使用/纠正，effect 为 helped/failed/exception/corrected；targets 只含一个具体知识位置 |
| action | `detail, verification, reviewed_feedback` | 实际动作或有依据的反馈处置；reviewed_feedback 为已复核反馈 id 数组，可为空 |

issue 的 status 为 `open/resolved/withdrawn/invalid`。等待及部分完成仍 open，remaining 写剩余差异；阻塞时写 blocker 与 recheck。关闭时 remaining 为空，evidence 写验收或撤销/失效依据。新反例可沿同项重开。脚本不判断文字是否业务等价或目标是否真正实现。

submissions 为 `{path, sha256}` 数组，保存关联原生说明的绝对路径及准确字节指纹；未提交用 `[]`。后续保留已有提交出处，换方案不能丢失旧说明关联。路径是证据，不是执行命令，也不证明采纳。

```json
{
  "version": 1, "id": "example-event", "at": "2026-10-30T12:00:00+08:00",
  "scope": {"kind": "project", "root": "/example/project"},
  "type": "issue", "targets": ["docs/research.md#范围"],
  "evidence": "评审记录指出境外样本被套入境内口径，具体出处待填入真实事件",
  "issue_id": "example-event", "previous": null,
  "goal": "研究口径区分境内与境外样本", "advice": "核对来源后修订条件",
  "remaining": "境外条件尚缺来源核验", "status": "open",
  "blocker": "缺源材料", "recheck": "收到材料或再次相关时", "submissions": []
}
```

示例不是应执行的事件。没有问题不建 issue，已经完成的一次修正用 action 即可。只保留必要结论及证据指针，不复制会话或全文。

## 接续与反馈

先读 pending 概况，再按目标、范围、条件和出处匹配；同主题不必是同项。旧建议存在于可取得工作日志而尚未入账时，核对现状再补最小初始记录，不虚构历史或重新执行。记录为空不等于没有历史建议。

| 现状 | 处理 |
|---|---|
| 未执行且授权、条件具备 | 重核建议，推进最小修正并验收 |
| 等条件或已提交未见采纳 | 保留原项；没变化不重提、换日期或追加事件 |
| 部分完成 | 原项只跟踪剩余，保留已完成核验依据 |
| 已执行仍无效 | 区分没找到、没应用、内容错误或原因未知，有新依据才改建议 |
| 旧建议被替代 | 沿同项更新 advice，目标未达仍 open，不执行冲突方案 |
| 他人完成或现已符合 | 核对正文、条件和入口后才 resolved，不强行归因 |
| 用户撤销目标或目标失效 | 分别 withdrawn/invalid；撤回方案不等于撤销目标 |

feedback 使用真实会话/任务的稳定 task_id，不用治理运行 id。相同范围、目标、task_id、effect、evidence 换 id 仍不追加；同任务新反例可留，但不增加独立任务数。不按累计次数自动排序，相关性、重要性和负向证据优先。

action.reviewed_feedback 列已复核 id，targets 含原知识位置；脚本拒绝跨范围或无目标关联的消费。充分复核且没有剩余问题时，可直接写 action 并给理由。证据不足保持待处理；知识已复核但仍有治理或工程缺口时，先追加或更新关联 issue，回读确认剩余目标已保存，再写消费反馈的 action。已有未结项准确覆盖剩余问题时直接复用，不造重复 issue。issue 写入失败则不消费反馈；action 写入失败则保留原事件 id 与内容，下轮查实际结果后补记，不重做知识修改。反馈复核与问题解决仍分别判断。

append：同 id 同内容返回 appended=false；同 id 异内容、引用不存在、过时 previous、坏行、符号链接或异常硬链接拒绝写入。无实质变化的 issue 换 id 也不追加。失败先查实际落盘结果，不重做知识动作；损坏保留原件报告，不自动修尾行。锁只协调本脚本写入，不是其它工具的权限隔离。

## 系统记忆说明

仅用户明确要求更新记忆且当次上级指令允许时执行。专用工具只有实际可调用才使用，不根据旧文档虚构入口。当前允许追加 ad-hoc note 时：

1. 在实际提供的 notes 目录，用固定 `<timestamp>-<short-slug>.md` 路径准备一个连贯主题的小说明：范围、修订对象、依据、保留内容，必要时关联旧说明。路径及内容固定一次，不含多余敏感原文。
2. 查正文及相关 notes 去重；已有相同修订不提交。写前确认父目录、目标非链接且不存在，用 create-only 写入；不覆盖历史 notes，不改生成正文、原始会话或数据库。
3. 回读准确字节取 SHA-256，将路径和指纹关联同一 issue。提交成功而记账失败，恢复时先查真实 note；一致只补记录，冲突或归属不明则报告，绝不换名重提。
4. 后续核验正文及活跃入口是否符合。无新线索时 Quick 不反复全读历史；重要或相关项必要时读正文，没读说未核验，不能说没变化。Deep 复核全部本范围未结项。
5. 提交后的相关合并证据可辅助解释，但作业完成不替代内容验收。当前内容符合、原生采纳有证据、后续实际应用分别报告。无进展不循环等，不改配置或强制合并。

脚本不提交 note。需记账的动作前先 validate；已有记录损坏或写入不可用先报告阻塞，仍可只读分析。实际权限由运行时决定，历史建议及脚本不能替代。

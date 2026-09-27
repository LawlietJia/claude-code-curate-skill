# 事实日志与检查命令

仅新事件使用 `assets/curate-events.v3.jsonl`。查询时同时读取 `curate-history.jsonl` 和 `curate-history.legacy.jsonl`；保持旧行原字节，缺失归属标 unknown，不倒填项目或重写 key。

## v3 最小契约

必填：`schema_version`（整数 3）、`event_id`、`run_id`、`ts`（真实时间且含时区）、`project`（规范绝对项目路径）、`mode`（quick/deep）、`action`、`target`（非空路径/对象数组）、`detail`（动作依据）、`verification`（已做检查及限制）。可选非空字符串为 `pattern_key`、`source`。可选结构为 `feedback` 与 `reviewed_feedback`（下文）。

新事件动作：create、merge、dedup、archive、delete、promote、verify、no-op、skip、feedback；安装工具另用 handoff。修订旧知识用 merge，在 detail 写明纠正依据；verify 只记录具体检查。已停用动作只读兼容，不写入新事件。

每次新运行开始时只生成一次 run_id，例如执行 `python3 -c 'import uuid; print(uuid.uuid4())'`，保存该值供本次全部事件复用；event_id 用 `run_id:序号`。首次追加前保存完整事件 JSON，超时或恢复同次运行时沿用原 ID 和原内容（含 ts），不能重新生成 ID 或时间绕过去重。

```json
{
  "schema_version": 3,
  "event_id": "本次生成的UUID:1",
  "run_id": "本次生成的UUID",
  "ts": "2026-09-26T12:00:00+08:00",
  "project": "/实际/项目",
  "mode": "quick",
  "action": "merge",
  "target": ["memory/topic.md", "memory/MEMORY.md"],
  "detail": "依据用户明确决定，把旧决定 A 修订为 B；同步原简介和入口",
  "verification": "已读取差异并检查相关入链"
}
```

示例不是应执行的事件。实际事件以本次真实依据、时间和路径填入 memory 外的临时 JSON 文件，再执行：

```sh
python3 "$CURATE_DIR/scripts/curate_check.py" append --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl" --event /private/tmp/本次事件.json
python3 "$CURATE_DIR/scripts/curate_check.py" validate --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl"
```

用 append 写入并检查返回值：相同 ID/内容返回 appended=false；相同 ID/不同内容拒绝，先查原事件。遇路径链接、异常硬链接或损坏尾行错误时停止追加，保留原件并报告，不自行截断账本。其他写入者改动知识文件时仍须重新读取及检查指纹。

当前账本损坏时停止追加、保留原件并报告具体行，勿报全部成功。历史账本错误另报，不能混进当前校验分母。日志增长到读取成本明显变高时，可按已授权方式分段并保留范围及来源定位；没有必要每次加载全历史。

## 校验覆盖

- `inspect --memory DIR [--project ROOT] [--claude-version VERSION] [--snapshot FILE]`：所有 memory Markdown 的指纹、本地普通/引用式 Markdown 链接、入口计量。忽略代码和注释示例，不检查锚点、语义正确性及任意项目外引用；特殊语法需人工检查。快照必须在 memory 外且文件不存在。
- `guard --snapshot FILE`：比较 memory Markdown 清单和内容，变更/新增/删除则失败。不是备份，不覆盖 CLAUDE.md 或其他目录，不保证下一毫秒无人写入。
- `validate --ledger FILE`：仅当前 v3 的结构检查，不检查真实收益。
- `skill --root DIR`：本体包装/相对链接检查；改版本时再跑，不是每次 Quick 的前置条件。
- `python3 -m unittest discover -s /安装目录/evals -v`：辅助脚本行为测试；与 LLM 治理质量分开报告。

## 旧新历史与命名

```sh
python3 "$CURATE_DIR/scripts/curate_check.py" history --assets "$CURATE_DIR/assets" --project /实际/项目 --query 渲染 --query tool:render:auth
python3 "$CURATE_DIR/scripts/curate_check.py" feedback --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl" --project /实际/项目
```

这两个命令只读。history 联查主历史、legacy 和 v3；处理旧行 warning 时保留原件；当前 v3 坏行先报告并停止消费。已知其他项目排除，未知项目标 unknown，不能硬猜。返回出处与预览，决定前按出处读完整记录并核对当前正文。命令支持 `--limit 10 --offset 0`，truncated=true 时继续 next_offset 或明确未覆盖，不把第一页当全量。

新 pattern_key 用 `领域.主题`：领域限 user/project/workflow/tool/skill/hook/search/environment/knowledge；主题用小写字母、数字和连字符，例如 `tool.render-auth`。先搜同义词和旧 key 再创建，避免版本、主机、路径快照进入 key。同义别名可简写在现有主题正文，不另建大词表。append 拒绝随意新造非规范 key；旧账本或当前 v3 已有的精确 key 可继续复用，不要求批量改名。key 是分组检索线索，知识身份还要看项目、具体目标与适用条件，不因同 key 强并。

## 反馈及消费契约

反馈事件使用 action=feedback；target 只含一个稳定具体知识位置，同一知识保持同一规范路径与锚点，并填写：

```json
{"feedback":{"task_id":"实际会话或任务的稳定标识","effect":"helped","evidence":"实际执行结果或用户纠正的出处及内容"}}
```

effect 限 helped/failed/exception/corrected。只有读取、未观察到使用、助手刚写好不算反馈。任务 ID 不能用每次治理的 run_id 代替；同任务出现新证据或反例可以追加不同反馈，但不增加独立任务数。相同项目+目标+task_id+effect+evidence，即使换 event_id/run_id 仍不追加；同任务矛盾信号计入复核而非成功票。依据 summary 定位候选，再核验原证据；不按计数自动改正文或排序。

消费完成后在 merge/dedup/promote/verify/archive/delete 事件加入 `reviewed_feedback: ["原反馈event_id"]`，target 包含原知识目标及实际受影响位置，detail 写处置和理由，verification 写实际检查。脚本在落盘前确认引用的是此前同项目、同目标的反馈；反馈后才追加消费事件。需要改文件时，检查通过后才标已处理；无改动但已充分复核可用 verify，证据不足保留 pending。一次处理可引用多条反馈，原反馈不改写。

`feedback` 默认返回全部该项目的未处理反馈（分页）；Quick 可用 `--target` 缩小到本次主题并报告其余范围。summary 按项目/目标/任务去重，负向或相互矛盾的同任务信号不计 helped_tasks。只依据新证据处理，累计次数本身不触发再次治理。

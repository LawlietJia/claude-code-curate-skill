# 事实日志与检查命令

仅新事件使用 `assets/curate-events.v3.jsonl`。查询时同时读取 `curate-history.jsonl` 和 `curate-history.legacy.jsonl`；保持旧行原字节，缺失归属标 unknown，不倒填项目或重写 key。

## v3 最小契约

必填：`schema_version`（整数 3）、`event_id`、`run_id`、`ts`（真实时间且含时区）、`project`（规范绝对项目路径）、`mode`（quick/deep）、`action`、`target`（非空路径/对象数组）、`detail`（动作依据）、`verification`（已做检查及限制）。可选非空字符串为 `pattern_key`、`source`。可选结构为 `feedback` 与 `reviewed_feedback`（下文）。

新事件动作：create、merge、dedup、archive、delete、promote、verify、no-op、skip、feedback；安装工具另用 handoff。修订旧知识用 merge，在 detail 写明纠正依据；verify 只记录具体检查。已停用动作只读兼容，不写入新事件。

## 日常 record 与重试

业务输入只填写实际动作和检查依据，不填写 `schema_version/event_id/run_id/ts`。`record` 自动生成这四项，排他创建完整事件文件并保存后，通过原 `append` 校验写入。修改旧知识用 merge；无反馈时省略 `feedback/reviewed_feedback`，不传空数组。清理和未决事项写在 detail/verification，不新造 cleaned/pending 等字段。

```json
{
  "project": "/实际/项目",
  "mode": "quick",
  "action": "merge",
  "target": ["memory/topic.md", "memory/MEMORY.md"],
  "detail": "依据用户明确决定，把旧决定 A 修订为 B；同步原简介和入口",
  "verification": "已读取差异并检查相关入链"
}
```

示例不是应执行的事件。将实际内容存入 memory 外、本轮独立暂存目录的输入文件；输入、完整事件、账本使用不同路径：

```sh
python3 "$CURATE_DIR/scripts/curate_check.py" record --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl" --input /实际/本轮暂存/内容.json --event /实际/本轮暂存/事件.json
```

首次事件自动生成运行 ID，序号默认 1；返回 `run_id/event_file` 及实际写入或去重命中的 `event_id`。同轮的下一条使用新的输入和事件路径，加 `--run-id 首次返回值 --sequence 2`，后续依次递增。已有 run_id 可从第一条完整事件取回；不把同轮每个动作都当新运行。

事件文件已存在时复用原件；同时提供 input/run-id/sequence 时必须与原件一致。冲突、不完整文件、符号链接或异常硬链接均停止，不覆盖、不补造事实、不自动换 ID。追加失败保留事件文件；成功返回前可能已经落盘，结果不确定时原样重试：

```sh
python3 "$CURATE_DIR/scripts/curate_check.py" record --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl" --event /实际/本轮暂存/事件.json
```

检查原命令退出码及 `ok`，不要用 `head/tail`、`|| true` 或后续清理掩盖失败。返回 `appended=false` 表示去重命中，实际 `event_id` 可能属于更早的同内容反馈；消费反馈必须引用返回 ID。`run_id` 始终是本次准备事件的运行 ID，供本轮后续动作复用。

已有完整 v3 事件仍可用 `append --ledger FILE --event FILE`。相同 ID/相同内容不重复写入；相同 ID/不同内容拒绝。若原事件已入账，更正作为新事件说明依据；未知结果先原样重试。未入账且内容确需修正时，先核对该 ID 的账本原记录及原输入，再修正事件业务字段，保留 ID 和时间。无法确定时报告阻塞。

只通过 record/append 写入当前账本，不用直接追加、重定向或其他自造格式绕过它。遇损坏尾行等错误时保留原件并报告，不自行截断账本。其他写入者改动知识文件时仍须重新读取及检查指纹。

当前账本损坏时停止追加、保留原件并报告具体行，勿报全部成功。历史账本错误另报，不能混进当前校验分母。日志增长到读取成本明显变高时，可按已授权方式分段并保留范围及来源定位；没有必要每次加载全历史。

产物清理沿用 delete/dedup/merge；同一理由的一组相关文件可写一条事件，target 列实际路径，detail 写删除依据、保留对象和必要恢复位置，verification 写实际核验及局限。永久遗忘沿用同一事件格式，从业务输入起使用不含待忘内容的目标标识，仅记范围、结果及限制。未发生知识使用就不造 feedback，不为每个缓存单独记账。

## 校验覆盖

- `inspect --memory DIR [--project ROOT] [--claude-version VERSION] [--snapshot FILE]`：所有 memory Markdown 的指纹、本地普通/引用式 Markdown 链接、入口计量。忽略代码和注释示例，不检查锚点、语义正确性及任意项目外引用；特殊语法需人工检查。快照必须在 memory 外且文件不存在。 入口默认检查 200 行及 25,000 UTF-16 单元，独立于版本号；would_truncate 表示默认预算下的截断风险，不代表实测当前运行时。--claude-version 仅作为可选元数据记录，不影响检查。
- 完整 `inspect` 同时报告到期条款。仅需复查提示时用 `inspect --memory DIR --due-only`，读取同一目录，只输出检查日期、命中位置和扫描问题。`review_due` 为待核，`invalid_review_date` 需核对日期。精简模式不检查链接或生成快照。
- `guard --snapshot FILE`：比较 memory Markdown 清单和内容，变更/新增/删除则失败。不是备份，不覆盖 CLAUDE.md 或其他目录，不保证下一毫秒无人写入。CLAUDE.md 及 rules 的体量、导入与触发另按治理规则核查，inspect/guard 不验证原生指令加载。
- `record --ledger FILE --event FILE [--input FILE] [--run-id ID] [--sequence N]`：准备并保存可重试事件，复用 append 的校验、去重和锁；新建事件须用暂存目录下的绝对文件路径；相对路径只可复用已有的完整事件。省略 input 时只重试已有事件。
- `validate --ledger FILE`：仅当前 v3 的结构检查，不检查真实收益，也不证明本次事件已写入。
- `skill --root DIR`：本体包装/相对链接检查；改版本时再跑，不是每次 Quick 的前置条件。
- `python3 -m unittest discover -s /安装目录/evals -v`：辅助脚本行为测试；与 LLM 治理质量分开报告。

## 旧新历史与命名

```sh
python3 "$CURATE_DIR/scripts/curate_check.py" history --assets "$CURATE_DIR/assets" --project /实际/项目 --query 渲染 --query tool:render:auth
python3 "$CURATE_DIR/scripts/curate_check.py" feedback --ledger "$CURATE_DIR/assets/curate-events.v3.jsonl" --project /实际/项目
```

这两个命令只读。history 联查主历史、legacy 和 v3；处理旧行 warning 时保留原件；当前 v3 坏行先报告并停止消费。已知其他项目排除，未知项目标 unknown，不能硬猜。返回出处与预览，决定前按出处读完整记录并核对当前正文。命令支持 `--limit 10 --offset 0`，不把第一页当全量。history 仅在处置仍缺历史依据时按 next_offset 续查，停止时说明剩余范围；feedback 在选定范围内先完成分页读取，再写消费事件，范围之外明确未覆盖。消费会缩短 pending 列表，使旧 next_offset 失效；消费后需续读时从 offset=0 重查，再完成本轮分页读取。证据不足的条目保留未决，同轮无新证据不反复复核，不为清零 pending 循环查询。

新 pattern_key 用 `领域.主题`：领域限 user/project/workflow/tool/skill/hook/search/environment/knowledge；主题用小写字母、数字和连字符，例如 `tool.render-auth`。先搜同义词和旧 key 再创建，避免版本、主机、路径快照进入 key。同义别名可简写在现有主题正文，不另建大词表。append 拒绝随意新造非规范 key；旧账本或当前 v3 已有的精确 key 可继续复用，不要求批量改名。key 是分组检索线索，知识身份还要看项目、具体目标与适用条件，不因同 key 强并。

## 反馈及消费契约

反馈事件使用 action=feedback；target 只含一个稳定具体知识位置，同一知识保持同一规范路径与锚点，并填写：

```json
{"feedback":{"task_id":"实际会话或任务的稳定标识","effect":"helped","evidence":"实际执行结果或用户纠正的出处及内容"}}
```

effect 限 helped/failed/exception/corrected。已有知识实际应用才记使用反馈，用户明确纠正已有知识也可记 corrected；新提炼方法的验证放在 create/merge 的 detail、verification，不追记为记忆复用。只有读取、未观察到使用、助手刚写好不算反馈。任务 ID 不能用每次治理的 run_id 代替；同任务出现新证据或反例可以追加不同反馈，但不增加独立任务数。相同项目+目标+task_id+effect+evidence，即使换 event_id/run_id 仍不追加；同任务矛盾信号计入复核而非成功票。依据 summary 定位候选，再核验原证据；不按计数自动改正文或排序。

消费完成后在 merge/dedup/promote/verify/archive/delete 事件加入 `reviewed_feedback: ["记账返回的反馈event_id"]`，target 包含原知识目标及实际受影响位置，detail 写处置和理由，verification 写实际检查。脚本在落盘前确认引用的是此前同项目、同目标的反馈；反馈后才追加消费事件。需要改文件时，检查通过后才标已处理；知识无改动但已充分复核可用 verify；如有尚未实施的工程建议，在 detail/verification 中明确。reviewed_feedback 不表示工程问题已解决。知识仍错误先修正，知识证据不足保留 pending；不为等待工程实施长期挂起已复核反馈。一次处理可引用多条反馈，原反馈不改写。

`feedback` 默认返回全部该项目的未处理反馈（分页）；Quick 可用 `--target` 缩小到本次主题并报告其余范围。summary 按项目/目标/任务去重，负向或相互矛盾的同任务信号不计 helped_tasks。只依据新证据处理，累计次数本身不触发再次治理。

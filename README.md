# Curate 2.2.0

Claude Code 项目知识、原生记忆与无用产物治理。

- `/curate`：处理本次增量、相关反馈和会话产物收尾。
- `/curate --deep`：盘点授权项目各类文件，治理知识并清理确认无用的产物。
- 保留来源和条件，合并重复、纠正错误、提升重要规则、核验过期知识。
- 联查旧新历史；记录真实使用反馈，处置后关联已处理事件。

执行规则见 [SKILL.md](SKILL.md)、[治理规则](references/governance.md)、[日志规则](references/audit.md)。

维护验证：

```sh
python3 scripts/curate_check.py skill --root .
python3 -B -m unittest discover -s evals -v
```

[行为测试与隔离样本](evals/README.md)。

# Curate 2.1.2

Claude Code 项目知识与原生记忆治理。

- `/curate`：处理本次增量和相关反馈。
- `/curate --deep`：全面检查授权项目的记忆、规则及知识入口。
- 保留来源和条件，合并重复、纠正错误、提升重要规则、核验过期知识。
- 联查旧新历史；记录真实使用反馈，处置后关联已处理事件。

执行规则见 [SKILL.md](SKILL.md)、[治理规则](references/governance.md)、[日志规则](references/audit.md)。

维护验证：

```sh
python3 scripts/curate_check.py skill --root .
python3 -B -m unittest discover -s evals -v
```

[行为测试与隔离样本](evals/README.md)。

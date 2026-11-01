# Curate：Claude Code 与 Codex 两个版本

治理项目知识、记忆、规则及无用产物。请按使用的工具选择版本，两版独立安装。

| 平台 | 当前版本 | 源码入口 | 独立下载 |
|---|---|---|---|
| Claude Code | 2.2.3 | [根目录 SKILL.md](SKILL.md) | [Claude Code 安装包](https://github.com/LawlietJia/claude-code-curate-skill/releases/download/codex-v1.0.1/curate-claude-code-v2.2.3.zip) |
| Codex | 1.0.1 | [codex/curate/SKILL.md](codex/curate/SKILL.md) | [Codex 安装包](https://github.com/LawlietJia/claude-code-curate-skill/releases/download/codex-v1.0.1/curate-codex-v1.0.1.zip) |

- **Claude Code**：安装包内 `curate/` 放入 `~/.claude/skills/`；调用 `/curate` 或 `/curate --deep`。
- **Codex**：安装包内 `curate/` 放入实际 `CODEX_HOME/skills/`，未设置时为 `~/.codex/skills/`；调用 `$curate`、`$curate --deep`，加 `--check` 仅检查。
- 目标已有同名 skill 时，先比较与备份自己的修改，勿直接覆盖；勿把整个仓库作为 Codex 的 skill 目录。两版 skill 名均为 `curate`，使用不同平台的安装目录。
- 根目录继续保留 Claude Code 版以兼容已有使用方式；Codex 的安装与权限边界见 [Codex 说明](codex/README.md)。独立 ZIP 只包含对应平台，不包含另一平台，也不携带维护者的治理账本或运行历史；首次运行建立自己的记录。

## Claude Code 版

Claude Code 项目知识、原生记忆与无用产物治理。

- `/curate`：处理本次增量、相关反馈和会话产物收尾。
- `/curate --deep`：盘点授权项目各类文件，治理知识并清理确认无用的产物。
- 保留来源和条件，合并重复、纠正错误、提升重要规则、核验过期知识。
- 规则变更及 Deep 治理中检查 CLAUDE.md 与关联规则的体量和加载方式，按用途精简、拆分并核验入口。
- 联查旧新历史；记录真实使用反馈，处置后关联已处理事件。

执行规则见 [SKILL.md](SKILL.md)、[治理规则](references/governance.md)、[日志规则](references/audit.md)。

维护验证：

```sh
python3 scripts/curate_check.py skill --root .
python3 -B -m unittest discover -s evals -v
```

[行为测试与隔离样本](evals/README.md)。

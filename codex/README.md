# Codex 版 Curate 1.0.1

手动整理项目知识、规则、经验和无用产物，并接续仍未解决的问题。此目录只适用于 Codex；Claude Code 版位于仓库根目录。

## 下载与安装

下载 [curate-codex-v1.0.1.zip](https://github.com/LawlietJia/claude-code-curate-skill/releases/download/codex-v1.0.1/curate-codex-v1.0.1.zip)，先解压到临时位置，将其中 `curate/` 放入实际 `CODEX_HOME/skills/`（未设置 CODEX_HOME 时为 `~/.codex/skills/`）。已有同名目录时先比较并保留自己的修改，不直接覆盖。

也可克隆仓库后，只将 `codex/curate/` 安装到上述位置。根目录的 SKILL.md 属于 Claude Code，不应作为 Codex 版安装。保留 `curate/` 下的 agents、references、scripts 和 tests。

## 使用

- `$curate`：Quick，整理本次会话相关知识和产物。
- `$curate --deep`：检查整个已授权项目。
- `$curate --check` / `$curate --deep --check`：只读检查，不提交记忆说明、不写记录。

以上参数由 skill 解释；已配置为明确调用时使用。项目知识治理也适用于研究、写作和文件交付。

## 与 Claude Code 版的区别

- 检查 AGENTS.md 的实际继承、override 和字节预算。常驻位置保留核心约束，长流程按任务条件放入手册；普通链接不等于原生自动加载。
- 系统记忆正文和摘要只读。只有用户明确要求更新、且当次运行时允许时，才通过允许入口提交小型说明；提交、采纳与后续正确使用分别核验。
- 不能绕过 Codex 权限，不强制启动后台合并，不保证永久遗忘或原生历史总量有界。真实采纳和长期召回提升不能由本地脚本测试证明。
- 实际反馈及未结问题放在 `CODEX_HOME/curate/events.jsonl`，不写进安装目录。无事件不预建；不附带维护者的私人记录或记忆。

辅助脚本需 Python 3 和 macOS/Linux 的 POSIX 文件锁；无额外 Python 包依赖。脚本不可用时仅做只读分析并说明限制，不绕过记账检查写入。

## 维护验证

从仓库根目录执行：

```sh
python3 -B codex/curate/tests/test_ledger.py
```

测试只使用隔离临时目录，不接触真实记忆或治理记录。覆盖记录幂等、跨范围隔离、部分完成、反馈消费、损坏保护、并发及只读边界；脚本测试不替代治理质量和真实加载验收。

运行规则见 [SKILL.md](curate/SKILL.md)、[治理规则](curate/references/governance.md)及[记录与接续](curate/references/records.md)。

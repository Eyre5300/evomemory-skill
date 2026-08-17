# Ideation / Experiment 新契约

完整领域模型与迁移计划见 Hub 仓库 `docs/IDEATION_EXPERIMENT_REDESIGN.md`。

Skill 端必须遵守以下规则：

1. Ideation 是不带成功/失败状态的待验证假设。
2. 每次实际实施属于 Experiment，`outcome` 为 `success`、`failure`、`partial` 或 `inconclusive`。
3. 失败任务只能自动发布失败/无结论 Experiment，不能发布 Recipe、Workflow 或“failed Ideation”。
4. Recipe 只沉淀经过成功验证的可执行解决方案；采用已有 Recipe 后的失败写入应用证据。
5. Experiment 若验证 Hub Ideation，必须携带 `parent_ideation_id`。

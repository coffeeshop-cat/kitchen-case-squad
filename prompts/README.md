# 提示词目录

命名规则：`{role}.v{n}.md`，例如 `chef.v1.md`、`redteam.v2.md`。

- 文件第一行写变更原因：`<!-- 变更原因: ... -->`
- 改提示词必须单独提交，不与业务代码混在一个 commit。
- 提示词要冻结时，在文件名版本号上升一级，不覆盖旧版本。
- 提示词不得包含真实姓名、地址、电话、API Key。

| 文件 | 角色 | 负责人 | 状态 |
|---|---|---|---|
| `redteam.v1.md` | 红队 | 刘彬彬 | R1 已建 |
| `evidence.v1.md` | 证物官 | 刘彬彬 | R2 |
| `chef.v1.md` | 主厨 | 刘彬彬 | R2 |
| `strategist.v1.md` | 军师 | 刘彬彬 | R2 |
| `quartermaster.v1.md` | 管家 | 刘彬彬 | R2 |
| `host.v1.md` | 主持人 | 刘彬彬 | R2 |

输出结构统一见 [docs/contracts.md 第 4、5 节](../docs/contracts.md)。

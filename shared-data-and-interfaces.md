# 公共数据与模块接口规范 v0.1

项目：One-Person AI Event Management Company（ELEC5620 Stage 2）  
维护人：Zidong Zhou  
状态：第一轮联调草案，供团队确认后实现。

## 1. 这份文档解决什么问题

统一四个业务模块交接时的数据名称、格式和调用方式，让大家可以分别开发后接在一起。只定义最小流程需要的内容，不要求现在实现全部用例。

本文中的字段、入口和存放位置是建议的实现约定，不表示代码已经存在。已有 Stage 1 设计和 AGENTS.md 继续适用；如发现冲突，先记录并讨论，不直接覆盖原设计。

## 2. 第一轮要跑通的流程

1. 客户提交活动需求，Planning 生成方案草稿。
2. Procurement 根据需求和方案检索供应商，返回报价及推荐理由。
3. Financial 汇总供应商费用、公司服务费和预备金，检查总预算。
4. 客户确认方案及预订，并完成模拟订金支付。
5. Procurement 发起模拟预订；只有收到供应商确认后才创建 VendorBooking。
6. Operations 根据已批准方案和已确认预订生成执行计划与任务。

Supervisor 负责分派和协调，不代替业务 Agent 完成业务判断。初次联调允许明确标记的固定结果；后续各成员用真实功能替换。此流程用于验证模块连接，不代表完成全部 Stage 1 需求。

缺少必需信息、超预算、客户未确认、订金未支付或供应商拒绝时，停止向后推进并返回原因。此轮可以先展示问题，不必一次完成所有恢复分支。

## 3. 所有模块遵守的基本约定

- 同一场活动始终使用同一个 `event_id`，由创建活动的入口生成。
- Python 属性及 JSON 字段使用 `snake_case`，例如 `guest_count`；业务类名沿用 Stage 1，例如 `EventProposal`。
- 日期使用 `YYYY-MM-DD`；日期时间使用带时区偏移的 ISO 8601 格式，例如 `2026-11-20T18:00:00+11:00`。
- 金额统一使用澳元。交接字段以 `_cents` 结尾，使用整数分：`500000` 表示 AUD 5,000，避免金额精度歧义。
- `budget_limit_cents` 是整场活动的总预算上限，不能直接当成每一类服务的预算。
- 服务类型第一轮统一使用 `venue`、`catering`、`photography`；需要其他类型时在公共定义中补充。
- 必填数据缺失时返回提示；不让 LLM 擅自补出日期、人数、预算或供应商确认结果。

## 4. 最小公共数据

以下列出交接必需字段，不是完整数据库表。每个模块可以有内部数据，但对外交接使用这里约定的字段。

| 数据 | 第一轮字段 | 负责产生或维护 |
|---|---|---|
| 活动需求 `EventRequirement` | `event_id`、`request_text`、`event_type`、`event_date`、`location`、`guest_count`、`budget_limit_cents` | Planning 整理，客户确认 |
| 活动方案 `EventProposal` | `event_id`、`proposal_id`、`summary`、`required_services`、`timeline`、`status` | Planning |
| 供应商报价 `VendorQuotation` 的交接数据 | `event_id`、`proposal_id`、`quotation_id`、`vendor_id`、`service_type`、`quoted_total_cents`、`available`、`recommendation_reason` | Procurement |
| 预算检查结果 | `event_id`、`proposal_id`、`vendor_total_cents`、`service_fee_cents`、`contingency_cents`、`estimated_total_cents`、`within_budget` | Financial |
| 客户确认记录的交接数据 | `event_id`、`proposal_id`、`approved_quotation_ids`、`approved` | 由客户在界面操作产生，通过 Service 保存 |
| 订金记录 `CustomerPayment` 的交接数据 | `event_id`、`proposal_id`、`payment_id`、`amount_cents`、`status` | Financial；支付使用模拟流程 |
| 已确认预订 `VendorBooking` | `event_id`、`booking_id`、`quotation_id`、`vendor_id`、`status` | Procurement |
| 执行计划 `ExecutionPlan` | `event_id`、`proposal_id`、`execution_plan_id`、`tasks` | Operations |

补充约定：

- `required_services` 是服务类型列表，例如 `["catering", "photography"]`。
- `timeline` 是活动节目安排列表，每项包含 `title`、`start_at`、`end_at`；不在这里分配供应商或布置任务。
- `tasks` 是执行任务列表，每项包含 `task_id`、`title`、`scheduled_at`、`booking_id`、`status`。不涉及供应商的任务，`booking_id` 可以为 `null`。
- 方案状态沿用 Stage 1：`Draft`、`PendingReview`、`Approved`、`Rejected`。客户确认由界面操作触发，Agent 不能自行设为 Approved。
- 预订状态沿用 Stage 1：`Confirmed`、`Completed`、`Cancelled`。推荐和报价不等于已确认预订。
- 任务状态沿用 Stage 1：`NOT_STARTED`、`IN_PROGRESS`、`DELAYED`、`COMPLETED`。
- 模拟订金记录第一轮使用 `pending`、`paid`、`failed`，只描述这一轮的客户订金支付，不替代其他付款状态机。订金比例由统一配置提供。
- 总费用 = 供应商费用 + 公司服务费 + 预备金。服务费率与预备金率从统一配置读取，由 Financial 用代码计算。
- 第一轮只处理当前方案；方案或报价修改后，旧预算和旧确认不能直接复用，必须重新检查与确认。

## 5. 模块入口与返回方式

下表是供 Supervisor 调用的模块入口约定，不是替换 Stage 1 Service 方法的完整清单。模块内部仍通过 Service 和领域对象完成业务操作，不直接操作数据库。

| 模块入口 | 读取的主要数据 | 返回的 `data` |
|---|---|---|
| `planning.generate_proposal(event_id)` | 已整理的活动需求 | 活动方案 |
| `procurement.recommend_vendors(event_id)` | 当前方案、活动需求、供应商目录 | `quotations` 报价列表 |
| `finance.check_budget(event_id)` | 当前推荐报价、预算上限、统一费率 | 预算检查结果 |
| `finance.record_deposit(event_id)` | 客户确认、当前费用、模拟支付结果 | 订金记录 |
| `procurement.confirm_bookings(event_id)` | 已批准报价、已支付订金、模拟供应商回复 | `bookings` 已确认预订列表 |
| `operations.generate_execution_plan(event_id)` | 已批准方案、已确认预订 | 执行计划 |

每个入口统一返回下面的结构。`status` 只表示本次调用结果，与方案、付款、预订的业务状态分开。

```json
{
  "event_id": "EV001",
  "agent": "procurement",
  "timestamp": "2026-10-18T22:00:00+11:00",
  "status": "success",
  "message": "Found suitable vendor quotations.",
  "data": {
    "quotations": []
  }
}
```

- `agent` 固定为 `planning`、`procurement`、`finance`、`operations` 之一。
- `status` 固定为 `success`、`needs_input`、`blocked`、`error` 之一。
- 缺少客户信息用 `needs_input`；不满足预算、审批或支付等条件用 `blocked`；程序或外部调用失败用 `error`。
- 非成功时，`message` 写清具体原因，`data` 可以为 `{}`；Supervisor 不把它当成功结果继续推进。
- 查无可用供应商时返回 `blocked`，不能返回空报价列表并声称推荐成功。上面的空列表仅示意结构。
- Agent 的推荐理由与动作结果保留在结果和日志中；LLM 输出须经字段与业务校验后，再由 Service 保存。

## 6. 公共定义放在哪里

建议统一放在 `src/shared/schemas.py`，供各模块导入使用；具体目录若已有约定，沿用现有目录。共享数据由 SQLite 保存，模块经对应 Service 读取和更新。

不要在各自模块中再建一份名称相同、字段不同的公共模型。Agent 不互相直接调用，由 Supervisor 协调；LLM 调用沿用 AGENTS.md 指定的统一封装。

## 7. 以后发现不够用怎么办

1. 使用数据的人提出缺少的字段或接口，并说明用途。
2. Zidong 与产生该数据的模块负责人确认，更新本文件和公共定义。
3. 受影响的模块同步修改，再用同一个示例活动检查交接。

内部实现变化但输入、输出不变时，不需要修改公共约定。只有真实影响到模块交接的内容才补进这份文档。

## 8. 第一轮联调完成标准

- 使用同一个 `event_id`，跑通第 2 节的最小流程，能够展示方案、报价、预算和执行任务。
- 客户批准、模拟订金支付、模拟供应商确认三个步骤有明确记录，不能自动跳过。
- 保存后重新读取，仍能获得该活动的数据。
- 至少验证一次超预算：返回 `blocked`，不继续预订或生成执行计划。
- 所有固定结果、模拟外部回复都有标记，后续按同一接口替换。

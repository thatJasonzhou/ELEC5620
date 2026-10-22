# 公共数据与模块接口规范 v0.1

> **Stage 2 integration note:** This document was imported with the Vendor
> Procurement component and is retained as its original team contract. The
> current integrated prototype has no independent Supervisor Agent and uses
> React, FastAPI and an OpenAI-compatible planner. Where this draft conflicts
> with the root `AGENTS.md` or `docs/architecture.md`, the current documents
> take priority.

项目：One-Person AI Event Management Company（ELEC5620 Stage 2）
维护人：Zidong Zhou
状态：第一轮联调草案，供团队确认后实现。

## 1. 这份文档解决什么问题

统一四个业务模块交接时的数据名称、格式和调用方式，让大家可以分别开发后接在一起。只定义最小流程需要的内容，不要求现在实现全部用例。

本文中的字段、入口和存放位置是建议的实现约定，不表示代码已经存在。已有 Stage 1 设计和 AGENTS.md 继续适用；如发现冲突，先记录并讨论，不直接覆盖原设计。

## 2. 第一轮要跑通的流程

1. Planning：根据客户需求生成方案草稿。
2. Procurement：筛选供应商，发起模拟询价和档期确认；收到供应商可承接的回复后，返回报价和推荐理由。
3. Financial：汇总供应商费用、公司服务费和预备金，检查预算。
4. 客户：确认具体方案、供应商及费用，完成模拟订金支付。
5. Procurement：向选定供应商提交正式预订；收到最终确认后创建 VendorBooking。
6. Operations：根据已批准方案和已确认预订生成执行计划与任务。

Supervisor 负责分派和协调，不代替业务 Agent 完成业务判断。初次联调允许明确标记的固定结果；后续各成员用真实功能替换。此流程用于验证模块连接，不代表完成全部 Stage 1 需求。

第 2 步的档期与报价确认不等于正式预订，也不保证锁定档期。所有模拟供应商回复和模拟支付均须明确标记；付款后若预订失败，保留已支付记录，停止后续流程并标记待处理。

缺少必需信息、超预算、客户未确认、订金未支付或供应商拒绝时，停止向后推进并返回原因。此轮可以先展示问题，不必一次完成所有恢复分支。

## 3. 所有模块遵守的基本约定

- 同一场活动始终使用同一个 `event_id`，由创建活动的入口生成。
- Python 属性及 JSON 字段使用 `snake_case`，例如 `guest_count`；业务类名沿用 Stage 1，例如 `EventProposal`。
- 日期使用 `YYYY-MM-DD`；日期时间使用带时区偏移的 ISO 8601 格式，例如 `2026-11-20T18:00:00+11:00`。
- 金额统一使用澳元。交接字段以 `_cents` 结尾，使用整数分：`500000` 表示 AUD 5,000，避免金额精度歧义。
- `budget_limit_cents` 是整场活动的总预算上限，不能直接当成每一类服务的预算。
- 客户只提供整场活动预算；Planning 根据活动需求生成内部的 `vendor_budget_cents`，作为全部供应商的目标预算，并保证它不超过总预算。
- 服务偏好是可选筛选条件。未讨论时必须询问一次；客户明确不需要额外服务时，记录 `services_confirmed=true` 和空的 `required_services`，后续不按服务类型筛选。
- 当前流程允许组合多个供应商，但每种服务只能确认一个供应商，例如餐饮一家、摄影一家、场地一家。
- 服务类型第一轮统一使用 `venue`、`catering`、`photography`；需要其他类型时在公共定义中补充。
- 必填数据缺失时返回提示；不让 LLM 擅自补出日期、人数、预算或供应商确认结果。

## 4. 最小公共数据

以下列出交接必需字段，不是完整数据库表。每个模块可以有内部数据，但对外交接使用这里约定的字段。

| 数据 | 第一轮字段 | 负责产生或维护 |
|---|---|---|
| 活动需求 `EventRequirement` | `event_id`、`request_text`、`event_type`、`event_date`、`location`、`guest_count`、`budget_limit_cents`、`services_confirmed` | Planning 整理，客户确认 |
| 活动方案 `EventProposal` | `event_id`、`proposal_id`、`summary`、`required_services`、`vendor_budget_cents`、`timeline`、`status` | Planning |
| 供应商报价 `VendorQuotation` 的交接数据 | `event_id`、`proposal_id`、`quotation_id`、`vendor_id`、`service_type`、`quoted_total_cents`、`available`、`recommendation_reason` | Procurement |
| 预算检查结果 | `event_id`、`proposal_id`、`vendor_total_cents`、`service_fee_cents`、`contingency_cents`、`estimated_total_cents`、`within_budget` | Financial |
| 客户确认记录的交接数据 | `event_id`、`proposal_id`、`approved_quotation_ids`、`approved` | 由客户在界面操作产生，通过 Service 保存 |
| 订金记录 `CustomerPayment` 的交接数据 | `event_id`、`proposal_id`、`payment_id`、`amount_cents`、`status` | Financial；支付使用模拟流程 |
| 已确认预订 `VendorBooking` | `event_id`、`booking_id`、`quotation_id`、`vendor_id`、`status` | Procurement |
| 执行计划 `ExecutionPlan` | `event_id`、`proposal_id`、`execution_plan_id`、`tasks` | Operations |

补充约定：

- `required_services` 是可选的服务筛选列表，例如 `["catering", "photography"]`。客户确认不需要额外服务时使用空列表。
- `services_confirmed` 用于区分“尚未询问服务”和“客户确认不需要服务”，避免对空列表重复追问。
- `vendor_budget_cents` 是 Planning 从整场预算中分配给全部供应商的内部目标预算，客户不需要另外填写。
- `timeline` 是活动节目安排列表，每项包含 `title`、`start_at`、`end_at`；不在这里分配供应商或布置任务。
- `tasks` 是执行任务列表，每项包含 `task_id`、`title`、`scheduled_at`、`booking_id`、`status`。不涉及供应商的任务，`booking_id` 可以为 `null`。
- 方案状态沿用 Stage 1：`Draft`、`PendingReview`、`Approved`、`Rejected`。客户确认由界面操作触发，Agent 不能自行设为 Approved。
- 预订状态沿用 Stage 1：`Confirmed`、`Completed`、`Cancelled`。推荐和报价不等于已确认预订。
- 任务状态沿用 Stage 1：`NOT_STARTED`、`IN_PROGRESS`、`DELAYED`、`COMPLETED`。
- 模拟订金记录第一轮使用 `pending`、`paid`、`failed`，只描述这一轮的客户订金支付，不替代其他付款状态机。订金比例由统一配置提供。
- 总费用 = 供应商费用 + 公司服务费 + 预备金。服务费率与预备金率从统一配置读取，由 Financial 用代码计算。
- 第一轮只处理当前方案；方案或报价修改后，旧预算和旧确认不能直接复用，必须重新检查与确认。

## 5. 模块入口与返回方式

下表是供应用工作流调用的模块入口约定，不是替换 Stage 1 Service 方法的完整清单。模块内部仍通过 Service 和领域对象完成业务操作，不直接操作数据库。本项目没有独立的 Supervisor Agent。

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

### 5.1 Procurement 推荐接口（KAN-16 已实现，推荐阶段）

上表中 `procurement.recommend_vendors` 一行描述的是**报价阶段**；当前已实现的是**推荐阶段**，入口为
`VendorProcurementManagerAgent.handle(request)`（agent 标识 `procurement`，实现见
`src/agents/vendor_procurement_manager.py`）。第 4 节的 `VendorQuotation` 与上表 `quotations` 结构**原样保留**，
供报价阶段使用；本阶段**不产生** `quotation_id` / `quoted_total_cents`，也不涉及预订与支付。

**输入字段**（request 为 dict）：

| 字段 | 必填 | 类型与约束 | 说明 |
|---|---|---|---|
| `event_id` | 是 | 非空字符串 | 活动 ID |
| `service_type` | 是 | 非空字符串 | `venue` / `catering` / `photography`；工作流在客户确认不需要额外服务时可传内部值 `any`，仅取消服务类型筛选 |
| `event_date` | 是 | `YYYY-MM-DD` 字符串 | 映射为 Service 的 `date` 参数 |
| `guest_count` | 是 | 整数，≥0（bool 不接受） | 预计人数 |
| `location` | 是 | 非空字符串 | 活动城市 |
| `customer_preferences` | 否 | 字符串 | 软性偏好，仅供 LLM 参考，不参与代码筛选 |
| `min_rating` | 否 | 数字，0–5（bool、字符串不接受） | 代码侧评分下限筛选 |
| `target_vendor_budget_cents` | 否 | 正整数 | Planning 分配的单一供应商目标预算，用于排序和解释，不改变目录中的真实价格 |

**status 规则**：输入缺失/非法 → `needs_input`（不调用 LLM；`event_id` 缺失时信封 `event_id` 为 `null`）；
无可用候选（筛选无结果，或 `min_rating` 过滤后为空）→ `blocked`（不调用 LLM）；LLM 调用失败或模型输出校验失败 → `error`；
成功 → `success`，`data` 含 `recommendations`（1–3 条）。

**`data.recommendations` 单项结构**（价格、评分、容量等事实一律从目录回填，不采用模型自述；
`basis_codes` 已经代码核验，可能为空列表）：

```json
{
  "rank": 1,
  "vendor_id": "V-CAT-002",
  "offering_id": "V-CAT-002-O1",
  "vendor_name": "Bayside Bite Co",
  "service_type": "catering",
  "service_location": "Melbourne",
  "guest_capacity": 120,
  "rating": 4.2,
  "total_price_cents": 620000,
  "event_date": "2026-12-05",
  "basis_codes": ["lowest_price"],
  "recommendation_reason": "Cheapest catering that fits the venue."
}
```

**允许的 basis codes**（闭集，代码侧 `ALLOWED_BASIS_CODES`；每个 code 必须对**当前有效候选集合**复核成立，否则整次结果按 `error` 处理）：

| code | 含义 |
|---|---|
| `lowest_price` | 该候选 `total_price_cents` 为当前候选集合中的最低值 |
| `highest_rating` | 该候选 `rating` 为当前候选集合中的最高值 |
| `highest_capacity` | 该候选 `guest_capacity` 为当前候选集合中的最大值 |
| `within_budget` | 该候选的目录价格不高于 `target_vendor_budget_cents` |

同一 `(vendor_id, offering_id)` 不得重复推荐；`recommendation_reason` 为自由文本，属于 AI 偏好解释，即使
basis codes 核验通过也不视为完全事实核验。示例：`py -3 -m examples.vendor_recommendation_example`（默认
MockLLMClient，输出显式标注 MOCK）。

### 5.2 Procurement 模拟询价入口（KAN-19）

`VendorProcurementManagerAgent.request_quotations(request)` 是独立报价入口；
原 `handle(request)` 推荐接口及 §5.1 保持不变。构造 Agent 时可选注入
`quotation_service=MockVendorQuotationService(...)`；未注入而调用报价入口返回 `error`。

输入沿用 §5.1 的活动/服务字段，并要求非空 `proposal_id`，用于关联交给 Financial 的报价。
`event_id`、`service_type`、`event_date`、`guest_count`、`location` 同样必填。
`customer_preferences` 和 `min_rating` 保持可选；此报价入口不调用 LLM，
偏好文本不用于本轮报价排序，`min_rating` 仍是代码侧筛选条件。

先筛选目录候选，再通过 Service 获取模拟供应商回复；只有 `status=accepted`
且 `available=true`、请求身份与金额等校验通过的回复，才可进入 `data.quotations`。
报价价格来自回复 `quoted_total_cents`，不能用目录估价或模型输出代替。
推荐理由在本入口由已校验事实生成，不继承目录价格比较结论。

每项报价含 §4 的 `event_id`、`proposal_id`、`quotation_id`、`vendor_id`、
`service_type`、`quoted_total_cents`、`available`、`recommendation_reason`，
并补充 `offering_id`、`event_date`、`guest_count`、`scenario_id`、`mock=true`。
`quotation_id` 关联具体活动、方案、服务项、日期和人数，重复相同请求保持确定性。

`data.supplier_replies` 保留各候选的回复及原因：`accepted`、`rejected`、`pending`；
没有配置模拟回复时记录本地状态 `unconfigured`，这不代表供应商已作出回复。
未确认记录的 `available` 可为 `null`、金额为 `null`，不能作为报价交给 Financial。
供应商回复的这些状态与 envelope 四种 `status` 不同。

- 缺少或非法输入：`needs_input`；缺失/非法 `event_id` 时返回 `null`。
- 无候选，或所有回复均拒绝/未确认/无配置：`blocked`，保留原因与空报价列表。
- Service 失败、非法回复、请求不匹配或重复报价 ID：`error`，不释放部分报价。
- 至少一个有效报价：`success`，`data.quotations` 仅含有效报价；其他候选仍可能未确认。

本轮模拟回复由预设场景决定，不随机、不访问供应商客户端或网络。
缺少预设使用专门的 `NoQuotationScenarioError`（继承 `ValueError`）表示；
其他 `ValueError` 不得误判成“供应商尚未回复”。
本入口不进行付款、预订或档期锁定；可选报价持久化见 §5.4，正式预订仍需后续业务步骤。

离线示例：`py -3 -m examples.vendor_quotation_agent_example`。

### 5.3 Procurement 模拟正式预订入口（KAN-20）

`VendorProcurementManagerAgent.confirm_bookings(request)` 调用独立
`VendorBookingService`；构造 Agent 的可选第四参数为 `booking_service`。
原推荐与询价入口保持不变。`VendorBooking` 在 shared/schemas.py 中是本轮最小模型，
只按 §4/本节交接，不宣称复现完整 Stage 1 类定义。

**输入**：非空 `event_id`、`proposal_id`；非空 `quotations` 列表（从 §5.2 选定的有效报价）；
`approval`、`budget`、`deposit` 三条交接记录。每条记录必须具有同一活动和方案的 ID。

- `approval`：`approved`（真正的 bool）、`approved_quotation_ids`（恰好包含此次选定报价，不能重复）。
- `budget`：`within_budget`（真正的 bool）、正整数分 `deposit_due_cents`。
  后者由 Financial 根据统一配置提供，本模块不重算费率、不代替财务业务判断。
- `deposit`：`payment_id`、整数分 `amount_cents`、`status`（`pending`/`paid`/`failed`）、`mock=true`。
  必须为 `paid` 且实付不少于应付订金才允许发起预订。这是客户付给公司的订金，
  不代表公司已付款给供应商。
- **本轮新增联调字段**：三条记录都带 `quotation_fingerprint`，由
  `src.services.vendor_booking_service.quotation_fingerprint(quotations)` 计算。
  它关联选定报价的 ID、活动/方案、供应商/服务项、日期、人数、金额；顺序不影响结果。
  报价变更后，旧预算、批准和付款记录不能直接复用，需重新审核。
  Financial 和统一前端后续接入时需对齐这些字段；采购 Agent 不生成批准或已支付状态。

审批、预算、付款记录是受信任模块之间的结构化交接；本原型校验其内容和关联，
尚未通过数据库或支付网关验证记录真实性，不能用于真实交易。

校验门槛全部满足后才请求最终模拟供应商回复。回复为 `confirmed`、`rejected`、`pending`，
或本地记录 `unconfigured`（没有配置回复）；目录可用、询价 accepted 都不等于最终确认。
只有 `confirmed` 且回复身份/金额/确认编号有效才创建 `VendorBooking`，状态固定 `Confirmed`。
除 §4 字段外，预订含 `proposal_id`、`offering_id`、`service_type`、`event_date`、`guest_count`、
`quoted_total_cents`、`supplier_confirmation_id`、单条报价的 `source_quotation_fingerprint`、`mock=true`。

返回沿用统一 envelope，`data` 含 `bookings`、`supplier_replies`、原样保留的 `customer_payment`
及 `requires_attention`：缺失/非法输入为 `needs_input`；预算未通过、未批准、未付足订金、
关联过期或供应商未确认返回 `blocked`；非法回复或接口失败返回 `error`；全部选定预订
均已确认才返回 `success`。非 success 时不得生成 Operations 执行计划。

如果部分供应商已确认、另一家拒绝或出错，保留已确认记录并阻止整体推进；
已付订金保留为 paid，标记待处理，不自动退款、再次扣款或伪造取消。
相同 Service 实例内重复提交已确认报价复用预订，不再次联系对应供应商；
已有预订的报价内容变化时要求人工处理，不能重新预订覆盖旧记录。

**范围限制**：未注入存储 Service 时仍在内存保存，重启后丢失记录及重复保护；
可选 SQLite 持久化见 §5.4。不包含跨进程/并发保护、真实付款、退款或档期锁定。
离线示例：`py -3 -m examples.vendor_booking_example`；审批、预算及付款均明确为模拟输入。

### 5.4 Procurement 可选 SQLite 持久化（KAN-21）

`ProcurementRecordService` 负责采购记录的 SQLite 读写；Agent 不包含 SQL。
通过 `record_service=records` 分别注入采购 Agent（保存校验后的有效报价）和
`VendorBookingService`（保存及重新读取已确认预订），两者使用同一数据库文件。
默认不注入，现有内存示例与页面保持兼容。

- `ProcurementRecordService.from_env()` 读取 `ELEC5620_DB_PATH`；未配置时使用仓库根目录
  `runtime/procurement.sqlite3`。数据库及临时 journal 不入库，供应商目录仍为 JSON。
- `records.get_quotations(event_id, proposal_id)` 返回该活动/方案已保存的有效报价；
  `booking_service.get_bookings(event_id, proposal_id)` 返回已确认预订，供后续模块读取。
  读取结果不证明审批、预算、支付已通过；执行计划仍须满足 §2/§5.3 的完整前提。
- 保存报价使用原交接字段；预订使用 §5.3 的 VendorBooking 字段。金额仍为整数澳元分，
  所有模拟标记保留。没有回复、pending 或 rejected 不会保存成有效报价/已确认预订。
- 相同记录重复保存复用；相同活动/方案/报价 ID 对应不同内容时拒绝覆盖。
  报价变更需新方案/报价身份并重新审核，不能改写旧记录；整批报价保存失败时全部回滚。
- 以同一路径重新创建 Service 后仍能读取记录；相同已确认报价通过原门槛后复用预订，
  不重复请求供应商。报价内容与既有预订不同仍阻止推进。
- 初始化或存储失败明确报错，不静默切换到空内存。供应商已确认但保存失败时返回 `error`，
  输出保留该确认及原支付记录，需在重启前保留结果并人工核对。数据库事务无法与外部回复原子提交。

本轮仅持久化采购报价和已确认预订，不替其他成员保存方案、预算、审批、付款或整条流程状态。
不支持并发预订协调；调用者应串行提交。进程在供应商确认后、保存前崩溃仍可能失去重复保护，
不宣称实现真实交易或跨系统“恰好一次”。离线示例使用临时数据库：
`py -3 -m examples.procurement_persistence_example`。

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

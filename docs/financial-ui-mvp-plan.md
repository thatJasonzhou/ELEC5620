## Financial 独立演示页

本地 Streamlit 页面复用现有 Financial／Procurement Agent 和 Service，完整支持
询价、预算、客户报价、显式模拟批准、订金、供应商预订、尾款、模拟完成证明、
供应商结算和只读财务核对。Planning／Operations 为 **STUB**；供应商回复和付款为 **MOCK**。
无需 API Key，不发起 LLM／支付网络请求；尚未接入真实 Operations 或活动关闭。

```powershell
$env:ELEC5620_DEPOSIT_RATE = '0.30'
# 可选：指定所有演示 Service 共用的数据库
# $env:ELEC5620_DB_PATH = 'C:\path\financial-demo.sqlite3'
.\.venv\Scripts\python.exe -m streamlit run ui/financial_ui.py
```

未配置数据库时保存到项目根目录 `runtime/financial-demo.sqlite3`，与供应商独立页面
默认库分开。若需共享，显式设置相同 `ELEC5620_DB_PATH`。订金比例无默认值，沿用
现有环境变量／项目 `.env` 读取；无效时页面禁用支付操作。

手动验收顺序（一个本地操作员，供应商付款串行）：

1. 点击 **Create new demo** → **Request mock quotations**。
2. **Save selection and budget** → **Calculate budget** → **Generate customer quotation**。
3. **Approve current quotation (mock customer)** → **Prepare deposit request** → **Simulate deposit payment**。
4. **Confirm mock supplier booking**。此时生成模拟完成证据后尝试准备供应商款，
   30% 实收不足时应阻塞；财务核对也应因欠款／未结算而阻塞。
5. **Prepare final payment request** → **Simulate final payment**，确认客户余额为零。
6. **Generate mock invoice and completion evidence** → **Prepare supplier payment** → **Simulate supplier payment**。
7. **Run financial check (mock scope)**，确认仅在保存的模拟结算范围内通过。
8. 刷新／重启页面，选择原活动，确认记录恢复、已付款按钮禁用，核对仍通过。

异常演示：创建另一个活动，在生成订金请求前将预算改为 AUD 1，保存后旧批准失效，
预算计算阻塞，不能继续报价／付款。已创建付款请求的活动冻结输入；换方案请创建新演示，
不清除历史。模拟完成证明可能早于活动日期，页面明确提示模拟提前完成场景。
付款结果不确定时不要重付。供应商演示执行标记在调用前保存，无终态结果时要求人工核查；
没有自动恢复或真实网关 exactly-once 保证。

自动页面验收使用 Streamlit AppTest；浏览器视觉检查仍需按上面步骤手动执行。
实施细节见 [实施方案](docs/financial-ui-mvp-plan.md)。

# Financial 独立演示 MVP 实施方案

日期：2026-10-23。状态：代码与自动验收已实现；浏览器手动验收待执行。

实现补充：为避免供应商执行结果保存失败后再次付款，在演示上下文中增加
vendor_execution_attempts，调用前持久化；有执行标记却无 paid/failed 终态时阻止重试。
不修改现有业务付款表和 KAN-27 核心接口。

## 1. 交付范围

交付独立 Streamlit 页面，跑通：模拟活动输入 → Procurement 询价 → Financial
预算／客户报价 → 用户批准 → 订金 → Procurement 正式模拟预订 → 尾款 →
模拟完成证据 → 供应商结算 → 只读财务核对。

Operations 和 Planning 输入标注 STUB，供应商回复和支付标注 MOCK。
不宣称真实 Operations 集成、活动关闭或完整 Supervisor/LangGraph 集成已完成。
不改三个遗留 UML 占位方法、现有 Agent 继承、PaymentService 签名或付款规则。
本轮不增加 FastAPI 或 LangGraph；它们属于整体系统后续集成。

## 2. 最小演示约束

- 单进程、单操作员、本地运行，供应商付款串行执行。
- 首个主路径固定 catering、Melbourne、2026-12-05、120 人，匹配现有询价和预订 fixture。
- 首次只选一个可接受报价，避免引入多供应商部分预订与替换流程。
- 可编辑预算上限用于超预算演示；首版不开放任意日期／人数输入，避免找不到供应商场景。
- 客户及 due_date 创建后固定；预算／选中报价变更可用于批准失效测试。
- 已有订金请求后冻结本次演示的业务上下文；需要换方案则创建新演示活动。
  历史记录保留；跨版本已收款调整仍由现有核心支持，但不纳入此页面首版。
- 此限制在 UI 和应用 Service 同时检查。不能只禁用按钮。
- 不提供自动重试、退款、失败后换请求重新付款或删除数据库按钮。

## 3. 文件与职责

新增文件：

| 文件 | 职责 |
|---|---|
| `ui/financial_ui.py` | 页面布局、表单、按钮、金额格式、结果呈现 |
| `src/demo/__init__.py` | 明确 demo 包边界 |
| `src/demo/financial_app.py` | 依赖装配及演示协调，调用各 Agent，不做金额计算 |
| `src/demo/context_service.py` | SQLite 演示上下文、版本、用户批准、失效检查 |
| `src/demo/operations_stub.py` | 显式创建并读取模拟完成证据、固定结算范围 |
| `tests/unit/test_financial_demo_context.py` | 上下文版本、批准、冻结和证据一致性 |
| `tests/unit/test_financial_ui.py` | Streamlit AppTest 关键操作与重渲染安全 |
| `tests/integration/test_financial_demo_flow.py` | 真实 Service 间的完整模拟交接 |
| `tests/e2e/test_financial_ui_flow.py` | 页面完整主路径和重启恢复 |

更新 README、shared-data-and-interfaces.md、docs/architecture.md；维护
docs/contributions.md（当前磁盘中不存在，实际开发时创建并填写真实成员和 Issue Key）。
先取得真实 Jira Issue Key，再建立 feature 分支；本方案不虚构编号。

这些是演示层内部 helper，不是新增业务 Agent，不替换 PlanningService 或
EventOperationsService。实现前将 helper 关系与 Stage 1 UML 核对；若有冲突，
记录具体冲突并取得明确确认后再做相关改动。

## 4. 依赖装配与存储

FinancialDemoApp(database_path) 显式构造：

1. ProcurementRecordService、FinancialRecordService、VendorPaymentRecordService。
2. MockPaymentService，以及禁止发生实际调用的 MockLLMClient。
3. VendorSettlementService(payment_service, procurement_records, vendor_records)。
4. FinancialReconciliationService(financial_records, procurement_records,
   vendor_records, context_provider=app.current_context,
   scope_provider=operations_stub.get_scope)。
5. 注入上述依赖的 FinancialManagerAgent。
6. VendorProcurementManagerAgent，配置现有目录、MockVendorQuotationService、
   MockVendorBookingService，以及带 record_service 的 VendorBookingService。

路径统一：优先 ELEC5620_DB_PATH；本页面未配置时使用项目根目录
runtime/financial-demo.sqlite3，启动时由协调层统一解析后显式传入所有 Service。
不要让不同 Service 分别回退到不同默认数据库。
订金比例继续使用现有 ELEC5620_DEPOSIT_RATE 配置读取机制；缺失／非法时显示
配置错误并禁用付款，不自行使用 30% 默认值。README 给出 0.30 演示配置。

新增两张仅供演示层使用的表，不迁移既有财务／Procurement 表：

- demo_financial_contexts：event_id 主键、revision 整数、payload_json、updated_at。
  payload 保存 schema_version=1、customer_id、due_date、event、proposal、
  selected_quotation_ids、原始 budget、原始 customer_quotation、approval。
- demo_operations_evidence：event_id 主键、payload_json、created_at。
  payload 保存 scope、按 booking_id 索引的 invoice 和 completion。

当前报价从 Procurement 存储读取；收付款／请求／执行状态从现有财务表读取。
演示表不复制付款事实、不维护可变余额、不改变已保存财务快照。
上下文修改和批准写入使用事务及 expected_revision，过期操作返回 blocked。
读取失败返回 error，不能回退到空上下文或重新初始化活动。

## 5. 演示应用接口

所有业务操作返回现有标准 envelope。协调层只组装输入、检查演示前置条件、
调用 Agent；金额、指纹和付款状态判定复用现有 Service。

```python
create_demo() -> dict                         # 唯一 event_id/proposal_id；不付款、不预订
load_demo(event_id: str) -> dict              # 从 SQLite 恢复
request_quotations(event_id: str) -> dict     # Procurement.request_quotations
update_selection(event_id, selected_ids, budget_limit_cents, expected_revision) -> dict
prepare_budget(event_id: str) -> dict
generate_customer_quotation(event_id: str) -> dict
approve_customer_quotation(event_id, customer_quotation_id, expected_revision) -> dict
prepare_deposit(event_id: str) -> dict
pay_deposit(event_id, deposit_request_id, amount_cents) -> dict
confirm_bookings(event_id: str) -> dict       # Procurement.confirm_bookings
get_customer_balance(event_id: str) -> dict
prepare_final(event_id: str) -> dict
pay_final(event_id, final_request_id, amount_cents) -> dict
create_operations_stub(event_id: str) -> dict # 显式操作；从完整预订集合固定 scope
prepare_vendor_payment(event_id, booking_id) -> dict
pay_vendor(event_id, payment_id, amount_cents) -> dict
reconcile(event_id: str) -> dict
get_history(event_id: str) -> dict
```

付款输入的金额来自保存请求，页面只读；应用每次仍调用核心重新校验。
pay_* 在显式点击时才组装 simulate=true；加载、刷新、准备请求均不得付款。

## 6. 输入组装规则

Financial 公共上下文从 context_service 和存储读取，至少包含：
event_id、proposal_id、event、proposal、quotations、selected_quotation_ids、budget、
customer_quotation、customer_id、due_date、approval。

批准字段沿用现有契约：event_id、proposal_id、customer_quotation_id、
quotation_fingerprint、approved=true、approved_quotation_ids。
演示审计元数据（revision、approved_at、source=DEMO_USER）保存在上下文中，
不能伪造为真实 Planning 或 Owner 批准。

预算／选择变更原子清空当前 budget、customer_quotation 和 approval 引用，revision+1；
历史财务快照不删除。旧页面提交批准必须因 revision 不符而阻塞。
每次付款从持久化当前上下文重新组装，不接受 UI 上传的完整批准对象。

Procurement 预订：

- quotations 仅传批准的选中报价，顺序与预算的 selected_quotation_ids 一致。
- approval 复用当前批准，不伪造独立批准。
- deposit 使用现有 Service 保存的成功订金原始记录。
- budget 传原始预算的副本，并补 deposit_due_cents=保存订金请求的 amount_cents。
  不将该补充字段写回原始预算快照，不重新计算订金。
- 验证选中报价的 quotation_fingerprint 与既有交接数据一致；不修改指纹算法。
- 未支付订金不得创建 booking；供应商拒绝时保留付款并显示 requires_attention。

不要复用 examples.vendor_payment_example.demo_inputs：该函数会预存 booking 并
自动收全额客户款，违反页面逐步显式操作要求。也不要复用示例中的虚构已付订金。

## 7. Operations STUB 的明确行为

用户点击“生成模拟完成证明”后，从该演示活动所有 proposal 的持久化 booking
生成固定结算范围，不从付款历史反推范围，不只读取当前 proposal。
仅处理本演示支持的 Confirmed mock booking；发现无法解释的状态或缺失报价时阻塞。

scope 格式沿用 §5.11：event_id、settlement_scope_id、scope_complete=true、
bookings=[{proposal_id, vendor_booking_id, quotation_id, vendor_id}]。
空预订集合在此演示路径阻塞，不生成可造成“无供应商责任”的空范围。

每个 booking 创建符合 §5.8 的 invoice／completion：

- 发票 amount_cents 等于已保存报价全额；currency=AUD；mock=true。
- 五项身份字段全部来自 booking／quotation，invoice_number、completion_id 唯一。
- completed_at 使用生成时的带时区 UTC 时间，不用未来活动日期伪造未来完成时间。
- 由于 fixture 活动日期可能尚未到来，页面显示“模拟提前完成场景”，不宣称真实履约。
- issued_date 为生成日；不直接套用现有绑定 EV001/VB1 的固定证据 JSON。
- 证据生成后持久化，重复点击返回同一证据和时间戳，不覆盖已结算依据。
- scope 是模拟声明的完整范围；后续检测 booking 集合变化则阻塞，不静默重建。

默认 scope_provider 只读取保存证据；未生成返回缺失，核对 blocked。
未来真实 Operations 接入替换证据来源和 scope_provider，当前财务契约保持不变。

## 8. 页面行为

页面标题 Financial Demo，常驻 MOCK / Planning STUB / Operations STUB 标记。
顶部选择已保存演示活动，或显式“创建新演示”；不在首次渲染自动创建活动。

依次呈现六个区域：输入与询价、预算与报价、客户批准与订金、供应商预订、
尾款与供应商结算、记录与核对。每个区域显示前置条件和最后结果。

session_state 只保存当前 event_id、表单草稿和展示结果；持久化事实从 Service 读取。
Streamlit rerun 不执行写入、询价、批准或付款；只有按钮／form_submit 才调用操作。
付款后重新读取余额和历史；即使 envelope=success，也必须检查付款 paid/failed。
核对只显示“模拟结算范围内财务核对通过／未通过”，没有活动关闭按钮。
requires_reconciliation／executing 等不确定状态提示人工核查，禁止界面自动重付。

## 9. 实施顺序与验收

1. 实现 context_service 和 operations_stub，测试恢复、批准失效、固定证据。
2. 实现 FinancialDemoApp 和真实 Agent 交接，先通过无 UI 的完整流程测试。
3. 实现 Streamlit 页面和 AppTest，验证逐步点击与 rerun 无副作用。
4. 更新契约、架构说明、README、真实 Issue 和成员贡献记录。
5. 运行单元／集成／E2E，并手动启动页面演示。

验收案例：

- 从全新数据库开始，未点击批准／付款时，没有已批准或 paid 事实。
- 超预算返回 blocked，客户报价／付款／预订无法继续。
- 批准后、创建订金请求前修改预算或选择，旧批准不能使用；历史报价保留。
- 订金支付后可预订；准备供应商结算时若实收不足，应阻塞。
- 付清尾款、显式生成模拟证据、逐笔结算后，客户和供应商余额为零，核对通过。
- 缺少范围、供应商未付款、客户有欠款均不能通过核对。
- 重复点击付款和页面刷新无新增支付调用；重建所有 Service 后仍复用结果。
- 结果不确定／存储读取失败显示阻塞或错误，不显示成功、不自动重试。
- Operations 生成证据前后均不修改 Procurement booking 的 Confirmed 状态。

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/integration/ -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/e2e/ -q -p no:cacheprovider
# 实现后的手动验收入口
.\.venv\Scripts\python.exe -m streamlit run ui/financial_ui.py
```

预估 3–5 人日；此为实施估计。已知核心基线为此前检查的 816 项测试通过，
不代表本方案中尚未编写的演示层测试已经通过。

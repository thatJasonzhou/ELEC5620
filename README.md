# ELEC5620

One-Person AI Event Management Company — Stage 2 代码库。

## 环境要求

- Python **3.12**（当前开发环境为 3.12.7；最低要求 3.10+）
- 依赖清单见 [requirements-dev.txt](requirements-dev.txt)

安装测试依赖：

```powershell
py -3 -m pip install -r requirements-dev.txt
```

## 当前功能

### 供应商确定性筛选（KAN-15）

基于虚构供应商目录 `data/vendor_catalog.json`（catering / photography），
按服务类型、日期、人数、地点进行确定性筛选，入口为
`VendorProcurementService.filter_vendors`。

运行示例（独立示例输入 + 运行入口）：

```powershell
py -3 -m examples.vendor_filtering_example
```

### 供应商推荐（KAN-16）

`VendorProcurementManagerAgent`（agent 标识 `procurement`）在确定性筛选的
候选集上调用 LLM 生成 1–3 条推荐；价格、评分、容量等事实从目录回填，
`basis_codes`（`lowest_price` / `highest_rating` / `highest_capacity`）
经代码对当前候选集复核。接口细节见
[shared-data-and-interfaces.md](shared-data-and-interfaces.md) 第 5.1 节。

**真实 LLM API 已验证**（2026-10-19，`CampusQwenClient` 经
`ELEC5620_LLM_*` 环境变量调用学校 Campus Qwen 代理）：

- endpoint 为**完整 URL**：`.../v1/chat/completions`（`ELEC5620_LLM_BASE_URL`
  需包含 `/chat/completions`，客户端不做拼接）
- 模型名：`campus-qwen`
- 认证方式：`Authorization: Bearer <key>`，已确认有效
- 响应格式：OpenAI 风格 `choices[0].message.content`，解析正确
- 一次真实 Agent 推荐运行：返回 2 条推荐（状态 `success`），返回 ID
  均来自候选集，事实字段从目录回填，basis codes 全部通过代码复核；
  模型未虚构候选集外的供应商或事实

因此**演示与自动化测试默认仍使用 `MockLLMClient`**（无网络依赖），
输出显式标注 MOCK；需要真实调用时显式传 `--live`。

运行推荐示例（默认 Mock，独立示例输入 + 显式 MOCK 标注）：

```powershell
py -3 -m examples.vendor_recommendation_example
```

运行真实 LLM 调用（一次性，仅 `--live` 时发起真实请求）。凭据与配置
**只来自环境变量**，不写入代码、文档或命令行：

```powershell
# 先设置环境变量（PowerShell）：
#   $env:ELEC5620_LLM_API_KEY = "<学校代理的 API key>"
#   $env:ELEC5620_LLM_BASE_URL = "http://<host>:<port>/v1/chat/completions"
#   $env:ELEC5620_LLM_MODEL = "campus-qwen"
py -3 -m examples.vendor_recommendation_example --live
```

真实模式输出显式标注 LIVE；缺少任一环境变量时以明确的
`LLMError` 退出（只提示变量名，不回显值），并建议改回 Mock 运行。

运行单元测试（含 LLM 层与推荐 Agent 测试，全部基于 Mock，无网络）：

```powershell
py -3 -m pytest tests/unit/ -v
```

### 供应商推荐演示页面（KAN-17）

英文 Streamlit 演示页 `ui/vendor_procurement_ui.py`，复用 KAN-15 的
`VendorProcurementService` 与 KAN-16 的 `VendorProcurementManagerAgent`，
**默认 Mock 模式**（不发起真实 LLM 调用、无网络依赖），也支持显式切换到
**Live 模式**（调用学校 Campus Qwen 代理），用于快速演示筛选与推荐流程：

```powershell
py -3 -m streamlit run ui/vendor_procurement_ui.py
```

页面行为：

- 表单输入活动日期、城市、人数、服务类型、（可选）最低评分与客户偏好；
  页面会提示目录中可用的示例日期 / 城市 / 服务类型（从目录动态读取）；
- 表单上方有 **Mock / Live 模式切换**（单选按钮，**默认 Mock**）：
  - 切换模式本身只重新渲染页面，**不构造客户端、不调用 LLM 或网络**；
  - **只有提交表单时才调用 API**（Mock 走确定性构造器，Live 走
    `CampusQwenClient`）；
  - Live 模式配置**仅从环境变量读取**（`ELEC5620_LLM_API_KEY` /
    `ELEC5620_LLM_BASE_URL` / `ELEC5620_LLM_MODEL`，同 KAN-16：
    `BASE_URL` 须为完整的 `.../v1/chat/completions` 端点，客户端不做
    拼接），API Key 只提示变量名、永不回显；Live 配置缺失或初始化
    失败时显示明确的 error 提示，**不静默回退到 Mock**；
- 提交后先显示确定性筛选出的候选供应商表（LLM 之前，代码筛选）；
- Mock 推荐由**模拟 LLM**（`MockLLMClient` + 确定性构造器，纯函数实现
  在 `ui/vendor_ui_helpers.py`）基于当前候选集生成（最高评分 → 最低价
  → 最高容量，去重后 1–3 条），页面显著标注 MOCK MODE；推荐 ID 与事实
  均来自当前候选集，无硬编码供应商 ID；
- 无候选 / 输入错误等状态均有明确提示；每次新提交都会替换上一次结果，
  失败运行不会残留上一次的正常结果；
- 不含预订、付款或持久化。

离线 UI 测试（`streamlit.testing.v1.AppTest`，无需浏览器、无网络；
覆盖正常路径、无候选、结果替换与 Mock/Live 模式切换）：

```powershell
py -3 -m pytest tests/unit/test_vendor_ui.py -v
```

### Supplier enquiries and quotations (KAN-19)

`VendorProcurementManagerAgent.request_quotations(request)` is a separate,
offline quotation entry point. Supply a `MockVendorQuotationService` as
the optional third constructor argument. The existing recommendation
`handle(request)`, CLI and Streamlit UI continue to work unchanged.

Provide `event_id`, `proposal_id`, `service_type`, `event_date`,
`guest_count` and `location`; optional rating/preference fields retain
their input validation. Only confirmed `accepted` mock supplier replies
become `data.quotations`. `data.supplier_replies` preserves declined,
pending and unconfigured replies. Missing presets never imply acceptance.
The quotation price comes from the supplier response, not the catalogue
estimate or an LLM. This entry point makes no LLM/network calls and does
not create bookings or collect payments. Optional quotation persistence is described under KAN-21.

```powershell
py -3 -m examples.vendor_quotation_example
py -3 -m examples.vendor_quotation_agent_example
py -3 -m pytest tests/unit/test_vendor_quotation_agent.py tests/unit/test_vendor_quotations.py -q
```

### Simulated booking confirmation (KAN-20)

`VendorProcurementManagerAgent.confirm_bookings(request)` delegates to an
optional fourth constructor dependency, `booking_service=VendorBookingService(...)`.
Existing two/three-argument construction and recommendation/quotation entries
remain compatible. Before a supplier call, provide the current selected mock
quotations, matching approval, Financial budget/deposit requirement, and paid
mock customer-deposit records. Each handoff record must carry the current
`quotation_fingerprint`, calculated with the helper in `vendor_booking_service`.
Financial supplies positive `deposit_due_cents`; Procurement does not calculate
a deposit rate or process payments. See root contract section 5.3 for fields.

Only a validated final supplier `confirmed` reply creates a `VendorBooking`
with `status=Confirmed`. A refusal, pending/unconfigured reply or error blocks
downstream execution and retains any previously confirmed bookings and the
paid deposit record for review. No automatic charge, refund or cancellation
is performed. All external replies and example approval/payment are MOCK.

Without `record_service`, the booking store remains **in memory per Service instance**.
KAN-21 adds opt-in SQLite persistence below. Concurrent supplier requests and real
payment integration remain future work. The existing Streamlit page is unchanged.

```powershell
py -3 -m examples.vendor_booking_example
py -3 -m pytest tests/unit/test_vendor_bookings.py -q
```


### Procurement SQLite persistence (KAN-21)

`ProcurementRecordService` saves immutable accepted quotation snapshots and
confirmed mock bookings in SQLite (standard library; no new dependency).
Use one database path for both dependencies:

```python
records = ProcurementRecordService.from_env()
bookings = VendorBookingService(supplier_service, record_service=records)
agent = VendorProcurementManagerAgent(llm, vendors, quotation_service, bookings,
                                     record_service=records)
```

Set `ELEC5620_DB_PATH` to a file path, or use the repository-root default
`runtime/procurement.sqlite3`. Relative overrides resolve from the working
directory. Runtime databases and journal files are ignored by Git. Instantiating
this dependency explicitly enables persistence; existing examples/UI stay in
memory. Initialization errors raise `ProcurementStorageError` for the application
entry point to handle. No silent fallback to an empty in-memory database occurs.

Financial can call `records.get_quotations(event_id, proposal_id)`; Operations can
call `bookings.get_bookings(event_id, proposal_id)`. These return saved records,
not an assertion that customer approval, budget or payment has been verified.
All existing booking gates still apply. Recreate Services with the same database
to reload bookings and avoid re-sending already confirmed supplier requests.
An existing identity with different contents raises a conflict; use reviewed new
proposal/quotation identities rather than overwrite history. A quotation batch
is saved atomically. Rejected/pending replies never become saved quotations or
confirmed bookings.

This persists Procurement records only: Planning, Financial, approval/payment
records and whole-workflow progress are not persisted by this change. Callers
must serialize booking attempts. An external confirmation followed by a failed
database save is returned as `error`, with confirmation and paid record retained
in the result for manual review. A crash in that interval can still lose restart
protection; this is not a distributed exactly-once booking guarantee.

```powershell
py -3 -m examples.procurement_persistence_example
py -3 -m pytest tests/unit/test_procurement_persistence.py -q
```

The offline example uses a temporary SQLite file, recreates its Services, and
checks that the booking ID survives with zero supplier calls after reload. It
deletes its temporary database on exit; no live API or payment is used.

### Financial Foundation (KAN-23)

本 Story 提供 `FinancialManagerAgent(AIAgent)` 骨架、`PaymentService`
抽象接口，以及公共 `Budget`、抽象 `Payment`、`CustomerPayment`、
`VendorPayment` 最小模型。复用已有 `envelope()`、LLM 接口和公共校验函数。
KAN-23 本身不包含预算计算、客户报价、模拟或真实支付、退款、持久化或 Supervisor 集成；
预算计算与检查由 KAN-24 提供，模拟支付由 KAN-26/27 提供，可选持久化见 KAN-29；
退款和 Supervisor 集成仍未实现。

直接从具体模块导入，不需要修改包级导出：

```python
from src.agents.financial_manager import FinancialManagerAgent
from src.services.payment_service import PaymentService
from src.shared.schemas import Budget, Payment, CustomerPayment, VendorPayment
```

构造 Agent 需要传入现有 `LLMClient` 和实现完整抽象接口的 `PaymentService`
子类；本 Story 不提供支付实现，当前预算检查也不调用这些依赖。
Foundation 定义的入口形式是 `handle({"event_id": "EV001", "action": "prepare_budget"})`；
KAN-24 已实现 `prepare_budget`，实际预算请求还须提供下节列出的完整业务输入。
合法 action 还包括 `update_proposal_cost`、`record_customer_payment`、
`settle_vendor_payment`、`reconcile_payments`。这些业务方法仍抛出
`NotImplementedError`，Agent 转为包含 `NOT_IMPLEMENTED` 的 `error` 信封，
不返回虚构的成功结果。缺失或非法外层字段返回 `needs_input`，非 dict 返回 `error`。
预算业务输入验证现由 KAN-24 提供；其他业务流程尚未实现。

ID 使用字符串、金额使用非负整数澳元分；状态和付款类型必须由调用者提供非空字符串，
Foundation 不定义默认业务状态或状态转换；KAN-24 创建的预算记录使用 `Calculated`，不代表客户批准。
模型使用 Python `date` 和带时区的 `datetime`；
本 Story 不提供 JSON 序列化或 Decimal 转换层。未发生的付款/批准事实可为 `None`。
UML 映射、关联限制及已批准的 KAN-24 Budget 调整见 [架构记录](docs/architecture.md)。

在仓库根目录使用项目虚拟环境运行（无需激活）：

```powershell
# Financial 基础测试（离线，不依赖 Streamlit）
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_financial_foundation.py -q -p no:cacheprovider
# 完整单元回归；现有 UI 测试要求环境已安装 Streamlit
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ -q -p no:cacheprovider
# 仅验证非 UI 回归时使用，不能称作完整测试通过
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ -q -p no:cacheprovider --ignore=tests/unit/test_vendor_ui.py
```

### Financial Budget Check V1 (KAN-24)

KAN-24 在 KAN-23 Foundation 基础上新增 UC4 预算计算与检查，保留现有 Agent、
Budget 和统一响应 envelope。

FinancialManagerAgent.handle() accepts action="prepare_budget", event, proposal,
quotations and selected_quotation_ids. Budget.calculate_total() owns deterministic
calculation; it never calls an LLM or payment service. No BudgetService is needed.
The request carries event_id; event supplies event_id, event_date, guest_count and
budget_limit_cents; proposal supplies event_id, proposal_id and required_services.
quotations are Procurement snapshots; selected_quotation_ids explicitly selects
which quotations contribute to the current proposal's budget.

All prices and budget limits are GST-inclusive. Service fee and contingency are
each 10% of the selected vendor total, independently ROUND_HALF_UP to integer
AUD cents. Total is the sum of these three amounts; no GST is added separately.
The approved tax_amount_cents=0 placeholder means no separate tax breakdown.

Results include amount breakdown, budget_valid, within_budget, over_budget_cents,
selected IDs and quotation_fingerprint. Equality is within budget. Overruns return
blocked with complete details. Under the approved Scheme B, Procurement requires
this complete budget result and checks amount types, selected quote cost sum,
component totals, budget limit/within_budget consistency, identities, current quote
fingerprint, customer approval and deposit. It does not construct Budget or
recalculate the service fee or contingency rates.
A valid calculation alone does not authorize booking.

Supplier replies still use Procurement Mock scenarios. PaymentService remains
an abstract dependency; mock payments are provided by KAN-26/27, optional budget
persistence by KAN-29. Invoice workflows and automatic Planner revision are deferred.
Full interface: shared-data-and-interfaces.md sections
5.3 and 5.5.

KAN-24 example and tests (repository root, existing virtual environment):

```powershell
.\.venv\Scripts\python.exe -B -m examples.budget_check_example
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_budget_check.py tests/unit/test_budget_v1.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_budget_handoff.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -B -m pytest tests/e2e/test_budget_check_cli.py -q -p no:cacheprovider
# Full regression, including UI tests requiring Streamlit
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ tests/integration/ tests/e2e/ -q -p no:cacheprovider
```

### Customer quotation generation (KAN-25)

Run `python -m examples.customer_quotation_example` for an offline Procurement
→ FIN-01 → customer quotation demonstration. Financial Manager accepts
`action="generate_customer_quotation"` with the same current event, proposal,
quotations and selected IDs as `prepare_budget`, plus `budget=budget_result["data"]`.
The returned `data.customer_quotation` contains vendor references and costs,
service fee, contingency, estimated customer total, provenance and timestamp.
All amounts are integer AUD cents, copied from the KAN-24 FIN-01 budget.

Missing, over-budget, incomplete or stale budgets block generation. Older budget
handoffs without the new source/budget fingerprints require explicit FIN-01
validation again. See section 5.6 of [the contracts](shared-data-and-interfaces.md).
Generation does not perform approval, booking or payment. KAN-29 adds optional
quotation persistence and reuse when record_service is injected.

### Record customer deposits (KAN-26)

Financial supports `prepare_deposit_request` and `simulate_deposit_payment` via
the existing Agent `handle` interface, using `MockPaymentService`. Preparation
creates only pending requests; only an explicit `simulate=true` payment call
can create paid evidence. No UI, gateway, LLM payment decision or booking is added.

Set required `ELEC5620_DEPOSIT_RATE` in the process environment or project-root
`.env`; `.env.example` provides an example. `.env` is already ignored by Git.
Process environment takes precedence, even when invalid. The Financial config
reader reads only this setting from `.env`, requires a finite `0 < rate <= 1`,
and has no default. No extra dependencies or shell activation are necessary.
Tests set explicit isolated configuration; the Demo uses your actual setting.

Customer Quotation's existing `estimated_total_cents` is its customer-facing
GST-inclusive quote total (vendor cost + service fee + contingency), copied from
FIN-01. There is no separate final-price field. Deposit uses this quoted total
only after receiving external approval for the specific customer quotation ID.
Decimal multiplication and ROUND_HALF_UP yield integer cents; a result below
one cent is blocked. No pricing or public total field is changed.

```powershell
.\.venv\Scripts\python.exe -B -m examples.deposit_payment_example
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ tests/integration/ tests/e2e/ -q -p no:cacheprovider
```

Demo approval is explicitly external MOCK test input, not Financial-generated
approval. It prepares pending, simulates a customer click, retries the payment,
and submits the output to existing KAN-20 validation with no supplier confirmation
configured. Validation reaches the unconfigured supplier reply and creates no booking.
See shared contract section 5.7 for Integration inputs and outputs.

Without record_service, records live in memory per Agent/DepositService instance
and restarting loses them. KAN-29 adds optional SQLite restart protection below;
cross-process exactly-once is not claimed.
Integration must supply authoritative current snapshots and approval on every call;
there is no independent Planning approval/revocation store yet.


### Manage Vendor Payments (KAN-27)

`VendorSettlementService` is the single mock vendor settlement workflow.
Inject `MockPaymentService`, `ProcurementRecordService`, and
`VendorPaymentRecordService` with an explicit SQLite path (normally the existing
`ProcurementRecordService.from_env().database_path`, using `ELEC5620_DB_PATH`).
Inject the settlement service into `FinancialManagerAgent` using the optional
`settlement_service=` keyword; existing Story 5 construction remains compatible.

- `action="prepare_vendor_payment_request"`: provide `event_id`, `proposal_id`,
  structured `invoice` and `completion` objects. Validates persisted Procurement
  bookings/quotations and saves a pending record without calling the provider.
- `action="simulate_vendor_payment"`: provide the same evidence plus `simulate=true`,
  the prepared `payment_id`, and exact integer `amount_cents`.
- Results use `data.vendor_payment`. Payment statuses are pending/paid/failed;
  envelope success is independent of payment status. Failed payments return blocked.
- `MockPaymentService(vendor_outcome="success" | "failure")` selects deterministic
  vendor outcomes in trusted test/demo setup. Customer deposits retain their behavior.

Invoice/completion fixtures in `data/mock_vendor_invoices.json` and
`data/mock_service_completions.json` are mock inputs, not persisted Procurement
records. Their exact validated snapshots are retained with the payment. The CLI
seeds mock Procurement snapshots into a temporary database for demonstration only.

Only full settlement after mock completion is supported. Owner Approval, vendor
prepayments, partial/instalment payments, real gateways and UI changes are deferred.
`approved_at` remains null. `settle_vendor_payment(booking)` remains a legacy UML
stub; use the structured actions above, not a second payment path.

Calls must be serialized. SQLite uniqueness prevents duplicate booking/invoice
records, and persisted paid/failed status prevents another provider invocation,
including after restart. Failed payments are terminal; no automatic retries occur.
Cross-process coordination and crash recovery are deferred. If execution succeeds
but saving fails, or the process stops between execution and save, retain the error
and perform manual review before any further execution; durable exactly-once
processing is not claimed.

```powershell
.\.venv\Scripts\python.exe -B -m examples.vendor_payment_example
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ tests/integration/ tests/e2e/ -q -p no:cacheprovider
```

### Financial persistence and recovery (KAN-29)

Inject the internal SQLite helper explicitly:

```python
from src.services.financial_record_service import FinancialRecordService
records = FinancialRecordService.from_env()
agent = FinancialManagerAgent(llm, MockPaymentService(), record_service=records)
```

Use `ELEC5620_DB_PATH` (default `runtime/procurement.sqlite3`) consistently with
Procurement and KAN-27. Existing constructions without this dependency remain in
memory. Initialization fails explicitly; enabled persistence never falls back silently.
Valid calculated budgets, including overruns, customer quotations and deposit
requests/results are saved in dedicated schema-versioned tables. Existing tables
are not migrated. PaymentService, Budget calculation and budget fingerprints remain unchanged.

Business identities use SQLite unique constraints. Identical retries preserve
original IDs/timestamps; changed immutable contents conflict. Deposit due date,
customer, amount and quote association are immutable. Repeated preparation also
returns the original paid record after current approval validation.

Pure quotation validation creates no UUID or stored quote. Customer payment first
commits an execution marker; paid evidence and completion are saved atomically.
Storage failures return error. Interrupted or uncertain execution blocks automatic
retries after restart and requires manual review, even if the visible record is
still pending. This journal applies to customer deposits; KAN-27 keeps its existing
settlement behavior. No automatic reconciliation or cross-process exactly-once is added.

`action="get_event_financial_records"` takes event_id and optional proposal_id.
It returns budgets, customer_quotations, deposits and vendor_payments collections;
customer payment evidence is inside each deposit. Vendor history reads existing
JSON payloads without migrating or initializing the vendor table. Empty history
is success with empty collections; read failure is error. Current approval remains
mandatory for preparation/payment, including paid retries. History is not approval.

Implementation decisions: [shared interfaces](shared-data-and-interfaces.md),
sections 5.9 (persistence) and 5.10 (customer collection protection).
The CLI uses a temporary database, external MOCK approval and actual deposit-rate
configuration, verifies restart recovery and zero repeated payment calls, then removes
its own temporary database. No UI changes or live calls are included.

```powershell
.\.venv\Scripts\python.exe -B -m examples.financial_persistence_example
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ tests/integration/ tests/e2e/ -q -p no:cacheprovider
```

## KAN-30：模拟客户尾款与余额

保留 Story 1 的“创建请求 → 显式模拟支付 → 保存结果”流程。FinancialManagerAgent
新增 `get_customer_balance`、`prepare_final_payment_request`、`simulate_final_payment`，
委派给 CustomerBalanceService。复用 CustomerPayment、PaymentService 和现有 SQLite
财务存储；不修改 Stage 1 继承关系或接口签名，不调用 LLM 决定金额。

余额 = 当前批准客户报价 `estimated_total_cents` − 同活动、客户下已持久化的成功付款。
按 payment_id 去重，历史报价下的成功订金继续抵扣；pending、failed、待核对及供应商付款
不计入。仅有完整有效成功凭据的 paid 记录可抵扣，凭据异常阻止计算并要求核对。

三个入口沿用订金的当前报价、预算、方案、客户批准、customer_id 和 due_date 输入。
准备返回 `data.final_payment`、`data.execution_state`、`data.balance`；查询余额返回
final_payment=null。模拟付款还需 `simulate=true`、`final_request_id` 和精确的
`amount_cents`。错误活动、客户、金额及失效报价均被阻止。

同报价、客户仅复用仍有效且金额等于当前余额的 prepared 请求。余额或报价变化使旧未执行
请求 stale，可创建新请求；零余额不创建请求。付款状态仍为 pending/paid/failed，执行状态
单独使用 prepared/executing/completed/stale/requires_reconciliation。
paid 和 failed 均为该请求终态，重放返回原结果，不再次调用 Mock。
`MockPaymentService(customer_outcome="failure")` 可显式演示失败，余额保持不变。

订金和尾款必须使用同一 FinancialRecordService 数据库（ELEC5620_DB_PATH）。SQLite
事务在付款前检查余额并持久化共享收款占用，防止两个入口同时收款；成功保存结果后原子释放。
执行中断、结果不确定或结果保存失败时保留占用并要求人工核对，禁止自动重付。硬终止或
数据库持续故障可能保留 executing/execution_started，同样阻止新收款。重启从付款结果
重新计算余额，不维护独立余额缓存。原来的内存订金演示不提供这套跨实例保护。

离线演示使用临时 SQLite、外部模拟批准及明确的付款操作，验证订金抵扣、尾款清零、
重建 Agent 后恢复和重复调用零新增扣款；不需要 API Key：

```powershell
$env:ELEC5620_DEPOSIT_RATE = '0.30'
.\.venv\Scripts\python.exe -B -m examples.final_payment_example
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ tests/integration/ tests/e2e/ -q
```

`get_event_financial_records` 额外返回 final_payments；完整输入输出见
[接口约定 §5.10](shared-data-and-interfaces.md#510-customer-final-payment-and-balance-kan-30)。
最新报价和批准由 Integration 提供；本轮“过期”指与当前快照或批准不一致，未增加报价有效期。
少付、多付、退款、失败后重新扣款、自动核对及真实支付网关留待后续，无新增 UI/API 页面。


### 财务只读核对（KAN-32）

`FinancialManagerAgent.reconcile_payments(event_id) -> bool` 与
`handle({"event_id": "EV001", "action": "reconcile_payments"})` 复用
`FinancialReconciliationService`。后者返回标准 finance envelope，包含客户余额、
供应商应付/已付/未结算项、证据引用及原因码。欠款、未结算或必要依据缺失返回
`blocked`，读取故障返回 `error`；Boolean 入口在系统错误时抛出存储异常。

构造 Agent 时注入 `reconciliation_service`；Service 注入同一 SQLite 路径的
FinancialRecordService、ProcurementRecordService、VendorPaymentRecordService，
以及可信的 `context_provider(event_id)` 和 Operations `scope_provider(event_id)`。
未配置 Service 或有效范围会阻塞。接口见公共文档 §5.11。
核对使用同一只读事务，不执行付款、重试、记录修复或活动关闭。

运行离线演示和验证：

```powershell
py -3 -B -m examples.financial_reconciliation_example
py -3 -m pytest tests/unit/ tests/integration/ tests/e2e/ -q
```

演示先显式创建模拟付款事实，再核对；Operations 范围明确为 **STUB**。
本阶段仅验证 Financial 与持久化模块，真实 Operations 权威范围接入及
活动关闭端到端验收仍是后续依赖，最终关闭由 Operations 执行。

## 目录结构

| 路径 | 说明 |
|---|---|
| `data/vendor_catalog.json` | 虚构供应商目录（供应商、服务项目、可用性） |
| `src/shared/schemas.py` | `Vendor` / `VendorServiceOffering` / `VendorAvailability`（示例数据结构，非完整 Stage 1 类定义） |
| `src/services/vendor_procurement_service.py` | `VendorProcurementService`：目录加载与确定性筛选 |
| `src/llm/` | LLM 包装层：`base`（抽象客户端/错误）、`campus_qwen`（真实代理客户端，已验证）、`mock`（测试/演示用脚本化客户端） |
| `src/agents/` | `AIAgent` 基类、`VendorProcurementManagerAgent` 与 `FinancialManagerAgent`（统一信封输出） |
| `examples/vendor_filtering_example.py` | KAN-15 独立示例输入与运行入口 |
| `examples/vendor_recommendation_example.py` | KAN-16 推荐示例（默认 MockLLMClient 标注 MOCK；`--live` 发起一次真实调用，标注 LIVE） |
| `tests/unit/test_vendor_filtering.py` | 筛选、输入校验与目录加载校验测试 |
| `tests/unit/test_llm_mock.py` | LLM 层与 MockLLMClient 行为测试 |
| `tests/unit/test_campus_qwen_client.py` | 真实客户端的离线测试（mock `urlopen`，无网络）：endpoint/timeout 校验、鉴权、重试与脱敏错误 |
| `tests/unit/test_vendor_procurement_agent.py` | 推荐 Agent 的输入校验、事实回填与 basis codes 复核测试 |
| `ui/vendor_procurement_ui.py` | KAN-17 供应商推荐 Streamlit 演示页（默认 Mock，可切换 Live；仅提交表单时调用 API，Live 配置从环境变量读取） |
| `ui/vendor_ui_helpers.py` | 演示页的 Streamlit 无关辅助模块（确定性 Mock 推荐构造器 `mock_response_from_prompt`），可被单元测试直接导入 |
| `tests/unit/test_vendor_ui.py` | 演示页离线 UI 测试（AppTest：正常 / 无候选 / 结果替换 / Mock 无硬编码 ID / Mock-Live 模式切换不触发调用） |
| `src/services/vendor_quotation_service.py` | KAN-19 deterministic simulated supplier replies |
| `data/mock_vendor_quotations.json` | Explicit mock acceptance / rejection / pending presets |
| `examples/vendor_quotation_agent_example.py` | Offline Agent quotation handoff example |
| `tests/unit/test_vendor_quotation_agent.py` | Quotation gates, reply validation and compatibility tests |
| `src/services/vendor_booking_service.py` | KAN-20 mock final replies, gates and memory-only bookings |
| `data/mock_vendor_bookings.json` | Explicit final supplier booking preset |
| `examples/vendor_booking_example.py` | Offline quotation-to-booking example with mock approval/payment |
| `tests/unit/test_vendor_bookings.py` | Booking gates, final replies, partial results and retry tests |
| `src/services/procurement_record_service.py` | KAN-21 opt-in SQLite Procurement records |
| `examples/procurement_persistence_example.py` | Offline save/reload/repeat demonstration |
| `tests/unit/test_procurement_persistence.py` | Durable records, isolation, conflicts and failure tests |
| `src/services/payment_service.py` | Stage 1 PaymentService 抽象接口，无支付实现 |
| `tests/unit/test_financial_foundation.py` | 财务继承、基础校验、错误信封与未实现行为测试 |
| `src/services/financial_record_service.py` | KAN-29 财务快照与订金执行日志 |
| `examples/financial_persistence_example.py` | 离线保存、重建 Service、恢复和重复付款保护演示 |
| `tests/unit/test_financial_records.py` / `test_financial_persistence.py` | 存储与财务工作流故障、冲突和恢复测试 |

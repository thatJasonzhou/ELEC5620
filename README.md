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

## Financial Foundation (KAN-23)

本 Story 只提供 `FinancialManagerAgent(AIAgent)` 骨架、`PaymentService`
抽象接口，以及公共 `Budget`、抽象 `Payment`、`CustomerPayment`、
`VendorPayment` 最小模型。复用已有 `envelope()`、LLM 接口和公共校验函数。
不包含预算计算、客户报价、模拟或真实支付、退款、持久化或 Supervisor 集成。

直接从具体模块导入，不需要修改包级导出：

```python
from src.agents.financial_manager import FinancialManagerAgent
from src.services.payment_service import PaymentService
from src.shared.schemas import Budget, Payment, CustomerPayment, VendorPayment
```

构造 Agent 需要传入现有 `LLMClient` 和实现完整抽象接口的 `PaymentService`
子类；本 Story 不提供支付实现，Foundation 本身也不调用这些依赖。
临时入口是 `handle({"event_id": "EV001", "action": "prepare_budget"})`。
合法 action 还包括 `update_proposal_cost`、`record_customer_payment`、
`settle_vendor_payment`、`reconcile_payments`。所有业务方法均抛出
`NotImplementedError`，Agent 转为包含 `NOT_IMPLEMENTED` 的 `error` 信封，
不返回虚构的成功结果。缺失或非法外层字段返回 `needs_input`，非 dict 返回 `error`。
完整业务输入验证尚未实现。

ID 使用字符串、金额使用非负整数澳元分；状态和付款类型必须由调用者提供非空字符串，
不定义默认业务状态或状态转换。模型使用 Python `date` 和带时区的 `datetime`；
本 Story 不提供 JSON 序列化或 Decimal 转换层。未发生的付款/批准事实可为 `None`。
UML 映射、关联限制及待确认项见 [架构记录](docs/architecture.md)。

在仓库根目录使用项目虚拟环境运行（无需激活）：

```powershell
# Financial 基础测试（离线，不依赖 Streamlit）
.\.venv\Scripts\python.exe -B -m pytest tests/unit/test_financial_foundation.py -q -p no:cacheprovider
# 完整单元回归；现有 UI 测试要求环境已安装 Streamlit
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ -q -p no:cacheprovider
# 环境缺少 Streamlit 时可单独验证非 UI 回归，不能称作完整测试通过
.\.venv\Scripts\python.exe -B -m pytest tests/unit/ -q -p no:cacheprovider --ignore=tests/unit/test_vendor_ui.py
```

## 目录结构

| 路径 | 说明 |
|---|---|
| `data/vendor_catalog.json` | 虚构供应商目录（供应商、服务项目、可用性） |
| `src/shared/schemas.py` | 供应商模型、`VendorBooking` 及 Financial Foundation 核心模型（非完整 Stage 1 实现） |
| `src/services/vendor_procurement_service.py` | `VendorProcurementService`：目录加载与确定性筛选 |
| `src/llm/` | LLM 包装层：`base`（抽象客户端/错误）、`campus_qwen`（真实代理客户端，已验证）、`mock`（测试/演示用脚本化客户端） |
| `src/agents/` | `AIAgent` 基类、采购 Agent 与 Financial Foundation Agent（统一信封输出） |
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
| `docs/architecture.md` | Financial 类关系、UML 映射与已知实现限制 |

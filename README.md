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

**真实 LLM API 尚未验证**：`src/llm/campus_qwen.py` 目前只能作为接口占位
实现使用，以下事项待与学校确认后才会可用——

- `ELEC5620_LLM_BASE_URL` 的 URL 语义（完整 endpoint 还是 base URL）
- `ELEC5620_LLM_MODEL` 的可用模型名
- 认证方式（当前假设 `Authorization: Bearer <key>`）
- 响应格式（当前假设 OpenAI 风格 `choices[0].message.content`）

因此演示与测试默认使用 `MockLLMClient`，输出显式标注 MOCK。

运行推荐示例（默认 Mock，独立示例输入 + 显式 MOCK 标注）：

```powershell
py -3 -m examples.vendor_recommendation_example
```

运行单元测试（含 LLM 层与推荐 Agent 测试，全部基于 Mock）：

```powershell
py -3 -m pytest tests/unit/ -v
```

## 目录结构

| 路径 | 说明 |
|---|---|
| `data/vendor_catalog.json` | 虚构供应商目录（供应商、服务项目、可用性） |
| `src/shared/schemas.py` | `Vendor` / `VendorServiceOffering` / `VendorAvailability`（示例数据结构，非完整 Stage 1 类定义） |
| `src/services/vendor_procurement_service.py` | `VendorProcurementService`：目录加载与确定性筛选 |
| `src/llm/` | LLM 包装层：`base`（抽象客户端/错误）、`campus_qwen`（真实代理客户端，待验证）、`mock`（测试/演示用脚本化客户端） |
| `src/agents/` | `AIAgent` 基类与 `VendorProcurementManagerAgent`（统一信封输出） |
| `examples/vendor_filtering_example.py` | KAN-15 独立示例输入与运行入口 |
| `examples/vendor_recommendation_example.py` | KAN-16 推荐示例（默认 MockLLMClient，输出标注 MOCK） |
| `tests/unit/test_vendor_filtering.py` | 筛选、输入校验与目录加载校验测试 |
| `tests/unit/test_llm_mock.py` | LLM 层与 MockLLMClient 行为测试 |
| `tests/unit/test_vendor_procurement_agent.py` | 推荐 Agent 的输入校验、事实回填与 basis codes 复核测试 |

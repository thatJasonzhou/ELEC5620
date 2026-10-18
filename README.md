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

## 目录结构

| 路径 | 说明 |
|---|---|
| `data/vendor_catalog.json` | 虚构供应商目录（供应商、服务项目、可用性） |
| `src/shared/schemas.py` | `Vendor` / `VendorServiceOffering` / `VendorAvailability`（示例数据结构，非完整 Stage 1 类定义） |
| `src/services/vendor_procurement_service.py` | `VendorProcurementService`：目录加载与确定性筛选 |
| `src/llm/` | LLM 包装层：`base`（抽象客户端/错误）、`campus_qwen`（真实代理客户端，已验证）、`mock`（测试/演示用脚本化客户端） |
| `src/agents/` | `AIAgent` 基类与 `VendorProcurementManagerAgent`（统一信封输出） |
| `examples/vendor_filtering_example.py` | KAN-15 独立示例输入与运行入口 |
| `examples/vendor_recommendation_example.py` | KAN-16 推荐示例（默认 MockLLMClient 标注 MOCK；`--live` 发起一次真实调用，标注 LIVE） |
| `tests/unit/test_vendor_filtering.py` | 筛选、输入校验与目录加载校验测试 |
| `tests/unit/test_llm_mock.py` | LLM 层与 MockLLMClient 行为测试 |
| `tests/unit/test_campus_qwen_client.py` | 真实客户端的离线测试（mock `urlopen`，无网络）：endpoint/timeout 校验、鉴权、重试与脱敏错误 |
| `tests/unit/test_vendor_procurement_agent.py` | 推荐 Agent 的输入校验、事实回填与 basis codes 复核测试 |

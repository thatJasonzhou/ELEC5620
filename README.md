# ELEC5620

One-Person AI Event Management Company — Stage 2 代码库。

## 环境要求

- Python **3.12**（当前开发环境为 3.12.7；最低要求 3.10+）
- 依赖清单见 [requirements-dev.txt](requirements-dev.txt)

安装测试依赖：

```powershell
py -3 -m pip install -r requirements-dev.txt
```

## 当前功能：供应商确定性筛选（KAN-15）

基于虚构供应商目录 `data/vendor_catalog.json`（catering / photography），
按服务类型、日期、人数、地点进行确定性筛选，入口为
`VendorProcurementService.filter_vendors`。

运行示例（独立示例输入 + 运行入口）：

```powershell
py -3 -m examples.vendor_filtering_example
```

运行单元测试：

```powershell
py -3 -m pytest tests/unit/ -v
```

## 目录结构

| 路径 | 说明 |
|---|---|
| `data/vendor_catalog.json` | 虚构供应商目录（供应商、服务项目、可用性） |
| `src/shared/schemas.py` | `Vendor` / `VendorServiceOffering` / `VendorAvailability`（示例数据结构，非完整 Stage 1 类定义） |
| `src/services/vendor_procurement_service.py` | `VendorProcurementService`：目录加载与确定性筛选 |
| `examples/vendor_filtering_example.py` | 独立示例输入与运行入口 |
| `tests/unit/test_vendor_filtering.py` | 筛选、输入校验与目录加载校验测试 |

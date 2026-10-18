# AGENTS.md — ELEC5620 Stage 2 开发规范

## 1. 项目背景

- 课程：ELEC5620 Model-Based Software Engineering。
- 项目：One-Person AI Event Management Company（一人 AI 活动管理公司）。
- Stage 2 目标：基于 Stage 1 的需求（含 15 个 Use Cases）与 UML 设计，交付可运行的原型，体现多 Agent 协作、LLM 能力与 Agile 开发过程。

## 2. 架构原则

### 已确认

1. Supervisor-Worker 架构：Supervisor 不直接执行业务计算。
2. 四个业务 Agent（Worker）：Event Planner、Vendor Procurement Manager、Financial Manager、Event Operations。
3. 保留 Stage 1 已确定的类继承、依赖与组合关系，实现时不擅自调整。
4. LLM 统一经 Campus Qwen API Proxy 调用；API Key 管理见第 9 节。
5. 原型优先：先打通端到端可演示流程，避免过度设计。

### 待确认（以 Stage 1 UML 核对结果为准）

- Agent 间消息 / 数据交换协议与 JSON 字段定义。
- Worker 执行顺序与异常分支。
- Worker 是否允许并行执行。
- 状态持久化 / checkpoint 机制。

以上待确认事项在核对前不作为强制实现约束。

## 3. 四个 Agent 职责（按 Stage 1 Use Case 分工）

| Agent | Use Case 分工 |
|---|---|
| Supervisor |
| Event Planner | UC1、UC2、UC5、UC6；主导 UC10 |
| Vendor Procurement Manager | UC3、UC7；参与供应商相关变更与异常处理 |
| Financial Manager | UC4、UC8、UC13 |
| Event Operations | UC9、UC11、UC12、UC14、UC15 |

- UC10 为跨 Agent 协作流程，由 Planner 主导、Supervisor 协调其余 Agent 配合。
- 各 UC 的具体名称与边界以 Stage 1 文档为准。
- 详细 UC → Agent 映射见 `docs/architecture.md`。

## 4. Stage 1 类图与 Service 接口约束

- 保留抽象基类 `AIAgent` 及四个 Agent 子类，具体命名以 Stage 1 类图为准。所有业务 Agent 必须继承 `AIAgent`，不得绕过基类约定。
- 业务操作统一通过 Service 接口完成，至少包括：
  - `PlanningService`
  - `VendorProcurementService`
  - `PaymentService`
  - `EventOperationsService`
- Agent 不直接操作数据库或绕过业务规则。
- 其余实体与关系（继承、依赖、组合、关联及 Multiplicity）以 Stage 1 原始 UML 为准。

**UML 冲突处理规则：**

1. Stage 1 已批准的设计是 Stage 2 实现的基准。
2. 如果实现方案与 Stage 1 UML 发生冲突，必须先记录冲突及可能的解决方案。
3. 向用户说明冲突原因、影响范围和建议调整方式。
4. 在获得用户明确确认之前，不得擅自修改 Stage 1 设计、相关实现或本文件中的架构约束。
5. 获得批准后，才可同步更新相关设计文档和代码，并在 `docs/architecture.md` 中记录调整原因。

## 5. 技术栈

- LLM：Campus Qwen API Proxy（学校提供）。
- Agent 编排：LangGraph。
- API 服务：FastAPI。
- 前端：Streamlit。
- 存储：SQLite。
- 供应商数据：JSON 模拟数据文件。

## 6. 开发规范

1. 代码与文档保持一致，并符合 Stage 1 交付物；发现与 UML 冲突时先记录，不擅自变更设计。
2. 模块职责单一；Agent 代码置于 `src/agents/` 对应文件，Agent 之间不互相引用。
3. 所有 LLM 调用统一走 `src/llm/` 包装模块，prompt、参数、重试与异常兜底集中管理。
4. 数据流转使用结构化 JSON；每个 Agent 输出须包含 agent 名、时间戳、状态等可追溯字段。
5. 配置（模型名、endpoint、数据库路径）集中在配置模块 / 环境变量管理。

## 7. 测试要求

1. 开发阶段：每次代码变更后运行相关的单元测试（`pytest tests/unit/`）。
2. 模块集成后：运行集成测试（`pytest tests/integration/`）。
3. 功能完成 / 交付前：运行端到端测试（`pytest tests/e2e/`），并完成一次手动演示流程验证。
4. 测试未通过不得发起合并。

## 8. GitHub + Jira 团队协作规则

### 课程要求

根据 ELEC5620 项目说明，Stage 2 需要：

1. 基于 Stage 1 的需求、架构和 UML 设计进行原型开发，并实现大部分模型。
2. 展示 LLM 对 Agent 感知、决策和交互能力的增强。
3. 体现 Agile 软件开发实践。
4. 在实现中使用先进技术。

团队成员的个人贡献应按课程提交与评分要求明确记录。

课程并未指定必须使用 Jira、特定 Git 分支策略或 Pull Request 审核制度。以下规则属于团队采用的开发管理规范，而非课程强制规定。

### 团队协作规范

1. **Jira 任务管理**
   - 每个功能或缺陷应建立对应的 Jira Issue。
   - 使用真实 Jira Issue Key（例如 `KAN-14`）追溯开发工作。

2. **Feature Branch**
   - 新功能在独立分支开发，避免直接修改 `main`。
   - 推荐命名：`feature/KAN-14-event-planner`。
   - 通用格式：`<type>/<JIRA-Key>-<short-desc>`。

3. **Commit 规范**
   - 格式：`type: description (KAN-14)`。
   - type 可使用 `feat`、`fix`、`docs`、`test`、`refactor`、`chore`。
   - Commit 信息应明确表达修改内容。

4. **Pull Request**
   - 推荐一个 Jira Issue 对应一个 PR。
   - PR 描述应包含 Issue Key、变更说明及测试结果。
   - 原则上至少经过一名队友审查后合并。
   - 发现阻塞性问题时，应在解决后再合并。

5. **个人贡献记录**
   - 在 Jira Issue 中记录负责人、完成内容及工作进度。
   - 在 `docs/contributions.md` 中维护贡献汇总，包括成员、Issue Key、职责和日期。
   - 确保贡献记录能够支持课程最终的个人贡献说明。

## 9. 安全与执行约定

- API Key 只允许在运行时通过环境变量加载。
- 禁止将 API Key 硬编码到代码或文档中。
- 禁止将 API Key 输出到日志、控制台或任何界面。
- 禁止将 API Key 或其他敏感凭据提交到 GitHub。
- 本文件仅记录项目规范，不包含业务代码。

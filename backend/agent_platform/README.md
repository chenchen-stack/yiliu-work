# 亿流 Work · Agent Platform（LangGraph）

与提示词 `亿流Work-LangGraph完整实现` 对齐的实现落点（不重复新建 `yiliu_work/` 根包，而是在本目录扩展）。

## 架构映射

| 提示词 | 本仓库路径 |
|--------|------------|
| `graph/state.py` | `workflow/state.py` — `WorkflowGraphState` + `AgentGraphState` |
| `graph/workflow_engine.py` | `workflow/engine.py` — `build_fangtai_workflow()` + `PlatformWorkflowEngine` |
| `graph/workflow_nodes.py` | `workflow/nodes.py` |
| `graph/router.py` | `workflow/router.py` |
| Checkpoint | `workflow/checkpoint.py` |
| `graph/agent_engine.py` | `agent/agent_engine.py` |
| `skills/registry.py` | `core/registry.py` |
| `skills/executor.py` | `core/executor.py` |
| Workflow API | `api/routes.py` — `/workflow/*` |
| Agent API | `api/routes.py` — `/agent/chat` |
| 生产任务入口 | `app/services/workflow_facade.py` |
| **生产对话 SSE** | `app/services/chat_agent_bridge.py` + `POST /api/v1/chat/stream` |

## 改造路线图（优先级）

| 优先级 | 项 | 状态 | 说明 |
|--------|-----|------|------|
| **P0** | 任务走 LangGraph Workflow | ✅ 默认开启 | `USE_LANGGRAPH_WORKFLOW=true`，`workflow_facade` |
| **P1** | 对话 SSE 桥接 | ✅ 已接入 | `POST /chat/stream`；**`POST /chat` 仍走 `agent_runtime`**（UI 块不丢） |
| **P1b** | 前端 ChatCenter 消费 SSE | ✅ 已接入 | `chatStream.ts` + `ChatAgentTrace`，`ChatCenter` 走 `/chat/stream` |
| **P1c** | 差异解释 + 管理端开关 | ✅ 已接入 | `agent_chat_json` @ 大模型配置；`diff_explain_via_agent` |
| **P2** | DB `Workflow.nodes` 动态编译图 | 🚧 脚手架 | `graph_builder.py` + `USE_DYNAMIC_WORKFLOW_GRAPH`（默认 false，仍用方太硬编码图） |
| **P3** | 全量 ReAct 替换 runtime | ⏳ | `USE_LANGGRAPH_AGENT=true` + 将 UI 块生成迁回 adapter |

### 为何 P1 不直接替换 `POST /chat`？

`agent_runtime` 承担：意图识别、数据源确认块、差异列表、对账发起、知识库引用等 **UI 协议**。`PlatformAgentEngine` 目前是 **纯文本 + Tool 流**。因此：

- **同步接口** `/chat` → 继续 `run_agent_turn`
- **流式接口** `/chat/stream` → 默认 SSE；`agent_chat.enabled` 时走 PlatformAgent（含可选差异解释）；对账卡片 / `client_action` 仍走 runtime

## 方太 Workflow 图（硬编码，当前生产）

```
data_import → field_mapping → difference_detect
  ├─(有差异)→ anomaly_explain → review_flow ─┬─(全部确认)→ report_gen → END
  │                                          └─(有退回)→ re_verify ↺ review_flow
  └─(无差异)──────────────────────────────→ report_gen → END
```

`interrupt_before=[review_flow]`

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `USE_LANGGRAPH_WORKFLOW` | `true` | 任务执行走 LangGraph |
| `USE_DYNAMIC_WORKFLOW_GRAPH` | `false` | 从 DB 编译图（当前回退硬编码） |
| `USE_PLATFORM_CHAT_SSE` | `true` | `/chat/stream` 开放问答走 PlatformAgent |
| `USE_LANGGRAPH_AGENT` | `false` | Platform `/agent/chat` ReAct |
| `USE_MOCK_LLM` | `true` | 无 Key 时占位 |

## Skill 执行

所有节点经 `SkillExecutor` → `app.services.skill_registry`，与 legacy `WorkflowEngine` 共用 `skill_packages/`。

## 对话 SSE 事件（`/chat/stream`）

| type | 含义 |
|------|------|
| `session` | `conversation_id` |
| `thinking` | 模型流式片段 |
| `tool_call` | Skill 调用 |
| `plan` | `plan_steps`（runtime） |
| `ui_blocks` | 富 UI 块（runtime） |
| `reply` | 最终文本 |
| `error` | 错误 |
| `done` | 结束元数据 |

关闭 LangGraph Workflow：`USE_LANGGRAPH_WORKFLOW=false`

## Skill 后台测试（管理端）

| 能力 | API | 说明 |
|------|-----|------|
| **自然语言对话测试** | `POST /api/v1/skill-test/sessions/{id}/chat`（SSE） | `SkillTestAgent` 规划并调用 Skill；管理端「Skill 库」弹窗 → **对话测试** |
| 预设场景 | `POST /api/v1/skill-test/sessions/{id}/preset` | 完整对账 / 只看差异等 |
| **结构化单次执行** | `POST /api/v1/skill-packages/{code}/execute` | JSON `input_data` + 可选 `task_id` |
| **yaml 内置用例** | `POST /api/v1/skill-packages/{code}/test` | 跑 `skill.yaml` 中 `tests` |

前端入口：**后台 → Skill 库 → 点击卡片** → 弹窗顶部 Tab：**对话测试**（默认）| **标准文件** | **结构化测试** | **接口**。

自然语言测试在服务端执行；未绑定任务时部分 Skill 会返回 dry_run 提示，需先在「工作台」创建对账任务。

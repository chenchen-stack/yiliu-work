# query_tasks — 任务查询

## 元信息

- **skill_id**: skill-query_tasks
- **fangtai_ref**: FT-SKILL-CHAT-001
- **name**: 任务查询
- **type**: 能力型
- **category**: 对话辅助
- **description**: 查询当前用户的收入核对任务列表，返回最近任务的状态、进度与待复核条数（对话 Skill，非 Workflow 节点）
- **tags**: [任务列表, 对话, 进度查询]
- **version**: 1.0.0
- **status**: 已发布

## 接口定义

### 输入

```json
{
  "user_id": "user-001",
  "limit": 10,
  "status_filter": "running"
}
```

### 输出

```json
{
  "total": 3,
  "tasks": [
    {
      "id": "task-uuid",
      "name": "2024-05月收入核对",
      "status": "review",
      "progress": 85,
      "period": "2024-05"
    }
  ]
}
```

## 执行逻辑

1. 按 `user_id` 过滤 `tasks` 表（或全员最近任务）
2. 排序：更新时间倒序，取 `limit` 条
3. 返回结构化列表供对话 `task_list` 卡片渲染

## 依赖

- `Task` 模型 / tasks API
- Agent 授权 `skill-query_tasks`

## 配置参数

见 `config.yaml`

## 调用关系

对话内直接调用，不在七步 Workflow 链路中

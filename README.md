# 亿流 Work 中台 · MVP P0

面向企业财资领域的 Agent 中台 — **收入核对中心**完整闭环。

## 快速启动

### 1. 后端

```powershell
cd yiliu-work\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

API 文档：http://127.0.0.1:8000/docs

### 2. 前端

```powershell
cd yiliu-work\frontend
npm install
npm run dev
```

访问：http://localhost:5173

### 3. 演示账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | 管理员（发布业务中心） |
| lili | finance123 | 财务员（新建任务、复核） |
| wangzong | manager123 | 财务经理 |
| ops1 | ops123 | 运营（责任处理） |

### 4. MVP 演示流程

1. **admin** 登录 → 管理后台 → 发布「收入核对中心」
2. **lili** 登录 → 工作台 → 新建核对任务 → 选择「完整演示数据集」
3. 等待执行完成 → 差异列表 → 确认/退回/指派
4. **ops1** 登录 → 提交处理反馈
5. **lili** → 再次验证 → 生成报告 → 关闭任务 → 沉淀案例
6. 差异详情 → 继续追问 → 收入差异解释 Agent
7. **admin** → 案例库 → 创建规则新版本 → 重新发布

### 5. 演示数据

`sample-data/dataset_full/` — 含正常匹配、金额差异、重复数据、映射异常  
`sample-data/dataset_full/corrected/` — 再次验证用处理后数据

### 6. 自动化验收

```powershell
cd yiliu-work\backend
python scripts\mvp_e2e_test.py
```

完整界面勾选清单见：`docs/亿流Work-MVP跑通验收步骤.md`

## 架构

| 层级 | MVP 实现 |
|------|----------|
| L1 交互入口 | 工作台 + 对话 + 管理后台 |
| L2 能力执行 | WorkflowEngine + 7 Skills + 收入差异解释 Agent |
| L3 本体翻译 | 字段映射 + 三类规则 + 证据链 |
| L4 数据接入 | 演示数据 + 文件上传 |

详细文档见 `/docs/` 目录。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card, Table, Tag, Button, Space, Typography, Drawer, Descriptions,
  message, Modal, Input, Alert, Tabs, Select, Tooltip,
} from 'antd'
import {
  CheckOutlined, CloseOutlined, UserAddOutlined, DownloadOutlined, ReloadOutlined,
  MessageOutlined, AuditOutlined, RobotOutlined, SafetyCertificateOutlined,
} from '@ant-design/icons'
import {
  getTask, getDifferences, getTaskAuditLogs, getWorkflowRuns, getUsers,
  reviewDifference, reExplainDifference, submitProcessing, verifyTask, generateReport, closeTask,
  archiveCase, getReportUrl, getTaskSkillInvocations, continueWorkflow, approveTaskReview,
  resumeTaskExecution, getLlmStatus,
  Difference, Task, User, AuditLog, SkillInvocation, LlmStatus,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { usePublishedCenter } from '../context/PublishedCenterContext'
import { PAGE_MODULE_KEYS, createShowAuditSection } from '../utils/pageModules'
import {
  VersionBadges, AiModeBadge, AuditTracePanel, TaskExecutionPanel,
} from '../components/TrustComponents'
import { DiffExplanationProse, DiffRuleEvidenceSection } from '../components/DiffEvidenceSections'
import {
  ReconciliationSystemSummary,
  SystemVsAiBlock,
  DiffTrustActions,
  EvidenceSourceList,
} from '../components/TrustDiffUI'

const TASK_STATUS: Record<string, string> = {
  draft: '草稿', running: '执行中', pending_review: '待复核', processing: '处理中',
  pending_verification: '待验证', reporting: '报告输出', closed: '已关闭', failed: '失败',
}

const STATUS_COLOR: Record<string, string> = {
  pending_review: 'gold', confirmed: 'green', rejected: 'red', assigned: 'blue',
  processing: 'cyan', pending_verification: 'orange', resolved: 'green', returned: 'volcano', closed: 'default',
}

const DIFF_TYPE_COLOR: Record<string, string> = {
  '金额差异': 'orange',
  '重复数据': 'purple',
  '映射异常': 'magenta',
  '接口/同步异常': 'volcano',
  '回款差异': 'geekblue',
  '帆软汇总差异': 'green',
}

export default function TaskDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { center, showModule, refresh: refreshCenterConfig } = usePublishedCenter()
  const showAuditSection = useMemo(() => createShowAuditSection(center), [center])
  const [task, setTask] = useState<Task | null>(null)
  const [diffs, setDiffs] = useState<Difference[]>([])
  const [selected, setSelected] = useState<Difference | null>(null)
  const [comment, setComment] = useState('')
  const [assignee, setAssignee] = useState<string>()
  const [users, setUsers] = useState<User[]>([])
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([])
  const [invocations, setInvocations] = useState<SkillInvocation[]>([])
  const [loading, setLoading] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [reporting, setReporting] = useState(false)
  const [reExplaining, setReExplaining] = useState(false)
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null)
  const [processText, setProcessText] = useState('')
  const autoContinued = useRef(false)
  const autoReport = useRef(false)
  const me = JSON.parse(localStorage.getItem('user') || '{}')

  const load = useCallback(async () => {
    if (!id) return
    const [t, d, lg, wr, inv] = await Promise.all([
      getTask(id), getDifferences(id), getTaskAuditLogs(id), getWorkflowRuns(id), getTaskSkillInvocations(id),
    ])
    setTask(t)
    setDiffs(d)
    setLogs(lg)
    setRuns(wr)
    setInvocations(inv)
  }, [id])

  useEffect(() => {
    load().catch(console.error)
    getUsers().then(setUsers).catch(console.error)
    getLlmStatus().then(setLlmStatus).catch(() => setLlmStatus(null))
  }, [load])

  useEffect(() => {
    const waitingAutoContinue = task?.status === 'pending_review' && diffs.length === 0
    const waitingReport = task?.status === 'reporting' && !(task.summary?.report_path)
    const shouldPoll = task && (['running', 'draft'].includes(task.status) || waitingAutoContinue || waitingReport)
    if (!shouldPoll) return undefined
    load().catch(console.error)
    const timer = setInterval(() => { load().catch(console.error) }, 800)
    return () => clearInterval(timer)
  }, [load, task?.status, task?.summary?.report_path, diffs.length])

  useEffect(() => {
    if (!id || !task || autoReport.current) return
    if (task.status === 'reporting' && !task.summary?.report_path) {
      autoReport.current = true
      setReporting(true)
      generateReport(id)
        .then(() => {
          message.success('PDF 报告已自动生成')
          return load()
        })
        .catch((e: unknown) => {
          autoReport.current = false
          const err = e as { response?: { data?: { detail?: string } } }
          message.error(err.response?.data?.detail || '报告生成失败，请手动重试')
        })
        .finally(() => setReporting(false))
    }
  }, [id, task, load])

  useEffect(() => {
    if (!id || !task || autoContinued.current) return
    if (task.status === 'pending_review' && diffs.length === 0) {
      autoContinued.current = true
      continueWorkflow(id)
        .then(() => {
          message.success('无差异，Workflow 已自动进入报告阶段')
          return load()
        })
        .catch((e: unknown) => {
          autoContinued.current = false
          console.error(e)
        })
    }
  }, [id, task, diffs.length, load])

  const aiMode = (task?.summary?.ai_mode as string) || undefined

  const handleResumeExecution = async () => {
    if (!id) return
    setResuming(true)
    try {
      await resumeTaskExecution(id)
      message.success('已重新发起执行，请稍候刷新')
      await load()
    } catch (e: unknown) {
      message.error(formatApiError(e, '重新执行失败'))
    } finally {
      setResuming(false)
    }
  }

  const canOpenAdmin = me.role === 'admin' || me.role === 'manager'

  const handleReExplain = async (preferLlm = false) => {
    if (!selected) return
    if (preferLlm && !llmStatus?.runtime_ready) {
      message.warning(llmStatus?.hint || '大模型未就绪，请先在管理后台配置 API Key 并关闭模拟模式')
      return
    }
    setReExplaining(true)
    try {
      const updated = await reExplainDifference(selected.id, preferLlm)
      setSelected(updated)
      setDiffs((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      const rec = updated.ai_recommendation as {
        model?: string
        fallback_reason?: string
      } | undefined
      const model = rec?.model || ''
      if (preferLlm) {
        if (model.startsWith('rule')) {
          message.warning(
            rec?.fallback_reason
              ? `大模型调用失败，已回退规则解释：${rec.fallback_reason}`
              : '大模型调用失败，已回退为规则引擎解释',
          )
        } else {
          message.success(`已使用大模型（${model}）重新生成解释`)
        }
      } else {
        message.success(
          model.startsWith('rule')
            ? '已按当前检测规则重新生成解释'
            : '已使用大模型重新生成解释',
        )
      }
    } catch (e: unknown) {
      message.error(formatApiError(e, '解释生成失败'))
    } finally {
      setReExplaining(false)
    }
  }

  const handleReview = async (decision: string) => {
    if (!selected) return
    if (decision === 'assign' && !assignee) {
      message.warning('请先选择指派对象')
      return
    }
    if (!['pending_review', 'identified'].includes(selected.status)) {
      message.warning(`当前差异状态为「${selected.status}」，不可复核处置，正在刷新…`)
      await load()
      return
    }
    setLoading(true)
    try {
      await reviewDifference(selected.id, decision, comment || undefined, decision === 'assign' ? assignee : undefined)
      message.success('操作成功')
      setSelected(null)
      setComment('')
      await load()
    } catch (e: unknown) {
      message.error(formatApiError(e, '操作失败'))
      await load()
    } finally {
      setLoading(false)
    }
  }

  const refreshSelectedDiff = useCallback(async () => {
    if (!selected || !id) return
    try {
      const list = await getDifferences(id)
      setDiffs(list)
      const fresh = list.find((d) => d.id === selected.id)
      if (fresh) setSelected(fresh)
    } catch {
      await load()
    }
  }, [selected, id, load])

  const handleApproveReview = async () => {
    if (!id) return
    setLoading(true)
    try {
      const result = await approveTaskReview(id)
      message.success('复核审批通过，Workflow 已进入再次验证')
      if (result.verify_result) {
        message.info(`验证完成：${JSON.stringify(result.verify_result)}`)
      }
      await load()
    } catch (e: unknown) {
      message.error(formatApiError(e, '审批失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleVerify = async () => {
    if (!id) return
    setLoading(true)
    try {
      await verifyTask(id)
      message.success('再次验证完成')
      await load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '验证失败')
    } finally {
      setLoading(false)
    }
  }

  const handleReport = async () => {
    if (!id) return
    setReporting(true)
    try {
      await generateReport(id, !!(task.summary?.report_path))
      message.success('报告已生成')
      await load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      message.error(err.response?.data?.detail || '生成失败')
    } finally {
      setReporting(false)
    }
  }

  const handleClose = () => {
    if (!id) return
    Modal.confirm({
      title: '关闭任务',
      content: '关闭后任务不可再修改或复核',
      onOk: async () => {
        await closeTask(id)
        message.success('任务已关闭')
        await load()
      },
    })
  }

  const handleArchive = async (diff: Difference) => {
    Modal.confirm({
      title: '沉淀为案例',
      content: '将保存差异处理经验至案例库',
      onOk: async () => {
        await archiveCase(diff.id, {
          reusable_rule_suggestion: '建议加强同类差异规则校验',
          root_cause: diff.ai_explanation,
          handling_result: diff.review_comment,
        })
        message.success('已沉淀至案例库')
      },
    })
  }

  const downloadReport = async () => {
    if (!task) return
    const token = localStorage.getItem('token')
    try {
      const resp = await fetch(getReportUrl(task.id), { headers: { Authorization: `Bearer ${token}` } })
      if (!resp.ok) {
        const errText = await resp.text()
        let detail = errText
        try {
          detail = JSON.parse(errText).detail || errText
        } catch { /* plain text */ }
        message.error(detail || `下载失败 (${resp.status})`)
        return
      }
      const blob = await resp.blob()
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `对账报告_${task.name}.pdf`
      a.click()
      URL.revokeObjectURL(a.href)
      message.success('报告已开始下载')
    } catch (e) {
      message.error(formatApiError(e, '下载报告失败，请确认后端已启动且端口与前端代理一致'))
    }
  }

  if (!task) return null

  const isClosed = task.status === 'closed'
  const pendingReview = diffs.filter((d) => ['pending_review', 'identified'].includes(d.status))
  const reviewProgress = (task.summary?.review_progress as {
    pending_review?: number
    ready_for_approval?: boolean
    total?: number
  } | undefined)
  const canApproveReview = !isClosed
    && ['pending_review', 'processing'].includes(task.status)
    && (me.role === 'admin' || me.role === 'manager')
    && !!reviewProgress?.ready_for_approval
  const myAssigned = diffs.filter((d) => d.assignee_id === me.id && ['assigned', 'processing', 'returned'].includes(d.status))

  const diffColumns = [
    { title: '类型', dataIndex: 'type', render: (t: string) => <Tag color={DIFF_TYPE_COLOR[t] || 'default'}>{t}</Tag> },
    { title: '业务键', dataIndex: 'business_key' },
    { title: '业务侧', dataIndex: 'business_amount', render: (v?: number) => v?.toLocaleString() },
    { title: '财务侧', dataIndex: 'finance_amount', render: (v?: number) => v?.toLocaleString() },
    { title: '差异金额', dataIndex: 'amount_diff', render: (v: number) => v?.toLocaleString() },
    { title: '风险', dataIndex: 'risk_level' },
    { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={STATUS_COLOR[s]}>{s}</Tag> },
    {
      title: '操作',
      render: (_: unknown, r: Difference) => (
        <Space>
          <Button type="link" onClick={() => { setSelected(r); setComment('') }}>详情</Button>
          {isClosed && r.status === 'confirmed' && (
            <Button type="link" onClick={() => handleArchive(r)}>沉淀案例</Button>
          )}
        </Space>
      ),
    },
  ]

  const byType: Record<string, number> = {}
  diffs.forEach((d) => { byType[d.type] = (byType[d.type] || 0) + 1 })
  const totalAmount = diffs.reduce((s, d) => s + (d.amount_diff || 0), 0)

  const pendingReviewHint =
    task?.status === 'pending_review' && !canApproveReview && pendingReview.length > 0
      ? {
          title: `${pendingReview.length} 条差异待复核`,
          desc: '请在「待复核」或「差异清单」中对每条差异确认/退回/指派；全部处置完成后，系统将通知上级审批。',
        }
      : null

  const drawerExtra = !isClosed && selected && ['pending_review', 'identified'].includes(selected.status) && (
    <Space wrap>
      <Button icon={<CloseOutlined />} danger loading={loading} onClick={() => handleReview('reject')}>退回</Button>
      <Select placeholder="指派给" style={{ width: 120 }} value={assignee} onChange={setAssignee}
        options={users.filter((u) => u.role === 'ops').map((u) => ({ value: u.id, label: u.display_name }))} />
      <Button icon={<UserAddOutlined />} loading={loading} disabled={!assignee} onClick={() => handleReview('assign')}>指派</Button>
    </Space>
  )

  const tabs: { key: string; label: React.ReactNode; children: React.ReactNode }[] = []

  if (showModule(PAGE_MODULE_KEYS.todaySummary)) {
    tabs.push({
      key: 'overview',
      label: '概览',
      children: (
        <>
          <ReconciliationSystemSummary
            businessRows={(task.summary?.business_rows as number) ?? undefined}
            financeRows={(task.summary?.finance_rows as number) ?? undefined}
            diffCount={diffs.length}
            matchedEstimate={(task.summary?.matched_count as number) ?? undefined}
            extraMetrics={[
              { label: '影响金额', value: totalAmount.toLocaleString(), tone: 'accent' },
              ...Object.entries(byType).map(([t, c]) => ({
                label: t,
                value: c,
              })),
            ]}
          />
        </>
      ),
    })
  }

  if (showModule('difference_handling')) {
    tabs.push({
      key: 'diffs',
      label: `差异清单 (${diffs.length})`,
      children: <Table dataSource={diffs} rowKey="id" columns={diffColumns} pagination={{ pageSize: 8 }} />,
    })
  }
  if (showModule('pending_review')) {
    tabs.push({
      key: 'review',
      label: `待复核 (${pendingReview.length})`,
      children: pendingReview.length
        ? <Table dataSource={pendingReview} rowKey="id" columns={diffColumns} pagination={false} />
        : <Card><Typography.Text type="secondary">没有待复核差异</Typography.Text></Card>,
    })
  }
  if (showModule('processing_progress')) {
    tabs.push({
      key: 'processing',
      label: '处理进度',
      children: (
        <>
          {myAssigned.length > 0 && !isClosed && (
            <Card title="分派给我的处理事项" style={{ marginBottom: 16 }}>
              {myAssigned.map((d) => (
                <div key={d.id} style={{ marginBottom: 12 }}>
                  <Tag color={DIFF_TYPE_COLOR[d.type] || 'default'}>{d.type}</Tag> {d.business_key}
                  <Input.TextArea rows={2} placeholder="处理说明 / 反馈" value={processText} onChange={(e) => setProcessText(e.target.value)} style={{ marginTop: 8 }} />
                  <Button type="primary" style={{ marginTop: 8 }} onClick={async () => {
                    try {
                      await submitProcessing(d.id, processText)
                      message.success('已提交处理反馈')
                      setProcessText('')
                      load()
                    } catch (e: unknown) {
                      const err = e as { response?: { data?: { detail?: string } } }
                      message.error(err.response?.data?.detail || '提交失败')
                    }
                  }}>提交处理结果</Button>
                </div>
              ))}
            </Card>
          )}
          <Table dataSource={diffs.filter((d) => ['assigned', 'processing', 'pending_verification', 'resolved', 'returned'].includes(d.status))}
            rowKey="id" columns={diffColumns} pagination={false} />
        </>
      ),
    })
  }
  if (showModule('re_verification')) {
    tabs.push({
      key: 'verify',
      label: '再次验证',
      children: (
        <Card>
          <Alert type="info" showIcon style={{ marginBottom: 12 }}
            message="本步骤将基于处理后数据重新执行确定性规则，不由 AI 直接判断是否关闭。" />
          <Typography.Paragraph>将重跑规则版本：<Tag color="purple">{task.rule_version_id?.slice(0, 8)}</Tag></Typography.Paragraph>
          <Button type="primary" loading={loading} disabled={task.status !== 'pending_verification'} onClick={handleVerify}>
            执行再次验证
          </Button>
          {task.status !== 'pending_verification' && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              仅「待验证」状态可执行（需先完成复核与责任处理）。
            </Typography.Paragraph>
          )}
        </Card>
      ),
    })
  }
  if (showModule('reconciliation_report')) {
    const hasReport = !!(task.summary?.report_path)
    const canGenerate = task.status === 'reporting' && !isClosed
    const reportBlockedReason = task.status !== 'reporting'
      ? '任务需进入「报告输出」状态（完成再次验证后）才能生成 PDF。'
      : null
    tabs.push({
      key: 'report',
      label: '报告输出',
      children: (
        <Card>
          {hasReport ? (
            <Alert type="success" showIcon style={{ marginBottom: 12 }}
              message="PDF 报告已生成"
              description="请点击「下载报告」获取文件。生成按钮在已有报告时会禁用；如需重新生成可先删除后重试，或联系管理员。"
            />
          ) : reportBlockedReason ? (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={reportBlockedReason} />
          ) : (
            <Alert type="info" showIcon style={{ marginBottom: 12 }}
              message="全部差异已处理并验证通过后，可生成最终 PDF 报告。"
              description="若仍有待复核/待验证差异，系统将拒绝生成报告。"
            />
          )}
          <Space wrap>
            <Button
              type="primary"
              loading={reporting}
              disabled={!canGenerate}
              onClick={handleReport}
            >
              {hasReport ? '重新生成 PDF' : '生成 PDF 报告'}
            </Button>
            <Button type="primary" ghost icon={<DownloadOutlined />} disabled={!hasReport} onClick={downloadReport}>
              下载报告
            </Button>
            <Button danger disabled={task.status !== 'reporting' || !hasReport} onClick={handleClose}>关闭任务</Button>
          </Space>
          {task.status === 'reporting' && !hasReport && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
              进入本页后将自动尝试生成报告；若失败请手动点击「生成 PDF 报告」。
            </Typography.Paragraph>
          )}
          {isClosed && <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>任务已关闭，只读。</Typography.Paragraph>}
        </Card>
      ),
    })
  }
  if (showModule('audit_trace')) {
    tabs.push({
      key: 'audit',
      label: <span><AuditOutlined /> 审计追溯</span>,
      children: (
        <AuditTracePanel
          invocations={invocations}
          runs={runs}
          logs={logs}
          showSkills={showAuditSection(PAGE_MODULE_KEYS.auditTraceSkills)}
          showWorkflow={showAuditSection(PAGE_MODULE_KEYS.auditTraceWorkflow)}
          showLogs={showAuditSection(PAGE_MODULE_KEYS.auditTraceLogs)}
        />
      ),
    })
  }

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 12 }} align="start">
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>{task.name}</Typography.Title>
          <Typography.Text type="secondary">周期 {task.period} · 编号 {task.id.slice(0, 8)} · 发起人 {task.creator_id.slice(0, 8)}</Typography.Text>
          <div style={{ marginTop: 8 }}>
            <Space>
              {pendingReviewHint ? (
                <Tooltip
                  placement="bottomLeft"
                  title={(
                    <div style={{ maxWidth: 320 }}>
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>{pendingReviewHint.title}</div>
                      <div>{pendingReviewHint.desc}</div>
                    </div>
                  )}
                >
                  <Tag
                    color="gold"
                    style={{ cursor: 'help', borderStyle: 'dashed' }}
                  >
                    {TASK_STATUS[task.status]} · {pendingReview.length}
                  </Tag>
                </Tooltip>
              ) : (
                <Tag color={task.status === 'closed' ? 'default' : task.status === 'failed' ? 'red' : 'processing'}>
                  {TASK_STATUS[task.status]}
                </Tag>
              )}
              <VersionBadges bcVersion={center?.version} workflowVersion={task.workflow_version} ruleVersion={task.rule_version_id} aiMode={aiMode} />
            </Space>
          </div>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => { load(); refreshCenterConfig() }}>刷新</Button>
      </Space>

      {task.error_message && (
        <Alert
          type="error"
          message={task.error_message}
          style={{ marginBottom: 16 }}
          action={
            task.status === 'failed' ? (
              <Button type="primary" size="small" loading={resuming} onClick={handleResumeExecution}>
                重新执行
              </Button>
            ) : undefined
          }
        />
      )}

      {canApproveReview && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message="复核已完成，等待上级/管理员审批"
          description={`共 ${reviewProgress?.total ?? diffs.length} 条差异已处置完毕。审批通过后将自动进入「再次验证」节点。`}
          action={
            <Button type="primary" loading={loading} onClick={handleApproveReview}>
              审批通过并继续 Workflow
            </Button>
          }
        />
      )}

      <TaskExecutionPanel
        status={task.status}
        progress={task.progress}
        summary={task.summary}
        runs={runs}
        invocations={invocations}
        live={task.status === 'running' || reporting}
        diffCount={diffs.length}
        onGenerateReport={handleReport}
        showReportAction={showModule('reconciliation_report')}
        reportGenerating={reporting}
        onDownloadReport={downloadReport}
        hasReport={!!task.summary?.report_path}
      />

      {tabs.length === 0 ? (
        <Alert type="info" showIcon message="后台未启用任何任务详情模块" description="请在管理后台「页面模块」中勾选模块并点击「发布生效」。" />
      ) : (
        <Tabs items={tabs} defaultActiveKey={tabs[0]?.key} />
      )}

      <Drawer title="差异详情" width={680} open={!!selected} onClose={() => setSelected(null)} extra={drawerExtra}>
        {selected && (
          <>
            <Typography.Title level={5} className="diff-drawer-section-title">一、差异事实摘要</Typography.Title>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="差异类型">{selected.type}</Descriptions.Item>
              <Descriptions.Item label="业务键">{selected.business_key}</Descriptions.Item>
              <Descriptions.Item label="业务侧金额">{selected.business_amount?.toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="财务侧金额">{selected.finance_amount?.toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="差异金额">{selected.amount_diff?.toLocaleString()}</Descriptions.Item>
              <Descriptions.Item label="当前状态"><Tag color={STATUS_COLOR[selected.status]}>{selected.status}</Tag></Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5} className="diff-drawer-section-title">二、原始数据对照</Typography.Title>
            <pre className="diff-drawer-json">{JSON.stringify({ business: selected.sap_record, finance: selected.dms_record }, null, 2)}</pre>

            <Typography.Title level={5} className="diff-drawer-section-title">三、规则与证据</Typography.Title>
            <DiffRuleEvidenceSection diff={selected} />

            <Typography.Title level={5} className="diff-drawer-section-title">四、系统判定 vs AI 分析</Typography.Title>
            <SystemVsAiBlock
              systemLines={[
                `类型 ${selected.type}`,
                `差异金额 ${selected.amount_diff?.toLocaleString() ?? '—'}`,
                ...((selected.rule_hits || []) as Array<{ message?: string }>).slice(0, 2).map((h) => h.message || ''),
              ].filter(Boolean) as string[]}
              aiText={selected.ai_explanation}
              confidence={selected.confidence}
            />
            {((selected.ai_recommendation as { evidence?: string[] })?.evidence?.length
              || (selected.evidence as { items?: string[] })?.items?.length) && (
              <>
                <Typography.Title level={5} className="diff-drawer-section-title" style={{ marginTop: 12 }}>依据来源</Typography.Title>
                <EvidenceSourceList
                  items={(
                    (selected.ai_recommendation as { evidence?: string[] })?.evidence
                    || (selected.evidence as { items?: string[] })?.items
                    || []
                  ).slice(0, 8).map((line) => ({ label: String(line) }))}
                />
              </>
            )}
            <Typography.Title level={5} className="diff-drawer-section-title" style={{ marginTop: 16 }}>
              规则解释与建议{' '}
              <AiModeBadge mode={(selected.ai_recommendation as { model?: string })?.model || aiMode} />
            </Typography.Title>
            <Space style={{ marginBottom: 8 }} wrap align="start">
              <Button
                size="small"
                icon={<SafetyCertificateOutlined />}
                loading={reExplaining}
                onClick={() => handleReExplain(false)}
              >
                重新生成规则解释
              </Button>
              <Tooltip
                title={
                  llmStatus?.runtime_ready
                    ? `将调用已配置模型：${llmStatus.model}`
                    : (llmStatus?.hint || '请先在管理后台配置大模型')
                }
              >
                <Button
                  size="small"
                  icon={<RobotOutlined />}
                  loading={reExplaining}
                  disabled={!llmStatus?.runtime_ready}
                  onClick={() => handleReExplain(true)}
                >
                  用大模型补充
                </Button>
              </Tooltip>
            </Space>
            {llmStatus && !llmStatus.runtime_ready && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 8 }}
                message="大模型未启用"
                description={
                  <>
                    {llmStatus.hint}
                    {canOpenAdmin && (
                      <>
                        {' '}
                        <Button type="link" size="small" style={{ padding: 0, height: 'auto' }}
                          onClick={() => navigate('/admin?tab=llm')}>
                          前往大模型配置
                        </Button>
                      </>
                    )}
                  </>
                }
              />
            )}
            <DiffExplanationProse
              explanation={selected.ai_explanation}
              suggestion={selected.suggestion}
            />

            <Typography.Title level={5} className="diff-drawer-section-title">五、您的操作（确认 / 质疑 / 修正）</Typography.Title>
            {!isClosed && selected.status === 'pending_review' && (
              <>
                <DiffTrustActions
                  diffId={selected.id}
                  confidence={selected.confidence}
                  onConfirm={async () => handleReview('confirm')}
                  onDone={refreshSelectedDiff}
                  disabled={loading}
                />
                <Input.TextArea rows={2} placeholder="复核意见（选填）" value={comment} onChange={(e) => setComment(e.target.value)} style={{ marginTop: 12 }} />
              </>
            )}
            {(!isClosed && selected.status !== 'pending_review') && (
              <Typography.Text type="secondary">当前状态不可复核处置（仅“待复核”可确认/质疑/修正）。</Typography.Text>
            )}
            <Button type="primary" icon={<MessageOutlined />} block style={{ marginTop: 16 }}
              onClick={() => navigate(`/chat?task_id=${task.id}&difference_id=${selected.id}`)}>
              继续追问（带上下文进入对话）
            </Button>
          </>
        )}
      </Drawer>
    </div>
  )
}

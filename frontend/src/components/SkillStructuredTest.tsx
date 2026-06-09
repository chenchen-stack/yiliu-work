import { useEffect, useState } from 'react'
import { Button, Collapse, Input, Space, Spin, Tag, Typography, message } from 'antd'
import { PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  executeSkillPackage,
  testSkillPackage,
  type SkillExecuteResult,
  type SkillPackageDetail,
  type SkillTestResult,
} from '../api/client'
import { formatApiError } from '../api/errors'

type Props = {
  skillCode: string
  pkg: SkillPackageDetail
}

export function SkillStructuredTest({ skillCode, pkg }: Props) {
  const [inputJson, setInputJson] = useState('{}')
  const [configJson, setConfigJson] = useState('{}')
  const [taskId, setTaskId] = useState('')
  const [executing, setExecuting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [execResult, setExecResult] = useState<SkillExecuteResult | null>(null)
  const [testResults, setTestResults] = useState<SkillTestResult[]>([])

  const canRun = Boolean(pkg.has_executor || pkg.platform_executable)

  useEffect(() => {
    const sample = pkg.sample_input && Object.keys(pkg.sample_input).length > 0
      ? pkg.sample_input
      : (pkg.tests?.[0]?.input || {})
    setInputJson(JSON.stringify(sample, null, 2))
    setConfigJson('{}')
    setExecResult(null)
    setTestResults([])
  }, [skillCode, pkg])

  const parseJson = (raw: string, label: string) => {
    try {
      return JSON.parse(raw || '{}') as Record<string, unknown>
    } catch {
      throw new Error(`${label} 不是合法 JSON`)
    }
  }

  const handleExecute = async () => {
    setExecuting(true)
    setExecResult(null)
    try {
      const input_data = parseJson(inputJson, '输入')
      const config = parseJson(configJson, '配置')
      const res = await executeSkillPackage(
        skillCode,
        input_data,
        config,
        taskId.trim() || undefined,
      )
      setExecResult(res)
      if (res.success) message.success(`执行成功（${res.duration_ms} ms）`)
      else message.warning(res.error || '执行返回失败')
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setExecuting(false)
    }
  }

  const handleRunTests = async () => {
    setTesting(true)
    setTestResults([])
    try {
      const res = await testSkillPackage(skillCode)
      setTestResults(res)
      const passed = res.filter((r) => r.passed).length
      message.success(`用例完成：${passed}/${res.length} 通过`)
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setTesting(false)
    }
  }

  if (!canRun) {
    return (
      <div className="skill-test-empty">
        <ThunderboltOutlined />
        <Typography.Text type="secondary">
          此 Skill 未注册 execute.py 或平台执行器，请使用「对话测试」由 Agent 编排调用。
        </Typography.Text>
      </div>
    )
  }

  return (
    <div className="skill-test-layout">
      <div className="skill-test-card skill-test-card--exec">
        <div className="skill-test-card__head">
          <span className="skill-test-card__title">单次执行（JSON）</span>
          <span className="skill-test-card__hint">直连后端 POST /skill-packages/{skillCode}/execute</span>
        </div>
        <div className="skill-test-action-bar">
          <label className="skill-test-action-bar__task">
            <span className="skill-test-label skill-test-label--inline">任务 ID（可选）</span>
            <Input
              className="skill-test-task-input"
              placeholder="绑定对账任务后走真实数据"
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              allowClear
            />
          </label>
          <Button
            type="primary"
            className="skill-test-action-bar__run catalog-upload-btn"
            icon={<PlayCircleOutlined />}
            loading={executing}
            onClick={() => { void handleExecute() }}
          >
            执行 Skill
          </Button>
        </div>
        <div className="skill-test-split">
          <div className="skill-test-split__col">
            <div className="skill-test-label">input_data</div>
            <Input.TextArea
              className="skill-test-editor"
              rows={10}
              value={inputJson}
              onChange={(e) => setInputJson(e.target.value)}
            />
          </div>
          <div className="skill-test-split__col">
            <div className="skill-test-label">config（可选）</div>
            <Input.TextArea
              className="skill-test-editor skill-test-editor--sm"
              rows={10}
              value={configJson}
              onChange={(e) => setConfigJson(e.target.value)}
            />
          </div>
        </div>
        {executing && (
          <div className="skill-test-result-placeholder"><Spin size="small" /> 执行中…</div>
        )}
        {execResult && !executing && (
          <div className="skill-test-result-pane skill-pkg-exec-result">
            <Space size={8} style={{ marginBottom: 8 }}>
              <Tag color={execResult.success ? 'success' : 'error'}>
                {execResult.success ? '成功' : '失败'}
              </Tag>
              <Typography.Text type="secondary">{execResult.duration_ms} ms</Typography.Text>
            </Space>
            {execResult.error && (
              <Typography.Paragraph type="danger" style={{ fontSize: 12 }}>
                {execResult.error}
              </Typography.Paragraph>
            )}
            <pre className="skill-pkg-exec-result__output">
              {JSON.stringify(execResult.output, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {pkg.tests && pkg.tests.length > 0 && (
        <div className="skill-test-card">
          <div className="skill-test-card__head">
            <span className="skill-test-card__title">skill.yaml 内置用例</span>
            <span className="skill-test-card__hint">{pkg.tests.length} 条 · POST /skill-packages/{skillCode}/test</span>
          </div>
          <Button
            type="default"
            icon={<ThunderboltOutlined />}
            loading={testing}
            onClick={() => { void handleRunTests() }}
          >
            跑全部用例
          </Button>
          {testing && <div className="skill-test-result-placeholder"><Spin size="small" /></div>}
          {testResults.length > 0 && !testing && (
            <Collapse
              className="skill-test-config-collapse"
              style={{ marginTop: 12 }}
              items={testResults.map((r) => ({
                key: r.name,
                label: (
                  <Space>
                    <Tag color={r.passed ? 'success' : 'error'}>{r.passed ? '通过' : '失败'}</Tag>
                    <span>{r.name}</span>
                    <Typography.Text type="secondary">{r.duration_ms} ms</Typography.Text>
                  </Space>
                ),
                children: (
                  <div className="skill-test-tool-json">
                    {r.error && <Typography.Text type="danger">{r.error}</Typography.Text>}
                    <pre>{JSON.stringify({ expected: r.expected, actual: r.actual }, null, 2)}</pre>
                  </div>
                ),
              }))}
            />
          )}
        </div>
      )}
    </div>
  )
}

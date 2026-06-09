import { useEffect, useState } from 'react'
import {
  Card, Form, Input, Upload, Button, Typography, message, Select, Space, Tag,
  Tooltip, Dropdown, Alert,
} from 'antd'
import {
  InboxOutlined, QuestionCircleOutlined, PlayCircleOutlined,
} from '@ant-design/icons'
import { DatasourceBrandIcon } from '../utils/datasourceBranding'
import { Link, useNavigate } from 'react-router-dom'
import {
  createTask, getDemoDatasets, getPublishedCenters, getAdminRules,
  getReconciliationLaunchOptions, DemoDataset, ReconciliationLaunchOptions,
} from '../api/client'
import { formatApiError } from '../api/errors'
import { REVENUE_CENTER_CODE } from '../utils/pageModules'

type SourceMode = 'datasource' | 'demo' | 'upload' | 'combined'

const CREATE_HELP = (
  <>
    核对数据须先在管理后台「流程编排 → 字段映射」选定业务/财务表并保存映射；
    前台仅能使用已绑定且通过列校验的表对，字段映射自动生效，无需再次上传。
    方太 POC 真实数据 / 临时上传可用于快速体验。
  </>
)

export default function TaskCreate() {
  const [loading, setLoading] = useState(false)
  const [datasets, setDatasets] = useState<DemoDataset[]>([])
  const [launch, setLaunch] = useState<ReconciliationLaunchOptions | null>(null)
  const [launchLoading, setLaunchLoading] = useState(true)
  const [sourceMode, setSourceMode] = useState<SourceMode>('datasource')
  const [sap, setSap] = useState<File | null>(null)
  const [dms, setDms] = useState<File | null>(null)
  const [fanruan, setFanruan] = useState<File | null>(null)
  const [combinedFile, setCombinedFile] = useState<File | null>(null)
  const [bizDsId, setBizDsId] = useState<string>()
  const [finDsId, setFinDsId] = useState<string>()
  const [demoDatasetId, setDemoDatasetId] = useState('dataset_fangtai_real')
  const [ruleVersion, setRuleVersion] = useState('')
  const [ruleSummary, setRuleSummary] = useState('')
  const navigate = useNavigate()

  const boundPair = launch?.datasource_pairs?.[0]
  const mappingReady = Boolean(launch?.mapping_ready && boundPair)

  useEffect(() => {
    getDemoDatasets().then(setDatasets).catch(console.error)
    getPublishedCenters().then(async (c) => {
      const rv = c[0]?.rule_version_id
      if (!rv) return
      setRuleVersion(rv.slice(0, 8) + '…')
      try {
        const rules = await getAdminRules({ rule_version_id: rv })
        const enabled = rules.filter((r) => r.enabled)
        if (enabled.length) {
          setRuleSummary(enabled.map((r) => r.name).join(' · '))
        }
      } catch {
        setRuleSummary('')
      }
    }).catch(console.error)

    setLaunchLoading(true)
    getReconciliationLaunchOptions(REVENUE_CENTER_CODE)
      .then((opts) => {
        setLaunch(opts)
        const pair = opts.datasource_pairs[0]
        if (opts.mapping_ready && pair) {
          setSourceMode('datasource')
          setBizDsId(pair.business_datasource_id)
          setFinDsId(pair.finance_datasource_id)
        } else {
          setSourceMode('demo')
        }
      })
      .catch(() => {
        setLaunch(null)
        setSourceMode('demo')
      })
      .finally(() => setLaunchLoading(false))
  }, [])

  const onFinish = async (values: { name: string; period: string }) => {
    if (sourceMode === 'datasource') {
      if (!mappingReady || !bizDsId || !finDsId) {
        return message.warning(launch?.hint || '请先在管理后台完成字段映射配置')
      }
      if (
        boundPair
        && (bizDsId !== boundPair.business_datasource_id || finDsId !== boundPair.finance_datasource_id)
      ) {
        return message.warning('仅可使用管理后台已绑定的数据源对')
      }
    }
    if (sourceMode === 'upload' && (!sap || !dms)) {
      return message.warning('请上传业务侧与财务侧文件')
    }
    if (sourceMode === 'combined' && !combinedFile) {
      return message.warning('请上传综合数据文件（含多个 Sheet 的 Excel）')
    }
    setLoading(true)
    try {
      const task = await createTask({
        name: values.name,
        period: values.period,
        demo_dataset_id: sourceMode === 'demo' ? demoDatasetId : undefined,
        business_datasource_id: sourceMode === 'datasource' ? bizDsId : undefined,
        finance_datasource_id: sourceMode === 'datasource' ? finDsId : undefined,
        sap: sourceMode === 'upload' && sap ? sap : undefined,
        dms: sourceMode === 'upload' && dms ? dms : undefined,
        fanruan: sourceMode === 'upload' && fanruan ? fanruan : undefined,
        combined: sourceMode === 'combined' && combinedFile ? combinedFile : undefined,
      })
      message.success('任务已创建，正在执行核对…')
      navigate(`/workbench/reconciliation/tasks/${task.id}`)
    } catch (e: unknown) {
      message.error(formatApiError(e, '创建失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="task-create-page">
      <Space align="center" style={{ marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>新建核对任务</Typography.Title>
        <Tooltip title={CREATE_HELP} placement="bottomLeft">
          <QuestionCircleOutlined style={{ color: '#94a3b8', cursor: 'help' }} />
        </Tooltip>
      </Space>

      <Card className="task-create-card">
        <Form layout="vertical" onFinish={onFinish}
          initialValues={{ name: '2024年5月收入核对', period: '2024-05' }}>
          <Form.Item name="name" label="任务名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="period" label="核对周期" rules={[{ required: true }]}>
            <Input placeholder="如 2024-05" />
          </Form.Item>
          <Form.Item label="规则版本" extra={ruleSummary || '执行时将按业务中心当前规则版本跑差异识别'}>
            <Input value={ruleVersion || '发布后自动绑定'} disabled />
          </Form.Item>

          {sourceMode === 'datasource' && (
            <>
              {!launchLoading && !mappingReady && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="尚未完成字段映射绑定"
                  description={
                    <>
                      {launch?.hint || '请管理员在管理后台配置字段映射并保存。'}
                      {' '}
                      <Link to="/admin">前往管理后台</Link>
                    </>
                  }
                />
              )}
              {mappingReady && boundPair && (
                <Form.Item label="核对数据（后台已绑定）" required>
                  <div className="task-create-pair">
                    <DatasourceBrandIcon catalog="sap" size={22} showEngine={false} />
                    <Input
                      disabled
                      value={`${boundPair.business_name} · ${boundPair.business_row_count ?? '—'} 行`}
                    />
                    <span className="task-create-arrow">↔</span>
                    <DatasourceBrandIcon catalog="dms" size={22} showEngine={false} />
                    <Input
                      disabled
                      value={`${boundPair.finance_name} · ${boundPair.finance_row_count ?? '—'} 行`}
                    />
                  </div>
                  <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 6, display: 'block' }}>
                    与管理后台「字段映射」绑定的表对一致（{boundPair.mapping_row_count} 条映射），不可随意更换
                  </Typography.Text>
                </Form.Item>
              )}
              {mappingReady && boundPair && (
                <div className="task-create-tags">
                  <Tag color="orange" title={boundPair.business_name}>{boundPair.business_name}</Tag>
                  <span className="task-create-arrow">↔</span>
                  <Tag color="cyan" title={boundPair.finance_name}>{boundPair.finance_name}</Tag>
                </div>
              )}
            </>
          )}

          {sourceMode === 'demo' && (
            <Form.Item label="POC 数据集" required>
              <Select
                value={demoDatasetId}
                onChange={setDemoDatasetId}
                options={datasets.map((d) => ({ value: d.id, label: `${d.name} — ${d.description}` }))}
              />
            </Form.Item>
          )}

          {sourceMode === 'combined' && (
            <Form.Item label="综合数据文件" required extra="上传包含多个 Sheet 的 Excel 文件（如 SAP/DMS/帆软数据），系统自动识别并分配各数据角色">
              <Upload.Dragger beforeUpload={(f) => { setCombinedFile(f); return false }} maxCount={1} accept=".xlsx,.xls">
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p>拖拽或点击上传综合 Excel 文件</p>
                <p className="ant-upload-hint">支持包含 SAP收入总额、DMS收入台账、帆软对账平台等多 Sheet 的 Excel</p>
              </Upload.Dragger>
            </Form.Item>
          )}

          {sourceMode === 'upload' && (
            <>
              <Form.Item label="业务侧文件" required>
                <Upload.Dragger beforeUpload={(f) => { setSap(f); return false }} maxCount={1} accept=".csv,.xlsx">
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p>上传业务侧文件（一次性，不入库）</p>
                </Upload.Dragger>
              </Form.Item>
              <Form.Item label="财务侧文件" required>
                <Upload.Dragger beforeUpload={(f) => { setDms(f); return false }} maxCount={1} accept=".csv,.xlsx">
                  <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                  <p>上传财务侧文件（一次性，不入库）</p>
                </Upload.Dragger>
              </Form.Item>
            </>
          )}

          <div className="task-create-actions">
            {mappingReady && sourceMode !== 'datasource' && (
              <Button type="link" size="small" onClick={() => setSourceMode('datasource')}>
                改用后台已绑定数据源
              </Button>
            )}
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'datasource',
                    label: '后台已绑定数据源',
                    disabled: !mappingReady,
                  },
                  { key: 'combined', label: '综合 Excel（多 Sheet 自动识别）' },
                  { key: 'demo', label: 'POC 数据集' },
                  { key: 'upload', label: '临时上传文件（分别上传）' },
                ],
                onClick: ({ key }) => setSourceMode(key as SourceMode),
              }}
            >
              <Button type="text" size="small">其他数据来源</Button>
            </Dropdown>
            <Button type="primary" htmlType="submit" icon={<PlayCircleOutlined />}
              loading={loading}
              disabled={sourceMode === 'datasource' && (!mappingReady || launchLoading)}>
              发起执行
            </Button>
          </div>
        </Form>
      </Card>
    </div>
  )
}

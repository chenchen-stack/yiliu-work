import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from 'antd'
import { PlusOutlined, MessageOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import { createAgent, listAgents, updateAgent, type AgentConfigItem } from '../api/client'
import { formatApiError } from '../api/errors'

const { TextArea } = Input
const { Paragraph } = Typography

export default function AgentCenter() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentConfigItem[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setAgents(await listAgents())
    } catch (e) {
      message.error(formatApiError(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    const v = await form.validateFields()
    try {
      const created = await createAgent({
        ...v,
        scope: 'personal',
        allowed_skill_ids: v.allowed_skill_ids || ['skill-anomaly_explain', 'skill-query_tasks'],
      })
      message.success('个人 Agent 已创建')
      setModalOpen(false)
      load()
      navigate(`/chat?agent_id=${created.id}&_new=${Date.now()}`)
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  const handlePublish = async (row: AgentConfigItem) => {
    try {
      await updateAgent(row.id, { publish: true })
      message.success('已提交团队发布（当前环境即时生效）')
      load()
    } catch (e) {
      message.error(formatApiError(e))
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>智能体中心</Typography.Title>
          <Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            创建个人 Agent、选择团队模板，在对话中完成探索性分析与 Workflow 引导。
          </Paragraph>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setModalOpen(true) }}>
          创建个人 Agent
        </Button>
      </Space>

      <Card>
        <Table
          rowKey="id"
          loading={loading}
          dataSource={agents}
          columns={[
            { title: '名称', dataIndex: 'name' },
            {
              title: '范围',
              dataIndex: 'scope',
              width: 110,
              render: (s: string) => (
                <Tag color={s === 'personal' ? 'blue' : 'green'}>
                  {s === 'personal' ? '个人' : '团队'}
                </Tag>
              ),
            },
            { title: '描述', dataIndex: 'description', ellipsis: true },
            {
              title: '操作',
              width: 220,
              render: (_: unknown, row: AgentConfigItem) => (
                <Space>
                  <Link to={`/chat?agent_id=${row.id}&_new=${Date.now()}`}>
                    <Button size="small" icon={<MessageOutlined />}>对话</Button>
                  </Link>
                  {row.scope === 'personal' && (
                    <Button size="small" onClick={() => handlePublish(row)}>申请发布</Button>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Modal title="创建个人 Agent" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={handleCreate}>
        <Form form={form} layout="vertical" initialValues={{
          allowed_skill_ids: ['skill-anomaly_explain', 'skill-query_tasks'],
          output_format: 'natural',
        }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="如：方太收入分析助手" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input />
          </Form.Item>
          <Form.Item name="persona" label="人设" rules={[{ required: true }]}>
            <TextArea rows={3} placeholder="你是一个财资对账分析助手…" />
          </Form.Item>
          <Form.Item name="allowed_skill_ids" label="授权 Skill">
            <Select mode="multiple" options={[
              { value: 'skill-anomaly_explain', label: '异常解释' },
              { value: 'skill-query_tasks', label: '任务查询' },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

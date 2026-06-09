import { useEffect, useState } from 'react'
import {
  Drawer, Form, Input, InputNumber, Select, Switch, Typography, Tag, Divider, Button, Space, message,
} from 'antd'
import { AdminRuleConfig, updateAdminRule } from '../api/client'
import { formatApiError } from '../api/errors'

const RULE_TYPE_LABEL: Record<string, string> = {
  amount_mismatch: '金额差异',
  duplicate_record: '重复数据',
  mapping_anomaly: '映射异常',
}

const RULE_ENGINE_SPEC: Record<string, {
  match: string
  compare: string
  output: string
}> = {
  amount_mismatch: {
    match: 'order_id → 发票号 invoice_num（方太 SAP/DMS 单号不同，按发票对齐）',
    compare: '业务侧 sales_amount vs 财务侧 sales_amount（同发票多行时先汇总）',
    output: '差值 > 容差阈值时生成 amount_mismatch 差异项',
  },
  duplicate_record: {
    match: '业务侧 (order_id, invoice_num, customer_id) 组合键',
    compare: '同键出现 ≥ 2 条记录',
    output: '生成 duplicate_record，记录重复次数与去重后金额',
  },
  mapping_anomaly: {
    match: 'order_id 对齐的业务/财务行',
    compare: 'MDM 主数据一致性 + product_code 编码比对',
    output: '生成 mapping_anomaly，附带 mapping_hits 证据',
  },
}

const RESPONSIBLE_OPTIONS = [
  { value: 'finance', label: '财务侧' },
  { value: 'mdm_team', label: '主数据团队' },
  { value: 'sales', label: '销售侧' },
  { value: 'ops', label: '运营侧' },
]

type Props = {
  rule: AdminRuleConfig | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}

export function AdminRuleDrawer({ rule, open, onClose, onSaved }: Props) {
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!rule || !open) return
    const params = (rule.params || {}) as Record<string, unknown>
    form.setFieldsValue({
      name: rule.name,
      condition: rule.condition || '',
      severity: rule.severity,
      enabled: rule.enabled,
      threshold: rule.threshold ?? 0,
      confidence: typeof params.confidence === 'number' ? params.confidence : 0.9,
      responsible_party: (params.responsible_party as string) || 'finance',
    })
  }, [rule, open, form])

  const spec = rule ? RULE_ENGINE_SPEC[rule.rule_type] : null

  const handleSave = async () => {
    if (!rule) return
    const vals = await form.validateFields()
    setSaving(true)
    try {
      await updateAdminRule(rule.id, {
        name: vals.name,
        condition: vals.condition,
        severity: vals.severity,
        enabled: vals.enabled,
        threshold: rule.rule_type === 'amount_mismatch' ? Number(vals.threshold || 0) : rule.threshold,
        params: {
          confidence: Number(vals.confidence),
          responsible_party: vals.responsible_party,
        },
      })
      onSaved()
      onClose()
    } catch (e) {
      message.error(formatApiError(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title={rule ? `规则详情 · ${rule.name}` : '规则详情'}
      width={560}
      open={open}
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={handleSave}>保存</Button>
        </Space>
      }
    >
      {rule && (
        <Form form={form} layout="vertical" className="admin-rule-drawer">
          <div className="admin-rule-drawer-meta">
            <Tag>{RULE_TYPE_LABEL[rule.rule_type] || rule.rule_type}</Tag>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              ID {rule.id.slice(0, 8)} · 版本 {rule.version}
            </Typography.Text>
          </div>

          <Divider orientation="left" plain style={{ margin: '8px 0 16px', fontSize: 12, color: '#94a3b8' }}>
            规则说明
          </Divider>
          <Form.Item name="name" label="规则名称" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item
            name="condition"
            label="检测逻辑说明"
            extra="面向业务人员的可读描述，会写入差异证据与审计追溯"
            rules={[{ required: true, message: '请描述规则逻辑' }]}
          >
            <Input.TextArea rows={3} placeholder="描述何时触发、判定依据是什么" />
          </Form.Item>

          {spec && (
            <div className="admin-rule-engine-spec">
              <Typography.Text strong style={{ fontSize: 13 }}>引擎执行逻辑（只读）</Typography.Text>
              <dl>
                <div><dt>匹配键</dt><dd>{spec.match}</dd></div>
                <div><dt>比对字段</dt><dd>{spec.compare}</dd></div>
                <div><dt>输出</dt><dd>{spec.output}</dd></div>
              </dl>
            </div>
          )}

          {Boolean((rule.params as Record<string, unknown> | undefined)?.troubleshooting_steps) && (
            <>
              <Divider orientation="left" plain style={{ margin: '16px 0 12px', fontSize: 12, color: '#94a3b8' }}>
                方太排查要点（登记表）
              </Divider>
              <pre className="admin-rule-troubleshooting">
                {String((rule.params as Record<string, unknown>).troubleshooting_steps)}
              </pre>
            </>
          )}

          <Divider orientation="left" plain style={{ margin: '20px 0 16px', fontSize: 12, color: '#94a3b8' }}>
            运行参数
          </Divider>
          <Form.Item name="enabled" label="启停状态" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
          <Form.Item name="severity" label="严重程度">
            <Select options={[
              { value: 'high', label: '高' },
              { value: 'medium', label: '中' },
              { value: 'low', label: '低' },
            ]} />
          </Form.Item>
          {rule.rule_type === 'amount_mismatch' && (
            <Form.Item
              name="threshold"
              label="容差阈值（¥）"
              extra="差异金额 ≤ 阈值时不计为差异；0 表示严格相等（浮点容差 0.01）"
            >
              <InputNumber min={0} style={{ width: '100%' }} prefix="¥" />
            </Form.Item>
          )}
          <Form.Item name="confidence" label="置信度">
            <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="responsible_party" label="责任方">
            <Select options={RESPONSIBLE_OPTIONS} />
          </Form.Item>
        </Form>
      )}
    </Drawer>
  )
}

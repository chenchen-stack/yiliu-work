import { Row, Col, Card, Typography, Tag } from 'antd'
import { Link } from 'react-router-dom'
const SCENARIOS = [
  { name: '收入核对中心', desc: '业务/财务侧三类差异识别 · AI解释 · 人工复核 · 再次验证 · 报告输出', active: true, path: '/workbench/reconciliation' },
  { name: '采购付款风控中心', desc: '供应商风险识别 · 合规检查 · 异常预警', active: false, path: '' },
  { name: '财资经营分析中心', desc: '经营指标分析 · 趋势洞察 · 决策支持', active: false, path: '' },
  { name: '现金流预测中心', desc: '资金流入流出预测 · 缺口预警', active: false, path: '' },
  { name: '付款排程中心', desc: '付款优先级排序 · 资金安排建议', active: false, path: '' },
  { name: '资金计划中心', desc: '年度/月度资金计划编制与跟踪', active: false, path: '' },
]

export default function ScenariosHub() {
  return (
    <div>
      <Typography.Title level={4}>场景中心</Typography.Title>
      <Typography.Paragraph type="secondary">以可复用能力底座支撑专业财资场景 · 当前仅「收入核对中心」已验证真实运行，其余为规划中</Typography.Paragraph>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {SCENARIOS.map((s) => (
          <Col xs={24} sm={12} lg={8} key={s.name}>
            {s.active ? (
              <Link to={s.path}>
                <div className="scenario-card active">
                  <Typography.Title level={5}>{s.name} <Tag color="success">已开放</Tag></Typography.Title>
                  <Typography.Text type="secondary">{s.desc}</Typography.Text>
                </div>
              </Link>
            ) : (
              <div className="scenario-card disabled" style={{ cursor: 'not-allowed', opacity: 0.75 }}>
                <Typography.Title level={5}>{s.name} <Tag>规划中 · 未开放</Tag></Typography.Title>
                <Typography.Text type="secondary">{s.desc}</Typography.Text>
              </div>
            )}
          </Col>
        ))}
      </Row>
      <Card title="场景与中台能力映射" style={{ marginTop: 24 }}>
        <Row gutter={16}>
          <Col span={6}><strong>交互入口</strong><br /><Typography.Text type="secondary">对话 + 工作台</Typography.Text></Col>
          <Col span={6}><strong>能力执行</strong><br /><Typography.Text type="secondary">Agent + Workflow + Skill</Typography.Text></Col>
          <Col span={6}><strong>本体翻译</strong><br /><Typography.Text type="secondary">规则 + MDM + AI归因</Typography.Text></Col>
          <Col span={6}><strong>数据接入</strong><br /><Typography.Text type="secondary">Excel/API/ETL</Typography.Text></Col>
        </Row>
      </Card>
    </div>
  )
}

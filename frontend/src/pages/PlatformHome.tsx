import { Row, Col, Button, Typography, Tag, Space } from 'antd'
import { Link } from 'react-router-dom'
import { MessageOutlined, DesktopOutlined, AppstoreOutlined } from '@ant-design/icons'
import { LayerBlock, GovTags } from '../components/PlatformParts'

export default function PlatformHome() {
  return (
    <div>
      <div className="platform-header" style={{ borderRadius: 8, marginBottom: 16 }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          亿流 Work · 企业财资 Agent 中台
        </Typography.Title>
        <p>一套中台内核 · 支撑多财资场景 · Workflow 控流程 · Agent 做编排 · Skill 封装能力 · AI 给建议 · 人工做复核</p>
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={16}>
          <LayerBlock level="l1" title="第一层 · 交互入口层">
            <Row gutter={12}>
              <Col span={12}>
                <strong>A. 业务前台</strong>
                <div>· 对话模式：Agent 对话中心 + Skill 能力调用</div>
                <div>· 工作台模式：收入对账中心（总览/任务/异常/报告）</div>
                <div style={{ marginTop: 8 }}>
                  <Link to="/chat"><Button size="small" icon={<MessageOutlined />}>进入对话模式</Button></Link>
                  {' '}
                  <Link to="/workbench/reconciliation"><Button size="small" type="primary" icon={<DesktopOutlined />}>进入工作台</Button></Link>
                </div>
              </Col>
              <Col span={12}>
                <strong>B. 管理后台</strong>
                <div>业务中心 · Agent · Skill/Tool · Workflow · 数据源 · 本体/映射 · 模型/知识</div>
                <Link to="/admin"><Button size="small" style={{ marginTop: 8 }}>管理后台</Button></Link>
              </Col>
            </Row>
          </LayerBlock>

          <LayerBlock level="scenario" title="已发布财资业务中心">
            <Row gutter={[8, 8]}>
              {['收入核对中心', '采购付款风控中心', '财资经营分析中心', '现金流预测中心', '付款排程中心', '资金计划中心'].map((s, i) => (
                <Col key={s} span={8}>
                  <Link to={i === 0 ? '/workbench/reconciliation' : '/scenarios'}>
                    <div style={{
                      padding: '8px 12px', background: i === 0 ? '#fff7ed' : '#f8fafc',
                      border: `1px solid ${i === 0 ? '#f97316' : '#e2e8f0'}`, borderRadius: 6, textAlign: 'center', fontSize: 12,
                    }}>
                      {s}<br />{i === 0 ? <Tag color="success" style={{ marginInlineEnd: 0 }}>已开放</Tag> : <Tag style={{ marginInlineEnd: 0 }}>规划中</Tag>}
                    </div>
                  </Link>
                </Col>
              ))}
            </Row>
          </LayerBlock>

          <LayerBlock level="l2" title="第二层 · 能力执行层">
            <strong>A. 执行模式</strong> 固定执行(Workflow) · 动态执行(Agent ReAct/Planner)<br />
            <strong>B. 能力资产</strong> 流程Skill · 能力Skill · 知识Skill · Agent配置<br />
            <strong>C. 执行资源</strong> Tool · Memory · 知识库 · LLM配置(DeepSeek)
          </LayerBlock>

          <LayerBlock level="l3" title="第三层 · 本体翻译层">
            财资对象与关系 · 数据映射(字段/主数据/指标) · 规则与逻辑(AI归因/证据/模板)
          </LayerBlock>

          <LayerBlock level="l4" title="第四层 · 数据接入层">
            数据源：ERP/财报/凭证/银企/BI · 接入：API · 库表同步 · 文件 · ETL
          </LayerBlock>
        </Col>

        <Col xs={24} lg={8}>
          <LayerBlock level="gov" title="横向治理">
            <GovTags />
          </LayerBlock>
          <div style={{ marginTop: 16, padding: 16, background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0' }}>
            <Typography.Title level={5}>当前验证状态</Typography.Title>
            <Space direction="vertical" size={4} style={{ fontSize: 13 }}>
              <span>业务闭环：<Tag color="success">已验证</Tag></span>
              <span>差异判定：<Tag color="orange">程序规则执行</Tag>（非 AI 判定事实）</span>
              <span>规则版本：<Tag color="purple">可创建新版本并真实影响新任务</Tag></span>
              <span>Workflow/Skill：<Tag color="gold">按节点 skill_code 真实调度</Tag></span>
              <span>中台配置驱动：<Tag color="cyan">page_modules 驱动前台模块</Tag></span>
            </Space>
            <Link to="/workbench/reconciliation/tasks/new">
              <Button type="primary" block icon={<AppstoreOutlined />} style={{ marginTop: 12 }}>新建收入核对任务</Button>
            </Link>
          </div>
        </Col>
      </Row>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Typography, Button, Space, Alert } from 'antd'
import { PlusOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { getStats, getTasks, Task } from '../api/client'
import { usePublishedCenter } from '../context/PublishedCenterContext'

const statusMap: Record<string, string> = {
  draft: '草稿', running: '执行中', pending_review: '待复核', processing: '处理中',
  pending_verification: '待验证', reporting: '报告生成', closed: '已关闭', failed: '失败',
}

export default function Dashboard() {
  const { center, published, showModule } = usePublishedCenter()
  const [stats, setStats] = useState({
    period_tasks: 0, difference_count: 0, difference_amount: 0, pending_review_count: 0, closed_count: 0,
  })
  const [recent, setRecent] = useState<Task[]>([])

  useEffect(() => {
    getStats().then(setStats).catch(console.error)
    getTasks().then((t) => setRecent(t.slice(0, 5))).catch(console.error)
  }, [])

  if (!published) {
    return (
      <Alert
        type="warning"
        showIcon
        message="收入核对中心尚未发布"
        description="请使用管理员账号在管理后台发布业务中心后再使用工作台。"
      />
    )
  }

  const centerName = center?.name || '收入核对中心'

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>工作台模式 · {centerName}</Typography.Title>
          <Typography.Text type="secondary">收入核对 · 任务批次 · 差异复核闭环</Typography.Text>
        </div>
        {showModule('create_task') && (
          <Link to="/workbench/reconciliation/tasks/new">
            <Button type="primary" icon={<PlusOutlined />}>新建核对任务</Button>
          </Link>
        )}
      </Space>

      {showModule('today_summary') && (
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}><Card><Statistic title="本期任务数" value={stats.period_tasks} /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card><Statistic title="差异笔数" value={stats.difference_count} valueStyle={{ color: '#f59e0b' }} /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card><Statistic title="差异金额" value={stats.difference_amount} prefix="¥" /></Card></Col>
          <Col xs={24} sm={12} lg={6}><Card><Statistic title="待复核" value={stats.pending_review_count} valueStyle={{ color: '#f97316' }} /></Card></Col>
        </Row>
      )}
      {showModule('today_summary') && (
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col span={24}><Card><Statistic title="已关闭任务" value={stats.closed_count} valueStyle={{ color: '#10b981' }} /></Card></Col>
        </Row>
      )}

      {showModule('task_batches') && (
        <Card title="最近核对批次" style={{ marginTop: 24 }}>
          {recent.length === 0 ? (
            <Typography.Text type="secondary">暂无任务，点击「新建核对任务」开始</Typography.Text>
          ) : recent.map((t) => (
            <div key={t.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0', borderBottom: '1px solid #e2e8f0' }}>
              <div>
                <Typography.Text strong>{t.name}</Typography.Text>
                <br />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {statusMap[t.status] || t.status} · {t.period} · 进度 {t.progress}%
                  {t.summary && typeof (t.summary as { total?: number }).total === 'number' ? ` · ${(t.summary as { total: number }).total} 条差异` : ''}
                </Typography.Text>
              </div>
              <Link to={`/workbench/reconciliation/tasks/${t.id}`}>
                <Button type="link" icon={<ArrowRightOutlined />}>查看</Button>
              </Link>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}

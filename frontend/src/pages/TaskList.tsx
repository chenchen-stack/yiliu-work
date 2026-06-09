import { useCallback, useEffect, useState } from 'react'
import { Table, Tag, Button, Typography, Space, Popconfirm, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { deleteTask, getTasks, Task } from '../api/client'
import { formatApiError } from '../api/errors'
import { usePublishedCenter } from '../context/PublishedCenterContext'

const statusColor: Record<string, string> = {
  pending_review: 'gold', closed: 'green', failed: 'red', running: 'blue', processing: 'cyan',
}

const statusLabel: Record<string, string> = {
  draft: '草稿', running: '执行中', pending_review: '待复核', processing: '处理中',
  pending_verification: '待验证', reporting: '报告阶段', closed: '已关闭', failed: '失败',
}

export default function TaskList() {
  const { showModule } = usePublishedCenter()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string>()

  const loadTasks = useCallback(() => {
    setLoading(true)
    getTasks().then(setTasks).finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadTasks() }, [loadTasks])

  const handleDelete = async (task: Task) => {
    setDeletingId(task.id)
    try {
      await deleteTask(task.id)
      message.success('任务已删除')
      loadTasks()
    } catch (e: unknown) {
      message.error(formatApiError(e, '删除失败'))
    } finally {
      setDeletingId(undefined)
    }
  }

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Typography.Title level={4} style={{ margin: 0 }}>核对任务</Typography.Title>
        {showModule('create_task') && (
          <Link to="/workbench/reconciliation/tasks/new">
            <Button type="primary" icon={<PlusOutlined />}>新建任务</Button>
          </Link>
        )}
      </Space>
      <Table
        loading={loading}
        dataSource={tasks}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '任务名称', dataIndex: 'name' },
          {
            title: '状态', dataIndex: 'status',
            render: (s: string) => <Tag color={statusColor[s] || 'default'}>{statusLabel[s] || s}</Tag>,
          },
          { title: '进度', dataIndex: 'progress', render: (p: number) => `${p}%` },
          {
            title: '差异数',
            render: (_: unknown, r: Task) => (r.summary as { total?: number })?.total ?? '-',
          },
          { title: '创建时间', dataIndex: 'created_at', render: (d: string) => new Date(d).toLocaleString('zh-CN') },
          {
            title: '操作',
            width: 120,
            render: (_: unknown, r: Task) => (
              <Space size={0}>
                <Link to={`/workbench/reconciliation/tasks/${r.id}`}>
                  <Button type="link" size="small">详情</Button>
                </Link>
                <Popconfirm
                  title="删除此任务？"
                  description={r.status === 'running' ? '执行中不可删除' : '删除后不可恢复'}
                  okText="删除"
                  cancelText="取消"
                  okButtonProps={{ danger: true, loading: deletingId === r.id }}
                  disabled={r.status === 'running'}
                  onConfirm={() => handleDelete(r)}
                >
                  <Button type="link" size="small" danger disabled={r.status === 'running'}>
                    删除
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
    </div>
  )
}

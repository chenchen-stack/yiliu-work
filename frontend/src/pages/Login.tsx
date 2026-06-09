import { useState } from 'react'
import { Alert, Button, Card, Form, Input, Typography, message, Row, Col } from 'antd'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/client'

const isGitHubPagesDemo = import.meta.env.BASE_URL !== '/'

function isBackendUnavailable(error: unknown) {
  const err = error as { response?: { status?: number }; code?: string; message?: string }
  if (!err.response) return true
  const status = err.response.status
  return status === 404 || status === 502 || status === 503
}

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.username, values.password)
      message.success('登录成功')
      navigate('/')
    } catch (error) {
      if (isBackendUnavailable(error)) {
        message.error('无法连接后端服务，请先在本地启动 backend')
      } else {
        message.error('用户名或密码错误')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg,#ea580c,#f97316,#fff7ed)' }}>
      <div className="platform-header" style={{ textAlign: 'center' }}>
        <h1>亿流 Work · 企业财资 Agent 中台</h1>
        <p>一套中台内核 · 支撑多财资场景</p>
      </div>
      <Row justify="center" style={{ paddingTop: 48 }}>
        <Col xs={22} sm={16} md={10} lg={8}>
          <Card>
            <Typography.Title level={4} style={{ textAlign: 'center', color: '#ea580c' }}>登录</Typography.Title>
            {isGitHubPagesDemo && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message="GitHub Pages 仅托管前端页面"
                description="登录与业务数据需要 FastAPI 后端。请在本机运行 start-all.bat 或 start-backend.bat，然后访问 http://localhost:5175 使用完整功能。"
              />
            )}
            <Typography.Paragraph type="secondary" style={{ textAlign: 'center', fontSize: 13 }}>
              演示：lili / finance123 · admin / admin123
            </Typography.Paragraph>
            <Form layout="vertical" onFinish={onFinish} initialValues={{ username: 'lili', password: 'finance123' }}>
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input size="large" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                <Input.Password size="large" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block size="large" loading={loading}>进入中台</Button>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Button, Spin } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

type Props = {
  title: string
  subtitle?: string
  loading?: boolean
  error?: string
  onRetry?: () => void
  /** 前台管理页占满内容区宽度 */
  fullWidth?: boolean
  /** 极简顶栏：仅返回 + 标题，无副标题区 */
  minimal?: boolean
  /** 顶栏右侧操作（如上传） */
  headExtra?: ReactNode
  children: ReactNode
}

export function ChatManageShell({
  title,
  subtitle,
  loading,
  error,
  onRetry,
  fullWidth,
  minimal = false,
  headExtra,
  children,
}: Props) {
  return (
    <div className={`chat-manage-page${fullWidth ? ' chat-manage-page--full' : ''}${minimal ? ' chat-manage-page--minimal' : ''}`}>
      <header className="chat-manage-page__head">
        <Link to="/chat" className="chat-manage-page__back">
          <ArrowLeftOutlined /> 返回
        </Link>
        {!minimal && (
          <div className="chat-manage-page__titles">
            <span className="chat-manage-page__title">{title}</span>
            {subtitle && <span className="chat-manage-page__sub">{subtitle}</span>}
          </div>
        )}
        {minimal && <span className="chat-manage-page__title chat-manage-page__title--solo">{title}</span>}
        {headExtra && <div className="chat-manage-page__extra">{headExtra}</div>}
      </header>

      {loading ? (
        <div className="chat-manage-page__loading"><Spin size="large" /></div>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message={error}
          action={onRetry ? <Button size="small" onClick={onRetry}>重试</Button> : undefined}
        />
      ) : (
        <div className={`chat-manage-page__body${fullWidth ? ' chat-manage-page__body--flat' : ''}`}>{children}</div>
      )}
    </div>
  )
}

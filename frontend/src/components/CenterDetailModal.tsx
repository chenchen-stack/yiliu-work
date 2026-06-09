import type { ReactNode } from 'react'
import { Modal } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

type Props = {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  extra?: ReactNode
  width?: number
  children: ReactNode
}

/** 技能 / 知识库 · 居中详情弹层（替代卡片内联展开） */
export function CenterDetailModal({
  open,
  onClose,
  title,
  subtitle,
  extra,
  width = 720,
  children,
}: Props) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={width}
      centered
      destroyOnClose
      className="catalog-detail-modal"
      title={null}
      closable={false}
    >
      <header className="catalog-detail-modal__head">
        <div className="catalog-detail-modal__titles">
          <h3 className="catalog-detail-modal__title">{title}</h3>
          {subtitle ? <p className="catalog-detail-modal__subtitle">{subtitle}</p> : null}
        </div>
        <div className="catalog-detail-modal__actions">
          {extra ? <div className="catalog-detail-modal__extra">{extra}</div> : null}
          <button
            type="button"
            className="catalog-detail-modal__close"
            aria-label="关闭"
            onClick={onClose}
          >
            <CloseOutlined />
          </button>
        </div>
      </header>
      <div className="catalog-detail-modal__body">{children}</div>
    </Modal>
  )
}

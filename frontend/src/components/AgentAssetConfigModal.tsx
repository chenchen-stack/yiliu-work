import { Modal, Typography, Button } from 'antd'
import { CloseOutlined, ExportOutlined } from '@ant-design/icons'
import { resolveAgentAsset } from '../utils/agentAssetConfig'
import { AgentAssetConfigPanel } from './AgentAssetConfigPanel'

type Props = {
  open: boolean
  assetKey: string | null
  onClose: () => void
  onOpenInAssets: (assetKey: string) => void
  onTraceSkill?: (skillId: string) => void
  onCreateRuleVersion?: () => void
}

export function AgentAssetConfigModal({
  open,
  assetKey,
  onClose,
  onOpenInAssets,
  onTraceSkill,
  onCreateRuleVersion,
}: Props) {
  if (!assetKey) return null

  const target = resolveAgentAsset(assetKey)

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={920}
      style={{ maxWidth: '92vw' }}
      destroyOnClose={false}
      maskClosable
      keyboard
      zIndex={1100}
      className="agent-asset-modal wf-config-modal"
      styles={{
        mask: { backdropFilter: 'blur(2px)' },
        body: { padding: 0 },
        content: { padding: 0, overflow: 'hidden', borderRadius: 14 },
      }}
      closable
      closeIcon={<CloseOutlined className="wf-config-modal__close-icon" />}
      title={null}
    >
      <div className="wf-config-modal__shell">
        <header className="wf-config-modal__head">
          <div className="wf-config-modal__brand">
            <span className="wf-config-modal__accent agent-asset-modal__accent" />
            <div className="wf-config-modal__titles">
              <Typography.Title level={4} className="wf-config-modal__title">
                {target.title}
              </Typography.Title>
              <Typography.Text type="secondary" className="wf-config-modal__sub">
                {target.subtitle}
              </Typography.Text>
            </div>
          </div>
          <div className="wf-config-modal__actions">
            <Button
              type="text"
              size="small"
              icon={<ExportOutlined />}
              className="wf-config-modal__link"
              onClick={() => onOpenInAssets(assetKey)}
            >
              全屏编辑
            </Button>
            <Button type="primary" onClick={onClose}>
              完成
            </Button>
          </div>
        </header>
        <div className="wf-config-modal__body agent-asset-modal__body">
          <AgentAssetConfigPanel
            assetKey={assetKey}
            onOpenInAssets={() => onOpenInAssets(assetKey)}
            onTraceSkill={onTraceSkill}
            onCreateRuleVersion={onCreateRuleVersion}
          />
        </div>
      </div>
    </Modal>
  )
}

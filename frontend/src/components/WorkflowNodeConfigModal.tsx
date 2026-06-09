import { Button, Modal, Typography } from 'antd'
import { CloseOutlined, ExportOutlined } from '@ant-design/icons'
import type {
  AdminRuleConfig,
  BusinessCenter,
  OntologyMapping,
  WorkflowNode,
} from '../api/client'
import type { AdminSkillRow } from './AdminSkillsPage'
import { resolveWorkflowNodePanel } from '../utils/workflowNodeConfig'
import { WorkflowNodeConfigPanel } from './WorkflowNodeConfigPanel'

type Props = {
  open: boolean
  node: WorkflowNode | null
  ontology: OntologyMapping | null
  center: BusinessCenter
  rules: AdminRuleConfig[]
  skills: AdminSkillRow[]
  onClose: () => void
  onReload: () => void
  onCreateRuleVersion: () => void
  onOpenInAssets: () => void
}

export function WorkflowNodeConfigModal({
  open,
  node,
  ontology,
  center,
  rules,
  skills,
  onClose,
  onReload,
  onCreateRuleVersion,
  onOpenInAssets,
}: Props) {
  if (!node) return null

  const target = resolveWorkflowNodePanel(
    node.id,
    node.skill_code || node.skill,
    node.label,
  )

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
      className="wf-config-modal"
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
            <span className={`wf-config-modal__accent wf-config-modal__accent--${node.id}`} />
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
              onClick={onOpenInAssets}
            >
              全屏编辑
            </Button>
            <Button type="primary" onClick={onClose}>
              完成
            </Button>
          </div>
        </header>
        <div className="wf-config-modal__body">
          <WorkflowNodeConfigPanel
            nodeId={node.id}
            nodeLabel={node.label}
            skillCode={node.skill_code || node.skill}
            ontology={ontology}
            center={center}
            rules={rules}
            skills={skills}
            onReload={onReload}
            onCreateRuleVersion={onCreateRuleVersion}
            embedded
          />
        </div>
      </div>
    </Modal>
  )
}

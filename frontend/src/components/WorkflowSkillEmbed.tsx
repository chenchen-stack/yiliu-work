import { useMemo, useState } from 'react'
import { Typography } from 'antd'
import type { SkillPackageDetail } from '../api/client'
import type { AdminSkillRow } from '../types/adminSkill'
import { SkillPackagePanel } from './SkillPackagePanel'

type Props = {
  skillCode: string
  skills: AdminSkillRow[]
  nodeLabel?: string
}

export function WorkflowSkillEmbed({ skillCode, skills, nodeLabel }: Props) {
  const skillRow = useMemo(
    () => skills.find((s) => s.code === skillCode) || { code: skillCode, name: skillCode },
    [skills, skillCode],
  )
  const [pkgDetail, setPkgDetail] = useState<SkillPackageDetail | null>(null)

  if (!skillCode) {
    return <Typography.Text type="secondary">未绑定 Skill</Typography.Text>
  }

  return (
    <div className="wf-node-panel__skill">
      <SkillPackagePanel
        skillCode={skillCode}
        skillRow={skillRow}
        nodeLabel={nodeLabel}
        pkgDetail={pkgDetail}
        setPkgDetail={setPkgDetail}
        embedded
      />
    </div>
  )
}

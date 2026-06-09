import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Spin, Typography } from 'antd'
import {
  CodeOutlined, FileTextOutlined, SettingOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { getSkillPackage, type SkillPackageDetail } from '../api/client'
import type { AdminSkillRow } from '../types/adminSkill'

type FileKey = 'skill_md' | 'skill_yaml' | 'config_yaml' | 'schema'

const SKILL_TYPE_LABEL: Record<string, string> = {
  ability: '能力型',
  knowledge: '知识型',
  process: '流程型',
  flow: '流程型',
}

function buildSkillYamlPreview(pkg: SkillPackageDetail): string {
  const doc = {
    id: pkg.id,
    code: pkg.code,
    name: pkg.name,
    description: pkg.description,
    type: pkg.type,
    version: pkg.version,
    status: pkg.status,
    creator: pkg.creator,
    input_schema: pkg.input_schema,
    output_schema: pkg.output_schema,
  }
  return JSON.stringify(doc, null, 2)
}

export function SkillCardExpandPanel({
  skill,
  onConfig,
}: {
  skill: AdminSkillRow
  onConfig?: () => void
}) {
  const code = skill.code || ''
  const [pkg, setPkg] = useState<SkillPackageDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [fileTab, setFileTab] = useState<FileKey>('skill_md')

  useEffect(() => {
    if (!code) return
    setLoading(true)
    getSkillPackage(code)
      .then((d) => {
        setPkg(d)
        if (d.skill_md) setFileTab('skill_md')
        else setFileTab('skill_yaml')
      })
      .catch(() => setPkg(null))
      .finally(() => setLoading(false))
  }, [code])

  const files = useMemo(() => {
    const list: { key: FileKey; label: string; icon: ReactNode }[] = []
    if (pkg?.skill_md) list.push({ key: 'skill_md', label: 'skill.md', icon: <FileTextOutlined /> })
    list.push({ key: 'skill_yaml', label: 'skill.yaml', icon: <CodeOutlined /> })
    if (pkg?.config_schema && Object.keys(pkg.config_schema).length > 0) {
      list.push({ key: 'config_yaml', label: 'config.yaml', icon: <SettingOutlined /> })
    }
    list.push({ key: 'schema', label: 'input/output', icon: <ThunderboltOutlined /> })
    return list
  }, [pkg])

  if (loading) {
    return (
      <div className="skill-card-expand__loading">
        <Spin size="small" />
      </div>
    )
  }

  if (!pkg) {
    return (
      <Typography.Text type="secondary" className="skill-card-expand__empty">
        未找到 Skill 包，请确认 skill_packages/{code} 已安装
      </Typography.Text>
    )
  }

  return (
    <div className="skill-card-expand" onClick={(e) => e.stopPropagation()}>
      <div className="skill-card-expand__files">
        {files.map((f) => (
          <button
            key={f.key}
            type="button"
            className={`skill-card-expand__file${fileTab === f.key ? ' skill-card-expand__file--active' : ''}`}
            onClick={() => setFileTab(f.key)}
          >
            {f.icon}
            <span>{f.label}</span>
          </button>
        ))}
        {pkg.has_executor && (
          <span className="skill-card-expand__file skill-card-expand__file--ghost">execute.py</span>
        )}
        {onConfig && (
          <button type="button" className="skill-card-expand__link" onClick={onConfig}>
            业务配置 →
          </button>
        )}
      </div>
      <div className="skill-card-expand__preview">
        {fileTab === 'skill_md' && (
          <pre className="skill-card-expand__code">{pkg.skill_md || '（无 skill.md）'}</pre>
        )}
        {fileTab === 'skill_yaml' && (
          <pre className="skill-card-expand__code">{buildSkillYamlPreview(pkg)}</pre>
        )}
        {fileTab === 'config_yaml' && (
          <pre className="skill-card-expand__code">{JSON.stringify(pkg.config_schema, null, 2)}</pre>
        )}
        {fileTab === 'schema' && (
          <div className="skill-card-expand__schema-split">
            <div>
              <span className="skill-card-expand__schema-label">input</span>
              <pre className="skill-card-expand__code skill-card-expand__code--sm">
                {JSON.stringify(pkg.input_schema, null, 2)}
              </pre>
            </div>
            <div>
              <span className="skill-card-expand__schema-label">output</span>
              <pre className="skill-card-expand__code skill-card-expand__code--sm">
                {JSON.stringify(pkg.output_schema, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
      <div className="skill-card-expand__meta">
        <span>{code}</span>
        <span>{SKILL_TYPE_LABEL[pkg.type] || pkg.type}</span>
        <span>v{pkg.version}</span>
        {pkg.has_executor && <span className="skill-card-expand__meta--ok">可执行</span>}
      </div>
    </div>
  )
}

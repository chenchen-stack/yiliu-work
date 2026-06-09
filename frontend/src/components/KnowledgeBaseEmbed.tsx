import { useMemo, useState } from 'react'
import { Button, Input, Typography, Upload, message } from 'antd'
import { SearchOutlined, UploadOutlined } from '@ant-design/icons'
import type { CaseAsset } from '../api/client'
import { uploadKnowledgeExcel } from '../api/client'
import {
  AdminCaseDetailDrawer,
  AdminCaseEntriesPanel,
  KNOWLEDGE_BASES,
  caseBelongsToKb,
  filterCases,
} from './AdminKnowledgePage'

type Props = {
  kbId: string
  cases: CaseAsset[]
  onReload?: () => void
}

export function KnowledgeBaseEmbed({ kbId, cases, onReload }: Props) {
  const selectedKb = KNOWLEDGE_BASES.find((k) => k.id === kbId)
  const [typeFilter, setTypeFilter] = useState('all')
  const [keyword, setKeyword] = useState('')
  const [detail, setDetail] = useState<CaseAsset | null>(null)
  const [uploading, setUploading] = useState(false)

  const filteredCases = useMemo(
    () => filterCases(cases, { typeFilter, keyword, kbId }),
    [cases, kbId, typeFilter, keyword],
  )

  if (!selectedKb) {
    return <Typography.Text type="secondary">未找到知识库 {kbId}</Typography.Text>
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const res = await uploadKnowledgeExcel(file, kbId)
      message.success(`已解析入库 ${res.entries_created} 条`)
      await onReload?.()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(err.response?.data?.detail || err.message || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const totalInKb = cases.filter((c) => caseBelongsToKb(c, kbId)).length

  return (
    <div className="agent-asset-kb-embed">
      <div className="agent-asset-kb-embed__head">
        <div>
          <Typography.Text strong>{selectedKb.name}</Typography.Text>
          <Typography.Text type="secondary" className="agent-asset-kb-embed__sub">
            {selectedKb.desc} · 共 {totalInKb} 条
          </Typography.Text>
        </div>
        <Upload
          accept=".xlsx,.xls"
          showUploadList={false}
          disabled={uploading}
          beforeUpload={(file) => {
            void handleUpload(file as File)
            return false
          }}
        >
          <Button size="small" type="primary" icon={<UploadOutlined />} loading={uploading}>
            上传 Excel
          </Button>
        </Upload>
      </div>
      <Input
        allowClear
        size="small"
        prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
        placeholder="搜索根因、处理结果或建议"
        className="admin-skills-search admin-kb-search"
        value={keyword}
        onChange={(e) => setKeyword(e.target.value)}
        style={{ marginBottom: 10 }}
      />
      <AdminCaseEntriesPanel
        title=""
        subtitle={`筛选后 ${filteredCases.length} 条`}
        cases={filteredCases}
        typeFilter={typeFilter}
        onTypeFilterChange={setTypeFilter}
        keyword={keyword}
        onKeywordChange={setKeyword}
        emptyDescription="暂无条目，可上传 Excel 或从对账任务沉淀"
        onOpen={setDetail}
        hideTitle
      />
      <AdminCaseDetailDrawer caseItem={detail} open={!!detail} onClose={() => setDetail(null)} />
    </div>
  )
}

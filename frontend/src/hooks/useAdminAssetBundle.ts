import { useCallback, useEffect, useState } from 'react'
import {
  getAdminBusinessCenter,
  getAdminBusinessCenters,
  getAdminLlmConfig,
  getAdminOntologyMapping,
  getAdminRules,
  getAdminSkills,
  type AdminRuleConfig,
  type BusinessCenter,
  type LlmConfig,
  type OntologyMapping,
} from '../api/client'
import type { AdminSkillRow } from '../components/AdminSkillsPage'
import { ensureWorkflowNodes } from '../utils/workflowNodes'

const BC_ID = 'bc-revenue-reconciliation'

export function useAdminAssetBundle() {
  const [center, setCenter] = useState<BusinessCenter | null>(null)
  const [ontology, setOntology] = useState<OntologyMapping | null>(null)
  const [rules, setRules] = useState<AdminRuleConfig[]>([])
  const [llmConfig, setLlmConfig] = useState<LlmConfig | null>(null)
  const [skills, setSkills] = useState<AdminSkillRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const centers = await getAdminBusinessCenters()
      const id = centers[0]?.id || BC_ID
      const [c, ont, ru, llm, sk] = await Promise.all([
        getAdminBusinessCenter(id),
        getAdminOntologyMapping().catch(() => null),
        getAdminRules({ rule_version_id: centers[0]?.rule_version_id }).catch(() => []),
        getAdminLlmConfig().catch(() => null),
        getAdminSkills().catch(() => []),
      ])
      setCenter(c)
      setOntology(ont)
      setRules(ru)
      setLlmConfig(llm)
      setSkills(sk as AdminSkillRow[])
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const workflowNodes = ensureWorkflowNodes(center?.workflow?.nodes || [])

  return {
    center,
    ontology,
    rules,
    llmConfig,
    skills,
    workflowNodes,
    enabledSkills: (center?.skills || skills) as AdminSkillRow[],
    loading,
    error,
    reload: load,
  }
}

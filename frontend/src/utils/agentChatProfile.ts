import type { AgentConfigItem } from '../api/client'

import { avatarImageUrl, resolveAvatarId } from './agentAvatars'



export type ChatUiBlock = { type: string; data: Record<string, unknown> }



export type WelcomeCapItem = {
  n: number
  title: string
  desc: string
  href?: string
  prompt?: string
  client_action?: string
  kb_id?: string
}



/** 面向业务用户的展示文案，不暴露 skill / kb / 数据源 ID */

const SKILL_DISPLAY: Record<string, { title: string; desc: string; tag?: string }> = {

  'skill-query_tasks': {

    title: '查看对账任务',

    desc: '了解进行中任务、待复核条数与最近核对批次',

    tag: '任务查询',

  },

  'skill-anomaly_explain': {

    title: '差异智能解释',

    desc: '结合方太规则与证据链，说明差异原因与处理建议',

    tag: '差异解释',

  },

}



const DATA_SOURCE_DISPLAY: Record<string, string> = {

  sap_billing: 'SAP 发货开票',

  dms_ledger: 'DMS 收入台账',

  sap: 'SAP 发货开票',

  dms: 'DMS 收入台账',

}



const KB_DISPLAY: Record<string, { title: string; desc: string; tag?: string }> = {

  'kb-fangtai-cases': {

    title: '方太案例经验',

    desc: '参考历史差异处理案例，辅助给出可落地的处理建议',

    tag: '案例参考',

  },

  'kb-compliance': {

    title: '合规与校验要点',

    desc: '查阅合规校验相关说明，辅助复核判断',

    tag: '合规要点',

  },

  revenue_reconciliation: {

    title: '收入核对知识',

    desc: '查阅收入核对领域的标准说明与口径',

    tag: '业务知识',

  },

}



const DEFAULT_WELCOME: WelcomeCapItem[] = [

  { n: 1, title: '查看对账任务', desc: '了解进度、待复核与最近批次' },

  { n: 2, title: '差异智能解释', desc: '说明金额差异、重复与映射类问题的原因' },

  { n: 3, title: '对话内发起核对', desc: '选择 SAP 发货开票与 DMS 收入台账进行比对' },

  { n: 4, title: '进入收入核对工作台', desc: '进入正式任务，完成复核、验证与报告' },

]



function looksTechnical(text: string): boolean {

  const t = text.trim()

  if (!t) return true

  return /^[a-z0-9][a-z0-9_.-]*$/i.test(t) && (t.includes('_') || t.includes('-') || t.startsWith('skill-') || t.startsWith('kb-'))

}



function friendlyDataSourceLabel(id?: string, name?: string): string {

  const key = String(id || '').trim()

  if (key && DATA_SOURCE_DISPLAY[key]) return DATA_SOURCE_DISPLAY[key]

  const n = String(name || '').trim()

  if (n && !looksTechnical(n)) return n

  if (/sap/i.test(key) || /sap/i.test(n)) return 'SAP 发货开票'

  if (/dms/i.test(key) || /dms/i.test(n)) return 'DMS 收入台账'

  return '业务数据'

}



function friendlySkill(
  id?: string,
  name?: string,
  backendDesc?: string,
): { title: string; desc: string; tag?: string } {
  const key = String(id || '').trim()
  const n = String(name || '').trim()
  const preset = key && SKILL_DISPLAY[key] ? SKILL_DISPLAY[key] : null

  if (n.includes('任务') || key.includes('query')) {
    const base = SKILL_DISPLAY['skill-query_tasks']
    return {
      ...base,
      title: n && !looksTechnical(n) ? n : base.title,
      desc: backendDesc?.trim() || base.desc,
    }
  }

  if (n.includes('异常') || key.includes('anomaly')) {
    const base = SKILL_DISPLAY['skill-anomaly_explain']
    return {
      ...base,
      title: n && !looksTechnical(n) ? n : base.title,
      desc: backendDesc?.trim() || base.desc,
    }
  }

  if (preset) {
    return {
      ...preset,
      title: n && !looksTechnical(n) ? n : preset.title,
      desc: backendDesc?.trim() || preset.desc,
    }
  }

  if (n && !looksTechnical(n)) {
    return {
      title: n,
      desc: backendDesc?.trim() || '按授权范围为您提供相关能力',
      tag: n,
    }
  }

  return {
    title: '智能分析',
    desc: backendDesc?.trim() || '按授权范围为您提供相关能力',
  }
}



function friendlyKb(id?: string, name?: string): { title: string; desc: string; tag?: string } {

  const key = String(id || '').trim()

  if (key && KB_DISPLAY[key]) return KB_DISPLAY[key]

  const n = String(name || '').trim()

  if (n && !looksTechnical(n)) {

    return { title: n, desc: '查阅已沉淀的业务知识，辅助分析与建议', tag: n }

  }

  return { title: '业务知识库', desc: '查阅已沉淀的业务知识，辅助分析与建议', tag: '知识参考' }

}



function friendlyWorkflowLabel(name?: string | null): { title: string; desc: string; tag: string } {

  const n = String(name || '').trim()

  const title = n && !looksTechnical(n) && !/workflow/i.test(n)

    ? n

    : '收入核对工作台'

  return {

    title: `进入${title.replace(/^进入/, '')}`,

    desc: '需要正式审批、复核与出具报告时，从这里进入完整流程',

    tag: '核对工作台',

  }

}



export function enrichWelcomeCapAction(
  item: WelcomeCapItem,
  ctx?: { skillId?: string; kbId?: string },
): WelcomeCapItem {
  const kbId = ctx?.kbId || item.kb_id
  if (kbId) {
    const f = friendlyKb(kbId)
    return {
      ...item,
      kb_id: kbId,
      title: item.title || f.title,
      prompt: item.prompt || `请检索${f.title}，说明常见收入/回款异常场景的排查要点与处理建议`,
      client_action: item.client_action || 'query_knowledge',
    }
  }
  if (item.href || item.prompt) return item

  const skillId = ctx?.skillId || ''
  const title = item.title

  if (skillId === 'skill-query_tasks' || /对账任务|查看任务/.test(title)) {
    return {
      ...item,
      prompt: '我有哪些进行中的对账任务？',
      client_action: 'query_tasks',
    }
  }
  if (skillId === 'skill-anomaly_explain' || (/差异/.test(title) && /解释/.test(title))) {
    return {
      ...item,
      prompt: '请结合方太规则与证据链，说明差异原因与处理建议',
    }
  }
  if (/双源|发起核对|对话内/.test(title) || (/SAP|DMS/.test(title) && /收入|数据/.test(title))) {
    return {
      ...item,
      prompt: '帮我核对一下最近一期的收入数据，比较SAP发货开票和DMS收入台账',
      client_action: 'start_reconciliation',
    }
  }
  if (/知识库|案例/.test(title) || title.startsWith('kb-')) {
    return enrichWelcomeCapAction(
      { ...item, kb_id: 'kb-fangtai-cases' },
      { kbId: 'kb-fangtai-cases' },
    )
  }
  if (/合规/.test(title)) {
    return enrichWelcomeCapAction({ ...item, kb_id: 'kb-compliance' }, { kbId: 'kb-compliance' })
  }
  if (/收入核对知识/.test(title)) {
    return enrichWelcomeCapAction(
      { ...item, kb_id: 'revenue_reconciliation' },
      { kbId: 'revenue_reconciliation' },
    )
  }
  if (/工作台|进入收入/.test(title)) {
    return { ...item, href: '/workbench/reconciliation' }
  }
  return item
}



export function sortAgentsForChat(list: AgentConfigItem[]): AgentConfigItem[] {

  return [...list].sort((a, b) => {

    if (a.code === 'revenue_diff_explain') return -1

    if (b.code === 'revenue_diff_explain') return 1

    if (a.scope === 'team_published' && b.scope !== 'team_published') return -1

    if (b.scope === 'team_published' && a.scope !== 'team_published') return 1

    return (a.name || '').localeCompare(b.name || '', 'zh')

  })

}



/** 底部挂载标签：短中文，不出现 ID */

export function mountTags(agent?: AgentConfigItem | null): string[] {

  if (!agent) return []

  const m = agent.asset_mounts

  if (!m) return []

  const tags: string[] = []

  const push = (t?: string) => {

    const v = String(t || '').trim()

    if (v && !tags.includes(v)) tags.push(v)

  }



  for (const s of m.skills || []) {
    push(friendlySkill(s.id, s.name, s.desc).tag)
  }

  const dsLabels = (m.data_sources || [])

    .map((d) => friendlyDataSourceLabel(d.id, d.name))

    .filter(Boolean)

  if (dsLabels.length) {

    push(dsLabels.join(' · '))

  }

  for (const k of m.knowledge_bases || []) {

    push(friendlyKb(k.id, k.name).tag)

  }

  if (m.linked_workflow || m.linked_workflow_name) {

    push(friendlyWorkflowLabel(m.linked_workflow_name).tag)

  }

  return tags.slice(0, 4)

}



export function buildWelcomeItemsFromAgent(agent?: AgentConfigItem | null): WelcomeCapItem[] {

  if (!agent) return DEFAULT_WELCOME.map((it, i) => ({ ...it, n: i + 1 }))

  const m = agent.asset_mounts

  const items: WelcomeCapItem[] = []

  let n = 1



  for (const sk of m?.skills || []) {
    const f = friendlySkill(sk.id, sk.name, sk.desc)
    items.push(enrichWelcomeCapAction({ n: n++, title: f.title, desc: f.desc }, { skillId: sk.id }))
  }



  const ds = m?.data_sources || []

  if (ds.length) {

    const labels = [...new Set(ds.map((d) => friendlyDataSourceLabel(d.id, d.name)))]

    items.push(enrichWelcomeCapAction({

      n: n++,

      title: '双源收入数据',

      desc: labels.join(' · '),

    }))

  }



  for (const kb of m?.knowledge_bases || []) {

    if (items.length >= 4) break

    const f = friendlyKb(kb.id, kb.name)

    items.push(enrichWelcomeCapAction({ n: n++, title: f.title, desc: f.desc }, { kbId: kb.id }))

  }



  if (m?.linked_workflow && items.length < 4) {

    const wf = friendlyWorkflowLabel(m.linked_workflow_name)

    items.push(enrichWelcomeCapAction({ n: n++, title: wf.title, desc: wf.desc }))

  }



  if (!items.length) {

    return DEFAULT_WELCOME.map((it, i) => enrichWelcomeCapAction({ ...it, n: i + 1 }))

  }

  return items.slice(0, 4).map((it, i) => ({ ...it, n: i + 1 }))

}



function sanitizeCapItem(item: WelcomeCapItem): WelcomeCapItem {
  let next = item
  if (looksTechnical(item.title)) {
    if (String(item.title).startsWith('skill-')) {
      const f = friendlySkill(item.title, item.title)
      next = { ...item, title: f.title, desc: f.desc }
      return enrichWelcomeCapAction(next, { skillId: item.title })
    }
    if (String(item.title).startsWith('kb-')) {
      const f = friendlyKb(item.title, item.title)
      next = { ...item, title: f.title, desc: f.desc }
      return enrichWelcomeCapAction(next, { kbId: item.title })
    }
    if (/sap|dms|billing|ledger/i.test(item.title)) {
      next = {
        ...item,
        title: '双源收入数据',
        desc: item.desc
          .split('·')
          .map((p) => friendlyDataSourceLabel(p.trim(), p.trim()))
          .join(' · '),
      }
    }
  }
  return enrichWelcomeCapAction(next)
}

function sanitizeMountTag(tag: string): string {
  const t = tag.trim()
  if (!t) return ''
  if (!looksTechnical(t)) return t
  if (t.startsWith('skill-')) return friendlySkill(t, t).tag || '智能分析'
  if (t.startsWith('kb-')) return friendlyKb(t, t).tag || '知识参考'
  if (DATA_SOURCE_DISPLAY[t]) return DATA_SOURCE_DISPLAY[t]
  if (/workflow/i.test(t)) return '核对工作台'
  return ''
}

/** 历史会话里旧的 welcome 块也转成业务文案 */
export function sanitizeWelcomeBlockData(data: Record<string, unknown>): Record<string, unknown> {
  const items = (Array.isArray(data.items) ? data.items : []) as WelcomeCapItem[]
  const tags = (Array.isArray(data.mount_tags) ? data.mount_tags : []) as string[]
  const description = String(data.description || '').trim()
  return {
    ...data,
    description: description && !looksTechnical(description)
      ? description
      : '帮您查任务、解释差异、发起核对，并可引导进入正式收入核对流程。',
    items: items.map(sanitizeCapItem),
    mount_tags: [...new Set(tags.map(sanitizeMountTag).filter(Boolean))].slice(0, 4),
  }
}

export function buildWelcomeCapsBlock(agent?: AgentConfigItem | null): ChatUiBlock {

  const items = buildWelcomeItemsFromAgent(agent)

  const mounts = mountTags(agent)

  const defaultDesc = '帮您查任务、解释差异、发起核对，并可引导进入正式收入核对流程。'

  const rawDesc = agent?.description?.trim() || ''

  const description = rawDesc && !looksTechnical(rawDesc) ? rawDesc : defaultDesc



  return {

    type: 'welcome_caps',

    data: {

      agent_id: agent?.id,

      agent_name: agent?.name || '收入核对助手',

      avatar_id: agent ? resolveAvatarId(agent) : 'anime-04',

      description,

      items,

      mount_tags: mounts,

    },

  }

}



export function buildChipsFromAgent(

  agent: AgentConfigItem | undefined,

  hasContext: boolean,

): Array<{ label: string; prompt: string; action?: string }> {

  if (hasContext) {

    return [

      { label: '解释归因', prompt: '请解释当前差异的归因结论与证据链' },

      { label: '处理说明', prompt: '请生成该差异的处理说明建议' },

    ]

  }

  const skills = new Set(agent?.allowed_skill_ids || [])

  const chips: Array<{ label: string; prompt: string; action?: string }> = [

    {

      label: '发起对账',

      prompt: '帮我核对一下5月份的收入数据，比较SAP发货开票和DMS收入台账',

      action: 'start_reconciliation',

    },

  ]

  if (skills.has('skill-query_tasks')) {

    chips.push({
      label: '查看任务',
      prompt: '我有哪些进行中的方太对账任务？',
      action: 'query_tasks',
    })

  }

  chips.push(
    { label: '核对流程', prompt: '方太收入核对中心的标准流程是什么？', action: 'faq_workflow' },
    { label: '差异类型', prompt: '金额差异、重复数据、映射异常分别怎么处理？', action: 'faq_diff_types' },
  )

  const kbIds = agent?.knowledge_base_ids || []
  if (kbIds.includes('revenue_reconciliation') || kbIds.some((id) => String(id).includes('revenue'))) {
    chips.push({
      label: '检索知识库',
      prompt: '请检索收入核对知识，说明回款异常怎么处理',
      action: 'query_knowledge',
    })
  } else if (kbIds.length) {
    chips.push({
      label: '检索知识库',
      prompt: '请检索方太历史案例库，说明常见差异的处理建议',
      action: 'query_knowledge',
    })
  }

  return chips

}



export function agentAssistantAvatarUrl(agent?: AgentConfigItem | null): string | undefined {

  if (!agent) return undefined

  return avatarImageUrl(resolveAvatarId(agent))

}



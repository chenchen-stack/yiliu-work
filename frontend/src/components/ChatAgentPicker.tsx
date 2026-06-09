import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { DownOutlined } from '@ant-design/icons'
import type { AgentConfigItem } from '../api/client'
import { agentAssistantAvatarUrl, mountTags } from '../utils/agentChatProfile'
import { avatarImageUrl, resolveAvatarId } from '../utils/agentAvatars'

type Props = {
  agents: AgentConfigItem[]
  value?: string
  onChange: (agentId: string) => void
  disabled?: boolean
}

export default function ChatAgentPicker({ agents, value, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false)
  const [menuPos, setMenuPos] = useState<{ left: number; bottom: number; width: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const selected = useMemo(
    () => agents.find((a) => a.id === value) || agents[0],
    [agents, value],
  )

  const updateMenuPos = () => {
    const el = triggerRef.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const width = Math.min(340, window.innerWidth - 24)
    let left = r.left
    if (left + width > window.innerWidth - 12) {
      left = Math.max(12, window.innerWidth - width - 12)
    }
    setMenuPos({
      left,
      bottom: window.innerHeight - r.top + 8,
      width,
    })
  }

  useLayoutEffect(() => {
    if (!open) {
      setMenuPos(null)
      return
    }
    updateMenuPos()
    window.addEventListener('resize', updateMenuPos)
    window.addEventListener('scroll', updateMenuPos, true)
    return () => {
      window.removeEventListener('resize', updateMenuPos)
      window.removeEventListener('scroll', updateMenuPos, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!agents.length) return null

  const thumb = selected ? agentAssistantAvatarUrl(selected) : avatarImageUrl('anime-04')

  const menu = open && menuPos
    ? createPortal(
        <>
          <button
            type="button"
            className="chat-agent-picker__backdrop"
            aria-label="关闭"
            onClick={() => setOpen(false)}
          />
          <div
            className="chat-agent-picker__menu chat-agent-picker__menu--fixed"
            role="listbox"
            style={{
              left: menuPos.left,
              bottom: menuPos.bottom,
              width: menuPos.width,
            }}
          >
            {agents.map((a) => {
              const on = a.id === (value || selected?.id)
              const tags = mountTags(a)
              return (
                <button
                  key={a.id}
                  type="button"
                  role="option"
                  aria-selected={on}
                  className={`chat-agent-picker__item${on ? ' is-active' : ''}`}
                  onClick={() => {
                    onChange(a.id)
                    setOpen(false)
                  }}
                >
                  <img
                    src={avatarImageUrl(resolveAvatarId(a))}
                    alt=""
                    className="chat-agent-picker__item-avatar"
                  />
                  <div className="chat-agent-picker__item-body">
                    <span className="chat-agent-picker__item-title">{a.name}</span>
                    <span className="chat-agent-picker__item-desc">
                      {a.description || '方太收入核对场景'}
                    </span>
                    {tags.length > 0 && (
                      <span className="chat-agent-picker__item-tags">{tags.join(' · ')}</span>
                    )}
                  </div>
                </button>
              )
            })}
          </div>
        </>,
        document.body,
      )
    : null

  return (
    <div className="chat-agent-picker">
      <button
        ref={triggerRef}
        type="button"
        className="chat-agent-picker__trigger"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        <img src={thumb} alt="" className="chat-agent-picker__thumb" />
        <span className="chat-agent-picker__name">{selected?.name || '选择 Agent'}</span>
        <DownOutlined className={`chat-agent-picker__chev${open ? ' is-open' : ''}`} />
      </button>
      {menu}
    </div>
  )
}

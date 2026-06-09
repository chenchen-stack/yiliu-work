/** 用户 / AI 使用不同动漫风格，避免两张头像看起来像同一人 */
function avatarUrl(style: string, seed: string, bg: string, flip = false) {
  const q = new URLSearchParams({
    seed,
    backgroundColor: bg,
    radius: '50',
  })
  if (flip) q.set('flip', 'true')
  return `https://api.dicebear.com/9.x/${style}/svg?${q.toString()}`
}

/** 用户：adventurer 少年感角色，朝左（面向气泡） */
const USER_AVATAR = avatarUrl('adventurer-neutral', 'yiliu-work-user', 'fff7ed', true)
/** AI：lorelei 助手形象，与用户明显区分 */
const AI_AVATAR = avatarUrl('lorelei', 'yiliu-work-agent', 'ffedd5')

export function ChatAvatar({
  role,
  assistantSrc,
}: {
  role: 'user' | 'assistant'
  /** 后台 Agent 配置的动漫头像 URL */
  assistantSrc?: string
}) {
  const isUser = role === 'user'
  const src = isUser ? USER_AVATAR : (assistantSrc || AI_AVATAR)
  return (
    <img
      className={`chat-fs-avatar-img chat-fs-avatar-img--${role}`}
      src={src}
      alt={isUser ? '我' : 'AI 助手'}
      width={36}
      height={36}
      draggable={false}
    />
  )
}

/** 动漫风格 Agent 头像（DiceBear lorelei，离线可缓存） */
export type AnimeAvatar = {
  id: string
  seed: string
  label: string
}

export const ANIME_AVATARS: AnimeAvatar[] = [
  { id: 'anime-01', seed: 'Airi', label: '茜' },
  { id: 'anime-02', seed: 'Kenji', label: '健司' },
  { id: 'anime-03', seed: 'Mika', label: '美香' },
  { id: 'anime-04', seed: 'Haru', label: '春' },
  { id: 'anime-05', seed: 'Yuki', label: '雪' },
  { id: 'anime-06', seed: 'Ren', label: '莲' },
  { id: 'anime-07', seed: 'Sora', label: '空' },
  { id: 'anime-08', seed: 'Nao', label: '奈绪' },
  { id: 'anime-09', seed: 'Kaito', label: '海斗' },
  { id: 'anime-10', seed: 'Emi', label: '惠美' },
  { id: 'anime-11', seed: 'Rin', label: '凛' },
  { id: 'anime-12', seed: 'Tao', label: '涛' },
]

const DEFAULT_AVATAR_ID = 'anime-01'

export function animeAvatarUrl(seed: string, size = 96): string {
  const bg = 'ffdfbf,ffd5dc,d1d4f9,b6e3f4,c0aede'
  return `https://api.dicebear.com/9.x/lorelei/svg?seed=${encodeURIComponent(seed)}&backgroundColor=${bg}&size=${size}`
}

export function resolveAvatarId(agent?: { avatar_id?: string; model_config_json?: Record<string, unknown> } | null): string {
  if (!agent) return DEFAULT_AVATAR_ID
  const fromMc = agent.model_config_json?.avatar_id
  if (typeof fromMc === 'string' && fromMc) return fromMc
  return agent.avatar_id || DEFAULT_AVATAR_ID
}

export function getAnimeAvatar(id?: string | null): AnimeAvatar {
  return ANIME_AVATARS.find((a) => a.id === id) || ANIME_AVATARS[0]
}

export function avatarImageUrl(id?: string | null): string {
  const av = getAnimeAvatar(id)
  return animeAvatarUrl(av.seed)
}

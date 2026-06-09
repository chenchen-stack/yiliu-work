import deepseekLogo from '../assets/brand/deepseek-logo.png'

type Props = {
  provider?: string
  size?: number
  className?: string
}

export function LlmProviderLogo({ provider = 'deepseek', size = 44, className }: Props) {
  if (provider === 'deepseek') {
    return (
      <img
        src={deepseekLogo}
        alt="DeepSeek"
        width={size}
        height={size}
        className={className ? `llm-provider-logo ${className}` : 'llm-provider-logo'}
        draggable={false}
      />
    )
  }
  const label = provider.slice(0, 2).toUpperCase()
  return (
    <div
      className={className ? `llm-provider-logo llm-provider-logo--fallback ${className}` : 'llm-provider-logo llm-provider-logo--fallback'}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.32) }}
      aria-hidden
    >
      {label}
    </div>
  )
}

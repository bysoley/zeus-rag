import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, ChevronDown } from 'lucide-react'
import type { Message } from '../types'

interface Props {
  scopeOptions: string[]
}

export default function Chat({ scopeOptions }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [scope, setScope] = useState('전체')
  const [isLoading, setIsLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (scopeOptions.length > 0 && !scopeOptions.includes(scope)) {
      setScope(scopeOptions[0])
    }
  }, [scopeOptions, scope])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const adjustHeight = () => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isLoading) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setIsLoading(true)

    setMessages(prev => [
      ...prev,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ])

    try {
      const res = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, scope }),
      })

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const data = JSON.parse(line.slice(6)) as {
            content?: string
            sources?: string
            error?: string
            done?: boolean
          }

          setMessages(prev => {
            const msgs = [...prev]
            const last = msgs[msgs.length - 1]
            if (data.content) {
              msgs[msgs.length - 1] = { ...last, content: last.content + data.content }
            }
            if (data.sources) {
              msgs[msgs.length - 1] = { ...last, content: last.content, sources: data.sources }
            }
            if (data.error) {
              msgs[msgs.length - 1] = { ...last, content: `오류: ${data.error}`, error: true }
            }
            return msgs
          })
        }
      }
    } catch {
      setMessages(prev => {
        const msgs = [...prev]
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content: '네트워크 오류가 발생했습니다.', error: true }
        return msgs
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Scope selector */}
      <div className="flex items-center gap-2 px-5 py-3">
        <span className="text-xs text-muted">범위</span>
        <div className="relative">
          <select
            value={scope}
            onChange={e => setScope(e.target.value)}
            className="appearance-none bg-surface-2 text-xs text-white rounded-md pl-3 pr-7 py-1.5 focus:outline-none cursor-pointer"
          >
            {scopeOptions.map(opt => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
          <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <p className="text-muted text-sm">로컬 자료에 대해 질문하세요</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {msg.role === 'user' ? (
              <div className="max-w-[72%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-accent text-white text-sm leading-relaxed">
                {msg.content}
              </div>
            ) : (
              <div className="max-w-[80%] space-y-2">
                <div className="px-4 py-3 rounded-2xl rounded-bl-sm bg-surface-2 text-sm text-[#e5e7eb]">
                  {msg.content ? (
                    <div className="md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <span className="inline-block w-1.5 h-4 bg-accent animate-pulse rounded-sm" />
                  )}
                </div>
                {msg.sources && (
                  <div className="px-4 py-2.5 rounded-xl bg-surface-2">
                    <p className="text-xs text-muted mb-1 font-medium">출처</p>
                    <pre className="text-xs text-muted whitespace-pre-wrap font-sans leading-relaxed">
                      {msg.sources}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-5 py-4">
        <div className="flex items-center gap-3 bg-surface-2 rounded-2xl px-4 py-2.5">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => { setInput(e.target.value); adjustHeight() }}
            onKeyDown={handleKeyDown}
            placeholder="질문을 입력하세요  (Shift+Enter로 줄바꿈)"
            rows={1}
            className="flex-1 bg-transparent text-sm text-white placeholder-muted resize-none outline-none"
            style={{ maxHeight: '160px', padding: 0, lineHeight: '1.5' }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <Send size={14} className="text-white" />
          </button>
        </div>
      </div>
    </div>
  )
}

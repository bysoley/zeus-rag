import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronDown, Send, Square } from 'lucide-react'
import type { Conversation, Message, SourceRef } from '../types'

interface Props {
  scopeOptions: string[]
  conversationId: string | null
  onConversationChanged: (conversation: Conversation) => void
  onBusyChange: (busy: boolean) => void
}

type Stage = 'retrieving' | 'generating'

interface StreamEvent {
  type: 'status' | 'delta' | 'complete' | 'error'
  stage?: Stage
  content?: string
  error?: string
  message?: Message
  conversation?: Conversation
}

const STAGE_LABEL: Record<Stage, string> = {
  retrieving: '관련 자료 검색 중...',
  generating: '답변 생성 중...',
}

function formatSource(source: SourceRef) {
  const location = source.heading
    ?? (source.start_line ? `L${source.start_line}-${source.end_line}` : null)
  const provider = source.provider ? ` (${source.provider})` : ''
  return `[${source.label}] ${source.source_id}:${source.relative_path}${location ? ` > ${location}` : ''}${provider} (유사도 ${source.similarity.toFixed(2)})`
}

export default function Chat({
  scopeOptions,
  conversationId,
  onConversationChanged,
  onBusyChange,
}: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [scope, setScope] = useState('전체')
  const [isLoading, setIsLoading] = useState(false)
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [stage, setStage] = useState<Stage | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const locallyCreatedIdRef = useRef<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (scopeOptions.length > 0 && !scopeOptions.includes(scope)) {
      setScope(scopeOptions[0])
    }
  }, [scopeOptions, scope])

  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      setScope('전체')
      return
    }
    if (locallyCreatedIdRef.current === conversationId) {
      locallyCreatedIdRef.current = null
      return
    }

    let cancelled = false
    setIsHistoryLoading(true)
    fetch(`/api/conversations/${conversationId}/messages`)
      .then(response => {
        if (!response.ok) throw new Error('대화 기록을 불러오지 못했습니다.')
        return response.json()
      })
      .then((loaded: Message[]) => {
        if (cancelled) return
        setMessages(loaded)
        const lastUserScope = [...loaded].reverse().find(message => message.role === 'user')?.scope
        setScope(lastUserScope && scopeOptions.includes(lastUserScope) ? lastUserScope : '전체')
      })
      .catch(() => {
        if (!cancelled) setMessages([])
      })
      .finally(() => {
        if (!cancelled) setIsHistoryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId, scopeOptions])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const adjustHeight = () => {
    const element = textareaRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = Math.min(element.scrollHeight, 160) + 'px'
  }

  const replaceLastAssistant = (update: (message: Message) => Message) => {
    setMessages(current => {
      const next = [...current]
      const index = next.map(message => message.role).lastIndexOf('assistant')
      if (index >= 0) {
        next[index] = update(next[index])
      } else {
        next.push(update({ role: 'assistant', content: '', sources: [], status: 'streaming' }))
      }
      return next
    })
  }

  const handleSend = async () => {
    const text = input.trim()
    if (!text || isLoading || isHistoryLoading) return

    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    setIsLoading(true)
    setStage('retrieving')
    onBusyChange(true)
    let activeConversationId = conversationId
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      if (!activeConversationId) {
        const createResponse = await fetch('/api/conversations', { method: 'POST' })
        if (!createResponse.ok) throw new Error('새 대화를 만들지 못했습니다.')
        const created = await createResponse.json() as Conversation
        activeConversationId = created.id
        locallyCreatedIdRef.current = created.id
        onConversationChanged(created)
      }

      const optimisticUser: Message = {
        role: 'user',
        content: text,
        scope,
        sources: [],
        status: 'complete',
      }
      const optimisticAssistant: Message = {
        role: 'assistant',
        content: '',
        sources: [],
        status: 'streaming',
      }
      setMessages(current => [...current, optimisticUser, optimisticAssistant])

      const response = await fetch(`/api/conversations/${activeConversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, scope }),
        signal: controller.signal,
      })
      if (!response.ok || !response.body) {
        const detail = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(detail?.detail ?? '답변 요청에 실패했습니다.')
      }

      const reader = response.body.getReader()
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
          const event = JSON.parse(line.slice(6)) as StreamEvent
          if (event.type === 'status' && event.stage) {
            setStage(event.stage)
          } else if (event.type === 'delta' && event.content) {
            setStage(null)
            replaceLastAssistant(message => ({
              ...message,
              content: message.content + event.content,
            }))
          } else if (event.type === 'complete' && event.message) {
            setStage(null)
            replaceLastAssistant(() => event.message!)
            if (event.conversation) onConversationChanged(event.conversation)
          } else if (event.type === 'error') {
            setStage(null)
            replaceLastAssistant(message => event.message ?? {
              ...message,
              content: `오류: ${event.error ?? '답변 생성 실패'}`,
              status: 'error',
            })
            if (event.conversation) onConversationChanged(event.conversation)
          }
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        replaceLastAssistant(current => ({ ...current, status: 'interrupted' }))
      } else {
        const message = error instanceof Error ? error.message : '네트워크 오류가 발생했습니다.'
        replaceLastAssistant(current => ({
          ...current,
          content: current.content || `오류: ${message}`,
          status: 'error',
        }))
      }
    } finally {
      abortControllerRef.current = null
      setIsLoading(false)
      setStage(null)
      onBusyChange(false)
    }
  }

  const handleStop = () => {
    abortControllerRef.current?.abort()
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      void handleSend()
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-5 py-3">
        <span className="text-xs text-muted">범위</span>
        <div className="relative">
          <select
            value={scope}
            onChange={event => setScope(event.target.value)}
            disabled={isLoading || isHistoryLoading}
            className="appearance-none bg-surface-2 text-xs text-white rounded-md pl-3 pr-7 py-1.5 focus:outline-none cursor-pointer disabled:opacity-50"
          >
            {scopeOptions.map(option => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
          <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted pointer-events-none" />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-6 space-y-4">
        {isHistoryLoading ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-muted text-sm">대화 기록을 불러오는 중...</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-muted text-sm">로컬 자료에 대해 질문하세요</p>
          </div>
        ) : null}

        {!isHistoryLoading && messages.map((message, index) => (
          <div
            key={message.id ?? `${message.role}-${index}`}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            {message.role === 'user' ? (
              <div className="max-w-[72%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-accent text-white text-sm leading-relaxed whitespace-pre-wrap">
                {message.content}
              </div>
            ) : (
              <div className="max-w-[80%] space-y-2">
                <div className="px-4 py-3 rounded-2xl rounded-bl-sm bg-surface-2 text-sm text-[#e5e7eb]">
                  {message.content ? (
                    <div className="md">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                    </div>
                  ) : message.status === 'streaming' ? (
                    <span className="flex items-center gap-2 text-muted">
                      <span className="inline-block w-1.5 h-4 bg-accent animate-pulse rounded-sm" />
                      {index === messages.length - 1 && stage && (
                        <span className="text-xs">{STAGE_LABEL[stage]}</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted">응답 내용이 없습니다.</span>
                  )}
                  {message.status === 'interrupted' && (
                    <p className="mt-2 text-xs text-amber-400">응답 생성이 중단되었습니다.</p>
                  )}
                  {message.status === 'error' && (
                    <p className="mt-2 text-xs text-red-400">답변 생성 중 오류가 발생했습니다.</p>
                  )}
                </div>
                {message.sources.length > 0 && (
                  <div className="px-4 py-2.5 rounded-xl bg-surface-2">
                    <p className="text-xs text-muted mb-1 font-medium">출처</p>
                    <pre className="text-xs text-muted whitespace-pre-wrap font-sans leading-relaxed">
                      {message.sources.map(formatSource).join('\n')}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="px-5 py-4">
        <div className="flex items-center gap-3 bg-surface-2 rounded-2xl px-4 py-2.5">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={event => { setInput(event.target.value); adjustHeight() }}
            onKeyDown={handleKeyDown}
            disabled={isHistoryLoading}
            placeholder="질문을 입력하세요  (Shift+Enter로 줄바꿈)"
            rows={1}
            className="flex-1 bg-transparent text-sm text-white placeholder-muted resize-none outline-none disabled:opacity-50"
            style={{ maxHeight: '160px', padding: 0, lineHeight: '1.5' }}
          />
          {isLoading ? (
            <button
              onClick={handleStop}
              title="응답 생성 중단"
              className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-xl bg-surface-3 hover:bg-red-500/80 transition-colors"
            >
              <Square size={12} className="text-white" fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={() => void handleSend()}
              disabled={!input.trim() || isHistoryLoading}
              className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={14} className="text-white" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

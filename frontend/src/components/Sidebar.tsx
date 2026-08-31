import { useState } from 'react'
import { MessageCircle, FileText, Plus, RefreshCw, Trash2, Zap } from 'lucide-react'
import type { Conversation, Page, Status } from '../types'

interface Props {
  page: Page
  setPage: (p: Page) => void
  status: Status | null
  onReindex: () => Promise<unknown>
  conversations: Conversation[]
  selectedConversationId: string | null
  chatBusy: boolean
  onNewConversation: () => void
  onSelectConversation: (id: string) => void
  onDeleteConversation: (id: string) => Promise<void>
}

export default function Sidebar({
  page,
  setPage,
  status,
  onReindex,
  conversations,
  selectedConversationId,
  chatBusy,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
}: Props) {
  const [reindexing, setReindexing] = useState(false)
  const [reindexMsg, setReindexMsg] = useState('')

  const handleReindex = async () => {
    setReindexing(true)
    setReindexMsg('')
    try {
      const data = await onReindex() as {
        updated_files: number
        total_chunks: number
        rebuilt: boolean
      }
      setReindexMsg(
        `완료: 업데이트 ${data.updated_files}개, 청크 ${data.total_chunks}개${data.rebuilt ? ' (전체 재구축)' : ''}`
      )
    } catch {
      setReindexMsg('인덱싱 실패')
    } finally {
      setReindexing(false)
    }
  }

  const navItem = (id: Page, icon: React.ReactNode, label: string) => (
    <button
      onClick={() => { if (!chatBusy) setPage(id) }}
      disabled={chatBusy}
      className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
        page === id
          ? 'bg-accent/10 text-accent'
          : 'text-muted hover:text-white hover:bg-surface-3'
      } disabled:opacity-50`}
    >
      {icon}
      {label}
    </button>
  )

  return (
    <aside className="w-60 flex-shrink-0 flex flex-col bg-surface-2 h-full">
      {/* Logo */}
      <div className="px-5 py-5 flex items-center gap-2">
        <Zap size={16} className="text-accent fill-accent" />
        <span className="text-sm font-semibold text-white tracking-tight">Zeus</span>
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-1 px-3">
        {navItem('chat', <MessageCircle size={15} />, '대화')}
        {navItem('save-note', <FileText size={15} />, '노트 저장')}
      </nav>

      <div className="px-3 pt-4 flex-1 min-h-0 flex flex-col">
        <button
          onClick={onNewConversation}
          disabled={chatBusy}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs text-muted hover:text-white hover:bg-surface-3 transition-colors disabled:opacity-40"
        >
          <Plus size={13} />
          새 대화
        </button>
        <div className="mt-2 overflow-y-auto space-y-1">
          {conversations.map(conversation => (
            <div
              key={conversation.id}
              className={`group flex items-center gap-1 w-full pl-3 pr-1 rounded-lg transition-colors ${
                page === 'chat' && selectedConversationId === conversation.id
                  ? 'bg-surface-3 text-white'
                  : 'text-muted hover:text-white hover:bg-surface-3'
              } ${chatBusy ? 'opacity-50' : ''}`}
            >
              <button
                onClick={() => onSelectConversation(conversation.id)}
                disabled={chatBusy}
                className="flex-1 min-w-0 py-2 text-left disabled:cursor-default"
              >
                <span className="block truncate text-xs">{conversation.title}</span>
              </button>
              <button
                disabled={chatBusy}
                aria-label={`${conversation.title} 삭제`}
                onClick={event => {
                  event.stopPropagation()
                  void onDeleteConversation(conversation.id)
                }}
                className="p-1.5 rounded opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-black/20 disabled:cursor-default"
              >
                <Trash2 size={11} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Status */}
      <div className="p-4 space-y-3">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <span
              className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                status?.ollama_ok ? 'bg-emerald-500' : 'bg-red-500'
              }`}
            />
            <span className="text-xs text-muted truncate">
              {status?.ollama_ok ? 'Ollama 연결됨' : 'Ollama 연결 안 됨'}
            </span>
          </div>
          {status && (
            <div className="text-xs text-muted pl-3.5 space-y-0.5">
              <div>{status.chat_model}</div>
              <div>문서 {status.document_count}개 · 청크 {status.chunk_count}개</div>
            </div>
          )}
        </div>

        <button
          onClick={handleReindex}
          disabled={reindexing}
          className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs text-muted hover:text-white hover:bg-surface-3 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={12} className={reindexing ? 'animate-spin' : ''} />
          {reindexing ? '인덱싱 중...' : 'Reindex'}
        </button>

        {reindexMsg && (
          <p className="text-xs text-muted leading-relaxed">{reindexMsg}</p>
        )}
      </div>
    </aside>
  )
}

import { useState } from 'react'
import { MessageCircle, FileText, RefreshCw, Zap } from 'lucide-react'
import type { Page, Status } from '../types'

interface Props {
  page: Page
  setPage: (p: Page) => void
  status: Status | null
  onReindex: () => Promise<unknown>
}

export default function Sidebar({ page, setPage, status, onReindex }: Props) {
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
      onClick={() => setPage(id)}
      className={`flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
        page === id
          ? 'bg-accent/10 text-accent'
          : 'text-muted hover:text-white hover:bg-surface-3'
      }`}
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
      <nav className="flex flex-col gap-1 p-3 flex-1">
        {navItem('chat', <MessageCircle size={15} />, '대화')}
        {navItem('save-note', <FileText size={15} />, '노트 저장')}
      </nav>

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

import { useState, useEffect } from 'react'
import type { Conversation, Page, Status } from './types'
import Sidebar from './components/Sidebar'
import Chat from './components/Chat'
import SaveNote from './components/SaveNote'

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [status, setStatus] = useState<Status | null>(null)
  const [scopeOptions, setScopeOptions] = useState<string[]>([])
  const [defaultFolder, setDefaultFolder] = useState('')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null)
  const [chatBusy, setChatBusy] = useState(false)

  const refreshStatus = () =>
    fetch('/api/status')
      .then(r => r.json())
      .then(setStatus)
      .catch(() => null)

  useEffect(() => {
    refreshStatus()
    fetch('/api/config')
      .then(r => r.json())
      .then(cfg => {
        setScopeOptions(cfg.scope_options ?? [])
        setDefaultFolder(cfg.default_note_folder ?? '')
      })
      .catch(() => null)

    fetch('/api/conversations')
      .then(r => r.json())
      .then((items: Conversation[]) => {
        setConversations(items)
        setSelectedConversationId(current => current ?? items[0]?.id ?? null)
      })
      .catch(() => null)
  }, [])

  const handleConversationChanged = (conversation: Conversation) => {
    setConversations(current =>
      [conversation, ...current.filter(item => item.id !== conversation.id)]
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    )
    setSelectedConversationId(conversation.id)
  }

  const handleNewConversation = () => {
    if (chatBusy) return
    setPage('chat')
    setSelectedConversationId(null)
  }

  const handleSelectConversation = (id: string) => {
    if (chatBusy) return
    setPage('chat')
    setSelectedConversationId(id)
  }

  const handleDeleteConversation = async (id: string) => {
    if (chatBusy) return
    const conversation = conversations.find(item => item.id === id)
    if (!window.confirm(`“${conversation?.title ?? '이 대화'}”를 영구 삭제할까요?`)) return

    const response = await fetch(`/api/conversations/${id}`, { method: 'DELETE' })
    if (!response.ok) return
    const remaining = conversations.filter(item => item.id !== id)
    setConversations(remaining)
    if (selectedConversationId === id) {
      setSelectedConversationId(remaining[0]?.id ?? null)
    }
  }

  const handleReindex = async () => {
    const res = await fetch('/api/reindex', { method: 'POST' })
    const data = await res.json()
    if (data.status) setStatus(data.status)
    return data
  }

  return (
    <div className="flex h-full">
      <Sidebar
        page={page}
        setPage={setPage}
        status={status}
        onReindex={handleReindex}
        conversations={conversations}
        selectedConversationId={selectedConversationId}
        chatBusy={chatBusy}
        onNewConversation={handleNewConversation}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={handleDeleteConversation}
      />
      <main className="flex-1 flex flex-col overflow-hidden">
        {page === 'chat' ? (
          <Chat
            scopeOptions={scopeOptions}
            conversationId={selectedConversationId}
            onConversationChanged={handleConversationChanged}
            onBusyChange={setChatBusy}
          />
        ) : (
          <SaveNote defaultFolder={defaultFolder} onSaved={refreshStatus} />
        )}
      </main>
    </div>
  )
}

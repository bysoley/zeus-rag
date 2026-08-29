import { useState, useEffect } from 'react'
import type { Page, Status } from './types'
import Sidebar from './components/Sidebar'
import Chat from './components/Chat'
import SaveNote from './components/SaveNote'

export default function App() {
  const [page, setPage] = useState<Page>('chat')
  const [status, setStatus] = useState<Status | null>(null)
  const [scopeOptions, setScopeOptions] = useState<string[]>([])
  const [defaultFolder, setDefaultFolder] = useState('')

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
  }, [])

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
      />
      <main className="flex-1 flex flex-col overflow-hidden">
        {page === 'chat' ? (
          <Chat scopeOptions={scopeOptions} />
        ) : (
          <SaveNote defaultFolder={defaultFolder} onSaved={refreshStatus} />
        )}
      </main>
    </div>
  )
}

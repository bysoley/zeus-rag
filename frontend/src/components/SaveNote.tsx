import { useState } from 'react'
import { CheckCircle, XCircle } from 'lucide-react'

interface Props {
  defaultFolder: string
  onSaved: () => void
}

export default function SaveNote({ defaultFolder, onSaved }: Props) {
  const [title, setTitle] = useState('')
  const [folder, setFolder] = useState(defaultFolder)
  const [tags, setTags] = useState('')
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)

  const handleSave = async () => {
    if (!title.trim() || !body.trim()) {
      setResult({ success: false, message: '제목과 본문은 필수입니다.' })
      return
    }
    setSaving(true)
    setResult(null)
    try {
      const res = await fetch('/api/save-note', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, folder: folder || defaultFolder, tags, body }),
      })
      const data = await res.json() as { success: boolean; message: string }
      setResult(data)
      if (data.success) {
        setTitle('')
        setTags('')
        setBody('')
        onSaved()
      }
    } catch {
      setResult({ success: false, message: '네트워크 오류가 발생했습니다.' })
    } finally {
      setSaving(false)
    }
  }

  const field = (
    label: string,
    node: React.ReactNode,
  ) => (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-muted">{label}</label>
      {node}
    </div>
  )

  const inputCls =
    'w-full bg-surface-2 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-muted outline-none'

  return (
    <div className="flex-1 overflow-y-auto px-8 py-8 max-w-2xl mx-auto w-full">
      <h2 className="text-base font-semibold mb-6">노트 저장</h2>

      <div className="space-y-4">
        {field(
          '제목 *',
          <input
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="노트 제목"
            className={inputCls}
          />,
        )}

        {field(
          '저장 폴더',
          <input
            value={folder}
            onChange={e => setFolder(e.target.value)}
            placeholder={defaultFolder}
            className={inputCls}
          />,
        )}

        {field(
          '태그 (쉼표로 구분)',
          <input
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="tag1, tag2, tag3"
            className={inputCls}
          />,
        )}

        {field(
          '본문 *',
          <textarea
            value={body}
            onChange={e => setBody(e.target.value)}
            placeholder="노트 내용을 입력하세요..."
            rows={12}
            className={`${inputCls} resize-none leading-relaxed`}
          />,
        )}

        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full py-2.5 rounded-xl bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium text-white transition-colors"
        >
          {saving ? '저장 중...' : '저장'}
        </button>

        {result && (
          <div
            className={`flex gap-2.5 p-3.5 rounded-xl text-sm ${
              result.success
                ? 'bg-emerald-950/40 border border-emerald-800/40 text-emerald-300'
                : 'bg-red-950/40 border border-red-800/40 text-red-300'
            }`}
          >
            {result.success ? <CheckCircle size={16} className="flex-shrink-0 mt-0.5" /> : <XCircle size={16} className="flex-shrink-0 mt-0.5" />}
            <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed">
              {result.message}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

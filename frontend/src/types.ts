export type Page = 'chat' | 'save-note'

export interface Status {
  ollama_ok: boolean
  chat_model: string
  embed_model: string
  document_count: number
  chunk_count: number
  last_indexed_at: string | null
  source_counts: Record<string, number>
}

export interface Message {
  id?: number
  conversation_id?: string
  role: 'user' | 'assistant'
  content: string
  scope?: string | null
  sources: SourceRef[]
  status: 'streaming' | 'complete' | 'error' | 'interrupted'
  created_at?: string
}

export interface SourceRef {
  label: string
  source_id: string
  relative_path: string
  similarity: number
  heading?: string | null
  start_line?: number | null
  end_line?: number | null
  provider?: string | null
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

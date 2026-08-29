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
  role: 'user' | 'assistant'
  content: string
  sources?: string
  error?: boolean
}

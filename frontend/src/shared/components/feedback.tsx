/** Operation result feedback (toast). Messages must come from real API results. */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

export interface FeedbackItem {
  id: number
  kind: 'success' | 'error'
  message: string
}

interface FeedbackContextValue {
  notify: (kind: FeedbackItem['kind'], message: string) => void
}

const FeedbackContext = createContext<FeedbackContextValue | null>(null)

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<FeedbackItem[]>([])
  const nextId = useRef(1)

  const notify = useCallback((kind: FeedbackItem['kind'], message: string) => {
    const id = nextId.current++
    setItems((current) => [...current, { id, kind, message }])
    window.setTimeout(() => {
      setItems((current) => current.filter((item) => item.id !== id))
    }, 4000)
  }, [])

  const value = useMemo(() => ({ notify }), [notify])

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div className="toast-host" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast toast-${item.kind}`} role={item.kind === 'error' ? 'alert' : 'status'}>
            {item.message}
          </div>
        ))}
      </div>
    </FeedbackContext.Provider>
  )
}

/** Show the result of a user-triggered operation. Never fabricate success —
 * pass the message from the API response (or its error envelope). */
export function useFeedback(): FeedbackContextValue {
  const ctx = useContext(FeedbackContext)
  if (!ctx) throw new Error('useFeedback must be used within FeedbackProvider')
  return ctx
}

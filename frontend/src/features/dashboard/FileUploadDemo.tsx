/** File upload component: authorize -> direct upload -> register (task 2.9).
 *
 * Shows upload progress and the failure reason of each stage; a lost
 * registration response can be retried safely (the backend replays the
 * same stored object). The page never holds long-term storage credentials -
 * only the short-term presigned URL from the API.
 */

import { useCallback, useRef, useState } from 'react'

import { filesApi, uploadToPresignedUrl } from '../../shared/api/files'
import type { StoredObjectOut } from '../../shared/api/types'

export type UploadPhase = 'idle' | 'granting' | 'uploading' | 'registering' | 'done' | 'failed'

interface Props {
  onRegistered?: (stored: StoredObjectOut) => void
}

const PHASE_LABELS: Record<UploadPhase, string> = {
  idle: '未开始',
  granting: '正在申请上传授权…',
  uploading: '直传中…',
  registering: '正在登记…',
  done: '登记完成',
  failed: '失败',
}

export function FileUploadDemo({ onRegistered }: Props) {
  const [phase, setPhase] = useState<UploadPhase>('idle')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [stored, setStored] = useState<StoredObjectOut | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const inFlight = useRef<{ grantId: string; file: File } | null>(null)

  const register = useCallback(
    async (grantId: string, target: File) => {
      setPhase('registering')
      setError(null)
      const sha256 = await digest(target)
      try {
        const result = await filesApi.completeUpload(grantId, sha256)
        setStored(result)
        setPhase('done')
        onRegistered?.(result)
      } catch (cause) {
        setPhase('failed')
        setError(cause instanceof Error ? cause.message : '登记失败')
        // Keep the grant around so the retry can replay the same registration.
        inFlight.current = { grantId, file: target }
      }
    },
    [onRegistered],
  )

  const reset = useCallback(() => {
    setPhase('idle')
    setProgress(0)
    setError(null)
    setStored(null)
    inFlight.current = null
  }, [])

  const start = useCallback(async () => {
    if (!file) return
    setError(null)
    setStored(null)
    setPhase('granting')
    try {
      const grant = await filesApi.requestGrant({
        filename: file.name,
        contentType: file.type || 'application/octet-stream',
        sizeBytes: file.size,
        idempotencyKey: crypto.randomUUID(),
      })
      inFlight.current = { grantId: grant.id, file }
      setPhase('uploading')
      await uploadToPresignedUrl(grant.upload_url as string, file, setProgress)
      await register(grant.id, file)
    } catch (cause) {
      setPhase('failed')
      setError(cause instanceof Error ? cause.message : '上传失败')
    }
  }, [file, register])

  const retryRegistration = useCallback(async () => {
    const pending = inFlight.current
    if (!pending) return
    await register(pending.grantId, pending.file)
  }, [register])

  const busy = phase === 'uploading' || phase === 'granting' || phase === 'registering'

  return (
    <section className="upload-card" aria-label="文件上传演示">
      <input
        type="file"
        aria-label="选择文件"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        disabled={busy}
      />
      <button type="button" className="primary-button" onClick={() => void start()} disabled={!file || busy}>
        上传
      </button>
      {phase === 'failed' && inFlight.current && (
        <button type="button" className="ghost-button" onClick={() => void retryRegistration()}>
          重试登记
        </button>
      )}
      {(phase === 'failed' || phase === 'done') && (
        <button type="button" className="ghost-button" onClick={reset}>
          重置
        </button>
      )}

      <p data-phase={phase}>{PHASE_LABELS[phase]}</p>
      {busy && (
        <progress value={progress} max={100} aria-label="上传进度">
          {progress}%
        </progress>
      )}
      {error && (
        <p role="alert" className="upload-error">
          {error}
        </p>
      )}
      {stored && (
        <p className="upload-result">
          文件已登记：{stored.id}（{stored.object_key}，{stored.size_bytes} 字节）
        </p>
      )}
    </section>
  )
}

/** SHA-256 via the standard Web Crypto API (available in browsers). */
async function digest(file: Blob): Promise<string> {
  const buffer = await file.arrayBuffer()
  const hash = await crypto.subtle.digest('SHA-256', buffer)
  return Array.from(new Uint8Array(hash))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

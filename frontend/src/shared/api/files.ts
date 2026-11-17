/** File upload authorization / completion API calls (task 2.9). */

import { apiRequest } from './client'
import type { StoredObjectOut, UploadGrantOut } from './types'

export interface UploadGrantParams {
  filename: string
  contentType: string
  sizeBytes: number
  /** Optional Idempotency-Key for safe retries of the grant request. */
  idempotencyKey?: string
}

export const filesApi = {
  requestGrant: ({ filename, contentType, sizeBytes, idempotencyKey }: UploadGrantParams) => {
    const headers: Record<string, string> = {}
    if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey
    return apiRequest<UploadGrantOut>('/files/upload-grants', {
      method: 'POST',
      body: { filename, content_type: contentType, size_bytes: sizeBytes },
      headers,
    })
  },

  completeUpload: (grantId: string, sha256: string) =>
    apiRequest<StoredObjectOut>(`/files/upload-grants/${grantId}/complete`, {
      method: 'POST',
      body: { sha256 },
    }),
}

/** PUT bytes to the presigned URL with progress reporting (task 2.9).
 * XHR is used because fetch cannot report upload progress. */
export function uploadToPresignedUrl(
  url: string,
  file: Blob,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url)
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    })
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve()
      } else {
        reject(new Error(`直传失败（HTTP ${xhr.status}）`))
      }
    })
    xhr.addEventListener('error', () => reject(new Error('直传失败：网络错误')))
    xhr.addEventListener('abort', () => reject(new Error('直传已取消')))
    if (signal) {
      signal.addEventListener('abort', () => xhr.abort())
    }
    xhr.send(file)
  })
}

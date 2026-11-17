/** Demo page for async job polling (task 2.8).
 *
 * Reads `?job=<id>` from the URL so a refresh restores the polling state;
 * shows stage/progress/failure/cancel states and stops on terminal status.
 */

import { useState } from 'react'

import { useHashRoute } from '../../app/router'
import { JOB_TERMINAL_STATUSES, useJobPolling } from '../../shared/components/useJobPolling'
import { useUrlQuery } from '../../shared/components/useUrlQuery'

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export function JobPollingDemoPage() {
  const route = useHashRoute()
  const patchQuery = useUrlQuery(route.path, route.query)
  const jobIdFromUrl = route.query.get('job')
  const [draft, setDraft] = useState(jobIdFromUrl ?? '')

  const { job, error, refreshing, cancel, refresh } = useJobPolling({ jobId: jobIdFromUrl })
  const terminal = job ? JOB_TERMINAL_STATUSES.includes(job.status) : false

  return (
    <section className="list-page" aria-label="任务轮询演示">
      <h1>任务轮询演示</h1>
      <p className="list-page-note">
        输入任务 ID 轮询其状态（写入 URL，刷新后按任务 ID 恢复）。任务到达终态后停止轮询。
      </p>

      <form
        className="list-filters"
        onSubmit={(event) => {
          event.preventDefault()
          patchQuery({ job: draft.trim() || null })
        }}
      >
        <input
          type="search"
          aria-label="任务 ID"
          placeholder="粘贴 async_job_id"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button type="submit" className="primary-button">
          开始轮询
        </button>
        {jobIdFromUrl && (
          <button type="button" className="ghost-button" onClick={() => patchQuery({ job: null })}>
            停止
          </button>
        )}
      </form>

      {!jobIdFromUrl && <p className="list-state">未选择任务</p>}

      {jobIdFromUrl && refreshing && !job && <p className="list-state">加载任务状态…</p>}

      {jobIdFromUrl && error && (
        <div className="list-state" role="alert" data-state="error">
          <p>{error}</p>
          <button type="button" className="ghost-button" onClick={refresh}>
            重试
          </button>
        </div>
      )}

      {job && (
        <div className="job-card" data-status={job.status}>
          <p>
            <strong>{job.job_type}</strong> · {STATUS_LABELS[job.status] ?? job.status}
            {job.stage ? ` · 阶段：${job.stage}` : ''}
          </p>
          <progress value={job.progress} max={100} aria-label="进度">
            {job.progress}%
          </progress>
          {job.last_error && (
            <p role="alert" className="job-error">
              失败原因：{job.last_error}
            </p>
          )}
          <p className="job-meta">
            重试次数：{job.attempts} · 开始：{job.started_at ?? '—'} · 结束：{job.finished_at ?? '—'}
          </p>
          <button
            type="button"
            className="ghost-button"
            disabled={terminal}
            onClick={() => void cancel()}
          >
            取消任务
          </button>
        </div>
      )}
    </section>
  )
}

/** Dashboard landing: module pending state plus the conventions demo entry. */

import type { ModuleDef } from '../../app/modules'
import { navigate } from '../../app/router'
import { Placeholder } from '../Placeholder'

export function DashboardHome({ module }: { module: ModuleDef }) {
  return (
    <>
      <Placeholder module={module} />
      <p className="demo-entry">
        <button type="button" className="ghost-button" onClick={() => navigate('/dashboard/components-demo')}>
          打开共享列表组件演示（分页 / 筛选 / 四类状态）
        </button>
        <button type="button" className="ghost-button" onClick={() => navigate('/dashboard/job-demo')}>
          打开任务轮询演示（进度 / 失败 / 取消）
        </button>
        <button type="button" className="ghost-button" onClick={() => navigate('/dashboard/upload-demo')}>
          打开文件上传演示（授权 / 直传 / 登记）
        </button>
      </p>
    </>
  )
}

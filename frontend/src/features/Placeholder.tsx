/** Explicit "待接入" state for modules whose real integration is pending. */

import type { ModuleDef } from '../app/modules'

export function Placeholder({ module }: { module: ModuleDef }) {
  return (
    <section className="placeholder" data-module={module.key}>
      <div className="placeholder-badge">待接入</div>
      <h1>{module.label}</h1>
      <p className="placeholder-text">{module.description}</p>
      <p className="placeholder-note">
        该模块为产品原型页，真实数据与操作将在对应实施阶段接入。当前不展示任何模拟业务结果。
      </p>
    </section>
  )
}

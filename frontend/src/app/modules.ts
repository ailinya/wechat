/** The eight top-level modules and their required read permissions. */

import type { PermissionCode } from '../shared/api/types'

export interface ModuleDef {
  key: string
  label: string
  path: string
  permission: PermissionCode | null
  description: string
}

export const MODULES: ModuleDef[] = [
  {
    key: 'dashboard',
    label: '工作台',
    path: '/dashboard',
    permission: null,
    description: '运营概览、任务动态与待办提醒',
  },
  {
    key: 'collection',
    label: '采集管理',
    path: '/collection',
    permission: 'collection:read',
    description: '来源与采集任务配置、执行与结果管理',
  },
  {
    key: 'creation',
    label: '智能创作',
    path: '/creation',
    permission: 'creation:read',
    description: '创作规则、素材分析与文章生成',
  },
  {
    key: 'content',
    label: '内容管理',
    path: '/content',
    permission: 'article:read',
    description: '文章编辑、排版、审核与发布',
  },
  {
    key: 'materials',
    label: '素材库',
    path: '/materials',
    permission: 'material:read',
    description: '素材存储、分类标签、检索与复用',
  },
  {
    key: 'analytics',
    label: '数据统计分析',
    path: '/analytics',
    permission: 'analytics:read',
    description: '采集、创作、审核、发布与账号指标',
  },
  {
    key: 'accounts',
    label: '账号管理',
    path: '/accounts',
    permission: 'account:read',
    description: '公众号授权、能力检测与素材同步',
  },
  {
    key: 'settings',
    label: '系统设置',
    path: '/settings',
    permission: 'settings:read',
    description: '平台配置、用户角色、通知与日志',
  },
]

export function moduleByPath(path: string): ModuleDef | undefined {
  return MODULES.find((module) => path === module.path || path.startsWith(`${module.path}/`))
}

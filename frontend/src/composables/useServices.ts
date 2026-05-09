import { ref } from 'vue'
import { servicesApi } from '@/lib/api'
import type { Service } from '@/types/task'

// G3：服务列表 composable。模块级 ref 共享 cache，4 个 caller（ServicePicker /
// ServicePanelsTab / TracePanelsTab / RuntimeStatusPanel）任何一个先 mount 触发
// 拉取，其他组件直接复用 cache。
//
// reactivity：services 是 ref，模板里 getByName(name) 会跟着 services.value 变更
// 自动 re-render（Vue 自动 tracking）。
//
// 失败兜底：API 不可达 / 后端没建 Service 行 → services.value 留空，组件渲染"未
// 配置"占位文案。

const services = ref<Service[]>([])
const loading = ref(false)
let initialized = false
let pending: Promise<void> | null = null

export function useServices() {
  if (!initialized && !pending) {
    loading.value = true
    pending = (async () => {
      try {
        services.value = await servicesApi.list()
        initialized = true
      } catch {
        // 静默：service 表空 / 接口不可达 → services.value 保持空
      } finally {
        loading.value = false
        pending = null
      }
    })()
  }

  function getByName(name: string): Service | null {
    return services.value.find((s) => s.name === name) || null
  }

  /** 强制刷新，admin 改了 Service 数据后调用 */
  async function refresh() {
    loading.value = true
    try {
      services.value = await servicesApi.list()
      initialized = true
    } finally {
      loading.value = false
    }
  }

  return { services, loading, getByName, refresh }
}

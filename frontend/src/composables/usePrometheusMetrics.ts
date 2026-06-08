// 拉某服务在指定时间窗的 Prometheus 容器指标（per-pod cpu/mem + 聚合 net/disk）。
// 从 ServicePanelsTab 的取数逻辑抽核心，供服务诊断页 Pod 时序面板复用。
import { ref } from 'vue'
import { prometheusSourcesApi, runsApi } from '@/lib/api'
import type { PrometheusMetricsResponse } from '@/types/task'

// 诊断页 Pod 时序需要的 metric：cpu/mem 有 per-pod，net/disk 仅聚合
const NEEDED = 'cpu_usage_by_pod,memory_usage_by_pod,network_rx,network_tx,disk_read,disk_write'

export function usePrometheusMetrics() {
  const data = ref<PrometheusMetricsResponse | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(
    sourceId: number | null | undefined,
    service: string,
    startSec: number,
    endSec: number,
  ) {
    if (!sourceId || !service || !(endSec > startSec)) {
      data.value = null
      return
    }
    loading.value = true
    error.value = ''
    try {
      const step = Math.max(15, Math.floor((endSec - startSec) / 240))
      data.value = await prometheusSourcesApi.metrics(sourceId, {
        service, start: startSec, end: endSec, step: `${step}s`, metrics: NEEDED,
      })
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      data.value = null
    } finally {
      loading.value = false
    }
  }

  // 本次压测（run 窗口）：终态走 run 级快照端点（DB 秒开，读不到后端自动回退实时）
  async function loadRunSnapshot(runId: string, service: string) {
    if (!runId || !service) { data.value = null; return }
    loading.value = true
    error.value = ''
    try {
      data.value = await runsApi.serviceMetrics(runId, service)
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      data.value = null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, load, loadRunSnapshot }
}

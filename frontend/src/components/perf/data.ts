import { BookOpen, Atom, GitBranch } from 'lucide-vue-next'

export const SPRING = { stiffness: 150, damping: 18 }
export const P99_THRESHOLD = 80

export const BIZ = [
  { id: 'shared', label: '共享课', sub: 'Shared Courses', icon: BookOpen, color: '#60a5fa' },
  { id: 'ai', label: 'AI 事业中心', sub: 'AI Center', icon: Atom, color: '#a78bfa' },
  { id: 'kg', label: 'KG 知识图谱', sub: 'Knowledge Graph', icon: GitBranch, color: '#34d399' },
]

export interface Person {
  name: string
  role: string
  avatar: string
  color: string
  progress: number
  status: 'running' | 'analyzing'
}

export const PEOPLE: Person[] = [
  { name: '张明', role: '架构师', avatar: 'ZM', color: '#3b82f6', progress: 0.72, status: 'running' },
  { name: '李薇', role: '测试主管', avatar: 'LW', color: '#8b5cf6', progress: 0.45, status: 'analyzing' },
  { name: '王浩', role: 'SRE', avatar: 'WH', color: '#10b981', progress: 0.91, status: 'running' },
  { name: '陈芳', role: '开发', avatar: 'CF', color: '#f59e0b', progress: 0.33, status: 'analyzing' },
  { name: '赵强', role: 'QA', avatar: 'ZQ', color: '#ec4899', progress: 0.68, status: 'running' },
]

// Visual schema for ChronosNerve / MetricsColumn / TemporalColumn.
// Both mock data and real API tasks (mapped) feed this shape.
export type StreamTaskStatus = 'success' | 'fail' | 'running' | 'draft' | 'configured'

export interface Task {
  id: string                      // 显示用编号 "TSK-001"
  dbId?: number                   // 真实数据库 id（mock 数据没有）
  title: string
  status: StreamTaskStatus
  time: string
  date: number
  duration: string
  owner: string
  rps: number
  p99: number
  errorRate: number
  vuser: number
  phases: { prep: number; exec: number; analysis: number }
  rpsWave: number[]
  biz: string
  color: string
}

export const TASKS: Task[] = [
  { id: 'TSK-2048', title: 'Gateway 高并发压测', status: 'running', time: '14:23', date: 11, duration: '15m32s', owner: '张明', rps: 12480, p99: 23.4, errorRate: 0.03, vuser: 500, phases: { prep: 2, exec: 12, analysis: 1.5 }, rpsWave: [4200, 6800, 9100, 11200, 12480, 12100, 12480, 11900, 12300, 12480], biz: 'shared', color: '#3b82f6' },
  { id: 'TSK-2047', title: '用户服务 Soak Test', status: 'fail', time: '11:05', date: 11, duration: '32m10s', owner: '李薇', rps: 8920, p99: 187.2, errorRate: 4.72, vuser: 200, phases: { prep: 5, exec: 25, analysis: 2.2 }, rpsWave: [3100, 5600, 7800, 8900, 8920, 6200, 4100, 3800, 5200, 8920], biz: 'ai', color: '#f97316' },
  { id: 'TSK-2046', title: '订单链路 Spike Test', status: 'success', time: '10:30', date: 11, duration: '8m45s', owner: '王浩', rps: 18340, p99: 15.8, errorRate: 0.01, vuser: 1000, phases: { prep: 1, exec: 7, analysis: 0.75 }, rpsWave: [2000, 8000, 14000, 18340, 18000, 17800, 18340, 18100, 18200, 18340], biz: 'kg', color: '#22c55e' },
  { id: 'TSK-2045', title: '支付网关 Endurance', status: 'success', time: '09:15', date: 10, duration: '1h02m', owner: '陈芳', rps: 6750, p99: 32.1, errorRate: 0.12, vuser: 150, phases: { prep: 3, exec: 55, analysis: 4 }, rpsWave: [2800, 4500, 5900, 6300, 6750, 6600, 6750, 6700, 6720, 6750], biz: 'shared', color: '#8b5cf6' },
  { id: 'TSK-2044', title: '搜索服务 Capacity', status: 'success', time: '08:40', date: 10, duration: '22m15s', owner: '赵强', rps: 9200, p99: 28.5, errorRate: 0.08, vuser: 300, phases: { prep: 2, exec: 18, analysis: 2.25 }, rpsWave: [3800, 5200, 7100, 8400, 9200, 9000, 9200, 9100, 9150, 9200], biz: 'kg', color: '#10b981' },
  { id: 'TSK-2043', title: '推荐引擎 Baseline', status: 'running', time: '08:00', date: 9, duration: '45m', owner: '张明', rps: 5600, p99: 42.3, errorRate: 0.21, vuser: 120, phases: { prep: 4, exec: 35, analysis: 6 }, rpsWave: [1200, 2800, 4100, 5000, 5600, 5400, 5600, 5500, 5580, 5600], biz: 'ai', color: '#3b82f6' },
  { id: 'TSK-2042', title: '图谱查询 Stress', status: 'success', time: '07:20', date: 9, duration: '18m30s', owner: '王浩', rps: 14200, p99: 19.7, errorRate: 0.02, vuser: 600, phases: { prep: 1.5, exec: 15, analysis: 2 }, rpsWave: [5000, 8200, 11000, 13500, 14200, 14000, 14200, 14100, 14150, 14200], biz: 'kg', color: '#22c55e' },
  { id: 'TSK-2041', title: '消息队列 Peak Load', status: 'running', time: '15:10', date: 11, duration: '28m', owner: '赵强', rps: 22100, p99: 18.3, errorRate: 0.05, vuser: 800, phases: { prep: 3, exec: 22, analysis: 3 }, rpsWave: [6000, 10200, 15800, 19500, 22100, 21800, 22100, 21600, 22000, 22100], biz: 'shared', color: '#3b82f6' },
  { id: 'TSK-2040', title: '认证服务 Chaos Test', status: 'fail', time: '13:45', date: 11, duration: '12m20s', owner: '张明', rps: 4300, p99: 245.6, errorRate: 8.91, vuser: 100, phases: { prep: 1, exec: 10, analysis: 1.3 }, rpsWave: [2000, 3500, 4300, 4100, 2800, 1500, 900, 1200, 3200, 4300], biz: 'ai', color: '#f97316' },
  { id: 'TSK-2039', title: '文件存储 Throughput', status: 'success', time: '16:00', date: 10, duration: '35m', owner: '李薇', rps: 7800, p99: 45.2, errorRate: 0.15, vuser: 250, phases: { prep: 4, exec: 28, analysis: 3 }, rpsWave: [2400, 4100, 5800, 7200, 7800, 7600, 7800, 7700, 7750, 7800], biz: 'kg', color: '#10b981' },
  { id: 'TSK-2038', title: '缓存层 Eviction Test', status: 'success', time: '12:30', date: 10, duration: '19m45s', owner: '王浩', rps: 31200, p99: 8.7, errorRate: 0.01, vuser: 1200, phases: { prep: 2, exec: 16, analysis: 1.75 }, rpsWave: [8000, 15000, 22000, 28000, 31200, 30800, 31200, 31000, 31100, 31200], biz: 'shared', color: '#22c55e' },
  { id: 'TSK-2037', title: '实时推送 WebSocket', status: 'running', time: '10:15', date: 9, duration: '52m', owner: '陈芳', rps: 3200, p99: 67.4, errorRate: 0.34, vuser: 180, phases: { prep: 5, exec: 40, analysis: 7 }, rpsWave: [800, 1500, 2200, 2800, 3200, 3100, 3200, 3150, 3180, 3200], biz: 'ai', color: '#8b5cf6' },
]

export const MONTH_NAMES = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']
export const WEEK_DAYS = ['日', '一', '二', '三', '四', '五', '六']

export function getCalendarDays(year: number, month: number) {
  const firstDay = new Date(year, month, 1).getDay()
  const dim = new Date(year, month + 1, 0).getDate()
  const prev = new Date(year, month, 0).getDate()
  const days: { day: number; current: boolean }[] = []
  for (let i = firstDay - 1; i >= 0; i--) days.push({ day: prev - i, current: false })
  for (let i = 1; i <= dim; i++) days.push({ day: i, current: true })
  const rem = 42 - days.length
  for (let i = 1; i <= rem; i++) days.push({ day: i, current: false })
  return days
}

export function stColor(s: string) {
  if (s === 'success') return '#22c55e'
  if (s === 'fail') return '#f97316'
  if (s === 'configured') return '#8b5cf6'   // 紫：已配置可运行
  if (s === 'draft') return '#94a3b8'        // 灰：仅上传未配置
  return '#3b82f6'                            // 蓝：running / 默认
}

export function parseTime(t: string): number {
  const [h, m] = t.split(':').map(Number)
  return h + m / 60
}

export function parseDuration(d: string): number {
  let mins = 0
  const hm = d.match(/(\d+)h/)
  const mm = d.match(/(\d+)m/)
  const sm = d.match(/(\d+)s/)
  if (hm) mins += parseInt(hm[1]) * 60
  if (mm) mins += parseInt(mm[1])
  if (sm) mins += parseInt(sm[1]) / 60
  return mins || 10
}

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { motion, AnimatePresence, useMotionValue, useTransform, useSpring } from "motion/react";
import { useTheme } from "./theme-context";
import {
  Plus, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Clock, Users, Zap, Brain,
  Search, Timer, AlertTriangle, CheckCircle2, Loader2, Gauge, Activity,
  BookOpen, Atom, GitBranch, Terminal, X, MoreHorizontal, Navigation,
} from "lucide-react";

/* ═══════════════════════════ CONFIG & DATA ═══════════════════════════ */
const SPRING = { stiffness: 150, damping: 18 };
const P99_THRESHOLD = 80;

/* Rim-light color: cool ice-blue daytime, warm amber at night */
function useRimColor() {
  const [c, setC] = useState("#7dd3fc");
  useEffect(() => {
    const h = new Date().getHours();
    setC(h >= 7 && h < 19 ? "#7dd3fc" : "#fbbf24");
  }, []);
  return c;
}

/* ── Animated counter (slot-machine) ── */
function Anim({ value, decimals = 0, suffix = "" }: { value: number; decimals?: number; suffix?: string }) {
  const [d, setD] = useState("0");
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return; ran.current = true;
    const s = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - s) / 1100, 1), e = 1 - Math.pow(1 - p, 4);
      setD(decimals > 0 ? (e * value).toFixed(decimals) : Math.floor(e * value).toLocaleString());
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [value, decimals]);
  return <span>{d}{suffix}</span>;
}

/* helper */
function stColor(s: string) { return s === "success" ? "#22c55e" : s === "fail" ? "#f97316" : "#3b82f6"; }
function stLabel(s: string) { return s === "success" ? "PASS" : s === "fail" ? "ALERT" : "LIVE"; }

/* ── Business Categories ── */
const BIZ = [
  { id: "shared", label: "共享课", sub: "Shared Courses", icon: BookOpen, color: "#60a5fa" },
  { id: "ai", label: "AI 事业中心", sub: "AI Center", icon: Atom, color: "#a78bfa" },
  { id: "kg", label: "KG 知识图谱", sub: "Knowledge Graph", icon: GitBranch, color: "#34d399" },
];

/* ── People ── */
const PEOPLE = [
  { name: "张明", role: "架构师", avatar: "ZM", color: "#3b82f6", progress: 0.72, status: "running" as const },
  { name: "李薇", role: "测试主管", avatar: "LW", color: "#8b5cf6", progress: 0.45, status: "analyzing" as const },
  { name: "王浩", role: "SRE", avatar: "WH", color: "#10b981", progress: 0.91, status: "running" as const },
  { name: "陈芳", role: "开发", avatar: "CF", color: "#f59e0b", progress: 0.33, status: "analyzing" as const },
  { name: "赵强", role: "QA", avatar: "ZQ", color: "#ec4899", progress: 0.68, status: "running" as const },
];

/* ── Tasks ── */
interface Task {
  id: string; title: string; status: "success" | "fail" | "running";
  time: string; date: number; duration: string; owner: string;
  rps: number; p99: number; errorRate: number; vuser: number;
  phases: { prep: number; exec: number; analysis: number };
  rpsWave: number[];
  biz: string; color: string;
}
const TASKS: Task[] = [
  { id: "TSK-2048", title: "Gateway 高并发压测", status: "running", time: "14:23", date: 11, duration: "15m32s", owner: "张明", rps: 12480, p99: 23.4, errorRate: 0.03, vuser: 500, phases: { prep: 2, exec: 12, analysis: 1.5 }, rpsWave: [4200,6800,9100,11200,12480,12100,12480,11900,12300,12480], biz: "shared", color: "#3b82f6" },
  { id: "TSK-2047", title: "用户服务 Soak Test", status: "fail", time: "11:05", date: 11, duration: "32m10s", owner: "李薇", rps: 8920, p99: 187.2, errorRate: 4.72, vuser: 200, phases: { prep: 5, exec: 25, analysis: 2.2 }, rpsWave: [3100,5600,7800,8900,8920,6200,4100,3800,5200,8920], biz: "ai", color: "#f97316" },
  { id: "TSK-2046", title: "订单链路 Spike Test", status: "success", time: "10:30", date: 11, duration: "8m45s", owner: "王浩", rps: 18340, p99: 15.8, errorRate: 0.01, vuser: 1000, phases: { prep: 1, exec: 7, analysis: 0.75 }, rpsWave: [2000,8000,14000,18340,18000,17800,18340,18100,18200,18340], biz: "kg", color: "#22c55e" },
  { id: "TSK-2045", title: "支付网关 Endurance", status: "success", time: "09:15", date: 10, duration: "1h02m", owner: "陈芳", rps: 6750, p99: 32.1, errorRate: 0.12, vuser: 150, phases: { prep: 3, exec: 55, analysis: 4 }, rpsWave: [2800,4500,5900,6300,6750,6600,6750,6700,6720,6750], biz: "shared", color: "#8b5cf6" },
  { id: "TSK-2044", title: "搜索服务 Capacity", status: "success", time: "08:40", date: 10, duration: "22m15s", owner: "赵强", rps: 9200, p99: 28.5, errorRate: 0.08, vuser: 300, phases: { prep: 2, exec: 18, analysis: 2.25 }, rpsWave: [3800,5200,7100,8400,9200,9000,9200,9100,9150,9200], biz: "kg", color: "#10b981" },
  { id: "TSK-2043", title: "推荐引擎 Baseline", status: "running", time: "08:00", date: 9, duration: "45m", owner: "张明", rps: 5600, p99: 42.3, errorRate: 0.21, vuser: 120, phases: { prep: 4, exec: 35, analysis: 6 }, rpsWave: [1200,2800,4100,5000,5600,5400,5600,5500,5580,5600], biz: "ai", color: "#3b82f6" },
  { id: "TSK-2042", title: "图谱查询 Stress", status: "success", time: "07:20", date: 9, duration: "18m30s", owner: "王浩", rps: 14200, p99: 19.7, errorRate: 0.02, vuser: 600, phases: { prep: 1.5, exec: 15, analysis: 2 }, rpsWave: [5000,8200,11000,13500,14200,14000,14200,14100,14150,14200], biz: "kg", color: "#22c55e" },
  { id: "TSK-2041", title: "消息队列 Peak Load", status: "running", time: "15:10", date: 11, duration: "28m", owner: "赵强", rps: 22100, p99: 18.3, errorRate: 0.05, vuser: 800, phases: { prep: 3, exec: 22, analysis: 3 }, rpsWave: [6000,10200,15800,19500,22100,21800,22100,21600,22000,22100], biz: "shared", color: "#3b82f6" },
  { id: "TSK-2040", title: "认证服务 Chaos Test", status: "fail", time: "13:45", date: 11, duration: "12m20s", owner: "张明", rps: 4300, p99: 245.6, errorRate: 8.91, vuser: 100, phases: { prep: 1, exec: 10, analysis: 1.3 }, rpsWave: [2000,3500,4300,4100,2800,1500,900,1200,3200,4300], biz: "ai", color: "#f97316" },
  { id: "TSK-2039", title: "文件存储 Throughput", status: "success", time: "16:00", date: 10, duration: "35m", owner: "李薇", rps: 7800, p99: 45.2, errorRate: 0.15, vuser: 250, phases: { prep: 4, exec: 28, analysis: 3 }, rpsWave: [2400,4100,5800,7200,7800,7600,7800,7700,7750,7800], biz: "kg", color: "#10b981" },
  { id: "TSK-2038", title: "缓存层 Eviction Test", status: "success", time: "12:30", date: 10, duration: "19m45s", owner: "王浩", rps: 31200, p99: 8.7, errorRate: 0.01, vuser: 1200, phases: { prep: 2, exec: 16, analysis: 1.75 }, rpsWave: [8000,15000,22000,28000,31200,30800,31200,31000,31100,31200], biz: "shared", color: "#22c55e" },
  { id: "TSK-2037", title: "实时推送 WebSocket", status: "running", time: "10:15", date: 9, duration: "52m", owner: "陈芳", rps: 3200, p99: 67.4, errorRate: 0.34, vuser: 180, phases: { prep: 5, exec: 40, analysis: 7 }, rpsWave: [800,1500,2200,2800,3200,3100,3200,3150,3180,3200], biz: "ai", color: "#8b5cf6" },
];

/* ── Calendar helpers ── */
const MONTH_NAMES = ["一月","二月","三月","四月","五月","六月","七月","八月","九月","十月","十一月","十二月"];
const WEEK_DAYS = ["日","一","二","三","四","五","六"];
function getCalendarDays(year: number, month: number) {
  const firstDay = new Date(year, month, 1).getDay();
  const dim = new Date(year, month + 1, 0).getDate();
  const prev = new Date(year, month, 0).getDate();
  const days: { day: number; current: boolean }[] = [];
  for (let i = firstDay - 1; i >= 0; i--) days.push({ day: prev - i, current: false });
  for (let i = 1; i <= dim; i++) days.push({ day: i, current: true });
  const rem = 42 - days.length;
  for (let i = 1; i <= rem; i++) days.push({ day: i, current: false });
  return days;
}

/* ── Mini wave sparkline for overlaying on bars ── */
function WaveSpark({ data, color, w = 160, h = 24 }: { data: number[]; color: string; w?: number; h?: number }) {
  const mn = Math.min(...data) * 0.8, mx = Math.max(...data) * 1.1, rg = mx - mn || 1;
  const pts = data.map((v, i) => ({ x: (i / (data.length - 1)) * w, y: h - ((v - mn) / rg) * h }));
  const pathD = pts.reduce((a, p, i) => {
    if (!i) return `M ${p.x} ${p.y}`;
    const prev = pts[i - 1], cx = (prev.x + p.x) / 2;
    return `${a} C ${cx} ${prev.y}, ${cx} ${p.y}, ${p.x} ${p.y}`;
  }, "");
  const uid = useMemo(() => `w${Math.random().toString(36).slice(2, 7)}`, []);
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="overflow-visible">
      <defs>
        <linearGradient id={`wg${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.2} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <filter id={`wf${uid}`}><feGaussianBlur stdDeviation="2" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <path d={`${pathD} L ${w} ${h} L 0 ${h} Z`} fill={`url(#wg${uid})`} />
      <path d={pathD} fill="none" stroke={color} strokeWidth={1.2} filter={`url(#wf${uid})`} opacity={0.7} />
    </svg>
  );
}

/* ══════════════════════════════════════════════════════════════
   COLUMN 1 — Categorical Sidebar (业务生态岛)
   Narrow frosted-black glass strip with 1px ion light border
   ══════════════════════════════════════════════════════════════ */
function CategoricalSidebar({ isDark, active, onSelect, rimColor }: {
  isDark: boolean; active: string; onSelect: (id: string) => void; rimColor: string;
}) {
  return (
    <div className="flex flex-col items-center py-5 gap-2 relative"
      style={{ width: 72 }}>
      <div className="w-8 h-8 rounded-2xl flex items-center justify-center mb-4"
        style={{
          background: "linear-gradient(135deg, rgba(59,130,246,0.15), rgba(139,92,246,0.15))",
          boxShadow: `0 0 20px rgba(59,130,246,0.08)`,
        }}>
        <Zap size={14} color="#60a5fa" />
      </div>
      {BIZ.map((b) => {
        const isActive = active === b.id;
        const Icon = b.icon;
        return (
          <motion.button key={b.id}
            onClick={() => onSelect(b.id)}
            animate={{ x: isActive ? 5 : 0, scale: isActive ? 1.05 : 1 }}
            whileTap={{ scale: 0.9 }}
            transition={{ type: "spring", ...SPRING }}
            className="relative w-11 h-11 rounded-2xl flex items-center justify-center cursor-pointer group"
            style={{
              background: isActive ? `${b.color}15` : isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
            }}>
            {isActive && (
              <motion.div layoutId="sidebarGlow" className="absolute inset-0 rounded-2xl"
                style={{
                  background: `radial-gradient(circle at center, ${b.color}25, transparent 70%)`,
                  boxShadow: `0 0 24px ${b.color}20, inset 0 0 12px ${b.color}08`,
                }}
                transition={{ type: "spring", ...SPRING }} />
            )}
            {isActive && (
              <motion.div layoutId="sidebarDot"
                className="absolute -left-[2px] w-[4px] h-6 rounded-full"
                style={{ background: b.color, boxShadow: `0 0 8px ${b.color}60` }}
                transition={{ type: "spring", ...SPRING }} />
            )}
            <motion.div
              animate={b.id === "ai" ? { scale: [1, 1.12, 1], opacity: [0.8, 1, 0.8] } : {}}
              transition={b.id === "ai" ? { duration: 3, repeat: Infinity, ease: "easeInOut" } : {}}
              className="relative z-10">
              <Icon size={18} color={isActive ? b.color : isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)"} />
            </motion.div>
            <div className="absolute left-full ml-3 px-2.5 py-1.5 rounded-xl whitespace-nowrap
              opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity duration-200 z-50"
              style={{
                background: isDark ? "rgba(20,20,30,0.95)" : "rgba(255,255,255,0.95)",
                backdropFilter: "blur(20px)",
                boxShadow: `0 4px 20px rgba(0,0,0,0.2), 0 0 0 1px ${rimColor}15`,
              }}>
              <p className="text-[13px]" style={{ color: isDark ? "#fff" : "#1a1a2e" }}>{b.label}</p>
              <p className="text-[10px] mt-0.5" style={{ color: isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)" }}>{b.sub}</p>
            </div>
          </motion.button>
        );
      })}
      <div className="flex-1" />
      <motion.button whileTap={{ scale: 0.85 }}
        className="w-9 h-9 rounded-xl flex items-center justify-center cursor-pointer"
        style={{ background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)" }}>
        <Search size={14} color={isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)"} />
      </motion.button>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   COLUMN 2 — Temporal & Personnel (时空与协作)
   Smart Calendar + Team Matrix with progress-ring avatars
   ══════════════════════════════════════════════════════════════ */
function TemporalColumn({ isDark, selectedDate, onSelectDate, rimColor, taskDates, focusedTask, tasks }: {
  isDark: boolean; selectedDate: number; onSelectDate: (d: number) => void;
  rimColor: string; taskDates: Set<number>; focusedTask?: string | null; tasks?: Task[];
}) {
  const today = new Date();
  const [vy, setVY] = useState(today.getFullYear());
  const [vm, setVM] = useState(today.getMonth());
  const days = useMemo(() => getCalendarDays(vy, vm), [vy, vm]);
  const todayDate = today.getDate();
  const isCurrentMonth = vm === today.getMonth() && vy === today.getFullYear();

  const prev = () => { if (vm === 0) { setVM(11); setVY(y => y - 1); } else setVM(m => m - 1); };
  const next = () => { if (vm === 11) { setVM(0); setVY(y => y + 1); } else setVM(m => m + 1); };

  return (
    <div className="flex flex-col h-full py-5 px-4" style={{ width: 290 }}>
      {/* ── Calendar ── */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-4 px-1">
          <motion.button whileTap={{ scale: 0.8 }} onClick={prev} className="cursor-pointer p-1.5 rounded-lg"
            style={{ background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)" }}>
            <ChevronLeft size={16} color={isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)"} />
          </motion.button>
          <div className="text-center">
            <p className="text-[18px] tracking-wide" style={{ color: isDark ? "rgba(255,255,255,0.8)" : "rgba(0,0,0,0.8)" }}>
              {MONTH_NAMES[vm]}
            </p>
            <p className="text-[12px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)" }}>{vy}</p>
          </div>
          <motion.button whileTap={{ scale: 0.8 }} onClick={next} className="cursor-pointer p-1.5 rounded-lg"
            style={{ background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)" }}>
            <ChevronRight size={16} color={isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)"} />
          </motion.button>
        </div>

        {/* Weekday headers */}
        <div className="grid grid-cols-7 mb-1">
          {WEEK_DAYS.map(w => (
            <div key={w} className="text-center py-1">
              <span className="text-[11px] tracking-wider" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.2)" }}>{w}</span>
            </div>
          ))}
        </div>

        {/* Borderless floating numbers */}
        <div className="grid grid-cols-7 gap-y-0.5">
          {days.map((d, i) => {
            const isToday = d.current && d.day === todayDate && isCurrentMonth;
            const isSelected = d.current && d.day === selectedDate && isCurrentMonth;
            const hasTask = d.current && taskDates.has(d.day);
            const focusedDate = focusedTask && tasks ? tasks.find(t => t.id === focusedTask)?.date : null;
            const isBacklit = d.current && focusedDate === d.day;
            return (
              <motion.button key={i}
                whileTap={{ scale: 0.8 }}
                onClick={() => d.current && onSelectDate(d.day)}
                className="relative w-full aspect-square flex flex-col items-center justify-center cursor-pointer"
                transition={{ type: "spring", ...SPRING }}>
                {isToday && (
                  <motion.div className="absolute inset-[2px] rounded-full"
                    animate={{
                      boxShadow: [
                        `0 0 8px ${rimColor}30, inset 0 0 4px ${rimColor}15`,
                        `0 0 16px ${rimColor}50, inset 0 0 8px ${rimColor}25`,
                        `0 0 8px ${rimColor}30, inset 0 0 4px ${rimColor}15`,
                      ],
                      background: [
                        `radial-gradient(circle, ${rimColor}08, transparent)`,
                        `radial-gradient(circle, ${rimColor}15, transparent)`,
                        `radial-gradient(circle, ${rimColor}08, transparent)`,
                      ],
                    }}
                    transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                    style={{ border: `1.5px solid ${rimColor}40` }}
                  />
                )}
                {isSelected && !isToday && (
                  <motion.div layoutId="calSel" className="absolute inset-[3px] rounded-full"
                    style={{ background: "#3b82f6", opacity: 0.15 }}
                    transition={{ type: "spring", ...SPRING }} />
                )}
                {isBacklit && !isToday && !isSelected && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.5 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.5 }}
                    className="absolute inset-[2px] rounded-full"
                    style={{
                      background: `radial-gradient(circle, ${rimColor}20, transparent)`,
                      boxShadow: `0 0 12px ${rimColor}30`,
                    }}
                    transition={{ type: "spring", ...SPRING }} />
                )}
                <span className="text-[14px] relative z-10"
                  style={{
                    color: isToday ? rimColor
                      : isSelected ? "#3b82f6"
                      : !d.current ? (isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.1)")
                      : isDark ? "rgba(255,255,255,0.55)" : "rgba(0,0,0,0.55)",
                  }}>
                  {d.day}
                </span>
                {hasTask && (
                  <div className="w-[5px] h-[5px] rounded-full absolute bottom-[3px]"
                    style={{
                      background: isToday ? rimColor : "rgba(59,130,246,0.5)",
                      boxShadow: `0 0 4px rgba(59,130,246,0.3)`,
                    }} />
                )}
              </motion.button>
            );
          })}
        </div>
      </div>

      {/* Separator */}
      <div className="mx-2 h-[1px] mb-3"
        style={{ background: `linear-gradient(90deg, transparent, ${rimColor}15, transparent)` }} />

      {/* ── Team Matrix ── */}
      <p className="text-[11px] uppercase tracking-[0.2em] px-2 mb-3"
        style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.2)" }}>
        Team Matrix
      </p>
      <div className="flex-1 overflow-y-auto flex flex-col gap-2">
        {PEOPLE.map((p, i) => {
          const ringColor = p.status === "running" ? "#22c55e" : "#3b82f6";
          const r = 18, circ = 2 * Math.PI * r;
          const offset = circ - p.progress * circ;
          return (
            <motion.div key={i}
              initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06, type: "spring", ...SPRING }}
              className="flex items-center gap-3 px-2.5 py-2.5 rounded-xl cursor-pointer group"
              style={{ background: isDark ? "rgba(255,255,255,0.015)" : "rgba(0,0,0,0.01)" }}>
              <div className="relative flex-shrink-0">
                <svg width={44} height={44} viewBox="0 0 44 44" className="absolute inset-0">
                  <circle cx={22} cy={22} r={r} fill="none" stroke={isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)"} strokeWidth={2.5} />
                  <circle cx={22} cy={22} r={r} fill="none" stroke={ringColor} strokeWidth={2.5}
                    strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
                    transform="rotate(-90 22 22)" opacity={0.8} />
                </svg>
                <div className="w-11 h-11 rounded-xl flex items-center justify-center text-[12px] text-white relative z-10"
                  style={{
                    background: `linear-gradient(135deg, ${p.color}dd, ${p.color}88)`,
                    boxShadow: `0 3px 10px ${p.color}25, inset 0 1px 0 rgba(255,255,255,0.15), inset 0 -1px 0 rgba(0,0,0,0.15)`,
                  }}>
                  {p.avatar}
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] truncate" style={{ color: isDark ? "rgba(255,255,255,0.65)" : "rgba(0,0,0,0.65)" }}>{p.name}</p>
                <p className="text-[11px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}>{p.role}</p>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-[6px] h-[6px] rounded-full"
                  style={{
                    background: ringColor,
                    boxShadow: `0 0 6px ${ringColor}40`,
                  }} />
                <span className="text-[10px]" style={{ color: ringColor }}>
                  {p.status === "running" ? "执行中" : "分析中"}
                </span>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   COLUMN 3 — Schedule Planner (时间计划表)
   Shows task execution as a day-planner / timetable view.
   Top: date pills for switching. Body: hour grid with task blocks.
   ══════════════════════════════════════════════════════════════ */

const SCHEDULE_HOURS = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17];

function parseTime(t: string): number {
  const [h, m] = t.split(":").map(Number);
  return h + m / 60;
}

function parseDuration(d: string): number {
  let mins = 0;
  const hm = d.match(/(\d+)h/);
  const mm = d.match(/(\d+)m/);
  const sm = d.match(/(\d+)s/);
  if (hm) mins += parseInt(hm[1]) * 60;
  if (mm) mins += parseInt(mm[1]);
  if (sm) mins += parseInt(sm[1]) / 60;
  return mins || 10;
}

function MetricsColumn({ isDark, tasks, focusedTask, rimColor, selectedDate, onSelectDate }: {
  isDark: boolean; tasks: Task[]; focusedTask: string | null; rimColor: string;
  selectedDate: number; onSelectDate: (d: number) => void;
}) {
  const [expandedTask, setExpandedTask] = useState<string | null>(null);

  const availableDates = useMemo(() =>
    [...new Set(tasks.map(t => t.date))].sort((a, b) => b - a),
  [tasks]);

  const dayTasks = useMemo(
    () => tasks.filter(t => t.date === selectedDate),
    [tasks, selectedDate]
  );

  const totalDayMins = useMemo(
    () => dayTasks.reduce((sum, t) => sum + parseDuration(t.duration), 0),
    [dayTasks]
  );

  const ROW_H = 80;
  const gridStart = SCHEDULE_HOURS[0];
  const gridEnd = SCHEDULE_HOURS[SCHEDULE_HOURS.length - 1] + 1;
  const totalGrid = gridEnd - gridStart;

  // Collision avoidance: assign lanes to overlapping tasks
  const taskLanes = useMemo(() => {
    const sorted = [...dayTasks].sort((a, b) => parseTime(a.time) - parseTime(b.time));
    const lanes: { endPx: number }[] = [];
    const assignments: { id: string; lane: number }[] = [];

    for (const t of sorted) {
      const startH = parseTime(t.time);
      const durH = parseDuration(t.duration) / 60;
      const topPx = ((startH - gridStart) / totalGrid) * (SCHEDULE_HOURS.length * ROW_H);
      const heightPx = Math.max(56, (durH / totalGrid) * (SCHEDULE_HOURS.length * ROW_H));
      const bottomPx = topPx + heightPx;

      let assignedLane = -1;
      for (let l = 0; l < lanes.length; l++) {
        if (lanes[l].endPx <= topPx + 2) {
          assignedLane = l;
          break;
        }
      }
      if (assignedLane === -1) {
        assignedLane = lanes.length;
        lanes.push({ endPx: bottomPx });
      } else {
        lanes[assignedLane].endPx = bottomPx;
      }
      assignments.push({ id: t.id, lane: assignedLane });
    }

    const totalLanes = Math.max(lanes.length, 1);
    const map: Record<string, { lane: number; totalLanes: number }> = {};
    for (const a of assignments) {
      map[a.id] = { lane: a.lane, totalLanes };
    }
    return map;
  }, [dayTasks, gridStart, totalGrid]);

  return (
    <div className="flex flex-col h-full py-5 px-4 flex-1 min-w-0">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-3 px-1">
        <p className="text-[11px] uppercase tracking-[0.2em]"
          style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.2)" }}>
          Schedule Planner
        </p>
        <div className="flex items-center gap-1.5">
          {[
            { label: "Prep", color: "#60a5fa" },
            { label: "Exec", color: "#818cf8" },
            { label: "Analysis", color: "#a78bfa" },
          ].map(l => (
            <div key={l.label} className="flex items-center gap-1 ml-2">
              <div className="w-[6px] h-[6px] rounded-sm" style={{ background: l.color }} />
              <span className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}>{l.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Date pills ── */}
      <div className="flex items-center gap-2 mb-3 px-1 overflow-x-auto flex-shrink-0">
        {availableDates.map(d => {
          const isActive = d === selectedDate;
          const count = tasks.filter(t => t.date === d).length;
          return (
            <motion.button key={d}
              whileTap={{ scale: 0.92 }}
              onClick={() => onSelectDate(d)}
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl cursor-pointer flex-shrink-0 relative overflow-hidden"
              style={{
                background: isActive
                  ? isDark ? "rgba(59,130,246,0.12)" : "rgba(59,130,246,0.08)"
                  : isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
                border: `1px solid ${isActive ? "rgba(59,130,246,0.2)" : isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.04)"}`,
              }}>
              {isActive && (
                <motion.div layoutId="datePill" className="absolute inset-0 rounded-xl"
                  style={{ background: isDark ? "rgba(59,130,246,0.08)" : "rgba(59,130,246,0.05)" }}
                  transition={{ type: "spring", ...SPRING }} />
              )}
              <span className="text-[16px] relative z-10"
                style={{ color: isActive ? "#3b82f6" : isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)" }}>
                {d}
              </span>
              <span className="text-[10px] relative z-10"
                style={{ color: isActive ? "#3b82f6" : isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)" }}>
                四月
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-md relative z-10"
                style={{
                  background: isActive ? "rgba(59,130,246,0.1)" : isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)",
                  color: isActive ? "#3b82f6" : isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)",
                }}>
                {count}
              </span>
            </motion.button>
          );
        })}
      </div>

      {/* ── Day summary ── */}
      <div className="flex items-center gap-4 mb-3 px-2">
        <div className="flex items-center gap-1.5">
          <Activity size={14} color={isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)"} />
          <span className="text-[12px]" style={{ color: isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)" }}>
            <Anim value={dayTasks.length} /> 个任务
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock size={14} color={isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)"} />
          <span className="text-[12px]" style={{ color: isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)" }}>
            共 <Anim value={Math.round(totalDayMins)} /> 分钟
          </span>
        </div>
      </div>

      {/* ── Time grid ── */}
      <div className="flex-1 overflow-y-auto pr-1 relative">
        <div className="relative" style={{ minHeight: SCHEDULE_HOURS.length * ROW_H }}>
          {/* Hour grid lines */}
          {SCHEDULE_HOURS.map((h, i) => (
            <div key={h} className="absolute left-0 right-0 flex items-start" style={{ top: i * ROW_H }}>
              <div className="w-[48px] flex-shrink-0 text-right pr-2 -mt-[6px]">
                <span className="text-[12px]" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }}>
                  {String(h).padStart(2, "0")}:00
                </span>
              </div>
              <div className="flex-1 h-[1px]" style={{ background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.04)" }} />
            </div>
          ))}

          {/* "Now" indicator */}
          {(() => {
            const now = new Date();
            const nowH = now.getHours() + now.getMinutes() / 60;
            if (nowH >= gridStart && nowH <= gridEnd && selectedDate === now.getDate()) {
              const top = ((nowH - gridStart) / (gridEnd - gridStart)) * (SCHEDULE_HOURS.length * ROW_H);
              return (
                <div className="absolute left-[48px] right-0 flex items-center z-30 pointer-events-none" style={{ top }}>
                  <div className="w-[8px] h-[8px] rounded-full" style={{ background: "#f43f5e", boxShadow: "0 0 8px rgba(244,63,94,0.4)" }} />
                  <div className="flex-1 h-[1.5px]" style={{ background: "linear-gradient(90deg, #f43f5e, transparent)" }} />
                </div>
              );
            }
            return null;
          })()}

          {/* Task blocks — lane-based collision avoidance */}
          {(() => { return dayTasks.map((t, i) => {
            const startH = parseTime(t.time);
            const durMins = parseDuration(t.duration);
            const durH = durMins / 60;
            const top = ((startH - gridStart) / totalGrid) * (SCHEDULE_HOURS.length * ROW_H);
            const height = Math.max(56, (durH / totalGrid) * (SCHEDULE_HOURS.length * ROW_H));
            const laneInfo = taskLanes[t.id] || { lane: 0, totalLanes: 1 };
            const laneWidth = 100 / laneInfo.totalLanes;
            const laneLeft = laneInfo.lane * laneWidth;
            const sc = stColor(t.status);
            const isFocused = focusedTask === t.id;
            const isGlobalFocused = isFocused; // from stream hover
            const isExpanded = expandedTask === t.id;
            const warn = t.p99 > P99_THRESHOLD;
            const total = t.phases.prep + t.phases.exec + t.phases.analysis;
            const prepPct = (t.phases.prep / total) * 100;
            const execPct = (t.phases.exec / total) * 100;
            const analysisPct = (t.phases.analysis / total) * 100;

            return (
              <motion.div key={t.id}
                initial={{ opacity: 0, x: 20, scaleY: 0.8 }}
                animate={{ opacity: 1, x: 0, scaleY: 1 }}
                transition={{ delay: i * 0.08, type: "spring", ...SPRING }}
                className="absolute rounded-2xl overflow-hidden cursor-pointer group"
                style={{
                  top,
                  left: `calc(54px + (100% - 58px) * ${laneLeft / 100})`,
                  width: `calc((100% - 58px) * ${laneWidth / 100} - ${laneInfo.totalLanes > 1 ? 4 : 0}px)`,
                  minHeight: 56,
                  height: isExpanded ? "auto" : height,
                  zIndex: isFocused ? 20 : isExpanded ? 15 : 10 - i,
                  background: isDark ? "rgba(255,255,255,0.025)" : "rgba(255,255,255,0.5)",
                  border: `1px solid ${isFocused ? `${sc}30` : isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.05)"}`,
                  boxShadow: isFocused
                    ? `0 4px 24px ${sc}25, 0 0 0 1px ${sc}20, 0 0 40px ${sc}15`
                    : `0 2px 8px rgba(0,0,0,${isDark ? 0.12 : 0.04})`,
                  transition: "all 0.3s ease",
                  transform: isGlobalFocused ? "scale(1.02)" : undefined,
                }}
                onClick={() => setExpandedTask(isExpanded ? null : t.id)}>

                {/* Left accent strip */}
                <div className="absolute left-0 top-0 bottom-0 w-[4px] rounded-l-2xl"
                  style={{ background: `linear-gradient(180deg, ${sc}, ${sc}60)` }} />

                {/* Top rim light */}
                <div className="absolute top-0 left-3 right-3 h-[1px]"
                  style={{ background: `linear-gradient(90deg, transparent, ${rimColor}15, transparent)` }} />

                <div className="pl-4 pr-3 py-2.5 relative">
                  {/* Duration width tooltip on hover */}
                  <div className="absolute -top-[2px] right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <span className="text-[9px] px-1.5 py-0.5 rounded"
                      style={{ background: isDark ? "rgba(0,0,0,0.6)" : "rgba(0,0,0,0.06)", color: isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.35)" }}>
                      {durMins.toFixed(0)}min
                    </span>
                  </div>
                  {/* Row 1: time + title + duration */}
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[12px] flex-shrink-0" style={{ color: sc }}>{t.time}</span>
                      {t.status === "running" && (
                        <motion.div className="w-[6px] h-[6px] rounded-full flex-shrink-0" style={{ background: sc }}
                          animate={{ scale: [1, 1.4, 1], opacity: [1, 0.4, 1] }}
                          transition={{ duration: 1.5, repeat: Infinity }} />
                      )}
                      <p className="text-[13px] truncate"
                        style={{ color: isDark ? "rgba(255,255,255,0.7)" : "rgba(0,0,0,0.7)" }}>
                        {t.title}
                      </p>
                    </div>
                    <span className="text-[11px] px-2 py-0.5 rounded-lg flex-shrink-0 ml-2"
                      style={{ background: `${sc}0c`, color: sc }}>
                      {t.duration}
                    </span>
                  </div>

                  {/* Row 2: Phase bar */}
                  <div className="relative h-[18px] rounded-md overflow-hidden mb-2"
                    style={{ background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)" }}>
                    <div className="absolute inset-0 flex">
                      <motion.div initial={{ width: 0 }} animate={{ width: `${prepPct}%` }}
                        transition={{ duration: 0.7, delay: i * 0.06, ease: "easeOut" }}
                        className="h-full" style={{ background: "linear-gradient(90deg, #3b82f6, #60a5fa)" }} />
                      <motion.div initial={{ width: 0 }} animate={{ width: `${execPct}%` }}
                        transition={{ duration: 0.9, delay: i * 0.06 + 0.15, ease: "easeOut" }}
                        className="h-full" style={{ background: "linear-gradient(90deg, #6366f1, #818cf8)" }} />
                      <motion.div initial={{ width: 0 }} animate={{ width: `${analysisPct}%` }}
                        transition={{ duration: 0.6, delay: i * 0.06 + 0.3, ease: "easeOut" }}
                        className="h-full" style={{ background: "linear-gradient(90deg, #8b5cf6, #a78bfa)" }} />
                    </div>
                    <div className="absolute inset-0 pointer-events-none"
                      style={{ background: "linear-gradient(180deg, rgba(255,255,255,0.12), transparent 50%)" }} />
                  </div>

                  {/* Row 3: owner + metrics */}
                  <div className="flex items-center gap-2.5">
                    {PEOPLE.find(p => p.name === t.owner) && (
                      <div className="w-5 h-5 rounded-md flex items-center justify-center text-[8px] text-white flex-shrink-0"
                        style={{ background: PEOPLE.find(p => p.name === t.owner)!.color, boxShadow: "inset 0 1px 0 rgba(255,255,255,0.15)" }}>
                        {PEOPLE.find(p => p.name === t.owner)!.avatar}
                      </div>
                    )}
                    <span className="text-[11px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}>{t.owner}</span>
                    <div className="flex items-center gap-3 ml-auto">
                      <span className="text-[10px]" style={{ color: "#60a5fa" }}><Anim value={t.rps} /> rps</span>
                      <span className="text-[10px]" style={{ color: warn ? "#f97316" : "#10b981" }}>P99: <Anim value={t.p99} decimals={1} suffix="ms" /></span>
                    </div>
                  </div>

                  {/* ── Expanded detail ── */}
                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ type: "spring", ...SPRING }}
                        className="overflow-hidden">
                        <div className="my-2.5 h-[1px]" style={{ background: `linear-gradient(90deg, transparent, ${rimColor}10, transparent)` }} />
                        {/* Phase cards */}
                        <div className="flex gap-2.5 mb-2.5">
                          {[
                            { label: "脚本准备", val: `${t.phases.prep}m`, color: "#60a5fa", pct: prepPct },
                            { label: "执行", val: `${t.phases.exec}m`, color: "#818cf8", pct: execPct },
                            { label: "结果分析", val: `${t.phases.analysis}m`, color: "#a78bfa", pct: analysisPct },
                          ].map(ph => (
                            <div key={ph.label} className="flex-1 rounded-xl p-2.5"
                              style={{ background: isDark ? "rgba(255,255,255,0.015)" : "rgba(0,0,0,0.015)", border: `1px solid ${isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.03)"}` }}>
                              <div className="flex items-center gap-1.5 mb-1">
                                <div className="w-[5px] h-[5px] rounded-sm" style={{ background: ph.color }} />
                                <span className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)" }}>{ph.label}</span>
                              </div>
                              <p className="text-[16px]" style={{ color: ph.color }}>{ph.val}</p>
                              <p className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }}>{ph.pct.toFixed(0)}%</p>
                            </div>
                          ))}
                        </div>
                        {/* Metrics grid */}
                        <div className="grid grid-cols-4 gap-2 mb-2.5">
                          {[
                            { icon: Gauge, label: "RPS", val: t.rps, c: "#3b82f6" },
                            { icon: Users, label: "Vuser", val: t.vuser, c: "#8b5cf6" },
                            { icon: Timer, label: "P99", val: t.p99, sfx: "ms", d: 1, c: warn ? "#f97316" : "#10b981" },
                            { icon: AlertTriangle, label: "Err%", val: t.errorRate, sfx: "%", d: 2, c: t.errorRate > 1 ? "#f97316" : "#22c55e" },
                          ].map(m => (
                            <div key={m.label} className="rounded-lg p-2 text-center" style={{ background: isDark ? "rgba(255,255,255,0.015)" : "rgba(0,0,0,0.015)" }}>
                              <m.icon size={14} color={m.c} className="mx-auto mb-1" />
                              <p className="text-[13px]" style={{ color: isDark ? "rgba(255,255,255,0.6)" : "rgba(0,0,0,0.6)" }}><Anim value={m.val} decimals={m.d || 0} suffix={m.sfx} /></p>
                              <p className="text-[9px]" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }}>{m.label}</p>
                            </div>
                          ))}
                        </div>
                        {/* RPS wave */}
                        <div className="rounded-xl p-2.5" style={{ background: isDark ? "rgba(255,255,255,0.015)" : "rgba(0,0,0,0.015)" }}>
                          <div className="flex items-center gap-1.5 mb-1.5">
                            <Activity size={12} color={isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)"} />
                            <span className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)" }}>Throughput Wave</span>
                          </div>
                          <WaveSpark data={t.rpsWave} color={sc} h={36} />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                {/* P99 warning bubble */}
                {warn && !isExpanded && (
                  <motion.div className="absolute top-2 right-2 px-2 py-1 rounded-lg flex items-center gap-1.5 z-20"
                    animate={{ boxShadow: ["0 0 4px rgba(249,115,22,0.2)", "0 0 10px rgba(249,115,22,0.5)", "0 0 4px rgba(249,115,22,0.2)"] }}
                    transition={{ duration: 1.5, repeat: Infinity }}
                    style={{ background: isDark ? "rgba(249,115,22,0.12)" : "rgba(249,115,22,0.08)", border: "1px solid rgba(249,115,22,0.25)" }}>
                    <AlertTriangle size={10} color="#f97316" />
                    <span className="text-[10px]" style={{ color: "#f97316" }}>P99: <Anim value={t.p99} decimals={1} suffix="ms" /></span>
                  </motion.div>
                )}
              </motion.div>
            );
          }); })()}

          {/* Empty state */}
          {dayTasks.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <Clock size={24} color={isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"} className="mx-auto mb-2" />
                <p className="text-[13px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.2)" }}>该日期无任务</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   COLUMN 4 — The Infinite Stream (无限时空流)
   Sticky genesis anchor, reverse-growth depth timeline,
   elastic momentum scroll, glass skeletons, time progress bar
   ══════════════════════════════════════════════════════════════ */

/* Glass Skeleton placeholder */
function GlassSkeleton({ isDark, rimColor, index }: { isDark: boolean; rimColor: string; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: [0.3, 0.6, 0.3] }}
      transition={{ duration: 2, repeat: Infinity, delay: index * 0.2 }}
      className="flex gap-3 pl-0">
      <div className="flex-shrink-0 w-[44px] flex justify-center">
        <div className="w-[16px] h-[16px] rounded-full mt-2"
          style={{ background: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
      </div>
      <div className="flex-1 rounded-xl p-3"
        style={{
          background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
          backdropFilter: "blur(40px)",
          border: `1px solid ${isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.03)"}`,
        }}>
        <div className="h-[10px] w-[60%] rounded mb-2" style={{ background: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }} />
        <div className="h-[12px] w-[85%] rounded mb-2" style={{ background: isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)" }} />
        <div className="h-[8px] w-[40%] rounded" style={{ background: isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)" }} />
      </div>
    </motion.div>
  );
}

/* Time progress bar labels */
const TIME_MARKERS = [
  { label: "Now", offset: 0 },
  { label: "1h ago", offset: 0.15 },
  { label: "3h ago", offset: 0.35 },
  { label: "1d ago", offset: 0.6 },
  { label: "Last Week", offset: 0.85 },
];

function ChronosNerve({ isDark, tasks, rimColor, onFocus, activeBiz, onSelectBiz }: {
  isDark: boolean; tasks: Task[]; rimColor: string;
  onFocus: (id: string | null) => void;
  activeBiz: string; onSelectBiz: (id: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [curlText, setCurlText] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);


  // Simulate async loading
  useEffect(() => {
    const timer = setTimeout(() => setIsLoading(false), 1200);
    return () => clearTimeout(timer);
  }, []);

  const bizTasks = useMemo(
    () => activeBiz === "all" ? tasks : tasks.filter(t => t.biz === activeBiz),
    [tasks, activeBiz]
  );

  const allSorted = useMemo(
    () => [...bizTasks].sort((a, b) => {
      if (a.date !== b.date) return b.date - a.date;
      return parseTime(b.time) - parseTime(a.time);
    }),
    [bizTasks]
  );



  const renderStreamCard = (t: Task, i: number) => {
    const sc = stColor(t.status);
    const warn = t.p99 > P99_THRESHOLD;

    return (
      <motion.div key={t.id}
        data-task-id={t.id}
        initial={{ opacity: 0, x: 30 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.04 + i * 0.03, type: "spring", ...SPRING }}
        onHoverStart={() => onFocus(t.id)}
        onHoverEnd={() => onFocus(null)}
        className="flex items-start gap-3 pl-0 cursor-pointer group relative">
        {/* Timeline node — vertically centered with first line of card */}
        <div className="flex-shrink-0 w-[44px] flex justify-center relative z-10 pt-[14px]">
          <motion.div
            className="w-[16px] h-[16px] rounded-full flex items-center justify-center"
            whileHover={{ scale: 1.3, boxShadow: `0 0 16px ${sc}40` }}
            transition={{ type: "spring", ...SPRING }}
            style={{
              background: isDark ? "rgba(10,10,10,0.8)" : "rgba(245,245,247,0.8)",
              border: `2px solid ${sc}`,
              boxShadow: `0 0 8px ${sc}28`,
            }}>
            {t.status === "running" ? (
              <motion.div className="w-[6px] h-[6px] rounded-full" style={{ background: sc }}
                animate={{ scale: [1, 1.5, 1], opacity: [1, 0.3, 1] }}
                transition={{ duration: 1.5, repeat: Infinity }} />
            ) : (
              <div className="w-[5px] h-[5px] rounded-full" style={{ background: sc }} />
            )}
          </motion.div>
        </div>

        {/* Card body */}
        <motion.div
          whileHover={{ x: -3, boxShadow: `0 4px 24px ${sc}12, 0 0 0 1px ${sc}15` }}
          transition={{ type: "spring", ...SPRING }}
          className="flex-1 rounded-xl p-3 min-w-0 relative overflow-hidden"
          style={{
            background: isDark ? "rgba(255,255,255,0.035)" : "rgba(255,255,255,0.6)",
            border: `1px solid ${isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.04)"}`,
          }}>
          {/* Rim light */}
          <div className="absolute top-0 left-2 right-2 h-[1px]"
            style={{ background: `linear-gradient(90deg, transparent, ${rimColor}25, transparent)` }} />

          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[11px]" style={{ color: sc }}>{t.time}</span>
              <span className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }}>{t.id}</span>
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded-md" style={{ background: `${sc}10`, color: sc }}>{t.duration}</span>
          </div>
          <p className="text-[13px] truncate mb-2" style={{ color: isDark ? "rgba(255,255,255,0.8)" : "rgba(0,0,0,0.8)" }}>{t.title}</p>
          <div className="flex items-center gap-2.5">
            {PEOPLE.find(p => p.name === t.owner) && (
              <div className="w-5 h-5 rounded-md flex items-center justify-center text-[8px] text-white"
                style={{ background: PEOPLE.find(p => p.name === t.owner)!.color, boxShadow: "inset 0 1px 0 rgba(255,255,255,0.15)" }}>
                {PEOPLE.find(p => p.name === t.owner)!.avatar}
              </div>
            )}
            <span className="text-[11px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}>{t.owner}</span>
            {(() => { const biz = BIZ.find(b => b.id === t.biz); if (!biz) return null; const BIcon = biz.icon; return (
              <div className="flex items-center gap-1.5 ml-auto px-2 py-0.5 rounded-md"
                style={{ background: `${biz.color}0c`, border: `1px solid ${biz.color}15` }}>
                <BIcon size={10} color={biz.color} />
                <span className="text-[9px]" style={{ color: biz.color }}>{biz.label}</span>
              </div>
            ); })()}
          </div>

          {warn && (
            <motion.div className="absolute -top-1 -right-1 px-2 py-1 rounded-lg flex items-center gap-1.5 z-20"
              animate={{ boxShadow: ["0 0 6px rgba(249,115,22,0.3)", "0 0 14px rgba(249,115,22,0.6)", "0 0 6px rgba(249,115,22,0.3)"] }}
              transition={{ duration: 1.5, repeat: Infinity }}
              style={{ background: isDark ? "rgba(249,115,22,0.15)" : "rgba(249,115,22,0.1)", border: "1px solid rgba(249,115,22,0.3)" }}>
              <AlertTriangle size={10} color="#f97316" />
              <span className="text-[10px]" style={{ color: "#f97316" }}>P99: <Anim value={t.p99} decimals={1} suffix="ms" /></span>
            </motion.div>
          )}
        </motion.div>
      </motion.div>
    );
  };

  return (
    <div className="flex flex-col h-full py-5 px-3 relative" style={{ width: 320 }}>
      {/* ── Biz category tabs ── */}
      <div className="flex flex-wrap gap-1.5 px-1 mb-3 flex-shrink-0">
        {BIZ.map((b) => {
          const isActive = activeBiz === b.id;
          const Icon = b.icon;
          const count = tasks.filter(t => t.biz === b.id).length;
          return (
            <motion.button key={b.id}
              whileTap={{ scale: 0.92 }}
              onClick={() => onSelectBiz(isActive ? "all" : b.id)}
              className="flex items-center gap-2 px-2.5 py-2 rounded-xl cursor-pointer relative overflow-hidden"
              style={{
                background: isActive ? `${b.color}12` : isDark ? "rgba(255,255,255,0.02)" : "rgba(0,0,0,0.02)",
                border: `1px solid ${isActive ? `${b.color}25` : isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.04)"}`,
              }}
              transition={{ type: "spring", ...SPRING }}>
              {isActive && (
                <motion.div layoutId="bizTabGlow" className="absolute inset-0 rounded-xl"
                  style={{ background: `radial-gradient(ellipse at center, ${b.color}10, transparent 70%)` }}
                  transition={{ type: "spring", ...SPRING }} />
              )}
              <Icon size={14} color={isActive ? b.color : isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.25)"} className="relative z-10" />
              <span className="text-[11px] relative z-10"
                style={{ color: isActive ? b.color : isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.35)" }}>{b.label}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-md relative z-10"
                style={{
                  background: isActive ? `${b.color}15` : isDark ? "rgba(255,255,255,0.03)" : "rgba(0,0,0,0.03)",
                  color: isActive ? b.color : isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)",
                }}>{count}</span>
            </motion.button>
          );
        })}
      </div>

      {/* ── Sticky Genesis Anchor — always visible ── */}
      <div className="relative z-50 flex-shrink-0 mb-1">
        <div className="flex items-start gap-3 pl-0 relative">
          {/* Breathing pulse ring */}
          <motion.div
            className="absolute -inset-2 rounded-2xl pointer-events-none"
            animate={{
              boxShadow: [
                "0 0 8px rgba(59,130,246,0.0), 0 0 20px rgba(139,92,246,0.0)",
                "0 0 12px rgba(59,130,246,0.15), 0 0 30px rgba(139,92,246,0.1)",
                "0 0 8px rgba(59,130,246,0.0), 0 0 20px rgba(139,92,246,0.0)",
              ],
            }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          />

          <motion.div
            whileHover={{ scale: 1.15, boxShadow: "0 0 30px rgba(59,130,246,0.4)" }}
            whileTap={{ scale: 0.9 }}
            onClick={() => setShowCreate(!showCreate)}
            className="w-[44px] h-[44px] rounded-full flex items-center justify-center cursor-pointer relative z-10 flex-shrink-0"
            style={{
              background: "linear-gradient(135deg, #3b82f6, #8b5cf6)",
              boxShadow: "0 4px 20px rgba(59,130,246,0.35), inset 0 1px 0 rgba(255,255,255,0.2), inset 0 -1px 0 rgba(0,0,0,0.2)",
            }}
            transition={{ type: "spring", ...SPRING }}>
            <motion.div animate={{ rotate: showCreate ? 45 : 0 }} transition={{ type: "spring", ...SPRING }}>
              <Plus size={20} color="#fff" />
            </motion.div>
            {/* Glass highlight */}
            <div className="absolute top-[4px] left-[7px] w-[14px] h-[7px] rounded-full"
              style={{ background: "rgba(255,255,255,0.25)", filter: "blur(2px)" }} />
          </motion.div>
          <div className="pt-1.5 flex-1">
            <p className="text-[14px]" style={{ color: isDark ? "rgba(255,255,255,0.8)" : "rgba(0,0,0,0.8)" }}>新纪元创建</p>
            <p className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}>Genesis Anchor · 生产力起点</p>
          </div>
        </div>

        {/* ── Expandable cURL input ── */}
        <AnimatePresence>
          {showCreate && (
            <motion.div
              initial={{ height: 0, opacity: 0, marginTop: 0 }}
              animate={{ height: "auto", opacity: 1, marginTop: 8 }}
              exit={{ height: 0, opacity: 0, marginTop: 0 }}
              transition={{ type: "spring", ...SPRING }}
              className="overflow-hidden">
              <div className="rounded-2xl p-3.5 relative"
                style={{
                  background: isDark ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.5)",
                  backdropFilter: "blur(40px)",
                  border: `1px solid ${rimColor}15`,
                  boxShadow: `0 4px 20px rgba(0,0,0,0.1), 0 0 0 1px ${rimColor}08`,
                }}>
                <div className="flex items-center gap-2 mb-2.5">
                  <Terminal size={14} color={isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)"} />
                  <span className="text-[11px]" style={{ color: isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.3)" }}>cURL 解析</span>
                </div>
                <textarea value={curlText} onChange={(e) => setCurlText(e.target.value)}
                  placeholder="curl -X POST https://..."
                  className="w-full h-[60px] rounded-lg px-3 py-2.5 text-[12px] resize-none outline-none"
                  style={{
                    background: isDark ? "rgba(0,0,0,0.3)" : "rgba(0,0,0,0.03)",
                    color: isDark ? "rgba(255,255,255,0.6)" : "rgba(0,0,0,0.6)",
                    border: `1px solid ${isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.06)"}`,
                  }} />
                <div className="flex justify-end mt-2.5">
                  <motion.button whileTap={{ scale: 0.9 }}
                    className="px-4 py-1.5 rounded-lg text-[11px] text-white cursor-pointer"
                    style={{ background: "linear-gradient(135deg, #3b82f6, #8b5cf6)" }}>解析并创建</motion.button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Section label ── */}
      <div className="flex items-center justify-between px-2 mb-2 mt-2 flex-shrink-0">
        <p className="text-[11px] uppercase tracking-[0.2em]"
          style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.2)" }}>Infinite Stream</p>
        <span className="text-[10px]" style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.2)" }}>{allSorted.length} 项</span>
      </div>

      {/* ── Infinite scroll area ── */}
      <div className="flex-1 min-h-0 relative overflow-hidden flex">
        {/* The vertical nerve line */}
        <div className="absolute left-[21px] top-0 bottom-0 w-[2px] z-0"
          style={{
            background: `linear-gradient(180deg, ${rimColor}90, ${rimColor}50, ${rimColor}08)`,
            boxShadow: `0 0 10px ${rimColor}35`,
          }} />

        {/* Scrollable task stream */}
        <div ref={scrollRef}
          className="flex-1 overflow-y-auto flex flex-col gap-3 relative z-10 pr-4"
          style={{
            scrollbarWidth: "none",
            scrollBehavior: "auto",
            overscrollBehavior: "contain",
          }}>
          {isLoading ? (
            // Glass skeleton loading
            <>
              {[0, 1, 2, 3].map(i => (
                <GlassSkeleton key={i} isDark={isDark} rimColor={rimColor} index={i} />
              ))}
            </>
          ) : (
            <>
              {allSorted.map((t, i) => renderStreamCard(t, i))}
              {/* Bottom padding for overscroll */}
              <div className="h-[60px] flex-shrink-0" />
            </>
          )}
        </div>

        {/* Top refraction fade - cards disappear "behind" the anchor */}
        <div className="absolute top-0 left-0 right-4 h-[40px] pointer-events-none z-20"
          style={{ background: `linear-gradient(to bottom, ${isDark ? "rgba(10,10,10,0.7)" : "rgba(245,245,247,0.7)"}, transparent)` }} />

        {/* Bottom fade */}
        <div className="absolute bottom-0 left-0 right-4 h-[50px] pointer-events-none z-20"
          style={{ background: `linear-gradient(to top, ${isDark ? "rgba(10,10,10,0.6)" : "rgba(245,245,247,0.6)"}, transparent)` }} />

        {/* ── Floating Time Progress Bar ── */}
        
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════
   MAIN EXPORT — Spatial Refraction Layout
   ══════════════════════════════════════════════════════════════ */
export function PerformanceStage() {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const rimColor = useRimColor();
  const [activeBiz, setActiveBiz] = useState("all");
  const [selectedDate, setSelectedDate] = useState(new Date().getDate());
  const [focusedTask, setFocusedTask] = useState<string | null>(null);

  const taskDates = useMemo(() => new Set(TASKS.map(t => t.date)), []);
  const filteredTasks = TASKS;

  // DOF: when hovering a timeline task, blur the left columns
  const dofActive = focusedTask !== null;

  /* Shared glass style generator for panels */
  const panelGlass = (extra: React.CSSProperties = {}): React.CSSProperties => ({
    background: isDark ? "rgba(255,255,255,0.025)" : "rgba(255,255,255,0.45)",
    backdropFilter: "blur(80px)",
    WebkitBackdropFilter: "blur(80px)",
    borderRadius: "24px",
    boxShadow: `
      inset 0 1px 0 0 rgba(255,255,255,${isDark ? 0.06 : 0.6}),
      inset 0 -1px 0 0 rgba(0,0,0,${isDark ? 0.08 : 0.02}),
      0 8px 40px rgba(0,0,0,${isDark ? 0.2 : 0.06}),
      0 0 0 1px ${rimColor}08
    `,
    border: `1px solid ${rimColor}${isDark ? "0a" : "12"}`,
    ...extra,
  });

  return (
    <div className="w-full h-full flex items-stretch gap-2.5 overflow-hidden">
      {/* Column 1: Chronos Nerve */}
      <div className="flex-shrink-0 overflow-hidden" style={panelGlass()}>
        <ChronosNerve isDark={isDark} tasks={filteredTasks} rimColor={rimColor} onFocus={setFocusedTask} activeBiz={activeBiz} onSelectBiz={setActiveBiz} />
      </div>

      {/* Column 2: Metrics & Consumption */}
      <motion.div
        className="flex-1 min-w-0 overflow-hidden"
        style={panelGlass()}
        animate={{ filter: dofActive ? "blur(1px)" : "blur(0px)", opacity: dofActive ? 0.8 : 1 }}
        transition={{ duration: 0.4 }}>
        <MetricsColumn isDark={isDark} tasks={filteredTasks} focusedTask={focusedTask} rimColor={rimColor} selectedDate={selectedDate} onSelectDate={setSelectedDate} />
      </motion.div>

      {/* Column 3: Temporal & Personnel */}
      <motion.div
        className="flex-shrink-0 overflow-hidden"
        style={panelGlass()}
        animate={{ filter: dofActive ? "blur(1.5px)" : "blur(0px)", opacity: dofActive ? 0.75 : 1 }}
        transition={{ duration: 0.4 }}>
        <TemporalColumn isDark={isDark} selectedDate={selectedDate} onSelectDate={setSelectedDate}
          rimColor={rimColor} taskDates={taskDates} focusedTask={focusedTask} tasks={filteredTasks} />
      </motion.div>
    </div>
  );
}

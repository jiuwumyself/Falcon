import { useState, useRef, useEffect } from "react";
import {
  motion,
  AnimatePresence,
  useMotionValue,
  useScroll,
  useTransform,
  useMotionValueEvent,
  useInView,
} from "motion/react";
import { FalconLogo } from "./falcon-logo";
import { useTheme } from "./theme-context";
import { PerformanceStage } from "./performance-stage";
import {
  Sun, Moon, Activity, Zap, Globe, TrendingUp, Eye, ArrowDown,
} from "lucide-react";

/* ─── Data ─── */
const PERF_DATA = {
  taskVolume: 12847, dispatchCount: 3216, successRate: 97.3, meanConcurrency: 842,
  successTrend: [96.1, 97.8, 95.2, 98.4, 94.7, 97.1, 96.5, 98.9, 97.3, 97.3],
  concurrencyTrend: [720, 810, 650, 890, 760, 830, 920, 780, 860, 842],
};
const UI_DATA = {
  taskVolume: 5234, dispatchCount: 1489, successRate: 93.8, meanConcurrency: 128,
  successTrend: [91.2, 94.5, 92.8, 95.1, 90.3, 93.7, 94.2, 92.1, 93.8, 93.8],
  concurrencyTrend: [110, 135, 98, 142, 120, 130, 115, 145, 125, 128],
};
const API_DATA = {
  taskVolume: 28493, dispatchCount: 7832, successRate: 99.1, meanConcurrency: 2140,
  successTrend: [98.7, 99.2, 98.9, 99.5, 99.1, 98.8, 99.3, 99.0, 99.4, 99.1],
  concurrencyTrend: [1980, 2050, 2200, 1890, 2100, 2300, 2050, 2180, 2090, 2140],
};

const MODULES = [
  { id: "performance", title: "性能板块", subtitle: "Load Dynamics", icon: Zap,
    color: "#3b82f6", colorEnd: "#60a5fa", data: PERF_DATA, desc: "全链路压测的实时律动", index: "01" },
  { id: "ui", title: "UI 板块", subtitle: "Visual Integrity", icon: Eye,
    color: "#8b5cf6", colorEnd: "#a78bfa", data: UI_DATA, desc: "极致对称的组件设计", index: "02" },
  { id: "api", title: "接口板块", subtitle: "Connectivity Sync", icon: Globe,
    color: "#10b981", colorEnd: "#34d399", data: API_DATA, desc: "最纯粹的测试底色", index: "03" },
];

const METRICS = [
  { key: "taskVolume", label: "任务总量", en: "Tasks", decimals: 0 },
  { key: "dispatchCount", label: "调度频次", en: "Dispatch", decimals: 0 },
  { key: "successRate", label: "达标率", en: "Success", decimals: 1, suffix: "%" },
  { key: "meanConcurrency", label: "均值负载", en: "Concurrency", decimals: 0 },
];

/* ─── AnimatedNumber ─── */
function AnimNum({ value, suffix = "", decimals = 0, trigger }: {
  value: number; suffix?: string; decimals?: number; trigger: boolean;
}) {
  const [d, setD] = useState("0");
  const ran = useRef(false);
  useEffect(() => {
    if (!trigger || ran.current) return;
    ran.current = true;
    const s = performance.now();
    const go = (now: number) => {
      const p = Math.min((now - s) / 1400, 1);
      const e = 1 - Math.pow(1 - p, 4);
      setD(decimals > 0 ? (e * value).toFixed(decimals) : Math.floor(e * value).toLocaleString());
      if (p < 1) requestAnimationFrame(go);
    };
    requestAnimationFrame(go);
  }, [trigger, value, decimals]);
  return <span>{d}{suffix}</span>;
}

/* ─── Sparkline ─── */
function Spark({ data, color, w = 280, h = 56, threshold = 95, uid = "x" }: {
  data: number[]; color: string; w?: number; h?: number; threshold?: number; uid?: string;
}) {
  const mn = Math.min(...data) - 1, mx = Math.max(...data) + 1, rg = mx - mn;
  const pts = data.map((v, i) => ({ x: (i / (data.length - 1)) * w, y: h - ((v - mn) / rg) * h, v }));
  const pathD = pts.reduce((a, p, i) => {
    if (!i) return `M ${p.x} ${p.y}`;
    const prev = pts[i - 1], cpx = (prev.x + p.x) / 2;
    return `${a} C ${cpx} ${prev.y}, ${cpx} ${p.y}, ${p.x} ${p.y}`;
  }, "");
  const lava = "#f97316";
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="overflow-visible">
      <defs>
        <linearGradient id={`g${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.2} /><stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
        <filter id={`f${uid}`}><feGaussianBlur stdDeviation="3" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      <path d={`${pathD} L ${w} ${h} L 0 ${h} Z`} fill={`url(#g${uid})`} />
      {pts.map((p, i) => {
        if (!i) return null;
        const prev = pts[i - 1], cpx = (prev.x + p.x) / 2;
        const bad = threshold > 0 && (p.v < threshold || prev.v < threshold);
        return <path key={i} d={`M ${prev.x} ${prev.y} C ${cpx} ${prev.y}, ${cpx} ${p.y}, ${p.x} ${p.y}`}
          fill="none" stroke={bad ? lava : color} strokeWidth={2.5} filter={`url(#f${uid})`} />;
      })}
      {pts.map((p, i) => <circle key={i} cx={p.x} cy={p.y} r={2.5}
        fill={threshold > 0 && p.v < threshold ? lava : color} opacity={0.9} />)}
    </svg>
  );
}

/* ─── GlassNav ─── */
function GlassNav({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-[28px] relative overflow-hidden ${className}`}
      style={{
        background: "var(--card)", backdropFilter: "blur(48px)", WebkitBackdropFilter: "blur(48px)",
        boxShadow: "inset 0 1px 0 0 rgba(255,255,255,0.08), 0 8px 32px rgba(0,0,0,0.12), 0 0 0 1px rgba(255,255,255,0.06)",
        border: "1px solid rgba(255,255,255,0.06)",
      }}>
      {children}
    </div>
  );
}

/* ─── Zoom Tunnel Section ─── */
function ZoomSection({ mod, scrollContainer }: { mod: typeof MODULES[0]; scrollContainer: React.RefObject<HTMLDivElement | null> }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { amount: 0.35 });
  const isDark = useTheme().theme === "dark";
  const Icon = mod.icon;
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      if (scrollContainer.current && ref.current) setMounted(true);
    });
    return () => cancelAnimationFrame(raf);
  }, [scrollContainer]);
  const { scrollYProgress } = useScroll(mounted
    ? { target: ref, container: scrollContainer, offset: ["start end", "end start"] }
    : {}
  );

  const scale = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], [0.5, 1, 1, 1.5]);
  const opacity = useTransform(scrollYProgress, [0, 0.3, 0.7, 1], [0, 1, 1, 0]);
  const blur = useTransform(scrollYProgress, [0, 0.35, 0.65, 1], [30, 0, 0, 20]);
  const blurStr = useTransform(blur, v => `blur(${v}px)`);
  const rotateX = useTransform(scrollYProgress, [0, 0.4, 0.6, 1], [15, 0, 0, -10]);

  return (
    <div ref={ref} className="h-screen flex-shrink-0 snap-start relative overflow-hidden"
      style={{ perspective: "1200px" }}>
      {[0.3, 0.5, 0.7].map((d, i) => (
        <motion.div key={i} className="absolute inset-0 flex items-center justify-center pointer-events-none"
          style={{ opacity: useTransform(scrollYProgress, [d - 0.15, d, d + 0.15], [0, 0.15, 0]) }}>
          <div className="rounded-full border" style={{
            width: `${300 + i * 200}px`, height: `${300 + i * 200}px`,
            borderColor: `${mod.color}15`,
          }} />
        </motion.div>
      ))}

      <motion.div className="h-full flex items-center justify-center px-8 lg:px-16"
        style={{ scale, opacity, filter: blurStr, rotateX, transformOrigin: "center center" }}>
        <div className="w-full max-w-[1000px] text-center">
          <motion.div className="mb-10"
            initial={{ opacity: 0, scale: 0.3 }} animate={inView ? { opacity: 1, scale: 1 } : {}}
            transition={{ type: "spring", stiffness: 150, damping: 15 }}>
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-3xl mb-5 relative"
              style={{ background: `${mod.color}10` }}>
              <Icon size={32} color={mod.color} />
              <motion.div className="absolute inset-0 rounded-3xl"
                animate={inView ? { boxShadow: [`0 0 0px ${mod.color}00`, `0 0 50px ${mod.color}20`, `0 0 0px ${mod.color}00`] } : {}}
                transition={{ duration: 3, repeat: Infinity }} />
            </div>
            <div className="flex items-center justify-center gap-3 mb-3">
              <div className="h-[1px] w-8" style={{ background: `${mod.color}30` }} />
              <span className="text-[11px] tracking-[0.3em] uppercase" style={{ color: `${mod.color}80` }}>{mod.index}</span>
              <div className="h-[1px] w-8" style={{ background: `${mod.color}30` }} />
            </div>
            <h2 className="text-[40px] lg:text-[56px] tracking-tight"
              style={{ color: isDark ? "#fff" : "#1a1a2e" }}>{mod.title}</h2>
            <p className="text-[13px] mt-2"
              style={{ color: isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.35)" }}>{mod.subtitle}</p>
          </motion.div>

          <div className="flex justify-center gap-6 lg:gap-12 mb-10 flex-wrap">
            {METRICS.map((m, mi) => (
              <motion.div key={m.key}
                initial={{ opacity: 0, scale: 0.5 }} animate={inView ? { opacity: 1, scale: 1 } : {}}
                transition={{ delay: 0.15 + mi * 0.08, type: "spring", stiffness: 200 }}
                className="min-w-[120px] rounded-2xl p-4 lg:p-5"
                style={{ background: isDark ? "rgba(255,255,255,0.025)" : "rgba(0,0,0,0.02)",
                  border: `1px solid ${isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)"}` }}>
                <p className="text-[30px] lg:text-[36px] tracking-tighter leading-none"
                  style={{ color: isDark ? "#fff" : "#1a1a2e" }}>
                  <AnimNum value={(mod.data as any)[m.key]} decimals={m.decimals} suffix={m.suffix} trigger={inView} />
                </p>
                <p className="text-[9px] mt-2 uppercase tracking-wider"
                  style={{ color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)" }}>{m.label}</p>
              </motion.div>
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8 max-w-[700px] mx-auto">
            <motion.div initial={{ opacity: 0, y: 30 }} animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ delay: 0.5 }}>
              <p className="text-[10px] mb-3 flex items-center justify-center gap-1.5 uppercase tracking-wider"
                style={{ color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)" }}>
                <TrendingUp size={10} /> 成功率
              </p>
              <Spark data={mod.data.successTrend} color={mod.color} uid={`s-${mod.id}`} />
            </motion.div>
            <motion.div initial={{ opacity: 0, y: 30 }} animate={inView ? { opacity: 1, y: 0 } : {}}
              transition={{ delay: 0.6 }}>
              <p className="text-[10px] mb-3 flex items-center justify-center gap-1.5 uppercase tracking-wider"
                style={{ color: isDark ? "rgba(255,255,255,0.25)" : "rgba(0,0,0,0.3)" }}>
                <Activity size={10} /> 并发
              </p>
              <Spark data={mod.data.concurrencyTrend} color={mod.colorEnd} threshold={-1} uid={`c-${mod.id}`} />
            </motion.div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

/* ─── Scroll Dots ─── */
function ScrollDots({ active, total, colors }: { active: number; total: number; colors: string[] }) {
  const isDark = useTheme().theme === "dark";
  return (
    <div className="fixed right-5 top-1/2 -translate-y-1/2 z-40 flex flex-col gap-3">
      {Array.from({ length: total }).map((_, i) => (
        <motion.div key={i} className="w-2 rounded-full"
          animate={{
            height: active === i ? 28 : 8,
            background: active === i ? colors[i] : isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)",
            boxShadow: active === i ? `0 0 10px ${colors[i]}40` : "none",
          }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }} />
      ))}
    </div>
  );
}

/* ─── Hero Section ─── */
function HeroSection({ isDark }: { isDark: boolean }) {
  return (
    <div className="h-screen flex-shrink-0 snap-start flex items-center justify-center relative">
      <div className="text-center px-5 max-w-[700px]">
        <motion.div className="mb-8 flex justify-center"
          initial={{ opacity: 0, scale: 0.6, rotate: -10 }}
          animate={{ opacity: 1, scale: 1, rotate: 0 }}
          transition={{ duration: 1, type: "spring" }}>
          <FalconLogo size={64} />
        </motion.div>
        <motion.p className="text-[11px] tracking-[0.3em] uppercase mb-4"
          style={{ color: isDark ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.25)" }}
          initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
          Falcon Eyes · 全链路质量洞察中心
        </motion.p>
        <motion.h1 className="text-[40px] lg:text-[56px] tracking-tight leading-tight"
          style={{ color: isDark ? "#fff" : "#1a1a2e" }}
          initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4, type: "spring", stiffness: 60 }}>
          每一次请求
          <br />
          <span style={{ background: "linear-gradient(135deg, #3b82f6, #8b5cf6, #10b981)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>都值得被守护</span>
        </motion.h1>
        <motion.p className="text-[14px] mt-5 max-w-[420px] mx-auto"
          style={{ color: isDark ? "rgba(255,255,255,0.3)" : "rgba(0,0,0,0.35)" }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.7 }}>质量的尽头，是信任</motion.p>
        <motion.div className="mt-14 flex flex-col items-center gap-2"
          animate={{ y: [0, 8, 0] }} transition={{ duration: 2.5, repeat: Infinity }}>
          <span className="text-[10px] tracking-[0.2em]"
            style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }}>SCROLL TO EXPLORE</span>
          <ArrowDown size={14} style={{ color: isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)" }} />
        </motion.div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════ */
/*            MAIN PAGE                   */
/* ══════════════════════════════════════ */
const NAV_ITEMS = [
  { id: "home", label: "概览" },
  { id: "performance", label: "性能板块" },
  { id: "ui", label: "UI 板块" },
  { id: "api", label: "接口板块" },
];

const DOT_COLORS = ["rgba(255,255,255,0.4)", "#3b82f6", "#8b5cf6", "#10b981"];

export function HomePage() {
  const [activeTab, setActiveTab] = useState("home");
  const [activeSection, setActiveSection] = useState(0);
  const { theme, toggleTheme } = useTheme();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [sliderStyle, setSliderStyle] = useState({ left: 0, width: 0 });
  const scrollRef = useRef<HTMLDivElement>(null);
  const isDark = theme === "dark";
  const [scrollMounted, setScrollMounted] = useState(false);

  useEffect(() => {
    if (activeTab === "home") {
      // Wait a tick for the DOM to render
      const raf = requestAnimationFrame(() => {
        if (scrollRef.current) setScrollMounted(true);
      });
      return () => { cancelAnimationFrame(raf); setScrollMounted(false); };
    } else {
      setScrollMounted(false);
    }
  }, [activeTab]);

  const { scrollYProgress } = useScroll(scrollMounted ? { container: scrollRef } : {});
  useMotionValueEvent(scrollYProgress, "change", (v) => {
    setActiveSection(Math.min(Math.round(v * 3), 3));
  });

  const updateSlider = (id: string) => {
    const el = tabRefs.current[id];
    if (el) setSliderStyle({ left: el.offsetLeft, width: el.offsetWidth });
  };
  const handleTabChange = (id: string) => { setActiveTab(id); updateSlider(id); };
  const setTabRef = (id: string) => (el: HTMLButtonElement | null) => {
    tabRefs.current[id] = el;
    if (id === activeTab && el && sliderStyle.width === 0) setTimeout(() => updateSlider(id), 50);
  };

  return (
    <div className="h-screen overflow-hidden transition-colors duration-500 relative"
      style={{ background: isDark ? "#0A0A0A" : "#F5F5F7" }}>

      {isDark && (
        <>
          <div className="fixed top-0 left-1/4 w-[600px] h-[600px] pointer-events-none"
            style={{ background: "radial-gradient(ellipse, rgba(59,130,246,0.04) 0%, transparent 70%)" }} />
          <div className="fixed bottom-0 right-1/4 w-[500px] h-[500px] pointer-events-none"
            style={{ background: "radial-gradient(ellipse, rgba(124,58,237,0.03) 0%, transparent 70%)" }} />
        </>
      )}

      {/* ── Command Island ── */}
      <div className="fixed top-5 left-1/2 -translate-x-1/2 z-50 w-[calc(100%-40px)] max-w-[900px]">
        <GlassNav>
          <div className="flex items-center justify-between px-4 py-2.5">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 pr-4 border-r border-white/[0.06]">
                <FalconLogo size={26} />
                <span className="text-[13px] tracking-tight hidden sm:block"
                  style={{ color: isDark ? "#fff" : "#1a1a2e" }}>Falcon Eyes</span>
              </div>
              <div className="relative flex rounded-2xl p-1"
                style={{ background: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)" }}>
                <motion.div className="absolute top-1 h-[calc(100%-8px)] rounded-[14px]"
                  animate={{ left: sliderStyle.left, width: sliderStyle.width }}
                  transition={{ type: "spring", stiffness: 400, damping: 30 }}
                  style={{ background: isDark ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.8)",
                    boxShadow: isDark ? "0 2px 8px rgba(0,0,0,0.2)" : "0 2px 8px rgba(0,0,0,0.06)" }} />
                {NAV_ITEMS.map((item) => (
                  <button key={item.id} ref={setTabRef(item.id)} onClick={() => handleTabChange(item.id)}
                    className="relative z-10 px-4 py-1.5 rounded-[14px] text-[12px] transition-colors duration-200 cursor-pointer whitespace-nowrap"
                    style={{ color: activeTab === item.id
                      ? isDark ? "#fff" : "#1a1a2e"
                      : isDark ? "rgba(255,255,255,0.4)" : "rgba(0,0,0,0.4)" }}>
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <motion.button whileTap={{ scale: 0.9 }} onClick={toggleTheme}
                className="w-9 h-9 rounded-full flex items-center justify-center cursor-pointer"
                style={{ background: isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)" }}>
                <AnimatePresence mode="wait">
                  <motion.div key={theme} initial={{ rotate: -90, opacity: 0 }}
                    animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }} transition={{ duration: 0.2 }}>
                    {isDark ? <Moon size={15} color="#93c5fd" /> : <Sun size={15} color="#f59e0b" />}
                  </motion.div>
                </AnimatePresence>
              </motion.button>
              <div className="relative">
                <motion.div className="absolute -inset-1 rounded-full"
                  animate={{ opacity: [0.3, 0.7, 0.3] }} transition={{ duration: 3, repeat: Infinity }}
                  style={{ background: "conic-gradient(from 0deg, #3b82f6, #7c3aed, #3b82f6)", filter: "blur(3px)" }} />
                <div className="relative w-9 h-9 rounded-full flex items-center justify-center text-[12px] text-white"
                  style={{ background: "linear-gradient(135deg, #3b82f6, #7c3aed)",
                    border: `2px solid ${isDark ? "#0A0A0A" : "#F5F5F7"}` }}>FE</div>
              </div>
            </div>
          </div>
        </GlassNav>
      </div>

      {/* ── Content ── */}
      <AnimatePresence mode="wait">
        {activeTab === "home" && (
          <motion.div key="home" className="h-full" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <ScrollDots active={activeSection} total={4} colors={DOT_COLORS} />
            <div ref={scrollRef} className="h-full overflow-y-auto relative"
              style={{ scrollSnapType: "y mandatory", scrollBehavior: "smooth" }}>
              <HeroSection isDark={isDark} />
              {MODULES.map((mod) => (
                <ZoomSection key={mod.id} mod={mod} scrollContainer={scrollRef} />
              ))}
            </div>
          </motion.div>
        )}

        {activeTab === "performance" && (
          <motion.div key="perf" className="h-full overflow-visible pt-20 px-4 pb-4"
            initial={{ opacity: 0, scale: 0.98, filter: "blur(8px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            exit={{ opacity: 0, scale: 1.02, filter: "blur(8px)" }}
            transition={{ duration: 0.45, ease: "easeOut" }}>
            <div className="w-full h-full px-2">
              <PerformanceStage />
            </div>
          </motion.div>
        )}

        {activeTab === "ui" && (
          <motion.div key="ui" className="h-full overflow-y-auto pt-24 px-5 pb-16"
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.3 }}>
            <div className="max-w-[1100px] mx-auto">
              <div className="mb-8 mt-2">
                <h1 className="text-[28px] tracking-tight" style={{ color: isDark ? "#fff" : "#1a1a2e" }}>UI 板块</h1>
                <p className="text-[13px] mt-1" style={{ color: isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.4)" }}>
                  User Interface testing & monitoring</p>
              </div>
              <GlassNav className="p-10 flex flex-col items-center justify-center min-h-[400px]">
                <div className="w-16 h-16 rounded-3xl flex items-center justify-center mb-4"
                  style={{ background: "rgba(139,92,246,0.1)" }}><Eye size={28} color="#8b5cf6" /></div>
                <p className="text-[15px]" style={{ color: isDark ? "#fff" : "#1a1a2e" }}>UI Testing Suite</p>
                <p className="text-[12px] mt-2 text-center max-w-[300px]"
                  style={{ color: isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.4)" }}>
                  Build, run and monitor automated UI test scenarios.</p>
              </GlassNav>
            </div>
          </motion.div>
        )}

        {activeTab === "api" && (
          <motion.div key="api" className="h-full overflow-y-auto pt-24 px-5 pb-16"
            initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.3 }}>
            <div className="max-w-[1100px] mx-auto">
              <div className="mb-8 mt-2">
                <h1 className="text-[28px] tracking-tight" style={{ color: isDark ? "#fff" : "#1a1a2e" }}>接口板块</h1>
                <p className="text-[13px] mt-1" style={{ color: isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.4)" }}>
                  Automated API testing & monitoring</p>
              </div>
              <GlassNav className="p-10 flex flex-col items-center justify-center min-h-[400px]">
                <div className="w-16 h-16 rounded-3xl flex items-center justify-center mb-4"
                  style={{ background: "rgba(139,92,246,0.1)" }}><Globe size={28} color="#8b5cf6" /></div>
                <p className="text-[15px]" style={{ color: isDark ? "#fff" : "#1a1a2e" }}>API Testing Suite</p>
                <p className="text-[12px] mt-2 text-center max-w-[300px]"
                  style={{ color: isDark ? "rgba(255,255,255,0.35)" : "rgba(0,0,0,0.4)" }}>
                  Build, run and monitor automated API test scenarios.</p>
              </GlassNav>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
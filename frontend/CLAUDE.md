# Falcon 前端上下文

> 根目录 `CLAUDE.md` 已覆盖整体项目信息。本文件只写**前端子项目专属的约定、细节和踩坑点**。

## 1. 技术栈要点

- **Vue 3.5** + **TypeScript 6** + **Vite 8**
- **Tailwind v4**（注意：**没有** `tailwind.config.js`！）
- **motion-v 2.2**（Vue 版 framer-motion）
- **vue-router 4**
- **lucide-vue-next**（图标）
- **@guolao/vue-monaco-editor** + **monaco-editor**（只读展示 JMX XML）
- **echarts** + **vue-echarts**（Step 2 线程组预览曲线 + 将来 Step 3 实时监控；按需引入 LineChart）
- **reka-ui**（已装但暂未用，需要 headless 基础组件时用）
- **@vueuse/core**、**clsx** + **tailwind-merge**（`cn()` 工具）

## 2. 入口与路由流

```
main.ts  →  App.vue (RouterView)
             │
             └─ layouts/AppLayout.vue       ← provideTheme() 在这里注入
                 │
                 ├─ pages/LoginPage.vue     (path: /)
                 └─ layouts/MainLayout.vue  ← 顶栏 nav + <RouterView> 包几个顶级平级 page
                     │
                     ├─ pages/HomePage.vue       (path: /home)       — 概览
                     ├─ pages/PerformancePage.vue (path: /performance) — 性能板块
                     ├─ pages/TasksPage.vue      (path: /performance/tasks) — wizard 整页接管
                     ├─ pages/UIPage.vue         (path: /ui)         — 占位
                     └─ pages/APIPage.vue        (path: /api)        — 占位
```

**路由顶级平级**（2026-04-23 调整）：`/home` / `/performance` / `/ui` / `/api` 四个板块**不嵌套**（旧版用 `/home` 一个路由 + 内部 tab state 切换，刷新会丢失当前 tab，已改）。顶栏 nav 是**路由驱动**的：active tab 由 `useRoute().name` 决定；路由里含 `performance-tasks` 也归到"性能"tab active。

**路由无 auth guard**。登录页表单提交后 `setTimeout 600ms → router.push('/home')`，没有任何鉴权。

**任务创建入口**：进 `/performance` → 左列 ChronosNerve 顶部那个渐变色大 "+" 按钮 → `router.push('/performance/tasks')` → TasksPage 加载 `TaskCreateWizard`；wizard 的 close 事件 `router.push('/performance')` 回性能页。Wizard 内部 step 是 ref state，**不改 URL**（/performance/tasks 是单一路由）。

**任务编辑入口**（2026-04-28）：性能板块 ChronosNerve 任务卡 `@click` → `router.push('/performance/tasks?id=N')` → `TasksPage` `onMounted` 拉 `tasksApi.get(id)` → 把 task 作 `initialTask` prop 喂给 wizard → wizard 跳到最远完成的 Step（`thread_groups_config` 非空 → Step 2，否则 Step 1）。

**右键删除**：ChronosNerve 任务卡 `@contextmenu.prevent="emit('contextTask', id, x, y)"` → PerformanceStage 弹 `<TaskContextMenu>` 浮层 → 点删除 confirm → `tasksApi.delete(id)` → 重拉列表。

**后台入口**：`MainLayout` 顶栏右侧主题切换按钮和头像之间，加 Settings 齿轮，新 tab 打开 `/admin/`（让用户去管理 Environment 等模型）。

## 3. 目录约定

| 目录 | 放什么 | 举例 |
|---|---|---|
| `src/pages/` | 顶层页面，被路由直接加载 | `LoginPage.vue`、`HomePage.vue`、`PerformancePage.vue`、`TasksPage.vue`、`UIPage.vue`、`APIPage.vue` |
| `src/layouts/` | 布局壳，包 `<RouterView />` | `AppLayout.vue`（仅 provideTheme）、`MainLayout.vue`（顶栏 nav + 4 个板块 page 容器） |
| `src/components/` | **跨页共用**的组件 | `FalconLogo.vue`、`GlassNav.vue`、`PerformanceStage.vue` |
| `src/components/tasks/` | 任务创建/编辑相关 | `TaskCreateWizard.vue`（5 步向导）、`ScriptTree.vue`/`ComponentNode.vue`（Step 1 组件树，CSVDataSet 行内 Paperclip + BeanShellPre 行内 JAR Package 上传）、`DetailDrawer.vue` + `detail/*.vue`（8 种可编辑组件的抽屉表单）、`ConfigStage.vue` + `config/*.vue`（Step 2 任务配置）、`scriptTreeCtx.ts` / `configStageCtx.ts` |
| `src/components/tasks/config/` | Step 2 子组件（v2 场景驱动） | `ScenarioTabs.vue`（6 个场景 pill + 说明条）、`ThreadGroupPicker.vue`（多 TG 时显示的切换器）、`TgParamsForm.vue`（参数表单，字段随 kind 自适应）、`ThreadGroupChart.vue`（echarts 线图）、`EnvironmentPicker.vue`（环境下拉）、`ValidateResultTable.vue`（校验结果表，含未解析变量警告） |
| `src/components/home/` | HomePage 专属子组件 | `HeroSection`、`ZoomSection`、`ScrollDots` |
| `src/components/perf/` | PerformanceStage 专属（**ChronosNerve 已接真任务列表**；其他列暂仍 mock） | `ChronosNerve`、`MetricsColumn`、`TemporalColumn`、`TaskContextMenu`（右键删除浮层）、`data.ts`、`useRimColor.ts` |
| `src/composables/` | Vue composable（`useXxx`） | `useTheme.ts` |
| `src/lib/` | 纯 TS 工具，无 Vue 依赖 | `api.ts`（fetch 封装）、`utils.ts` 的 `cn()` |
| `src/types/` | 共享 TypeScript 类型 | `task.ts`（Task / TaskRun / Paginated / JmxComponent） |
| `src/router/` | 路由配置 | `index.ts` |

**新组件落位原则**：先判断是否跨页共用，只有一个页面用的就放到 `components/<页面名>/`。

## 4. 样式系统（Tailwind v4 关键差异）

### 4.1 没有配置文件
Tailwind v4 抛弃了 `tailwind.config.js`，所有自定义都写在 CSS 里。当前项目的配置都集中在 `src/style.css`：

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:...');
@import "tailwindcss";

@custom-variant dark (&:is(.dark *));   /* 自定义 dark variant */

:root { --background: #F5F5F7; ... }     /* 浅色 CSS 变量 */
.dark { --background: #0A0A0A; ... }     /* 深色覆盖 */

@theme inline {
  --font-sans: 'Inter', ...;
  --color-background: var(--background); /* 让 bg-background 生效 */
  ...
}
```

### 4.2 要加颜色/字体/圆角时
**不要**去找 config 文件——改 `style.css` 里的 `@theme inline` 块，或者先加 `--my-token` CSS 变量，再在 `@theme inline` 里映射成 `--color-my-token`。

### 4.3 Google Fonts `@import url(...)` 必须在 `@import "tailwindcss"` 之前
否则会报 "must precede all rules" 警告。

### 4.4 `cn()` 用法
```ts
import { cn } from '@/lib/utils'
<div :class="cn('rounded-md px-2', props.class)">
```
内部是 `twMerge(clsx(...))`，可以安全合并 Tailwind class（后者覆盖前者）。

## 5. motion-v 用法（最容易踩坑的地方）

### 5.1 组件写法
React 用 `<motion.div>`，**Vue 里写不出来**。改用通用的 `<Motion>`：

```vue
<Motion as="div" :initial="{opacity: 0}" :animate="{opacity: 1}" :transition="{duration: 0.6}">
  ...
</Motion>
```

- `as="div"` / `as="button"` / `as="svg"` / `as="circle"` / `as="p"` 等任何 HTML/SVG 标签
- **省略 `as`** 时默认是 `div`

### 5.2 Props 语法
- Vue 语法，用 `:` 绑定：`:initial`、`:animate`、`:exit`、`:transition`
- Hover/Tap：`:while-hover`、`:while-tap`（**不是** `whileHover`，Vue 会自动 kebab-case）
- 条件动画：`:animate="inView ? {...} : {}"`

### 5.3 常用 API 导入
```ts
import {
  Motion, AnimatePresence,
  useScroll, useTransform, useMotionValue, useMotionValueEvent, useInView,
} from 'motion-v'
```

### 5.4 `useScroll` + `useTransform` 典型用法
```ts
const sectionRef = ref<HTMLElement | null>(null)
const { scrollYProgress } = useScroll({
  target: sectionRef,
  container: scrollContainerRef,
  offset: ['start end', 'end start'],
})
const scale = useTransform(scrollYProgress, [0, 0.5, 1], [0.5, 1, 1.5])
// 在模板里直接绑到 :style="{ scale }"
```

在模板里把 `MotionValue` 直接塞 `:style` 即可，`<Motion>` 会自动订阅更新——**不需要** `.value`。

### 5.5 `useInView`
```ts
const elRef = ref<HTMLElement | null>(null)
const inView = useInView(elRef, { amount: 0.35 })  // 返回 Ref<boolean>
// 模板里 inView 会自动 unwrap，直接用
```

### 5.6 `AnimatePresence`
用法跟 React 版一样，要给孩子一个 `key`：

```vue
<AnimatePresence mode="wait">
  <Motion v-if="show" key="a" :exit="{opacity: 0}">...</Motion>
  <Motion v-else key="b" :exit="{opacity: 0}">...</Motion>
</AnimatePresence>
```

## 6. 主题系统

### 6.1 定义
`src/composables/useTheme.ts`：provide/inject + `watchEffect` 切换 `<html>` 的 `.dark` class。

### 6.2 用法
```vue
<script setup>
import { useTheme } from '@/composables/useTheme'
import { computed } from 'vue'

const { theme, toggleTheme } = useTheme()
const isDark = computed(() => theme.value === 'dark')
</script>
```

**约束**：`useTheme()` 必须在 `<AppLayout>` 子树下调用（`AppLayout.vue` 里调了 `provideTheme()`）。

### 6.3 两种着色方式混用
项目同时有两种上色做法，**不要统一**，按场景选：
- **Tailwind class**：`bg-background text-foreground` 这类语义色（自动跟 `.dark` 走）
- **内联 `:style` 条件色**：`:style="{ color: isDark ? '#fff' : '#1a1a2e' }"`（figma 设计很多半透明色，Tailwind class 写起来不如 `rgba()` 直接）

## 7. 图标

`lucide-vue-next`：

```vue
<script setup>
import { Sun, Moon } from 'lucide-vue-next'
</script>
<template>
  <Sun :size="16" color="#f59e0b" />
  <!-- 动态选择用 component :is -->
  <component :is="isDark ? Moon : Sun" :size="15" />
</template>
```

## 8. Path alias

`@/` → `src/`（配置在 `vite.config.ts` 和 `tsconfig.app.json`）。统一用 `@/...`，**不要用相对路径 `../../`**。

```ts
import FalconLogo from '@/components/FalconLogo.vue'
import { useTheme } from '@/composables/useTheme'
```

## 9. 与后端的联调

`vite.config.ts` 已配代理：

```ts
proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } }
```

前端发 `fetch('/api/performance/tasks/')` 就行，不用写全地址，开发时 Vite 自动转发到 Django。

### 封装好的 API helper

`src/lib/api.ts` 导出：

```ts
import { api, apiForm, ApiError } from '@/lib/api'

// JSON 请求
const tasks = await api<Paginated<Task>>('/tasks/')
await api(`/tasks/${id}/`, { method: 'PATCH', body: JSON.stringify({ virtual_users: 100 }) })

// multipart/form-data（上传文件）
const fd = new FormData()
fd.append('jmx_file', file)
await apiForm<Task>('/tasks/', fd)
```

`api()` 自动拼 `/api/performance` 前缀（见 `api.ts` 的 `BASE` 常量——后端按板块拆 app 后所有端点都在 `/api/performance/...` 下）、set JSON Content-Type、非 2xx 抛 `ApiError`（含 `.status`、`.body` 原文、`.humanMessage` 解析好的人读文案——**优先用 humanMessage**，把 `{"jmx_file":["仅支持 .jmx 文件"]}` 渲染成 `jmx_file: 仅支持 .jmx 文件`）。**不要** 在这里加 token/auth 逻辑——v1 平台无认证。

> **多板块演进**：以后做 UI 板块 / 接口板块会有 `/api/uiauto/...` 和 `/api/apitest/...`，届时把 `api.ts` 拆成 `api/performance.ts` / `api/uiauto.ts` 等 per-module 实例。现在单板块阶段只用一个 BASE。

### 已有的 API 端点（v1，**lib/api.ts 的 `tasksApi` 已封装常用调用**）

- `GET /api/performance/tasks/` → `Paginated<Task>`（PAGE_SIZE=50，**默认过滤软删**；`Task` 含 `status: 'draft'|'configured'` 计算字段 + `csv_bindings: TaskCsvBinding[]`）
- `POST /api/performance/tasks/`（multipart, 含 `jmx_file`） → 后端解析 JMX 自动填 `virtual_users/ramp_up_seconds/duration_seconds`；**title 不再加日期前缀**，直接用用户输入
- `GET/PATCH /api/performance/tasks/:id/`（`PATCH title` 会 rename 磁盘文件；`PATCH vuser/ramp/duration` 会 `patch_jmx` 重写文件——v1 前端已不调用 PATCH）
- `DELETE /api/performance/tasks/:id/` → **软删除**（DB `is_deleted=True` + 物理删除原件 + 全部 csv_bindings 物理 CSV）
- `POST /api/performance/tasks/:id/replace-jmx/`（multipart）→ 覆盖原件；**自动清空 `thread_groups_config` + 解绑 csv_bindings**；前端按钮在已配置 Step 2 时弹 confirm
- `POST /api/performance/tasks/:id/components/upload-csv/` body `path` + `csv_file` → 按 CSVDataSet 路径绑定（替换旧 binding 同时删旧 CSV 物理文件）
- `POST /api/performance/tasks/:id/components/delete-csv/` body `{path}` → 解除绑定 + 删物理文件
- `GET /api/performance/tasks/:id/raw-xml/` → `{ xml: string }`（原件）
- `GET /api/performance/tasks/:id/download/` → 二进制 JMX（原件）
- `GET /api/performance/tasks/:id/preview-run-xml/` → `{ xml }` 内存生成的可执行版（调试 / 预览，不写盘）
- `GET /api/performance/tasks/:id/components/` → `JmxComponent[]`
- `POST /api/performance/tasks/:id/components/toggle/` body `{path, enabled}`
- `POST /api/performance/tasks/:id/components/rename/` body `{path, testname}`
- `GET /api/performance/tasks/:id/components/detail/?path=...` → HTTPSampler / HeaderManager 字段
- `PATCH /api/performance/tasks/:id/components/detail/` body `{path, kind, fields}`
- `GET /api/performance/tasks/:id/thread-groups/` → `ThreadGroupsResponse { thread_groups, saved_config, environment }`
- `PATCH /api/performance/tasks/:id/thread-groups/` body `{thread_groups, environment_id}` → **仅入库**（不再写 `_run.jmx`）
- `POST /api/performance/tasks/:id/validate/` body `{environment_id?}` → `ValidateResult[]`（1 并发请求每个启用的 HTTPSampler，内存生成 XML）
- `GET /api/performance/environments/` → `Environment[]`（不分页；编辑走后台 admin）

## 10. 构建 / 类型检查

```bash
npm run dev               # Vite dev，5173（被占时自动 5174）
npm run build             # vue-tsc -b && vite build
npm run preview           # 预览 build 产物
npx vue-tsc --noEmit      # 只跑类型检查（快）
```

**提交前必跑**：`npm run build` —— 如果有未用的 import、类型错误，`vue-tsc` 会在构建阶段失败（严格模式）。

## 11. 约定 & 踩坑

### 11.1 `figma/` 是参考源，不是运行时代码
**永远不要** `import ... from '../../figma/...'`。需要还原 figma 设计时：读 `figma/src/app/components/*.tsx` → 照着写对应的 `.vue`。

### 11.2 Mock 数据 vs 真 API 数据（2026-04-28 更新）
前端同时存在两种数据源：
- **`src/components/perf/data.ts`**：`TASKS` 是 mock（仍保留作为 `MetricsColumn` / `TemporalColumn` 视觉占位，因为它们需要 rps / p99 / phases 这些运行时数据，v1 还没有），`PEOPLE` / `BIZ` 是视觉点缀
- **`PerformanceStage.vue`**：mounted 时调 `tasksApi.list()` → `mapApiTask()` 映射成 `StreamTask` schema → 喂给 ChronosNerve（左列任务列表，**这一列是真数据**）
- **`src/types/task.ts`**：API 真类型，新业务统一用它

`StreamTask`（perf/data.ts）保留是因为它的视觉 schema 比 API Task 多了运行时字段；映射函数把缺的字段填 0 / 空串。等 v1.1 接 TaskRun，`MetricsColumn` / `TemporalColumn` 也切真数据时，能消掉这层映射。

`StreamTask.status`：`success` / `fail` / `running` / `draft` / `configured`，对应到 `stColor()`（draft=灰、configured=紫、其他原色）。

### 11.3 API helper = `src/lib/api.ts`（v1 新写的）
当前版本**没有** token/auth 逻辑。如果以后要加鉴权，改这一个文件就够。**不要**在组件里直接 `fetch()`——统一走 `api()` / `apiForm()` 方便拦截错误和加 header。

### 11.4 路由里的 `login` 名称是历史遗留
路径 `/` 对应的 `name: 'login'`，但其实是"入口页"。以后如果把这个页改成真正的仪表板入口，记得一并改 `name`。

### 11.5 严格类型模式
`tsconfig.app.json` 继承 `@vue/tsconfig`，默认 `strict: true`，还开了 `noUnusedLocals` 之类。**未使用的 import 会直接让 build 失败**（见曾经的 `AnimatePresence` unused 踩坑）。

**TypeScript 6 的 `erasableSyntaxOnly`** 还禁掉了 constructor parameter properties：

```ts
// ❌ 会报 TS1294
class Foo { constructor(public bar: string) {} }

// ✅ 要这样写
class Foo {
  bar: string
  constructor(bar: string) { this.bar = bar }
}
```

见 `src/lib/api.ts` 的 `ApiError` 类。

### 11.7 Monaco editor（v1 新装）
用 `@guolao/vue-monaco-editor` 的 `<VueMonacoEditor>` 组件。它**不打包 Monaco**——运行时从 CDN 加载，所以首屏 `TaskEditPanel` 打开"查看 XML"那一下可能会有轻微延迟。生产要自托管的话另外配置 `loader.config({ paths })`。

在 `TaskEditPanel.vue` 的用法：

```vue
<VueMonacoEditor
  v-model:value="xml"
  language="xml"
  :theme="isDark ? 'vs-dark' : 'vs'"
  :options="{ readOnly: true, fontSize: 12, minimap: { enabled: false }, wordWrap: 'on' }"
  height="400px"
/>
```

### 11.6 Windows 下的依赖
`@rollup/rollup-win32-x64-msvc` 一类的 native 包跟着 `npm install` 自动处理，不要手动装。如果 `npm run dev` 报 "Cannot find module" 带 platform 后缀的 native 包，删 `node_modules` 重装。

### 11.8 `Task` 类型字段跟后端对齐（2026-04-28 改造）
`src/types/task.ts` 的 `Task.jmx_filename` 是**文件名字符串**（不是 URL），对应后端 CharField；物理文件落 `<jmeter_home>/scripts/`。

**已删除字段**：`csv_filename` / `run_jmx_filename`。

**新增字段**：
- `csv_bindings: TaskCsvBinding[]` —— 每个 `{component_path, filename}` 对应一个 CSVDataSet 绑定
- `status: 'draft' | 'configured' | 'running' | 'success' | 'failed'` —— 后端计算字段，前端按它着色 / 排序

下载 .jmx 用 `GET /api/performance/tasks/:id/download/` 端点（开新窗口）。CSV 上传走 `POST /api/performance/tasks/:id/components/upload-csv/`（multipart，body `path` + `csv_file`），通过 `tasksApi.uploadComponentCsv(id, path, file)` 调用。

## 12. TaskCreateWizard 结构约定（v1 已落地）

Wizard 是单一 glass panel：

```
┌──────────────────────────────────────────────────────┐
│ ┌──104px──┐ │                                       │
│ │ 竖脊    │ │       右侧内容区（flex-1）          │
│ │ 01 ●    │ │                                       │
│ │ 上传脚本│ │   按 activeStep.id 切换渲染：        │
│ │ │       │ │   - 'upload' → dropzone / (header + ScriptTree) │
│ │ 02 ○    │ │   - 'config' → v1.1 占位            │
│ │ 任务配置│ │   - 'execute/analyze/report' → 占位 │
│ │ │       │ │                                 [×] │
│ │ …       │ │                                       │
│ └─────────┘ │                                       │
└──────────────────────────────────────────────────────┘
```

### 12.1 Step 语义（重要，不要搞反）
- **Step 1 `upload`**：`uploadedTask` 为 null 时 → 居中 dropzone；非 null 时 → 左侧 header + 下方 `<ScriptTree>` 渲染组件树。**不切换到 Step 2**。
- **Step 2 `config`**（v2 场景驱动）：`<ConfigStage>` 三段式布局。顶部 TG 切换器（单 TG 时隐藏） + 禁用 TG 提示 → 场景 Tab pill（6 选一，**每个 pill 旁有 `?` 图标 hover tooltip：用途 / 典型参数 / 关注指标**）+ 常驻说明条 → 左右分栏（左 35% 参数表单 + 环境下拉 + 校验/保存按钮 / 右 65% echarts 线图 + 校验结果）
- **Step 3-5 `execute/analyze/report`**：占位 "v1.1 即将推出"，内容在 `TaskCreateWizard.vue` 的 `STEPS` 数组末尾 template 里

### 12.2 状态机
- `currentStep: ref<number>` —— 0-4 数组索引；初始 0；编辑模式（`initialTask` 非空 + `thread_groups_config` 非空）→ 直接跳到 1
- `uploadedTask: ref<Task | null>` —— null 代表还没上传；接受 `props.initialTask` 时通过 `applyInitialTask()` 同步
- `fileInput: ref<HTMLInputElement | null>` —— 共享的隐藏 `<input type="file">`；dropzone 点击走 `triggerPicker`，"重新上传"按钮走 `triggerReupload`（已配置 Step 2 时 confirm，否则直接打开选择器）
- `toast: ref<{text}|null>` —— 重新上传成功后短暂展示反馈（`脚本已替换` 或 `脚本已替换，请重新配置 Step 2`），2.5s 自动消失
- `isDone(i)`: `i === 0 && !!uploadedTask.value`（v1 只有 Step 1 有"完成"概念）
- `canEnterStep(i)`: `i === 0 || !!uploadedTask.value`（Step 2-5 需要先上传过）
- 节点点击 → 如果 `!canEnterStep(i)` → no-op + 灰度视觉 + `cursor-not-allowed`
- **没有"自动前进到下一步"**

### 12.3 流转
- 选/拖 .jmx 文件 → `handleFile()` 校验 `.jmx` 后缀 + 大小 ≤ **10 MB**（`MAX_JMX_SIZE` 常量，与后端 `settings.MAX_UPLOAD_SIZE` 对齐）→ `doUpload()` 立即 POST（**没有"保存任务"按钮**，文件就是触发）
- 上传成功 → `uploadedTask.value = task`；**同步显示组件树**（不切步骤）
- 已上传状态下点"重新上传"按钮 → `triggerPicker()` 打开系统文件选择器 → `doUpload()` 检测到 `uploadedTask` 已存在 → `apiForm('/tasks/:id/replace-jmx/')` **覆盖当前任务**（Task id / title / 磁盘文件名 都不变，仅 jmx_hash 和 vuser/ramp/duration 重新解析）；`ScriptTree` 的 watch 监听 `[task.id, task.jmx_hash]`，hash 变 → 自动重拉组件树
- 拖非 .jmx 文件 → `uploadError` 显示"仅支持 .jmx 文件"

### 12.4 组件拆分
- `TaskCreateWizard.vue` —— 外壳 + 竖脊 + 上传流程 + Step 1 内两种分支的渲染
- `ScriptTree.vue` —— 已上传后的组件树容器：mount 时拉 `GET /components/`（watch `[task.id, task.jmx_hash]`，覆盖上传后 hash 变自动重拉）；分发到 `ComponentNode`；点开关时 POST `/components/toggle/` 并把回传的新树整体替换；用 `busyPaths: Set<string>` 防重复点击。**provide** `SCRIPT_TREE_CTX`（`scriptTreeCtx.ts` 里定义 `InjectionKey`）：包含 `searchQuery / expandTrigger / collapseTrigger` 三个 ref，供 `ComponentNode` inject
- `ComponentNode.vue` —— 递归单行；自身维护 `expanded` 状态（**默认展开到三级**：`expanded = ref(depth < 2)`，更深的层级默认折叠，用户点 chevron 可逐级展开）；每行 `[chevron] [status dot] [testname] [tag] [右侧控件]`；depth 缩进；父禁用时子行视觉变灰（用 `parentEnabled` prop 级联）。**右侧控件两种**：
  - `depth === 0 && tag === 'TestPlan'` → **工具栏**：搜索输入框 (180px) + "全部展开" + "全部折叠" 按钮，**没有 enabled 开关**（避免用户不小心禁用整个测试计划）
  - 其他节点 → enabled toggle 开关
- **展开 / 折叠全部**：两个按钮分别 `ctx.expandTrigger.value++` / `collapseTrigger.value++`；`ComponentNode` watch 这两个 ref——展开时把 depth 0/1/2 的节点设 `expanded=true`（跟初值一致），折叠时把 depth ≥ 1 的节点设 `expanded=false`（TestPlan 根节点保持展开，否则工具栏就成了孤零零一行）
- **搜索行为**：搜索框 v-model 到 `ctx.searchQuery`，ComponentNode 里基于它 computed `isMatch`（`testname` 或 `tag` 大小写不敏感 contains）和 `hasMatchingDescendant`（递归子树）。匹配 → 行背景 `rgba(254,240,138,0.55)` / dark 下 `rgba(250,204,21,0.18)`（淡黄高亮）。只要 `isMatch || hasMatchingDescendant` 为 true，**watch 强制把这条分支的 `expanded` 设 true**（自动展开祖先路径）；搜索清空**不自动回弹**，保留用户已展开状态
- **保存失败闪红**：`ScriptTree` 的 `handleToggle` catch 里把出错的 path 写进 `ctx.errorFlashPath`，800 ms 后清空。ComponentNode 检测到 `errorFlashPath === 自己.path` 时行背景变淡红（优先级高于搜索高亮）。文件没变 + UI 闪红一眼就知道"这次切换没保存成功"。CSV 行上传失败同样触发闪红。
- **CSVDataSet 行**特殊渲染（2026-04-28 改成按 path 多绑定）：enabled toggle 左侧多一个 Paperclip 图标 → 点了打开文件选择器 → `tasksApi.uploadComponentCsv(taskId, node.path, file)` 调 `POST /tasks/:id/components/upload-csv/` → ScriptTree 把回传的新 Task emit 给 TaskCreateWizard（`@task-updated`）。按钮颜色：在 `task.csv_bindings` 找到对应 path 的 binding 时变绿（`#10b981`），hover 提示显示该 binding 的 filename；未绑定时灰色。
- **CSVDataSet 自动可见**：ScriptTree 每次拉到新 tree 后扫出所有 `tag === 'CSVDataSet'` 节点的 path 和祖先 path，放进 `ctx.forceExpandPaths`。ComponentNode watch 此 set，若命中自己 path，强制 `expanded = true`——这样即便 CSVDataSet 深度超过 3 级，也能第一眼看到。用户后续可手动折叠。
- **双击 testname 改名**：非 TestPlan 节点的 testname 文字 `@dblclick` 进入编辑态（替换为 input + 蓝色边框）。Enter / 失焦 → `emit('rename', path, newName)` → ScriptTree 调 `POST /components/rename/` 写盘；Esc 取消；没改动就不发请求。失败依旧触发 errorFlashPath 闪红。TestPlan 根行不开放改名（那一级承载工具栏）。
- **HTTPSampler / HeaderManager 抽屉编辑**：ComponentNode 在 enabled toggle 左侧 (对这两种 tag) 加紫色齿轮按钮（Settings 图标）→ `emit('edit', node)` → ScriptTree 把 `editingNode` 设为该节点 → `DetailDrawer` 从右侧滑入（400px 宽）→ mount 时 `GET /components/detail/?path=...` 拉字段；子组件 `HttpSamplerForm` 或 `HeaderManagerForm` 按 `detail.kind` 条件渲染；保存时 `PATCH /components/detail/` 写盘，返回的新树直接 `tree.value = event`；抽屉自动关闭。HeaderManager 整条重建 collectionProp，增/删/改 headers 都在表单里完成。
- **HTTPSampler 表单结构**（`HttpSamplerForm.vue`）分三节：
  - **基础**：domain / port / protocol(select) / method(select) / path
  - **请求内容**：顶部 segmented control 切换 "参数 / 消息体" —— 参数模式 = name/value 表单，消息体模式 = textarea（写入 raw body，后端 `HTTPSampler.postBodyRaw=true`）；切换模式时 Arguments collection 整条重建
  - **文件上传**：path + paramname + mimetype 三字段的列表，对应 JMX 的 `HTTPsampler.Files` collection，multipart 上传场景用

### 12.5 Step 2 组件拆分（v2 场景驱动）

- `ConfigStage.vue` —— Step 2 根组件。mount 时 `GET /thread-groups/`；local `configs: ThreadGroupConfig[]` 只含**启用**的 TG（禁用的不显示、保存时保留原样）；`currentPath` 决定右侧编辑哪个 TG（单 TG 时就一个、不显示切换器）。"保存"按钮一次 `PATCH` 全部 TG 配置 + environment_id；"校验"按钮 `POST /validate/`，结果填进 `ValidateResultTable`。
- `ScenarioTabs.vue` —— 6 个场景 pill（基准/负载/压力/稳定性/峰值/吞吐量）。选中态：场景色渐变 + scale 1.04 + 外发光 + 右上角小圆点指示；下方常驻一条场景说明条（左边竖条染场景色 + label + desc）。切换场景 → emit `update:modelValue`，`ConfigStage` 把**当前 TG** 的 `kind` + `params` 整段重置为场景默认。
- `ThreadGroupPicker.vue` —— 多 TG 切换器。`threadGroups.length > 1` 时才渲染；每个 TG 一个 pill，右侧小标签显示该 TG 已选场景（场景色）。点击 → emit `update:currentPath`。
- `TgParamsForm.vue` —— 参数表单。`fields` computed 根据当前 `config.kind` 返回字段清单（5 种 kind 各自的字段组）；number input 都带 `min/max`（5000/43200，Arrivals 的 target_rps 除外）；`ConcurrencyThreadGroup` / `ArrivalsThreadGroup` 额外带 Unit 下拉（S/M）。**不自动切换 kind**——参数微调不改 scenario。
- `ThreadGroupChart.vue` —— echarts 线图（`vue-echarts` 包装）。按需引入 `LineChart + GridComponent + TooltipComponent + TitleComponent + MarkPointComponent + CanvasRenderer`。根据 kind + params 算 `(t, y)` 点列，渲染成折线 + 半透明场景色填充面 + 峰值 markPoint。y 轴名 `活跃用户数` 或 `RPS`（Arrivals kind 专用）。高度固定 320px。
- `EnvironmentPicker.vue` —— 同 v1，无改动。
- `ValidateResultTable.vue` —— 新增一行黄色警告显示 `unresolved_vars`（"⚠ 有未解析变量：username, token"）。

### 12.6 Step 2 场景 → TG 映射（configStageCtx.ts 的 SCENARIOS 数组）

| 场景 ID | 标签 | 色 | 底层 kind | 默认参数摘要 |
|---|---|---|---|---|
| `baseline` | 基准 | 蓝 | `ThreadGroup` | users=10 / ramp=5 / duration=300 |
| `load` | 负载 | 绿 | `SteppingThreadGroup` | 从 0 每 30s 加 10 人共 10 阶 |
| `stress` | 压力 | 橙 | `SteppingThreadGroup` | 从 50 每 30s 加 50 人共 10 阶 |
| `soak` | 稳定性 | 紫 | `ConcurrencyThreadGroup` | 50 并发跑 1 小时 |
| `spike` | 峰值 | 红 | `UltimateThreadGroup` | 500 人 5s 冲高，hold 60s，5s 退出 |
| `throughput` | 吞吐量 | 粉 | `ArrivalsThreadGroup` | 500 RPS（每分钟单位）跑 10 分钟 |

**读写规则**：`thread_groups_config` JSON 每项存 `{path, scenario, kind, params}`。老数据（v1 没 scenario 字段）→ `inferScenarioFromKind` 按 kind 反推一个。新 TG 首次进 Step 2 → 默认 `load` 场景。

### 12.7 Step 2 与 Step 1 的协作（2026-04-28 改造：取消 `_run.jmx`）

- Step 2 **只显示启用的 TG**；禁用的 TG 在 PATCH body 里缺席 → 后端原件里它们原样保留（含 `enabled=false`），跑压测时也一样保留禁用
- Step 2 保存 = **仅写 DB**（`thread_groups_config` + `environment`），**不写盘**；状态变成 `configured`，列表里徽标变紫
- **原件 vs 内存生成**：Step 1 所有操作改原件 `<title>.jmx`；Step 2 配置入 DB；validate / 跑压测时（v1.1）后端 `services/jmx.py::build_run_xml(task)` 在内存里读原件 → 套 thread_groups_config + csv_bindings → 返回 bytes。**没有派生文件，永远没有"派生品过期"**——Step 1 后续改动自动反映到下次 run。

### 12.8 configStageCtx.ts

- `MAX_USERS=5000` / `MAX_DURATION_SECONDS=43200` 常量（与后端 `services/jmx.py` 对齐）
- `SCENARIOS: ScenarioDef[]` 数组（6 项）—— UI 和默认参数的单一数据源；底层 kind 也在这里定
- `scenarioById(id)` / `inferScenarioFromKind(kind)` 两个工具函数
- `CONFIG_STAGE_CTX` InjectionKey 预留（当前未真正 provide，v1.1+ 再用）
- 三者解耦，以后要新增 Step（例如 v1.1 的 execute）直接再加 `<template v-else-if="activeStep.id === 'execute'">` 分支

## 13. 新增页面的步骤

1. 在 `src/pages/` 建 `XxxPage.vue`
2. 在 `src/router/index.ts` 的 `children` 里加一项 `{ path: 'xxx', name: 'xxx', component: () => import('@/pages/XxxPage.vue') }`
3. 如果新页面用主题，`<script setup>` 里 `const { theme } = useTheme()`（已在 AppLayout 提供过，直接拿）
4. 顶层包一个深浅色背景容器，参考 HomePage 的 `:style="{ background: isDark ? '#0A0A0A' : '#F5F5F7' }"`

## 14. 新增共用组件的步骤

1. 判断是否只有一个页面用 → 只有一处放 `components/<页面>/`，跨页放 `components/`
2. 用 `<script setup lang="ts">` + `defineProps` / `withDefaults`
3. 要动画就 `import { Motion } from 'motion-v'`
4. 要图标 `import { X } from 'lucide-vue-next'`
5. 跨页共用组件加一个可选的 `class` prop 透传样式（见 `GlassNav.vue` 的模式）

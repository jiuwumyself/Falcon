import { inject, provide, readonly, ref, watchEffect, type InjectionKey, type Ref } from 'vue'

export type Theme = 'dark' | 'light'

export interface ThemeCtx {
  theme: Readonly<Ref<Theme>>
  toggleTheme: (e?: MouseEvent) => void
  ripple: Readonly<Ref<{ x: number; y: number; active: boolean }>>
}

const ThemeKey: InjectionKey<ThemeCtx> = Symbol('theme')

export function provideTheme(): ThemeCtx {
  const theme = ref<Theme>('dark')
  const ripple = ref({ x: 0, y: 0, active: false })

  watchEffect(() => {
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
  })

  const toggleTheme = (e?: MouseEvent) => {
    if (e) ripple.value = { x: e.clientX, y: e.clientY, active: true }
    setTimeout(() => {
      theme.value = theme.value === 'dark' ? 'light' : 'dark'
      setTimeout(() => {
        ripple.value = { ...ripple.value, active: false }
      }, 600)
    }, 50)
  }

  const ctx: ThemeCtx = {
    theme: readonly(theme),
    toggleTheme,
    ripple: readonly(ripple),
  }
  provide(ThemeKey, ctx)
  return ctx
}

export function useTheme(): ThemeCtx {
  const ctx = inject(ThemeKey)
  if (!ctx) throw new Error('useTheme() must be called inside a component under <AppLayout>')
  return ctx
}

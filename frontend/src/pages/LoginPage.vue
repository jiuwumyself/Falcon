<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Motion } from 'motion-v'
import { Eye, EyeOff } from 'lucide-vue-next'
import FalconLogo from '@/components/FalconLogo.vue'
import ParticleCanvas from '@/components/ParticleCanvas.vue'

const router = useRouter()
const email = ref('')
const password = ref('')
const showPass = ref(false)
const focusedField = ref<string | null>(null)
const isLoading = ref(false)

function handleLogin(e: Event) {
  e.preventDefault()
  isLoading.value = true
  setTimeout(() => router.push('/home'), 600)
}
</script>

<template>
  <div class="flex h-screen w-screen overflow-hidden" style="background: #0A0A0A">
    <!-- Left: Particle Nebula -->
    <div class="hidden lg:flex flex-1 relative items-center justify-center overflow-hidden">
      <ParticleCanvas />
      <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
        <Motion
          :initial="{ opacity: 0, scale: 0.8 }"
          :animate="{ opacity: 0.45, scale: 1 }"
          :transition="{ duration: 2 }"
        >
          <FalconLogo :size="400" />
        </Motion>
      </div>
      <div
        class="absolute inset-0 pointer-events-none"
        style="background: radial-gradient(ellipse at center, transparent 30%, #0A0A0A 75%)"
      />
      <Motion
        class="absolute bottom-12 left-12 z-10"
        :initial="{ opacity: 0, y: 20 }"
        :animate="{ opacity: 1, y: 0 }"
        :transition="{ delay: 0.5, duration: 0.8 }"
      >
        <p class="text-white/30 tracking-[0.3em] text-[11px] uppercase">Precision in Speed</p>
      </Motion>
    </div>

    <!-- Right: Login Panel -->
    <div class="flex-1 lg:flex-none lg:w-[520px] flex items-center justify-center relative p-8">
      <div
        class="absolute inset-0"
        style="background: linear-gradient(135deg, rgba(59,130,246,0.03) 0%, transparent 50%, rgba(124,58,237,0.03) 100%)"
      />
      <Motion
        :initial="{ opacity: 0, x: 30 }"
        :animate="{ opacity: 1, x: 0 }"
        :transition="{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }"
        class="relative w-full max-w-[380px]"
      >
        <div
          class="relative rounded-[28px] p-10 overflow-hidden"
          style="
            background: rgba(255,255,255,0.04);
            backdrop-filter: blur(40px);
            -webkit-backdrop-filter: blur(40px);
            box-shadow: inset 0 1px 0 0 rgba(255,255,255,0.08), inset 0 -1px 0 0 rgba(255,255,255,0.02), 0 20px 60px rgba(0,0,0,0.4);
            border: 1px solid rgba(255,255,255,0.06);
          "
        >
          <!-- Logo -->
          <div class="flex items-center gap-3 mb-10">
            <FalconLogo :size="36" />
            <div>
              <h1 class="text-white text-[20px] tracking-tight">Falcon Eyes</h1>
              <p class="text-white/30 text-[11px] tracking-wider">INTELLIGENT TEST PLATFORM</p>
            </div>
          </div>

          <form class="space-y-5" @submit="handleLogin">
            <!-- Email -->
            <div class="relative">
              <label class="text-white/50 text-[12px] mb-1.5 block tracking-wide">EMAIL</label>
              <div class="relative">
                <input
                  v-model="email"
                  type="email"
                  placeholder="name@company.com"
                  class="w-full px-4 py-3 rounded-2xl text-white placeholder-white/20 outline-none transition-all duration-300 text-[14px]"
                  :style="{
                    background: 'rgba(255,255,255,0.04)',
                    border: `1px solid ${focusedField === 'email' ? 'rgba(59,130,246,0.5)' : 'rgba(255,255,255,0.06)'}`,
                    boxShadow: focusedField === 'email'
                      ? '0 0 20px rgba(59,130,246,0.1), inset 0 0 20px rgba(59,130,246,0.03)'
                      : 'none',
                  }"
                  @focus="focusedField = 'email'"
                  @blur="focusedField = null"
                />
              </div>
            </div>

            <!-- Password -->
            <div class="relative">
              <label class="text-white/50 text-[12px] mb-1.5 block tracking-wide">PASSWORD</label>
              <div class="relative">
                <input
                  v-model="password"
                  :type="showPass ? 'text' : 'password'"
                  placeholder="Enter your password"
                  class="w-full px-4 py-3 pr-12 rounded-2xl text-white placeholder-white/20 outline-none transition-all duration-300 text-[14px]"
                  :style="{
                    background: 'rgba(255,255,255,0.04)',
                    border: `1px solid ${focusedField === 'password' ? 'rgba(59,130,246,0.5)' : 'rgba(255,255,255,0.06)'}`,
                    boxShadow: focusedField === 'password'
                      ? '0 0 20px rgba(59,130,246,0.1), inset 0 0 20px rgba(59,130,246,0.03)'
                      : 'none',
                  }"
                  @focus="focusedField = 'password'"
                  @blur="focusedField = null"
                />
                <button
                  type="button"
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors"
                  @click="showPass = !showPass"
                >
                  <component :is="showPass ? EyeOff : Eye" :size="16" />
                </button>
              </div>
            </div>

            <!-- Login Button -->
            <Motion
              as="button"
              type="submit"
              :disabled="isLoading"
              :while-tap="{ scale: 0.97 }"
              class="w-full py-3.5 rounded-2xl text-white relative overflow-hidden cursor-pointer transition-shadow duration-300 mt-3"
              style="
                background: linear-gradient(135deg, #3b82f6, #6366f1, #7c3aed);
                box-shadow: 0 8px 30px rgba(59,130,246,0.25);
              "
            >
              <span class="relative z-10 text-[14px] tracking-wide">
                {{ isLoading ? 'Authenticating...' : 'Sign In' }}
              </span>
              <Motion
                class="absolute inset-0"
                :animate="{ backgroundPosition: ['200% 0', '-200% 0'] }"
                :transition="{ duration: 3, repeat: Infinity }"
                style="
                  background: linear-gradient(90deg, transparent 30%, rgba(255,255,255,0.1) 50%, transparent 70%);
                  background-size: 200% 100%;
                "
              />
            </Motion>
          </form>

          <div class="mt-8 text-center">
            <p class="text-white/20 text-[12px]">
              Don't have an account?
              <span class="text-blue-400/60 cursor-pointer hover:text-blue-400 transition-colors">
                Request Access
              </span>
            </p>
          </div>
        </div>
      </Motion>
    </div>
  </div>
</template>

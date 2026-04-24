import { onMounted, ref } from 'vue'

export function useRimColor() {
  const color = ref('#7dd3fc')
  onMounted(() => {
    const h = new Date().getHours()
    color.value = h >= 7 && h < 19 ? '#7dd3fc' : '#fbbf24'
  })
  return color
}

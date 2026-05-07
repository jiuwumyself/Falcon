import type { Service } from '@/types/task'

// v1.2 服务库当前为前端 mock 数据。Task 上只存 service_name 字符串，
// Step 3 RuntimeStatusPanel 用 service_name 反查这里的 grafana_panels。
// v1.3 接入后端 Service 表后，这个文件可以删掉，改成调 servicesApi.list()。

const MOCK_SERVICES: Service[] = [
  {
    id: 'svc-user',
    name: '用户中心',
    base_url: 'https://user.example.com',
    grafana_url: 'https://grafana.example.com/d/user-overview',
    pinpoint_app: 'user-service',
    arthus_endpoint: 'https://arthus.example.com/api/user',
    description: '账户、登录、会话、用户信息相关接口。',
    grafana_panels: [
      {
        name: '服务总览',
        url: 'https://grafana.example.com/d-solo/user-overview/user-overview?orgId=1&panelId=1',
        type: 'service',
      },
      {
        name: 'JVM 指标',
        url: 'https://grafana.example.com/d-solo/user-jvm/user-jvm?orgId=1&panelId=2',
        type: 'service',
      },
      {
        name: 'DB 慢查询',
        url: 'https://grafana.example.com/d-solo/user-db/user-db?orgId=1&panelId=4',
        type: 'service',
      },
      {
        name: '接口调用链',
        url: 'https://grafana.example.com/d-solo/user-trace/user-trace?orgId=1&panelId=10',
        type: 'trace',
      },
      {
        name: '错误根因',
        url: 'https://grafana.example.com/d-solo/user-trace/user-trace?orgId=1&panelId=11',
        type: 'trace',
      },
    ],
  },
  {
    id: 'svc-order',
    name: '订单服务',
    base_url: 'https://order.example.com',
    grafana_url: 'https://grafana.example.com/d/order-overview',
    pinpoint_app: 'order-service',
    arthus_endpoint: 'https://arthus.example.com/api/order',
    description: '下单、查询、支付回调、退款相关接口。',
    grafana_panels: [
      {
        name: '下单 RPS / RT',
        url: 'https://grafana.example.com/d-solo/order-overview/order-overview?orgId=1&panelId=1',
        type: 'service',
      },
      {
        name: '消息队列堆积',
        url: 'https://grafana.example.com/d-solo/order-mq/order-mq?orgId=1&panelId=3',
        type: 'service',
      },
      {
        name: '调用链 P99',
        url: 'https://grafana.example.com/d-solo/order-trace/order-trace?orgId=1&panelId=10',
        type: 'trace',
      },
    ],
  },
  {
    id: 'svc-payment',
    name: '支付网关',
    base_url: 'https://pay.example.com',
    grafana_url: 'https://grafana.example.com/d/payment-overview',
    pinpoint_app: 'payment-gateway',
    arthus_endpoint: 'https://arthus.example.com/api/payment',
    description: '支付下单、回调、对账、风控相关接口。',
    grafana_panels: [
      {
        name: '渠道成功率',
        url: 'https://grafana.example.com/d-solo/payment-channel/payment-channel?orgId=1&panelId=1',
        type: 'service',
      },
      {
        name: '风控拦截',
        url: 'https://grafana.example.com/d-solo/payment-risk/payment-risk?orgId=1&panelId=2',
        type: 'service',
      },
    ],
  },
  {
    id: 'svc-ai',
    name: 'AI 推理服务',
    base_url: 'https://ai.example.com',
    grafana_url: 'https://grafana.example.com/d/ai-inference',
    pinpoint_app: 'ai-inference',
    arthus_endpoint: '',
    description: '模型推理、向量检索、内容生成。',
    grafana_panels: [
      {
        name: 'GPU 利用率',
        url: 'https://grafana.example.com/d-solo/ai-gpu/ai-gpu?orgId=1&panelId=1',
        type: 'service',
      },
      {
        name: '推理延迟分布',
        url: 'https://grafana.example.com/d-solo/ai-inference/ai-inference?orgId=1&panelId=2',
        type: 'service',
      },
      {
        name: '请求链路',
        url: 'https://grafana.example.com/d-solo/ai-trace/ai-trace?orgId=1&panelId=10',
        type: 'trace',
      },
    ],
  },
]

export function getMockServices(): Service[] {
  return MOCK_SERVICES
}

export function getMockServiceByName(name: string): Service | null {
  if (!name) return null
  return MOCK_SERVICES.find((s) => s.name === name) ?? null
}

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EnvironmentViewSet, LoadGeneratorViewSet, PrometheusDataSourceViewSet,
    RunViewSet, ServiceViewSet, TaskViewSet, serve_run_report,
    arthas_clusters, arthas_namespaces, arthas_pods,
)

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'runs', RunViewSet, basename='run')
router.register(r'environments', EnvironmentViewSet, basename='environment')
router.register(r'services', ServiceViewSet, basename='service')
router.register(r'load-generators', LoadGeneratorViewSet, basename='load-generator')

router.register(r'prometheus-sources', PrometheusDataSourceViewSet, basename='prometheus-source')

urlpatterns = [
    # 报告静态资源：显式路由放在 router 之前（<path:sub> 吃斜杠，绕开 router 的 /$ 坑）
    path('runs/<str:run_id>/report/', serve_run_report, name='run-report-index'),
    path('runs/<str:run_id>/report/<path:sub>', serve_run_report, name='run-report-asset'),
    # Arthas 终端：zapp-server 实时列 集群/命名空间/某服务的 pod（前端级联选，免手填）
    path('arthas/clusters/', arthas_clusters, name='arthas-clusters'),
    path('arthas/namespaces/', arthas_namespaces, name='arthas-namespaces'),
    path('arthas/pods/', arthas_pods, name='arthas-pods'),
    path('', include(router.urls)),
]

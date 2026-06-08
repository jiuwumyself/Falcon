from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EnvironmentViewSet, LoadGeneratorViewSet, PrometheusDataSourceViewSet,
    RunViewSet, ServiceViewSet, TaskViewSet, serve_run_report,
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
    path('', include(router.urls)),
]

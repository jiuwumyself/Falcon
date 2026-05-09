from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EnvironmentViewSet, LoadGeneratorViewSet, RunViewSet, ServiceViewSet,
    TaskViewSet,
)

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'runs', RunViewSet, basename='run')
router.register(r'environments', EnvironmentViewSet, basename='environment')
router.register(r'services', ServiceViewSet, basename='service')
router.register(r'load-generators', LoadGeneratorViewSet, basename='load-generator')

urlpatterns = [
    path('', include(router.urls)),
]

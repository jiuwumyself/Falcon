from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EnvironmentViewSet, RunViewSet, TaskViewSet

router = DefaultRouter()
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'runs', RunViewSet, basename='run')
router.register(r'environments', EnvironmentViewSet, basename='environment')

urlpatterns = [
    path('', include(router.urls)),
]

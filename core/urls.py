"""热应激预警系统 - URL路由"""

from django.urls import path
from . import views

urlpatterns = [
    # 页面路由
    path('', views.dashboard, name='index'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('projects/', views.projects_view, name='projects'),
    path('users/', views.users_view, name='users'),

    # API - 数据
    path('api/stats/', views.api_stats, name='api_stats'),
    path('api/devices/', views.api_devices, name='api_devices'),
    path('api/devices/<int:device_id>/', views.api_device_detail, name='api_device_detail'),
    path('api/alerts/', views.api_alerts, name='api_alerts'),
    path('api/alerts/clear/', views.api_clear_alerts, name='api_clear_alerts'),

    # API - 项目管理
    path('api/projects/create/', views.api_project_create, name='api_project_create'),
    path('api/projects/<int:project_id>/update/', views.api_project_update, name='api_project_update'),
    path('api/projects/<int:project_id>/delete/', views.api_project_delete, name='api_project_delete'),
    path('api/projects/<int:project_id>/jurisdiction/', views.api_project_jurisdiction, name='api_project_jurisdiction'),
    path('api/projects/<int:project_id>/export-csv/', views.api_project_export_csv, name='api_project_export_csv'),
    path('api/projects/<int:project_id>/users/', views.api_project_users, name='api_project_users'),

    # API - 设备管理
    path('api/devices/create/', views.api_device_create, name='api_device_create'),
    path('api/devices/<int:device_id>/update/', views.api_device_update, name='api_device_update'),
    path('api/devices/<int:device_id>/delete/', views.api_device_delete, name='api_device_delete'),

    # API - 行政区划
    path('api/regions/', views.api_regions, name='api_regions'),
    path('api/regions/children/', views.api_regions_children, name='api_regions_children'),
    path('api/regions/tree/', views.api_regions_tree, name='api_regions_tree'),
    path('api/regions/<int:region_id>/', views.api_region_detail, name='api_region_detail'),

    # API - 手表端（device_id 鉴权，无需登录）
    path('api/watch/register/', views.watch_register, name='watch_register'),
    path('api/watch/upload/', views.watch_upload, name='watch_upload'),
    path('api/watch/heartbeat/', views.watch_heartbeat, name='watch_heartbeat'),
    path('api/watch/alerts/', views.watch_alerts, name='watch_alerts'),
    path('api/watch/alerts/<int:alert_id>/ack/', views.watch_ack_alert, name='watch_ack_alert'),

    # API - 设备绑定管理（需登录）
    path('api/devices/pending/', views.api_pending_devices, name='api_pending_devices'),
    path('api/devices/<int:device_id>/bind/', views.api_device_bind, name='api_device_bind'),
]

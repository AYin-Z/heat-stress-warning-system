"""热应激预警系统 - Admin配置"""

from django.contrib import admin
from .models import Project, Device, HealthData, Alert, DeviceLocation, Region


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['name']


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['device_id', 'officer_name', 'project', 'is_online', 'last_report_time']
    list_filter = ['is_online', 'project']
    search_fields = ['device_id', 'officer_name', 'asset_code']


@admin.register(HealthData)
class HealthDataAdmin(admin.ModelAdmin):
    list_display = ['device', 'heart_rate', 'blood_oxygen', 'core_temperature', 'timestamp']
    list_filter = ['device__project']


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['device', 'alert_type', 'risk_level', 'core_temperature', 'created_at']
    list_filter = ['alert_type', 'risk_level']


@admin.register(DeviceLocation)
class DeviceLocationAdmin(admin.ModelAdmin):
    list_display = ['device', 'latitude', 'longitude', 'timestamp']


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'level', 'parent_code', 'year']
    list_filter = ['level', 'year']
    search_fields = ['code', 'name', 'eng_name']
    readonly_fields = ['code', 'parent_code']

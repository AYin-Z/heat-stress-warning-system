"""热应激预警系统 - 视图"""

import csv
import io
import json
import os
from datetime import datetime, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.conf import settings

from .models import (Project, Device, HealthData, Alert, DeviceLocation, Region,
                             get_device_risk_level, is_device_effectively_online,
                             TEMP_WARNING_THRESHOLD, TEMP_NORMAL_WARNING, ONLINE_TIMEOUT_SECONDS)
from .watch_forward import forward_core_temperature


# ============ 页面视图 ============

def login_view(request):
    """登录页面"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    error = ''
    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            next_url = request.GET.get('next', '/dashboard/')
            return redirect(next_url)
        error = '用户名或密码错误'
    return render(request, 'login.html', {'error': error})


def logout_view(request):
    """退出登录"""
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    """大屏主界面——始终显示正在录入的项目"""
    current_project = Project.objects.filter(status='recording').first()

    return render(request, 'dashboard.html', {
        'current_project': current_project,
        'amap_key': settings.AMAP_KEY,
        'amap_secret': settings.AMAP_SECRET,
    })


@login_required
def projects_view(request):
    """项目管理页面"""
    projects = Project.objects.all().order_by('-created_at')
    # 附加设备和用户统计
    project_data = []
    for p in projects:
        devices = p.devices.all()
        active_count = devices.filter(bind_status='active').count()
        pending_count = devices.filter(bind_status='pending').count()
        project_data.append({
            'id': p.id,
            'name': p.name,
            'status': p.status,
            'status_display': p.get_status_display(),
            'description': p.description or '',
            'jurisdiction_color': p.jurisdiction_color,
            'created_at': p.created_at,
            'device_total': devices.count(),
            'device_active': active_count,
            'device_pending': pending_count,
        })
    recording = Project.objects.filter(status='recording').first()
    return render(request, 'projects.html', {
        'projects': project_data,
        'recording_project': recording,
    })


@login_required
def users_view(request):
    """用户管理页面"""
    projects = Project.objects.all()
    return render(request, 'users.html', {'projects': projects})


# ============ API 辅助函数 ============

GEO_BUFFER_DEGREES = 0.1  # 约10km缓冲


def _load_jurisdiction_geoms(project):
    """加载项目辖区几何（含缓冲），返回 (buffered_geoms, region_geoms)。全国通用，不硬编码。"""
    from shapely.geometry import shape
    region_geoms = {}   # code -> (shape, name, geojson_str)
    buffered_geoms = {}  # code -> buffered_shape
    if project:
        for r in project.jurisdiction_regions.filter(level='county').exclude(geometry_geojson=''):
            try:
                geom_dict = json.loads(r.geometry_geojson)
                geom = shape(geom_dict)
                region_geoms[r.code] = (geom, r.name, r.geometry_geojson)
                buffered_geoms[r.code] = geom.buffer(GEO_BUFFER_DEGREES)
            except Exception:
                pass
    return buffered_geoms, region_geoms


def _resolve_device_coords(device):
    """解析设备坐标：当前坐标 → 回退到最后已知历史坐标。返回 (lat, lng) 或 (None, None)。"""
    lat, lng = device.latitude, device.longitude
    if (lat is None or lng is None) and device.health_data.exists():
        last = device.health_data.exclude(latitude__isnull=True).exclude(
            longitude__isnull=True).order_by('-timestamp').first()
        if last:
            lat, lng = last.latitude, last.longitude
    return lat, lng


def _device_in_jurisdiction(device, buffered_geoms):
    """判断设备是否在辖区缓冲区内。无辖区数据 → 放行；无坐标 → 放行。"""
    if not buffered_geoms:
        return True
    lat, lng = _resolve_device_coords(device)
    if lat is None or lng is None:
        return True  # 无坐标设备不拦截
    from shapely.geometry import Point
    pt = Point(lng, lat)
    return any(buf.contains(pt) for buf in buffered_geoms.values())


# ============ API视图 ============

@login_required
def api_stats(request):
    """获取统计数据（含数据质量分类和今日预警数，仅统计辖区内设备）"""
    project_id = request.GET.get('project_id', '')
    current_project = None
    if project_id:
        current_project = Project.objects.filter(id=project_id).first()
    if not current_project:
        current_project = Project.objects.filter(status='recording').first()
        project_id = current_project.id if current_project else None
    devices = Device.objects.filter(bind_status='active')
    if project_id:
        devices = devices.filter(project_id=project_id)

    buffered_geoms, _ = _load_jurisdiction_geoms(current_project)
    filtered = [d for d in devices if _device_in_jurisdiction(d, buffered_geoms)]
    total = len(filtered)
    online = sum(1 for d in filtered if is_device_effectively_online(d))

    normal_count = warning_count = high_risk_count = monitoring_count = 0
    unavailable_count = offline_count = awaiting_data_count = 0

    for device in filtered:
        risk_level, _ = get_device_risk_level(device)
        if risk_level == 'normal':
            normal_count += 1
        elif risk_level == 'warning':
            warning_count += 1
        elif risk_level == 'high_risk':
            high_risk_count += 1
        elif risk_level == 'monitoring':
            monitoring_count += 1
        elif risk_level == 'unavailable':
            unavailable_count += 1
        elif risk_level == 'offline':
            offline_count += 1
        elif risk_level == 'awaiting_data':
            awaiting_data_count += 1
        # http_shell — HTTP注册空壳，不在大屏统计范围内

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_alerts = Alert.objects.filter(device__project_id=project_id, created_at__gte=today_start).count() if project_id else 0

    return JsonResponse({
        'total_devices': total,
        'online_devices': online,
        'offline_devices': offline_count,
        'monitoring_devices': monitoring_count,
        'unavailable_devices': unavailable_count,
        'awaiting_data_devices': awaiting_data_count,
        'today_alerts': today_alerts,
        'risk_stats': [
            {'name': '正常', 'value': normal_count, 'color': '#52c41a'},
            {'name': '普通预警', 'value': warning_count, 'color': '#fa8c16'},
            {'name': '高风险预警', 'value': high_risk_count, 'color': '#ff4d4f'},
            {'name': '监测中', 'value': monitoring_count, 'color': '#1890FF'},
            {'name': '数据不可用', 'value': unavailable_count, 'color': '#ffffff'},
            {'name': '离线', 'value': offline_count, 'color': '#666666'},
            {'name': '等待首次数据', 'value': awaiting_data_count, 'color': '#722ed1'},
        ]
    })


@login_required
def api_devices(request):
    """获取设备列表（仅辖区内设备 + 坐标回退 + 区县匹配）"""
    from shapely.geometry import Point

    project_id = request.GET.get('project_id', '')
    current_project = None
    if project_id:
        current_project = Project.objects.filter(id=project_id).first()
    if not current_project:
        current_project = Project.objects.filter(status='recording').first()
    devices = Device.objects.filter(project=current_project) if current_project else Device.objects.none()

    buffered_geoms, region_geoms = _load_jurisdiction_geoms(current_project)

    data = []
    seen_regions = set()
    region_polygons = []

    for device in devices:
        # 地理围栏：设备坐标不在辖区（含缓冲）内 → 不显示
        if not _device_in_jurisdiction(device, buffered_geoms):
            continue

        # 过滤空壳设备（HTTP注册产生，无健康数据）
        if not device.health_data.exists():
            continue

        latest_health = device.health_data.first()
        health_info = {}
        if latest_health:
            health_info = {
                'heart_rate': latest_health.heart_rate,
                'blood_oxygen': latest_health.blood_oxygen,
                'blood_pressure_sys': latest_health.blood_pressure_sys,
                'blood_pressure_dia': latest_health.blood_pressure_dia,
                'step_frequency': latest_health.step_frequency,
                'core_temperature': latest_health.core_temperature,
                'steps': latest_health.steps,
                'data_quality': latest_health.data_quality,
                'core_temp_source': latest_health.core_temp_source,
            }
            risk_level, risk_text = get_device_risk_level(device)
        else:
            risk_level, risk_text = get_device_risk_level(device)

        # 坐标回退
        device_lat, device_lng = _resolve_device_coords(device)

        # 匹配所在区县
        matched_region = None
        if region_geoms and device_lng is not None and device_lat is not None:
            pt = Point(device_lng, device_lat)
            for code, (geom, name, geojson_str) in region_geoms.items():
                try:
                    if geom.contains(pt):
                        matched_region = {'code': code, 'name': name}
                        if code not in seen_regions:
                            seen_regions.add(code)
                            region_polygons.append({
                                'code': code,
                                'name': name,
                                'geojson': json.loads(geojson_str),
                            })
                        break
                except Exception:
                    pass

        data.append({
            'id': device.id,
            'device_id': device.device_id,
            'asset_code': device.asset_code,
            'officer_name': device.officer_name,
            'officer_age': device.officer_age,
            'officer_gender': device.officer_gender,
            'is_online': is_device_effectively_online(device),
            'latitude': device_lat,
            'longitude': device_lng,
            'marker_shape': device.marker_shape,
            'marker_color': device.marker_color,
            'bind_status': device.bind_status,
            'hardware_serial': device.hardware_serial or '',
            'battery_level': device.battery_level,
            'worn': device.worn,
            'firmware_version': device.firmware_version,
            'risk_level': risk_level,
            'risk_text': risk_text,
            'health': health_info,
            'region': matched_region,
            'last_report_time': timezone.localtime(device.last_report_time).strftime('%Y-%m-%d %H:%M:%S') if device.last_report_time else '',
            'offline_duration': _format_offline_duration(device),
            'has_history': device.health_data.exists(),
        })

    # 若没有设备匹配到区县，回退显示项目全部辖区（保证地图能跳转）
    if not region_polygons and current_project:
        for r in current_project.jurisdiction_regions.filter(level='county').exclude(geometry_geojson=''):
            try:
                region_polygons.append({
                    'code': r.code,
                    'name': r.name,
                    'geojson': json.loads(r.geometry_geojson),
                })
            except Exception:
                pass

    return JsonResponse({'devices': data, 'region_polygons': region_polygons})


@login_required
def api_device_detail(request, device_id):
    """获取设备详细信息"""
    device = get_object_or_404(Device, id=device_id)
    latest_health = device.health_data.first()

    health_info = {}
    if latest_health:
        health_info = {
            'heart_rate': latest_health.heart_rate,
            'blood_oxygen': latest_health.blood_oxygen,
            'blood_pressure_sys': latest_health.blood_pressure_sys,
            'blood_pressure_dia': latest_health.blood_pressure_dia,
            'step_frequency': latest_health.step_frequency,
            'core_temperature': latest_health.core_temperature,
            'steps': latest_health.steps,
            'data_quality': latest_health.data_quality,
            'core_temp_source': latest_health.core_temp_source,
            'timestamp': latest_health.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        }
        # 风险等级 — 统一调用 get_device_risk_level()
        risk_level, risk_text = get_device_risk_level(device)
    else:
        risk_level, risk_text = get_device_risk_level(device)

    # 最近2小时轨迹
    two_hours_ago = timezone.now() - timedelta(hours=2)
    locations = device.locations.filter(timestamp__gte=two_hours_ago).order_by('timestamp')
    trajectory = [{'lat': loc.latitude, 'lng': loc.longitude, 'time': loc.timestamp.strftime('%H:%M:%S')} for loc in locations]

    # 历史健康数据（最近20条）
    health_history = []
    for hd in device.health_data.all()[:20]:
        health_history.append({
            'heart_rate': hd.heart_rate,
            'blood_oxygen': hd.blood_oxygen,
            'core_temperature': hd.core_temperature,
            'timestamp': hd.timestamp.strftime('%H:%M:%S'),
        })

    return JsonResponse({
        'device': {
            'id': device.id,
            'device_id': device.device_id,
            'asset_code': device.asset_code,
            'officer_name': device.officer_name,
            'officer_age': device.officer_age,
            'officer_gender': device.officer_gender,
            'is_online': is_device_effectively_online(device),
            'battery_level': device.battery_level,
            'worn': device.worn,
            'firmware_version': device.firmware_version,
            'marker_shape': device.marker_shape,
            'marker_color': device.marker_color,
        },
        'health': health_info,
        'risk_level': risk_level,
        'risk_text': risk_text,
        'trajectory': trajectory,
        'health_history': health_history,
    })


@login_required
def api_alerts(request):
    """获取预警历史"""
    project_id = request.GET.get('project_id', '')
    if not project_id:
        recording = Project.objects.filter(status='recording').first()
        project_id = recording.id if recording else None
    alerts = Alert.objects.all()
    if project_id:
        alerts = alerts.filter(device__project_id=project_id)

    limit = int(request.GET.get('limit', 50))
    alerts = alerts[:limit]

    data = []
    for alert in alerts:
        data.append({
            'id': alert.id,
            'officer_name': alert.device.officer_name,
            'device_id': alert.device.device_id,
            'alert_type': alert.alert_type,
            'alert_type_display': alert.get_alert_type_display(),
            'risk_level': alert.risk_level,
            'core_temperature': alert.core_temperature,
            'heart_rate': alert.heart_rate,
            'blood_oxygen': alert.blood_oxygen,
            'advice_text': alert.advice_text,
            'is_read': alert.is_read,
            'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    return JsonResponse({'alerts': data})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_clear_alerts(request):
    """清除预警记录"""
    project_id = request.POST.get('project_id', '')
    keep = int(request.POST.get('keep', 0))
    alerts = Alert.objects.all()
    if project_id:
        alerts = alerts.filter(device__project_id=project_id)
    if keep > 0:
        # 保留最近N条
        to_keep = alerts.order_by('-created_at')[:keep].values_list('id', flat=True)
        alerts.exclude(id__in=to_keep).delete()
    else:
        alerts.delete()
    return JsonResponse({'ok': True})


# ============ 项目管理 API ============

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_project_create(request):
    data = json.loads(request.body)
    status = data.get('status', 'recording')
    # 新建录入中项目时，停掉其他所有项目
    if status == 'recording':
        Project.objects.filter(status='recording').update(status='stopped')
    project = Project.objects.create(
        name=data.get('name', '新项目'),
        description=data.get('description', ''),
        jurisdiction_geo=data.get('jurisdiction_geo', ''),
        jurisdiction_color=data.get('jurisdiction_color', '#1890FF'),
        status=status,
    )
    region_codes = data.get('region_codes', [])
    if region_codes:
        regions = Region.objects.filter(code__in=region_codes, level='county')
        project.jurisdiction_regions.set(regions)
    return JsonResponse({'ok': True, 'id': project.id})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_project_update(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    data = json.loads(request.body)
    if 'name' in data:
        project.name = data['name']
    if 'description' in data:
        project.description = data['description']
    if 'status' in data:
        new_status = data['status']
        if new_status == 'recording' and project.status != 'recording':
            # 切换录入中：先停掉当前录入中的项目
            Project.objects.filter(status='recording').update(status='stopped')
        project.status = new_status
    if 'jurisdiction_geo' in data:
        project.jurisdiction_geo = data['jurisdiction_geo']
    if 'jurisdiction_color' in data:
        project.jurisdiction_color = data['jurisdiction_color']
    project.save()
    # 更新区域关联
    if 'region_codes' in data:
        region_codes = data['region_codes']
        if region_codes:
            regions = Region.objects.filter(code__in=region_codes, level='county')
            project.jurisdiction_regions.set(regions)
        else:
            project.jurisdiction_regions.clear()
    return JsonResponse({'ok': True})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_project_delete(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    project.delete()
    return JsonResponse({'ok': True})


@login_required
def api_project_jurisdiction(request, project_id):
    """获取项目的辖区 GeoJSON（从 M2M 区域或 legacy 字段）"""
    project = get_object_or_404(Project, id=project_id)

    features = []
    region_list = []  # 所有关联区域（含无 geometry 的），供编辑表单使用

    # 优先使用 M2M 关联区域
    regions = project.jurisdiction_regions.all()
    if regions.exists():
        for r in regions:
            region_list.append({
                'code': r.code,
                'name': r.name,
            })
            if r.geometry_geojson:
                geom = json.loads(r.geometry_geojson)
                features.append({
                    'type': 'Feature',
                    'geometry': geom,
                    'properties': {
                        'name': r.name,
                        'level': r.level,
                        'code': r.code,
                    }
                })
    # 回退到 legacy jurisdiction_geo 字段
    elif project.jurisdiction_geo:
        try:
            legacy = json.loads(project.jurisdiction_geo)
            if isinstance(legacy, dict):
                if legacy.get('type') == 'FeatureCollection':
                    features = legacy.get('features', [])
                elif legacy.get('type') in ('Polygon', 'MultiPolygon'):
                    features = [{
                        'type': 'Feature',
                        'geometry': legacy,
                        'properties': {'name': project.name}
                    }]
            elif isinstance(legacy, list):
                features = legacy
        except (json.JSONDecodeError, TypeError):
            pass
        # legacy 模式下从 features 提取 region_list
        for f in features:
            props = f.get('properties', {})
            code = props.get('code', '')
            name = props.get('name', '')
            if name:
                region_list.append({'code': code, 'name': name})

    return JsonResponse({
        'project_id': project.id,
        'project_name': project.name,
        'project_description': project.description or '',
        'project_status': project.status,
        'fill_color': project.jurisdiction_color or '#1890FF',
        'stroke_color': project.jurisdiction_color or '#1890FF',
        'region_list': region_list,
        'geojson': {
            'type': 'FeatureCollection',
            'features': features,
        }
    })


# ============ 项目 CSV 导出 API ============

@login_required
def api_project_export_csv(request, project_id):
    """导出项目所有健康数据为 CSV 文件"""
    project = get_object_or_404(Project, id=project_id)
    devices = Device.objects.filter(project_id=project_id)

    all_rows = []
    for device in devices:
        for hd in device.health_data.all().order_by('timestamp'):
            all_rows.append({
                '设备ID': device.device_id,
                '民警姓名': device.officer_name,
                '警号/资产编码': device.asset_code or '',
                '时间': hd.timestamp.strftime('%Y-%m-%d %H:%M:%S') if hd.timestamp else '',
                '心率(bpm)': hd.heart_rate,
                '血氧(%)': hd.blood_oxygen,
                '收缩压(mmHg)': hd.blood_pressure_sys,
                '舒张压(mmHg)': hd.blood_pressure_dia,
                '步频(步/分)': hd.step_frequency,
                '核心温度(℃)': hd.core_temperature,
                '温度来源': hd.core_temp_source or '',
                '步数': hd.steps,
                '纬度': hd.latitude,
                '经度': hd.longitude,
            })

    if not all_rows:
        return JsonResponse({'ok': False, 'message': '该项目没有可导出的健康数据'}, status=404)

    # 写 CSV
    export_dir = os.path.join(settings.BASE_DIR, 'data_cache', 'exports')
    os.makedirs(export_dir, exist_ok=True)
    filename = f'project_{project_id}_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    filepath = os.path.join(export_dir, filename)

    fieldnames = list(all_rows[0].keys())
    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    with open(filepath, 'rb') as f:
        response = HttpResponse(f.read(), content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Content-Length'] = os.path.getsize(filepath)
    return response


# ============ 项目用户管理 API ============

def _format_offline_duration(device) -> str:
    """计算离线时长文本（仅对有历史记录但离线的设备有效，含超时判定）"""
    if is_device_effectively_online(device):
        return ''
    if device.last_report_time is None:
        return ''
    # 有历史健康数据才算"留过记录"
    has_history = device.health_data.exists()
    if not has_history:
        return ''
    now = timezone.now()
    delta = now - device.last_report_time
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return '刚刚离线'
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    if days > 0:
        return f'离线 {days}天{hours}小时'
    if hours > 0:
        return f'离线 {hours}小时{minutes}分钟'
    return f'离线 {minutes}分钟'


@login_required
def api_project_users(request, project_id):
    """获取项目下的所有用户（设备），仅返回辖区内设备"""
    project = get_object_or_404(Project, id=project_id)
    buffered_geoms, _ = _load_jurisdiction_geoms(project)
    devices = project.devices.all().order_by('-created_at')
    data = []
    for d in devices:
        if not _device_in_jurisdiction(d, buffered_geoms):
            continue
        # 过滤空壳设备（无健康数据）
        if not d.health_data.exists():
            continue
        data.append({
            'id': d.id,
            'device_id': d.device_id,
            'hardware_serial': d.hardware_serial or '',
            'mac_address': d.mac_address or '',
            'officer_name': d.officer_name or '(待填写)',
            'officer_age': d.officer_age,
            'officer_gender': d.officer_gender,
            'asset_code': d.asset_code,
            'bind_status': d.bind_status,
            'bind_status_display': d.get_bind_status_display(),
            'is_online': is_device_effectively_online(d),
            'battery_level': d.battery_level,
            'last_report_time': timezone.localtime(d.last_report_time).strftime('%Y-%m-%d %H:%M:%S') if d.last_report_time else '',
            'offline_duration': _format_offline_duration(d),
            'has_history': d.health_data.exists(),
            'created_at': d.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })
    return JsonResponse({'users': data, 'total': len(data)})


# ============ 设备管理 API ============

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_device_create(request):
    """手动创建手表（管理员操作），之后手表通过中继上报数据"""
    data = json.loads(request.body)
    device_id = data.get('device_id', '').strip()
    if not device_id:
        return JsonResponse({'error': '设备ID不能为空', 'code': 'MISSING_DEVICE_ID'}, status=400)

    # 检查是否已存在
    if Device.objects.filter(device_id=device_id).exists():
        return JsonResponse({'error': f'设备 {device_id} 已存在', 'code': 'DUPLICATE'}, status=409)

    project_id = data.get('project_id')
    project = None
    if project_id:
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            pass
    if not project:
        project = Project.objects.filter(status='recording').first() or Project.objects.first()
    if not project:
        return JsonResponse({'error': '系统没有可用项目', 'code': 'NO_PROJECT'}, status=500)

    device = Device.objects.create(
        project=project,
        device_id=device_id,
        bind_status='active',
        officer_name=data.get('officer_name', ''),
        officer_age=data.get('officer_age') or None,
        officer_gender=data.get('officer_gender', '男'),
        asset_code=data.get('asset_code', ''),
        marker_shape=data.get('marker_shape', 'circle'),
        marker_color=data.get('marker_color', '#1890FF'),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
    )

    return JsonResponse({
        'ok': True,
        'id': device.id,
        'device_id': device.device_id,
        'message': '手表创建成功，等待中继上报数据',
    })

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_device_update(request, device_id):
    device = get_object_or_404(Device, id=device_id)
    data = json.loads(request.body)
    for field in ['officer_name', 'officer_age', 'officer_gender', 'marker_shape',
                   'marker_color', 'asset_code', 'latitude', 'longitude']:
        if field in data:
            setattr(device, field, data[field])
    if 'mac_address' in data:
        device.mac_address = data['mac_address'].strip() or None
    # 允许切换项目
    if 'project_id' in data and data['project_id']:
        try:
            device.project = Project.objects.get(id=data['project_id'])
        except Project.DoesNotExist:
            pass
    device.save()
    return JsonResponse({'ok': True})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_device_delete(request, device_id):
    device = get_object_or_404(Device, id=device_id)
    device.delete()
    return JsonResponse({'ok': True})


# ============ 设备绑定管理 API ============

@login_required
def api_pending_devices(request):
    """获取待绑定设备列表"""
    devices = Device.objects.filter(bind_status='pending').order_by('-created_at')
    data = []
    for d in devices:
        data.append({
            'id': d.id,
            'device_id': d.device_id,
            'hardware_serial': d.hardware_serial or '',
            'is_online': is_device_effectively_online(d),
            'last_report_time': timezone.localtime(d.last_report_time).strftime('%Y-%m-%d %H:%M:%S') if d.last_report_time else '',
            'latitude': d.latitude,
            'longitude': d.longitude,
            'created_at': d.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'project_id': d.project_id,
            'project_name': d.project.name,
        })
    return JsonResponse({'pending_devices': data})


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def api_device_bind(request, device_id):
    """激活并绑定设备（管理员填写民警信息后激活）"""
    device = get_object_or_404(Device, id=device_id)

    if device.bind_status == 'active':
        return JsonResponse({'error': '该设备已激活', 'code': 'ALREADY_ACTIVE'}, status=400)
    if device.bind_status == 'disabled':
        return JsonResponse({'error': '该设备已被禁用', 'code': 'DEVICE_DISABLED'}, status=400)

    data = json.loads(request.body)

    # 更新项目归属
    if 'project_id' in data:
        try:
            device.project = Project.objects.get(id=data['project_id'])
        except Project.DoesNotExist:
            return JsonResponse({'error': '项目不存在'}, status=400)

    # 更新民警信息
    if 'officer_name' in data:
        device.officer_name = data['officer_name']
    if 'officer_age' in data:
        device.officer_age = data['officer_age']
    if 'officer_gender' in data:
        device.officer_gender = data['officer_gender']
    if 'asset_code' in data:
        device.asset_code = data['asset_code']
    if 'marker_shape' in data:
        device.marker_shape = data['marker_shape']
    if 'marker_color' in data:
        device.marker_color = data['marker_color']
    if 'latitude' in data:
        device.latitude = data['latitude']
    if 'longitude' in data:
        device.longitude = data['longitude']

    # 激活
    device.bind_status = 'active'
    device.save()

    return JsonResponse({
        'ok': True,
        'device_id': device.device_id,
        'bind_status': 'active',
        'message': '设备已激活',
    })


# ============ 行政区划 API ============

@login_required
def api_regions(request):
    """获取区域列表，支持过滤"""
    level = request.GET.get('level', '')
    parent_code = request.GET.get('parent_code', '')
    search = request.GET.get('search', '')
    with_geometry = request.GET.get('with_geometry', 'true') == 'true'
    ids = request.GET.get('ids', '')

    qs = Region.objects.all()

    if level:
        qs = qs.filter(level=level)
    if parent_code:
        qs = qs.filter(parent_code=parent_code)
    if search:
        qs = qs.filter(name__icontains=search)
    if ids:
        id_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
        if id_list:
            qs = qs.filter(id__in=id_list)

    # 不分页时，用 defer 优化大查询
    if with_geometry:
        qs = qs.only('code', 'name', 'level', 'parent_code', 'parent_id',
                     'geometry_geojson', 'center_lat', 'center_lng',
                     'eng_name', 'year')
    else:
        qs = qs.defer('geometry_geojson')

    regions = []
    for r in qs[:500]:
        item = {
            'id': r.id,
            'code': r.code,
            'name': r.name,
            'level': r.level,
            'parent_code': r.parent_code,
            'parent_id': r.parent_id,
            'eng_name': r.eng_name or '',
            'year': r.year,
            'center_lat': r.center_lat,
            'center_lng': r.center_lng,
        }
        if with_geometry and r.geometry_geojson:
            item['geometry'] = json.loads(r.geometry_geojson)
        regions.append(item)

    return JsonResponse({'regions': regions, 'total': qs.count()})


@login_required
def api_region_detail(request, region_id):
    """获取单个区域详情（含几何）"""
    region = get_object_or_404(Region, id=region_id)
    geometry = None
    if region.geometry_geojson:
        geometry = json.loads(region.geometry_geojson)

    return JsonResponse({
        'region': {
            'id': region.id,
            'code': region.code,
            'name': region.name,
            'level': region.level,
            'parent_code': region.parent_code,
            'parent_id': region.parent_id,
            'eng_name': region.eng_name or '',
            'year': region.year,
            'center_lat': region.center_lat,
            'center_lng': region.center_lng,
            'geometry': geometry,
        }
    })


@login_required
def api_regions_children(request):
    """获取某个区域的子级"""
    code = request.GET.get('code', '')
    level = request.GET.get('level', '')
    if not code:
        return JsonResponse({'children': [], 'error': '缺少 code 参数'})

    qs = Region.objects.filter(parent_code=code)
    if level:
        qs = qs.filter(level=level)

    children = []
    for r in qs:
        children.append({
            'id': r.id,
            'code': r.code,
            'name': r.name,
            'level': r.level,
        })

    return JsonResponse({'children': children})


@login_required
def api_regions_tree(request):
    """获取三级区域树（无几何数据，用于级联选择器）"""
    import json as _json

    all_regions = Region.objects.defer('geometry_geojson').order_by('code')

    # 按层级分组
    provinces = []
    pref_map = {}  # province_code -> [prefectures]
    county_map = {}  # prefecture_code -> [counties]

    for r in all_regions:
        if r.level == 'province':
            provinces.append(r)
        elif r.level == 'prefecture':
            pref_map.setdefault(r.parent_code, []).append(r)
        elif r.level == 'county':
            county_map.setdefault(r.parent_code, []).append(r)

    tree = []
    for prov in provinces:
        prov_children = []
        # 地级市（常规三级结构：省→市→县）
        for pref in pref_map.get(prov.code, []):
            pref_children = []
            for county in county_map.get(pref.code, []):
                pref_children.append({
                    'code': county.code,
                    'name': county.name,
                    'level': 'county',
                })
            prov_children.append({
                'code': pref.code,
                'name': pref.name,
                'level': 'prefecture',
                'children': pref_children,
            })
        # 省直辖县级区划（直辖市/省直管县/自治区直辖县）— 始终追加，与地级市同级
        for county in county_map.get(prov.code, []):
            prov_children.append({
                'code': county.code,
                'name': county.name,
                'level': 'county',
            })
        tree.append({
            'code': prov.code,
            'name': prov.name,
            'level': 'province',
            'children': prov_children,
        })

    return JsonResponse({'tree': tree})


# ============ 手表端 API（device_id 鉴权，无需 session 登录）============

def _auto_create_watch_device(device_id, **extra_fields):
    """自动创建设备（手表通过 MQTT 或 HTTP 首次上报数据时调用）。
    设备初始状态为 pending，需管理员激活后才能上传 vital 数据。"""
    from django.db import IntegrityError
    default_project = Project.objects.filter(status='recording').first() or Project.objects.first()
    if not default_project:
        return None
    try:
        device = Device.objects.create(
            project=default_project,
            device_id=device_id,
            bind_status='pending',
            is_online=True,
            last_report_time=timezone.now(),
            officer_name='',  # 待管理员填写
            latitude=extra_fields.get('latitude'),
            longitude=extra_fields.get('longitude'),
            battery_level=extra_fields.get('battery_level', None),
            firmware_version=extra_fields.get('firmware_version', ''),
            worn=extra_fields.get('worn', True),
        )
    except IntegrityError:
        # 并发创建时，另一个线程/请求已创建，直接取已有记录
        device = Device.objects.get(device_id=device_id)
    return device


def _get_device_from_header(request, auto_create=False):
    """从请求头 X-Device-ID 获取设备，鉴权失败返回 (None, error_response)

    auto_create=True 时，设备不存在自动创建 pending 记录（用于 heartbeat 和 upload）。
    """
    device_id = request.headers.get('X-Device-ID', '') or request.GET.get('device_id', '')
    if not device_id:
        return None, JsonResponse({'error': '缺少设备ID', 'code': 'MISSING_DEVICE_ID'}, status=401)
    try:
        device = Device.objects.get(device_id=device_id)
    except Device.DoesNotExist:
        if auto_create:
            device = _auto_create_watch_device(device_id)
            if device is None:
                return None, JsonResponse({'error': '系统未配置项目，无法自动注册设备', 'code': 'NO_PROJECT'}, status=500)
        else:
            return None, JsonResponse({'error': '设备未注册', 'code': 'DEVICE_NOT_FOUND'}, status=404)
    return device, None


def _check_device_active(device):
    """检查设备是否已激活，未激活返回 (None, error_response)"""
    if device.bind_status == 'disabled':
        return None, JsonResponse({'error': '该设备已被禁用', 'code': 'DEVICE_DISABLED'}, status=403)
    if device.bind_status == 'pending':
        return None, JsonResponse({'error': '设备未激活，请联系管理员', 'code': 'DEVICE_NOT_ACTIVATED',
                                    'bind_status': 'pending'}, status=403)
    return device, None


@csrf_exempt
@require_http_methods(["POST"])
def watch_register(request):
    """
    手表自注册接口（无需鉴权）
    手表首次开机时调用，上报硬件序列号，获取 device_id
    如果硬件序列号已注册，直接返回已有 device_id
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '请求体不是有效的JSON', 'code': 'INVALID_JSON'}, status=400)

    hardware_serial = data.get('hardware_serial', '').strip()
    if not hardware_serial:
        return JsonResponse({'error': '缺少硬件序列号', 'code': 'MISSING_SERIAL'}, status=400)

    # 检查是否已注册
    firmware_version = data.get('firmware_version', '') or ''
    existing = Device.objects.filter(hardware_serial=hardware_serial).first()
    if existing:
        if existing.bind_status == 'disabled':
            return JsonResponse({'error': '该设备已被禁用', 'code': 'DEVICE_DISABLED'}, status=403)

        existing.is_online = True
        existing.last_report_time = timezone.now()
        if data.get('latitude'):
            existing.latitude = data['latitude']
        if data.get('longitude'):
            existing.longitude = data['longitude']
        if firmware_version:
            existing.firmware_version = firmware_version
        update_fields = ['is_online', 'last_report_time']
        if data.get('latitude'):
            update_fields.append('latitude')
        if data.get('longitude'):
            update_fields.extend(['latitude', 'longitude'])
        if firmware_version:
            update_fields.append('firmware_version')
        existing.save(update_fields=update_fields)

        msg = '设备已激活' if existing.bind_status == 'active' else '设备已在待审核列表中，请等待管理员激活'
        return JsonResponse({
            'ok': True,
            'device_id': existing.device_id,
            'bind_status': existing.bind_status,
            'message': msg,
        })

    # 新注册：生成 device_id
    import secrets
    while True:
        new_id = 'WATCH-' + secrets.token_hex(4).upper()
        if not Device.objects.filter(device_id=new_id).exists():
            break

    # 分配到默认项目（取第一个 recording 状态的项目，没有则取第一个）
    default_project = Project.objects.filter(status='recording').first() or Project.objects.first()
    if not default_project:
        return JsonResponse({'error': '系统未配置项目，请联系管理员', 'code': 'NO_PROJECT'}, status=500)

    device = Device.objects.create(
        project=default_project,
        device_id=new_id,
        hardware_serial=hardware_serial,
        firmware_version=firmware_version,
        bind_status='pending',
        is_online=True,
        last_report_time=timezone.now(),
        latitude=data.get('latitude'),
        longitude=data.get('longitude'),
        officer_name='',  # 待管理员填写
    )

    return JsonResponse({
        'ok': True,
        'device_id': device.device_id,
        'bind_status': 'pending',
        'message': '设备已注册，等待管理员激活',
    }, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def watch_upload(request):
    """
    Vital 数据上传接口 — 接收手表生命体征数据。

    手表发送格式（vital 消息，camelCase）:
    {
      "deviceId": "A80-abc123",
      "timestamp": 1752672000000,         // Unix 毫秒
      "latitude": 39.9042,
      "longitude": 116.4074,
      "gpsAccuracy": 5.0,
      "heartRate": 78,
      "spo2": 98,
      "bloodPressure": "120/80",
      "coreTemp": 37.1,
      "coreTempSource": "heart_rate_estimate",
      "steps": 3421,
      "batteryLevel": 85,
      "worn": true,
      "dataQuality": "complete",
      "firmwareVersion": "1.0.0"
    }

    兼容旧格式（中继服务器转发，snake_case）:
    {"heart_rate": 98, "core_temperature": 37.5, "timestamp": "ISO-8601"}

    请求头: X-Device-ID: <device_id>
    """
    device, err = _get_device_from_header(request, auto_create=True)
    if err:
        return err

    _, err = _check_device_active(device)
    if err:
        return err

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '请求体不是有效的JSON', 'code': 'INVALID_JSON'}, status=400)

    # ── 判断格式：camelCase（手表直发） vs snake_case（中继转发）──
    is_watch_format = 'heartRate' in data or 'deviceId' in data

    if is_watch_format:
        # === 手表直发格式 (camelCase) — 中继没发的字段不填假数据 ===
        _hr = data.get('heartRate')
        heart_rate = int(_hr) if _hr is not None else None
        _spo2 = data.get('spo2')
        spo2 = float(_spo2) if _spo2 is not None else None

        # 血压解析
        bp_sys, bp_dia = None, None
        bp_str = data.get('bloodPressure', '')
        if bp_str and '/' in str(bp_str):
            try:
                parts = str(bp_str).split('/')
                bp_sys = int(parts[0])
                bp_dia = int(parts[1])
            except (ValueError, IndexError):
                pass

        _ct = data.get('coreTemp')
        core_temperature = float(_ct) if _ct is not None else None
        core_temp_source = data.get('coreTempSource', '') or ''
        _steps = data.get('steps')
        steps = int(_steps) if _steps is not None else None
        _gps = data.get('gpsAccuracy')
        gps_accuracy = float(_gps) if _gps is not None else None
        data_quality = data.get('dataQuality', '') or ''
        _bat = data.get('batteryLevel')
        battery_level = int(_bat) if _bat is not None else None
        worn = data.get('worn')
        worn = bool(worn) if worn is not None else None
        firmware_version = str(data.get('firmwareVersion', '') or '') or ''
        _lat = data.get('latitude')
        lat = float(_lat) if _lat is not None else None
        _lng = data.get('longitude')
        lng = float(_lng) if _lng is not None else None

        # 时间戳：Unix 毫秒 → datetime
        ts = data.get('timestamp')
        if ts and isinstance(ts, (int, float)):
            from datetime import datetime as dt
            report_time = dt.fromtimestamp(ts / 1000.0, tz=timezone.get_current_timezone())
        else:
            report_time = timezone.now()

    else:
        # === 旧格式（中继服务器转发，snake_case）— 同样不填假数据 ===
        _hr = data.get('heart_rate')
        heart_rate = int(_hr) if _hr is not None else None
        _spo2 = data.get('blood_oxygen')
        spo2 = float(_spo2) if _spo2 is not None else None
        _sys = data.get('blood_pressure_sys')
        bp_sys = int(_sys) if _sys is not None else None
        _dia = data.get('blood_pressure_dia')
        bp_dia = int(_dia) if _dia is not None else None
        _steps = data.get('step_frequency')
        steps = int(_steps) if _steps is not None else None
        data_quality = data.get('data_quality', '') or ''
        _gps = data.get('gps_accuracy')
        gps_accuracy = float(_gps) if _gps is not None else None
        _bat = data.get('battery_level')
        battery_level = int(_bat) if _bat is not None else None
        worn = data.get('worn')
        worn = bool(worn) if worn is not None else None
        firmware_version = str(data.get('firmware_version', '') or '') or ''
        _lat = data.get('latitude')
        lat = float(_lat) if _lat is not None else None
        _lng = data.get('longitude')
        lng = float(_lng) if _lng is not None else None

        # 核心温度 — 只使用中继上报的值，不做本地估算
        _ct = data.get('core_temperature')
        core_temperature = float(_ct) if _ct is not None else None
        core_temp_source = data.get('core_temp_source', '') or ''

        # 中继服务器 thermal 元数据
        thermal = data.get('thermal', {})
        if thermal and isinstance(thermal, dict):
            core_temp_source = thermal.get('current_source', core_temp_source)

        # 时间戳
        report_time_str = data.get('timestamp', '')
        if report_time_str:
            try:
                from django.utils.dateparse import parse_datetime
                report_time = parse_datetime(report_time_str)
            except Exception:
                report_time = timezone.now()
        else:
            report_time = timezone.now()

    # ── 保存健康数据 ──
    health = HealthData.objects.create(
        device=device,
        heart_rate=heart_rate,
        blood_oxygen=spo2,
        blood_pressure_sys=bp_sys,
        blood_pressure_dia=bp_dia,
        core_temperature=core_temperature,
        core_temp_source=core_temp_source,
        steps=steps,
        gps_accuracy=gps_accuracy,
        data_quality=data_quality,
        latitude=lat,
        longitude=lng,
    )
    health.timestamp = report_time
    health.save(update_fields=['timestamp'])

    # ── 更新设备状态 ──
    device.is_online = True
    device.last_report_time = report_time
    update_fields = ['is_online', 'last_report_time']
    if lat is not None:
        device.latitude = lat
        update_fields.append('latitude')
    if lng is not None:
        device.longitude = lng
        update_fields.append('longitude')
    if battery_level is not None:
        device.battery_level = battery_level
        update_fields.append('battery_level')
    if worn is not None:
        device.worn = worn
        update_fields.append('worn')
    if firmware_version:
        device.firmware_version = firmware_version
        update_fields.append('firmware_version')
    device.save(update_fields=update_fields)

    # ── 保存位置轨迹（有坐标才保存）──
    if lat is not None and lng is not None:
        DeviceLocation.objects.create(
            device=device,
            latitude=lat,
            longitude=lng,
        )

    # ── 温度预警判断（阈值取自 models.TEMP_WARNING_THRESHOLD / TEMP_NORMAL_WARNING）──
    alert_created = None
    if core_temperature is not None and core_temperature >= TEMP_WARNING_THRESHOLD:
        alert_created = Alert.objects.create(
            device=device,
            alert_type='high_risk',
            risk_level='high_risk',
            core_temperature=core_temperature,
            heart_rate=heart_rate,
            blood_oxygen=spo2,
            advice_text='1. 立即停止当前活动，转移至阴凉通风处休息\n2. 补充电解质饮料，如症状持续及时就医',
        )
    elif core_temperature is not None and core_temperature >= TEMP_NORMAL_WARNING:
        alert_created = Alert.objects.create(
            device=device,
            alert_type='normal',
            risk_level='warning',
            core_temperature=core_temperature,
            heart_rate=heart_rate,
            blood_oxygen=spo2,
            advice_text='1. 适当降低活动强度，注意补充水分\n2. 持续监测体温变化，必要时暂停执勤',
        )

    # ── 转发 core_temperature 到 watch-api ──
    forward_core_temperature(
        device_id=device.device_id,
        core_temperature=core_temperature,
        timestamp=report_time.isoformat() if hasattr(report_time, 'isoformat') else str(report_time),
        source=core_temp_source,
    )

    # ── 构建响应 ──
    response_data = {
        'ok': True,
        'core_temperature': core_temperature,
        'thermal': {
            'status': 'ready',
            'current_core_temperature': core_temperature,
            'current_source': core_temp_source,
            'confidence': 'medium' if core_temp_source == 'informer_model_1' else 'low',
            'samples_collected': 0,
            'samples_required': 20,
            'forecast': None,
        },
    }
    if alert_created:
        response_data['alert'] = {
            'id': alert_created.id,
            'type': alert_created.alert_type,
            'risk_level': alert_created.risk_level,
            'core_temperature': alert_created.core_temperature,
            'officer_name': device.officer_name or device.device_id,
            'advice': alert_created.advice_text,
        }

    return JsonResponse(response_data)


@csrf_exempt
@require_http_methods(["POST"])
def watch_heartbeat(request):
    """
    手表状态上报接口 — 轻量 status 消息（所有状态设备均可调用）

    请求头: X-Device-ID: <device_id>
    请求体 (status 消息):
    {
      "online": true,
      "latitude": 39.9,
      "longitude": 116.4,
      "battery": 85
    }

    维持设备在线状态、位置、电量。
    响应中返回 bind_status，手表据此判断是否已被激活。
    """
    device, err = _get_device_from_header(request, auto_create=True)
    if err:
        return err

    if device.bind_status == 'disabled':
        return JsonResponse({'error': '该设备已被禁用', 'code': 'DEVICE_DISABLED'}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    # 更新状态
    device.is_online = bool(data.get('online', True))
    device.last_report_time = timezone.now()
    if 'latitude' in data and data['latitude'] is not None:
        device.latitude = float(data['latitude'])
    if 'longitude' in data and data['longitude'] is not None:
        device.longitude = float(data['longitude'])
    if 'battery' in data and data['battery'] is not None:
        device.battery_level = int(data['battery'])

    update_fields = ['is_online', 'last_report_time']
    if 'latitude' in data and data['latitude'] is not None:
        update_fields.append('latitude')
    if 'longitude' in data and data['longitude'] is not None:
        update_fields.append('longitude')
    if 'battery' in data and data['battery'] is not None:
        update_fields.append('battery_level')
    device.save(update_fields=update_fields)

    return JsonResponse({
        'ok': True,
        'server_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        'device_id': device.device_id,
        'bind_status': device.bind_status,
    })


@csrf_exempt
@require_http_methods(["GET"])
def watch_alerts(request):
    """
    手表拉取预警接口（仅激活设备可调用）
    请求头: X-Device-ID: <device_id>
    返回该设备最近未读的预警记录
    """
    device, err = _get_device_from_header(request)
    if err:
        return err

    _, err = _check_device_active(device)
    if err:
        return err

    limit = int(request.GET.get('limit', 10))
    alerts = device.alerts.filter(is_read=False).order_by('-created_at')[:limit]

    data = []
    for alert in alerts:
        data.append({
            'id': alert.id,
            'alert_type': alert.alert_type,
            'risk_level': alert.risk_level,
            'core_temperature': alert.core_temperature,
            'officer_name': alert.device.officer_name or alert.device.device_id,
            'advice': alert.advice_text,
            'heart_rate': alert.heart_rate,
            'blood_oxygen': alert.blood_oxygen,
            'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })

    return JsonResponse({'alerts': data})


@csrf_exempt
@require_http_methods(["POST"])
def watch_ack_alert(request, alert_id):
    """
    手表确认已读预警（仅激活设备可调用）
    请求头: X-Device-ID: <device_id>
    """
    device, err = _get_device_from_header(request)
    if err:
        return err

    _, err = _check_device_active(device)
    if err:
        return err

    alert = get_object_or_404(Alert, id=alert_id, device=device)
    alert.is_read = True
    alert.save(update_fields=['is_read'])

    return JsonResponse({'ok': True})

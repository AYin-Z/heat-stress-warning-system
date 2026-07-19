"""热应激预警系统 - 数据模型"""

from django.db import models


# ═══════════════════════════════════════════════════════════════
# 风险阈值常量（医学标准，中继服务器可覆盖）
# ═══════════════════════════════════════════════════════════════
TEMP_WARNING_THRESHOLD = 39.0     # 高风险预警阈值
TEMP_NORMAL_WARNING = 38.0        # 普通预警阈值
ONLINE_TIMEOUT_SECONDS = 90       # 90秒内无上报 → 视为离线


def is_device_effectively_online(device):
    """判断设备是否实际在线：is_online=True 且最后上报在超时时间内"""
    if not device.is_online:
        return False
    if device.last_report_time is None:
        return False
    from django.utils import timezone
    delta = (timezone.now() - device.last_report_time).total_seconds()
    return delta <= ONLINE_TIMEOUT_SECONDS


def get_device_risk_level(device):
    """
    统一设备风险/状态分类 — 以中继服务器上报字段为准。
    所有 API 和页面统一调用此函数，不各自硬编码判断逻辑。

    返回: (risk_level: str, risk_text: str)
        risk_level: 'normal' | 'warning' | 'high_risk' | 'monitoring' | 'unavailable' | 'never_reported' | 'offline'
    """
    # 离线（含超时：5分钟无上报视为离线）
    if not is_device_effectively_online(device):
        return ('offline', '离线')

    # 从未上报过任何数据
    if device.last_report_time is None:
        return ('never_reported', '从未上报')

    latest = device.health_data.first()

    # 以中继上报的 dataQuality / worn 为准
    data_quality = (latest.data_quality or '') if latest else ''
    is_worn = device.worn if device.worn is not None else True

    if not is_worn or data_quality in ('not_worn', 'no_vitals'):
        return ('unavailable', '数据不可用')

    # 有数据上报但缺少核心温度
    if not latest or latest.core_temperature is None or latest.core_temperature == 0:
        return ('monitoring', '监测中')

    # 核心温度来自中继服务器，阈值兜底
    t = latest.core_temperature
    if t >= TEMP_WARNING_THRESHOLD:
        return ('high_risk', '高风险预警')
    if t >= TEMP_NORMAL_WARNING:
        return ('warning', '普通预警')
    return ('normal', '正常')


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


class Project(models.Model):
    """项目/任务"""
    STATUS_CHOICES = [
        ('recording', '数据录入中'),
        ('stopped', '停止录入'),
        ('archived', '已归档'),
    ]
    name = models.CharField('项目名称', max_length=200)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='recording')
    jurisdiction_geo = models.TextField('辖区范围GeoJSON', blank=True, help_text='辖区范围的GeoJSON多边形坐标')
    jurisdiction_color = models.CharField('辖区配色', max_length=20, default='#1890FF')
    description = models.TextField('项目简介', blank=True, help_text='项目的简要描述')
    jurisdiction_regions = models.ManyToManyField('Region', blank=True, verbose_name='辖区区域',
                                                   help_text='选择该项目管辖的行政区域')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'project'
        verbose_name = '项目'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.name} [{self.get_status_display()}]"


class Device(models.Model):
    """手表/设备（绑定民警）"""
    SHAPE_CHOICES = [
        ('circle', '圆形'),
        ('triangle', '三角形'),
        ('square', '方形'),
        ('diamond', '菱形'),
        ('pentagon', '五边形'),
        ('star', '星形'),
        ('hexagon', '六边形'),
        ('cross', '十字形'),
    ]
    BIND_STATUS_CHOICES = [
        ('pending', '待绑定'),
        ('active', '已激活'),
        ('disabled', '已禁用'),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='devices', verbose_name='所属项目')
    device_id = models.CharField('设备ID', max_length=100, unique=True)
    asset_code = models.CharField('资产编码', max_length=100, blank=True)
    officer_name = models.CharField('民警姓名', max_length=50)
    officer_age = models.IntegerField('年龄', default=25)
    officer_gender = models.CharField('性别', max_length=10, choices=[('男', '男'), ('女', '女')], default='男')
    marker_shape = models.CharField('图标形状', max_length=20, choices=SHAPE_CHOICES, default='circle')
    marker_color = models.CharField('图标颜色', max_length=20, default='#1890FF')
    is_online = models.BooleanField('在线状态', default=False)
    last_report_time = models.DateTimeField('最后上报时间', null=True, blank=True)
    latitude = models.FloatField('纬度', null=True, blank=True, help_text='NULL=中继未上报坐标')
    longitude = models.FloatField('经度', null=True, blank=True, help_text='NULL=中继未上报坐标')
    bind_status = models.CharField('绑定状态', max_length=20, choices=BIND_STATUS_CHOICES, default='active')
    hardware_serial = models.CharField('硬件序列号', max_length=200, blank=True, null=True, unique=True,
                                        help_text='手表硬件唯一标识，注册时由手表上报')
    battery_level = models.IntegerField('电量(%)', null=True, blank=True, help_text='手表电量百分比')
    worn = models.BooleanField('佩戴状态', default=True, help_text='手表是否佩戴在身上')
    firmware_version = models.CharField('固件版本', max_length=50, blank=True, help_text='手表固件版本号')
    mac_address = models.CharField('MAC地址', max_length=17, blank=True, null=True,
                                   help_text='手表WiFi/蓝牙MAC地址，格式: AA:BB:CC:DD:EE:FF')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        db_table = 'device'
        verbose_name = '设备'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.officer_name} ({self.device_id})"


class HealthData(models.Model):
    """实时健康数据"""
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='health_data', verbose_name='设备')
    heart_rate = models.IntegerField('心率(bpm)', null=True, blank=True, help_text='NULL=中继未上报')
    blood_oxygen = models.FloatField('血氧(%)', null=True, blank=True, help_text='NULL=中继未上报')
    blood_pressure_sys = models.IntegerField('收缩压(mmHg)', null=True, blank=True, help_text='NULL=中继未上报')
    blood_pressure_dia = models.IntegerField('舒张压(mmHg)', null=True, blank=True, help_text='NULL=中继未上报')
    step_frequency = models.IntegerField('步频(步/分)', null=True, blank=True, help_text='NULL=中继未上报')
    core_temperature = models.FloatField('核心温度(℃)', null=True, blank=True, help_text='NULL=中继未上报')
    core_temp_source = models.CharField('温度来源', max_length=50, blank=True,
                                        help_text='heart_rate_estimate / kalman_estimation / informer_model_1')
    steps = models.IntegerField('步数', null=True, blank=True)
    gps_accuracy = models.FloatField('GPS精度(m)', null=True, blank=True)
    data_quality = models.CharField('数据质量', max_length=30, blank=True, help_text='complete / partial / invalid')
    latitude = models.FloatField('纬度', null=True, blank=True, help_text='NULL=中继未上报')
    longitude = models.FloatField('经度', null=True, blank=True, help_text='NULL=中继未上报')
    timestamp = models.DateTimeField('上报时间', auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'health_data'
        verbose_name = '健康数据'
        verbose_name_plural = verbose_name
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.device.officer_name} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


class Alert(models.Model):
    """预警记录"""
    ALERT_TYPE_CHOICES = [
        ('normal', '普通预警'),
        ('high_risk', '高风险预警'),
    ]
    RISK_LEVEL_CHOICES = [
        ('normal', '正常'),
        ('warning', '普通预警'),
        ('high_risk', '高风险预警'),
    ]
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='alerts', verbose_name='设备')
    alert_type = models.CharField('预警类型', max_length=20, choices=ALERT_TYPE_CHOICES, default='normal')
    risk_level = models.CharField('风险等级', max_length=20, choices=RISK_LEVEL_CHOICES, default='normal')
    core_temperature = models.FloatField('核心温度(℃)')
    heart_rate = models.IntegerField('心率(bpm)', default=0)
    blood_oxygen = models.FloatField('血氧(%)', default=0)
    advice_text = models.TextField('健康处置预案', blank=True)
    is_read = models.BooleanField('已读', default=False)
    created_at = models.DateTimeField('预警时间', auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'alert'
        verbose_name = '预警记录'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_alert_type_display()}] {self.device.officer_name} - {self.created_at.strftime('%m-%d %H:%M')}"


class DeviceLocation(models.Model):
    """设备位置轨迹"""
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='locations', verbose_name='设备')
    latitude = models.FloatField('纬度')
    longitude = models.FloatField('经度')
    timestamp = models.DateTimeField('时间', auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'device_location'
        verbose_name = '位置轨迹'
        verbose_name_plural = verbose_name
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.device.officer_name} - ({self.latitude}, {self.longitude})"


class Region(models.Model):
    """行政区域 (省/市/县三级)"""
    LEVEL_CHOICES = [
        ('province', '省级'),
        ('prefecture', '地级'),
        ('county', '县级'),
    ]
    code = models.CharField('区划码', max_length=12, db_index=True,
                            help_text='行政区划代码')
    name = models.CharField('名称', max_length=100, db_index=True)
    level = models.CharField('层级', max_length=20, choices=LEVEL_CHOICES, db_index=True)
    parent_code = models.CharField('上级区划码', max_length=12, blank=True, db_index=True,
                                   help_text='上级区域的区划码')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='children', verbose_name='上级区域')
    geometry_geojson = models.TextField('简化几何GeoJSON', blank=True,
                                        help_text='简化的GeoJSON几何数据')
    center_lat = models.FloatField('中心纬度', null=True, blank=True)
    center_lng = models.FloatField('中心经度', null=True, blank=True)
    eng_name = models.CharField('英文名', max_length=200, blank=True, null=True)
    var_name = models.CharField('变体名', max_length=200, blank=True, null=True)
    year = models.CharField('年份', max_length=10, blank=True, default='2024')

    class Meta:
        db_table = 'region'
        verbose_name = '行政区域'
        verbose_name_plural = verbose_name
        ordering = ['code']
        unique_together = [['code', 'level']]
        indexes = [
            models.Index(fields=['level', 'parent_code']),
            models.Index(fields=['level', 'name']),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.name} ({self.code})"

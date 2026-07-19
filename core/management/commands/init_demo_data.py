"""初始化演示数据"""
import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Project, Device, HealthData, Alert, DeviceLocation


class Command(BaseCommand):
    help = '初始化演示数据'

    def handle(self, *args, **options):
        # 创建超级用户
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            self.stdout.write(self.style.SUCCESS('创建超级用户: admin / admin123'))

        # 创建演示项目
        project, _ = Project.objects.get_or_create(
            name='成都春熙路执勤',
            defaults={
                'status': 'recording',
                'jurisdiction_geo': '',
                'jurisdiction_color': '#1890FF',
            }
        )

        # 创建演示设备
        officers = [
            {'name': '赵建国', 'age': 35, 'gender': '男', 'shape': 'star', 'color': '#1890FF', 'lat': 30.6562, 'lng': 104.0825},
            {'name': '李明远', 'age': 28, 'gender': '男', 'shape': 'triangle', 'color': '#52c41a', 'lat': 30.6580, 'lng': 104.0780},
            {'name': '王芳', 'age': 26, 'gender': '女', 'shape': 'diamond', 'color': '#ff4d4f', 'lat': 30.6530, 'lng': 104.0855},
            {'name': '张伟', 'age': 42, 'gender': '男', 'shape': 'pentagon', 'color': '#faad14', 'lat': 30.6600, 'lng': 104.0800},
            {'name': '陈小红', 'age': 24, 'gender': '女', 'shape': 'hexagon', 'color': '#722ed1', 'lat': 30.6550, 'lng': 104.0765},
            {'name': '刘强', 'age': 31, 'gender': '男', 'shape': 'square', 'color': '#13c2c2', 'lat': 30.6515, 'lng': 104.0830},
            {'name': '周敏', 'age': 29, 'gender': '女', 'shape': 'cross', 'color': '#eb2f96', 'lat': 30.6575, 'lng': 104.0880},
            {'name': '吴磊', 'age': 38, 'gender': '男', 'shape': 'circle', 'color': '#f5222d', 'lat': 30.6595, 'lng': 104.0750},
        ]

        for i, officer in enumerate(officers):
            device, created = Device.objects.get_or_create(
                device_id=f'WATCH-{1000+i}',
                defaults={
                    'project': project,
                    'asset_code': f'ASSET-{2000+i}',
                    'officer_name': officer['name'],
                    'officer_age': officer['age'],
                    'officer_gender': officer['gender'],
                    'marker_shape': officer['shape'],
                    'marker_color': officer['color'],
                    'is_online': True,
                    'latitude': officer['lat'],
                    'longitude': officer['lng'],
                    'last_report_time': timezone.now(),
                }
            )
            if not created:
                # 更新已有设备
                for k, v in officer.items():
                    if hasattr(device, k):
                        setattr(device, k, v)
                device.is_online = True
                device.last_report_time = timezone.now()
                device.save()

            # 生成历史健康数据和轨迹
            for j in range(30):
                t = timezone.now() - timedelta(minutes=5 * j)
                lat_delta = random.uniform(-0.002, 0.002)
                lng_delta = random.uniform(-0.002, 0.002)
                lat = officer['lat'] + lat_delta
                lng = officer['lng'] + lng_delta

                # 随机生成温度趋势
                is_hot = (j < 3)  # 最近的几次温度偏高
                base_temp = 37.0 + random.uniform(-0.3, 1.0)
                if is_hot and officer['name'] in ['王芳', '张伟', '吴磊']:
                    base_temp += random.uniform(1.0, 2.5)

                heart_rate = random.randint(70, 150) if is_hot else random.randint(60, 90)

                HealthData.objects.get_or_create(
                    device=device,
                    timestamp=t,
                    defaults={
                        'heart_rate': heart_rate,
                        'blood_oxygen': round(random.uniform(94, 100), 1),
                        'blood_pressure_sys': random.randint(110, 150),
                        'blood_pressure_dia': random.randint(70, 95),
                        'step_frequency': random.randint(40, 160),
                        'core_temperature': round(base_temp, 1),
                        'latitude': round(lat, 6),
                        'longitude': round(lng, 6),
                    }
                )

                DeviceLocation.objects.get_or_create(
                    device=device,
                    timestamp=t,
                    defaults={
                        'latitude': round(lat, 6),
                        'longitude': round(lng, 6),
                    }
                )

            # 为部分设备创建预警记录
            if officer['name'] in ['王芳', '吴磊']:
                for j in range(2):
                    alert_t = timezone.now() - timedelta(minutes=15 * j)
                    Alert.objects.get_or_create(
                        device=device,
                        created_at=alert_t,
                        defaults={
                            'alert_type': 'high_risk' if officer['name'] == '王芳' else 'normal',
                            'risk_level': 'high_risk' if officer['name'] == '王芳' else 'warning',
                            'core_temperature': round(39.2 + random.uniform(-0.3, 0.5), 1),
                            'heart_rate': random.randint(110, 155),
                            'blood_oxygen': round(random.uniform(93, 97), 1),
                            'advice_text': '1. 立即停止当前活动，转移至阴凉通风处休息\n2. 补充电解质饮料，如症状持续及时就医',
                        }
                    )

            # 更新设备最后位置为最新HealthData的位置
            latest = device.health_data.first()
            if latest:
                device.latitude = latest.latitude
                device.longitude = latest.longitude
                device.save()

        self.stdout.write(self.style.SUCCESS(f'初始化完成: 项目={project.name}, 设备={Device.objects.count()}, '
                                              f'健康数据={HealthData.objects.count()}, 预警={Alert.objects.count()}'))

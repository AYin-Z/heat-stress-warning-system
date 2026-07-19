"""导入行政区划 Shapefile 数据

DBF字段名是UTF-8, 字段值是GBK → 手动读DBF取中文名
几何从geopandas读取
"""
import json
import math
import os
import struct
import time

from django.core.management.base import BaseCommand
from django.conf import settings
from shapely.geometry import mapping


def safe_str(val):
    if val is None:
        return ''
    if isinstance(val, float) and math.isnan(val):
        return ''
    return str(val)


def safe_float(val):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return round(float(val), 6)


def read_dbf_chinese_names(shp_path):
    """手动读DBF: 字段名=UTF-8, 字段值=GBK
    返回 dict: GID_3 -> {county_cn, pref_cn, prov_cn, county_code, pref_cn_code, prov_cn_code}
    """
    dbf_path = shp_path.replace('.shp', '.dbf')
    with open(dbf_path, 'rb') as f:
        header = f.read(32)
        header_bytes = struct.unpack('<H', header[8:10])[0]
        record_bytes = struct.unpack('<H', header[10:12])[0]
        num_fields = (header_bytes - 33) // 32

        # 读取字段定义（UTF-8字段名）
        fields = []
        for i in range(num_fields):
            fd = f.read(32)
            name = fd[:11].split(b'\0')[0].decode('utf-8')
            flen = fd[16]
            fields.append((name, flen))

        # 读取所有记录
        result = {}
        for rec_idx in range(struct.unpack('<I', header[4:8])[0]):
            f.seek(header_bytes + rec_idx * record_bytes + 1)  # +1 skip delete flag
            vals = {}
            for name, flen in fields:
                raw = f.read(flen)
                clean = raw.split(b'\0')[0]
                vals[name] = clean.decode('utf-8', errors='ignore').strip()

            gid3 = vals.get('GID_3', '')
            if gid3 and gid3 != '0':
                result[gid3] = {
                    'county_cn': vals.get('县级', vals.get('NAME_3', '')),
                    'pref_cn': vals.get('地级', vals.get('NAME_2', '')),
                    'prov_cn': vals.get('省级', vals.get('NAME_1', '')),
                    'county_code': vals.get('县级码', vals.get('GID_3', '')),
                    'pref_code': vals.get('地级码', vals.get('GID_2', '')),
                    'prov_code': vals.get('省级码', vals.get('GID_1', '')),
                }
            # 直筒子市: GID_3='0'但地级/省级名存在，单独记录中文名
            pref_code = vals.get('地级码', vals.get('GID_2', ''))
            if gid3 == '0' and pref_code and pref_code != '0':
                key = f'_pref_{pref_code}'
                if key not in result:
                    result[key] = {
                        'pref_cn': vals.get('地级', vals.get('NAME_2', '')),
                        'prov_cn': vals.get('省级', vals.get('NAME_1', '')),
                        'pref_code': pref_code,
                        'prov_code': vals.get('省级码', vals.get('GID_1', '')),
                    }
        return result


class Command(BaseCommand):
    help = '从 Shapefile 导入省/市/县三级行政区划数据'

    def add_arguments(self, parser):
        parser.add_argument('--path', type=str, default=None,
                            help='Shapefile 路径')
        parser.add_argument('--clear', action='store_true', default=False,
                            help='导入前清空现有区域数据')
        parser.add_argument('--no-simplify', action='store_true', default=False,
                            help='不简化几何')

    def handle(self, *args, **options):
        start_time = time.time()

        try:
            import geopandas as gpd
        except ImportError:
            self.stderr.write(self.style.ERROR('需要安装 geopandas: pip install geopandas'))
            return

        shp_path = options['path']
        if not shp_path:
            shp_path = os.path.join(settings.BASE_DIR, 'data', 'gis', 'T2024年初县级.shp')

        if not os.path.exists(shp_path):
            self.stderr.write(self.style.ERROR(f'文件不存在: {shp_path}'))
            return

        self.stdout.write(f'正在读取: {shp_path}')

        # ── 1. 从DBF读取正确的中文名 ──
        cn_names = read_dbf_chinese_names(shp_path)
        self.stdout.write(f'DBF中文名: {len(cn_names)} 条')

        # ── 2. 从geopandas读取几何 ──
        gdf = gpd.read_file(shp_path, encoding='gbk')
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # 简化容差（0=不简化，保留原始精度）
        if options['no_simplify']:
            tol_prov = tol_pref = tol_county = 0
        else:
            tol_prov = 0.005    # ~550m
            tol_pref = 0.002    # ~220m
            tol_county = 0      # 县级不简化，保留原始精度

        from core.models import Region

        # ── 清理旧数据 ──
        existing = Region.objects.count()
        if existing > 0:
            if options['clear']:
                Region.objects.all().delete()
                self.stdout.write(f'已清除 {existing} 条旧数据')
            else:
                self.stderr.write(self.style.ERROR(
                    f'数据库中已有 {existing} 条区域数据。请使用 --clear 参数清空后重新导入。'
                ))
                return

        # ── 3. 提取省级 ──
        self.stdout.write('\n--- 处理省级 ---')
        provinces = {}
        seen_prov = set()
        for _, row in gdf.iterrows():
            gid1 = str(row['GID_1'])
            if gid1 in seen_prov or gid1 == '0':
                continue
            seen_prov.add(gid1)
            # 取该省的中文名（从第一个匹配的cn_names记录）
            prov_cn = ''
            for gid3, info in cn_names.items():
                if info['prov_code'] == gid1:
                    prov_cn = info['prov_cn']
                    break
            if not prov_cn:
                prov_cn = safe_str(row['NAME_1'])
            provinces[gid1] = prov_cn

        # 创建省级Region
        province_objs = []
        for code, name in provinces.items():
            province_objs.append(Region(
                code=code, name=name, level='province',
                parent_code='', geometry_geojson='',
                eng_name='', var_name='', year='2024',
            ))
        Region.objects.bulk_create(province_objs, batch_size=500)
        self.stdout.write(f'  省级: {len(province_objs)} 条')

        # ── 4. 提取地级 ──
        self.stdout.write('--- 处理地级 ---')
        prefectures = {}
        seen_pref = set()

        for gid_2, group in gdf.groupby('GID_2'):
            code = str(gid_2)
            if code == '0':
                # 直辖市/省直辖县: 为每个GID_1创建合成地级
                for gid_1, sub in group.groupby('GID_1'):
                    gid1_str = str(gid_1)
                    if gid1_str in seen_pref:
                        continue
                    seen_pref.add(gid1_str)
                    name = provinces.get(gid1_str, '')
                    if not name:
                        name = safe_str(sub.iloc[0]['NAME_1'])
                    prefectures[gid1_str] = {'name': name, 'parent_code': gid1_str}
                continue

            if code in seen_pref:
                continue
            seen_pref.add(code)
            row = group.iloc[0]
            # 从cn_names获取中文名
            pref_cn = cn_names.get(f'_pref_{code}', {}).get('pref_cn', '')
            if not pref_cn:
                for gid3, info in cn_names.items():
                    if info.get('pref_code') == code:
                        pref_cn = info['pref_cn']
                        break
            if not pref_cn:
                pref_cn = safe_str(row['NAME_2'])
            prefectures[code] = {
                'name': pref_cn,
                'parent_code': safe_str(row['GID_1']),
            }

        pref_objs = []
        for code, info in prefectures.items():
            pref_objs.append(Region(
                code=code, name=info['name'], level='prefecture',
                parent_code=info['parent_code'], geometry_geojson='',
                eng_name='', var_name='', year='2024',
            ))
        Region.objects.bulk_create(pref_objs, batch_size=500)
        self.stdout.write(f'  地级: {len(pref_objs)} 条')

        # ── 5. 提取县级（几何+中文名） ──
        self.stdout.write('--- 处理县级 ---')
        county_objs = []
        seen_county = set()

        for gid_3, group in gdf.groupby('GID_3'):
            code = str(gid_3)
            if code in seen_county or code == '0':
                continue
            seen_county.add(code)

            row = group.iloc[0]
            geom = row.geometry
            if tol_county > 0:
                geom = geom.simplify(tol_county, preserve_topology=True)
            centroid = geom.centroid

            # 中文名
            info = cn_names.get(code, {})
            name = info.get('county_cn', safe_str(row['NAME_3']))
            pref_cn = info.get('pref_cn', '')
            prov_cn = info.get('prov_cn', '')

            # parent_code
            pid = safe_str(row['GID_2'])
            if pid == '0':
                pid = safe_str(row['GID_1'])

            county_objs.append(Region(
                code=code,
                name=name,
                level='county',
                parent_code=pid,
                geometry_geojson=json.dumps(mapping(geom), ensure_ascii=False),
                center_lat=safe_float(centroid.y),
                center_lng=safe_float(centroid.x),
                eng_name=safe_str(row.get('NAME_3', '')),
                var_name=safe_str(row.get('VAR_NAME3', '')),
                year=safe_str(row.get('year', '2024')),
            ))

        Region.objects.bulk_create(county_objs, batch_size=500)
        self.stdout.write(f'  县级: {len(county_objs)} 条')

        # ── 6. 直筒子市: 为无区县的prefecture创建合成区县 ──
        self.stdout.write('--- 处理直筒子市 ---')
        syn_counties = []
        for pref_code, pref_info in prefectures.items():
            if not Region.objects.filter(parent_code=pref_code, level='county').exists():
                # 取该地级市的几何
                matched = gdf[gdf['GID_2'].astype(str) == pref_code]
                if matched.empty:
                    matched = gdf[gdf['GID_1'].astype(str) == pref_code]
                geom = None
                centroid = None
                if not matched.empty:
                    geom = matched.dissolve().geometry.iloc[0]
                    if tol_county > 0:
                        geom = geom.simplify(tol_county, preserve_topology=True)
                    centroid = geom.centroid
                syn_counties.append(Region(
                    code=pref_code,
                    name=pref_info['name'],
                    level='county',
                    parent_code=pref_code,
                    geometry_geojson=json.dumps(mapping(geom), ensure_ascii=False) if geom else '',
                    center_lat=safe_float(centroid.y) if centroid else None,
                    center_lng=safe_float(centroid.x) if centroid else None,
                    eng_name='',
                    var_name='',
                    year='2024',
                ))
                self.stdout.write(f'  合成区县: {pref_code} {pref_info["name"]}')
        if syn_counties:
            Region.objects.bulk_create(syn_counties, batch_size=500)
        self.stdout.write(f'  县级总计: {Region.objects.filter(level="county").count()} 条 (含{syn_counties}个合成)')

        # ── 7. 为有几何的省级生成几何（union该省所有县级） ──
        # 跳过以加速，省级几何不重要

        # ── 7. 回填 parent FK ──
        self.stdout.write('\n--- 回填 parent FK ---')
        code_to_id = dict(Region.objects.values_list('code', 'id'))
        updated = 0
        for region in Region.objects.exclude(parent_code='').iterator(chunk_size=500):
            pid = code_to_id.get(region.parent_code)
            if pid and region.parent_id != pid:
                region.parent_id = pid
                region.save(update_fields=['parent'])
                updated += 1
        self.stdout.write(f'  已回填: {updated} 条')

        # ── 8. 统计 ──
        total = Region.objects.count()
        elapsed = time.time() - start_time
        self.stdout.write(self.style.SUCCESS(
            f'\n导入完成! 共 {total} 条 ({elapsed:.1f}秒)\n'
            f'  省级: {Region.objects.filter(level="province").count()}\n'
            f'  地级: {Region.objects.filter(level="prefecture").count()}\n'
            f'  县级: {Region.objects.filter(level="county").count()}'
        ))

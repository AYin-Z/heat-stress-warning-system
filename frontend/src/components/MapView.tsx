/**
 * 地图核心组件 — 高德地图
 * 显示所有在线民警位置，不同风险等级用不同颜色标记
 */
import { useEffect, useRef, useState } from 'react';
import { Spin } from 'antd';
import AMapLoader from '@amap/amap-jsapi-loader';
import { useAppState } from '../store';
import { RiskLevel } from '../types';

// ============================================================
// 颜色/图标配置
// ============================================================

const RISK_COLORS: Record<string, string> = {
  [RiskLevel.Normal]: '#52c41a',
  [RiskLevel.Warning]: '#fa8c16',
  [RiskLevel.HighRisk]: '#ff4d4f',
  [RiskLevel.Unavailable]: '#5c7c8a',
  [RiskLevel.Offline]: '#8c8c8c',
};

// 不同设备用不同形状 (AMap Marker content)
const SHAPES = ['●', '▲', '■', '◆', '⬟', '★'];
let shapeIndex = 0;
const deviceShapeMap: Record<string, string> = {};
function getShape(deviceId: string): string {
  if (!deviceShapeMap[deviceId]) {
    deviceShapeMap[deviceId] = SHAPES[shapeIndex % SHAPES.length];
    shapeIndex++;
  }
  return deviceShapeMap[deviceId];
}

// ============================================================
// 占位：高德 API Key — 需要用户提供
// ============================================================

const AMAP_KEY = import.meta.env.VITE_AMAP_KEY || '';
const AMAP_VERSION = '2.0';

// ============================================================
// Component
// ============================================================

export default function MapView() {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstance = useRef<any>(null);
  const markersRef = useRef<Map<string, any>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { state, dispatch } = useAppState();

  // ============================================================
  // 初始化地图
  // ============================================================

  useEffect(() => {
    let cancelled = false;

    if (!AMAP_KEY) {
      setError('地图服务未配置');
      setLoading(false);
      return;
    }

    AMapLoader.load({
      key: AMAP_KEY,
      version: AMAP_VERSION,
      plugins: ['AMap.ToolBar', 'AMap.Scale'],
    })
      .then((AMap: any) => {
        if (cancelled || !mapRef.current) return;

        const map = new AMap.Map(mapRef.current, {
          zoom: 14,
          center: [116.397428, 39.90923], // 默认北京中心，实际应动态设置
          mapStyle: 'amap://styles/darkblue', // 深色主题适配大屏
          features: ['bg', 'road', 'building', 'point'],
        });

        map.addControl(new AMap.ToolBar({ position: 'LT' }));
        map.addControl(new AMap.Scale({ position: 'LB' }));

        mapInstance.current = map;
        setLoading(false);
      })
      .catch((err: Error) => {
        console.warn('[Map] Load failed:', err);
        setError(err.message);
        setLoading(false);
      });

    return () => {
      cancelled = true;
      mapInstance.current?.destroy();
    };
  }, []);

  // ============================================================
  // 更新地图标记
  // ============================================================

  useEffect(() => {
    const map = mapInstance.current;
    if (!map) return;

    const currentMarkers = markersRef.current;
    const activeIds = new Set(Object.keys(state.devices));

    // 移除离线设备标记
    currentMarkers.forEach((marker, deviceId) => {
      if (!activeIds.has(deviceId)) {
        map.remove(marker);
        currentMarkers.delete(deviceId);
      }
    });

    // 更新/新增标记
    Object.values(state.devices).forEach((device) => {
      if (device.latitude == null || device.longitude == null) return;
      const deviceId = device.deviceId;
      const riskLevel = device.riskLevel || RiskLevel.Unavailable;
      const color = RISK_COLORS[riskLevel];
      const name = state.officers[deviceId]?.name || deviceId;
      const safeName = escapeHtml(name);
      const shape = getShape(deviceId);

      // 标记内容：风险 icon + 姓名
      const content = `
        <div style="
          text-align: center;
          cursor: pointer;
          filter: drop-shadow(0 2px 4px rgba(0,0,0,0.5));
        ">
          <div style="
            font-size: 20px;
            color: ${color};
            text-shadow: 0 0 8px ${color}80;
          ">${shape}</div>
          <div style="
            background: rgba(0,0,0,0.75);
            color: ${color};
            font-size: 11px;
            font-weight: 600;
            padding: 1px 6px;
            border-radius: 2px;
            white-space: nowrap;
            border: 1px solid ${color}40;
          ">${safeName}</div>
        </div>
      `;

      const position = [device.longitude, device.latitude];
      const markerData = { device, name: safeName, color };

      if (currentMarkers.has(deviceId)) {
        const marker = currentMarkers.get(deviceId);
        marker?.setPosition(position);
        marker?.setContent(content);
        marker?.setExtData(markerData);
      } else {
        // 创建新标记
        const marker = new (window as any).AMap.Marker({
          position,
          content,
          offset: new (window as any).AMap.Pixel(0, -20),
          zIndex: 100,
          extData: markerData,
        });

        // 点击事件 → 打开详情
        marker.on('click', () => {
          dispatch({ type: 'SELECT_DEVICE', deviceId });
        });

        // hover 显示简要信息
        marker.on('mouseover', () => {
          const latest = marker.getExtData();
          marker.setLabel({
            content: `<div style="
              background: rgba(13,27,42,0.95);
              color: #e0e8f0;
              padding: 4px 8px;
              border-radius: 4px;
              font-size: 12px;
              border: 1px solid ${latest.color}60;
            ">
              <b>${latest.name}</b><br/>
              心率 ${latest.device.heartRate ?? '--'} bpm | 血氧 ${latest.device.spo2 ?? '--'}%<br/>
              核心温度 ${latest.device.coreTemp?.toFixed(1) || '--'}℃
            </div>`,
            offset: new (window as any).AMap.Pixel(0, -60),
          });
        });

        marker.on('mouseout', () => {
          marker.setLabel(null);
        });

        map.add(marker);
        currentMarkers.set(deviceId, marker);
      }
    });
  }, [state.devices, state.officers, dispatch]);

  // ============================================================
  // Loading / Error
  // ============================================================

  if (loading) {
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a1628',
      }}>
        <Spin description="加载地图中..." size="large">
          <div style={{ padding: 50 }} />
        </Spin>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#0a1628',
        color: '#ff4d4f',
        flexDirection: 'column',
        gap: 8,
      }}>
        <div>{error || '地图不可用'}</div>
      </div>
    );
  }

  return (
    <div
      ref={mapRef}
      style={{
        flex: 1,
        width: '100%',
        height: '100%',
        background: '#0a1628',
      }}
    />
  );
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character] || character);
}

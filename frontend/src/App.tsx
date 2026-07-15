/**
 * 主应用 — 大屏单页全屏布局
 *
 * 布局：
 * ┌──────────────────────────────────────────┐
 * │ TopStatusBar (48px)                       │
 * ├────────────────────────────┬─────────────┤
 * │                            │ [饼图 200px] │
 * │                            ├─────────────┤
 * │       MapView              │             │
 * │                            │ AlertSidebar│
 * │                            │  (可折叠)    │
 * │                            │             │
 * └────────────────────────────┴─────────────┘
 */

import { lazy, Suspense, useEffect } from 'react';
import { ConfigProvider, theme } from 'antd';
import { AppProvider, useAppState } from './store';
import { mqttService } from './services/mqtt';
import TopStatusBar from './components/TopStatusBar';
import AlertSidebar from './components/AlertSidebar';
import AlertPopup from './components/AlertPopup';
import type { VitalData, AlertPopupData, AlertRecord } from './types';

const MapView = lazy(() => import('./components/MapView'));
const RiskPieChart = lazy(() => import('./components/RiskPieChart'));
const OfficerDetail = lazy(() => import('./components/OfficerDetail'));

function AppInner() {
  const { dispatch } = useAppState();

  // ============================================================
  // 初始化 MQTT 连接 + 数据订阅
  // ============================================================

  useEffect(() => {
    const cleanup: (() => void)[] = [];

    // 连接 EMQX
    mqttService.connect(`pc-dashboard-${Date.now()}`);

    // 订阅生理数据
    cleanup.push(
      mqttService.onVital((data: VitalData) => {
        dispatch({ type: 'VITAL_DATA', payload: data });
      })
    );

    // 订阅预警弹窗
    cleanup.push(
      mqttService.onAlert((data: AlertPopupData) => {
        dispatch({ type: 'ALERT', payload: data });
      })
    );

    // 订阅预警记录
    cleanup.push(
      mqttService.onAlertRecord((record: AlertRecord) => {
        dispatch({ type: 'ALERT_RECORD', payload: record });
      })
    );

    // 订阅设备上下线
    cleanup.push(
      mqttService.onStatus((deviceId: string, online: boolean) => {
        dispatch({
          type: online ? 'DEVICE_ONLINE' : 'DEVICE_OFFLINE',
          deviceId,
        });
      })
    );

    return () => {
      cleanup.forEach((fn) => fn());
      mqttService.disconnect();
    };
  }, [dispatch]);

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 顶部状态栏 */}
      <TopStatusBar />

      {/* 主体：地图 + 右侧面板 */}
      <div style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
        <Suspense fallback={null}>
          {/* 地图 */}
          <MapView />

          {/* 右上角饼图 */}
          <RiskPieChart />

          {/* 民警详情弹窗 */}
          <OfficerDetail />
        </Suspense>

        {/* 右侧预警历史 */}
        <AlertSidebar />

        {/* 预警弹窗 */}
        <AlertPopup />

      </div>
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 4,
          colorBgContainer: '#0d1b2a',
          colorBgElevated: '#0d1b2a',
        },
      }}
    >
      <AppProvider>
        <AppInner />
      </AppProvider>
    </ConfigProvider>
  );
}

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

import { useEffect } from 'react';
import { ConfigProvider, theme } from 'antd';
import { AppProvider, useAppState } from './store';
import { mqttService } from './services/mqtt';
import TopStatusBar from './components/TopStatusBar';
import RiskPieChart from './components/RiskPieChart';
import AlertSidebar from './components/AlertSidebar';
import AlertPopup from './components/AlertPopup';
import OfficerDetail from './components/OfficerDetail';
import MapView from './components/MapView';
import type { VitalData, AlertPopupData, AlertRecord } from './types';

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

  // ============================================================
  // 模拟注册一些测试人员（开发用，实际从后端加载）
  // ============================================================

  useEffect(() => {
    // TODO: 从后端 API 加载人员列表
    dispatch({
      type: 'REGISTER_OFFICER',
      payload: { deviceId: 'A80-001', name: '赵建国', policeId: 'P2021001', age: 35, gender: '男' },
    });
    dispatch({
      type: 'REGISTER_OFFICER',
      payload: { deviceId: 'A80-002', name: '李明', policeId: 'P2021002', age: 28, gender: '男' },
    });
    dispatch({
      type: 'REGISTER_OFFICER',
      payload: { deviceId: 'A80-003', name: '王芳', policeId: 'P2021003', age: 31, gender: '女' },
    });
  }, [dispatch]);

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 顶部状态栏 */}
      <TopStatusBar />

      {/* 主体：地图 + 右侧面板 */}
      <div style={{ flex: 1, display: 'flex', position: 'relative', overflow: 'hidden' }}>
        {/* 地图 */}
        <MapView />

        {/* 右上角饼图 */}
        <RiskPieChart />

        {/* 右侧预警历史 */}
        <AlertSidebar />

        {/* 预警弹窗 */}
        <AlertPopup />

        {/* 民警详情弹窗 */}
        <OfficerDetail />
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

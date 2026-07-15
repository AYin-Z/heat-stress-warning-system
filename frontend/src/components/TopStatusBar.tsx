/**
 * 顶部状态栏 — 在线/离线手表统计
 */
import { useAppState } from '../store';
import { Badge, Space, Typography, Tag } from 'antd';
import { WifiOutlined, DisconnectOutlined, WarningOutlined } from '@ant-design/icons';

const { Text } = Typography;

export default function TopStatusBar() {
  const { state } = useAppState();
  const online = state.onlineDevices.size;
  const knownDevices = new Set([
    ...Object.keys(state.officers),
    ...Object.keys(state.devices),
    ...state.onlineDevices,
  ]);
  const offline = Math.max(0, knownDevices.size - online);

  const totalAlerts = state.alertRecords.length;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 24px',
        background: 'linear-gradient(135deg, #001529 0%, #002140 100%)',
        color: '#fff',
        height: 48,
        boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        zIndex: 100,
      }}
    >
      {/* 左侧：系统名称 */}
      <Text strong style={{ color: '#fff', fontSize: 16, letterSpacing: 2 }}>
        热应激预警系统
      </Text>

      {/* 右侧：统计 */}
      <Space size="large">
        <Space>
          <Badge status="processing" color="#52c41a" />
          <Text style={{ color: '#52c41a', fontWeight: 500 }}>
            <WifiOutlined style={{ marginRight: 4 }} />
            在线 {online}
          </Text>
        </Space>
        <Space>
          <Badge status="default" color="#8c8c8c" />
          <Text style={{ color: '#8c8c8c', fontWeight: 500 }}>
            <DisconnectOutlined style={{ marginRight: 4 }} />
            离线 {offline}
          </Text>
        </Space>
        {totalAlerts > 0 && (
          <Tag color="error" icon={<WarningOutlined />}>
            今日预警 {totalAlerts}
          </Tag>
        )}
        <Text style={{ color: '#ffffff73', fontSize: 12 }}>
          MQTT: ws://39.105.86.77:8083/mqtt
        </Text>
      </Space>
    </div>
  );
}

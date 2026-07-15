/**
 * 二级详情弹窗 — 点击地图民警标记后显示
 * 展示实时生理数据（心率/血氧/血压/步频/核心温度/位置）
 */
import { Modal, Descriptions, Typography, Space, Tag } from 'antd';
import { HeartOutlined, DashboardOutlined, EnvironmentOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useAppState } from '../store';
import { RiskLevel } from '../types';

const { Text } = Typography;

export default function OfficerDetail() {
  const { state, dispatch } = useAppState();
  const { selectedDeviceId, devices, officers } = state;

  if (!selectedDeviceId) return null;

  const device = devices[selectedDeviceId];
  const officer = officers[selectedDeviceId];

  if (!device) return null;

  const riskColors: Record<string, string> = {
    [RiskLevel.Normal]: '#52c41a',
    [RiskLevel.Warning]: '#fa8c16',
    [RiskLevel.HighRisk]: '#ff4d4f',
    [RiskLevel.Offline]: '#8c8c8c',
  };

  const riskLabels: Record<string, string> = {
    [RiskLevel.Normal]: '正常',
    [RiskLevel.Warning]: '⚠ 普通预警',
    [RiskLevel.HighRisk]: '🚨 高风险预警',
    [RiskLevel.Offline]: '离线',
  };

  const riskColor = riskColors[device.riskLevel || RiskLevel.Normal];

  return (
    <Modal
      open={true}
      onCancel={() => dispatch({ type: 'SELECT_DEVICE', deviceId: null })}
      footer={null}
      width={480}
      title={
        <Space>
          <EnvironmentOutlined style={{ color: riskColor }} />
          <Text strong style={{ fontSize: 16 }}>
            {officer?.name || device.deviceId}
          </Text>
          <Tag
            color={
              device.riskLevel === RiskLevel.HighRisk
                ? 'error'
                : device.riskLevel === RiskLevel.Warning
                  ? 'warning'
                  : 'success'
            }
          >
            {riskLabels[device.riskLevel || RiskLevel.Normal]}
          </Tag>
        </Space>
      }
      styles={{
        body: { background: '#0d1b2a', maxHeight: '60vh', overflow: 'auto' },
        header: { background: '#0d1b2a', borderBottom: '1px solid #1a2d42' },
      }}
    >
      {/* 基本信息 */}
      <Descriptions
        column={2}
        size="small"
        colon={false}
        styles={{ label: { color: '#8c9bb0', fontSize: 12 }, content: { color: '#e0e8f0', fontSize: 13 } }}
      >
        <Descriptions.Item label="设备ID">{device.deviceId}</Descriptions.Item>
        <Descriptions.Item label="姓名">{officer?.name || '-'}</Descriptions.Item>
        {officer?.policeId && <Descriptions.Item label="警号">{officer.policeId}</Descriptions.Item>}
        {officer?.age && <Descriptions.Item label="年龄">{officer.age}岁</Descriptions.Item>}
        {officer?.gender && <Descriptions.Item label="性别">{officer.gender}</Descriptions.Item>}
      </Descriptions>

      <div style={{ margin: '12px 0', borderTop: '1px solid #1a2d42' }} />

      {/* 生理数据 */}
      <Text strong style={{ color: '#8c9bb0', fontSize: 12, display: 'block', marginBottom: 8 }}>
        <HeartOutlined /> 实时生理数据
      </Text>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <DataCard
          label="心率"
          value={device.heartRate ?? '--'}
          unit="bpm"
          icon={<HeartOutlined />}
          color={device.heartRate != null && device.heartRate > 120 ? '#ff4d4f' : '#52c41a'}
        />
        <DataCard
          label="血氧"
          value={device.spo2 ?? '--'}
          unit="%"
          icon={<DashboardOutlined />}
          color={device.spo2 != null && device.spo2 < 95 ? '#fa8c16' : '#52c41a'}
        />
        <DataCard
          label="血压"
          value={device.bloodPressure ?? '--/--'}
          unit="mmHg"
          color="#40a9ff"
        />
        <DataCard
          label="步频"
          value={device.stepRate?.toFixed(0) || '-'}
          unit="步/分"
          color="#9254de"
        />
      </div>

      <div style={{ margin: '12px 0', borderTop: '1px solid #1a2d42' }} />

      {/* 核心温度 — 高亮 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 12,
          background: `${riskColor}15`,
          borderRadius: 8,
          border: `1px solid ${riskColor}40`,
        }}
      >
        <Space>
          <ThunderboltOutlined style={{ color: riskColor, fontSize: 22 }} />
          <Text style={{ color: '#8c9bb0' }}>核心温度</Text>
        </Space>
        <Text
          strong
          style={{ color: riskColor, fontSize: 28 }}
        >
          {device.coreTemp != null ? device.coreTemp.toFixed(1) : '--'}℃
        </Text>
      </div>

      {/* 位置 */}
      <div style={{ marginTop: 12 }}>
        <Text style={{ color: '#8c9bb0', fontSize: 12 }}>
          <EnvironmentOutlined /> 位置: {device.locationName || (
            device.latitude != null && device.longitude != null
              ? `${device.latitude.toFixed(4)}, ${device.longitude.toFixed(4)}`
              : '暂无有效定位'
          )}
        </Text>
      </div>

      {/* AI 建议 */}
      {device.advice && (
        <div
          style={{
            marginTop: 12,
            padding: 8,
            background: 'rgba(64, 169, 255, 0.08)',
            borderRadius: 4,
            borderLeft: '3px solid #40a9ff',
          }}
        >
          <Text style={{ color: '#8c9bb0', fontSize: 11 }}>AI 处置建议：</Text>
          <Text style={{ color: '#e0e8f0', fontSize: 12, display: 'block', marginTop: 4 }}>
            {device.advice}
          </Text>
        </div>
      )}
    </Modal>
  );
}

/** 数据卡片小组件 */
function DataCard({
  label,
  value,
  unit,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  unit: string;
  icon?: React.ReactNode;
  color: string;
}) {
  return (
    <div
      style={{
        padding: 10,
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 6,
        border: '1px solid #1a2d42',
      }}
    >
      <Text style={{ color: '#8c9bb0', fontSize: 11 }}>{label}</Text>
      <div style={{ display: 'flex', alignItems: 'baseline', marginTop: 4 }}>
        {icon && <span style={{ color, marginRight: 4 }}>{icon}</span>}
        <Text strong style={{ color, fontSize: 20 }}>
          {value}
        </Text>
        <Text style={{ color: '#8c9bb0', fontSize: 12, marginLeft: 4 }}>{unit}</Text>
      </div>
    </div>
  );
}

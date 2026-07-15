/**
 * 预警弹窗 — 右下角/中央弹出
 */
import { useEffect } from 'react';
import { Modal, Typography, Descriptions, Space } from 'antd';
import { WarningOutlined, AlertOutlined } from '@ant-design/icons';
import { useAppState } from '../store';
import { AlertType } from '../types';

const { Text } = Typography;

export default function AlertPopup() {
  const { state, dispatch, getOfficerName } = useAppState();
  const alert = state.activeAlert;

  useEffect(() => {
    if (alert) {
      // 30 秒自动消失
      const timer = setTimeout(() => {
        dispatch({ type: 'DISMISS_ALERT' });
      }, 30000);
      return () => clearTimeout(timer);
    }
  }, [alert, dispatch]);

  if (!alert) return null;

  const isHighRisk = alert.alertType === AlertType.HighRisk;

  return (
    <Modal
      open={true}
      onCancel={() => dispatch({ type: 'DISMISS_ALERT' })}
      footer={null}
      width={400}
      centered
      closable
      mask={false}
      style={{ position: 'fixed', right: 340, bottom: 40 }}
      styles={{
        body: {
          background: isHighRisk
            ? 'linear-gradient(135deg, #2a1215 0%, #1a0a0a 100%)'
            : 'linear-gradient(135deg, #2a1f12 0%, #1a1208 100%)',
          borderRadius: 8,
        },
        header: {
          background: isHighRisk ? '#2a1215' : '#2a1f12',
          borderBottom: isHighRisk ? '1px solid #5c1a1a' : '1px solid #5c3a1a',
        },
      }}
      title={
        <Space>
          {isHighRisk ? (
            <WarningOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
          ) : (
            <AlertOutlined style={{ color: '#fa8c16', fontSize: 20 }} />
          )}
          <Text strong style={{ color: isHighRisk ? '#ff4d4f' : '#fa8c16', fontSize: 16 }}>
            {alert.alertType}
          </Text>
        </Space>
      }
    >
      <Descriptions column={1} size="small" colon={false} styles={{ label: { color: '#8c9bb0' }, content: { color: '#e0e8f0' } }}>
        <Descriptions.Item label="民警">
          {getOfficerName(alert.deviceId)} ({alert.deviceId})
        </Descriptions.Item>
        <Descriptions.Item label="核心温度">
          <Text
            strong
            style={{
              color: isHighRisk ? '#ff4d4f' : '#fa8c16',
              fontSize: 24,
            }}
          >
            {alert.coreTemp != null ? `${alert.coreTemp.toFixed(1)}℃` : '--'}
          </Text>
        </Descriptions.Item>
      </Descriptions>

      <div
        style={{
          marginTop: 12,
          padding: 8,
          background: 'rgba(255,255,255,0.05)',
          borderRadius: 4,
          borderLeft: `3px solid ${isHighRisk ? '#ff4d4f' : '#fa8c16'}`,
        }}
      >
        <Text style={{ color: '#8c9bb0', fontSize: 11 }}>处置建议：</Text>
        <Text style={{ color: '#e0e8f0', fontSize: 12, display: 'block', marginTop: 4 }}>
          {alert.advice || '请立即停止当前活动，转移至阴凉处休息并补充水分。'}
        </Text>
      </div>
    </Modal>
  );
}

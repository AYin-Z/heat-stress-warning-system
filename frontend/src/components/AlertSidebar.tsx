/**
 * 右侧预警历史侧边栏 — 可折叠
 */
import { useState } from 'react';
import { Tag, Typography, Button, Tooltip, Popconfirm, Badge, Space } from 'antd';
import {
  DoubleRightOutlined,
  DoubleLeftOutlined,
  DeleteOutlined,
  WarningOutlined,
  AlertOutlined,
} from '@ant-design/icons';
import { useAppState } from '../store';
import { AlertType } from '../types';
import dayjs from 'dayjs';

const { Text } = Typography;

const SIDEBAR_WIDTH = 320;
const COLLAPSED_WIDTH = 40;

export default function AlertSidebar() {
  const { state, dispatch } = useAppState();
  const [collapsed, setCollapsed] = useState(false);

  const toggle = () => {
    setCollapsed(!collapsed);
    dispatch({ type: 'TOGGLE_SIDEBAR' });
  };

  return (
    <div
      style={{
        position: 'absolute',
        right: 0,
        top: 48,
        bottom: 0,
        width: collapsed ? COLLAPSED_WIDTH : SIDEBAR_WIDTH,
        background: '#0d1b2a',
        borderLeft: '1px solid #1a2d42',
        transition: 'width 0.3s ease',
        zIndex: 60,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* 折叠按钮 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: '1px solid #1a2d42',
          minHeight: 40,
        }}
      >
        {!collapsed && (
          <Space size="small">
            <AlertOutlined style={{ color: '#fa8c16' }} />
            <Text strong style={{ color: '#e0e8f0', fontSize: 13 }}>
              预警记录
            </Text>
            <Badge count={state.alertRecords.length} size="small" />
          </Space>
        )}
        <Button
          type="text"
          size="small"
          icon={collapsed ? <DoubleLeftOutlined /> : <DoubleRightOutlined />}
          onClick={toggle}
          style={{ color: '#8c9bb0', marginLeft: collapsed ? 'auto' : 0 }}
        />
      </div>

      {/* 记录列表 */}
      {!collapsed && (
        <>
          {state.alertRecords.length > 0 && (
            <div style={{ padding: '4px 12px', textAlign: 'right' }}>
              <Popconfirm
                title="清除全部预警记录？"
                onConfirm={() => dispatch({ type: 'CLEAR_RECORDS' })}
              >
                <Tooltip title="清除全部">
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    style={{ fontSize: 12 }}
                  >
                    清除
                  </Button>
                </Tooltip>
              </Popconfirm>
            </div>
          )}

          <div style={{ flex: 1, overflow: 'auto', padding: '0 4px' }}>
            {state.alertRecords.length === 0 ? (
              <div style={{ padding: 24, textAlign: 'center' }}>
                <Text style={{ color: '#8c9bb0' }}>暂无预警记录</Text>
              </div>
            ) : state.alertRecords.map((record) => (
                <div
                  key={record.id}
                  style={{
                    padding: '8px 12px',
                    borderBottom: '1px solid #1a2d42',
                    borderRadius: 4,
                    marginBottom: 2,
                    background:
                      record.alertType === AlertType.HighRisk
                        ? 'rgba(255, 77, 79, 0.08)'
                        : 'rgba(250, 140, 22, 0.05)',
                    cursor: 'default',
                  }}
                >
                  <div style={{ width: '100%' }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 4,
                      }}
                    >
                      <Text strong style={{ color: '#e0e8f0', fontSize: 13 }}>
                        {record.officerName}
                      </Text>
                      <Tag
                        color={record.alertType === AlertType.HighRisk ? 'error' : 'warning'}
                        style={{ margin: 0, fontSize: 11 }}
                        icon={
                          record.alertType === AlertType.HighRisk ? (
                            <WarningOutlined />
                          ) : (
                            <AlertOutlined />
                          )
                        }
                      >
                        {record.alertType}
                      </Tag>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text style={{ color: '#8c9bb0', fontSize: 11 }}>
                        {dayjs(record.timestamp).format('HH:mm:ss')}
                      </Text>
                      <Text style={{ color: '#fa8c16', fontSize: 12, fontWeight: 500 }}>
                        {record.coreTemp != null ? `${record.coreTemp.toFixed(1)}℃` : '--'}
                      </Text>
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </>
      )}
    </div>
  );
}

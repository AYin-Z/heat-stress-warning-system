/**
 * MQTT 服务层 — 连接 EMQX 中继服务器
 * WebSocket: ws://39.105.86.77:8083/mqtt
 */
import mqtt from 'mqtt';
import type { MqttClient } from 'mqtt';
import type { VitalData, AlertRecord, AlertPopupData } from '../types';

// ============================================================
// 配置
// ============================================================

const BROKER_URL = 'ws://39.105.86.77:8083/mqtt';

const TOPICS = {
  vital: 'watch/+/vital',       // 生理数据: watch/{deviceId}/vital
  alert: 'watch/+/alert',        // 预警触发: watch/{deviceId}/alert
  status: 'watch/+/status',      // 设备状态: watch/{deviceId}/status (online/offline)
};

// ============================================================
// 回调类型
// ============================================================

export type OnVitalData = (data: VitalData) => void;
export type OnAlert = (data: AlertPopupData) => void;
export type OnAlertRecord = (record: AlertRecord) => void;
export type OnStatusChange = (deviceId: string, online: boolean) => void;

// ============================================================
// MQTT 服务
// ============================================================

class MqttService {
  private client: MqttClient | null = null;
  private connected = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  // 回调注册
  private onVitalCallbacks: OnVitalData[] = [];
  private onAlertCallbacks: OnAlert[] = [];
  private onAlertRecordCallbacks: OnAlertRecord[] = [];
  private onStatusCallbacks: OnStatusChange[] = [];

  // ============================================================
  // 连接
  // ============================================================

  connect(clientId?: string) {
    const id = clientId || `pc-dashboard-${Date.now()}`;

    this.client = mqtt.connect(BROKER_URL, {
      clientId: id,
      clean: true,
      connectTimeout: 10000,
      reconnectPeriod: 5000,
    });

    this.client.on('connect', () => {
      console.log('[MQTT] Connected to EMQX');
      this.connected = true;

      // 订阅所有 watch 主题
      this.client!.subscribe(
        [TOPICS.vital, TOPICS.alert, TOPICS.status],
        { qos: 1 },
        (err) => {
          if (err) console.error('[MQTT] Subscribe error:', err);
          else console.log('[MQTT] Subscribed to watch topics');
        }
      );
    });

    this.client.on('message', (topic, payload) => {
      try {
        const data = JSON.parse(payload.toString());
        this.handleMessage(topic, data);
      } catch (e) {
        console.warn('[MQTT] Failed to parse message:', topic);
      }
    });

    this.client.on('error', (err) => {
      console.error('[MQTT] Error:', err.message);
    });

    this.client.on('close', () => {
      console.log('[MQTT] Disconnected');
      this.connected = false;
    });

    return this;
  }

  // ============================================================
  // 消息路由
  // ============================================================

  private handleMessage(topic: string, data: any) {
    // 从 topic 提取 deviceId: watch/{deviceId}/type
    const parts = topic.split('/');
    const deviceId = parts[1];

    if (topic.endsWith('/vital')) {
      const vitalData: VitalData = { deviceId, ...data };
      this.onVitalCallbacks.forEach((cb) => cb(vitalData));
    }

    if (topic.endsWith('/alert')) {
      const alertData: AlertPopupData = { deviceId, ...data };
      this.onAlertCallbacks.forEach((cb) => cb(alertData));

      // 同时生成历史记录
      const record: AlertRecord = {
        id: `${deviceId}-${Date.now()}`,
        timestamp: Date.now(),
        deviceId,
        officerName: data.officerName || deviceId,
        coreTemp: data.coreTemp,
        alertType: data.alertType,
      };
      this.onAlertRecordCallbacks.forEach((cb) => cb(record));
    }

    if (topic.endsWith('/status')) {
      const online = data.status === 'online';
      this.onStatusCallbacks.forEach((cb) => cb(deviceId, online));
    }
  }

  // ============================================================
  // 注册回调
  // ============================================================

  onVital(cb: OnVitalData) {
    this.onVitalCallbacks.push(cb);
    return () => {
      this.onVitalCallbacks = this.onVitalCallbacks.filter((c) => c !== cb);
    };
  }

  onAlert(cb: OnAlert) {
    this.onAlertCallbacks.push(cb);
    return () => {
      this.onAlertCallbacks = this.onAlertCallbacks.filter((c) => c !== cb);
    };
  }

  onAlertRecord(cb: OnAlertRecord) {
    this.onAlertRecordCallbacks.push(cb);
    return () => {
      this.onAlertRecordCallbacks = this.onAlertRecordCallbacks.filter((c) => c !== cb);
    };
  }

  onStatus(cb: OnStatusChange) {
    this.onStatusCallbacks.push(cb);
    return () => {
      this.onStatusCallbacks = this.onStatusCallbacks.filter((c) => c !== cb);
    };
  }

  // ============================================================
  // 断开
  // ============================================================

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.client?.end();
    this.connected = false;
  }

  isConnected() {
    return this.connected;
  }

  /** 发布消息（用于调试） */
  publish(topic: string, data: any) {
    this.client?.publish(topic, JSON.stringify(data), { qos: 1 });
  }
}

// 单例导出
export const mqttService = new MqttService();

"""
watch-api 转发 — 将计算得到的 core_temperature 转发到外部 watch-api。

配置:
    WATCH_API_URL              # watch-api 地址
    WATCH_API_FORWARD_ENABLED  # 是否启用转发 (默认 True)
"""

import json
import logging
import threading
from urllib import request, error

from django.conf import settings

logger = logging.getLogger(__name__)


def _build_payload(device_id: str, core_temperature: float,
                   timestamp: str, source: str) -> dict:
    """构建转发到 watch-api 的 payload"""
    return {
        "device_id": device_id,
        "core_temperature": core_temperature,
        "timestamp": timestamp,
        "source": source,
    }


def forward_core_temperature(device_id: str, core_temperature: float,
                             timestamp: str = "", source: str = "informer_model_1"):
    """
    转发核心温度到 watch-api（后台线程，不阻塞主请求）。

    参数:
        device_id: 设备 ID
        core_temperature: 核心温度值
        timestamp: ISO 格式时间戳
        source: 数据来源 (kalman_estimation / informer_model_1)
    """
    enabled = getattr(settings, 'WATCH_API_FORWARD_ENABLED', True)
    if not enabled:
        return

    watch_api_url = getattr(settings, 'WATCH_API_URL', '')
    if not watch_api_url:
        logger.warning("[Forward] WATCH_API_URL 未配置，跳过转发")
        return

    payload = _build_payload(device_id, core_temperature, timestamp, source)

    def _do_forward():
        try:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            req = request.Request(
                watch_api_url,
                data=data,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with request.urlopen(req, timeout=5) as resp:
                logger.info(f"[Forward] device={device_id} ct={core_temperature} "
                            f"→ watch-api status={resp.status}")
        except error.HTTPError as e:
            logger.error(f"[Forward] HTTP {e.code}: {e.reason}")
        except Exception as e:
            logger.error(f"[Forward] 失败: {e}")

    t = threading.Thread(target=_do_forward, daemon=True)
    t.start()

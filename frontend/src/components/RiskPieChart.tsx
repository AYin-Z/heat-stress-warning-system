/**
 * 风险概况饼图 — 右上角
 * 绿(正常) / 橙(普通预警) / 红(高风险) / 灰(离线)
 */
import * as echarts from 'echarts/core';
import { PieChart } from 'echarts/charts';
import { TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import EChartsReactCore from 'echarts-for-react/esm/core';
import { useAppState } from '../store';

echarts.use([PieChart, TooltipComponent, CanvasRenderer]);

export default function RiskPieChart() {
  const { getRiskStats } = useAppState();
  const stats = getRiskStats();

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: '{b}: {c} 人 ({d}%)',
    },
    series: [
      {
        name: '风险概况',
        type: 'pie',
        radius: ['50%', '75%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 4,
          borderColor: '#0d1b2a',
          borderWidth: 3,
        },
        label: {
          show: true,
          position: 'outside',
          formatter: '{b}\n{d}%',
          color: '#8c9bb0',
          fontSize: 11,
        },
        emphasis: {
          label: { fontSize: 16, fontWeight: 'bold' },
          scaleSize: 8,
        },
        data: [
          {
            value: stats.normal,
            name: '正常',
            itemStyle: { color: '#52c41a' },
          },
          {
            value: stats.warning,
            name: '普通预警',
            itemStyle: { color: '#fa8c16' },
          },
          {
            value: stats.highRisk,
            name: '高风险',
            itemStyle: { color: '#ff4d4f' },
          },
          {
            value: stats.offline,
            name: '离线',
            itemStyle: { color: '#8c8c8c' },
          },
        ].filter((d) => d.value > 0),
      },
    ],
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 56,
        right: 8,
        width: 200,
        height: 200,
        zIndex: 50,
      }}
    >
      <EChartsReactCore
        echarts={echarts}
        option={option}
        style={{ width: '100%', height: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}

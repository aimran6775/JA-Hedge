"use client";

import { useEffect, useRef } from "react";
import { createChart, type IChartApi, ColorType, LineStyle } from "lightweight-charts";

interface EquityCurveProps {
  /** Array of { cumulative_pnl: number } or { pnl: number } */
  data: Array<Record<string, unknown>>;
  height?: number;
}

/**
 * Interactive equity curve chart using TradingView lightweight-charts.
 * Replaces the old static SVG.
 */
export function EquityCurve({ data, height = 220 }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || data.length < 2) return;

    // Clean up old chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(90, 90, 114, 0.8)",
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.03)" },
        horzLines: { color: "rgba(255,255,255,0.03)" },
      },
      crosshair: {
        vertLine: { color: "rgba(16,185,129,0.3)", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "rgba(16,185,129,0.3)", width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.06)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.06)",
        timeVisible: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true },
    });

    chartRef.current = chart;

    // Build cumulative P&L series
    const values = data.map((d) =>
      (d.cumulative_pnl as number) ?? (d.pnl as number) ?? 0,
    );

    // Use trade index as "time" — lightweight-charts needs ascending numbers
    const seriesData = values.map((v, i) => ({
      time: (i + 1) as unknown as import("lightweight-charts").Time,
      value: v,
    }));

    const lastVal = values[values.length - 1] ?? 0;
    const lineColor = lastVal >= 0 ? "#10b981" : "#ef4444";
    const areaTop = lastVal >= 0 ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)";
    const areaBottom = "rgba(0,0,0,0)";

    const series = chart.addAreaSeries({
      lineColor,
      topColor: areaTop,
      bottomColor: areaBottom,
      lineWidth: 2,
      priceFormat: { type: "custom", formatter: (v: number) => `$${v.toFixed(2)}` },
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: lineColor,
      crosshairMarkerBackgroundColor: "#050508",
    });

    series.setData(seriesData);

    // Zero line
    series.createPriceLine({
      price: 0,
      color: "rgba(255,255,255,0.1)",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: false,
    });

    chart.timeScale().fitContent();

    // Responsive resize
    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height]);

  if (data.length < 2) {
    return (
      <div className="flex items-center justify-center text-sm text-[var(--text-muted)]" style={{ height }}>
        Not enough trades for a chart
      </div>
    );
  }

  return <div ref={containerRef} className="w-full" />;
}

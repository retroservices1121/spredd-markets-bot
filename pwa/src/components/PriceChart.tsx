import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, ColorType } from "lightweight-charts";

interface PriceChartProps {
  data?: { time: string; value: number }[];
  color?: string;
  height?: number;
}

export function PriceChart({
  data,
  color = "#00FF88",
  height = 200,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9CA3AF",
        fontSize: 11,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "rgba(255,255,255,0.05)" },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.05 },
      },
      timeScale: {
        borderVisible: false,
        timeVisible: false,
      },
      crosshair: {
        horzLine: { visible: false },
        vertLine: { labelVisible: false },
      },
      handleScroll: false,
      handleScale: false,
    });

    const series = chart.addAreaSeries({
      lineColor: color,
      topColor: `${color}33`,
      bottomColor: `${color}05`,
      lineWidth: 2,
      priceFormat: { type: "custom", formatter: (p: number) => `${(p * 100).toFixed(0)}%` },
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [color, height]);

  useEffect(() => {
    if (!seriesRef.current || !data?.length) return;
    seriesRef.current.setData(
      data.map((d) => ({ time: d.time as string, value: d.value }))
    );
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  // Show placeholder data if no real data
  useEffect(() => {
    if (data?.length || !seriesRef.current) return;
    const now = Date.now();
    const placeholder = Array.from({ length: 30 }, (_, i) => ({
      time: new Date(now - (29 - i) * 86400000).toISOString().split("T")[0],
      value: 0.5 + Math.sin(i * 0.3) * 0.15 + Math.random() * 0.05,
    }));
    seriesRef.current.setData(placeholder);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={containerRef} className="w-full" />;
}

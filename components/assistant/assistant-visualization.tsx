"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  XAxis,
  YAxis,
} from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Visualization } from "@/lib/types/brim";
import {
  normalizeKpiData,
  normalizePieChartData,
  normalizeSeriesChartData,
  normalizeTableData,
} from "@/lib/assistant/normalize-visualization-data";
import { cn } from "@/lib/utils";

const chartConfig = {
  value: { label: "Amount", color: "var(--chart-1)" },
  spend: { label: "Spend", color: "var(--chart-3)" },
} satisfies ChartConfig;

const pieColors = [
  "var(--chart-1)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

type AssistantVisualizationProps = {
  visualization: Visualization;
  size?: "default" | "stage" | "fullscreen";
};

export function AssistantVisualization({
  visualization,
  size = "default",
}: AssistantVisualizationProps) {
  const { type, title, data } = visualization;
  const chartHeight =
    size === "fullscreen"
      ? "aspect-auto h-[calc(100vh-14rem)] max-h-none w-full"
      : size === "stage"
        ? "aspect-auto h-[min(50vh,20rem)] max-h-[50vh] w-full"
        : "h-48";
  const tableScrollClass =
    size === "fullscreen"
      ? "max-h-[calc(100vh-14rem)] overflow-y-auto"
      : size === "stage"
        ? "max-h-[50vh] overflow-y-auto"
        : undefined;
  const kpiValueClass =
    size === "fullscreen"
      ? "text-5xl md:text-6xl"
      : size === "stage"
        ? "text-4xl md:text-5xl"
        : "text-2xl";
  const wrapperClass =
    size === "fullscreen"
      ? "flex min-h-0 flex-1 flex-col rounded-xl border border-border/50 bg-card p-4 md:p-6"
      : size === "stage"
        ? "rounded-xl border border-border/50 bg-card p-6 md:p-8"
        : "rounded-xl border border-border/50 bg-card p-4";

  const emptyState = (
    <div className={wrapperClass}>
      <p className="text-sm font-normal text-muted-foreground">{title}</p>
      <p className="mt-3 text-sm text-muted-foreground">
        Chart data is unavailable for this response.
      </p>
    </div>
  );

  if (type === "kpi") {
    const kpiData = normalizeKpiData(data);
    if (!kpiData) return emptyState;
    return (
      <div className={wrapperClass}>
        <p className="text-xs font-normal text-muted-foreground">{title}</p>
        <p className={cn("mt-2 font-normal text-primary/80", kpiValueClass)}>
          {kpiData.value}
        </p>
        <p className="text-sm text-muted-foreground">{kpiData.label}</p>
        {kpiData.change && (
          <p className="mt-1 text-xs text-muted-foreground">{kpiData.change}</p>
        )}
      </div>
    );
  }

  if (type === "table") {
    const tableData = normalizeTableData(data);
    if (tableData.columns.length === 0) return emptyState;
    return (
      <div className={cn(wrapperClass, "overflow-hidden p-0")}>
        <p className="border-b border-border/40 px-4 py-3 text-xs font-normal text-muted-foreground">
          {title}
        </p>
        <div className={cn(tableScrollClass)}>
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow>
                {tableData.columns.map((col) => (
                  <TableHead key={col}>{col}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {tableData.rows.map((row, i) => (
                <TableRow key={i}>
                  {row.map((cell, j) => (
                    <TableCell key={j}>{cell}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    );
  }

  if (type === "bar") {
    const chartData = normalizeSeriesChartData(data).map(({ name, value }) => ({
      name,
      spend: value,
    }));
    if (chartData.length === 0) return emptyState;
    return (
      <div className={wrapperClass}>
        <p className="mb-4 text-sm font-normal text-muted-foreground">{title}</p>
        <ChartContainer config={chartConfig} className={cn(chartHeight, "w-full")}>
          <BarChart data={chartData}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="name" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="spend" fill="var(--color-spend)" radius={4} />
          </BarChart>
        </ChartContainer>
      </div>
    );
  }

  if (type === "line") {
    const chartData = normalizeSeriesChartData(data);
    if (chartData.length === 0) return emptyState;
    return (
      <div className={wrapperClass}>
        <p className="mb-4 text-sm font-normal text-muted-foreground">{title}</p>
        <ChartContainer config={chartConfig} className={cn(chartHeight, "w-full")}>
          <LineChart data={chartData}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="name" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Line
              type="monotone"
              dataKey="value"
              stroke="var(--color-value)"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ChartContainer>
      </div>
    );
  }

  if (type === "pie") {
    const segments = normalizePieChartData(data);
    if (segments.length === 0) return emptyState;
    return (
      <div className={wrapperClass}>
        <p className="mb-4 text-sm font-normal text-muted-foreground">{title}</p>
        <ChartContainer
          config={chartConfig}
          className={cn(
            chartHeight,
            "mx-auto w-full",
            size === "fullscreen"
              ? "max-w-2xl"
              : size === "stage"
                ? "max-w-lg"
                : "max-w-xs"
          )}
        >
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent />} />
            <Pie
              data={segments}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={70}
            >
              {segments.map((_, i) => (
                <Cell key={i} fill={pieColors[i % pieColors.length]} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
      </div>
    );
  }

  return null;
}

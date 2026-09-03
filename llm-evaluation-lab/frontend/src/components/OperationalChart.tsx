import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ComparisonData } from "../types";

export default function OperationalChart({ comparison }: { comparison: ComparisonData }) {
  const data = comparison.all_configurations.map((item) => {
    const metric = item.metrics.find((candidate) => candidate.name === "p95_latency");
    return { name: item.key.toUpperCase(), latency: metric?.value ?? 0, fullName: item.label };
  });
  return (
    <div className="chart-wrap" aria-label="p95 latency by configuration">
      <div><h3>p95 latency by configuration</h3><p>Milliseconds · lower is better</p></div>
      <ResponsiveContainer width="100%" height={176}>
        <BarChart data={data} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
          <CartesianGrid stroke="#d9dde0" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: "#626c73", fontSize: 11 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: "#626c73", fontSize: 11 }} axisLine={false} tickLine={false} unit=" ms" />
          <Tooltip formatter={(value) => [`${Number(value).toFixed(1)} ms`, "p95 latency"]} labelFormatter={(_, payload) => payload[0]?.payload.fullName ?? ""} />
          <Bar dataKey="latency" fill="#1265d6" radius={[3, 3, 0, 0]} maxBarSize={48} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

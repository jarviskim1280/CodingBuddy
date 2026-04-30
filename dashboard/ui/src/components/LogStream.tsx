import { useEffect, useRef } from "react";

interface Log {
  id: number;
  agent_id: number;
  timestamp: string;
  level: string;
  message: string;
}

const LEVEL_STYLES: Record<string, string> = {
  info: "text-gray-300",
  debug: "text-gray-600",
  warning: "text-yellow-400",
  error: "text-red-400",
};

function fmtTime(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return iso;
  }
}

interface LogStreamProps {
  logs: Log[];
  agentId?: number | null;
  maxHeight?: string;
}

export default function LogStream({ logs, agentId, maxHeight = "320px" }: LogStreamProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  const filtered = agentId != null ? logs.filter((l) => l.agent_id === agentId) : logs;

  if (!filtered.length) {
    return (
      <div
        className="font-mono text-sm bg-gray-950 border border-gray-800 rounded-lg p-4 text-gray-700"
        style={{ maxHeight }}
      >
        No logs yet...
      </div>
    );
  }

  return (
    <div
      className="font-mono text-xs bg-gray-950 border border-gray-800 rounded-lg p-3 overflow-y-auto space-y-0.5"
      style={{ maxHeight }}
    >
      {filtered.map((log) => (
        <div key={log.id} className="flex gap-2">
          <span className="text-gray-700 shrink-0">{fmtTime(log.timestamp)}</span>
          <span className={`shrink-0 w-12 ${LEVEL_STYLES[log.level] ?? "text-gray-400"}`}>
            [{log.level}]
          </span>
          <span className={LEVEL_STYLES[log.level] ?? "text-gray-300"}>{log.message}</span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

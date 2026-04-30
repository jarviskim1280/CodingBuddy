interface Agent {
  id: number;
  type: string;
  status: string;
  current_task_id: number | null;
  last_heartbeat: string | null;
}

const STATUS_STYLES: Record<string, string> = {
  idle: "bg-gray-800 text-gray-400",
  working: "bg-cyan-900 text-cyan-300",
  waiting: "bg-yellow-900 text-yellow-300",
  done: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

const STATUS_DOT: Record<string, string> = {
  idle: "bg-gray-500",
  working: "bg-cyan-400 animate-pulse",
  waiting: "bg-yellow-400 animate-pulse",
  done: "bg-green-400",
  failed: "bg-red-400",
};

const TYPE_ICONS: Record<string, string> = {
  backend: "⚙️",
  frontend: "🎨",
  tester: "🧪",
  reviewer: "🔍",
};

export default function AgentStatus({ agents }: { agents: Agent[] }) {
  if (!agents.length) {
    return <p className="text-gray-600 text-sm">No agents spawned yet.</p>;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {agents.map((agent) => {
        const badge = STATUS_STYLES[agent.status] ?? "bg-gray-800 text-gray-400";
        const dot = STATUS_DOT[agent.status] ?? "bg-gray-500";
        const icon = TYPE_ICONS[agent.type] ?? "🤖";

        return (
          <div
            key={agent.id}
            className="flex items-center gap-3 p-3 rounded-lg border border-gray-800 bg-gray-900"
          >
            <span className="text-2xl">{icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-sm capitalize text-gray-200">{agent.type}</span>
                <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
              </div>
              <div className={`text-xs px-1.5 py-0.5 rounded font-medium inline-block mt-0.5 ${badge}`}>
                {agent.status}
              </div>
              {agent.current_task_id && (
                <p className="text-xs text-gray-600 mt-0.5">task #{agent.current_task_id}</p>
              )}
            </div>
            <div className="text-xs text-gray-700 shrink-0">#{agent.id}</div>
          </div>
        );
      })}
    </div>
  );
}

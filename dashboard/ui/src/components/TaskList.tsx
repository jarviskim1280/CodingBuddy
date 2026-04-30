interface Task {
  id: number;
  type: string;
  description: string;
  status: string;
  branch: string;
  pr_url: string;
  assigned_agent_id: number | null;
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-gray-800 text-gray-400",
  in_progress: "bg-cyan-900 text-cyan-300",
  review: "bg-blue-900 text-blue-300",
  done: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

const TYPE_ICONS: Record<string, string> = {
  backend: "⚙️",
  frontend: "🎨",
  tests: "🧪",
  review: "🔍",
};

export default function TaskList({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) {
    return <p className="text-gray-600 text-sm">No tasks yet.</p>;
  }

  return (
    <div className="space-y-2">
      {tasks.map((task) => {
        const badge = STATUS_STYLES[task.status] ?? "bg-gray-800 text-gray-400";
        const icon = TYPE_ICONS[task.type] ?? "📋";

        return (
          <div
            key={task.id}
            className="flex items-start gap-3 p-3 rounded-lg border border-gray-800 bg-gray-900"
          >
            <span className="text-lg shrink-0">{icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-mono text-gray-500 uppercase">{task.type}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${badge}`}>
                  {task.status}
                </span>
              </div>
              <p className="text-sm text-gray-300 mt-0.5 line-clamp-2">{task.description}</p>
              {task.branch && (
                <span className="text-xs font-mono text-gray-600 mt-1 block">{task.branch}</span>
              )}
              {task.pr_url && task.pr_url.startsWith("http") && (
                <a
                  href={task.pr_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-cyan-500 hover:underline mt-0.5 block"
                >
                  View PR →
                </a>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

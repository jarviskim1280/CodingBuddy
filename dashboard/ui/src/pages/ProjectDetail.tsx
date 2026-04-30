import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import TaskList from "../components/TaskList";
import AgentStatus from "../components/AgentStatus";
import LogStream from "../components/LogStream";

interface Task {
  id: number;
  type: string;
  description: string;
  status: string;
  branch: string;
  pr_url: string;
  assigned_agent_id: number | null;
}

interface Agent {
  id: number;
  type: string;
  status: string;
  current_task_id: number | null;
  last_heartbeat: string | null;
}

interface Log {
  id: number;
  agent_id: number;
  timestamp: string;
  level: string;
  message: string;
}

interface Project {
  id: number;
  name: string;
  description: string;
  status: string;
  stack: Record<string, string | string[]>;
  repo_url: string;
  created_at: string;
  tasks: Task[];
  agents: Agent[];
}

const STATUS_STYLES: Record<string, string> = {
  planning: "text-yellow-400",
  active: "text-cyan-400",
  done: "text-green-400",
  failed: "text-red-400",
};

export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [logs, setLogs] = useState<Log[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchProject = async () => {
    const res = await fetch(`/api/projects/${id}`);
    if (!res.ok) return;
    const data = await res.json();
    setProject(data);
    if (data.agents.length > 0 && selectedAgent == null) {
      setSelectedAgent(data.agents[0].id);
    }
  };

  const fetchLogs = async (agentId: number) => {
    const res = await fetch(`/api/agents/logs?agent_id=${agentId}&limit=300`);
    if (!res.ok) return;
    const data = await res.json();
    setLogs(data);
  };

  useEffect(() => {
    fetchProject().finally(() => setLoading(false));

    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (ev) => {
      const event = JSON.parse(ev.data);
      if (event.type === "log" || event.type === "agent_status" || event.type === "project_done") {
        fetchProject();
        if (selectedAgent != null) fetchLogs(selectedAgent);
      }
    };
    const ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 20_000);

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, [id]);

  useEffect(() => {
    if (selectedAgent != null) fetchLogs(selectedAgent);
  }, [selectedAgent]);

  if (loading) return <div className="text-gray-500 text-sm">Loading...</div>;
  if (!project) return <div className="text-red-400">Project not found.</div>;

  const statusColor = STATUS_STYLES[project.status] ?? "text-gray-400";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <Link to="/" className="text-sm text-gray-500 hover:text-gray-300 mb-2 inline-block">
          ← All projects
        </Link>
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold font-mono text-white">{project.name}</h1>
          <span className={`text-sm font-medium ${statusColor}`}>{project.status}</span>
        </div>
        <p className="text-gray-400 text-sm mt-1">{project.description}</p>
        {project.repo_url && (
          <p className="text-xs text-gray-600 mt-1 font-mono">{project.repo_url}</p>
        )}
      </div>

      {/* Stack badges */}
      {project.stack && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(project.stack)
            .filter(([, v]) => v && typeof v === "string")
            .map(([k, v]) => (
              <span key={k} className="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded border border-gray-700">
                {k}: {v as string}
              </span>
            ))}
        </div>
      )}

      {/* Two-column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 mb-3">Tasks</h2>
          <TaskList tasks={project.tasks} />
        </section>

        <section>
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500 mb-3">Agents</h2>
          <AgentStatus agents={project.agents} />
        </section>
      </div>

      {/* Log stream */}
      {project.agents.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Logs</h2>
            <div className="flex gap-2">
              {project.agents.map((a) => (
                <button
                  key={a.id}
                  onClick={() => setSelectedAgent(a.id)}
                  className={`text-xs px-2 py-1 rounded border transition-colors capitalize ${
                    selectedAgent === a.id
                      ? "border-cyan-600 text-cyan-300 bg-cyan-950"
                      : "border-gray-700 text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {a.type} #{a.id}
                </button>
              ))}
            </div>
          </div>
          <LogStream logs={logs} maxHeight="400px" />
        </section>
      )}
    </div>
  );
}

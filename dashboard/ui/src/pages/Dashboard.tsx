import { useEffect, useState } from "react";
import ProjectCard from "../components/ProjectCard";

interface Project {
  id: number;
  name: string;
  description: string;
  status: string;
  stack: Record<string, string | string[]>;
  created_at: string;
  repo_url: string;
}

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = async () => {
    try {
      const res = await fetch("/api/projects/");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setProjects(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();

    // subscribe to WS for live updates
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (ev) => {
      const event = JSON.parse(ev.data);
      if (event.type === "project_done" || event.type === "agent_status") {
        fetchProjects();
      }
    };
    // keep-alive ping
    const ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 20_000);

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Projects</h1>
          <p className="text-gray-500 text-sm mt-1">
            Run <code className="bg-gray-800 px-1 rounded">buddy new "description"</code> to create a project.
          </p>
        </div>
        <button
          onClick={fetchProjects}
          className="text-sm text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-1.5 transition-colors"
        >
          Refresh
        </button>
      </div>

      {loading && (
        <div className="text-gray-500 text-sm">Loading...</div>
      )}

      {error && (
        <div className="text-red-400 bg-red-950 border border-red-900 rounded-lg p-4 text-sm">
          Error: {error}
        </div>
      )}

      {!loading && !error && projects.length === 0 && (
        <div className="text-center py-20 text-gray-600">
          <p className="text-4xl mb-4">⚡</p>
          <p className="text-lg font-medium text-gray-500">No projects yet</p>
          <p className="text-sm mt-2">
            Run <code className="bg-gray-800 text-gray-300 px-1.5 py-0.5 rounded">buddy new "build a todo app"</code> to get started.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
      </div>
    </div>
  );
}

import { Link } from "react-router-dom";

interface Project {
  id: number;
  name: string;
  description: string;
  status: string;
  stack: Record<string, string | string[]>;
  created_at: string;
  repo_url: string;
}

const STATUS_STYLES: Record<string, string> = {
  planning: "bg-yellow-900 text-yellow-300",
  active: "bg-cyan-900 text-cyan-300",
  done: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

export default function ProjectCard({ project }: { project: Project }) {
  const badge = STATUS_STYLES[project.status] ?? "bg-gray-800 text-gray-400";
  const stack = project.stack;

  return (
    <Link to={`/projects/${project.id}`} className="block">
      <div className="rounded-xl border border-gray-800 bg-gray-900 p-5 hover:border-cyan-700 transition-colors">
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-mono font-semibold text-white text-lg">{project.name}</h2>
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full shrink-0 ${badge}`}>
            {project.status}
          </span>
        </div>
        <p className="text-gray-400 text-sm mt-1 line-clamp-2">{project.description}</p>

        {stack && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {Object.entries(stack)
              .filter(([, v]) => v && typeof v === "string")
              .map(([k, v]) => (
                <span key={k} className="text-xs bg-gray-800 text-gray-300 px-2 py-0.5 rounded">
                  {v as string}
                </span>
              ))}
          </div>
        )}

        <div className="flex items-center justify-between mt-4 text-xs text-gray-600">
          <span>#{project.id}</span>
          <span>{project.created_at ? new Date(project.created_at).toLocaleDateString() : ""}</span>
        </div>
      </div>
    </Link>
  );
}

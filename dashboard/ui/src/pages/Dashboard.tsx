import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
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

type PipelineStep = "idle" | "planning" | "repo" | "launching" | "done" | "error";

const STEP_LABELS: Record<PipelineStep, string> = {
  idle: "",
  planning: "Planning with Claude…",
  repo: "Creating repository…",
  launching: "Launching agents…",
  done: "Done!",
  error: "Something went wrong",
};

export default function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // new-project form
  const [showForm, setShowForm] = useState(false);
  const [description, setDescription] = useState("");
  const [step, setStep] = useState<PipelineStep>("idle");
  const [stepMessage, setStepMessage] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const fetchProjects = async () => {
    try {
      const res = await fetch("/api/projects/");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setProjects(await res.json());
      setFetchError(null);
    } catch (e) {
      setFetchError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();

    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onmessage = (ev) => {
      const event = JSON.parse(ev.data);

      if (event.type === "pipeline_status") {
        setStepMessage(event.message);
        setStep(event.step as PipelineStep);
      }

      if (event.type === "project_created") {
        setStep("launching");
        setStepMessage(event.message);
        fetchProjects();
        // navigate after a brief moment so user sees the "launching" state
        setTimeout(() => navigate(`/projects/${event.project_id}`), 1200);
      }

      if (event.type === "project_error") {
        setStep("error");
        setStepMessage(event.error);
      }

      if (event.type === "project_done" || event.type === "agent_status") {
        fetchProjects();
      }
    };

    const ping = setInterval(
      () => ws.readyState === WebSocket.OPEN && ws.send("ping"),
      20_000
    );

    return () => {
      clearInterval(ping);
      ws.close();
    };
  }, []);

  // auto-focus textarea when form opens
  useEffect(() => {
    if (showForm) setTimeout(() => textareaRef.current?.focus(), 50);
  }, [showForm]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!description.trim() || step !== "idle") return;

    setSubmitError(null);
    setStep("planning");
    setStepMessage(STEP_LABELS["planning"]);

    try {
      const res = await fetch("/api/projects/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: description.trim() }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail ?? `HTTP ${res.status}`);
      }

      // navigation happens via the WS project_created event
    } catch (e) {
      setStep("error");
      setSubmitError(String(e));
    }
  };

  const resetForm = () => {
    setShowForm(false);
    setDescription("");
    setStep("idle");
    setStepMessage("");
    setSubmitError(null);
  };

  const busy = step !== "idle" && step !== "error";

  return (
    <div>
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Projects</h1>
          <p className="text-gray-500 text-sm mt-1">
            Describe what you want to build and Claude agents will generate it.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchProjects}
            className="text-sm text-gray-400 hover:text-white border border-gray-700 rounded-lg px-3 py-1.5 transition-colors"
          >
            Refresh
          </button>
          {!showForm && (
            <button
              onClick={() => setShowForm(true)}
              className="text-sm font-medium bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg px-4 py-1.5 transition-colors"
            >
              + New project
            </button>
          )}
        </div>
      </div>

      {/* ── New project form ── */}
      {showForm && (
        <div className="mb-8 rounded-xl border border-cyan-800 bg-gray-900 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-white">New project</h2>
            {!busy && (
              <button
                onClick={resetForm}
                className="text-gray-500 hover:text-gray-300 text-sm"
              >
                ✕ Cancel
              </button>
            )}
          </div>

          <form onSubmit={handleSubmit} className="space-y-3">
            <textarea
              ref={textareaRef}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={busy}
              placeholder='e.g. "A todo app with task creation, due dates, and completion tracking"'
              rows={3}
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-cyan-600 resize-none disabled:opacity-50"
            />

            {/* step progress */}
            {step !== "idle" && (
              <div
                className={`flex items-center gap-2 text-sm px-3 py-2 rounded-lg ${
                  step === "error"
                    ? "bg-red-950 text-red-400 border border-red-800"
                    : "bg-cyan-950 text-cyan-300 border border-cyan-800"
                }`}
              >
                {busy && (
                  <span className="inline-block w-3 h-3 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin shrink-0" />
                )}
                <span>{stepMessage || STEP_LABELS[step]}</span>
              </div>
            )}

            {submitError && step === "error" && (
              <p className="text-xs text-red-400">{submitError}</p>
            )}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={!description.trim() || busy}
                className="px-5 py-2 text-sm font-medium bg-cyan-600 hover:bg-cyan-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg transition-colors"
              >
                {busy ? "Working…" : "Generate project"}
              </button>
              {step === "error" && (
                <button
                  type="button"
                  onClick={() => { setStep("idle"); setSubmitError(null); }}
                  className="px-4 py-2 text-sm text-gray-400 hover:text-white border border-gray-700 rounded-lg transition-colors"
                >
                  Try again
                </button>
              )}
            </div>
          </form>
        </div>
      )}

      {/* ── Errors / loading ── */}
      {loading && <div className="text-gray-500 text-sm">Loading…</div>}
      {fetchError && (
        <div className="text-red-400 bg-red-950 border border-red-900 rounded-lg p-4 text-sm mb-6">
          Error: {fetchError}
        </div>
      )}

      {/* ── Empty state ── */}
      {!loading && !fetchError && projects.length === 0 && (
        <div className="text-center py-20 text-gray-600">
          <p className="text-4xl mb-4">⚡</p>
          <p className="text-lg font-medium text-gray-500">No projects yet</p>
          <p className="text-sm mt-2">
            Click{" "}
            <button
              onClick={() => setShowForm(true)}
              className="text-cyan-500 hover:underline"
            >
              + New project
            </button>{" "}
            to get started.
          </p>
        </div>
      )}

      {/* ── Project grid ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} />
        ))}
      </div>
    </div>
  );
}

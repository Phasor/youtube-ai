import { useState, useEffect, useRef } from "react";

const STYLES = [
  "cinematic documentary",
  "dark thriller",
  "anime",
  "sci-fi futurism",
  "nature & wildlife",
  "corporate explainer",
  "historical drama",
  "horror",
];

const MOCK_SCENES = Array.from({ length: 60 }, (_, i) => ({
  index: i + 1,
  title: `Scene ${i + 1}`,
  status: i < 8 ? "done" : i === 8 ? "generating" : "pending",
  narration: "",
  visual_prompt: "",
}));

function StatusDot({ status }) {
  const map = {
    done: "#00ff9d",
    generating: "#ffb830",
    failed: "#ff3d3d",
    pending: "#2a2a3e",
  };
  return (
    <div
      style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: map[status] || map.pending,
        boxShadow: status === "generating" ? `0 0 8px ${map.generating}` : status === "done" ? `0 0 4px ${map.done}44` : "none",
        animation: status === "generating" ? "pulse 1.2s ease-in-out infinite" : "none",
        flexShrink: 0,
      }}
    />
  );
}

function SceneGrid({ scenes }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(10, 1fr)", gap: 4 }}>
      {scenes.map((s) => {
        const colours = {
          done: "#00ff9d22",
          generating: "#ffb83033",
          failed: "#ff3d3d22",
          pending: "#ffffff08",
        };
        const borders = {
          done: "#00ff9d55",
          generating: "#ffb830",
          failed: "#ff3d3d55",
          pending: "#ffffff11",
        };
        return (
          <div
            key={s.index}
            title={s.title}
            style={{
              aspectRatio: "1",
              background: colours[s.status],
              border: `1px solid ${borders[s.status]}`,
              borderRadius: 3,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 8,
              color: s.status === "done" ? "#00ff9d" : s.status === "generating" ? "#ffb830" : "#ffffff33",
              fontFamily: "monospace",
              cursor: "default",
              transition: "all 0.3s",
              animation: s.status === "generating" ? "glow 1.2s ease-in-out infinite" : "none",
            }}
          >
            {s.index}
          </div>
        );
      })}
    </div>
  );
}

function LogLine({ line }) {
  const colour = line.startsWith("[ERR]") ? "#ff3d3d" :
                 line.startsWith("[OK]") ? "#00ff9d" :
                 line.startsWith("[WARN]") ? "#ffb830" : "#8888aa";
  return (
    <div style={{ color: colour, fontFamily: "monospace", fontSize: 12, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>
      {line}
    </div>
  );
}

export default function App() {
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState("cinematic documentary");
  const [customStyle, setCustomStyle] = useState("");
  const [scenes, setScenes] = useState(MOCK_SCENES);
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState("idle"); // idle | scripting | generating | stitching | done
  const [logs, setLogs] = useState([
    "[INFO] Pipeline ready. Enter a topic and click Run.",
  ]);
  const [progress, setProgress] = useState({ done: 8, total: 60 });
  const [elapsedSecs, setElapsedSecs] = useState(0);
  const [estMinutes, setEstMinutes] = useState(null);
  const logEndRef = useRef(null);
  const timerRef = useRef(null);
  const animRef = useRef(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const addLog = (msg) => setLogs((l) => [...l, msg]);

  const fmtTime = (s) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const simulatePipeline = () => {
    if (!topic.trim()) return;
    const finalStyle = customStyle.trim() || style;
    setRunning(true);
    setPhase("scripting");
    setElapsedSecs(0);
    setProgress({ done: 0, total: 60 });
    setScenes(MOCK_SCENES.map((s) => ({ ...s, status: "pending" })));
    setLogs([]);

    timerRef.current = setInterval(() => {
      setElapsedSecs((e) => e + 1);
    }, 1000);

    addLog(`[INFO] Starting pipeline`);
    addLog(`[INFO] Topic: "${topic}"`);
    addLog(`[INFO] Style: ${finalStyle}`);
    addLog(`[INFO] Target: 60 scenes × 10s = 10 min video`);

    setTimeout(() => {
      addLog(`[INFO] Calling Claude to generate script...`);
    }, 800);

    setTimeout(() => {
      addLog(`[OK]   Script generated: 60 scenes`);
      addLog(`[INFO] Beginning video generation with Kling v2-master`);
      setPhase("generating");

      let sceneIdx = 0;
      const interval = setInterval(() => {
        if (sceneIdx >= 60) {
          clearInterval(interval);
          setPhase("stitching");
          addLog(`\n[INFO] All clips generated`);
          addLog(`[INFO] Generating voiceover with ElevenLabs...`);
          setTimeout(() => {
            addLog(`[OK]   Voiceover saved: audio/voiceover.mp3`);
            addLog(`[INFO] Stitching final video with ffmpeg...`);
            setTimeout(() => {
              addLog(`[OK]   Final video: final/abc123_final.mp4`);
              addLog(`[OK]   ═══════════════════════════════`);
              addLog(`[OK]   Pipeline complete: 60/60 scenes`);
              addLog(`[OK]   Total runtime: ~${Math.round(elapsedSecs / 60)}m`);
              setPhase("done");
              setRunning(false);
              clearInterval(timerRef.current);
            }, 2000);
          }, 1500);
          return;
        }

        const idx = sceneIdx;
        setScenes((prev) =>
          prev.map((s) =>
            s.index === idx + 1 ? { ...s, status: "generating" } :
            s.index === idx ? { ...s, status: "done" } : s
          )
        );

        if (idx % 5 === 0) {
          const secsPerScene = 18;
          const remaining = (60 - idx) * secsPerScene;
          setEstMinutes(Math.ceil(remaining / 60));
          addLog(`[INFO] Scene ${idx + 1}/60: submitting to Kling...`);
        }
        if (idx > 0 && idx % 5 === 4) {
          addLog(`[OK]   Scenes ${idx - 3}–${idx + 1} complete, frames chained`);
        }

        setProgress({ done: idx, total: 60 });
        sceneIdx++;
      }, 120);
    }, 2500);
  };

  const done = progress.done;
  const total = progress.total;
  const pct = total > 0 ? (done / total) * 100 : 0;

  const phaseLabel = {
    idle: "Ready",
    scripting: "Generating Script",
    generating: "Generating Clips",
    stitching: "Stitching Video",
    done: "Complete",
  }[phase];

  const phaseColour = {
    idle: "#8888aa",
    scripting: "#a78bfa",
    generating: "#ffb830",
    stitching: "#38bdf8",
    done: "#00ff9d",
  }[phase];

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0a0a14",
      color: "#e0e0f0",
      fontFamily: "'DM Sans', system-ui, sans-serif",
      padding: "32px 24px",
      maxWidth: 960,
      margin: "0 auto",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; }
        @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(1.4)} }
        @keyframes glow { 0%,100%{box-shadow:0 0 4px #ffb83088} 50%{box-shadow:0 0 14px #ffb830cc} }
        @keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
        input, select { outline: none; }
        input:focus, select:focus { border-color: #a78bfa !important; }
        ::-webkit-scrollbar { width: 4px; } 
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #ffffff22; border-radius: 2px; }
      `}</style>

      {/* Header */}
      <div style={{ marginBottom: 36 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "linear-gradient(135deg, #a78bfa, #38bdf8)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 18,
          }}>⚡</div>
          <div>
            <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.5px" }}>
              AI Video Pipeline
            </div>
            <div style={{ fontSize: 12, color: "#8888aa", marginTop: 1 }}>
              Claude · Kling v2-master · ElevenLabs · ffmpeg
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            <StatusDot status={running ? "generating" : phase === "done" ? "done" : "pending"} />
            <span style={{ fontSize: 12, color: phaseColour, fontWeight: 500 }}>{phaseLabel}</span>
          </div>
        </div>
      </div>

      {/* Input Row */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr auto auto", gap: 10, marginBottom: 24
      }}>
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Video topic — e.g. 'The rise of AI in 2025'"
          disabled={running}
          onKeyDown={(e) => e.key === "Enter" && !running && simulatePipeline()}
          style={{
            background: "#12121e",
            border: "1px solid #ffffff18",
            borderRadius: 10,
            padding: "12px 16px",
            color: "#e0e0f0",
            fontSize: 14,
            transition: "border-color 0.2s",
          }}
        />
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          disabled={running}
          style={{
            background: "#12121e",
            border: "1px solid #ffffff18",
            borderRadius: 10,
            padding: "12px 14px",
            color: "#e0e0f0",
            fontSize: 13,
            cursor: "pointer",
            minWidth: 160,
          }}
        >
          {STYLES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          onClick={simulatePipeline}
          disabled={running || !topic.trim()}
          style={{
            background: running ? "#1e1e2e" : "linear-gradient(135deg, #a78bfa, #7c3aed)",
            border: "none",
            borderRadius: 10,
            padding: "12px 24px",
            color: running ? "#8888aa" : "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: running ? "default" : "pointer",
            transition: "all 0.2s",
            letterSpacing: "0.3px",
            fontFamily: "inherit",
          }}
        >
          {running ? "Running…" : "▶ Run"}
        </button>
      </div>

      {/* Stats Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 20 }}>
        {[
          { label: "Scenes Done", value: `${done} / ${total}`, colour: "#00ff9d" },
          { label: "Progress", value: `${Math.round(pct)}%`, colour: "#a78bfa" },
          { label: "Elapsed", value: fmtTime(elapsedSecs), colour: "#38bdf8" },
          { label: "Est. Remaining", value: estMinutes ? `~${estMinutes}m` : "—", colour: "#ffb830" },
        ].map(({ label, value, colour }) => (
          <div key={label} style={{
            background: "#12121e",
            border: "1px solid #ffffff0f",
            borderRadius: 10,
            padding: "14px 16px",
          }}>
            <div style={{ fontSize: 11, color: "#8888aa", marginBottom: 4, letterSpacing: "0.5px", textTransform: "uppercase" }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 600, color: colour, fontFamily: "'DM Mono', monospace" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Progress Bar */}
      <div style={{ marginBottom: 20 }}>
        <div style={{
          height: 6, background: "#ffffff0a", borderRadius: 3, overflow: "hidden"
        }}>
          <div style={{
            height: "100%",
            width: `${pct}%`,
            background: phase === "done"
              ? "linear-gradient(90deg, #00ff9d, #38bdf8)"
              : "linear-gradient(90deg, #a78bfa, #38bdf8)",
            borderRadius: 3,
            transition: "width 0.4s ease",
            backgroundSize: "200% 100%",
            animation: running && phase === "generating" ? "shimmer 2s linear infinite" : "none",
          }} />
        </div>
      </div>

      {/* Scene Grid */}
      <div style={{
        background: "#12121e",
        border: "1px solid #ffffff0f",
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
      }}>
        <div style={{ fontSize: 11, color: "#8888aa", marginBottom: 10, letterSpacing: "0.5px", textTransform: "uppercase" }}>
          Scene Map — 60 clips × 10s = 10 min
        </div>
        <SceneGrid scenes={scenes} />
        <div style={{ display: "flex", gap: 16, marginTop: 12 }}>
          {[["done","#00ff9d","Complete"],["generating","#ffb830","Generating"],["pending","#ffffff22","Pending"],["failed","#ff3d3d","Failed"]].map(([s,c,l]) => (
            <div key={s} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "#8888aa" }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: c }} />
              {l}
            </div>
          ))}
        </div>
      </div>

      {/* Pipeline Steps */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, marginBottom: 16 }}>
        {[
          { id: "scripting", icon: "✍️", label: "Script", sub: "Claude" },
          { id: "generating", icon: "🎬", label: "Clips", sub: "Kling AI" },
          { id: "chaining", icon: "🔗", label: "Frame Chain", sub: "last→first" },
          { id: "stitching", icon: "🎙️", label: "Voiceover", sub: "ElevenLabs" },
          { id: "done", icon: "🎞️", label: "Stitch", sub: "ffmpeg" },
        ].map(({ id, icon, label, sub }) => {
          const isActive = phase === id;
          const isDone = ["scripting","generating","stitching","done"].indexOf(phase) >
                         ["scripting","generating","stitching","done"].indexOf(id);
          return (
            <div key={id} style={{
              background: isActive ? "#1e1230" : "#12121e",
              border: `1px solid ${isActive ? "#a78bfa55" : "#ffffff0f"}`,
              borderRadius: 10,
              padding: "12px 10px",
              textAlign: "center",
              transition: "all 0.3s",
            }}>
              <div style={{ fontSize: 20, marginBottom: 4 }}>{icon}</div>
              <div style={{ fontSize: 12, fontWeight: 500, color: isActive ? "#a78bfa" : isDone ? "#00ff9d" : "#8888aa" }}>{label}</div>
              <div style={{ fontSize: 10, color: "#8888aa55", marginTop: 2 }}>{sub}</div>
            </div>
          );
        })}
      </div>

      {/* Log Console */}
      <div style={{
        background: "#0d0d18",
        border: "1px solid #ffffff0f",
        borderRadius: 12,
        padding: 16,
        height: 200,
        overflowY: "auto",
      }}>
        <div style={{ fontSize: 11, color: "#8888aa", marginBottom: 10, letterSpacing: "0.5px", textTransform: "uppercase", fontFamily: "'DM Mono', monospace" }}>
          ● Console
        </div>
        {logs.map((line, i) => <LogLine key={i} line={line} />)}
        <div ref={logEndRef} />
      </div>

      {/* Setup Instructions */}
      <div style={{
        marginTop: 20,
        background: "#12121e",
        border: "1px solid #ffffff0f",
        borderRadius: 12,
        padding: 16,
      }}>
        <div style={{ fontSize: 11, color: "#8888aa", marginBottom: 12, letterSpacing: "0.5px", textTransform: "uppercase" }}>
          Setup
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {[
            { step: "1", title: "Install deps", code: "pip install requests moviepy pillow python-dotenv elevenlabs" },
            { step: "2", title: "Configure .env", code: "cp .env.example .env && nano .env" },
            { step: "3", title: "Install Kling MCP (optional)", code: "npx -y mcp-kling@latest" },
            { step: "4", title: "Run pipeline", code: 'python video_pipeline.py --topic "Your topic"' },
          ].map(({ step, title, code }) => (
            <div key={step} style={{ display: "flex", gap: 10 }}>
              <div style={{
                width: 22, height: 22, borderRadius: 6,
                background: "#a78bfa22", color: "#a78bfa",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 700, flexShrink: 0,
              }}>{step}</div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 3 }}>{title}</div>
                <div style={{
                  fontFamily: "'DM Mono', monospace", fontSize: 10,
                  color: "#38bdf8", background: "#0a0a14",
                  padding: "4px 8px", borderRadius: 5,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  maxWidth: 320,
                }} title={code}>{code}</div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid #ffffff08", fontSize: 12, color: "#8888aa", lineHeight: 1.6 }}>
          <strong style={{ color: "#e0e0f0" }}>How frame chaining works:</strong> After each clip is generated, the pipeline extracts the last frame using ffmpeg, uploads it as a temporary URL, then passes it as the <code style={{ color: "#38bdf8", background: "#0a0a14", padding: "1px 5px", borderRadius: 3 }}>image</code> parameter to the next Kling call — keeping character, lighting, and scene consistent across all 60 clips.
        </div>
      </div>
    </div>
  );
}

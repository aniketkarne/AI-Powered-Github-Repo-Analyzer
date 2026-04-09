import React, { useState } from "react";
import axios from "axios";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from "chart.js";
import { Bar, Pie } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

function App() {
  const [username, setUsername] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const analyze = async () => {
    if (!username.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(`${API_BASE}/api/profile/${username.trim()}`);
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || "Failed to fetch profile");
    } finally {
      setLoading(false);
    }
  };

  const langData = data
    ? {
        labels: data.language_breakdown.map((l) => l.language),
        datasets: [
          {
            data: data.language_breakdown.map((l) => l.count),
            backgroundColor: [
              "#58a6ff","#f0e68c","#ff6b6b","#69f0ae","#ff9f43",
              "#ab47bc","#26c6da","#ffee58","#8d6e63","#78909c",
            ],
          },
        ],
      }
    : null;

  const starData = data
    ? {
        labels: data.star_trend.slice(0, 10).map((r) => r.repo),
        datasets: [
          {
            label: "Stars",
            data: data.star_trend.slice(0, 10).map((r) => r.stars),
            backgroundColor: "#f0e68c",
          },
        ],
      }
    : null;

  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ textAlign: "center" }}>GitHub Repo Analyzer</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: "2rem" }}>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && analyze()}
          placeholder="GitHub username..."
          style={{ flex: 1, padding: "10px 14px", fontSize: 16, borderRadius: 8, border: "1px solid #ccc" }}
        />
        <button
          onClick={analyze}
          disabled={loading}
          style={{ padding: "10px 24px", fontSize: 16, borderRadius: 8, border: "none", background: "#58a6ff", color: "#fff", cursor: loading ? "not-allowed" : "pointer" }}
        >
          {loading ? "Loading..." : "Analyze"}
        </button>
      </div>

      {error && (
        <div style={{ color: "red", textAlign: "center", marginBottom: "1rem" }}>{error}</div>
      )}

      {data && (
        <>
          {/* Profile Header */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: "2rem", padding: "1rem", border: "1px solid #eee", borderRadius: 12 }}>
            <img src={data.profile.avatar_url} alt="avatar" width={64} height={64} style={{ borderRadius: "50%" }} />
            <div>
              <h2 style={{ margin: 0 }}>{data.profile.name || data.profile.login}</h2>
              <p style={{ margin: "4px 0 0", color: "#666" }}>@{data.profile.login}</p>
              {data.profile.bio && <p style={{ margin: "4px 0 0", fontSize: 14 }}>{data.profile.bio}</p>}
              <p style={{ margin: "4px 0 0", fontSize: 14, color: "#666" }}>
                {data.profile.followers} followers · {data.profile.following} following · {data.profile.public_repos} public repos
              </p>
            </div>
          </div>

          {/* Charts row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: "2rem" }}>
            <div style={{ border: "1px solid #eee", borderRadius: 12, padding: "1rem" }}>
              <h3 style={{ marginTop: 0 }}>Language Breakdown</h3>
              {langData && langData.labels.length > 0 ? (
                <Pie data={langData} options={{ responsive: true, plugins: { legend: { position: "bottom" } } }} />
              ) : (
                <p style={{ color: "#999" }}>No language data</p>
              )}
            </div>
            <div style={{ border: "1px solid #eee", borderRadius: 12, padding: "1rem" }}>
              <h3 style={{ marginTop: 0 }}>Top 10 Starred Repos</h3>
              {starData ? (
                <Bar data={starData} options={{ responsive: true, plugins: { legend: { display: false } }, indexAxis: "y" }} />
              ) : (
                <p style={{ color: "#999" }}>No star data</p>
              )}
            </div>
          </div>

          {/* Repo list */}
          <h3>All Repositories ({data.repos.length})</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {data.repos.map((repo) => (
              <div key={repo.name} style={{ padding: "10px 14px", border: "1px solid #eee", borderRadius: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <strong>{repo.name}</strong>
                  <span style={{ color: "#666", fontSize: 14 }}>
                    ⭐ {repo.stars} · 🍴 {repo.forks}
                    {repo.language && <span> · {repo.language}</span>}
                  </span>
                </div>
                {repo.description && <p style={{ margin: "4px 0 0", fontSize: 13, color: "#555" }}>{repo.description}</p>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default App;

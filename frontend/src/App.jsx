import { useEffect, useMemo, useState } from "react";
import { initializeApp, getApps } from "firebase/app";
import {
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
} from "firebase/auth";
import "./App.css";

const runtimeConfig = window.RUNTIME_CONFIG;
const firebaseApp =
  runtimeConfig?.firebase && getApps().length === 0
    ? initializeApp(runtimeConfig.firebase)
    : getApps()[0];
const auth = firebaseApp ? getAuth(firebaseApp) : null;
const apiBaseUrl = runtimeConfig?.apiBaseUrl
  ? runtimeConfig.apiBaseUrl.replace(/\/$/, "")
  : null;

function App() {
  const [user, setUser] = useState(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authStatus, setAuthStatus] = useState("");

  const [workflows, setWorkflows] = useState([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState("");

  const [pendingInputs, setPendingInputs] = useState([]);
  const [noteText, setNoteText] = useState("");
  const [submitStatus, setSubmitStatus] = useState("");

  const [executions, setExecutions] = useState([]);
  const [outputStatus, setOutputStatus] = useState("");
  const [details, setDetails] = useState({});
  const [expanded, setExpanded] = useState({});

  const [filterWorkflowId, setFilterWorkflowId] = useState("");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");
  const [filterLimit, setFilterLimit] = useState(50);

  useEffect(() => {
    if (!auth) return;
    const unsubscribe = onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
    });
    return () => unsubscribe();
  }, []);

  useEffect(() => {
    if (!user) {
      setWorkflows([]);
      setExecutions([]);
      setSelectedWorkflowId("");
      return;
    }
    fetchWorkflows();
    refreshOutputs();
  }, [user]);

  useEffect(() => {
    if (!user) return;
    refreshOutputs();
  }, [filterWorkflowId, filterFrom, filterTo, filterLimit, user]);

  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.id === selectedWorkflowId),
    [workflows, selectedWorkflowId]
  );

  const apiFetch = async (path, options = {}) => {
    if (!user) {
      throw new Error("Sign in to continue.");
    }
    if (!apiBaseUrl) {
      throw new Error("Missing apiBaseUrl in config.js.");
    }
    const token = await user.getIdToken();
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(`${apiBaseUrl}${path}`, { ...options, headers });
  };

  const fetchWorkflows = async () => {
    try {
      const response = await apiFetch("/api/workflows");
      if (!response.ok) {
        throw new Error("Failed to load workflows.");
      }
      const data = await response.json();
      setWorkflows(data);
      if (!selectedWorkflowId && data.length) {
        setSelectedWorkflowId(data[0].id);
      }
    } catch (error) {
      setOutputStatus(error.message);
    }
  };

  const refreshOutputs = async () => {
    setOutputStatus("Loading outputs...");
    const params = new URLSearchParams();
    if (filterWorkflowId) params.append("workflow_id", filterWorkflowId);
    if (filterFrom) params.append("processed_from", filterFrom);
    if (filterTo) params.append("processed_to", filterTo);
    if (filterLimit) params.append("limit", filterLimit);

    try {
      const response = await apiFetch(`/api/executions?${params.toString()}`);
      if (!response.ok) {
        throw new Error("Failed to load outputs.");
      }
      const data = await response.json();
      setExecutions(data);
      setOutputStatus(data.length ? "" : "No executions yet.");
    } catch (error) {
      setOutputStatus(error.message);
    }
  };

  const handleFileChange = (event) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setPendingInputs((prev) => [
      ...prev,
      ...files.map((file) => ({
        file,
        name: file.name,
        type: "File upload",
        status: "pending",
      })),
    ]);
    event.target.value = "";
  };

  const handleAddTextNote = () => {
    setSubmitStatus("");
    if (!noteText.trim()) {
      setSubmitStatus("Paste note text before adding.");
      return;
    }
    const filename = `note-${Date.now()}.txt`;
    const file = new File([noteText.trim()], filename, {
      type: "text/plain",
    });
    setPendingInputs((prev) => [
      ...prev,
      { file, name: filename, type: "Text input", status: "pending" },
    ]);
    setNoteText("");
  };

  const submitNotes = async () => {
    setSubmitStatus("");
    if (!selectedWorkflowId) {
      setSubmitStatus("Select a workflow first.");
      return;
    }
    if (!pendingInputs.length) {
      setSubmitStatus("Add at least one note.");
      return;
    }

    const form = new FormData();
    form.append("workflow_id", selectedWorkflowId);
    pendingInputs.forEach((item) => {
      form.append("notes", item.file, item.file.name);
    });

    setPendingInputs((prev) =>
      prev.map((item) => ({ ...item, status: "submitted" }))
    );

    try {
      const response = await apiFetch("/api/executions", {
        method: "POST",
        body: form,
      });
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText || "Submission failed.");
      }
      setSubmitStatus("Submitted. Background processing started.");
      setPendingInputs([]);
      refreshOutputs();
    } catch (error) {
      setSubmitStatus(error.message);
    }
  };

  const loadDetails = async (executionId) => {
    if (details[executionId]) return;
    setDetails((prev) => ({
      ...prev,
      [executionId]: { loading: true },
    }));
    try {
      const response = await apiFetch(`/api/executions/${executionId}`);
      if (!response.ok) {
        throw new Error("Failed to load output detail.");
      }
      const data = await response.json();
      setDetails((prev) => ({
        ...prev,
        [executionId]: { loading: false, data },
      }));
    } catch (error) {
      setDetails((prev) => ({
        ...prev,
        [executionId]: { loading: false, error: error.message },
      }));
    }
  };

  const toggleDetails = (executionId) => {
    setExpanded((prev) => {
      const next = !prev[executionId];
      if (next) loadDetails(executionId);
      return { ...prev, [executionId]: next };
    });
  };

  const handleSignIn = async (event) => {
    event.preventDefault();
    setAuthStatus("");
    if (!auth) {
      setAuthStatus("Firebase is not configured.");
      return;
    }
    try {
      await signInWithEmailAndPassword(auth, authEmail, authPassword);
    } catch (error) {
      setAuthStatus(getAuthErrorMessage(error, { action: "sign-in" }));
    }
  };

  const handleCreateAccount = async () => {
    setAuthStatus("");
    if (!auth) {
      setAuthStatus("Firebase is not configured.");
      return;
    }
    try {
      await createUserWithEmailAndPassword(auth, authEmail, authPassword);
    } catch (error) {
      setAuthStatus(getAuthErrorMessage(error, { action: "sign-up" }));
    }
  };

  const handleSignOut = async () => {
    if (!auth) return;
    await signOut(auth);
  };

  if (!runtimeConfig) {
    return (
      <div className="app-shell">
        <div className="card">
          <h2>Missing config</h2>
          <p>
            Copy <code>frontend/public/config.js.example</code> to{" "}
            <code>frontend/public/config.js</code> and fill it in.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">DoctusTech</p>
          <h1>Workflow Console</h1>
        </div>
        {user && (
          <div className="auth-chip">
            <span>{user.email || "Signed in"}</span>
            <button className="ghost" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        )}
      </header>

      {!user && (
        <section className="card">
          <h2>Secure Access</h2>
          <p className="muted">
            Sign in to run workflows, upload notes, and view outputs.
          </p>
          <form className="stack" onSubmit={handleSignIn}>
            <label>
              Email
              <input
                type="email"
                value={authEmail}
                onChange={(event) => setAuthEmail(event.target.value)}
                placeholder="you@clinic.com"
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
                placeholder="********"
                required
              />
            </label>
            <div className="button-row">
              <button type="submit" className="primary">
                Sign in
              </button>
              <button type="button" className="ghost" onClick={handleCreateAccount}>
                Create account
              </button>
            </div>
            {authStatus && <p className="status-message">{authStatus}</p>}
          </form>
        </section>
      )}

      {user && (
        <>
          <section className="card">
            <div className="section-header">
              <h2>Workflows</h2>
              <p className="muted">Choose the workflow you want to run.</p>
            </div>
            <div className="workflow-list">
              {workflows.map((workflow) => (
                <div
                  className={`workflow-card ${
                    workflow.id === selectedWorkflowId ? "active" : ""
                  }`}
                  key={workflow.id}
                >
                  <strong>{workflow.name}</strong>
                  <span className="muted">{workflow.description}</span>
                  <div className="input-tags">
                    {(workflow.inputs || []).map((input) => (
                      <span className="input-tag" key={input.name}>
                        {input.name} ({input.type}
                        {input.multiple ? ", multiple" : ""})
                      </span>
                    ))}
                  </div>
                  <button
                    className="ghost"
                    onClick={() => setSelectedWorkflowId(workflow.id)}
                  >
                    Select workflow
                  </button>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="section-header">
              <h2>Inputs</h2>
              <p className="muted">Upload progress notes or paste text.</p>
            </div>
            <div className="stack">
              <label className="file-input">
                <input type="file" multiple onChange={handleFileChange} />
                <span>Select files</span>
              </label>
              <label>
                Paste note text
                <textarea
                  rows="5"
                  value={noteText}
                  onChange={(event) => setNoteText(event.target.value)}
                  placeholder="Assessment/Plan..."
                />
              </label>
              <div className="button-row">
                <button type="button" className="ghost" onClick={handleAddTextNote}>
                  Add text note
                </button>
                <button type="button" className="primary" onClick={submitNotes}>
                  Submit to workflow
                </button>
              </div>
              {selectedWorkflow && (
                <p className="muted">
                  Selected: <strong>{selectedWorkflow.name}</strong>
                </p>
              )}
              <div className="note-list">
                {pendingInputs.map((item, index) => (
                  <div className="note-item" key={`${item.name}-${index}`}>
                    <div>
                      <strong>{item.name}</strong>
                      <div className="muted">{item.type}</div>
                    </div>
                    <span className={`status ${item.status}`}>{item.status}</span>
                  </div>
                ))}
              </div>
              {submitStatus && <p className="status-message">{submitStatus}</p>}
            </div>
          </section>

          <section className="card wide">
            <div className="section-header">
              <div>
                <h2>Outputs</h2>
                <p className="muted">Track completed runs and inspect outputs.</p>
              </div>
              <button className="ghost" onClick={refreshOutputs}>
                Refresh
              </button>
            </div>
            <div className="filters">
              <label>
                Workflow
                <select
                  value={filterWorkflowId}
                  onChange={(event) => setFilterWorkflowId(event.target.value)}
                >
                  <option value="">All</option>
                  {workflows.map((workflow) => (
                    <option key={workflow.id} value={workflow.id}>
                      {workflow.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Processed from
                <input
                  type="date"
                  value={filterFrom}
                  onChange={(event) => setFilterFrom(event.target.value)}
                />
              </label>
              <label>
                Processed to
                <input
                  type="date"
                  value={filterTo}
                  onChange={(event) => setFilterTo(event.target.value)}
                />
              </label>
              <label>
                Limit
                <input
                  type="number"
                  min="1"
                  max="200"
                  value={filterLimit}
                  onChange={(event) => setFilterLimit(Number(event.target.value))}
                />
              </label>
            </div>
            <div className="output-list">
              {executions.map((exec) => {
                const processedAt = exec.processed_at
                  ? new Date(exec.processed_at).toLocaleString()
                  : "Pending";
                const inputName =
                  exec.input_ref?.filename || exec.note_id || exec.id;
                const detailState = details[exec.id] || {};
                return (
                  <div className="output-item" key={exec.id}>
                    <h3>{inputName}</h3>
                    <div className="output-meta">
                      <span>{exec.workflow_name || exec.workflow_id}</span>
                      <span>Status: {exec.status}</span>
                      <span>{processedAt}</span>
                    </div>
                    <button
                      className="ghost"
                      onClick={() => toggleDetails(exec.id)}
                    >
                      {expanded[exec.id] ? "Hide details" : "View details"}
                    </button>
                    {expanded[exec.id] && (
                      <div className="detail-panel">
                        {detailState.loading && (
                          <p className="muted">Loading details...</p>
                        )}
                        {detailState.error && (
                          <p className="muted">{detailState.error}</p>
                        )}
                        {detailState.data && (
                          <OutputDetail
                            output={detailState.data.output}
                            error={detailState.data.error}
                          />
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {outputStatus && <p className="status-message">{outputStatus}</p>}
          </section>
        </>
      )}

      <footer className="footer">
        Built for DoctusTech Technical Test.
      </footer>
    </div>
  );
}

function getAuthErrorMessage(error, { action }) {
  const code = error?.code || "";
  const defaultMessage =
    action === "sign-up"
      ? "Sign-up failed. Please try again."
      : "Sign-in failed. Please try again.";

  switch (code) {
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "Incorrect email or password.";
    case "auth/invalid-email":
      return "Please enter a valid email address.";
    case "auth/user-disabled":
      return "This account has been disabled. Contact support.";
    case "auth/email-already-in-use":
      return "That email is already registered. Try signing in.";
    case "auth/weak-password":
      return "Password is too weak. Use at least 6 characters.";
    case "auth/too-many-requests":
      return "Too many attempts. Try again in a few minutes.";
    case "auth/network-request-failed":
      return "Network error. Check your connection and try again.";
    default:
      return defaultMessage;
  }
}

function OutputDetail({ output, error }) {
  if (!output) {
    return <p className="muted">{error || "Processing not complete yet."}</p>;
  }
  const conditions = output.conditions || [];
  return (
    <div className="output-detail">
      <strong>Assessment Plan</strong>
      <pre>{output.assessment_plan || "N/A"}</pre>
      <strong>Conditions</strong>
      <div className="condition-grid">
        {conditions.map((condition, index) => (
          <div className="condition-item" key={`${condition.condition}-${index}`}>
            <strong>{condition.condition || "Unknown"}</strong>
            <div>{condition.icd10_code || "No ICD-10"}</div>
            <div className="muted">{condition.icd10_description || ""}</div>
            <div className="muted">
              HCC:{" "}
              {condition.hcc_match
                ? `${condition.hcc_match.code} ${condition.hcc_match.description}`
                : "N/A"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;

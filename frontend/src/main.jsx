import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

const API_URL = (
  import.meta.env.VITE_API_URL || "/api"
).replace(/\/$/, "");
const sessionId = `s-${crypto.randomUUID()}`;

function App() {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState(null);
  const tail = useRef(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ status: "offline" }));
  }, []);
  useEffect(() => {
    const element = tail.current;
    if (typeof element?.scrollIntoView === "function") {
      element.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [messages, busy]);

  async function send(event) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;
    setDraft("");
    setMessages((current) => [
      ...current,
      { role: "user", content: message },
      { role: "pending", content: "" },
    ]);
    setBusy(true);
    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          ...(systemPrompt.trim()
            ? { system_prompt: systemPrompt.trim() }
            : {}),
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw new Error(
          data.detail ||
            "The assistant is temporarily unavailable. Please try again.",
        );
      setMessages((current) => [
        ...current.slice(0, -1),
        { role: "assistant", content: data.reply, metadata: data.metadata },
      ]);
    } catch (error) {
      setMessages((current) => [
        ...current.slice(0, -1),
        {
          role: "error",
          content: error.message || "Could not connect to the assistant.",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="#">
          <span className="brand-mark">L</span>
          <span>
            lyftr<span className="brand-ai">.ai</span>
          </span>
        </a>
        <div className="status">
          <i className={health?.status === "ok" ? "online" : ""} />
          {health?.status === "ok"
            ? "Systems ready"
            : health?.status === "offline"
              ? "Backend offline"
              : "Connecting"}
        </div>
      </header>
      <section className="hero">
        <div className="eyebrow">
          <span /> RESILIENT AI CHAT
        </div>
        <h1>
          A clearer way to
          <br />
          <em>think things through.</em>
        </h1>
        <p>
          Ask anything. Your assistant keeps context, rides through provider
          hiccups, and remembers the details that matter.
        </p>
      </section>
      <section className="chat-card" aria-label="Chat conversation">
        <div className="card-head">
          <div>
            <div className="card-title">Your conversation</div>
            <div className="card-subtitle">
              Private session <span>·</span> Context-aware
            </div>
          </div>
          <div className="session-icon">✳</div>
        </div>
        <div className="conversation" aria-live="polite">
          {messages.length === 0 && (
            <div className="welcome">
              <div className="welcome-icon">✳</div>
              <strong>What’s on your mind?</strong>
              <span>Start anywhere. I’ll keep up.</span>
              <div className="suggestions">
                <button
                  onClick={() => setDraft("Help me plan a productive week")}
                >
                  Plan my week <span>↗</span>
                </button>
                <button
                  onClick={() => setDraft("Explain a tricky idea simply")}
                >
                  Make an idea clearer <span>↗</span>
                </button>
              </div>
            </div>
          )}
          {messages.map((message, index) =>
            message.role === "user" ? (
              <div className="user-row" key={index}>
                <div className="user-bubble">{message.content}</div>
              </div>
            ) : message.role === "pending" ? (
              <div className="assistant-row" key={index}>
                <div className="assistant-avatar">✳</div>
                <div className="loading">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : message.role === "error" ? (
              <div className="error-message" key={index}>
                <span>!</span>
                {message.content}
              </div>
            ) : (
              <div className="assistant-row" key={index}>
                <div className="assistant-avatar">✳</div>
                <article
                  className="assistant-message"
                  data-testid="assistant-message"
                >
                  <div className="reply-text">{message.content}</div>
                  <div className="metadata">
                    <span
                      className={`source ${message.metadata.resolution_source === "LLM_CACHE" ? "cached" : ""}`}
                      data-testid="meta-source"
                    >
                      <i />
                      {message.metadata.resolution_source}
                    </span>
                    <span className="meta-item">
                      <b>MODEL</b>
                      <span data-testid="meta-model">
                        {message.metadata.model}
                      </span>
                    </span>
                    <span className="meta-item">
                      <b>TIME</b>
                      <span data-testid="meta-latency">
                        {message.metadata.latency_ms} ms
                      </span>
                    </span>
                    <span className="meta-item">
                      <b>INPUT</b>
                      <span data-testid="meta-input-tokens">
                        {message.metadata.input_tokens}
                      </span>
                    </span>
                    <span className="meta-item">
                      <b>OUTPUT</b>
                      <span data-testid="meta-output-tokens">
                        {message.metadata.output_tokens}
                      </span>
                    </span>
                  </div>
                </article>
              </div>
            ),
          )}
          <div ref={tail} />
        </div>
        <form className="composer" onSubmit={send}>
          <div className="input-shell">
            <textarea
              data-testid="chat-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Write a message..."
              rows="1"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <button
              data-testid="send-button"
              className="send-button"
              type="submit"
              disabled={busy || !draft.trim()}
              aria-label="Send message"
            >
              {busy ? (
                <span className="send-spinner" />
              ) : (
                <svg viewBox="0 0 20 20" aria-hidden="true">
                  <path d="M3.5 10h12m-5-5 5 5-5 5" />
                </svg>
              )}
            </button>
          </div>
          <div className="composer-foot">
            <label className="prompt-toggle">
              <span className="sparkle">✳</span>
              <span>System prompt</span>
              <input
                data-testid="system-prompt-input"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                placeholder="Optional session instructions"
              />
            </label>
            <span className="enter-hint">
              ENTER TO SEND <kbd>↵</kbd>
            </span>
          </div>
        </form>
      </section>
      <footer>
        <span>Thoughtful answers, built to keep going.</span>
        <span>
          POWERED BY LYFTR AI <b>✳</b>
        </span>
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

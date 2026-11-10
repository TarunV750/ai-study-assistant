import { useCallback, useEffect, useMemo, useState } from "react";
import { askQuestion, createStudyMaterial, getDocument, listDocuments, uploadPdf } from "./api.js";

const STUDY_MODES = [
  ["summary", "Summary"], ["key-concepts", "Key concepts"],
  ["questions", "Practice questions"], ["study-guide", "Study guide"],
];

const statusLabel = (status) => ({ uploaded: "Processing", processing: "Processing", extracted: "Creating embeddings", embedded: "Indexing", indexed: "Ready", failed: "Needs attention" }[status] || status);

export default function App() {
  const [documents, setDocuments] = useState([]);
  const [selected, setSelected] = useState([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([{ role: "assistant", text: "Upload a course PDF, select it, and ask a question. I’ll answer from your materials and show the sources." }]);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadProgress, setUploadProgress] = useState(null);
  const [studyMode, setStudyMode] = useState("summary");
  const [studyOutput, setStudyOutput] = useState(null);

  const refresh = useCallback(async () => {
    try { const data = await listDocuments(); setDocuments(data.documents || []); }
    catch (error) { setNotice(error.message); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const readyDocuments = useMemo(() => documents.filter((doc) => doc.status === "indexed"), [documents]);

  async function handleUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("upload"); setNotice(""); setUploadProgress(0);
    try {
      const result = await uploadPdf(file, setUploadProgress);
      setNotice(`${file.name} uploaded. We’re preparing it for search.`);
      for (let attempt = 0; attempt < 60; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5000));
        const doc = await getDocument(result.documentId);
        if (["indexed", "failed"].includes(doc.status)) break;
      }
      await refresh();
    } catch (error) { setNotice(error.message); }
    finally { setBusy(""); setUploadProgress(null); event.target.value = ""; }
  }

  function toggleDocument(id) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function submitQuestion(event) {
    event.preventDefault();
    if (!question.trim()) return;
    const asked = question.trim();
    setQuestion(""); setMessages((current) => [...current, { role: "user", text: asked }]); setBusy("ask"); setNotice("");
    try {
      const result = await askQuestion(asked, selected);
      setMessages((current) => [...current, { role: "assistant", text: result.answer, sources: result.sources || [] }]);
    } catch (error) { setNotice(error.message); }
    finally { setBusy(""); }
  }

  async function generateStudyMaterial() {
    setBusy("study"); setNotice("");
    try { setStudyOutput(await createStudyMaterial({ mode: studyMode, documentIds: selected, count: 8, questionType: "mixed" })); }
    catch (error) { setNotice(error.message); }
    finally { setBusy(""); }
  }

  return <div className="app-shell">
    <header><a className="brand" href="#top"><span>CL</span> CourseLens <b>AI</b></a><div className="privacy">Private S3 storage · source-grounded answers</div></header>
    <main id="top">
      <section className="hero"><div><p className="eyebrow">Your course material, made conversational</p><h1>Study with answers you can <em>trace.</em></h1><p className="lede">Turn course PDFs into searchable knowledge, clear explanations, focused summaries, and practice questions—every answer tied to a page.</p></div><label className={`upload-card ${busy === "upload" ? "working" : ""}`}><input type="file" accept="application/pdf,.pdf" onChange={handleUpload} disabled={Boolean(busy)} /><span className="upload-icon">↑</span><strong>{busy === "upload" ? `Uploading ${uploadProgress ?? 100}%` : "Add a course PDF"}</strong><small>PDF only · up to 10 MiB</small>{uploadProgress !== null && <i style={{ width: `${uploadProgress}%` }} />}</label></section>
      {notice && <div className="notice" role="status">{notice}<button onClick={() => setNotice("")} aria-label="Dismiss">×</button></div>}
      <section className="workspace">
        <aside><div className="section-title"><div><p className="eyebrow">Library</p><h2>Your sources</h2></div><button className="icon-button" onClick={refresh} aria-label="Refresh">↻</button></div>
          <div className="document-list">{documents.length === 0 ? <div className="empty"><span>PDF</span><p>Your uploaded documents will appear here.</p></div> : documents.map((doc) => <button key={doc.documentId} className={`document ${selected.includes(doc.documentId) ? "selected" : ""}`} onClick={() => doc.status === "indexed" && toggleDocument(doc.documentId)} disabled={doc.status !== "indexed"}><span className="file-icon">PDF</span><span><strong>{doc.fileName || doc.originalFilename || "Course document"}</strong><small>{statusLabel(doc.status)}</small></span><i>{selected.includes(doc.documentId) ? "✓" : ""}</i></button>)}</div>
          <p className="selection-note">{selected.length ? `${selected.length} source${selected.length > 1 ? "s" : ""} selected` : `${readyDocuments.length} ready · no filter selected`}</p>
        </aside>
        <section className="chat-panel"><div className="panel-heading"><div><p className="eyebrow">Ask</p><h2>Source-grounded chat</h2></div><span className="live-dot">Bedrock</span></div>
          <div className="messages">{messages.map((message, index) => <article key={index} className={`message ${message.role}`}><span className="avatar">{message.role === "user" ? "You" : "AI"}</span><div><p>{message.text}</p>{message.sources?.length > 0 && <div className="sources">{message.sources.map((source) => <span key={source.chunkId}>Source {source.sourceNumber} · {source.filename || "PDF"} p. {source.pageNumber}</span>)}</div>}</div></article>)}{busy === "ask" && <article className="message assistant"><span className="avatar">AI</span><div className="thinking"><i /><i /><i /></div></article>}</div>
          <form className="ask-form" onSubmit={submitQuestion}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about a concept, definition, or example…" maxLength={2000} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form.requestSubmit(); } }} /><button disabled={Boolean(busy) || !question.trim()}>Ask →</button></form>
        </section>
      </section>
      <section className="study-section"><div className="section-title"><div><p className="eyebrow">Study tools</p><h2>Build your next study session</h2></div><p>Generated only from the sources you choose.</p></div><div className="study-controls"><div>{STUDY_MODES.map(([value, label]) => <button key={value} className={studyMode === value ? "active" : ""} onClick={() => setStudyMode(value)}>{label}</button>)}</div><button className="generate" onClick={generateStudyMaterial} disabled={Boolean(busy) || readyDocuments.length === 0}>{busy === "study" ? "Generating…" : "Generate"}</button></div>{studyOutput && <article className="study-output"><p className="eyebrow">{studyOutput.title}</p><div>{studyOutput.content}</div>{studyOutput.sources?.length > 0 && <p className="source-line">Based on {studyOutput.sources.length} retrieved source passages.</p>}</article>}</section>
    </main><footer><span>CourseLens AI</span><p>Built on AWS · Answers remain grounded in your uploaded material.</p></footer>
  </div>;
}

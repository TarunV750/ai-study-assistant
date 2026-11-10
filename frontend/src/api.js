const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const MAX_PDF_BYTES = 10 * 1024 * 1024;

async function request(path, options = {}) {
  if (!API_BASE_URL) throw new Error("Set VITE_API_BASE_URL before using the app.");
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status}).`);
  return payload;
}

export function validatePdf(file) {
  if (!file) throw new Error("Choose a PDF first.");
  if (file.type !== "application/pdf" || !file.name.toLowerCase().endsWith(".pdf")) throw new Error("Only PDF files are accepted.");
  if (file.size <= 0 || file.size > MAX_PDF_BYTES) throw new Error("PDF must be between 1 byte and 10 MiB.");
}

export async function uploadPdf(file, onProgress) {
  validatePdf(file);
  const instruction = await request("/upload-url", { method: "POST", body: JSON.stringify({ filename: file.name, fileSize: file.size, contentType: file.type }) });
  await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", instruction.upload.url);
    xhr.upload.onprogress = (event) => event.lengthComputable && onProgress?.(Math.round((event.loaded / event.total) * 100));
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error("S3 rejected the upload."));
    xhr.onerror = () => reject(new Error("The upload could not reach S3."));
    const form = new FormData();
    Object.entries(instruction.upload.fields).forEach(([key, value]) => form.append(key, value));
    form.append("file", file);
    xhr.send(form);
  });
  return instruction;
}

export const listDocuments = () => request("/documents");
export const getDocument = (id) => request(`/documents/${encodeURIComponent(id)}`);
export const askQuestion = (question, documentIds) => request("/ask", { method: "POST", body: JSON.stringify({ question, documentIds }) });
export const createStudyMaterial = (payload) => request("/study", { method: "POST", body: JSON.stringify(payload) });

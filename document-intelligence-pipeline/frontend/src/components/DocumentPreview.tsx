import { useEffect, useState } from "react"

import { api } from "../api/client"

type PreviewState = "loading" | "ready" | "error"

interface DocumentPreviewProps {
  documentId: string
  filename: string
  mimeType: string
}

export function DocumentPreview({ documentId, filename, mimeType }: DocumentPreviewProps) {
  const [state, setState] = useState<PreviewState>("loading")
  const url = api.fileUrl(documentId)
  const isPdf = mimeType === "application/pdf"
  const isImage = mimeType.startsWith("image/")

  useEffect(() => setState("loading"), [documentId])

  if (!isPdf && !isImage) {
    return (
      <div className="document-preview-fallback">
        <strong>Preview is not available for this file type.</strong>
        <a href={url} target="_blank" rel="noreferrer">Open original</a>
      </div>
    )
  }

  return (
    <div className={`document-preview-frame preview-${state}`} aria-busy={state === "loading"}>
      {state === "loading" ? <div className="document-preview-status">Loading original…</div> : null}
      {state === "error" ? (
        <div className="document-preview-fallback" role="alert">
          <strong>The inline preview could not be rendered.</strong>
          <a href={url} target="_blank" rel="noreferrer">Open original</a>
        </div>
      ) : null}
      {isPdf ? (
        <iframe
          key={documentId}
          title={`Original ${filename}`}
          src={`${url}#view=FitH&toolbar=0&navpanes=0`}
          onLoad={() => setState("ready")}
          onError={() => setState("error")}
        />
      ) : (
        <img
          key={documentId}
          src={url}
          alt={`Original ${filename}`}
          onLoad={() => setState("ready")}
          onError={() => setState("error")}
        />
      )}
    </div>
  )
}

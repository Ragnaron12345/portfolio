#!/bin/sh
set -eu

ensure_workflow() {
  workflow_id="$1"
  workflow_file="$2"

  # Checked-in exports are the source of truth for this reproducible demo.
  # Keep a recoverable export, unpublish the running version, replace it with
  # the current file, and restore the previous version if import fails.
  if n8n export:workflow --id="$workflow_id" --output="/tmp/$workflow_id.json" >/dev/null 2>&1; then
    echo "Refreshing workflow $workflow_id from $workflow_file..."
    n8n unpublish:workflow --id="$workflow_id"
    if ! n8n import:workflow --input="/workflows/$workflow_file"; then
      echo "Import failed; restoring the previous $workflow_id export."
      n8n import:workflow --input="/tmp/$workflow_id.json"
      n8n publish:workflow --id="$workflow_id"
      exit 1
    fi
  else
    echo "Importing $workflow_file..."
    n8n import:workflow --input="/workflows/$workflow_file"
  fi

  n8n publish:workflow --id="$workflow_id"
}

ensure_workflow "ErrHandler202609" "00-shared-error-handler.json"
ensure_workflow "SupportFlow2609" "01-ai-support-triage.json"
ensure_workflow "InvoiceFlow2609" "02-invoice-processing.json"
ensure_workflow "IncidentFlow260" "03-incident-intelligence.json"

#!/usr/bin/env sh
# Pull every Ollama generation model the app needs that isn't pulled yet
# (docs/design-rag.md §9.2).
#
# /rag/compare never pulls a model and returns 422 for one that's missing, so
# every machine the harness runs against (laptop and VM) must have each model
# already pulled. The list is:
#   - RAG_DEFAULT_MODEL, as the backend actually sees it (.env or config.py)
#   - every "generation_model" in the configs file, if it exists
#   - any extra model names given after it
#
# A model that `ollama list` already shows is never pulled again: pulling an
# existing tag updates it to the library's current build, which could change
# answers between the committed report and grading (§11.2). Updating a model
# is a deliberate manual `ollama pull`, followed by a new report.
#
# Needs only docker: the JSON is parsed by the backend container's Python.
#
# Usage (from the directory holding the compose file):
#   sh scripts/pull_models.sh eval/configs.json          # locally
#   sh pull_models.sh configs.json                       # on the VM
#   sh scripts/pull_models.sh eval/configs.json qwen2.5:3b
#
# COMPOSE overrides the compose command, e.g. COMPOSE="sudo docker compose".
set -eu

COMPOSE="${COMPOSE:-docker compose}"
CONFIGS="${1:-eval/configs.json}"
[ $# -gt 0 ] && shift

echo "==> waiting for ollama (up to 5 minutes)"
tries=0
until $COMPOSE exec -T ollama ollama list >/dev/null 2>&1 </dev/null; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "error: ollama didn't answer within 5 minutes" >&2
    exit 1
  fi
  sleep 5
done

models=$($COMPOSE exec -T backend python -c \
  "from app.config import settings; print(settings.RAG_DEFAULT_MODEL)" </dev/null)

if [ -f "$CONFIGS" ]; then
  from_configs=$($COMPOSE exec -T backend python -c '
import json, sys

def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "generation_model" and isinstance(value, str):
                yield value
            else:
                yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)

print("\n".join(sorted(set(walk(json.load(sys.stdin))))))
' <"$CONFIGS")
  models="$models
$from_configs"
else
  echo "note: $CONFIGS not found; checking only the default model and any arguments" >&2
fi

for extra in "$@"; do
  models="$models
$extra"
done

present=$($COMPOSE exec -T ollama ollama list </dev/null | awk 'NR > 1 { print $1 }')

echo "$models" | sed '/^$/d' | sort -u | while read -r model; do
  # `ollama list` shows an untagged name with its implicit :latest tag.
  case "$model" in *:*) tagged="$model" ;; *) tagged="$model:latest" ;; esac
  if printf '%s\n' "$present" | grep -qxF "$tagged"; then
    echo "==> $model already pulled; not re-pulling"
    continue
  fi
  echo "==> ollama pull $model"
  # </dev/null: otherwise exec reads the loop's stdin and swallows the
  # remaining model names.
  $COMPOSE exec -T ollama ollama pull "$model" </dev/null
done

echo "==> pulled models:"
$COMPOSE exec -T ollama ollama list </dev/null

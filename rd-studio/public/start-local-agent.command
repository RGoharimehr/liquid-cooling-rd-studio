#!/bin/zsh
# RD Studio local assistant. Run: zsh /path/to/start-local-agent.command
set -eu
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v ollama >/dev/null 2>&1; then
  print 'Install Ollama from https://ollama.com/download, then run this launcher again.'
  exit 1
fi
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_NO_CLOUD=1
export OLLAMA_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,https://liquid-cooling-reference-studio.rgchat037.chatgpt.site"
rd_agent_model='qwen3:4b-instruct-2507-q4_K_M'
if curl --silent --fail --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null; then
  print 'Ollama is already running. This launcher cannot change the running service settings.'
  print 'For local-only inference and Site access, stop the existing Ollama process and run this launcher again.'
  print 'If RD Studio is already connected to a local-only service, keep using it.'
  exit 0
fi
ollama serve &
rd_agent_pid=$!
trap 'kill "$rd_agent_pid" 2>/dev/null || true' EXIT INT TERM
for rd_agent_try in {1..30}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:11434/api/tags >/dev/null; then break; fi
  sleep 1
done
ollama pull "$rd_agent_model"
print 'Local AI is ready. Keep this Terminal window open, then choose Local assistant → Connect Ollama in RD Studio.'
wait "$rd_agent_pid"

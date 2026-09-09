# Local design assistant

Open **Local assistant** in the Studio header. Connect Ollama, select a downloaded local model, then ask a question or describe a parameter change.

The assistant receives the current draft, a compact applied-design summary, relevant source notes, bounded diagnostics and up to three recent conversation turns. Meshes, full books, exports and arbitrary local files are not sent. Requests go directly from the browser to loopback Ollama. The hosted server does not proxy them to a cloud AI provider.

## Local runtime

Run `zsh public/start-local-agent.command` from this checkout, or use the launcher offered in the interface. Install Ollama first if it is unavailable. The launcher binds `127.0.0.1:11434`, sets `OLLAMA_NO_CLOUD=1`, adds the exact Studio origin to Ollama's browser allowlist, and pulls `qwen3:4b-instruct-2507-q4_K_M` if missing. The model download is about 2.5 GB; memory and speed depend on the computer. Keep the launcher running. Ctrl+C stops the service it started.

If Ollama was already running, the launcher does not stop it or pretend it changed the service's settings. Restart that service with the displayed environment settings when needed. Browser local-network permission is separate from CORS; allow it for the Studio. Some embedded browsers may restrict loopback access. Use the Studio in a top-level Chrome tab if needed, without disabling browser protections.

## Proposal flow

1. The local model returns constrained JSON: explanation, parameter replacements, qualifications and existing parameter-source IDs.
2. The client rejects unknown parameters, bad types/ranges/enums, duplicate keys, invalid assignment shapes, unavailable sources and inactive controls. A malformed proposal gets one automatic correction attempt.
3. A separate module worker generates the candidate. It runs the same configuration, catalogue, connectivity and geometry checks as normal Apply, without replacing the current export session.
4. The interface shows the exact old/new values and candidate findings. Only a passing candidate can be staged. A draft or applied-design change invalidates an earlier proposal.
5. **Stage these parameters** updates pending controls. **Apply design** remains the step that changes the canvas and enables exports for that configuration.

**Review design checks** is a deterministic review of engine findings and does not need a model. It is labelled separately from local AI. Model explanations can be wrong; generator checks establish only their documented scope, not code compliance, manufacturer qualification, hydraulic operating points or successful native Revit/Flownex transfer.

## Code and verification

- `lib/design-agent.ts`: bounded context, loopback API, structured response and parameter validation.
- `components/studio/design-assistant.tsx`: connection, conversation, cancellation, candidate worker and staging.
- `scripts/test-agent.mjs`: protocol, patch and snapshot regressions; run with Node 24.
- `public/start-local-agent.command`: local-only runtime launcher.

The assistant never executes model-generated code or shell commands, and cannot publish, edit files or fabricate a native Flownex project.

Primary API references: [Ollama chat](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [FAQ and origins](https://docs.ollama.com/faq), [model tag](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M).

## Acceptance on this Mac

Twelve assistant regression checks and TypeScript checking passed. The production build passed. The in-app browser connected directly to the installed local Qwen model. A request for two pods and four CDUs returned a parameter diff, passed a separate generator run, staged into the controls, and applied as a 32-compute-rack / 4-CDU / 2-pod design with exports enabled. Cancelling a subsequent model request preserved that design. The assistant panel was visually inspected.

An earlier model response supplied malformed assignment arrays; those are now explicitly rejected. Structured output remains a proposal, never a guarantee of correctness.

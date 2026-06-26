# Autonomous SRE Agent: Human-in-the-Loop ChatOps

This repository contains the architecture and application code to deploy an Autonomous Site Reliability Engineering (SRE) Agent. The agent investigates production alerts, cross-references internal runbooks, and — with human approval — executes safe remediation steps to resolve incidents.

## 🏗️ Architecture Flow

```mermaid
sequenceDiagram
    participant Web as Browser
    participant API as FastAPI + Ngrok
    participant Graph as LangGraph (Brain)
    participant EC2 as AWS EC2 (Hands)
    participant LLM as Gemini 2.5 Flash
    participant Slack as Slack (Mouth)

    Web->>API: 1. Trigger /slack/trigger
    API->>Graph: 2. Invoke State Machine
    Graph->>EC2: 3. Fetch Docker Logs (Paramiko SSH)
    Graph->>EC2: 4. Read internal runbook.md
    Graph->>LLM: 5. Analyze Logs + SOP
    LLM-->>Graph: 6. Returns exact Bash command
    Graph->>Slack: 7. Post Interactive Block (Approve)
    Note over Graph: Graph pauses execution (MemorySaver)
    Slack->>API: 8. Human clicks "Approve" (/slack/actions)
    API->>Graph: 9. Resume State from Memory
    Graph->>EC2: 10. Execute Remediation (docker restart)
    Graph->>Slack: 11. Post Resolution Confirmation
```

## 📋 Prerequisites

- An AWS EC2 Instance (Ubuntu 24.04 recommended).
- A Google Gemini API Key.
- A Slack Workspace with permissions to create a new App.
- An Ngrok Auth Token (for tunneling webhooks).
- A LangSmith API Key (optional, for tracing & observability).

## 🚀 Phase 1: Infrastructure & The "Trap"

First, we will set up the host server, install dependencies, and create the vulnerable container the AI will investigate.

### Log into your EC2 instance as root:

```bash
sudo su -
```

### Install system dependencies:

```bash
apt update && apt upgrade -y
apt install -y docker.io python3-venv curl unzip
```

### Deploy the Target Application:

Start an Nginx web server and intentionally inject a critical error into the logs to trigger our scenario.

```bash
docker run -d --name nginx-web -p 80:80 nginx
docker exec nginx-web sh -c "echo '2026/06/23 [alert] worker_connections are not enough' >> /var/log/nginx/error.log"
```

## 🔑 Phase 2: System Permissions (SSH Loopback)

The Python agent needs permission to execute diagnostic and remediation commands on its own host machine securely. We will set up a modern ed25519 loopback SSH key.

### Generate and Authorize the Key for Root:

```bash
ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
cat /root/.ssh/id_ed25519.pub >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

### Verify the Loopback Connection:

```bash
ssh -i /root/.ssh/id_ed25519 root@127.0.0.1 "echo 'Root SSH Works'"
```

(Type yes to accept the fingerprint if prompted. Ensure it prints "Root SSH Works" before proceeding).

## ⚙️ Phase 3: Project Configuration

### Clone this repository and navigate into it:

```bash
git clone <your-repository-url> /root/project
cd /root/project
```

### Initialize the Python Environment:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure Environment Variables:

Rename the `.env.example` file to `.env` (or create a new `.env` file) and populate it with your specific API keys:

```bash
# API Keys
GOOGLE_API_KEY="your_gemini_api_key"
SLACK_BOT_TOKEN="xoxb-your-slack-bot-token"
SLACK_CHANNEL_ID="C01234567"

# Infrastructure Paths
EC2_HOST="127.0.0.1"
EC2_USER="root"
EC2_KEY_PATH="/root/.ssh/id_ed25519"

# LangSmith (Observability)
LANGSMITH_API_KEY="your_langsmith_api_key"
LANGSMITH_PROJECT="Autonomous_SRE_Demo"
```

> Note: LangSmith tracing is optional but highly recommended in production-like testing to inspect the agent's reasoning, tool usage, and costs.

## 🌐 Phase 4: Webhooks & Slack Setup

To bridge your local EC2 instance with Slack's external API, we need a secure tunnel.

### Start Ngrok:

Open a secondary SSH terminal into the instance and run:

```bash
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

ngrok config add-authtoken YOUR_NGROK_TOKEN
ngrok http 8000
```

Copy the public Forwarding URL (e.g., `https://1234-abcd.ngrok-free.app`).

### Configure the Slack App:

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create an app.
2. Add the `chat:write` scope under **OAuth & Permissions** and install it to your workspace.
3. Under **Interactivity & Shortcuts**, toggle the feature ON.
4. Paste your Ngrok URL into the **Request URL** box and append the actions endpoint (e.g., `https://1234-abcd.ngrok-free.app/slack/actions`).
5. Click **Save**.

## 🎬 Phase 5: Live Execution

With the infrastructure running and the webhooks connected, you can now run the complete ChatOps workflow.

### Start the backend engine:

```bash
# Ensure your venv is active
python sre_backend.py
```

### Trigger the Incident:

Open a web browser and navigate to your Ngrok trigger URL:

```
https://1234-abcd.ngrok-free.app/slack/trigger
```

### Approve the Remediation:

Switch to your configured Slack channel. You will see the agent pull the logs, consult the runbook.md, and formulate the correct bash command.

Click the **Approve Restart** button.

### Verify the Fix:

Return to your EC2 terminal and run `docker ps` to verify the Nginx container's uptime has been successfully reset.

## 🔎 Phase 6: Observability & Tracing (LangSmith)

Agentic AI operates as a "black box" by default. To make this enterprise-ready, we integrate LangSmith to trace the AI's thought process, tool execution, and token usage. The tracing layer is intentionally lightweight in the demo but can be extended for production.

### Quick enable

1. Add `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` to your `.env` (see above).
2. Restart the backend so the tracer picks up the environment variables.

### What you will find in a LangSmith trace (detailed)

- Execution DAG (waterfall):
  - Full visual DAG showing nodes (LLM calls, tool calls, function steps) and their ordering (START -> diagnostics_agent -> human_in_the_loop -> remediation).
  - Each node is clickable to inspect details.

- LLM node details:
  - Raw prompt / system + user messages (what the model actually saw).
  - Model name, parameters (temperature, max_tokens), and model response text.
  - Token usage: prompt tokens, completion tokens, total tokens — useful to estimate cost per incident.
  - Latency for the LLM generation (wall-clock time).

- Tool / external call tracing:
  - Exact tool invocation (e.g., SSH command executed via Paramiko), arguments, working directory, and any structured inputs.
  - Captured stdout/stderr from the remote command (if configured to capture); in this project we surface docker logs and command output in the trace.
  - Duration and success/failure status of each tool call.

- Attachments and context snapshots:
  - Snapshots of files or artifacts included in the context (runbook.md content, selected docker logs) attached to the run for later inspection.
  - You can click attachments to expand and read the exact content that was given to the model.

- Human-in-the-loop events:
  - Timestamped actions for approvals/denials from Slack with the user identity (or anonymized ID depending on configuration).
  - The exact decision boundary where the agent paused and what it was waiting for.

- Error events & retries:
  - Stack traces or structured error messages captured during execution.
  - Automatic or manual retry attempts with inputs that changed between attempts.

- Metadata & tags:
  - Run-level metadata: project, environment, incident_id/tag, commit SHA, host name.
  - Custom tags you add (for example, severity=high, team=platform). These make searching and grouping runs easier.

- Searchable timeline and filters:
  - Filter traces by model name, user, tag, time range, or specific tool names (e.g., Paramiko/SSH).
  - Full-text search of prompts and tool outputs (useful when auditing repeated failures).

- Cost & performance dashboards:
  - Aggregate token consumption across runs, average latency per LLM call, and per-tool time breakdown.
  - Identify expensive runs and optimize prompts or reduce unnecessary context.

- Privacy & Redaction hints (important):
  - Traces can contain sensitive information (keys, IPs, secrets) if you log raw prompts and tool outputs. Configure redaction rules or sanitize inputs before sending them to LangSmith.
  - Prefer attaching sanitized artifacts when possible and limit raw prompt logging in production.

### Example trace use-cases

- Forensics: After a bad remediation, open the trace to see the exact prompt, the logs fed to the model, the model's proposed command, and the human approval step.
- Cost analysis: Find runs with high token usage and inspect the prompt sizes to trim unnecessary context (large logs embedded inline are often the culprit).
- Latency investigation: Determine whether the pipeline is waiting on SSH/tool execution or on LLM generation.
- Audit & Compliance: Export trace artifacts showing what decisions the agent made and why, useful for post-incident review.

### Minimal instrumentation example (conceptual)

Add a tracer into your runtime so LangSmith receives traces. The exact code depends on your LangChain / LangSmith SDK version; below is a conceptual example — consult LangSmith docs for exact APIs:

```python name=examples/langsmith_instrumentation.py
import os
from langchain.callbacks import LangSmithTracer  # conceptual import

os.environ.setdefault("LANGSMITH_API_KEY", "YOUR_KEY")
tracer = LangSmithTracer(project_name=os.environ.get("LANGSMITH_PROJECT", "Autonomous_SRE_Demo"))

# Register tracer with your LLM/callback manager so each chain/LLM call is traced.
# Example (conceptual):
# llm = OpenAI(temperature=0, callbacks=[tracer])
# chain = LLMChain(llm=llm, ...)
# chain.run("analyze the logs")
```

Notes:
- The repository's demo keeps a minimal, non-invasive tracing footprint. In production, prefer attaching structured logs rather than embedding huge raw files in prompts.
- Confirm the LangSmith SDK/version you use and follow their official quickstart to wire callbacks correctly.

### Best practices for using LangSmith with this project

- Tag every run with an incident_id and host so you can correlate traces with monitoring/alerting systems.
- Sanitize and redact secrets from captured outputs before sending them to the trace store.
- Attach only the relevant slice of logs (time-bounded) rather than entire log files to reduce token costs and noise.
- Add custom metadata (e.g., deployment version, runbook version) so run comparisons are meaningful.
- Set retention and access controls to satisfy your organization's compliance requirements.

---


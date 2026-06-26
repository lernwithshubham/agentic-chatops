# Autonomous SRE Agent: Human-in-the-Loop ChatOps

This repository contains the architecture and application code to deploy an Autonomous Site Reliability Engineering (SRE) Agent. The agent investigates production alerts, cross-references internal Standard Operating Procedures (SOPs), and requests human approval via Slack before executing remediation commands on the server.

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
- A LangSmith API Key (optional, for tracing).

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
```

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

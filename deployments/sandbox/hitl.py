"""
Kagenti HITL Delivery — Multi-channel approval system (Phase 8, C14+C18)

When an autonomous agent hits a HITL (Human-In-The-Loop) operation, this module
routes the approval request to the appropriate channel and waits for a response.

Channels:
  - GitHub: Post as PR/issue comment, human replies in thread
  - Slack: Interactive message with approve/deny buttons
  - Kagenti UI: Approval queue with WebSocket push
  - A2A: input_required task state for agent-to-agent delegation

Architecture:
  Agent → HITL request → Context Registry (stores contextId, channel, state)
                       → Channel Adapter (posts to GitHub/Slack/UI)
                       → Human responds
                       → Channel Adapter receives response
                       → Context Registry updates state
                       → Agent resumes with decision

Usage:
    from hitl import HITLManager, ApprovalRequest
    hitl = HITLManager(channels=["github", "kagenti-ui"])

    # Agent requests approval
    request = ApprovalRequest(
        context_id="sandbox-abc123",
        operation="git push origin main",
        risk_level="high",
        message="Agent wants to push to main branch. Approve?",
        options=["approve", "deny", "approve-once"],
    )
    decision = await hitl.request_approval(request)
    if decision.approved:
        # proceed with operation
        ...
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    """A HITL approval request from an agent."""

    context_id: str
    operation: str
    risk_level: RiskLevel = RiskLevel.MEDIUM
    message: str = ""
    options: list[str] = field(default_factory=lambda: ["approve", "deny"])
    metadata: dict = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class ApprovalDecision:
    """Human's decision on an approval request."""

    request_id: str
    status: DecisionStatus
    chosen_option: str = ""
    responder: str = ""
    channel: str = ""
    message: str = ""
    decided_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def approved(self) -> bool:
        return self.status == DecisionStatus.APPROVED


class ContextRegistry:
    """Stores and retrieves HITL approval contexts."""

    def __init__(self):
        self._contexts: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    def register(self, request: ApprovalRequest):
        self._contexts[request.request_id] = request

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        return self._contexts.get(request_id)

    def record_decision(self, decision: ApprovalDecision):
        self._decisions[decision.request_id] = decision

    def get_decision(self, request_id: str) -> Optional[ApprovalDecision]:
        return self._decisions.get(request_id)

    def pending_requests(self) -> list[ApprovalRequest]:
        return [
            r for r in self._contexts.values() if r.request_id not in self._decisions
        ]


class ChannelAdapter:
    """Base class for HITL channel adapters."""

    def post_request(self, request: ApprovalRequest) -> str:
        """Post approval request to channel. Returns channel-specific ref."""
        raise NotImplementedError

    def check_response(self, ref: str) -> Optional[ApprovalDecision]:
        """Check if human has responded. Returns None if still pending."""
        raise NotImplementedError


class GitHubAdapter(ChannelAdapter):
    """Posts HITL requests as GitHub PR/issue comments."""

    def __init__(self, repo: str, token: str = ""):
        self.repo = repo
        self.token = token  # Injected by AuthBridge, not stored

    def post_request(self, request: ApprovalRequest) -> str:
        # Format as markdown comment
        body = f"""### 🔒 Agent Approval Request

**Operation:** `{request.operation}`
**Risk Level:** {request.risk_level.value}
**Context:** {request.context_id}

{request.message}

**Options:** {" | ".join(f"`{opt}`" for opt in request.options)}

Reply with one of the options to respond.
_Request ID: {request.request_id}_
"""
        # In production: POST to GitHub API via AuthBridge
        return f"github:{self.repo}:comment:{request.request_id}"

    def check_response(self, ref: str) -> Optional[ApprovalDecision]:
        # In production: GET comments from GitHub API, parse replies
        return None  # Pending


class SlackAdapter(ChannelAdapter):
    """Posts HITL requests as Slack interactive messages."""

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url

    def post_request(self, request: ApprovalRequest) -> str:
        # In production: POST to Slack webhook with interactive buttons
        return f"slack:channel:{request.request_id}"

    def check_response(self, ref: str) -> Optional[ApprovalDecision]:
        # In production: Slack sends interaction payload to callback URL
        return None


class KagentiUIAdapter(ChannelAdapter):
    """Posts HITL requests to Kagenti UI approval queue via WebSocket."""

    def __init__(self, api_url: str = ""):
        self.api_url = api_url

    def post_request(self, request: ApprovalRequest) -> str:
        # In production: POST to Kagenti backend, push via WebSocket
        return f"ui:queue:{request.request_id}"

    def check_response(self, ref: str) -> Optional[ApprovalDecision]:
        # In production: Poll Kagenti backend for decision
        return None


class HITLManager:
    """Manages HITL approval workflow across channels."""

    ADAPTERS = {
        "github": GitHubAdapter,
        "slack": SlackAdapter,
        "kagenti-ui": KagentiUIAdapter,
    }

    def __init__(self, channels: list[str] = None):
        self.registry = ContextRegistry()
        self.channels = channels or ["kagenti-ui"]
        self.adapters: dict[str, ChannelAdapter] = {}
        for ch in self.channels:
            if ch in self.ADAPTERS:
                self.adapters[ch] = self.ADAPTERS[ch]()

    def request_approval(self, request: ApprovalRequest) -> str:
        """Submit an approval request. Returns request_id.

        In production, this would be async and the agent would poll
        or receive a callback when a decision is made.
        """
        self.registry.register(request)

        # Post to all configured channels
        refs = {}
        for name, adapter in self.adapters.items():
            ref = adapter.post_request(request)
            refs[name] = ref

        return request.request_id

    def get_decision(self, request_id: str) -> Optional[ApprovalDecision]:
        """Check if a decision has been made."""
        return self.registry.get_decision(request_id)

    def pending_count(self) -> int:
        """Number of pending approval requests."""
        return len(self.registry.pending_requests())


# FastAPI integration endpoints
FASTAPI_ROUTES = '''
# Add to kagenti/backend/main.py:

hitl_manager = HITLManager(channels=["github", "kagenti-ui"])

@app.post("/api/v1/sandbox/hitl/request")
async def create_hitl_request(request: dict):
    """Agent submits an approval request."""
    req = ApprovalRequest(
        context_id=request["context_id"],
        operation=request["operation"],
        risk_level=RiskLevel(request.get("risk_level", "medium")),
        message=request.get("message", ""),
        options=request.get("options", ["approve", "deny"]),
    )
    request_id = hitl_manager.request_approval(req)
    return {"request_id": request_id, "status": "pending"}

@app.post("/api/v1/sandbox/hitl/respond")
async def respond_to_hitl(response: dict):
    """Human responds to an approval request."""
    decision = ApprovalDecision(
        request_id=response["request_id"],
        status=DecisionStatus.APPROVED if response["decision"] == "approve" else DecisionStatus.DENIED,
        chosen_option=response["decision"],
        responder=response.get("responder", "unknown"),
        channel=response.get("channel", "api"),
    )
    hitl_manager.registry.record_decision(decision)
    return {"request_id": decision.request_id, "status": decision.status.value}

@app.get("/api/v1/sandbox/hitl/{request_id}")
async def get_hitl_status(request_id: str):
    """Check status of an approval request."""
    decision = hitl_manager.get_decision(request_id)
    if decision:
        return {"request_id": request_id, "status": decision.status.value, "decision": decision.chosen_option}
    return {"request_id": request_id, "status": "pending"}
'''


if __name__ == "__main__":
    # Demo the HITL workflow
    mgr = HITLManager(channels=["github", "kagenti-ui"])

    req = ApprovalRequest(
        context_id="sandbox-demo",
        operation="git push origin main",
        risk_level=RiskLevel.HIGH,
        message="Agent completed the fix and wants to push directly to main.",
        options=["approve", "deny", "approve-to-draft-pr"],
    )

    request_id = mgr.request_approval(req)
    print(f"HITL request submitted: {request_id}")
    print(f"Pending approvals: {mgr.pending_count()}")

    # Simulate human response
    decision = ApprovalDecision(
        request_id=request_id,
        status=DecisionStatus.APPROVED,
        chosen_option="approve-to-draft-pr",
        responder="engineer@company.com",
        channel="github",
    )
    mgr.registry.record_decision(decision)
    print(
        f"Decision: {mgr.get_decision(request_id).status.value} ({decision.chosen_option})"
    )
    print(f"Pending approvals: {mgr.pending_count()}")

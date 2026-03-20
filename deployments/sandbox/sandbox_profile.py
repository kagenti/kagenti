"""
Kagenti Composable Sandbox Profile — name and manifest builder (Session F)

Builds self-documenting agent names and K8s manifests from security layer toggles.
Each layer is an independent toggle; the agent name suffix lists active layers.

Usage:
    from sandbox_profile import SandboxProfile

    profile = SandboxProfile(
        base_agent="sandbox-legion",
        secctx=True,
        landlock=True,
        proxy=True,
    )
    print(profile.name)        # "sandbox-legion-secctx-landlock-proxy"
    print(profile.warnings)    # [] (valid combo)
    manifest = profile.build_manifest()  # K8s Deployment dict
"""

from datetime import datetime, timedelta, timezone
from typing import Optional


# Layer suffix order (must be stable for consistent naming)
_LAYER_ORDER = ["secctx", "landlock", "proxy", "gvisor"]


class SandboxProfile:
    """Composable sandbox security profile."""

    def __init__(
        self,
        base_agent: str = "sandbox-legion",
        secctx: bool = False,
        landlock: bool = False,
        proxy: bool = False,
        gvisor: bool = False,
        managed_lifecycle: bool = False,
        ttl_hours: int = 2,
        namespace: str = "team1",
        proxy_domains: Optional[str] = None,
    ):
        self.base_agent = base_agent
        self.secctx = secctx
        self.landlock = landlock
        self.proxy = proxy
        self.gvisor = gvisor
        self.managed_lifecycle = managed_lifecycle
        self.ttl_hours = ttl_hours
        self.namespace = namespace
        self.proxy_domains = proxy_domains or (
            ".anthropic.com,.openai.com,.pypi.org,"
            ".pythonhosted.org,.github.com,.githubusercontent.com"
        )

    @property
    def name(self) -> str:
        """Composable name: base-agent + active layer suffixes."""
        layers = {
            "secctx": self.secctx,
            "landlock": self.landlock,
            "proxy": self.proxy,
            "gvisor": self.gvisor,
        }
        suffixes = [layer for layer in _LAYER_ORDER if layers[layer]]
        if not suffixes:
            return self.base_agent
        return f"{self.base_agent}-{'-'.join(suffixes)}"

    @property
    def warnings(self) -> list[str]:
        """Warnings for unusual layer combinations."""
        warns = []
        if (self.landlock or self.proxy or self.gvisor) and not self.secctx:
            active = [l for l in ["landlock", "proxy", "gvisor"] if getattr(self, l)]
            warns.append(
                f"{', '.join(active)} without SecurityContext is not recommended"
                " — container escape bypasses these layers"
            )
        return warns

    def _build_agent_env(self) -> list[dict]:
        """Build environment variables for the agent container."""
        env = [
            {"name": "WORKSPACE_DIR", "value": "/workspace"},
            {"name": "PORT", "value": "8080"},
        ]
        if self.proxy:
            env.extend(
                [
                    {"name": "HTTP_PROXY", "value": "http://localhost:3128"},
                    {"name": "HTTPS_PROXY", "value": "http://localhost:3128"},
                    {
                        "name": "NO_PROXY",
                        "value": "localhost,127.0.0.1,.svc,.cluster.local",
                    },
                ]
            )
        return env

    def _build_agent_command(self) -> tuple[list[str], list[str]]:
        """Build command and args for the agent container."""
        if self.landlock:
            return (
                ["sh", "-c"],
                [
                    "pip install --target=/tmp/pip-packages --quiet nono-py 2>/dev/null; "
                    "export PYTHONPATH=/tmp/pip-packages:$PYTHONPATH; "
                    "python3 nono_launcher.py python3 agent_server.py"
                ],
            )
        return (
            ["python3"],
            ["agent_server.py"],
        )

    def _build_agent_container(self) -> dict:
        """Build the main agent container spec."""
        command, args = self._build_agent_command()
        container = {
            "name": "agent",
            "image": "python:3.11-slim",
            "command": command,
            "args": args,
            "ports": [{"containerPort": 8080, "protocol": "TCP"}],
            "env": self._build_agent_env(),
            "resources": {
                "requests": {"cpu": "250m", "memory": "512Mi"},
                "limits": {"cpu": "2", "memory": "4Gi"},
            },
            "volumeMounts": [
                {"name": "workspace", "mountPath": "/workspace"},
                {"name": "tmp", "mountPath": "/tmp"},
            ],
        }
        if self.secctx:
            container["securityContext"] = {
                "allowPrivilegeEscalation": False,
                "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            }
        return container

    def _build_proxy_container(self) -> dict:
        """Build the Squid proxy sidecar container."""
        return {
            "name": "proxy",
            "image": "sandbox-proxy:latest",
            "ports": [{"containerPort": 3128, "protocol": "TCP"}],
            "env": [
                {"name": "ALLOWED_DOMAINS", "value": self.proxy_domains},
            ],
            "securityContext": {
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"]},
            },
            "resources": {
                "requests": {"cpu": "50m", "memory": "128Mi"},
                "limits": {"cpu": "200m", "memory": "256Mi"},
            },
            "volumeMounts": [
                {"name": "proxy-tmp", "mountPath": "/tmp"},
                {"name": "proxy-var", "mountPath": "/var/spool/squid"},
                {"name": "proxy-log", "mountPath": "/var/log/squid"},
                {"name": "proxy-run", "mountPath": "/var/run/squid"},
            ],
        }

    def _build_volumes(self) -> list[dict]:
        """Build volume list."""
        volumes = [
            {"name": "workspace", "emptyDir": {}},
            {"name": "tmp", "emptyDir": {}},
        ]
        if self.proxy:
            volumes.extend(
                [
                    {"name": "proxy-tmp", "emptyDir": {}},
                    {"name": "proxy-var", "emptyDir": {}},
                    {"name": "proxy-log", "emptyDir": {}},
                    {"name": "proxy-run", "emptyDir": {}},
                ]
            )
        return volumes

    def _build_pod_spec(self) -> dict:
        """Build the pod template spec."""
        containers = [self._build_agent_container()]
        if self.proxy:
            containers.append(self._build_proxy_container())

        spec = {
            "automountServiceAccountToken": False,
            "containers": containers,
            "volumes": self._build_volumes(),
        }
        if self.secctx:
            spec["securityContext"] = {
                "runAsNonRoot": True,
                "seccompProfile": {"type": "RuntimeDefault"},
            }
        return spec

    def _build_labels(self) -> dict:
        """Build common labels."""
        return {
            "app.kubernetes.io/name": self.name,
            "app.kubernetes.io/part-of": "kagenti",
            "app.kubernetes.io/component": "sandbox-agent",
            "kagenti.io/security-profile": self.name.replace(
                f"{self.base_agent}-", "", 1
            )
            if self.name != self.base_agent
            else "none",
        }

    def build_manifest(self) -> dict:
        """Build K8s Deployment or SandboxClaim manifest."""
        if self.managed_lifecycle:
            return self._build_sandbox_claim()
        return self._build_deployment()

    def _build_deployment(self) -> dict:
        """Build a standard K8s Deployment."""
        labels = self._build_labels()
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": labels,
            },
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app.kubernetes.io/name": self.name}},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": self._build_pod_spec(),
                },
            },
        }

    def _build_sandbox_claim(self) -> dict:
        """Build a kubernetes-sigs SandboxClaim."""
        shutdown_time = (
            datetime.now(timezone.utc) + timedelta(hours=self.ttl_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        return {
            "apiVersion": "extensions.agents.x-k8s.io/v1alpha1",
            "kind": "SandboxClaim",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self._build_labels(),
            },
            "spec": {
                "sandboxTemplateRef": {"name": self.name},
                "lifecycle": {
                    "shutdownPolicy": "Delete",
                    "shutdownTime": shutdown_time,
                },
            },
        }

    def build_service(self) -> dict:
        """Build a K8s Service for the agent."""
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": self.name,
                "namespace": self.namespace,
                "labels": self._build_labels(),
            },
            "spec": {
                "selector": {"app.kubernetes.io/name": self.name},
                "ports": [
                    {
                        "port": 8080,
                        "targetPort": 8080,
                        "protocol": "TCP",
                        "name": "http",
                    }
                ],
            },
        }

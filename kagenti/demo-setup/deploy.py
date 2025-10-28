"""
Kagenti Demo Setup Script

This script automates the deployment of Kagenti demo agents and tools.
It's designed to be run after a fresh Kagenti installation.

Usage:
    python deploy.py [options]

Options:
    --demo {weather,slack,all}  Which demo to setup (default: all)
    --namespace NAMESPACE       Kubernetes namespace to deploy to (default: team1)
    --help                      Show this help message
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple


class Colors:
    """ANSI color codes for terminal output"""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    MAGENTA = "\033[0;35m"
    NC = "\033[0m"  # No Color


def print_info(message: str):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}")


def print_error(message: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")


def print_warning(message: str):
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")


def print_step(step: int, message: str):
    print(f"\n{Colors.BLUE}Step {step}: {message}{Colors.NC}")


def print_demo_header(demo: str):
    print(f"\n{Colors.MAGENTA}{'=' * 60}{Colors.NC}")
    print(f"{Colors.MAGENTA}Setting up {demo.upper()} Demo{Colors.NC}")
    print(f"{Colors.MAGENTA}{'=' * 60}{Colors.NC}")


def run_command(
    cmd: list, check=True, capture_output=False
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result"""
    try:
        result = subprocess.run(
            cmd, check=check, capture_output=capture_output, text=True
        )
        return result
    except subprocess.CalledProcessError as e:
        if check:
            print_error(f"Command failed: {' '.join(cmd)}")
            if e.stderr:
                print_error(f"Error output: {e.stderr}")
            raise
        return e


def check_prerequisites():
    """Check if required tools are installed"""
    print_info("Checking prerequisites...")

    # Check kubectl
    try:
        run_command(["kubectl", "version", "--client"], capture_output=True)
        print_info("kubectl is installed")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("kubectl is not installed or not in PATH")
        return False

    return True


def check_namespace_exists(namespace: str) -> bool:
    """Check if the Kubernetes namespace exists"""
    print_info(f"Checking if namespace '{namespace}' exists...")

    try:
        result = run_command(
            ["kubectl", "get", "namespace", namespace], capture_output=True, check=False
        )
        if result.returncode == 0:
            print_info(f"Namespace '{namespace}' exists")
            return True
        else:
            print_error(f"Namespace '{namespace}' does not exist")
            return False
    except Exception as e:
        print_error(f"Error checking namespace: {e}")
        return False


def apply_component(yaml_file: Path, namespace: str, component_name: str) -> bool:
    """Apply a Kubernetes component YAML file"""
    print_info(f"Deploying {component_name}...")

    if not yaml_file.exists():
        print_error(f"YAML file not found: {yaml_file}")
        return False

    try:
        run_command(
            ["kubectl", "apply", "-f", str(yaml_file), "-n", namespace],
            capture_output=True,
        )
        print_info(f"{component_name} deployed successfully ")
        return True
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to deploy {component_name}")
        if e.stderr:
            print_error(f"Error: {e.stderr}")
        return False


def wait_for_deployment(
    deployment_name: str, namespace: str, timeout: int = 300
) -> bool:
    """Wait for a deployment to be ready"""
    print_info(f"Waiting for {deployment_name} deployment to be ready...")

    try:
        run_command(
            [
                "kubectl",
                "wait",
                "--for=condition=available",
                f"--timeout={timeout}s",
                f"deployment/{deployment_name}",
                "-n",
                namespace,
            ],
            capture_output=True,
            check=False,
        )
        print_info(f"{deployment_name} is ready")
        return True
    except subprocess.CalledProcessError:
        print_warning(f"Deployment {deployment_name} not yet available")
        return False


def check_pod_status(namespace: str, filter_text: str = ""):
    """Check and display pod status"""
    print_info("Checking pod status...")

    try:
        result = run_command(
            ["kubectl", "get", "pods", "-n", namespace], capture_output=True
        )

        # Filter lines containing specified text
        lines = result.stdout.split("\n")
        header = lines[0] if lines else ""

        if filter_text:
            filtered_pods = [
                line for line in lines[1:] if filter_text.lower() in line.lower()
            ]
        else:
            filtered_pods = lines[1:]

        if filtered_pods:
            print(header)
            for pod in filtered_pods:
                if pod.strip():  # Skip empty lines
                    print(pod)
        else:
            print_warning(f"No pods found with filter: {filter_text}")

    except subprocess.CalledProcessError as e:
        print_warning(f"Could not get pod status: {e}")


def run_auth_demo_setup(namespace: str, script_dir: Path) -> bool:
    """Run the auth demo setup script (Keycloak configuration)"""
    print_info("Running auth demo setup (Keycloak configuration)...")

    # Path to auth demo script
    auth_script = script_dir.parent / "auth" / "auth_demo" / "set_up_demo.py"

    if not auth_script.exists():
        print_error(f"Auth demo script not found: {auth_script}")
        return False

    # Set up environment variables
    env = os.environ.copy()
    # If KEYCLOAK vars are not set, provide defaults (to prevent errors from set_up_demo.py)
    env.update(
        {
            "KEYCLOAK_URL": env.get(
                "KEYCLOAK_URL", "http://keycloak.localtest.me:8080"
            ),
            "KEYCLOAK_REALM": env.get("KEYCLOAK_REALM", "master"),
            "KEYCLOAK_ADMIN_USERNAME": env.get("KEYCLOAK_ADMIN_USERNAME", "admin"),
            "KEYCLOAK_ADMIN_PASSWORD": env.get("KEYCLOAK_ADMIN_PASSWORD", "admin"),
            "NAMESPACE": namespace,
        }
    )

    print_info(f"Using Keycloak URL: {env['KEYCLOAK_URL']}")
    print_info(f"Using Keycloak Realm: {env['KEYCLOAK_REALM']}")

    try:
        # Try to run with uv first (if available), otherwise use python
        try:
            result = run_command(
                [
                    "uv",
                    "run",
                    "--directory",
                    str(auth_script.parent),
                    "python",
                    str(auth_script),
                ],
                check=False,
                capture_output=True,
                env=env,
            )
            if result.returncode != 0:
                # Fall back to regular python
                result = run_command(
                    ["python3", str(auth_script)], env=env, capture_output=True
                )
        except FileNotFoundError:
            # uv not found, use python
            result = run_command(
                ["python3", str(auth_script)], env=env, capture_output=True
            )

        if result.stdout:
            print(result.stdout)

        print_info("Auth demo setup completed")
        return True

    except subprocess.CalledProcessError as e:
        print_error("Failed to run auth demo setup")
        if e.stderr:
            print_error(f"Error: {e.stderr}")
        return False


def get_demo_components(demo: str) -> List[Tuple[str, str, str]]:
    """Get list of components for a demo: (yaml_file, component_name, deployment_name)"""
    components = {
        "weather": [
            ("weather-tool.yaml", "weather-tool", "weather-tool"),
            ("weather-service-agent.yaml", "weather-service", "weather-service"),
        ],
        "slack": [
            ("slack-tool.yaml", "slack-tool", "slack-tool"),
            ("slack-researcher-agent.yaml", "slack-researcher", "slack-researcher"),
        ],
    }
    return components.get(demo, [])


def setup_demo(demo: str, namespace: str, script_dir: Path) -> bool:
    """Setup a specific demo"""
    print_demo_header(demo)

    components = get_demo_components(demo)
    if not components:
        print_error(f"Unknown demo: {demo}")
        return False

    # Deploy components
    step = 1
    for yaml_file, component_name, deployment_name in components:
        print_step(step, f"Deploying {component_name}")
        component_yaml = script_dir / "components" / yaml_file
        if not apply_component(component_yaml, namespace, component_name):
            return False
        step += 1

    # Wait for components to be ready
    print_step(step, "Waiting for components to be ready")
    time.sleep(5)  # Give components time to start

    for _, _, deployment_name in components:
        wait_for_deployment(deployment_name, namespace)

    step += 1

    # Check pod status
    print_step(step, "Checking pod status")
    check_pod_status(namespace, demo.split()[0])  # Filter by demo name
    step += 1

    return True


def print_summary(demos: List[str], namespace: str):
    """Print setup summary and next steps"""
    print()
    print_info("=" * 60)
    print_info("Demo Setup Complete!")
    print_info("=" * 60)
    print()
    print_info(f"Demos deployed: {', '.join(demos)}")
    print_info(f"Namespace: {namespace}")
    print()
    print_info("Next steps:")
    print_info("1. Verify deployments are running:")
    print(f"   kubectl get pods -n {namespace}")
    print()

    print_info("2. Check logs if needed:")
    for demo in demos:
        for _, _, deployment_name in get_demo_components(demo):
            print(f"   kubectl logs -f deployment/{deployment_name} -n {namespace}")
    print()
    print_info("=" * 60)


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Setup Kagenti Demos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--demo",
        choices=["weather", "slack", "all"],
        default="all",
        help="Which demo to setup (default: all)",
    )
    parser.add_argument(
        "--namespace",
        default="team1",
        help="Kubernetes namespace to deploy to (default: team1)",
    )

    args = parser.parse_args()

    # Get script directory
    script_dir = Path(__file__).parent

    print_info("=" * 60)
    print_info("Kagenti Demo Setup Script")
    print_info("=" * 60)
    print_info(f"Demos: {args.demo}")
    print_info(f"Namespace: {args.namespace}")
    print()

    # Check prerequisites
    if not check_prerequisites():
        print_error("Prerequisites check failed")
        sys.exit(1)

    # Check namespace exists
    if not check_namespace_exists(args.namespace):
        print_error(
            f"Please create namespace '{args.namespace}' first or specify an existing namespace"
        )
        print_info(f"Usage: {sys.argv[0]} --namespace <namespace>")
        sys.exit(1)

    # Determine which demos to setup
    demos_to_setup = ["weather", "slack"] if args.demo == "all" else [args.demo]

    # Setup each demo
    success = True
    for demo in demos_to_setup:
        if not setup_demo(demo, args.namespace, script_dir):
            print_error(f"Failed to setup {demo} demo")
            success = False
            break

    if not success:
        sys.exit(1)

    # Run auth demo setup (Keycloak configuration)
    print()
    print_demo_header("AUTH/KEYCLOAK")
    if not run_auth_demo_setup(args.namespace, script_dir):
        print_warning("Auth demo setup failed, but components are deployed")
        print_warning("You may need to run the auth setup manually:")
        print_warning(f"  cd {script_dir.parent}/auth/auth_demo")
        print_warning(f"  export NAMESPACE={args.namespace}")
        print_warning("  python3 set_up_demo.py")

    # Print summary
    print_summary(demos_to_setup, args.namespace)


if __name__ == "__main__":
    main()

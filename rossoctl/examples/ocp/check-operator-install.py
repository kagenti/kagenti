# Assisted by watsonx Code Assistant
# Copyright 2025 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import subprocess
import shlex
import time
import argparse
import sys

# --- Configuration ---
TIMEOUT_SECONDS = 300
POLL_INTERVAL = 10


def run_kubectl_command(command):
    """Executes a kubectl command and returns its output."""
    try:
        # Use shlex.split() for safe command parsing instead of shell=True
        result = subprocess.run(
            shlex.split(command), capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Silently fail if the resource doesn't exist yet, which is expected during polling
        if "NotFound" in e.stderr:
            return None
        print(f"Error executing command: {e.stderr}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main function to verify operator installation."""
    parser = argparse.ArgumentParser(
        description="Verify a Kubernetes Operator installation via its Subscription."
    )
    parser.add_argument("subscription", help="The name of the Subscription.")
    parser.add_argument(
        "namespace", help="The namespace where the Subscription exists."
    )
    args = parser.parse_args()

    start_time = time.time()

    print(
        f"[INFO] 1/2: Waiting for Subscription '{args.subscription}' to report its CSV..."
    )
    csv_name = None
    while time.time() - start_time < TIMEOUT_SECONDS:
        jsonpath = "'{.status.currentCSV}'"
        command = f"kubectl get subscription {args.subscription} -n {args.namespace} -o jsonpath={jsonpath}"

        csv_name = run_kubectl_command(command)
        if csv_name:
            print(f"[SUCCESS] Subscription is ready. Target CSV is: {csv_name}")
            break

        print(f"  ... subscription not ready yet, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

    if not csv_name:
        print(
            f"[FAIL] Timed out waiting for Subscription '{args.subscription}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[INFO] 2/2: Waiting for ClusterServiceVersion '{csv_name}' to succeed...")
    while time.time() - start_time < TIMEOUT_SECONDS:
        jsonpath = "'{.status.phase}'"
        command = (
            f"kubectl get csv {csv_name} -n {args.namespace} -o jsonpath={jsonpath}"
        )

        csv_phase = run_kubectl_command(command)

        if csv_phase == "Succeeded":
            print(f"[SUCCESS] CSV '{csv_name}' has succeeded.")
            print("\nOperator installation is complete.")
            sys.exit(0)

        if csv_phase == "Failed":
            print(
                f"[FAIL] CSV '{csv_name}' is in 'Failed' phase. Please investigate.",
                file=sys.stderr,
            )
            sys.exit(1)

        print(f"  ... CSV phase is '{csv_phase}', waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

    print(f"[FAIL] Timed out waiting for CSV '{csv_name}' to succeed.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

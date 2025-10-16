#! /bin/sh
set -ex

# This script is used to addply a headless service to a kind cluster so that local services (i.e. ollama)
# can be accessed via http://dockerhost:<port>

cat <<EOF | kubectl apply -f -
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: dockerhost
  labels:
    kubernetes.io/service-name: dockerhost
addressType: IPv4
endpoints:
- addresses:
  - $(docker network inspect kind | jq -r '.[] | .IPAM.Config[] | select(.Gateway) | .Gateway')
  conditions:
    ready: true
ports:
- name: all-ports
  protocol: TCP
---
apiVersion: v1
kind: Service
metadata:
  name: dockerhost
spec:
  clusterIP: None
EOF

## We also need to update the ollama environment to use dockerhost instead of host.docker.internal

sed -i 's/host\.docker\.internal/dockerhost/g' app/resources/environments.yaml

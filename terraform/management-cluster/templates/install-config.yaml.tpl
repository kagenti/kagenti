apiVersion: v1
baseDomain: ${base_domain}
metadata:
  name: ${cluster_name}
networking:
  clusterNetwork:
  - cidr: 10.128.0.0/14
    hostPrefix: 23
  machineNetwork:
  - cidr: ${vpc_cidr}
  networkType: OVNKubernetes
  serviceNetwork:
  - 172.30.0.0/16
platform:
  aws:
    region: ${aws_region}
    subnets:
%{ for subnet in split(",", private_subnets) ~}
    - ${subnet}
%{ endfor ~}
%{ for subnet in split(",", public_subnets) ~}
    - ${subnet}
%{ endfor ~}
compute:
- name: worker
  platform:
    aws:
      type: ${worker_type}
      zones:
%{ for az in availability_zones ~}
      - ${az}
%{ endfor ~}
  replicas: ${worker_replicas}
controlPlane:
  name: master
  platform:
    aws:
      type: ${master_type}
      zones:
%{ for az in availability_zones ~}
      - ${az}
%{ endfor ~}
  replicas: ${master_replicas}
pullSecret: '${pull_secret}'
sshKey: |
  ${ssh_public_key}

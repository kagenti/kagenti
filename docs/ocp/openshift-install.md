# Kagenti Installation on OpenShift

**This document is work in progress - main focus is to define the steps that are required on OpenShift that need to be automated in the installer**

## Istio Ambient Installation

Istio Ambient can be installed with the [OpenShift Service Mesh 3.0 operator](https://developers.redhat.com/articles/2025/03/12/try-istio-ambient-mode-red-hat-openshift#).

### Operator Installation

1. Go to the installer directory:

```shell
cd kagenti/installer
```

2. Install the operator by creating a subscription

```shell
kubectl apply -n openshift-operators -f app/resources/ocp/servicemeshoperator3.yaml 
```

3. Check operator installation is complete

```shell
python ../examples/ocp/check-operator-install.py servicemeshoperator3 openshift-operators
```

### Installing Istio ambient mode 

These steps are from the [Red Hat OpenShift Service Mesh documents](https://docs.redhat.com/en/documentation/red_hat_openshift_service_mesh/3.1/html/installing/ossm-istio-ambient-mode#ossm-installing-istio-ambient-mode_ossm-istio-ambient-mode)

1. Install the Istio control plane

```shell
kubectl create namespace istio-system
kubectl label namespace istio-system istio-discovery=enabled
kubectl apply -n openshift-operators -f app/resources/ocp/istio.yaml 
kubectl wait --for=condition=Ready istios/default --timeout=3m
```

2. Install the Istio Container Network Interface (CNI)

```shell
kubectl create namespace istio-cni
kubectl label namespace istio-cni istio-discovery=enabled
kubectl apply -f app/resources/ocp/istio-cni.yaml 
kubectl wait --for=condition=Ready istios/default --timeout=3m
```

3. Install the Ztunnel proxy

```shell
kubectl create namespace ztunnel
kubectl label namespace ztunnel istio-discovery=enabled
kubectl apply -f app/resources/ocp/ztunnel.yaml
kubectl wait --for=condition=Ready ztunnel/default --timeout=3m
```

### Install Gateway API (if not already present)

```shell
kubectl get crd gateways.gateway.networking.k8s.io &> /dev/null || \
{ kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml; }
```

## UI deployment

The simpler approach at this point to expose the UI is to use an OpenShift route
(TODO - explore how HTTPRoute could be used with istio ingress gateway and TLS termination)

```shell
kubectl apply -f app/resources/ocp/ui-route.yaml
```

## Kiali Deployment

1. Install the operator by creating a subscription

```shell
kubectl apply -n openshift-operators -f app/resources/ocp/kiali-operator.yaml 
```

2. Check operator installation is complete

```shell
python ../examples/ocp/check-operator-install.py kiali-ossm openshift-operators
```

3. Apply kiali config

```shell
kubectl apply -f app/resources/ocp/kiali-config.yaml 
```

Note: may still need to [enable user workload monitoring](https://docs.redhat.com/en/documentation/openshift_container_platform/4.16/html/monitoring/configuring-user-workload-monitoring#preparing-to-configure-the-monitoring-stack-uwm)

## Phoenix and otel-collector deployment

```shell
kubectl apply -n kagenti-system -f app/resources/phoenix.yaml
kubectl apply -n kagenti-system -f app/resources/ocp/phoenix-route.yaml
kubectl apply -n kagenti-system -f app/resources/otel-collector.yaml
```

## Keycloak

1. Create namespace

```shell
kubectl create ns keycloak
```

2. Deploy a postgres instance

```shell
kubectl apply -n keycloak -f app/resources/ocp/keycloak-postgres.yaml 
```

3. Install the operator by creating a subscription

```shell
kubectl apply -n keycloak -f app/resources/ocp/keycloak-operator.yaml 
```

4. Check operator installation is complete

```shell
python ../examples/ocp/check-operator-install.py rhbk-operator keycloak
```

5. Create keycloak instance

```shell
kubectl apply -n keycloak -f app/resources/ocp/keycloak.yaml 
```

To access it, get the URL from the route:

```shell
kubectl get route -n keycloak -l app=keycloak
```

The admin user and password can be retrived from the secret:

```shell
for key in username password; do echo -n "$key: "; kubectl get secret keycloak-initial-admin -n keycloak -o jsonpath="{.data.$key}" | base64 --decode && echo; done
```


## Installing Tekton (OpenShift Pipelines)

```shell
kubectl apply -n keycloak -f app/resources/ocp/openshift-pipelines-operator.yaml
```

```shell
python ../examples/ocp/check-operator-install.py openshift-pipelines-operator-rh openshift-operators
```

## Installing Cert Manager

```shell
kubectl create ns cert-manager-operator
```

```shell
kubectl apply -n keycloak -f app/resources/ocp/cert-manager-operator.yaml
```

```shell
python ../examples/ocp/check-operator-install.py openshift-cert-manager-operator cert-manager-operator
```

## Installing the Kagenti Platform Operator

```shell
export OPERATOR_NAMESPACE=kagenti-system
export LATEST_TAG=0.2.0-alpha.6
helm upgrade --install kagenti-platform-operator --create-namespace --namespace ${OPERATOR_NAMESPACE} oci://ghcr.io/kagenti/kagenti-operator/kagenti-platform-operator-chart --version ${LATEST_TAG} --set controllerManager.resources.limits.memory=512Mi
```

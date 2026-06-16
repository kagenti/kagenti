{{/*
Expand the name of the chart.
*/}}
{{- define "kagenti.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "kagenti.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "kagenti.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels WITHOUT app.kubernetes.io/name. Use this on resources that set
their own per-component name (e.g. kagenti-ui, kagenti-backend) so the name is
emitted exactly once. Mixing an explicit name with "kagenti.labels" (which also
adds app.kubernetes.io/name) would otherwise produce a duplicate YAML map key.
This is the single source of truth for the shared (non-name) label keys.
*/}}
{{- define "kagenti.commonLabels" -}}
helm.sh/chart: {{ include "kagenti.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Common labels, including app.kubernetes.io/name. Composed from
kagenti.commonLabels so the shared keys are defined in one place.
*/}}
{{- define "kagenti.labels" -}}
app.kubernetes.io/name: {{ include "kagenti.name" . }}
{{ include "kagenti.commonLabels" . }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kagenti.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kagenti.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "kagenti.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "kagenti.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Determines if the community Istio charts should be enabled.
This becomes the single source of truth for the complex logic.
It will be enabled if:
  - The main 'istio' component is enabled AND
  - The 'openshift' flag is NOT true.
*/}}
{{- define "kagenti.istio.communityCharts.enabled" -}}
{{- tpl "{{ and .Values.components.istio.enabled (not .Values.openshift) }}" . | toString -}}
{{- end -}}

{{/*
Validate that authBridge.clientAuthType=federated-jwt is only used when
SPIRE is enabled. The federated-jwt path mints a JWT-SVID via the
in-process SPIFFE provider, which is only constructed when spire.enabled
gates a top-level `spiffe:` block into the rendered authbridge config.
Without that, the new authbridge image fails to Configure with
"spiffe identity requires a SPIFFE provider to be injected" at boot.
Failing here at helm template time gives a clearer message than a
CrashLoopBackOff. See kagenti-extensions#332.
*/}}
{{- define "kagenti.authBridge.validateSpiffeIdentity" -}}
{{- if and (eq .Values.authBridge.clientAuthType "federated-jwt") (not .Values.spire.enabled) -}}
{{- fail "authBridge.clientAuthType=federated-jwt requires spire.enabled=true (the in-process SPIFFE provider is needed to mint JWT-SVID client assertions)" -}}
{{- end -}}
{{- end -}}

{{/*
AuthBridge runtime config YAML (config.yaml content for authbridge-runtime-config ConfigMap).
Single source of truth: evaluates authBridge.pipeline from values.yaml via tpl(),
prepends the conditional spiffe block when SPIRE is enabled.
Both authbridge-template-configmaps.yaml and agent-namespaces.yaml include this.
*/}}
{{- define "kagenti.authbridge-runtime-config-yaml" -}}
{{- if .Values.spire.enabled }}
spiffe: {}
{{- end }}
pipeline:
{{ tpl .Values.authBridge.pipeline . | indent 2 }}
{{- end -}}

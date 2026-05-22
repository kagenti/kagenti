{{/*
Expand the name of the chart.
*/}}
{{- define "openshell.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name.
*/}}
{{- define "openshell.fullname" -}}
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
Chart name and version for the chart label.
*/}}
{{- define "openshell.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "openshell.labels" -}}
helm.sh/chart: {{ include "openshell.chart" . }}
{{ include "openshell.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
openshell.ai/tenant: {{ .Values.tenant }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "openshell.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openshell.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Compute driver target namespace (defaults to tenant)
*/}}
{{- define "openshell.driverNamespace" -}}
{{- default .Values.tenant .Values.driver.namespace }}
{{- end }}

{{/*
OIDC audience (defaults to tenant)
*/}}
{{- define "openshell.oidcAudience" -}}
{{- default .Values.tenant .Values.oidc.audience }}
{{- end }}

{{/*
Validate required values
*/}}
{{- define "openshell.validateValues" -}}
{{- required "tenant is required (e.g. --set tenant=team1)" .Values.tenant -}}
{{- if .Values.oidc.enabled -}}
{{- required "oidc.issuer is required when oidc.enabled=true" .Values.oidc.issuer -}}
{{- end -}}
{{- end }}

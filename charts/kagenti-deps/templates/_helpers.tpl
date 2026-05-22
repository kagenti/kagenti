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
Common labels
*/}}
{{- define "kagenti.labels" -}}
helm.sh/chart: {{ include "kagenti.chart" . }}
{{ include "kagenti.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
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
{{/*
Build the final OTEL collector config by merging the base config with
component-specific presets when those components are enabled.
Uses mustMergeOverwrite for recursive map merge. Arrays are replaced,
not concatenated (e.g. service.extensions).
*/}}
{{- define "kagenti.otel.collectorConfig" -}}
{{- $config := deepCopy .Values.otel.collector.config -}}
{{- $hasComponentPipeline := false -}}
{{- if and $.Values.components.phoenix.enabled $.Values.otel.collector.phoenixConfig -}}
{{- $config = mustMergeOverwrite $config (deepCopy $.Values.otel.collector.phoenixConfig) -}}
{{- $hasComponentPipeline = true -}}
{{- end -}}
{{- $mlflowEnabled := or $.Values.components.mlflow.enabled ($.Values.otel.mlflow).enabled -}}
{{- if and $mlflowEnabled $.Values.otel.collector.mlflowConfig -}}
{{- $config = mustMergeOverwrite $config (deepCopy $.Values.otel.collector.mlflowConfig) -}}
{{- $hasComponentPipeline = true -}}
{{- end -}}
{{- if and (not $hasComponentPipeline) $.Values.otel.collector.defaultConfig -}}
{{- $config = mustMergeOverwrite $config (deepCopy $.Values.otel.collector.defaultConfig) -}}
{{- end -}}
{{- if and $mlflowEnabled $.Values.mlflow.auth.enabled $.Values.otel.collector.mlflowAuthConfig -}}
{{- $config = mustMergeOverwrite $config (deepCopy $.Values.otel.collector.mlflowAuthConfig) -}}
{{- end -}}
{{- if and $.Values.openshift (get (get ($config) "extensions" | default dict) "oauth2client/mlflow") -}}
{{- $_ := set (index $config "extensions" "oauth2client/mlflow") "tls" (dict "ca_file" "/etc/pki/ingress-ca/ingress-ca.pem") -}}
{{- end -}}
{{- $rhoaiMlflow := ($.Values.otel.mlflow).enabled | default false -}}
{{- if and $.Values.openshift $rhoaiMlflow -}}
{{- $mlflowExp := dig "exporters" "otlphttp/mlflow" dict $config -}}
{{- if $mlflowExp -}}
{{- $_ := set $mlflowExp "tls" (dict) -}}
{{- end -}}
{{- if $.Values.otel.collector.rhoaiMlflowAuthConfig -}}
{{- $config = mustMergeOverwrite $config (deepCopy $.Values.otel.collector.rhoaiMlflowAuthConfig) -}}
{{- end -}}
{{- if $mlflowExp -}}
{{- $_ := set $mlflowExp "auth" (dict "authenticator" "bearertokenauth/mlflow") -}}
{{- $headers := $mlflowExp.headers | default dict -}}
{{- $_ := set $headers "x-mlflow-workspace" ($.Values.otel.mlflow).workspace -}}
{{- $_ := set $headers "x-mlflow-experiment-id" (($.Values.otel.mlflow).experimentId | toString) -}}
{{- $_ := set $mlflowExp "headers" $headers -}}
{{- end -}}
{{- end -}}
{{- if and $mlflowEnabled $.Values.mlflow.auth.enabled (not $rhoaiMlflow) -}}
{{- $mlflowExporter := index $config "exporters" "otlphttp/mlflow" | default dict -}}
{{- $_ := set $mlflowExporter "auth" (dict "authenticator" "oauth2client/mlflow") -}}
{{- end -}}
{{- toYaml $config -}}
{{- end -}}

{{/*
Merge two env var lists: defaults and overrides.
Entries in overrides with the same `name` replace the default; new names are appended.
Usage: include "kagenti.mergeEnvVars" (dict "defaults" $defaults "overrides" $overrides)
*/}}
{{- define "kagenti.mergeEnvVars" -}}
{{- $overrideNames := dict -}}
{{- range (.overrides | default list) -}}
{{- $_ := set $overrideNames .name true -}}
{{- end -}}
{{- $merged := list -}}
{{- range .defaults -}}
{{- if not (hasKey $overrideNames .name) -}}
{{- $merged = append $merged . -}}
{{- end -}}
{{- end -}}
{{- range (.overrides | default list) -}}
{{- $merged = append $merged . -}}
{{- end -}}
{{- toYaml $merged -}}
{{- end -}}

{{- define "kagenti.istio.communityCharts.enabled" -}}
{{- tpl "{{ and .Values.components.istio.enabled (not .Values.openshift) }}" . | toString -}}
{{- end -}}


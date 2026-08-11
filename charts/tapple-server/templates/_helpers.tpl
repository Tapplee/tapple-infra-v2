{{- define "tapple-server.name" -}}
{{- .Chart.Name -}}
{{- end }}

{{- define "tapple-server.fullname" -}}
{{- printf "%s" .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "tapple-server.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
app.kubernetes.io/name: {{ include "tapple-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | default .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
environment: {{ required "environment 는 필수 (prod | dev)" .Values.environment }}
{{- end }}

{{- define "tapple-server.selectorLabels" -}}
app.kubernetes.io/name: {{ include "tapple-server.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

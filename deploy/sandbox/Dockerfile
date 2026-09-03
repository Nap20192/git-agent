# Образ Песочницы агента: git + инструменты для security-ревью, доступные
# тулам раннера (grep_code → rg, git_diff → git) и Сабагентам как команды.
# Сборка: task sandbox:image → git-agent/sandbox:latest (локальный docker,
# OpenSandbox на этой же машине подхватывает тег напрямую).
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ripgrep jq curl ca-certificates \
        nodejs npm \
        golang-go \
    && rm -rf /var/lib/apt/lists/*

# Статанализ: semgrep (мультиязычный), bandit (Python), gosec (Go);
# зависимости с известными CVE: osv-scanner (lock-файлы любых экосистем).
RUN pip install semgrep bandit \
    && GOBIN=/usr/local/bin go install github.com/securego/gosec/v2/cmd/gosec@latest \
    && curl -fsSL -o /usr/local/bin/osv-scanner \
         https://github.com/google/osv-scanner/releases/latest/download/osv-scanner_linux_amd64 \
    && chmod +x /usr/local/bin/osv-scanner \
    && rm -rf /root/go/pkg /root/.cache

# Кеш go-сборки gosec не нужен в рантайме; /repo — рабочая директория агента.
WORKDIR /repo
ENTRYPOINT ["tail", "-f", "/dev/null"]

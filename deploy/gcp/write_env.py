"""Write the VM's .env: .env.example + VM settings + secrets from Secret Manager.

    python deploy/gcp/write_env.py                 write/refresh .env
    python deploy/gcp/write_env.py KEY=VALUE ...   also set these keys

Runs on the GCP VM (deploy/gcp/vm-up.sh). Secrets are read with the VM's own
service account over the metadata server; they are never printed and never
leave the VM's .env (which is gitignored). A secret that does not exist yet
(e.g. the GitHub token) is left empty and the stack still comes up.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV = os.path.join(REPO, ".env")
META = "http://metadata.google.internal/computeMetadata/v1/"

# .env key -> Secret Manager secret (created by deploy/gcp/create_vm.ps1)
SECRETS = {
    "DOCTOR_API_KEY": "aid-doctor-api-key",
    "ZAI_API_KEY": "aid-zai-api-key",
    "AGAI_GITHUB_TOKEN": "aid-github-token",
    "AGAI_A2A_TOKEN": "aid-a2a-token",
    "GRAFANA_ADMIN_PASSWORD": "aid-grafana-password",
    "MINIO_ROOT_PASSWORD": "aid-minio-password",
}


def meta(path: str) -> str:
    req = urllib.request.Request(META + path, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def secret(project: str, token: str, name: str) -> str:
    url = f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets/{name}/versions/latest:access"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return base64.b64decode(json.load(r)["payload"]["data"]).decode().strip()
    except urllib.error.HTTPError as e:
        print(f"write_env: secret {name}: HTTP {e.code} - left empty", file=sys.stderr)
        return ""


def settings() -> dict:
    project = meta("project/project-id")
    token = json.loads(meta("instance/service-accounts/default/token"))["access_token"]
    ip = meta("instance/network-interfaces/0/access-configs/0/external-ip")
    values = {
        # Ollama runs on the VM itself (deploy/gcp/startup.sh).
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "CONTAINER_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
        "DOCTOR_PROVIDER": "glm",
        "DOCTOR_MODEL": meta_or("aid-doctor-model", "glm-4.5-flash"),
        "DOCTOR_FALLBACK_PROVIDER": "ollama",
        "DOCTOR_FALLBACK_MODEL": "llama3.2",
        "RUNTIME_DIR": "./runtime",
        # The agent team runs as the compose profile "agents".
        "COMPOSE_PROFILES": "agents",
        "DOCTOR_AGENTS_URL": "http://agai:8080",
        "DOCTOR_AGENTS_PUBLIC_URL": f"http://{ip}:8200",
    }
    for key, name in SECRETS.items():
        values[key] = secret(project, token, name)
    return values


def meta_or(attr: str, default: str) -> str:
    try:
        return meta(f"instance/attributes/{attr}").strip() or default
    except urllib.error.URLError:
        return default


def write(values: dict) -> None:
    base = ENV if os.path.exists(ENV) else os.path.join(REPO, ".env.example")
    lines, seen = [], set()
    for raw in open(base, encoding="utf-8"):
        key = raw.split("=", 1)[0].strip()
        if "=" in raw and not raw.lstrip().startswith("#") and key in values:
            lines.append(f"{key}={values[key]}\n")
            seen.add(key)
        else:
            lines.append(raw if raw.endswith("\n") else raw + "\n")
    lines += [f"{k}={v}\n" for k, v in values.items() if k not in seen]
    tmp = ENV + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV)


def main(argv) -> int:
    extra = dict(a.split("=", 1) for a in argv if "=" in a)
    write(extra if extra else settings())   # KEY=VALUE args only touch those keys
    print(f"write_env: {'updated ' + ', '.join(extra) if extra else 'wrote'} {ENV}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

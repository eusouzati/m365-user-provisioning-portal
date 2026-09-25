"""Sprint 10: garantias do pipeline (sem segredos, OIDC, menor privilégio)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"


def load(name: str) -> dict:
    data = yaml.safe_load((WF / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML 1.1: "on" vira True
    return data


def test_ci_reutilizavel_e_sem_duplicar_na_main():
    ci = load("ci.yml")
    assert "workflow_call" in ci["on"]
    assert ci["on"]["push"] == {"branches-ignore": ["main"]}
    assert ci["permissions"] == {"contents": "read"}


def test_deploy_depende_do_ci_e_usa_oidc():
    wf = load("deploy.yml")
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["ci"]["uses"] == "./.github/workflows/ci.yml"
    job = wf["jobs"]["deploy"]
    assert job["needs"] == "ci"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert "refs/heads/main" in job["if"] and "DEPLOY_LAB_ENABLED" in job["if"]
    assert "DEPLOY_PRODUCTION_ENABLED" in job["if"]
    assert "environment" in job and job["concurrency"]["cancel-in-progress"] is False
    login = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("azure/login"))
    assert set(login["with"]) == {"client-id", "tenant-id", "subscription-id"}
    assert all(v.startswith("${{ vars.") for v in login["with"].values())


def test_nenhum_segredo_nos_workflows():
    for f in WF.glob("*.yml"):
        usados = set(re.findall(r"secrets\.([A-Za-z0-9_]+)", f.read_text(encoding="utf-8")))
        assert usados <= {"GITHUB_TOKEN"}, f"{f.name} usa segredos: {usados}"
    texto = (WF / "deploy.yml").read_text(encoding="utf-8")
    assert "publish-profile" not in texto and "client-secret" not in texto


def test_script_da_identidade_nao_cria_segredo_e_limita_escopo():
    s = (ROOT / "scripts" / "New-GitHubDeployIdentity.ps1").read_text(encoding="utf-8-sig")
    for proibido in ("credential reset", "--password", "client-secret"):
        assert proibido not in s
    assert set(re.findall(r"--role '([^']+)'", s)) == {"Website Contributor"}
    assert set(re.findall(r"--scope (\S+)", s)) == {"$webAppId"}
    assert "environment:$Environment" in s and "api://AzureADTokenExchange" in s
    assert "AzureADMyOrg" in s
    assert s.count("Read-Host") == 1 and "-cne 'SIM'" in s


def test_codeql_e_cobertura_no_ci():
    ql = load("codeql.yml")
    job = ql["jobs"]["analisar"]
    assert job["permissions"] == {"contents": "read", "security-events": "write"}
    assert any("codeql-action/analyze" in str(s.get("uses", "")) for s in job["steps"])
    testes = next(s for s in load("ci.yml")["jobs"]["testes"]["steps"] if "pytest" in str(s))
    assert "--cov=app" in testes["run"] and "--cov-fail-under" in testes["run"]

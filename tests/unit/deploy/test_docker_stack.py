"""Structural checks for the production Swarm stack (bot and admin services)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

STACK_PATH = Path(__file__).resolve().parents[3] / "docker-stack.yml"
HOST_RULE = "Host(`agent.qeva-ai.com`)"


@pytest.fixture(scope="module")
def services() -> dict[str, Any]:
    stack = yaml.safe_load(STACK_PATH.read_text())
    return stack["services"]


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service["environment"]
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return {key: str(value) for key, value in env.items()}


def _labels(service: dict[str, Any]) -> dict[str, str]:
    return dict(item.split("=", 1) for item in service["deploy"]["labels"])


def _router_rule(labels: dict[str, str], router: str) -> str:
    return labels[f"traefik.http.routers.{router}.rule"]


def test_backend_and_admin_services_exist(services: dict[str, Any]) -> None:
    assert {"backend", "admin"} <= set(services)


def test_roles_are_bot_and_admin(services: dict[str, Any]) -> None:
    assert _env(services["backend"])["APP_ROLE"] == "bot"
    assert _env(services["admin"])["APP_ROLE"] == "admin"


def test_both_services_share_the_same_image(services: dict[str, Any]) -> None:
    assert services["admin"]["image"] == services["backend"]["image"]


def test_admin_mounts_the_same_secret(services: dict[str, Any]) -> None:
    assert services["admin"]["secrets"] == services["backend"]["secrets"]


def test_admin_router_has_path_prefix_and_higher_priority(
    services: dict[str, Any],
) -> None:
    admin = _labels(services["admin"])
    bot = _labels(services["backend"])
    rule = _router_rule(admin, "agente-ai-admin")
    assert HOST_RULE in rule
    assert "PathPrefix(`/admin`)" in rule
    admin_priority = int(admin["traefik.http.routers.agente-ai-admin.priority"])
    bot_priority = int(bot.get("traefik.http.routers.agente-ai-backend.priority", 0))
    assert admin_priority > bot_priority


def test_bot_router_keeps_the_host_only_rule(services: dict[str, Any]) -> None:
    rule = _router_rule(_labels(services["backend"]), "agente-ai-backend")
    assert rule == HOST_RULE


def test_admin_has_its_own_loadbalancer_service_and_healthcheck(
    services: dict[str, Any],
) -> None:
    admin = _labels(services["admin"])
    assert admin["traefik.http.services.agente-ai-admin.loadbalancer.server.port"] == "8000"
    assert admin["traefik.http.routers.agente-ai-admin.service"] == "agente-ai-admin"
    assert "healthcheck" in services["admin"]
    assert "replicas" in services["admin"]["deploy"]
    assert services["admin"]["deploy"]["replicas"] == 1

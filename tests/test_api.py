"""Tests for the local FastAPI application skeleton."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mirko.api import LOOPBACK_HOST, create_app
from mirko.meeting_folder import MeetingFolder, MeetingFolderError


def minimal_config() -> dict:
    return {
        "schema_version": 1,
        "meeting": {
            "id": "SA3#130",
            "title": "SA3#130 Prague",
            "timezone": "Europe/Prague",
            "days": ["2026-10-12", "2026-10-16"],
            "hours": {"start": "09:00", "end": "18:00"},
            "tdoc_series_prefix": "S3-26",
        },
        "source": {
            "kind": "local",
            "protocol": "ftp",
            "host": "10.10.10.10",
            "port": 21,
            "base_path": "/ftp/SA/SA3",
            "username": "anonymous",
        },
    }


@pytest.fixture()
def folder(tmp_path: Path) -> MeetingFolder:
    return MeetingFolder.create(tmp_path / "SA3-130", minimal_config())


@pytest.fixture()
def client(folder: MeetingFolder) -> TestClient:
    return TestClient(create_app(folder))


def test_meeting_endpoint(client: TestClient) -> None:
    response = client.get("/api/meeting")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": 1,
        "id": "SA3#130",
        "title": "SA3#130 Prague",
        "timezone": "Europe/Prague",
        "days": ["2026-10-12", "2026-10-16"],
        "hours": {"start": "09:00", "end": "18:00"},
        "tdoc_series_prefix": "S3-26",
        "source_kind": "local",
        "endpoint": "ftp://10.10.10.10:21/ftp/SA/SA3",
    }


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "meeting_id": "SA3#130",
        "schema_version": 1,
        "database": "ok",
    }


def test_openapi_contains_skeleton_endpoints(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/meeting" in paths
    assert "/api/health" in paths


def test_password_is_not_exposed(tmp_path: Path) -> None:
    data = minimal_config()
    data["source"]["password"] = "s3cret"
    folder = MeetingFolder.create(tmp_path / "SA3-130", data)

    response = TestClient(create_app(folder)).get("/api/meeting")

    assert "s3cret" not in response.text
    assert "password" not in response.text


def test_create_app_accepts_a_path(folder: MeetingFolder) -> None:
    client = TestClient(create_app(folder.path))
    assert client.get("/api/health").status_code == 200


def test_create_app_rejects_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(MeetingFolderError):
        create_app(tmp_path / "missing")


def test_server_is_loopback_only() -> None:
    assert LOOPBACK_HOST == "127.0.0.1"

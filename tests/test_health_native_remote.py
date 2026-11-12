from copy import deepcopy

from test_apple_health import native_snapshot
from test_remote_core import enroll
from test_remote_core import server as remote_server

server = remote_server


async def test_native_health_sharing_is_authenticated_scoped_encrypted_and_cloud_opt_in(server, config):
    app, http = server
    _, owner = await enroll(app, http, owner=True)
    device, companion = await enroll(app, http)
    payload = native_snapshot()
    assert (await http.post("/api/apple-health/native", json=payload)).status_code == 401
    assert (await http.post("/api/apple-health/native", headers=companion, json=payload)).status_code == 200
    persisted = (config.data_dir / "apple-health.json").read_text()
    assert "Synthetic iPhone" not in persisted
    assert not app.state.runtime.apple_health.load()["allow_cloud"]
    consent = {"scope": "personal", "privacy_revision": 0, "revision": 1, "allow_cloud": True}
    assert (await http.post("/api/apple-health/consent", headers=companion, json=consent)).status_code == 403
    assert (await http.post("/api/apple-health/consent", headers=owner, json=consent)).status_code == 200
    work = deepcopy(payload)
    work["scope"] = "work"
    assert (await http.post("/api/apple-health/native", headers=companion, json=work)).status_code == 403
    assert (await http.post("/api/voice/session", headers=companion, json={"scope": "personal", "private": True})).status_code == 200
    payload.update(revision=2, privacy_revision=1)
    assert (await http.post("/api/apple-health/native", headers=companion, json=payload)).status_code == 403
    assert app.state.runtime.apple_health.load()["revision"] == 2
    await app.state.runtime.remote.revoke_device(device["device_id"])
    assert (await http.post("/api/apple-health/native", headers=companion, json=payload)).status_code == 401

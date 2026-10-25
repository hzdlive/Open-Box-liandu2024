"""Tests for the unified deploy pipeline (v7 #22 POST /deploy 对照）.

The pipeline is exercised with a FakeManager (no kernel binary) plus
hook seams for the ruleset/conflict/verify stages. Endpoint tests use
the Flask test client: the state endpoint never touches the manager,
and the busy case works in-process because the test client runs the
app in the same process (the held module lock blocks the endpoint).
"""

import json
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import deploy as deploy_mod
from core.conflicts import ConflictError
from panel import app as appmod
from panel import db as dbmod


class FakeManager:
    def __init__(self, check=(True, "ok")):
        self._check = check
        self._running = False
        self.started = 0
        self.restarted = 0
        self.config_path = os.path.join(tempfile.mkdtemp(), "config.json")
        self.log_path = os.path.join(tempfile.mkdtemp(), "sing-box.log")

    def is_installed(self):
        return True

    def status(self):
        return SimpleNamespace(running=self._running)

    def start(self):
        self.started += 1
        self._running = True

    def restart(self):
        self.restarted += 1
        self._running = True

    def check_config(self, path=None):
        return self._check

    def to_dict(self):
        return {"running": self._running, "installed": True}


def _fresh_db():
    path = tempfile.mktemp(suffix=".db")
    c = sqlite3.connect(path)
    dbmod.init_db(c)
    c.close()
    return path


def _conn(dbfile):
    return sqlite3.connect(dbfile)


def test_status_table():
    cases = {
        "ok": 200, "conflict": 409, "validate": 409, "cancelled": 409,
        "rulesets": 503, "start": 500, "verify": 500, "error": 500,
        "bogus-stage": 500,
    }
    for stage, code in cases.items():
        assert deploy_mod.deploy_status({"ok": False, "stage": stage}) == code
    assert deploy_mod.deploy_status({"ok": True, "stage": "ok"}) == 200


def test_pipeline_success_writes_config_and_state():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    result = deploy_mod.run_deploy(
        conn, m,
        hooks={"verify_start": lambda manager, before: {"state": "running"}})
    assert result["ok"] is True and result["stage"] == "ok"
    assert deploy_mod.deploy_status(result) == 200
    assert m.started == 1 and m.restarted == 0
    with open(m.config_path) as f:
        json.load(f)  # written config parses
    raw = dbmod.get_setting(conn, deploy_mod.STATE_SETTING, "")
    assert json.loads(raw)["stage"] == "ok"
    # lock released after the run
    assert deploy_mod._DEPLOY_LOCK.acquire(blocking=False)
    deploy_mod._DEPLOY_LOCK.release()


def test_pipeline_validate_failure_is_409_with_message():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager(check=(False, "outbounds[2] refers to unknown tag"))
    result = deploy_mod.run_deploy(conn, m)
    assert result["stage"] == "validate"
    assert deploy_mod.deploy_status(result) == 409
    assert "outbounds[2]" in result["validation"]
    assert m.started == 0
    assert not os.path.exists(m.config_path)


def test_pipeline_conflict_gate_is_409_before_write():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    result = deploy_mod.run_deploy(
        conn, m, hooks={"detect_conflicts": lambda manager: [{"process": "x"}]})
    assert result["stage"] == "conflict"
    assert deploy_mod.deploy_status(result) == 409
    assert m.started == 0
    assert not os.path.exists(m.config_path)


def test_pipeline_missing_rulesets_degrades_with_warning():
    # Deliberate deviation from the original's 503-on-missing: our
    # geodata contract is degrade-and-skip (a fresh panel's defaults
    # already reference 23 sets), so the deploy continues and the
    # missing list stays visible in the result.
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    result = deploy_mod.run_deploy(conn, m, hooks={
        "referenced": ["geosite-cn"],
        "refresh_names": lambda c, names: {
            "missing": ["geosite-cn"], "reused": [], "downloaded": [],
            "kept_old": []},
        "verify_start": lambda manager, before: {"state": "running"},
    })
    assert result["ok"] is True and result["stage"] == "ok"
    assert result["rulesets_missing"] == ["geosite-cn"]
    assert "geosite-cn" in result["warning"]
    assert m.started == 1


def test_pipeline_verify_failure_is_500_after_start():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    result = deploy_mod.run_deploy(conn, m, hooks={
        "verify_start": lambda manager, before: {
            "state": "failed", "message": "FATAL: bad outbound"}})
    assert result["stage"] == "verify"
    assert deploy_mod.deploy_status(result) == 500
    assert m.started == 1  # config was written and the kernel started


def test_pipeline_start_race_conflict_maps_to_409():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()

    def _boom():
        raise ConflictError([{"process": "y", "message": "port 9090 occupied"}])
    m.start = _boom
    result = deploy_mod.run_deploy(conn, m)
    assert result["stage"] == "conflict"
    assert deploy_mod.deploy_status(result) == 409


def test_pipeline_busy_raises_without_writing_state():
    dbfile = _fresh_db()
    conn = _conn(dbfile)
    m = FakeManager()
    deploy_mod._DEPLOY_LOCK.acquire()
    try:
        try:
            deploy_mod.run_deploy(conn, m)
        except deploy_mod.DeployBusy:
            pass
        else:
            raise AssertionError("expected DeployBusy")
    finally:
        deploy_mod._DEPLOY_LOCK.release()
    assert dbmod.get_setting(conn, deploy_mod.STATE_SETTING, "") == ""


def test_endpoint_state_never_fails_and_busy_is_500():
    dbfile = _fresh_db()
    app = appmod.create_app(dbfile)
    client = app.test_client()
    r = client.get("/api/openbox/deploy/state")
    assert r.status_code == 200
    assert r.get_json()["ok"] is False
    # hold the lock in this (same) process: the endpoint must 500
    deploy_mod._DEPLOY_LOCK.acquire()
    try:
        r = client.post("/api/openbox/deploy")
    finally:
        deploy_mod._DEPLOY_LOCK.release()
    assert r.status_code == 500
    assert "部署" in r.get_json()["error"]


def test_endpoint_deploy_status_matches_body():
    # Environment-dependent stage (no kernel binary here -> validate),
    # but the status must always equal the Ny mapping of the body.
    dbfile = _fresh_db()
    app = appmod.create_app(dbfile)
    client = app.test_client()
    r = client.post("/api/openbox/deploy")
    body = r.get_json()
    assert r.status_code == deploy_mod.deploy_status(body)
    assert body["stage"] in ("ok", "conflict", "validate", "cancelled",
                             "rulesets", "start", "verify", "error")
    r = client.get("/api/openbox/deploy/state")
    assert r.get_json()["stage"] == body["stage"]

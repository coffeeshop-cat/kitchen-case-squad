"""agentarts 适配器单元测试（不触网，urlopen 被打桩）。"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from app.agentarts import (
    AgentArtsError,
    AgentArtsPlanner,
    _NoRedirect,
)

URL = "https://workflow.example.com/runtimes/rt1/invocations"
KEY = "secret-key-123"

USABLE = [
    {"id": "i1", "name": "鸡蛋", "qty": 3, "unit": "个", "state": "usable", "expiry": None},
    {"id": "i2", "name": "番茄", "qty": 2, "unit": "个", "state": "usable", "expiry": None},
    {"id": "i3", "name": "坏菜", "qty": 1, "unit": "份", "state": "discard", "expiry": None},
]

GOOD_BIZ = {
    "proposal": {
        "status": "ready",
        "title": "番茄炒蛋",
        "duration_min": 12,
        "servings": 2,
        "used_items": [
            {"id": "i1", "qty": 2, "unit": "个"},
            {"id": "i2", "qty": 1, "unit": "个"},
        ],
        "steps": [
            {"title": "备料", "detail": "鸡蛋打散。", "minutes": 2},
        ],
    },
    "audit": {"status": "pass", "reason": "ok"},
}


def fake_urlopen(payload, status=200, headers=None, redirect=False):
    raw = json.dumps(payload).encode("utf-8") if not isinstance(payload, (bytes, str)) or isinstance(payload, dict) else payload

    class R:
        def __init__(self):
            self.status = status
            self.headers = headers or {}

        def read(self, n=-1):
            return raw if isinstance(raw, bytes) else raw.encode("utf-8")

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return R()


def make_planner():
    return AgentArtsPlanner(URL, KEY)


class RequestTests(unittest.TestCase):
    def test_headers_and_body_contract(self):
        captured = {}

        def handler(req, timeout, context):
            captured["req"] = req
            return fake_urlopen({"output": json.dumps(GOOD_BIZ, ensure_ascii=False)})

        with mock.patch("app.agentarts.urllib.request.urlopen", side_effect=handler):
            verdict, events = make_planner().plan(USABLE)

        req = captured["req"]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, URL)
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertTrue(req.get_header("X-hw-agentarts-session-id"))
        self.assertEqual(len(req.get_header("X-hw-agentarts-session-id")), 32)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(set(body), {"inputs"})
        case_json = json.loads(body["inputs"]["case_json"])
        ids = [it["id"] for it in case_json["items"]]
        self.assertEqual(ids, ["i1", "i2"])  # discard 不穿透
        for it in case_json["items"]:
            self.assertEqual(set(it), {"id", "name", "qty", "unit"})

    def test_verdict_structure(self):
        with mock.patch(
            "app.agentarts.urllib.request.urlopen",
            return_value=fake_urlopen({"output": json.dumps(GOOD_BIZ)}),
        ):
            verdict, events = make_planner().plan(USABLE)
        self.assertEqual(verdict["status"], "ready")
        self.assertEqual(verdict["purchase_count"], 0)
        self.assertEqual(verdict["used_items"][0]["name"], "鸡蛋")
        self.assertEqual([e["agent"] for e in events], ["主厨", "管家"])
        for e in events:
            self.assertEqual(e["type"], "agent_speak")
            self.assertLess(len(e["text"]), 80)

    def test_wrapped_result_json(self):
        wrapped = {"result_json": json.dumps(GOOD_BIZ)}
        with mock.patch(
            "app.agentarts.urllib.request.urlopen",
            return_value=fake_urlopen(wrapped),
        ):
            verdict, _ = make_planner().plan(USABLE)
        self.assertEqual(verdict["status"], "ready")


class SecurityTests(unittest.TestCase):
    def test_http_url_rejected(self):
        with self.assertRaises(AgentArtsError):
            AgentArtsPlanner("http://x.example.com", KEY)
        with self.assertRaises(AgentArtsError):
            AgentArtsPlanner("", KEY)

    def test_no_redirect_followed(self):
        h = _NoRedirect()
        self.assertIsNone(h.redirect_request(None, None, 302, "x", {}, "https://evil/"))

    def test_no_secret_or_upstream_leak_in_errors(self):
        bad = {"proposal": {"status": "ready", "title": "x" * 500}, "audit": {"status": "pass"}}
        with mock.patch(
            "app.agentarts.urllib.request.urlopen",
            return_value=fake_urlopen(bad),
        ):
            with self.assertRaises(AgentArtsError) as cm:
                make_planner().plan(USABLE)
        msg = str(cm.exception)
        self.assertNotIn(KEY, msg)
        self.assertNotIn("xxxxx", msg)
        self.assertNotIn("secret", msg)

    def test_http_error_no_body_leak(self):
        import urllib.error

        def raiser(req, timeout, context):
            raise urllib.error.HTTPError(
                URL, 403, "denied with secret-key-123 inside", {}, None
            )

        with mock.patch("app.agentarts.urllib.request.urlopen", side_effect=raiser):
            with self.assertRaises(AgentArtsError) as cm:
                make_planner().plan(USABLE)
        msg = str(cm.exception)
        self.assertIn("403", msg)
        self.assertNotIn(KEY, msg)


class BusinessValidationTests(unittest.TestCase):
    def plan_with(self, biz):
        with mock.patch(
            "app.agentarts.urllib.request.urlopen",
            return_value=fake_urlopen({"output": json.dumps(biz)}),
        ):
            return make_planner().plan(USABLE)

    def test_insufficient_gives_empty_plan(self):
        biz = {
            "proposal": {"status": "insufficient", "title": "x", "duration_min": 1,
                         "servings": 1, "used_items": [], "steps": []},
            "audit": {"status": "pass", "reason": "不够"},
        }
        verdict, events = self.plan_with(biz)
        self.assertEqual(verdict["status"], "insufficient")
        self.assertEqual(verdict["used_items"], [])
        self.assertEqual(verdict["steps"], [])
        self.assertEqual(verdict["purchase_count"], 0)
        self.assertTrue(events)

    def test_audit_reject_gives_empty_plan(self):
        biz = dict(GOOD_BIZ)
        biz["audit"] = {"status": "reject", "reason": "含过敏原风险"}
        verdict, _ = self.plan_with(biz)
        self.assertEqual(verdict["status"], "insufficient")
        self.assertEqual(verdict["used_items"], [])

    def test_audit_not_pass_blocks_ready(self):
        biz = dict(GOOD_BIZ)
        biz["audit"] = {"status": "pending", "reason": ""}
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_overstock_rejected(self):
        biz = json.loads(json.dumps(GOOD_BIZ))
        biz["proposal"]["used_items"][0]["qty"] = 999
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_unit_mismatch_rejected(self):
        biz = json.loads(json.dumps(GOOD_BIZ))
        biz["proposal"]["used_items"][0]["unit"] = "克"
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_unknown_item_rejected(self):
        biz = json.loads(json.dumps(GOOD_BIZ))
        biz["proposal"]["used_items"][0]["id"] = "nope"
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_duplicate_used_rejected(self):
        biz = json.loads(json.dumps(GOOD_BIZ))
        biz["proposal"]["used_items"].append({"id": "i1", "qty": 1, "unit": "个"})
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_bad_steps_rejected(self):
        biz = json.loads(json.dumps(GOOD_BIZ))
        biz["proposal"]["steps"] = [{"title": "", "detail": "x", "minutes": 0}]
        with self.assertRaises(AgentArtsError):
            self.plan_with(biz)

    def test_unrecognized_body_rejected(self):
        with self.assertRaises(AgentArtsError):
            self.plan_with({"hello": "world"})
        with self.assertRaises(AgentArtsError):
            self.plan_with({"output": "not-json{{"})

    def test_non_object_root_rejected(self):
        with mock.patch(
            "app.agentarts.urllib.request.urlopen",
            return_value=fake_urlopen([1, 2]),
        ):
            with self.assertRaises(AgentArtsError):
                make_planner().plan(USABLE)

    def test_zero_purchase_only_after_validation(self):
        verdict, _ = self.plan_with(GOOD_BIZ)
        self.assertEqual(verdict["purchase_count"], 0)
        self.assertIn("调味料", verdict["note"])


if __name__ == "__main__":
    unittest.main()

"""Demo 最短闭环：开案 → 确认 → 出计划 → 急救 → 结案 → 判例。"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import STORE, create_app

PNG = ("plate.png", b"\x89PNG\r\n\x1a\nfake", "image/png")


class ApiFlowTests(unittest.TestCase):
    def setUp(self):
        with STORE.lock:
            STORE.cases.clear()
            STORE.sse_queues.clear()
            STORE.in_flight.clear()
            STORE.case_laws.clear()
        self.client = TestClient(create_app("demo"))

    def test_demo_loop(self):
        created = self.client.post("/cases")
        self.assertEqual(created.status_code, 200)
        case = created.json()
        self.assertEqual(case["status"], "review")
        cid = case["id"]

        confirmed = self.client.post(
            f"/cases/{cid}/confirm",
            json={
                "items": [
                    {"id": "i1", "name": "鸡蛋", "qty": 3, "unit": "个", "state": "usable"},
                    {"id": "i2", "name": "番茄", "qty": 2, "unit": "个", "state": "usable"},
                    {"id": "i3", "name": "奶油", "qty": 200, "unit": "克", "state": "discard"},
                ]
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        case = confirmed.json()
        self.assertEqual(case["status"], "planned")
        verdict = case["verdict"]
        self.assertEqual(verdict["title"], "番茄炒蛋")
        self.assertEqual(len(verdict["timetable"]), 3)
        self.assertIsInstance(verdict["tradeoff"], str)

        rescued = self.client.post(
            f"/cases/{cid}/rescue", files={"photo": PNG}
        )
        self.assertEqual(rescued.status_code, 200)
        self.assertEqual(rescued.json()["rescue_count"], 1)
        self.assertEqual(len(rescued.json()["options"]), 3)

        closed = self.client.post(
            f"/cases/{cid}/close",
            files={"empty_plate": PNG},
            data={"actual_minutes": "18", "failures": "米饭偏硬；盐多了", "empty": "true"},
        )
        self.assertEqual(closed.status_code, 200)
        body = closed.json()
        self.assertTrue(body["case_law_id"].startswith("law-"))
        self.assertEqual(body["case"]["status"], "closed")
        consumed = [it for it in body["case"]["items"] if it["state"] == "consumed"]
        self.assertEqual(len(consumed), 2)

        laws = self.client.get("/case-laws").json()["items"]
        self.assertEqual(len(laws), 1)
        self.assertEqual(laws[0]["failures"], ["米饭偏硬", "盐多了"])
        self.assertTrue(laws[0]["rescued"])

        again = self.client.post(
            f"/cases/{cid}/close", files={"empty_plate": PNG}
        )
        self.assertEqual(again.status_code, 409)

    def test_rescue_requires_planned_case(self):
        case = self.client.post("/cases").json()
        response = self.client.post(
            f"/cases/{case['id']}/rescue", files={"photo": PNG}
        )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()

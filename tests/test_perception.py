"""感知层：保质期规则与模型输出归一化。"""

from __future__ import annotations

import datetime as dt
import unittest

from contracts.enums import ItemKind, ItemLocation, ItemState
from perception.normalize import (
    NormalizationError,
    normalize_model_output,
    normalize_name,
    parse_quantity,
)
from perception.pipeline import (
    PerceptionUnavailable,
    apply_confidence_gate,
    recognize,
)
from perception.shelf_life import estimate_expiry, load_rules


class ShelfLifeTests(unittest.TestCase):
    def test_seed_table_has_thirty_items(self):
        rules = load_rules()
        self.assertGreaterEqual(len(rules), 30)
        self.assertIn("鸡蛋", rules)
        self.assertEqual(rules["米饭"]["expiry_tier"], "hours")

    def test_estimate_expiry_from_purchase_time(self):
        result = estimate_expiry(
            "牛奶",
            purchased_at="2026-11-20T08:00",
            now=dt.datetime(2026, 11, 21, 8, 0),
        )
        self.assertEqual(result["expiry_tier"], "days")
        self.assertEqual(result["expiry_est"], "2026-11-27")
        self.assertFalse(result["safety_exceeded"])

    def test_safety_limit_flags_leftover_rice(self):
        result = estimate_expiry(
            "米饭",
            opened_at="2026-11-25T18:00",
            now=dt.datetime(2026, 11, 26, 19, 0),
        )
        self.assertTrue(result["safety_exceeded"])


class NormalizeTests(unittest.TestCase):
    def test_chinese_aliases_and_quantity(self):
        self.assertEqual(normalize_name("西红柿"), "番茄")
        self.assertEqual(parse_quantity("半"), 0.5)
        self.assertEqual(parse_quantity("两"), 2)

    def test_normalizes_and_merges_duplicates(self):
        evidence = normalize_model_output(
            [
                {
                    "名称": "西红柿",
                    "数量": "两",
                    "单位": "颗",
                    "位置": "冷藏",
                    "生熟": "生",
                    "置信度": 0.9,
                },
                {
                    "名称": "半块豆腐",
                    "单位": "块",
                    "位置": "冰箱",
                    "生熟": "熟",
                    "置信度": 0.4,
                },
                {
                    "名称": "豆腐",
                    "数量": 0.5,
                    "单位": "块",
                    "位置": "冷藏",
                    "生熟": "熟",
                    "置信度": 0.8,
                },
            ]
        )
        self.assertEqual(len(evidence.items), 2)
        tomato = next(item for item in evidence.items if item.name == "番茄")
        tofu = next(item for item in evidence.items if item.name == "豆腐")
        self.assertEqual(tomato.qty, 2)
        self.assertEqual(tomato.unit, "个")
        self.assertEqual(tomato.kind, ItemKind.RAW)
        self.assertEqual(tomato.location, ItemLocation.FRIDGE)
        self.assertEqual(tofu.qty, 1.0)
        self.assertEqual(tofu.confidence, 0.4)

    def test_invalid_item_is_reported_not_silently_fixed(self):
        evidence = normalize_model_output(
            [
                {"名称": "", "数量": 1, "单位": "个"},
                {"名称": "鸡蛋", "数量": 3, "单位": "个", "置信度": 0.9},
            ]
        )
        self.assertEqual(len(evidence.items), 1)
        self.assertEqual(len(evidence.notes), 1)

    def test_strict_mode_raises(self):
        with self.assertRaises(NormalizationError):
            normalize_model_output([{"名称": "", "数量": 1, "单位": "个"}], strict=True)

    def test_confidence_gate_keeps_discard(self):
        evidence = normalize_model_output(
            [
                {"名称": "鸡蛋", "数量": 3, "单位": "个", "置信度": 0.9},
                {"名称": "剩菜", "数量": 1, "单位": "盒", "置信度": 0.1},
            ]
        )
        evidence.items[0].state = ItemState.USABLE
        evidence.items[1].state = ItemState.DISCARD
        apply_confidence_gate(evidence)
        self.assertEqual(evidence.items[0].state, ItemState.USABLE)
        self.assertEqual(evidence.items[1].state, ItemState.DISCARD)


class RecognizeTests(unittest.TestCase):
    def test_without_recognizer_raises_clear_error(self):
        with self.assertRaises(PerceptionUnavailable):
            recognize(b"fake", "image/png")

    def test_recognizer_output_goes_through_contract_and_gate(self):
        evidence = recognize(
            b"fake",
            "image/png",
            recognizer=lambda _photo, _mime: [
                {"名称": "鸡蛋", "数量": 3, "单位": "个", "置信度": 0.4},
                {"名称": "番茄", "数量": 2, "单位": "个", "置信度": 0.9},
            ],
        )
        self.assertEqual(len(evidence.items), 2)
        self.assertEqual(evidence.items[0].state, ItemState.REVIEW)
        self.assertEqual(evidence.items[1].state, ItemState.USABLE)


if __name__ == "__main__":
    unittest.main()

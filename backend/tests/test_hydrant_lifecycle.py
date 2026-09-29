"""消防栓生命周期规则的最小回归测试：只使用标准库，便于无外网环境执行。"""
from __future__ import annotations

import unittest

from app.seed import SEED_ROWS
from app.services.hydrant import (
    ACTION_COMPLETE,
    ACTION_REMOVE,
    ACTION_REPAIR,
    ACTION_TEST,
    STATUS_DRAFT,
    STATUS_DRY,
    STATUS_OK,
    STATUS_REPAIR,
    STATUS_RUST,
    HydrantService,
)
from app.store import store


class HydrantLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        store._tables["hydrant"] = [dict(row) for row in SEED_ROWS["hydrant"]]
        self.service = HydrantService()

    def test_historical_missing_fields_only_allows_completion(self) -> None:
        entry = self.service.get_entry(3)
        self.assertEqual(entry["status"], STATUS_DRAFT)
        self.assertEqual(entry["available_actions"], [ACTION_COMPLETE])
        self.assertTrue(entry["incomplete"])
        self.assertTrue(any("所在道路" in warning for warning in entry["warnings"]))

        blocked, message = self.service.run_action(3, ACTION_TEST)
        self.assertIsNone(blocked)
        self.assertIn("字段不完整", message)

        completed, _ = self.service.run_action(
            3, ACTION_COMPLETE, {"所在道路": "建设北路", "出水压力": "0.30"}
        )
        assert completed is not None
        self.assertEqual(completed["status"], STATUS_RUST)
        self.assertIn(ACTION_TEST, completed["available_actions"])
        self.assertFalse(completed["incomplete"])

    def test_duplicate_repair_is_blocked_until_retest_closes_it(self) -> None:
        self.assertEqual(self.service.get_entry(2)["available_actions"], [ACTION_TEST, ACTION_REMOVE])

        duplicate, message = self.service.run_action(2, ACTION_REPAIR)
        self.assertIsNone(duplicate)
        self.assertIn("重复安排维修", message)

        retested, _ = self.service.run_action(2, ACTION_TEST, {"出水压力": "0.32MPa"})
        assert retested is not None
        self.assertEqual(retested["status"], STATUS_OK)
        self.assertIn(ACTION_REPAIR, retested["available_actions"])

        repaired, _ = self.service.run_action(2, ACTION_REPAIR)
        assert repaired is not None
        self.assertEqual(repaired["status"], STATUS_REPAIR)
        self.assertNotIn(ACTION_REPAIR, repaired["available_actions"])

    def test_abnormal_pressure_keeps_actions_consistent_everywhere(self) -> None:
        low_pressure, _ = self.service.run_action(1, ACTION_TEST, {"出水压力": "0.05"})
        assert low_pressure is not None
        self.assertEqual(low_pressure["status"], STATUS_REPAIR)
        self.assertEqual(low_pressure["available_actions"], [ACTION_TEST, ACTION_REMOVE])

        zero_pressure, _ = self.service.create_entry({
            "消防栓编号": "HYDR-ZERO",
            "口径规格": "DN100",
            "所在道路": "滨河路",
            "出水压力": "0",
        })
        assert zero_pressure is not None
        self.assertEqual(zero_pressure["status"], STATUS_DRY)
        self.assertTrue(zero_pressure["abnormal"])
        self.assertEqual(self.service.list_entries(status=STATUS_DRY)[1], 1)

        listed = self.service.list_entries(status=STATUS_DRY)[0][0]
        detailed = self.service.get_entry(int(zero_pressure["id"]))
        self.assertEqual(listed["available_actions"], detailed["available_actions"])
        self.assertEqual(listed["status"], detailed["status"])

    def test_removed_hydrant_has_no_maintenance_actions(self) -> None:
        removed, _ = self.service.run_action(1, ACTION_REMOVE)
        assert removed is not None
        self.assertEqual(removed["status"], "已拆除")
        self.assertEqual(removed["available_actions"], [])
        blocked, message = self.service.run_action(1, ACTION_TEST)
        self.assertIsNone(blocked)
        self.assertIn("已拆除", message)


if __name__ == "__main__":
    unittest.main()

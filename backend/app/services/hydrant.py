"""消防栓管理业务规则。

重构后本模块不再自己维护一套状态判断：生命周期位置、按钮（动作）可见性、
编号/口径/道路/压力校验全部来自 :mod:`app.services.lifecycle` 的统一入口
:func:`derive_view`。列表、详情、维护记录三处都通过 ``_present`` 拿到同一份
结论，保证动作一致。

兼容历史数据：种子与外部导入的老行可能缺字段、缺 ``status``、编号重复，
这些情况在统一判定里收窄动作并给出提示，而不是在读取时报错。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import lifecycle as lc
from app.store import store

MODULE = "hydrant"
REQUIRED_FIELDS = lc.REQUIRED_FIELDS

# 维护记录（消防栓维度的动作历史）独立成表，和业务行分离。
LOG_MODULE = "hydrant_maintenance_log"

# 与种子状态对应的历史维护记录（只在日志表为空时补入，模拟纸质台账转录）。
_SEED_LOGS = {
    1: ("试水检测", "2026-09-01 09:10:00", "季度试水正常，压力 0.35MPa"),
    2: ("安排维修", "2026-08-20 14:30:00", "试水欠压 0.05MPa，已安排维修"),
    3: ("安排维修", "2026-07-15 10:05:00", "接口锈蚀，登记外观缺陷待维修"),
    4: ("试水检测", "2026-06-10 09:00:00", "历史试水记录，压力台账缺失"),
    5: ("安排维修", "2026-08-21 16:20:00", "重复登记档案：与 HYDR-0002 同编号"),
    6: ("试水检测", "2025-12-02 11:00:00", "纸质档案转录试水，口径字段缺失"),
}


class HydrantService:
    def __init__(self) -> None:
        self._ensure_seed_logs()

    def _ensure_seed_logs(self) -> None:
        """为历史档案补一条维护记录，保证维护记录页有完整时间线。"""
        logs = store.rows(LOG_MODULE)
        if logs:
            return
        rows = {int(row.get("id", 0)): row for row in store.rows(MODULE)}
        for entry_id, (action, operated_at, detail) in _SEED_LOGS.items():
            if entry_id in rows:
                logs.append({
                    "id": len(logs) + 1,
                    "entry_id": entry_id,
                    "action": action,
                    "detail": detail,
                    "operated_at": operated_at,
                })
    # ------------------------------------------------------------------ 读取
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(lc.NUMBER_FIELD, ""))]
        if status:
            # 状态过滤同样走统一判定，兼容历史写法与别名。
            rows = [row for row in rows if lc.read_status(row) == status]
        duplicate_ids = self._duplicate_number_ids(rows)
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self._present(row, duplicate_ids) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self._present(row, self._duplicate_number_ids())

    def list_maintenance(self, entry_id: int | None = None) -> list[dict[str, Any]]:
        """维护记录：可查全部消防栓，也可只查单条；记录里带当时与当前两份动作。"""
        logs = store.rows(LOG_MODULE)
        if entry_id is not None:
            logs = [log for log in logs if int(log.get("entry_id", 0)) == entry_id]
        current = {
            int(row.get("id", 0)): self._present(row, self._duplicate_number_ids())
            for row in store.rows(MODULE)
        }
        return [self._present_log(log, current.get(int(log.get("entry_id", 0)))) for log in logs]

    # ------------------------------------------------------------------ 登记
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        number = str(values[lc.NUMBER_FIELD]).strip()
        # 编号重复允许建档（历史上确实有重复档案），但标记后动作收窄。
        duplicate = any(
            str(row.get(lc.NUMBER_FIELD, "")).strip() == number
            for row in store.rows(MODULE)
        )

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in [*REQUIRED_FIELDS, lc.PRESSURE_FIELD, "上次试水日", "维护单位", "完好情况"]:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = lc.INITIAL_STATUS
        rows.append(entry)

        self._append_log(entry["id"], "建档登记", "消防栓档案建立")
        if duplicate:
            self._append_log(entry["id"], "重复编号提示", f"编号 {number} 已存在，档案动作已收窄")
        return self._present(entry, self._duplicate_number_ids()), []

    # ------------------------------------------------------------------ 动作
    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        pressure: Any = None,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"消防栓 {entry_id} 不存在或已归档", False
        if action not in lc.ACTIONS:
            return None, f"动作「{action}」不属于消防栓管理可执行范围", False

        if action not in self._present(row, self._duplicate_number_ids())["available_actions"]:
            view = self._present(row, self._duplicate_number_ids())
            # 与按钮可见性同一口径：被拦下的动作给出同一原因，状态保持不变。
            reason = view["blocked_actions"].get(action, "当前状态不允许该动作")
            return view, reason, False

        if action == lc.ACTION_TEST:
            view, message, applied = self._do_test(row, pressure)
            return view, message, applied
        if action == lc.ACTION_REPAIR:
            self._set_status(row, "待维修")
            self._append_log(entry_id, action, f"消防栓已{action}，状态流转为待维修")
            return self._present(row, self._duplicate_number_ids()), f"消防栓已{action}", True

        self._set_status(row, lc.TERMINAL_STATUS)
        self._append_log(entry_id, action, "消防栓已登记拆除，生命周期结束")
        return self._present(row, self._duplicate_number_ids()), f"消防栓已{action}", True

    # ------------------------------------------------------------------ 内部
    def _do_test(
        self,
        row: dict[str, Any],
        pressure: Any,
    ) -> tuple[dict[str, Any], str, bool]:
        """试水检测：必须带新压力；压力异常时状态与动作按统一口径联动。"""
        if pressure is not None and str(pressure).strip():
            row[lc.PRESSURE_FIELD] = str(pressure).strip()
        elif not str(row.get(lc.PRESSURE_FIELD) or "").strip():
            # 重复维护拦截：无历史压力又未提交新压力，试水没有意义。
            return self._present(row, self._duplicate_number_ids()), "试水检测需提供本次出水压力", False

        state, value = lc.classify_pressure(row.get(lc.PRESSURE_FIELD))

        if state == "invalid":
            # 无法识别的压力不写检测日期，视为动作未生效。
            return self._present(row, self._duplicate_number_ids()), "出水压力无法识别，请重新测压", False

        row["上次试水日"] = datetime.now().strftime("%Y-%m-%d")
        if state == "low":
            # 欠压：消防栓实际处于无水状态，统一改判为「无水」，动作随之收窄。
            self._set_status(row, "无水")
            self._append_log(row["id"], lc.ACTION_TEST, f"试水欠压 {value}MPa，改判为无水")
            return self._present(row, self._duplicate_number_ids()), f"试水压力仅 {value}MPa，已标记为无水并请安排维修", True

        if state == "high":
            # 超压：维持可维修，但试水结论是异常，记录并提示先泄压。
            self._append_log(row["id"], lc.ACTION_TEST, f"试水超压 {value}MPa，需泄压复核")
            return self._present(row, self._duplicate_number_ids()), f"试水压力 {value}MPa 偏高，请先泄压再安排维修", True

        # 压力正常：试水通过回到「完好」（待维修/锈蚀经试水确认恢复）。
        self._set_status(row, "完好")
        self._append_log(row["id"], lc.ACTION_TEST, f"试水正常，压力 {value}MPa")
        return self._present(row, self._duplicate_number_ids()), f"试水检测完成，压力 {value}MPa，状态正常", True

    def _set_status(self, row: dict[str, Any], status: str) -> None:
        """写状态时同步两处：规范 ``status`` 与兼容用的中文「设施状态」列。"""
        row["status"] = status
        row["设施状态"] = status

    def _append_log(self, entry_id: int, action: str, detail: str) -> dict[str, Any]:
        logs = store.rows(LOG_MODULE)
        log = {
            "id": max((int(item.get("id", 0)) for item in logs), default=0) + 1,
            "entry_id": entry_id,
            "action": action,
            "detail": detail,
            "operated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        logs.append(log)
        return log

    def _duplicate_number_ids(self, rows: list[dict[str, Any]] | None = None) -> set[int]:
        """编号重复的消防栓 id 集合（历史重复档案的兼容分支）。"""
        rows = store.rows(MODULE) if rows is None else rows
        seen: dict[str, int] = {}
        duplicates: set[int] = set()
        for row in rows:
            number = str(row.get(lc.NUMBER_FIELD, "")).strip()
            if not number:
                continue
            if number in seen:
                duplicates.add(seen[number])
                duplicates.add(int(row.get("id", 0)))
            else:
                seen[number] = int(row.get("id", 0))
        return duplicates

    def _present(self, row: dict[str, Any], duplicate_ids: set[int]) -> dict[str, Any]:
        """统一视图出口：列表、详情、动作回执共用。"""
        return lc.derive_view(
            row,
            duplicate_number=int(row.get("id", 0)) in duplicate_ids,
        )

    def _present_log(self, log: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
        """维护记录视图：附带当前可执行动作，保证记录页与列表动作一致。"""
        view = dict(log)
        view["消防栓编号"] = (current or {}).get(lc.NUMBER_FIELD)
        view["current_status"] = (current or {}).get("status", "已归档")
        view["available_actions"] = (current or {}).get("available_actions", [])
        view["warnings"] = (current or {}).get("warnings", ["消防栓档案不存在或已归档"])
        return view

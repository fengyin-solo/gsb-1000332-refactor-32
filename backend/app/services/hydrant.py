"""消防栓管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.store import store

MODULE = "hydrant"
REQUIRED_FIELDS = ["消防栓编号", "口径规格", "所在道路"]
OPTIONAL_FIELDS = ["出水压力", "上次试水日", "维护单位", "完好情况", "设施状态"]
LIST_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

STATUS_DRAFT = "待建档"
STATUS_OK = "完好"
STATUS_REPAIR = "待维修"
STATUS_RUST = "锈蚀"
STATUS_DRY = "无水"
STATUS_REMOVED = "已拆除"
STATUS_ORDER = [STATUS_DRAFT, STATUS_OK, STATUS_REPAIR, STATUS_RUST, STATUS_DRY, STATUS_REMOVED]
ACTIVE_STATUSES = {STATUS_OK, STATUS_REPAIR, STATUS_RUST, STATUS_DRY}

ACTION_TEST = "试水检测"
ACTION_REPAIR = "安排维修"
ACTION_REMOVE = "登记拆除"
ACTION_COMPLETE = "补全档案"
ACTION_CREATE = "建档登记"
ACTION_RUST = "登记锈蚀"
ACTION_DRY = "登记无水"
ACTION_RULES = {
    ACTION_TEST: STATUS_OK,
    ACTION_REPAIR: STATUS_REPAIR,
    ACTION_REMOVE: STATUS_REMOVED,
    ACTION_COMPLETE: None,
    # 建档记录只用于维护时间线，不是外部可重复提交的动作。
    ACTION_CREATE: None,
    # 兼容旧版/外部系统曾经写入的动作名。
    ACTION_RUST: STATUS_RUST,
    ACTION_DRY: STATUS_DRY,
}
ACTION_ALIASES = {
    "试水": ACTION_TEST,
    "水压检测": ACTION_TEST,
    "维修": ACTION_REPAIR,
    "安排维护": ACTION_REPAIR,
    "维修登记": ACTION_REPAIR,
    "拆除": ACTION_REMOVE,
    "拆除登记": ACTION_REMOVE,
    "补录": ACTION_COMPLETE,
    "档案补全": ACTION_COMPLETE,
    "锈蚀登记": ACTION_RUST,
    "无水登记": ACTION_DRY,
}

STATUS_ALIASES = {
    "": None,
    "正常": STATUS_OK,
    "可用": STATUS_OK,
    "完好可用": STATUS_OK,
    "维修中": STATUS_REPAIR,
    "待维护": STATUS_REPAIR,
    "故障": STATUS_REPAIR,
    "异常": STATUS_REPAIR,
    "生锈": STATUS_RUST,
    "腐蚀": STATUS_RUST,
    "断水": STATUS_DRY,
    "无压": STATUS_DRY,
    "拆除": STATUS_REMOVED,
    "已拆": STATUS_REMOVED,
    "废弃": STATUS_REMOVED,
    "归档": STATUS_REMOVED,
    "缺失": STATUS_DRAFT,
    "待补录": STATUS_DRAFT,
    "历史数据": STATUS_DRAFT,
}
FIELD_ALIASES = {
    "消防栓编号": ("消防栓编号", "编号", "hydrant_no", "hydrantCode", "code"),
    "口径规格": ("口径规格", "口径", "规格", "diameter", "spec"),
    "所在道路": ("所在道路", "道路", "路段", "road", "address"),
    "出水压力": ("出水压力", "压力", "水压", "pressure"),
    "上次试水日": ("上次试水日", "试水日期", "试水时间", "test_date", "lastTestDate"),
    "维护单位": ("维护单位", "养护单位", "维护部门", "maintenance_unit"),
    "完好情况": ("完好情况", "完好状态", "condition"),
    "设施状态": ("设施状态", "设备状态", "facility_status"),
}
RECORD_KEYS = ("maintenance_records", "maintenanceRecords", "records", "维护记录", "养护记录")
PRESSURE_MIN = 0.10
PRESSURE_MAX = 0.80
PRESSURE_READING_MIN = 0.0
PRESSURE_READING_MAX = 2.0


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    return str(value).strip()


def _first_value(entry: dict[str, Any], field: str) -> Any:
    for key in FIELD_ALIASES[field]:
        value = entry.get(key)
        if _clean(value):
            return value
    return None


def _normalize_diameter(value: Any) -> tuple[str, str]:
    text = _clean(value).upper().replace(" ", "")
    if not text:
        return "", "口径规格不能为空"
    if text.startswith("DN"):
        number = text[2:].removesuffix("MM")
    elif text.endswith("MM"):
        number = text[:-2]
    else:
        number = text
    if number.isdigit() and 2 <= len(number) <= 3:
        return f"DN{number}", ""
    return _clean(value), "口径规格需使用 DN100、DN150 或 100mm 这类格式"


def _parse_pressure(value: Any, *, allow_unknown: bool = True) -> tuple[float | None, str | None, bool]:
    """返回压力数值、错误说明、是否为历史未知值。"""
    text = _clean(value)
    if not text:
        return None, None, False
    if isinstance(value, bool):
        return None, "出水压力必须是数字（单位 MPa）", False
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(?:MPa|mpa|兆帕)?", text)
    if not match:
        if allow_unknown:
            return None, None, True
        return None, "出水压力必须是数字（单位 MPa）", False
    try:
        pressure = float(match.group(1))
    except ValueError:
        if allow_unknown:
            return None, None, True
        return None, "出水压力必须是数字（单位 MPa）", False
    if pressure < PRESSURE_READING_MIN or pressure > PRESSURE_READING_MAX:
        return pressure, "出水压力超出可登记范围（0～2MPa）", False
    return pressure, None, False


def _normalize_action(action: str) -> str:
    action = _clean(action)
    return ACTION_ALIASES.get(action, action)


def _status_from_any(value: Any) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if text in STATUS_ORDER:
        return text
    return STATUS_ALIASES.get(text)


def _extract_records(entry: dict[str, Any]) -> list[dict[str, Any]]:
    for key in RECORD_KEYS:
        value = entry.get(key)
        if isinstance(value, list) and value:
            return [item for item in value if isinstance(item, dict)]
    return []


def _record_action(record: dict[str, Any]) -> str:
    value = record.get("action") or record.get("动作") or record.get("维护动作") or record.get("type")
    return _normalize_action(str(value or ""))


def _mark_duplicate_records(records: list[dict[str, Any]]) -> None:
    previous_maintenance = ""
    for record in records:
        action = _record_action(record)
        is_duplicate = (
            bool(action)
            and action == previous_maintenance
            and action not in (ACTION_TEST, ACTION_CREATE)
        )
        record["duplicate"] = is_duplicate or bool(record.get("duplicate"))
        if action in (ACTION_REPAIR, ACTION_RUST, ACTION_DRY):
            previous_maintenance = action


def _derive_lifecycle(
    entry: dict[str, Any],
    *,
    complete: bool,
    raw_status: str | None,
    pressure_state: tuple[float | None, str | None, bool],
    records: list[dict[str, Any]],
) -> str:
    pressure, _pressure_error, _pressure_unknown = pressure_state
    latest_action = _record_action(records[-1]) if records else ""

    if raw_status == STATUS_REMOVED:
        return STATUS_REMOVED
    if not complete:
        return STATUS_DRAFT

    pressure_zero = pressure is not None and pressure == 0
    pressure_abnormal = pressure is not None and not pressure_zero and (
        pressure < PRESSURE_MIN or pressure > PRESSURE_MAX
    )

    if latest_action == ACTION_TEST:
        return STATUS_DRY if pressure_zero else (STATUS_REPAIR if pressure_abnormal else STATUS_OK)

    if pressure_zero:
        return STATUS_DRY
    if pressure_abnormal:
        return STATUS_REPAIR
    if raw_status in ACTIVE_STATUSES:
        return raw_status

    if latest_action == ACTION_RUST:
        return STATUS_RUST
    if latest_action == ACTION_DRY:
        return STATUS_DRY
    if latest_action == ACTION_REPAIR:
        return STATUS_REPAIR
    return STATUS_OK


def _field_errors(
    entry: dict[str, Any],
    *,
    current_id: int | None = None,
    include_pressure: bool = True,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    number = _clean(_first_value(entry, "消防栓编号"))
    diameter = _clean(_first_value(entry, "口径规格"))
    road = _clean(_first_value(entry, "所在道路"))

    if not number:
        errors["消防栓编号"] = "消防栓编号不能为空"
    elif len(number) > 32:
        errors["消防栓编号"] = "消防栓编号不能超过 32 个字符"
    else:
        for row in store.rows(MODULE):
            if current_id is not None and int(row.get("id") or 0) == current_id:
                continue
            if _clean(_first_value(row, "消防栓编号")) == number:
                errors["消防栓编号"] = f"消防栓编号 {number} 已存在，不能重复建档"
                break

    _normalized_diameter, diameter_error = _normalize_diameter(diameter)
    if diameter_error:
        errors["口径规格"] = diameter_error
    if not road:
        errors["所在道路"] = "所在道路不能为空"

    pressure = _first_value(entry, "出水压力")
    if include_pressure and _clean(pressure):
        _parsed, pressure_error, _unknown = _parse_pressure(pressure, allow_unknown=False)
        if pressure_error:
            errors["出水压力"] = pressure_error
    return errors


def _reconcile_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """把历史字段归一化到生命周期字段；原字段保留，兼容旧调用方。"""
    records = _extract_records(entry)
    for index, record in enumerate(records, start=1):
        record.setdefault("id", index)
        record.setdefault("hydrant_id", entry.get("id"))
        record.setdefault("hydrant_no", _clean(_first_value(entry, "消防栓编号")))
        record.setdefault("source", "history")
        action = _record_action(record)
        if action:
            record["action"] = action
            target = ACTION_RULES.get(action)
            if target and not record.get("status"):
                record["status"] = target
    dated_records = [
        record for record in records
        if str(record.get("created_at") or record.get("date") or record.get("时间") or "")
    ]
    undated_records = [
        record for record in records
        if not str(record.get("created_at") or record.get("date") or record.get("时间") or "")
    ]
    dated_records.sort(key=lambda item: str(item.get("created_at") or item.get("date") or item.get("时间") or ""))
    undated_records.sort(key=lambda item: int(item.get("id") or 0))
    records = dated_records + undated_records
    _mark_duplicate_records(records)

    # 历史数据可能只保留了中文名或旧系统字段；补齐规范字段，但不删除旧字段。
    normalized_values: dict[str, Any] = {}
    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        value = _first_value(entry, field)
        if value is not None:
            normalized_values[field] = _clean(value)
    if not entry.get("_lifecycle_seeded"):
        source_status = _clean(entry.get("设施状态") or entry.get("完好情况") or entry.get("status"))
        normalized_values["_原始设施状态"] = source_status
        normalized_values["_lifecycle_seeded"] = True
    entry.update(normalized_values)

    raw_entry_status = _status_from_any(
        entry.get("_原始设施状态")
        or entry.get("设施状态")
        or entry.get("完好情况")
        or entry.get("status")
    )
    raw_record_status = _status_from_any(records[-1].get("status") if records else None)
    if raw_entry_status is None and raw_record_status:
        raw_entry_status = raw_record_status
    raw_status = raw_entry_status
    pressure_state = _parse_pressure(entry.get("出水压力"))
    errors = _field_errors(
        entry,
        current_id=int(entry["id"]) if entry.get("id") is not None else None,
        include_pressure=False,
    )
    complete = not any(field in errors for field in REQUIRED_FIELDS)
    status = _derive_lifecycle(
        entry,
        complete=complete,
        raw_status=raw_status,
        pressure_state=pressure_state,
        records=records,
    )

    entry["status"] = status
    entry["设施状态"] = status
    if not _clean(entry.get("完好情况")):
        entry["完好情况"] = "待补录" if status == STATUS_DRAFT else status
    entry["pending"] = status not in (STATUS_OK, STATUS_REMOVED)
    pressure, pressure_error, pressure_unknown = pressure_state
    entry["abnormal"] = status in {STATUS_REPAIR, STATUS_RUST, STATUS_DRY} or bool(pressure_error)
    entry["incomplete"] = not complete
    entry["field_errors"] = errors
    entry["maintenance_records"] = records

    warnings: list[str] = []
    if not complete:
        missing = [field for field in REQUIRED_FIELDS if field in errors]
        if missing:
            warnings.append(f"历史档案缺少或未通过校验：{'、'.join(missing)}")
    if pressure_unknown:
        warnings.append("出水压力不是有效数值，已按历史未知压力兼容展示")
    elif pressure is not None and not pressure_error:
        if pressure == 0:
            warnings.append("出水压力为 0MPa，已按无水状态处理")
        elif pressure < PRESSURE_MIN:
            warnings.append(f"出水压力低于 {PRESSURE_MIN:.2f}MPa，已转入待维修")
        elif pressure > PRESSURE_MAX:
            warnings.append(f"出水压力高于 {PRESSURE_MAX:.2f}MPa，已转入待维修")
    duplicate_count = sum(1 for record in records if record.get("duplicate"))
    if duplicate_count:
        warnings.append(f"存在 {duplicate_count} 条连续重复维护记录，已标记并拦截同类重复动作")
    entry["warnings"] = warnings
    return entry


def _available_actions(entry: dict[str, Any]) -> list[str]:
    status = entry.get("status")
    records = entry.get("maintenance_records") or []
    open_repair = False
    for record in reversed(records):
        action = _record_action(record)
        if action == ACTION_REPAIR:
            open_repair = True
            break
        if action in (ACTION_CREATE, ACTION_TEST):
            break

    if status == STATUS_REMOVED:
        return [ACTION_COMPLETE] if entry.get("field_errors") else []
    if status == STATUS_DRAFT or entry.get("field_errors"):
        return [ACTION_COMPLETE]

    actions = [ACTION_TEST, ACTION_REMOVE]
    if status in (STATUS_OK, STATUS_RUST, STATUS_DRY) and not open_repair:
        actions.insert(1, ACTION_REPAIR)
    return actions


def _present_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = _reconcile_entry(entry)
    presented = deepcopy(normalized)
    presented.pop("_原始设施状态", None)
    presented.pop("_lifecycle_seeded", None)
    presented["available_actions"] = _available_actions(normalized)
    return presented


class HydrantService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        number: str | None = None,
        diameter: str | None = None,
        road: str | None = None,
        abnormal: bool | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self.get_entry(int(row["id"])) for row in store.rows(MODULE) if row.get("id") is not None]
        rows = [row for row in rows if row is not None]

        keyword = _clean(keyword)
        number_text = _clean(number) or keyword
        diameter_text = _clean(diameter)
        road_text = _clean(road)
        if number_text:
            rows = [row for row in rows if number_text in str(row.get("消防栓编号", ""))]
        if diameter_text:
            rows = [row for row in rows if diameter_text.upper() in str(row.get("口径规格", "")).upper()]
        if road_text:
            rows = [row for row in rows if road_text in str(row.get("所在道路", ""))]
        if abnormal is True:
            rows = [row for row in rows if bool(row.get("abnormal"))]
        elif abnormal is False:
            rows = [row for row in rows if not bool(row.get("abnormal"))]

        normalized_status = _status_from_any(status)
        if normalized_status:
            rows = [row for row in rows if row.get("status") == normalized_status]

        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return _present_entry(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        values = values or {}
        diameter = _clean(values.get("口径规格") or values.get("口径"))
        normalized_diameter, diameter_error = _normalize_diameter(diameter)
        prepared = {
            field: _clean(values.get(field))
            for field in REQUIRED_FIELDS + ["出水压力", "上次试水日", "维护单位"]
        }
        if normalized_diameter:
            prepared["口径规格"] = normalized_diameter
        elif diameter:
            prepared["口径规格"] = diameter

        errors = _field_errors(prepared, current_id=None)
        invalid_fields = [field for field in REQUIRED_FIELDS + ["出水压力"] if field in errors]
        if invalid_fields:
            return None, [errors[field] for field in invalid_fields]

        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS + ["出水压力", "上次试水日", "维护单位"]:
            if prepared.get(field):
                entry[field] = prepared[field]
        rows.append(entry)
        entry = _reconcile_entry(entry)
        if entry["status"] == STATUS_DRAFT:
            record_status = STATUS_DRAFT
        else:
            record_status = entry["status"]
        entry["maintenance_records"].append({
            "id": len(entry["maintenance_records"]) + 1,
            "hydrant_id": entry["id"],
            "hydrant_no": entry.get("消防栓编号", ""),
            "action": ACTION_CREATE,
            "status": record_status,
            "source": "system",
            "duplicate": False,
        })
        _reconcile_entry(entry)
        return self.get_entry(int(entry["id"])), []

    def list_maintenance_records(self, entry_id: int | None = None) -> list[dict[str, Any]]:
        if entry_id is not None:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return []
            return deepcopy(_reconcile_entry(entry)["maintenance_records"])

        records: list[dict[str, Any]] = []
        for row in store.rows(MODULE):
            records.extend(_reconcile_entry(row)["maintenance_records"])
        return deepcopy(records)

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"消防栓 {entry_id} 不存在或已归档"

        normalized_action = _normalize_action(action)
        if normalized_action not in ACTION_RULES or normalized_action == ACTION_CREATE:
            return None, f"动作「{action}」不属于消防栓管理可执行范围"

        normalized = _reconcile_entry(entry)
        available = _available_actions(normalized)
        if normalized_action not in available:
            if (normalized.get("field_errors") or normalized.get("status") == STATUS_DRAFT) and normalized_action != ACTION_COMPLETE:
                return None, "历史档案字段不完整，请先补全档案后再维护"
            if normalized.get("status") == STATUS_REMOVED:
                return None, "消防栓已拆除，仅可查看档案，不能继续维护"
            if normalized_action == ACTION_REPAIR:
                return None, "该消防栓已有未闭环维修单，不能重复安排维修"
            return None, f"当前状态「{normalized.get('status')}」不允许执行{normalized_action}"

        values = values or {}
        record = {
            "id": len(normalized["maintenance_records"]) + 1,
            "hydrant_id": entry_id,
            "hydrant_no": normalized.get("消防栓编号", ""),
            "action": normalized_action,
            "source": "system",
            "duplicate": False,
        }

        if normalized_action == ACTION_COMPLETE:
            updates: dict[str, Any] = {}
            for field in REQUIRED_FIELDS + ["出水压力", "上次试水日", "维护单位"]:
                value = values.get(field)
                if _clean(value):
                    updates[field] = _clean(value)
            if not updates:
                return None, "补全档案至少需要提交一个字段"
            diameter_value = updates.get("口径规格")
            if diameter_value:
                normalized_diameter, diameter_error = _normalize_diameter(diameter_value)
                if diameter_error:
                    return None, diameter_error
                updates["口径规格"] = normalized_diameter
            if updates.get("出水压力"):
                _pressure, pressure_error, _unknown = _parse_pressure(
                    updates["出水压力"], allow_unknown=False
                )
                if pressure_error:
                    return None, pressure_error

            merged = {**normalized, **updates}
            errors = _field_errors(merged, current_id=entry_id)
            if errors:
                first_field = next(iter(errors))
                return None, errors[first_field]
            entry.update(updates)
            normalized["maintenance_records"].append(record)
            reconciled = _reconcile_entry(entry)
            record["status"] = reconciled["status"]
            entry["_原始设施状态"] = reconciled["status"]
            record["remark"] = "档案字段已补全"
            normalized = _reconcile_entry(entry)
        elif normalized_action == ACTION_TEST:
            pressure_value = values.get("出水压力") or values.get("压力") or values.get("pressure")
            if _clean(pressure_value):
                pressure, pressure_error, _unknown = _parse_pressure(
                    pressure_value, allow_unknown=False
                )
                if pressure_error:
                    return None, pressure_error
                entry["出水压力"] = f"{pressure:.2f}".rstrip("0").rstrip(".")
                record["pressure"] = pressure
            else:
                pressure, _error, _unknown = _parse_pressure(entry.get("出水压力"))
                if pressure is not None:
                    record["pressure"] = pressure

            test_date = values.get("上次试水日") or values.get("试水日期") or values.get("test_date")
            if _clean(test_date):
                entry["上次试水日"] = _clean(test_date)
                record["test_date"] = entry["上次试水日"]
            if values.get("维护单位"):
                entry["维护单位"] = _clean(values["维护单位"])
                record["maintenance_unit"] = entry["维护单位"]

            normalized["maintenance_records"].append(record)
            reconciled = _reconcile_entry(entry)
            # 读数异常时试水动作不能把设施刷成“完好”，由生命周期统一落到待维修/无水。
            target_status = reconciled["status"]
            entry["_原始设施状态"] = target_status
            entry["status"] = target_status
            record["status"] = target_status
            normalized = _reconcile_entry(entry)
        else:
            target_status = ACTION_RULES[normalized_action]
            if target_status:
                entry["_原始设施状态"] = target_status
                entry["status"] = target_status
            record["status"] = target_status
            normalized["maintenance_records"].append(record)
            normalized = _reconcile_entry(entry)

        _mark_duplicate_records(normalized["maintenance_records"])
        return self.get_entry(entry_id), f"消防栓已{normalized_action}"

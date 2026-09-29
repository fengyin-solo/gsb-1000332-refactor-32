"""消防栓管理接口：维护消防栓，覆盖试水检测、安排维修、登记拆除等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.hydrant import HydrantService

router = APIRouter(prefix="/api/hydrant", tags=["消防栓管理"])

service = HydrantService()

LIST_FIELDS = ["消防栓编号", "口径规格", "所在道路", "出水压力", "上次试水日", "维护单位", "完好情况", "设施状态"]
STATUSES = ["待建档", "完好", "待维修", "锈蚀", "无水", "已拆除"]


class HydrantActionPayload(BaseModel):
    """兼容 {values:{action}} 旧请求，也支持 {action, ...} 新请求。"""

    action: str | None = None
    values: dict[str, Any] | None = None
    remark: str | None = None
    消防栓编号: str | None = None
    口径规格: str | None = None
    所在道路: str | None = None
    出水压力: str | int | float | None = None
    上次试水日: str | None = None
    维护单位: str | None = None


def _payload_data(payload: HydrantActionPayload) -> tuple[str, dict[str, Any]]:
    values = dict(payload.values or {})
    if payload.action and not values.get("action"):
        values["action"] = payload.action
    for field in ["消防栓编号", "口径规格", "所在道路", "出水压力", "上次试水日", "维护单位", "remark"]:
        value = getattr(payload, field)
        if value is not None and not values.get(field):
            values[field] = value
    return str(values.get("action") or "").strip(), values


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按消防栓编号检索"),
    status: str | None = Query(default=None, description="待建档、完好、待维修、锈蚀、无水、已拆除"),
    page: int = 1,
    size: int = 20,
    消防栓编号: str | None = Query(default=None, alias="消防栓编号"),
    口径规格: str | None = Query(default=None, alias="口径规格"),
    所在道路: str | None = Query(default=None, alias="所在道路"),
    abnormal: bool | None = Query(default=None, description="是否仅查看压力或状态异常记录"),
) -> PageResult[dict]:
    """按消防栓编号、口径、道路与生命周期状态过滤；没有数据时返回空页，不报错。"""
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始")
    if size < 1:
        raise HTTPException(status_code=400, detail="每页条数至少为 1")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        status=status,
        page=page,
        size=size,
        number=消防栓编号,
        diameter=口径规格,
        road=所在道路,
        abnormal=abnormal,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/maintenance-records")
def list_all_maintenance_records(
    hydrant_id: int | None = Query(default=None, description="可选：按消防栓 ID 过滤"),
) -> dict[str, Any]:
    """维护记录统一入口；与列表、详情共用同一套生命周期动作判断。"""
    records = service.list_maintenance_records(hydrant_id)
    return {"total": len(records), "items": records}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出消防栓管理清单：返回当前全量归一化数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "hydrant", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消防栓明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消防栓 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条消防栓，缺字段时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="消防栓已登记", entry=entry)


@router.get("/{entry_id}/maintenance-records")
def list_entry_maintenance_records(entry_id: int) -> dict[str, Any]:
    """读取单条消防栓的维护记录；不存在时与详情返回相同口径。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"消防栓 {entry_id} 不存在或已归档")
    records = service.list_maintenance_records(entry_id)
    return {"total": len(records), "items": records}


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: HydrantActionPayload) -> ActionResult:
    """对单条消防栓执行生命周期动作；不允许的动作会被拦下并说明原因。"""
    action, values = _payload_data(payload)
    entry, message = service.run_action(entry_id, action, values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

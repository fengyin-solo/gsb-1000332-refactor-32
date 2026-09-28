"""消防栓管理接口：维护消防栓，覆盖试水检测、安排维修、登记拆除等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.hydrant import HydrantService

router = APIRouter(prefix="/api/hydrant", tags=["消防栓管理"])

service = HydrantService()

LIST_FIELDS = ["消防栓编号", "口径规格", "所在道路", "出水压力", "上次试水日", "维护单位", "完好情况", "设施状态"]
STATUSES = ["完好", "待维修", "锈蚀", "无水", "已拆除"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按消防栓编号检索"),
    status: str | None = Query(default=None, description="完好、待维修、锈蚀、无水、已拆除"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按消防栓编号与状态过滤消防栓管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：固定路径必须注册在 /{entry_id} 之前，否则会被当成编号解析。
@router.get("/maintenance")
def list_maintenance(
    entry_id: int | None = Query(default=None, description="只看某条消防栓的维护记录"),
) -> dict[str, Any]:
    """维护记录：默认返回全部消防栓的动作历史；每条附带当前可执行动作。"""
    items = service.list_maintenance(entry_id=entry_id)
    return {"total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出消防栓管理清单：返回当前过滤条件下的全量数据。"""
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
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="消防栓已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条消防栓执行试水检测、安排维修、登记拆除。

    按钮可见性由服务端统一判定：被拦下的动作仍返回当前视图，
    前端据此展示与列表一致的状态和可读原因。试水检测可在 values
    里携带本次出水压力 ``pressure``。
    """
    action = str(payload.values.get("action") or "").strip()
    pressure = payload.values.get("pressure")
    entry, message, applied = service.run_action(entry_id, action, pressure=pressure)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=applied, message=message, entry=entry)

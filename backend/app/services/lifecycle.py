"""消防栓生命周期统一判定。

历史上消防栓的状态判断散落在多处：列表过滤只认英文 ``status``、前端把
「设施状态」中文列直接渲染、按钮是否可点靠前端写死、口径/道路/压力各自
单独校验。这里把"一条消防栓此刻处于生命周期什么位置、能执行哪些动作、
为什么不能执行"收敛到唯一入口 :func:`derive_view`，列表、详情与维护记录
三处共用同一结论。

设计上刻意保留兼容分支：

* 老数据可能没有 ``status``（或值不在状态序列里），退化为按中文「设施状态」
  列识别；再认不出来就按兼容态「待建档」处理，而不是直接报错。
* 老数据可能缺口径、道路、压力字段：缺字段只标记并收窄动作，不阻断读取。
* 同编号的重复维护记录照常展示，但重复动作会被拦下并给出可读原因。
"""
from __future__ import annotations

from typing import Any

# 消防栓状态序列（生命周期顺序）。索引即生命周期位置。
STATUS_ORDER = ["完好", "待维修", "锈蚀", "无水", "已拆除"]
INITIAL_STATUS = "完好"
TERMINAL_STATUS = "已拆除"

# 兼容分支：历史行可能用中文列「设施状态」携带状态，且写法不统一。
STATUS_ALIASES = {
    "正常": "完好",
    "良好": "完好",
    "待修": "待维修",
    "需维修": "待维修",
    "生锈": "锈蚀",
    "锈蚀严重": "锈蚀",
    "没水": "无水",
    "断水": "无水",
    "拆除": "已拆除",
    "已拆": "已拆除",
}

# 三个维护动作；动作集合在列表、详情、维护记录间保持同一份。
ACTION_TEST = "试水检测"
ACTION_REPAIR = "安排维修"
ACTION_REMOVE = "登记拆除"
ACTIONS = [ACTION_TEST, ACTION_REPAIR, ACTION_REMOVE]

# 合法终态以外的"动作 -> 目标状态"流转表。重复维护不允许回到已过阶段。
ACTION_TARGET = {
    ACTION_TEST: "完好",
    ACTION_REPAIR: "待维修",
    ACTION_REMOVE: TERMINAL_STATUS,
}

# 档案登记必填字段（编号、口径、道路）；压力允许历史缺省。
NUMBER_FIELD = "消防栓编号"
CALIBER_FIELD = "口径规格"
ROAD_FIELD = "所在道路"
PRESSURE_FIELD = "出水压力"
REQUIRED_FIELDS = [NUMBER_FIELD, CALIBER_FIELD, ROAD_FIELD]

# 室外消防栓常用口径 DN50~DN200，超出区间视为异常口径（兼容纯数字写法）。
MIN_CALIBER_MM = 50
MAX_CALIBER_MM = 200

# 市政室外消防栓出水压力合理区间（MPa）。低于下限近似无水，高于上限有爆管风险。
MIN_PRESSURE_MPA = 0.10
MAX_PRESSURE_MPA = 0.70


def _text(value: Any) -> str:
    """把任意字段值归一成去空白的字符串；None / 缺失返回空串。"""
    if value is None:
        return ""
    return str(value).strip()


def parse_caliber(value: Any) -> float | None:
    """解析口径（mm）。兼容 "DN100"、"100mm"、纯数字；无法解析返回 None。"""
    text = _text(value).upper().replace("DN", "").replace("MM", "").replace("（", "(")
    # 取括号前的主体，例如 "100(地上式)"。
    text = text.split("(", 1)[0].strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_pressure(value: Any) -> float | None:
    """解析出水压力（MPa）。兼容 "0.35MPa"、"0.35 Mpa"、纯数字。"""
    text = _text(value).lower()
    for unit in ("mpa", "兆帕"):
        text = text.replace(unit, "")
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return None


def read_status(row: dict[str, Any]) -> str:
    """读取生命周期状态，兼容历史的多种写法。

    优先取规范 ``status``；缺失或越界时退到中文「设施状态」列（含别名）；
    都认不出来时归入兼容态「待建档」，交给动作分支提示先补档。
    """
    raw = _text(row.get("status")) or _text(row.get("设施状态"))
    status = STATUS_ALIASES.get(raw, raw)
    if status in STATUS_ORDER:
        return status
    return "待建档"


def classify_pressure(value: Any) -> tuple[str, float | None]:
    """压力判定：normal / low / high / invalid / missing。"""
    text = _text(value)
    if not text:
        return "missing", None
    pressure = parse_pressure(value)
    if pressure is None or pressure < 0:
        return "invalid", pressure
    if pressure < MIN_PRESSURE_MPA:
        return "low", pressure
    if pressure > MAX_PRESSURE_MPA:
        return "high", pressure
    return "normal", pressure


def check_fields(row: dict[str, Any]) -> tuple[list[str], bool]:
    """校验编号、口径、道路。返回 (缺失字段名, 口径是否异常)。

    历史缺字段只做标记：列表仍展示该行，只是动作收窄到「补全档案」。
    """
    missing = [field for field in REQUIRED_FIELDS if not _text(row.get(field))]
    caliber = parse_caliber(row.get(CALIBER_FIELD))
    bad_caliber = caliber is None or not (MIN_CALIBER_MM <= caliber <= MAX_CALIBER_MM)
    if CALIBER_FIELD in missing:
        bad_caliber = False  # 已计入缺失，不重复告警
    return missing, bad_caliber


def derive_view(
    row: dict[str, Any],
    *,
    duplicate_number: bool = False,
) -> dict[str, Any]:
    """统一判定入口：由原始行推出生命周期视图。

    返回字段在列表 / 详情 / 维护记录三处保持一致：

    * ``status``：归一后的规范状态（含兼容态「待建档」）
    * ``stage``：生命周期位置（0 起，-1 表示兼容态）
    * ``available_actions``：当前真正可执行的动作（按钮可见性的唯一依据）
    * ``blocked_actions``：被拦下的动作及可读原因（供界面提示）
    * ``warnings``：历史缺字段、异常口径、异常压力、重复编号等提示
    * ``pressure_state``：normal/low/high/invalid/missing
    """
    status = read_status(row)
    stage = STATUS_ORDER.index(status) if status in STATUS_ORDER else -1

    missing, bad_caliber = check_fields(row)
    pressure_state, pressure_value = classify_pressure(row.get(PRESSURE_FIELD))

    warnings: list[str] = []
    if missing:
        warnings.append(f"历史档案缺少必填字段：{'、'.join(missing)}，请先补全档案")
    if bad_caliber:
        warnings.append(f"口径「{_text(row.get(CALIBER_FIELD)) or '空'}」不在 DN{MIN_CALIBER_MM}~DN{MAX_CALIBER_MM} 常用范围")
    if duplicate_number:
        warnings.append("存在相同消防栓编号的重复档案，动作已限定为试水检测，请核对编号")
    if pressure_state == "missing":
        warnings.append("缺少出水压力记录，试水检测时请补测压力")
    elif pressure_state == "invalid":
        warnings.append(f"出水压力「{_text(row.get(PRESSURE_FIELD))}」无法识别，需重新测压")
    elif pressure_state == "low":
        warnings.append(f"出水压力 {pressure_value}MPa 低于 {MIN_PRESSURE_MPA}MPa，疑似无水/欠压")
    elif pressure_state == "high":
        warnings.append(f"出水压力 {pressure_value}MPa 高于 {MAX_PRESSURE_MPA}MPa，存在爆管风险")

    available: list[str] = []
    blocked: dict[str, str] = {}

    # 兼容态/历史缺字段：只允许把档案补回正常生命周期。
    incomplete = bool(missing) or status == "待建档"
    if incomplete:
        blocked = {
            ACTION_TEST: "档案不完整，先补全编号、口径与道路",
            ACTION_REPAIR: "档案不完整，先补全编号、口径与道路",
            ACTION_REMOVE: "档案不完整，先补全编号、口径与道路",
        }
    elif status == TERMINAL_STATUS:
        # 终态：已拆除，生命周期结束。
        blocked = {
            ACTION_TEST: "消防栓已拆除，不能再试水检测",
            ACTION_REPAIR: "消防栓已拆除，不能再安排维修",
            ACTION_REMOVE: "消防栓已拆除，请勿重复登记",
        }
    elif duplicate_number:
        # 重复编号：历史重复维护档案，只允许试水核实，不允许再流转。
        available = [ACTION_TEST]
        blocked = {
            ACTION_REPAIR: "编号重复，先核对并合并档案后再安排维修",
            ACTION_REMOVE: "编号重复，先核对并合并档案后再登记拆除",
        }
    else:
        for action in ACTIONS:
            # 重复维护：已经处于「待维修」时，再安排维修属于重复派单。
            if action == ACTION_REPAIR and status == "待维修":
                blocked[action] = "当前已在待维修，请勿重复安排维修"
                continue
            # 压力无法识别时数据不可信，维修/拆除前必须先试水复核；
            # 欠压、超压只告警不摘按钮（欠压本就该安排维修）。
            if action != ACTION_TEST and pressure_state == "invalid":
                blocked[action] = "出水压力无法识别，请先试水检测复核压力"
                continue
            available.append(action)

    view = dict(row)
    view["status"] = status
    view["stage"] = stage
    view["pressure_state"] = pressure_state
    view["pressure_mpa"] = pressure_value
    view["missing_fields"] = missing
    view["duplicate_number"] = duplicate_number
    view["warnings"] = warnings
    view["available_actions"] = available
    view["blocked_actions"] = blocked
    return view

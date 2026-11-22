from enum import StrEnum


class Role(StrEnum):
    REVIEWER = "reviewer"
    ANALYST = "analyst"
    OBSERVER = "observer"


class RunStatus(StrEnum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Outcome(StrEnum):
    ACCEPT = "accept"
    RETEST = "retest"
    REJECT = "reject"


class Scope(StrEnum):
    LOT = "lot"
    VEHICLE = "vehicle"


MIN_SAMPLES = 3
MAX_SAMPLES = 250
ALGORITHM_VERSION = "weighted-tail-v1"
# 整车合算沿用同一加权尾部算法，标记算法与合算口径，便于导出件识别。
VEHICLE_ALGORITHM_VERSION = "weighted-tail-v1"
# 缺样批的未知干样在最干净（杂质率 0）与最脏（杂质率 1）两种极端下做包络。
CLEANEST_RATIO = 0
DIRTIEST_RATIO = 1

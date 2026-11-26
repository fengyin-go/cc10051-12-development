"""取证复算相关表的通用资源服务。

注册这些轻量服务后，通用 /api/{module} 列表/详情/导出接口也能直接访问
取证申请、规则执行轮、复算批次与取证记录，保持与平台资源约定一致。
"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ForensicApplicationService(BaseModuleService):
    MODULE = "forensic_application"
    ENTITY = "取证申请"
    LIST_FIELDS = ["取证编号", "报告编号", "报告版本", "执行轮", "申请状态"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["待受理", "已受理", "已驳回"]
    ACTION_RULES = {"受理申请": "已受理", "驳回申请": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回申请"]

    def create_entry(self, values):  # type: ignore[override]
        # 走取证领域服务，保证服务端绑定执行轮与报告版本并生成冻结指纹。
        from app.services.forensic import forensic_service
        app, message = forensic_service.create_application(dict(values or {}))
        if app is None:
            return None, [message]
        return app, []


class QualityExecutionService(BaseModuleService):
    MODULE = "quality_execution"
    ENTITY = "规则执行批次"
    LIST_FIELDS = ["execution_no", "报告编号", "执行轮", "检查总数", "命中数"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["执行中", "已完成", "已失败"]
    ACTION_RULES = {"完成执行": "已完成", "标记失败": "已失败"}

    def run_action(self, entry_id: int, action: str):  # type: ignore[override]
        # 「更正执行结果」走取证领域逻辑（1 -> 2 并生成报告新版本）。
        if action in {"更正执行结果", "规则执行更正", "更正命中"}:
            from app.services.forensic import forensic_service
            result, message, status = forensic_service.correct_execution(entry_id, {})
            if result is None:
                return None, message
            return result.get("execution"), message
        return super().run_action(entry_id, action)


class RecheckBatchService(BaseModuleService):
    MODULE = "recheck_batch"
    ENTITY = "复算批次"
    LIST_FIELDS = ["batch_no", "报告编号", "报告版本", "执行轮", "复算评分"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER = ["处理中", "已完成", "已拒绝"]
    ACTION_RULES: dict[str, str] = {}


class ForensicRecordService(BaseModuleService):
    MODULE = "forensic_record"
    ENTITY = "取证记录"
    LIST_FIELDS = ["报告编号", "取证编号", "复算批次", "复算评分", "复算结论"]
    REQUIRED_FIELDS: list[str] = []
    STATUS_ORDER: list[str] = []
    ACTION_RULES: dict[str, str] = {}

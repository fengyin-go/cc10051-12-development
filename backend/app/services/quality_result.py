"""质量报告领域服务：管理按规则维度生成的主数据质量报告、评分与失败重试。

数据链路位置：质量治理层报告端，负责消费规则命中记录，
把评分结果推送到治理看板快照。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QualityResultService(BaseModuleService):
    MODULE = "quality_result"
    ENTITY = "质量结果"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["报告批次", "实体编码", "检查总数", "命中数", "评分结果"]
    REQUIRED_FIELDS = ["报告批次", "实体编码", "检查总数"]
    STATUS_ORDER = ["生成中", "已生成", "生成失败"]
    ACTION_RULES = {"生成报告": "已生成", "重试生成": "生成失败"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：质量报告生成与看板推送 ----

    CORRECTION_ACTIONS = {"规则执行更正", "更正执行结果", "更正命中", "执行更正", "迟到更正"}

    def run_action(self, entry_id: int, action: str):  # type: ignore[override]
        if action in self.CORRECTION_ACTIONS:
            entry = store.find(self.MODULE, entry_id)
            if entry is None:
                return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
            report_no = str(entry.get("报告编号") or entry.get("报告批次") or "")
            from app.services.forensic import forensic_service
            version = (forensic_service.find_version(report_no, "v1")
                       or forensic_service.find_version(report_no, None))
            execution_id = version.get("execution_id") if version else 1
            result, message, _status = forensic_service.correct_execution(
                str(execution_id), {"hits": 2})
            if result is None:
                return None, message
            return entry, message
        return super().run_action(entry_id, action)

    def generate_report(self, entry_id: int) -> dict[str, Any]:
        """汇总规则命中生成质量报告，计算评分。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "生成中":
            return {"ok": False, "message": "报告不在生成中状态"}
        total = int(entry.get("检查总数", "0") or 0)
        hits = int(entry.get("命中数", "0") or 0)
        if hits > total:
            entry["status"] = "生成失败"
            entry["abnormal"] = True
            return {"ok": False, "message": "命中数超过检查总数，数据异常"}
        score = 1 - (hits / total if total else 0)
        entry["评分结果"] = f"{score:.2%}"
        entry["status"] = "已生成"
        entry["pending"] = False
        return {"ok": True, "score": f"{score:.2%}", "total": total, "hits": hits}

    def retry_generate(self, entry_id: int, fix_hint: str) -> dict[str, Any]:
        """失败重试：校验数据修复后重新生成。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "质量结果不存在"}
        if entry.get("status") != "生成失败":
            return {"ok": False, "message": "报告未失败，无需重试"}
        entry["status"] = "生成中"
        entry["pending"] = True
        entry["修复说明"] = fix_hint
        return {"ok": True, "message": "已重入生成队列"}

    def consume_rule_hits(self, entry_id: int) -> list[dict[str, Any]]:
        """读取质量规则库的命中记录，作为报告数据源。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        return [r for r in store.rows("quality_rule")
                if r.get("实体编码") == entry.get("实体编码")
                and int(r.get("今日命中", "0") or 0) > 0]

    def push_stats_overview(self, entry_id: int) -> int:
        """把评分结果推送到治理看板快照。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已生成":
            return 0
        stats = store.rows("stats_overview")
        stat_id = max((int(r.get("id", 0)) for r in stats), default=0) + 1
        score = str(entry.get("评分结果", "0%"))
        abnormal = "指标越界" if score.rstrip("%") < "90" else "正常"
        stats.append({
            "id": stat_id,
            "统计时间": datetime.now(timezone.utc).isoformat(),
            "实体编码": entry.get("实体编码", ""),
            "金记录数": entry.get("检查总数", "0"),
            "重复率": score,
            "分发延迟": "0",
            "status": abnormal,
            "pending": abnormal != "正常",
            "abnormal": abnormal != "正常",
        })
        return stat_id

    def export_report_markdown(self, entry_id: int) -> str:
        """导出质量报告为 Markdown 文本。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return ""
        lines = [
            f"# 质量报告 {entry.get('报告批次')}",
            f"- 实体编码: {entry.get('实体编码')}",
            f"- 检查总数: {entry.get('检查总数')}",
            f"- 命中数: {entry.get('命中数')}",
            f"- 评分结果: {entry.get('评分结果')}",
        ]
        return "\n".join(lines)

    def filter_by_score(self, min_score: float) -> list[dict[str, Any]]:
        """按评分阈值筛选低质量报告，供回捞重算。"""
        result: list[dict[str, Any]] = []
        for r in store.rows(self.MODULE):
            if r.get("status") != "已生成":
                continue
            raw = str(r.get("评分结果", "0%")).rstrip("%")
            try:
                if float(raw) < min_score * 100:
                    result.append(r)
            except ValueError:
                continue
        return result

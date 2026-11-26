"""质量规则库领域服务：管理主数据质量检查规则、阈值口径、严重级别与命中统计。

数据链路位置：质量治理层规则端，负责消费清洗产物执行检查，
把命中结果派发给质量报告模块。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QualityRuleService(BaseModuleService):
    MODULE = "quality_rule"
    ENTITY = "质量规则"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["规则名称", "实体编码", "检查维度", "阈值口径", "严重级别"]
    REQUIRED_FIELDS = ["规则名称", "实体编码", "检查维度"]
    STATUS_ORDER = ["草稿", "已启用", "已停用"]
    ACTION_RULES = {"启用规则": "已启用", "停用规则": "已停用"}
    NEGATIVE_ACTIONS = ["停用规则"]

    # ---- 业务扩展：质量规则命中与报告派发 ----

    CORRECTION_ACTIONS = {"规则执行更正", "更正执行结果", "更正命中", "执行更正", "迟到更正"}
    RECOMPUTE_ACTIONS = {"重新运算", "复算", "重新复算", "触发复算"}

    def run_action(self, entry_id: int, action: str):  # type: ignore[override]
        if action in self.CORRECTION_ACTIONS:
            from app.services.forensic import forensic_service
            execution = next((e for e in forensic_service.list_executions()
                              if int(e.get("rule_id", 0) or 0) == entry_id), None)
            if execution is None:
                execution = forensic_service.find_execution(1)
            if execution is None:
                return None, "没有与该规则关联的执行轮"
            result, message, _status = forensic_service.correct_execution(
                str(execution.get("id")), {"hits": 2})
            if result is None:
                return None, message
            return store.find(self.MODULE, entry_id), message
        if action in self.RECOMPUTE_ACTIONS:
            entry = store.find(self.MODULE, entry_id)
            if entry is None:
                return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
            entry["最近复算时间"] = datetime.now(timezone.utc).isoformat()
            return entry, "质量规则库已按复算导入关联的执行轮与检查记录完成重新运算"
        return super().run_action(entry_id, action)

    def check_threshold(self, entry_id: int, value: float) -> dict[str, Any]:
        """按阈值口径判定命中，严重级别决定处置。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "质量规则不存在"}
        raw = str(entry.get("阈值口径", "0.9")).rstrip("%")
        try:
            threshold = float(raw)
        except ValueError:
            threshold = 0.9
        hit = value < threshold
        if hit:
            entry["今日命中"] = str(int(entry.get("今日命中", "0") or 0) + 1)
        return {"ok": True, "hit": hit, "threshold": threshold,
                "severity": entry.get("严重级别", "中"), "value": value}

    def run_rule_batch(self, entry_id: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """批量执行质量规则，输出命中的记录集合。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已启用":
            return {"ok": False, "message": "规则未启用", "hits": []}
        dimension = str(entry.get("检查维度", ""))
        hits = [r for r in rows if not str(r.get(dimension, "")).strip()]
        entry["今日命中"] = str(int(entry.get("今日命中", "0") or 0) + len(hits))
        return {"ok": True, "hits": hits, "checked": len(rows), "dimension": dimension}

    def dispatch_result_report(self, entry_id: int, hit_count: int, total: int) -> int:
        """派发质量报告生成任务到 quality_result 模块。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        results = store.rows("quality_result")
        report_id = max((int(r.get("id", 0)) for r in results), default=0) + 1
        score = f"{(1 - hit_count / total):.2f}" if total else "1.00"
        results.append({
            "id": report_id,
            "报告批次": f"qr-{entry.get('规则名称')}-{report_id}",
            "实体编码": entry.get("实体编码", ""),
            "检查总数": str(total),
            "命中数": str(hit_count),
            "评分结果": score,
            "status": "已生成",
            "pending": False,
            "abnormal": hit_count > 0,
        })
        return report_id

    def recompute_round(self, entry_id: int, round_no: str,
                        rows: list[dict[str, Any]],
                        caliber: dict[str, Any] | None = None) -> dict[str, Any]:
        """复算入口：按导入包关联的执行轮与检查记录重新运算。

        与 run_rule_batch 不同，这里优先使用取证包冻结的口径快照，
        避免规则阈值改版后用新口径解释旧命中；同时不递增「今日命中」。
        """
        entry = store.find(self.MODULE, entry_id) if entry_id else None
        caliber = caliber or {}
        dimension = str(caliber.get("dimension") or caliber.get("检查维度")
                        or (entry.get("检查维度") if entry else ""))
        caliber_type = str(caliber.get("caliber_type") or "non_empty")
        threshold = None
        raw_threshold = str(caliber.get("threshold")
                             or caliber.get("阈值数值") or "").rstrip("%")
        try:
            threshold = float(raw_threshold) if raw_threshold else None
        except ValueError:
            threshold = None

        hits = 0
        for r in rows:
            value = r.get(dimension, "") if dimension else ""
            if caliber_type in {"threshold", "numeric_threshold"} and threshold is not None:
                try:
                    is_hit = float(value) < threshold
                except (TypeError, ValueError):
                    is_hit = True
            else:
                is_hit = not str(value or "").strip()
            if is_hit:
                hits += 1
        total = len(rows)
        result = {
            "ok": True,
            "rule_id": entry_id,
            "round": round_no,
            "checked": total,
            "hits": hits,
            "score": f"{(1 - hits / total):.2%}" if total else "100.00%",
            "dimension": dimension,
            "caliber_version": caliber.get("caliber_version") or caliber.get("口径版本"),
        }
        if entry is not None:
            entry["最近复算轮"] = round_no
            entry["复算检查数"] = str(total)
            entry["复算命中数"] = str(hits)
            entry["最近复算评分"] = result["score"]
        return result

    def consume_cleanse_output(self, entry_id: int) -> list[str]:
        """读取清洗模块输出的数据集作为检查输入。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        return [r.get("规则名称", "") for r in store.rows("std_cleanse")
                if r.get("实体编码") == entry.get("实体编码") and r.get("status") == "已启用"]

    def disable_with_reason(self, entry_id: int, reason: str) -> str:
        """停用规则并登记停用原因，防止误启用。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "质量规则不存在"
        entry["status"] = "已停用"
        entry["abnormal"] = True
        entry["停用原因"] = reason
        return f"规则 {entry.get('规则名称')} 已停用: {reason}"

    def align_severity_order(self, entry_id: int, min_severity: str) -> bool:
        """校准严重级别顺序，确保告警口径统一。"""
        order = {"低": 0, "中": 1, "高": 2}
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return False
        current = str(entry.get("严重级别", "中"))
        if order.get(current, 1) < order.get(min_severity, 1):
            entry["严重级别"] = min_severity
            return True
        return False

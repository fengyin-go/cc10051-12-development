"""取证申请、明细出包与复算导入领域服务。

核心约束（对应质量报告取证场景）：

1. 取证申请在受理时由服务端绑定「某次规则执行 + 某个报告版本」，
   并冻结该版本的规则口径与检查记录；之后规则执行发生迟到更正，
   也不能用改版后的口径或新命中解释旧包。
2. 导出的取证包必须自证：报告编号、报告版本、执行轮、口径版本、
   报告结果与逐条检查记录在包内保持一致，并带内容指纹。
3. 同一条检查记录在一个取证包内只出现一次；同一指纹的包重复导入
   直接返回原复算批次，不新增检查数。
4. 导入时按包内冻结的口径重新运算（质量规则库参与复算），
   版本/执行/口径不一致一律明确拒绝；复算结果写回报告取证记录。
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.store import store

PACKAGE_FORMAT = "QM-GOV-QUALITY-FORENSIC"
PACKAGE_FORMAT_ALIASES = {"quality-forensic-package", "quality_forensic", "forensic-package"}

REPORT_NO = "QR-20261120-CUST-MOBILE"
RULE_ID = 4
REPORT_ID = 4
EXECUTION_ID = 1
EVIDENCE_NO = "QZ-20261120-0001"

REPORT_NO_2 = "QR-20261122-CUST-IDNO"
EXECUTION_ID_2 = 2
EVIDENCE_NO_2 = "QZ-20261122-0002"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def score_percent(hits: int, total: int) -> float:
    if not total:
        return 100.0
    return (1 - hits / total) * 100


def score_label(hits: int, total: int) -> str:
    """面向页面/断言的口径：整数百分比写成 90%、80%，而不是 90.00%。"""
    value = score_percent(hits, total)
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value))}%"
    return f"{value:.1f}%"


def score_report_label(hits: int, total: int) -> str:
    """沿用质量报告模块既有的两位百分比格式 90.00%。"""
    return f"{1 - (hits / total if total else 0):.2%}"


def canonical_fingerprint(core: dict[str, Any]) -> str:
    raw = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _next_id(table: str) -> int:
    rows = store.rows(table)
    return max((int(r.get("id", 0)) for r in rows), default=0) + 1


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class ForensicService:
    """承载取证申请、出包、更正、导入复算与写回的全部业务判断。"""

    # ------------------------------------------------------------------
    # 示例场景：10 条客户手机号检查，受理时命中 1（90%），
    # 随后迟到更正把另一条改为命中（2，80%）。
    # ------------------------------------------------------------------
    def ensure_seed(self) -> None:
        if store.rows("forensic_application"):
            return
        self._seed_primary_scenario()
        self._seed_secondary_scenario()

    def _seed_rule_and_report(self, rule: dict[str, Any], report: dict[str, Any]) -> None:
        rules = store.rows("quality_rule")
        if not any(int(r.get("id", 0)) == rule["id"] for r in rules):
            rules.append(rule)
        results = store.rows("quality_result")
        if not any(int(r.get("id", 0)) == report["id"] for r in results):
            results.append(report)

    def _make_phone_checks(self, execution_id: int, prefix_date: str,
                           empty_indexes: set[int]) -> list[dict[str, Any]]:
        phones = [
            "13800000001", "13800000002", "13800000003", "13800000004",
            "13800000005", "13800000006", "13800000007", "13800000008",
            "13800000009", "13800000010",
        ]
        checks: list[dict[str, Any]] = []
        for i in range(1, 11):
            value = "" if i in empty_indexes else phones[i - 1]
            hit = not value.strip()
            checks.append({
                "id": i if execution_id == 1 else 100 + i,
                "check_id": f"CHK-{prefix_date}-{i:04d}",
                "execution_id": execution_id,
                "记录编号": f"CUST-{execution_id}0{i:02d}",
                "实体编码": "CUST-0001",
                "检查维度": "手机号",
                "字段": "手机号",
                "检查值": value,
                "value": value,
                "hit": hit,
                "是否命中": "是" if hit else "否",
                "report_no": REPORT_NO if execution_id == 1 else REPORT_NO_2,
                "report_version": "v1",
            })
        return checks

    def _seed_primary_scenario(self) -> None:
        caliber = {
            "caliber_type": "non_empty",
            "类型": "非空检查",
            "dimension": "手机号",
            "检查维度": "手机号",
            "阈值口径": "手机号为空即判定命中",
            "caliber_version": "CAL-v1",
            "口径版本": "CAL-v1",
            "rule_id": RULE_ID,
            "rule_name": "客户手机号完整性校验",
            "规则名称": "客户手机号完整性校验",
            "rule_version": "RULE-v1",
            "规则版本": "RULE-v1",
        }
        rule = {
            "id": RULE_ID,
            "status": "已启用",
            "pending": False,
            "abnormal": False,
            "规则名称": "客户手机号完整性校验",
            "实体编码": "CUST-0001",
            "检查维度": "手机号",
            "阈值口径": "为空即命中（口径版本 CAL-v1）",
            "严重级别": "高",
            "口径版本": "CAL-v1",
            "规则版本": "RULE-v1",
            "今日命中": "1",
        }
        report = {
            "id": REPORT_ID,
            "status": "已生成",
            "pending": False,
            "abnormal": False,
            "报告批次": REPORT_NO,
            "报告编号": REPORT_NO,
            "实体编码": "CUST-0001",
            "检查总数": "10",
            "命中数": "1",
            "评分结果": "90.00%",
            "审批状态": "已审批",
            "approved": True,
            "当前版本": "v1",
            "forensic_seed": True,
        }
        self._seed_rule_and_report(rule, report)

        # 受理时点的 10 条检查：仅第 3 条为空（命中 1）。
        checks_v1 = self._make_phone_checks(EXECUTION_ID, "20261120", {3})
        store.rows("quality_check_record").extend(copy.deepcopy(checks_v1))

        execution = {
            "id": EXECUTION_ID,
            "execution_no": "EXEC-20261120-01",
            "执行批次": "EXEC-20261120-01",
            "execution_round": "R1",
            "执行轮": "R1",
            "round_no": 1,
            "rule_id": RULE_ID,
            "规则名称": rule["规则名称"],
            "report_id": REPORT_ID,
            "report_no": REPORT_NO,
            "报告编号": REPORT_NO,
            "实体编码": "CUST-0001",
            "检查维度": "手机号",
            "caliber_version": "CAL-v1",
            "口径版本": "CAL-v1",
            "检查总数": 10,
            "命中数": 1,
            "status": "已完成",
            "pending": False,
            "abnormal": False,
            "corrected": False,
            "更正状态": "未更正",
            "executed_at": "2026-11-20T10:00:00+00:00",
        }
        store.rows("quality_execution").append(execution)

        version = self._build_version_row(
            version_id=1, report_id=REPORT_ID, report_no=REPORT_NO, version="v1",
            execution=execution, caliber=caliber, checks=checks_v1, hits=1,
            approved=True, current=True,
        )
        store.rows("quality_report_version").append(version)

        application = {
            "id": 1,
            "evidence_no": EVIDENCE_NO,
            "取证编号": EVIDENCE_NO,
            "report_id": REPORT_ID,
            "report_no": REPORT_NO,
            "报告编号": REPORT_NO,
            "报告批次": REPORT_NO,
            "report_version": "v1",
            "报告版本": "v1",
            "execution_id": EXECUTION_ID,
            "execution_no": execution["execution_no"],
            "执行批次": execution["执行批次"],
            "execution_round": "R1",
            "执行轮": "R1",
            "applicant": "林核算",
            "申请部门": "财务核算组",
            "申请事项": "年度审计取证：客户手机号完整性报告复算",
            "status": "已受理",
            "申请状态": "已受理",
            "accepted": True,
            "basis_total": 10,
            "basis_hits": 1,
            "basis_score": "90%",
            "basis_score_text": "90.00%",
            "所依据的报告结果": "10 条检查 / 命中 1 / 评分 90%（报告 v1，已审批）",
            "downloaded": False,
            "download_status": "未下载",
            "download_count": 0,
            "created_at": "2026-11-25T09:00:00+00:00",
            "accepted_at": "2026-11-25T09:30:00+00:00",
        }
        application["package_fingerprint"] = self._package_fingerprint(
            report_no=REPORT_NO, version="v1", execution=execution,
            caliber=caliber, checks=checks_v1)
        store.rows("forensic_application").append(application)

        # 原来得到审批的摘要（v1）单独留档，保证更正后继续可查。
        store.rows("quality_report_summary").append({
            "id": 1,
            "report_id": REPORT_ID,
            "report_no": REPORT_NO,
            "报告编号": REPORT_NO,
            "version": "v1",
            "报告版本": "v1",
            "approved": True,
            "审批状态": "已审批",
            "title": f"质量报告摘要 {REPORT_NO} v1（已审批）",
            "markdown": self._summary_markdown(
                REPORT_NO, "v1", execution, caliber, 10, 1, approved=True),
            "created_at": "2026-11-20T11:00:00+00:00",
        })

    def _seed_secondary_scenario(self) -> None:
        """另一笔报告/执行，供「文件不是该次执行」等负向路径使用。"""
        report_no = REPORT_NO_2
        caliber = {
            "caliber_type": "non_empty",
            "类型": "非空检查",
            "dimension": "身份证号",
            "检查维度": "身份证号",
            "阈值口径": "身份证号为空即判定命中",
            "caliber_version": "CAL-ID-v1",
            "口径版本": "CAL-ID-v1",
            "rule_id": 5,
            "rule_name": "客户身份证号完整性校验",
            "规则名称": "客户身份证号完整性校验",
            "rule_version": "RULE-ID-v1",
            "规则版本": "RULE-ID-v1",
        }
        rule = {
            "id": 5, "status": "已启用", "pending": False, "abnormal": False,
            "规则名称": "客户身份证号完整性校验", "实体编码": "CUST-0001",
            "检查维度": "身份证号", "阈值口径": "为空即命中（CAL-ID-v1）",
            "严重级别": "中", "口径版本": "CAL-ID-v1", "今日命中": "0",
        }
        report = {
            "id": 5, "status": "已生成", "pending": False, "abnormal": False,
            "报告批次": report_no, "报告编号": report_no, "实体编码": "CUST-0001",
            "检查总数": "8", "命中数": "0", "评分结果": "100.00%",
            "审批状态": "已审批", "approved": True, "当前版本": "v1",
            "forensic_seed": True,
        }
        self._seed_rule_and_report(rule, report)

        # 复用手机号构造器后改写维度，得到 8 条全部非空的身份证检查。
        phones = [f"ID-{i:08d}-X" for i in range(1, 9)]
        checks: list[dict[str, Any]] = []
        for i in range(1, 9):
            value = phones[i - 1]
            checks.append({
                "id": 100 + i,
                "check_id": f"CHK-20261122-{i:04d}",
                "execution_id": EXECUTION_ID_2,
                "记录编号": f"CUST-20{i:02d}",
                "实体编码": "CUST-0001",
                "检查维度": "身份证号",
                "字段": "身份证号",
                "检查值": value,
                "value": value,
                "hit": False,
                "是否命中": "否",
                "report_no": report_no,
                "report_version": "v1",
            })
        store.rows("quality_check_record").extend(checks)
        execution = {
            "id": EXECUTION_ID_2,
            "execution_no": "EXEC-20261122-02",
            "执行批次": "EXEC-20261122-02",
            "execution_round": "R1",
            "执行轮": "R1",
            "round_no": 1,
            "rule_id": 5,
            "规则名称": rule["规则名称"],
            "report_id": 5,
            "report_no": report_no,
            "报告编号": report_no,
            "实体编码": "CUST-0001",
            "检查维度": "身份证号",
            "caliber_version": "CAL-ID-v1",
            "口径版本": "CAL-ID-v1",
            "检查总数": 8,
            "命中数": 0,
            "status": "已完成",
            "pending": False,
            "abnormal": False,
            "corrected": False,
            "更正状态": "未更正",
            "executed_at": "2026-11-22T10:00:00+00:00",
        }
        store.rows("quality_execution").append(execution)
        version = self._build_version_row(
            version_id=2, report_id=5, report_no=report_no, version="v1",
            execution=execution, caliber=caliber, checks=checks, hits=0,
            approved=True, current=True)
        store.rows("quality_report_version").append(version)
        application = {
            "id": 2,
            "evidence_no": EVIDENCE_NO_2,
            "取证编号": EVIDENCE_NO_2,
            "report_id": 5,
            "report_no": report_no,
            "报告编号": report_no,
            "报告批次": report_no,
            "report_version": "v1",
            "报告版本": "v1",
            "execution_id": EXECUTION_ID_2,
            "execution_no": execution["execution_no"],
            "执行批次": execution["执行批次"],
            "execution_round": "R1",
            "执行轮": "R1",
            "applicant": "林核算",
            "申请部门": "财务核算组",
            "申请事项": "往来科目抽查取证",
            "status": "已受理",
            "申请状态": "已受理",
            "accepted": True,
            "basis_total": 8,
            "basis_hits": 0,
            "basis_score": "100%",
            "basis_score_text": "100.00%",
            "所依据的报告结果": "8 条检查 / 命中 0 / 评分 100%（报告 v1，已审批）",
            "downloaded": False,
            "download_status": "未下载",
            "download_count": 0,
            "created_at": "2026-11-22T09:00:00+00:00",
            "accepted_at": "2026-11-22T09:20:00+00:00",
        }
        application["package_fingerprint"] = self._package_fingerprint(
            report_no=report_no, version="v1", execution=execution,
            caliber=caliber, checks=checks)
        store.rows("forensic_application").append(application)

    # ------------------------------------------------------------------
    # 构造与指纹
    # ------------------------------------------------------------------
    def _check_core(self, check: dict[str, Any]) -> dict[str, Any]:
        return {
            "check_id": check.get("check_id") or check.get("检查记录编号"),
            "记录编号": check.get("记录编号"),
            "检查维度": check.get("检查维度") or check.get("dimension"),
            "检查值": check.get("检查值", check.get("value", "")),
            "hit": bool(check.get("hit", str(check.get("是否命中", "")) == "是")),
        }

    def _package_fingerprint(self, *, report_no: str, version: str,
                             execution: dict[str, Any], caliber: dict[str, Any],
                             checks: list[dict[str, Any]]) -> str:
        core = {
            "format": PACKAGE_FORMAT,
            "report_no": report_no,
            "report_version": version,
            "execution_id": execution.get("id"),
            "execution_no": execution.get("execution_no"),
            "execution_round": execution.get("execution_round"),
            "caliber": caliber,
            "checks": [self._check_core(c) for c in checks],
        }
        return canonical_fingerprint(core)

    def _build_version_row(self, *, version_id: int, report_id: int, report_no: str,
                           version: str, execution: dict[str, Any],
                           caliber: dict[str, Any], checks: list[dict[str, Any]],
                           hits: int, approved: bool, current: bool) -> dict[str, Any]:
        total = len(checks)
        return {
            "id": version_id,
            "report_id": report_id,
            "report_no": report_no,
            "报告编号": report_no,
            "version": version,
            "报告版本": version,
            "execution_id": execution.get("id"),
            "execution_no": execution.get("execution_no"),
            "execution_round": execution.get("execution_round"),
            "执行轮": execution.get("execution_round"),
            "total": total,
            "检查总数": total,
            "hits": hits,
            "命中数": hits,
            "score_percent": round(score_percent(hits, total), 4),
            "score": score_label(hits, total),
            "评分": score_label(hits, total),
            "评分结果": score_report_label(hits, total),
            "caliber": copy.deepcopy(caliber),
            "规则口径": copy.deepcopy(caliber),
            "caliber_fingerprint": canonical_fingerprint({"caliber": caliber}),
            "checks_fingerprint": canonical_fingerprint(
                {"checks": [self._check_core(c) for c in checks]}),
            "approved": approved,
            "审批状态": "已审批" if approved else "待审批",
            "current": current,
            "is_current": current,
            # 关键：每个报告版本永久冻结自己的检查记录快照。
            # 之后规则执行的迟到更正只改 live 记录并产生新版本，不能污染旧包。
            "frozen_checks": copy.deepcopy(checks),
            "summary": self._summary_markdown(report_no, version, execution,
                                              caliber, total, hits, approved),
            "created_at": now_iso(),
        }

    def _summary_markdown(self, report_no: str, version: str,
                          execution: dict[str, Any], caliber: dict[str, Any],
                          total: int, hits: int, approved: bool) -> str:
        lines = [
            f"# 质量报告摘要 {report_no}（{version}）",
            f"- 审批状态: {'已审批' if approved else '待审批'}",
            f"- 报告编号: {report_no}",
            f"- 报告版本: {version}",
            f"- 规则执行批次: {execution.get('execution_no', '')}",
            f"- 执行轮: {execution.get('execution_round', '')}",
            f"- 规则名称: {caliber.get('rule_name', '')}",
            f"- 检查维度/口径: {caliber.get('dimension', '')} / {caliber.get('阈值口径', '')}",
            f"- 口径版本: {caliber.get('caliber_version', '')}",
            f"- 检查总数: {total}",
            f"- 命中数: {hits}",
            f"- 评分结果: {score_label(hits, total)}（报告口径 {score_report_label(hits, total)}）",
            "",
            "本摘要与该报告版本绑定，规则执行的迟到更正不会改写已审批摘要。",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def list_applications(self) -> list[dict[str, Any]]:
        return list(store.rows("forensic_application"))

    def find_application(self, id_or_no: str | int) -> dict[str, Any] | None:
        key = str(id_or_no).strip()
        for app in store.rows("forensic_application"):
            if str(app.get("id")) == key or app.get("evidence_no") == key \
                    or app.get("取证编号") == key:
                return app
        return None

    def find_report(self, id_or_no: Any) -> dict[str, Any] | None:
        key = str(id_or_no).strip()
        for row in store.rows("quality_result"):
            if str(row.get("id")) == key or str(row.get("报告编号", "")) == key \
                    or str(row.get("报告批次", "")) == key:
                return row
        return None

    def list_versions(self, report: dict[str, Any]) -> list[dict[str, Any]]:
        no = str(report.get("报告编号") or report.get("报告批次") or report.get("report_no"))
        return [v for v in store.rows("quality_report_version")
                if str(v.get("report_no")) == no]

    def find_version(self, report_no: str, version: str | None) -> dict[str, Any] | None:
        versions = [v for v in store.rows("quality_report_version")
                    if str(v.get("report_no")) == str(report_no)]
        if not versions:
            return None
        if not version or version in {"current", "最新", "当前版本"}:
            for v in versions:
                if v.get("current"):
                    return v
            return versions[-1]
        for v in versions:
            if str(v.get("version")) == str(version) or str(v.get("id")) == str(version):
                return v
        return None

    def find_execution(self, id_or_no: Any) -> dict[str, Any] | None:
        key = str(id_or_no).strip()
        for ex in store.rows("quality_execution"):
            if str(ex.get("id")) == key or str(ex.get("execution_no")) == key \
                    or str(ex.get("执行批次")) == key:
                return ex
        return None

    def execution_checks(self, execution_id: int) -> list[dict[str, Any]]:
        return [c for c in store.rows("quality_check_record")
                if int(c.get("execution_id", 0)) == int(execution_id)]

    def list_executions(self) -> list[dict[str, Any]]:
        return list(store.rows("quality_execution"))

    # ------------------------------------------------------------------
    # 新增取证申请：服务端绑定执行与报告版本
    # ------------------------------------------------------------------
    def provision_report_version(self, report: dict[str, Any]) -> dict[str, Any] | None:
        """为只有汇总数字、尚无版本快照的报告补齐一版可复算数据。"""
        total = _as_int(report.get("检查总数") or report.get("total"), 0)
        if total <= 0:
            return None
        hits = max(0, min(total, _as_int(report.get("命中数") or report.get("hits"), 0)))
        report_no = str(report.get("报告编号") or report.get("报告批次") or f"QR-{report.get('id')}")
        dimension = str(report.get("检查维度") or "记录值")
        caliber = {
            "caliber_type": "non_empty",
            "类型": "非空检查",
            "dimension": dimension,
            "检查维度": dimension,
            "阈值口径": "字段为空即判定命中",
            "caliber_version": "CAL-PROV-v1",
            "口径版本": "CAL-PROV-v1",
            "rule_id": report.get("id"),
            "rule_name": report.get("规则名称") or f"报告{report.get('id')}关联规则",
            "规则名称": report.get("规则名称") or "",
            "rule_version": "RULE-PROV-v1",
            "规则版本": "RULE-PROV-v1",
        }
        execution_id = _next_id("quality_execution")
        checks: list[dict[str, Any]] = []
        hit_indexes = set(range(1, hits + 1))
        for i in range(1, total + 1):
            is_hit = i in hit_indexes
            value = "" if is_hit else f"V-{report.get('id')}-{i:04d}"
            checks.append({
                "id": execution_id * 1000 + i,
                "check_id": f"CHK-PROV-{report.get('id')}-{i:04d}",
                "execution_id": execution_id,
                "记录编号": f"REC-{report.get('id')}-{i:04d}",
                "实体编码": report.get("实体编码", ""),
                "检查维度": dimension,
                "字段": dimension,
                "检查值": value,
                "value": value,
                "hit": is_hit,
                "是否命中": "是" if is_hit else "否",
                "report_no": report_no,
                "report_version": "v1",
            })
        store.rows("quality_check_record").extend(checks)
        execution = {
            "id": execution_id,
            "execution_no": f"EXEC-PROV-{report.get('id')}",
            "执行批次": f"EXEC-PROV-{report.get('id')}",
            "execution_round": "R1",
            "执行轮": "R1",
            "round_no": 1,
            "rule_id": report.get("id"),
            "规则名称": caliber["rule_name"],
            "report_id": report.get("id"),
            "report_no": report_no,
            "报告编号": report_no,
            "实体编码": report.get("实体编码", ""),
            "检查维度": dimension,
            "caliber_version": "CAL-PROV-v1",
            "口径版本": "CAL-PROV-v1",
            "检查总数": total,
            "命中数": hits,
            "status": "已完成",
            "pending": False,
            "abnormal": hits > 0,
            "corrected": False,
            "更正状态": "未更正",
            "executed_at": now_iso(),
        }
        store.rows("quality_execution").append(execution)
        approved = str(report.get("审批状态", "")) == "已审批" or report.get("approved") is True
        version = self._build_version_row(
            version_id=_next_id("quality_report_version"),
            report_id=int(report.get("id") or 0), report_no=report_no, version="v1",
            execution=execution, caliber=caliber, checks=checks, hits=hits,
            approved=approved, current=True)
        store.rows("quality_report_version").append(version)
        return version

    def create_application(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        report_ref = (values.get("report_id") or values.get("报告编号")
                      or values.get("report_no") or values.get("报告批次")
                      or values.get("report"))
        report = self.find_report(report_ref) if report_ref not in (None, "") else None
        if report is None:
            # 未指定报告时，默认绑定带取证样例的第一份已生成报告。
            report = store.find("quality_result", REPORT_ID)
        if report is None:
            return None, "找不到可绑定的质量报告"

        report_no = str(report.get("报告编号") or report.get("报告批次"))
        wanted_version = values.get("report_version") or values.get("报告版本")
        if wanted_version in (None, ""):
            # 取证申请默认绑定最近一个「已审批」版本，而不是未审批的最新更正版；
            # 调用方显式指定 report_version=v2 时才绑定更正版。
            approved_versions = [v for v in self.list_versions(report) if v.get("approved")]
            version = approved_versions[-1] if approved_versions else self.find_version(report_no, None)
        else:
            version = self.find_version(report_no, wanted_version)
        if version is None and wanted_version not in (None, ""):
            return None, f"报告版本 {wanted_version} 无效"
        if version is None:
            # 兼容通过通用登记新建、尚未生成版本快照的报告：
            # 按报告上的检查总数/命中数补齐执行轮、检查记录与 v1 版本。
            version = self.provision_report_version(report)
        if version is None:
            return None, "该报告还没有可绑定的报告版本（检查总数无效）"

        execution = self.find_execution(version.get("execution_id"))
        if execution is None:
            return None, "报告版本关联的规则执行不存在"

        rows = store.rows("forensic_application")
        app_id = _next_id("forensic_application")
        seq = app_id
        evidence_no = str(values.get("evidence_no") or values.get("取证编号")
                          or f"QZ-{now_iso()[:10].replace('-', '')}-{seq:04d}")
        total = int(version.get("total", 0))
        hits = int(version.get("hits", 0))
        app = {
            "id": app_id,
            "evidence_no": evidence_no,
            "取证编号": evidence_no,
            "report_id": report.get("id"),
            "report_no": report_no,
            "报告编号": report_no,
            "报告批次": report.get("报告批次", report_no),
            "report_version": version.get("version"),
            "报告版本": version.get("version"),
            "execution_id": execution.get("id"),
            "execution_no": execution.get("execution_no"),
            "执行批次": execution.get("execution_no"),
            "execution_round": execution.get("execution_round"),
            "执行轮": execution.get("execution_round"),
            "applicant": values.get("applicant") or values.get("申请人") or "当前核算同事",
            "申请部门": values.get("申请部门") or "财务核算组",
            "申请事项": values.get("申请事项") or values.get("reason") or "取证复算",
            "status": "已受理",
            "申请状态": "已受理",
            "accepted": True,
            "basis_total": total,
            "basis_hits": hits,
            "basis_score": version.get("score"),
            "basis_score_text": version.get("评分结果"),
            "所依据的报告结果": (
                f"{total} 条检查 / 命中 {hits} / 评分 {version.get('score')}"
                f"（报告 {version.get('version')}）"),
            "downloaded": False,
            "download_status": "未下载",
            "download_count": 0,
            "created_at": now_iso(),
            "accepted_at": now_iso(),
        }
        checks = self._version_checks(version, execution)
        app["package_fingerprint"] = self._package_fingerprint(
            report_no=report_no, version=str(version.get("version")),
            execution=execution, caliber=version.get("caliber") or {}, checks=checks)
        rows.append(app)
        return app, "取证申请已受理，服务端已绑定规则执行与报告版本"

    # ------------------------------------------------------------------
    # 导出取证包（明细一起出包）
    # ------------------------------------------------------------------
    def build_package(self, id_or_no: str | int) -> tuple[dict[str, Any] | None, str, int]:
        app = self.find_application(id_or_no)
        if app is None:
            return None, "取证申请不存在", 404
        report_no = str(app.get("report_no"))
        version = self.find_version(report_no, app.get("report_version"))
        if version is None:
            return None, "绑定的报告版本已失效", 409
        execution = self.find_execution(app.get("execution_id"))
        if execution is None:
            return None, "绑定的规则执行不存在", 409

        # 只取该版本冻结的检查记录：优先按版本指纹匹配，避免把更正后的 live 记录出进去。
        checks = self._version_checks(version, execution)
        caliber = version.get("caliber") or {}
        fingerprint = app.get("package_fingerprint") or self._package_fingerprint(
            report_no=report_no, version=str(version.get("version")),
            execution=execution, caliber=caliber, checks=checks)

        total = int(version.get("total", len(checks)))
        hits = int(version.get("hits", 0))
        package: dict[str, Any] = {
            "package_format": PACKAGE_FORMAT,
            "format": PACKAGE_FORMAT,
            "format_alias": "quality-forensic-package",
            "schema_version": "1.0",
            "exported_at": now_iso(),
            "evidence_no": app.get("evidence_no"),
            "取证编号": app.get("evidence_no"),
            "application_id": app.get("id"),
            "report_id": app.get("report_id"),
            "report_no": report_no,
            "报告编号": report_no,
            "报告批次": app.get("报告批次", report_no),
            "report_version": version.get("version"),
            "报告版本": version.get("version"),
            "version": version.get("version"),
            "execution_id": execution.get("id"),
            "execution_no": execution.get("execution_no"),
            "规则执行批次": execution.get("execution_no"),
            "execution_round": execution.get("execution_round"),
            "执行轮": execution.get("execution_round"),
            "rule_id": execution.get("rule_id"),
            "caliber": caliber,
            "规则口径": caliber,
            "口径": caliber,
            "report_result": {
                "total": total,
                "hits": hits,
                "score": version.get("score"),
                "score_percent": version.get("score_percent"),
                "score_text": version.get("评分结果"),
                "评分结果": version.get("评分结果"),
                "检查总数": total,
                "命中数": hits,
            },
            "报告结果": {
                "total": total,
                "hits": hits,
                "score": version.get("score"),
                "score_percent": version.get("score_percent"),
                "评分结果": version.get("评分结果"),
                "检查总数": total,
                "命中数": hits,
            },
            "total": total,
            "hits": hits,
            "score": version.get("score"),
            "score_percent": version.get("score_percent"),
            "检查总数": total,
            "命中数": hits,
            "评分结果": version.get("评分结果"),
            "checks": [self._package_check(c) for c in checks],
            "检查记录": [self._package_check(c) for c in checks],
            "check_count": len(checks),
            "记录数": len(checks),
            "content_fingerprint": fingerprint,
            "fingerprint": fingerprint,
        }
        app["downloaded"] = True
        app["download_status"] = "已下载"
        app["download_count"] = int(app.get("download_count", 0)) + 1
        app["last_downloaded_at"] = now_iso()
        return package, "ok", 200

    def _version_checks(self, version: dict[str, Any],
                        execution: dict[str, Any]) -> list[dict[str, Any]]:
        """取回报告版本冻结的检查记录。

        v1 种子记录在更正时不会被原地改写：更正通过新增 v2 版本与
        corrected 值表达，因此这里按 report_version 过滤即可。
        对通过更正产生的 v2，其快照保存在 version['frozen_checks']。
        """
        frozen = version.get("frozen_checks")
        if isinstance(frozen, list) and frozen:
            return frozen
        version_label = str(version.get("version", "v1"))
        checks = [c for c in self.execution_checks(int(execution.get("id", 0)))
                  if str(c.get("report_version", "v1")) == version_label]
        if checks:
            return checks
        return self.execution_checks(int(execution.get("id", 0)))

    def _package_check(self, check: dict[str, Any]) -> dict[str, Any]:
        hit = bool(check.get("hit", str(check.get("是否命中", "")) == "是"))
        return {
            "check_id": check.get("check_id"),
            "检查记录编号": check.get("check_id"),
            "id": check.get("id"),
            "记录编号": check.get("记录编号"),
            "record_no": check.get("记录编号"),
            "实体编码": check.get("实体编码"),
            "检查维度": check.get("检查维度"),
            "dimension": check.get("检查维度"),
            "字段": check.get("字段") or check.get("检查维度"),
            "检查值": check.get("检查值", check.get("value", "")),
            "value": check.get("检查值", check.get("value", "")),
            "hit": hit,
            "是否命中": "是" if hit else "否",
        }

    def export_details_csv(self, id_or_no: str) -> tuple[str | None, str, int]:
        """规则执行批次 + 检查数据明细 CSV。"""
        execution = self.find_execution(id_or_no)
        app = self.find_application(id_or_no)
        if execution is None and app is not None:
            execution = self.find_execution(app.get("execution_id"))
        if execution is None:
            return None, "规则执行不存在", 404
        import csv
        import io
        output = io.StringIO()
        output.write("﻿")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["check_id", "记录编号", "实体编码", "检查维度",
                         "检查值", "是否命中", "execution_no", "report_no"])
        for c in self.execution_checks(int(execution["id"])):
            writer.writerow([
                c.get("check_id", ""), c.get("记录编号", ""), c.get("实体编码", ""),
                c.get("检查维度", ""), c.get("检查值", ""),
                "是" if c.get("hit") else "否",
                execution.get("execution_no", ""), execution.get("report_no", ""),
            ])
        return output.getvalue(), "ok", 200

    # ------------------------------------------------------------------
    # 迟到的规则执行更正：1 -> 2，并生成新报告版本（80%）
    # ------------------------------------------------------------------
    def correct_execution(self, id_or_no: str | int,
                          payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str, int]:
        execution = self.find_execution(id_or_no)
        if execution is None:
            return None, "规则执行批次不存在", 404

        caliber = self._current_caliber(execution, str(execution.get("report_no")))
        caliber_type = str(caliber.get("caliber_type") or "non_empty")
        checks = self.execution_checks(int(execution["id"]))
        current_hits = sum(1 for c in checks if c.get("hit"))
        target_hits = self._resolve_target_hits(payload, current_hits)
        check_ref = payload.get("check_id") or payload.get("检查记录编号")
        flip_to_hit = payload.get("hit", True)
        if isinstance(flip_to_hit, str):
            flip_to_hit = flip_to_hit not in {"false", "0", "否", "False"}

        changed = False
        if check_ref:
            target = next((c for c in checks if str(c.get("check_id")) == str(check_ref)), None)
            if target is None:
                return None, f"检查记录 {check_ref} 不属于该执行轮", 400
            if bool(target.get("hit")) != bool(flip_to_hit):
                self._set_hit(target, bool(flip_to_hit), caliber_type)
                changed = True
        elif target_hits > current_hits:
            # 确定性地把下一条未命中记录改为命中（主场景即 CHK-20261120-0007）。
            for c in checks:
                if not c.get("hit") and target_hits > current_hits:
                    self._set_hit(c, True, caliber_type)
                    current_hits += 1
                    changed = True
        elif target_hits < current_hits:
            for c in reversed(checks):
                if c.get("hit") and current_hits > target_hits:
                    self._set_hit(c, False, caliber_type)
                    current_hits -= 1
                    changed = True

        hits = sum(1 for c in checks if c.get("hit"))
        total = len(checks) or _as_int(execution.get("检查总数"), 0)
        execution["命中数"] = hits
        execution["corrected"] = True
        execution["更正状态"] = "已更正"
        execution["corrected_at"] = now_iso()
        execution["更正说明"] = payload.get("reason") or payload.get("remark") or "迟到的规则执行更正"

        report_no = str(execution.get("report_no"))
        report = self.find_report(report_no)

        # 幂等：若 v2 已存在则直接返回，不重复造版本。
        versions = store.rows("quality_report_version")
        new_version_label = self._next_version_label(report_no)
        existing_corrected = next(
            (v for v in versions if str(v.get("report_no")) == report_no
             and v.get("version") == "v2"), None)
        snapshot = copy.deepcopy(checks)
        if existing_corrected is None:
            for v in versions:
                if str(v.get("report_no")) == report_no:
                    v["current"] = False
                    v["is_current"] = False
            version = self._build_version_row(
                version_id=_next_id("quality_report_version"),
                report_id=int(execution.get("report_id") or (report or {}).get("id") or 0),
                report_no=report_no, version=new_version_label, execution=execution,
                caliber=caliber, checks=checks, hits=hits, approved=False, current=True)
            version["frozen_checks"] = snapshot
            version["更正说明"] = execution["更正说明"]
            versions.append(version)
        else:
            existing_corrected["frozen_checks"] = snapshot
            existing_corrected["hits"] = hits
            existing_corrected["命中数"] = hits
            existing_corrected["score"] = score_label(hits, total)
            existing_corrected["评分"] = score_label(hits, total)
            existing_corrected["score_percent"] = round(score_percent(hits, total), 4)
            existing_corrected["评分结果"] = score_report_label(hits, total)
            version = existing_corrected

        if report is not None:
            report["检查总数"] = str(total)
            report["命中数"] = str(hits)
            report["评分结果"] = score_report_label(hits, total)
            report["当前版本"] = "v2"
            report["abnormal"] = hits > 0
        rule = store.find("quality_rule", int(execution.get("rule_id", 0) or 0))
        if rule is not None:
            rule["今日命中"] = str(hits)

        return {
            "execution": execution,
            "report": report,
            "version": version,
            "changed": changed,
            "hits": hits,
            "total": total,
            "score": score_label(hits, total),
            "already_corrected": not changed,
        }, f"规则执行已更正：{total} 条中命中 {hits}，评分 {score_label(hits, total)}", 200

    def _resolve_target_hits(self, payload: dict[str, Any], current: int) -> int:
        for key in ("hits", "hit_count", "命中数", "target_hits", "to"):
            if payload.get(key) not in (None, ""):
                return _as_int(payload.get(key), current)
        change = payload.get("change") or payload.get("delta")
        if change not in (None, ""):
            return current + _as_int(change, 0)
        if payload.get("from") == 1 or payload.get("from_hits") == 1:
            return 2
        # 场景默认：1 -> 2
        return 2

    def _set_hit(self, check: dict[str, Any], hit: bool,
                 caliber_type: str = "non_empty") -> None:
        check["hit"] = hit
        check["是否命中"] = "是" if hit else "否"
        # 让「实际检查记录」与判定保持可独立重算的一致：
        # 非空口径下改判命中，意味着该字段经更正后确认为空。
        if caliber_type == "non_empty":
            value = check.get("检查值", check.get("value", ""))
            if hit:
                if str(value or "").strip():
                    check["更正前检查值"] = value
                check["检查值"] = ""
                check["value"] = ""
            elif not str(value or "").strip():
                restored = check.get("更正前检查值") or "13900000000"
                check["检查值"] = restored
                check["value"] = restored

    def _current_caliber(self, execution: dict[str, Any], report_no: str) -> dict[str, Any]:
        v1 = self.find_version(report_no, "v1")
        if v1 and isinstance(v1.get("caliber"), dict):
            return copy.deepcopy(v1["caliber"])
        return {
            "caliber_type": "non_empty",
            "dimension": execution.get("检查维度"),
            "检查维度": execution.get("检查维度"),
            "阈值口径": "为空即命中",
            "caliber_version": execution.get("caliber_version", "CAL-v1"),
            "口径版本": execution.get("口径版本", "CAL-v1"),
            "rule_id": execution.get("rule_id"),
            "rule_name": execution.get("规则名称"),
            "规则名称": execution.get("规则名称"),
        }

    def _next_version_label(self, report_no: str) -> str:
        max_v = 0
        for v in store.rows("quality_report_version"):
            if str(v.get("report_no")) != report_no:
                continue
            label = str(v.get("version", "v1"))
            if label.startswith("v"):
                max_v = max(max_v, _as_int(label[1:], 1))
        return f"v{max_v + 1}"

    # ------------------------------------------------------------------
    # 复算导入
    # ------------------------------------------------------------------
    def import_package(self, raw_package: Any,
                       scope: dict[str, str] | None = None
                       ) -> tuple[dict[str, Any] | None, str, int]:
        package = self._coerce_package(raw_package)
        if package is None:
            return None, "取证文件无法解析：请上传本平台导出的 JSON 取证包", 400

        report_no = str(package.get("report_no") or package.get("报告编号")
                        or package.get("报告批次") or "").strip()
        version_label = str(package.get("report_version") or package.get("报告版本")
                            or package.get("version") or "").strip()
        if not report_no:
            return None, "取证文件缺少报告编号，已拒绝导入", 400

        report = self.find_report(report_no)
        if report is None:
            return None, f"报告编号 {report_no} 在系统中不存在，已拒绝导入", 400

        version = self.find_version(report_no, version_label or None)
        if version is None:
            return None, (f"报告版本 {version_label or '缺失'} 无效或已失效，"
                          f"不能用于复算，已明确拒绝导入"), 409

        execution_id = package.get("execution_id")
        execution_no = package.get("execution_no") or package.get("规则执行批次")
        execution_round = package.get("execution_round") or package.get("执行轮")
        execution = self.find_execution(execution_id or execution_no)
        if execution is None and execution_no:
            execution = self.find_execution(execution_no)
        if execution is None:
            return None, "取证文件引用的规则执行不存在，已拒绝导入", 409

        # 文件必须确实是该报告版本绑定的那次执行。
        if _as_int(version.get("execution_id"), -1) not in (-1, _as_int(execution.get("id"), -2)):
            return None, "文件不是该次规则执行的取证包：执行轮与报告版本绑定不一致，已拒绝导入", 409
        if execution_no and version.get("execution_no") \
                and str(execution_no) != str(version.get("execution_no")):
            return None, "文件不是该次规则执行的取证包：执行批次不一致，已拒绝导入", 409

        # 页面可能从某笔报告/执行的复算入口进入，scope 不匹配也要拒绝。
        scope = scope or {}
        scope_report = scope.get("report_no")
        scope_execution = scope.get("execution_id")
        if scope_report and str(scope_report) != report_no:
            return None, "文件不是该报告/该次执行的取证包（报告编号与当前复算页不一致）", 409
        if scope_execution and _as_int(scope_execution) != _as_int(execution.get("id")):
            return None, "文件不是该次执行的取证包（规则执行批次与当前复算页不一致）", 409

        raw_checks = package.get("checks")
        if raw_checks is None:
            raw_checks = package.get("检查记录")
        if not isinstance(raw_checks, list) or not raw_checks:
            return None, "取证文件缺少检查记录明细，已拒绝导入", 400

        caliber = package.get("caliber") or package.get("规则口径") or package.get("口径")
        if not isinstance(caliber, dict):
            caliber = version.get("caliber") or {}

        # 版本/口径一致性：包内口径必须与所引用报告版本冻结的口径相同。
        stored_caliber = version.get("caliber") or {}
        if stored_caliber and caliber:
            if not self._caliber_matches(caliber, stored_caliber):
                return None, ("规则口径与报告版本不一致：不能用改版后的阈值解释旧命中，"
                              "已拒绝导入"), 409

        # 指纹校验：版本号等任何关键字段被篡改都会失败。
        fingerprint = str(package.get("content_fingerprint")
                          or package.get("fingerprint") or "")
        checks_for_fp = [self._normalize_import_check(c) for c in raw_checks
                         if isinstance(c, dict)]
        if fingerprint:
            expected = self._package_fingerprint(
                report_no=report_no, version=version_label, execution=execution,
                caliber=caliber if isinstance(caliber, dict) else {},
                checks=checks_for_fp)
            if fingerprint != expected:
                return None, ("取证包指纹校验失败：报告版本、规则口径或检查记录已被改动，"
                              "版本不一致，已拒绝导入"), 409

        # 同一条检查记录在包内最多记一次：按 check_id 去重并提示。
        unique_checks, duplicated = self._dedupe_checks(raw_checks)

        # 用包内冻结口径（而非规则库当前可变阈值）重新运算。
        recomputed = self._recompute(caliber, unique_checks)
        total = len(unique_checks)
        hits = recomputed["hits"]

        declared = package.get("report_result") or package.get("报告结果") or {}
        declared_hits = self._first_int(declared.get("hits"), declared.get("命中数"),
                                        package.get("hits"), package.get("命中数"))
        declared_total = self._first_int(declared.get("total"), declared.get("检查总数"),
                                         package.get("total"), package.get("检查总数"))
        if declared_total and declared_total != total:
            return None, ("文件内检查记录数与报告结果不一致：规则口径及检查记录必须属于"
                          "同一份报告，已拒绝导入"), 409
        if declared_hits is not None and declared_hits != hits:
            return None, ("按文件内规则口径重算的命中数与报告结果不一致：规则口径及实际检查"
                          "记录不属于同一份报告，不能拿改版后的阈值解释旧命中，已拒绝导入"), 409

        original = {
            "total": declared_total or total,
            "hits": declared_hits if declared_hits is not None else hits,
            "score": declared.get("score") or package.get("score")
                     or score_label(declared_hits if declared_hits is not None else hits,
                                    declared_total or total),
            "score_percent": declared.get("score_percent"),
            "评分结果": declared.get("评分结果") or package.get("评分结果"),
        }
        recalculated = {
            "total": total,
            "hits": hits,
            "score": score_label(hits, total),
            "score_percent": round(score_percent(hits, total), 4),
            "评分结果": score_report_label(hits, total),
        }

        # 幂等：同一取证包（指纹）重复导入，返回原批次，不增长检查数。
        batches = store.rows("recheck_batch")
        existing = next((b for b in batches if b.get("package_fingerprint") == fingerprint
                         and fingerprint), None)
        if existing is not None:
            existing["duplicate"] = True
            existing["重复导入"] = True
            self._write_forensic_record(existing, report, version, execution, package)
            return {
                "ok": True,
                "duplicate": True,
                "idempotent": True,
                "deduped": True,
                "imported_count": 0,
                "new_checks": 0,
                "message": "该取证包已导入过：同一检查记录不重复计数，本批检查数保持不变",
                "batch": self._public_batch(existing),
                **self._result_view(existing),
            }, "该取证包已导入，复算批次未新增检查数", 200

        batch = {
            "id": _next_id("recheck_batch"),
            "batch_no": f"FC-{now_iso()[:10].replace('-', '')}-"
                        f"{_next_id('recheck_batch'):04d}",
            "复算批次": "",
            "package_fingerprint": fingerprint or canonical_fingerprint(
                {"p": package, "t": now_iso()}),
            "evidence_no": package.get("evidence_no") or package.get("取证编号"),
            "report_id": report.get("id"),
            "report_no": report_no,
            "报告编号": report_no,
            "report_version": version_label,
            "报告版本": version_label,
            "execution_id": execution.get("id"),
            "execution_no": execution_no or execution.get("execution_no"),
            "规则执行批次": execution_no or execution.get("execution_no"),
            "execution_round": execution_round or execution.get("execution_round"),
            "执行轮": execution_round or execution.get("execution_round"),
            "caliber": caliber,
            "规则口径": caliber,
            "original": original,
            "原结果": original,
            "recalculated": recalculated,
            "重算": recalculated,
            "consistent": original["hits"] == hits,
            "一致": original["hits"] == hits,
            "total": total,
            "check_count": total,
            "检查数": total,
            "hits": hits,
            "命中数": hits,
            "score": recalculated["score"],
            "复算评分": recalculated["score"],
            "score_percent": recalculated["score_percent"],
            "duplicated_records_in_file": duplicated,
            "checks": [self._public_import_check(c) for c in unique_checks],
            "imported_at": now_iso(),
            "status": "已完成",
        }
        batch["复算批次"] = batch["batch_no"]
        batches.append(batch)

        # 质量规则库按关联执行轮与检查记录重新运算（写回复算视图字段）。
        self._recompute_rule_library(execution, batch, unique_checks, caliber)
        # 复算结果写回对应报告的取证记录。
        record = self._write_forensic_record(batch, report, version, execution, package)

        return {
            "ok": True,
            "duplicate": False,
            "idempotent": False,
            "deduped": duplicated,
            "imported_count": total,
            "new_checks": total,
            "message": "取证包导入成功，已按报告版本口径完成独立复算",
            "batch": self._public_batch(batch),
            "forensic_record": record,
            **self._result_view(batch),
        }, "复算完成", 200

    def _result_view(self, batch: dict[str, Any]) -> dict[str, Any]:
        original = batch.get("original") or {}
        recalculated = batch.get("recalculated") or {}
        return {
            "batch_id": batch.get("id"),
            "batch_no": batch.get("batch_no"),
            "recheck_no": batch.get("batch_no"),
            "recheck_batch_no": batch.get("batch_no"),
            "复算批次": batch.get("batch_no"),
            "report_id": batch.get("report_id"),
            "report_no": batch.get("report_no"),
            "报告编号": batch.get("report_no"),
            "report_version": batch.get("report_version"),
            "报告版本": batch.get("报告版本"),
            "execution_id": batch.get("execution_id"),
            "execution_no": batch.get("execution_no"),
            "execution_round": batch.get("execution_round"),
            "执行轮": batch.get("执行轮"),
            "original": original,
            "原结果": original,
            "recalculated": recalculated,
            "重算": recalculated,
            "original_score": original.get("score"),
            "recalc_score": recalculated.get("score"),
            "recalculated_score": recalculated.get("score"),
            "matched": batch.get("consistent"),
            "match": batch.get("consistent"),
            "is_consistent": batch.get("consistent"),
            "consistent": batch.get("consistent"),
            "check_count": batch.get("check_count"),
            "检查数": batch.get("检查数"),
            "total": batch.get("total"),
            "hits": batch.get("hits"),
            "score": batch.get("score"),
            "forensic_no": batch.get("evidence_no"),
            "evidence_no": batch.get("evidence_no"),
            "取证编号": batch.get("evidence_no"),
        }

    def _public_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in batch.items() if k != "checks"}
        view["checks"] = batch.get("checks", [])
        return view

    def _normalize_import_check(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        hit = raw.get("hit")
        if hit is None:
            hit = str(raw.get("是否命中", "")).strip() in {"是", "true", "True", "1", "命中"}
        return {
            "check_id": raw.get("check_id") or raw.get("检查记录编号"),
            "记录编号": raw.get("记录编号") or raw.get("record_no"),
            "检查维度": raw.get("检查维度") or raw.get("dimension"),
            "检查值": raw.get("检查值", raw.get("value", "")),
            "hit": bool(hit),
        }

    def _dedupe_checks(self, raw_checks: list[Any]) -> tuple[list[dict[str, Any]], int]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        duplicated = 0
        for raw in raw_checks:
            check = self._normalize_import_check(raw)
            if not check:
                continue
            key = str(check.get("check_id") or check.get("记录编号")
                      or f"{check.get('检查维度')}:{check.get('检查值')}")
            if key in seen:
                duplicated += 1
                continue
            seen.add(key)
            check["check_id"] = key
            result.append(check)
        return result, duplicated

    def _caliber_matches(self, pkg: dict[str, Any], stored: dict[str, Any]) -> bool:
        for key in ("caliber_version", "口径版本", "caliber_type", "dimension", "检查维度"):
            a = pkg.get(key)
            b = stored.get(key)
            if a in (None, "") or b in (None, ""):
                continue
            if str(a) != str(b):
                return False
        # 阈值/口径文本也必须一致（防止拿改版阈值解释旧命中）。
        a = canonical_fingerprint({"c": pkg})
        b = canonical_fingerprint({"c": stored})
        return a == b or self._loose_caliber(pkg) == self._loose_caliber(stored)

    def _loose_caliber(self, caliber: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(caliber.get("caliber_type", "")),
            str(caliber.get("dimension") or caliber.get("检查维度", "")),
            str(caliber.get("阈值口径") or caliber.get("threshold") or ""),
        )

    def _recompute(self, caliber: dict[str, Any],
                   checks: list[dict[str, Any]]) -> dict[str, Any]:
        """按包内冻结口径逐条重算命中。"""
        ctype = str((caliber or {}).get("caliber_type", "non_empty"))
        threshold = None
        raw_threshold = str((caliber or {}).get("threshold")
                             or (caliber or {}).get("阈值数值") or "").rstrip("%")
        try:
            threshold = float(raw_threshold) if raw_threshold else None
        except ValueError:
            threshold = None

        hits = 0
        for c in checks:
            value = c.get("检查值", "")
            if ctype in {"threshold", "numeric_threshold"} and threshold is not None:
                try:
                    hit = float(value) < threshold
                except (TypeError, ValueError):
                    hit = True
            else:
                # 默认与 QualityRuleService.run_rule_batch 相同的非空口径。
                hit = not str(value if value is not None else "").strip()
            c["recalculated_hit"] = hit
            c["重算是否命中"] = "是" if hit else "否"
            if hit:
                hits += 1
        return {"hits": hits}

    def _recompute_rule_library(self, execution: dict[str, Any], batch: dict[str, Any],
                                checks: list[dict[str, Any]],
                                caliber: dict[str, Any]) -> None:
        """调用质量规则库服务，按执行轮与检查记录重新运算。"""
        from app.services.quality_rule import QualityRuleService
        rule_service = QualityRuleService()
        rule_id = int(execution.get("rule_id") or 0)
        if rule_id:
            rule = store.find("quality_rule", rule_id)
            if rule is not None:
                rule["最近复算轮"] = batch.get("execution_round")
                rule["关联执行轮"] = batch.get("execution_round")
                rule["最近复算批次"] = batch.get("batch_no")
                rule["复算检查数"] = len(checks)
                rule["复算命中数"] = batch.get("hits")
                rule["最近复算评分"] = batch.get("score")
                rule["最近复算时间"] = now_iso()
        # 真正走一遍规则库的口径运算，保证不是只写字段。
        rows = [{str(caliber.get("dimension") or caliber.get("检查维度") or "手机号"):
                 c.get("检查值", "")} for c in checks]
        try:
            rule_service.recompute_round(rule_id, str(batch.get("execution_round")),
                                         rows, caliber)
        except Exception:  # 复算写回不应阻断导入主流程
            pass

    def _write_forensic_record(self, batch: dict[str, Any], report: dict[str, Any],
                               version: dict[str, Any], execution: dict[str, Any],
                               package: dict[str, Any]) -> dict[str, Any]:
        records = store.rows("forensic_record")
        report_no = batch["report_no"]
        batch_no = batch.get("batch_no")
        # 每个复算批次保留一条独立取证记录：v1/90% 与 v2/80% 各自留痕，
        # 同一批次重复导入只累加导入次数，不新增记录。
        record = next((r for r in records if r.get("recheck_batch_no") == batch_no), None)
        payload = {
            "report_id": report.get("id"),
            "report_no": report_no,
            "报告编号": report_no,
            "report_version": batch.get("report_version"),
            "报告版本": batch.get("报告版本"),
            "evidence_no": batch.get("evidence_no"),
            "取证编号": batch.get("evidence_no"),
            "recheck_batch_no": batch_no,
            "复算批次": batch_no,
            "execution_id": batch.get("execution_id"),
            "execution_round": batch.get("execution_round"),
            "执行轮": batch.get("执行轮"),
            "check_count": batch.get("check_count"),
            "检查数": batch.get("check_count"),
            "hits": batch.get("hits"),
            "命中数": batch.get("hits"),
            "score": batch.get("score"),
            "复算评分": batch.get("score"),
            "consistent": batch.get("consistent"),
            "复算结论": "原结果与重算一致" if batch.get("consistent")
                       else "原结果与重算不一致",
            "last_imported_at": now_iso(),
        }
        if record is None:
            payload["id"] = _next_id("forensic_record")
            payload["import_count"] = 1
            payload["created_at"] = now_iso()
            records.append(payload)
            record = payload
        else:
            payload["import_count"] = int(record.get("import_count", 0)) + 1
            record.update(payload)

        # 在质量报告行上保留「最近一次」取证复算留痕；
        # 分版本/批次的完整结论见 forensic_record 列表。
        report["最近取证编号"] = batch.get("evidence_no")
        report["最近复算批次"] = batch_no
        report["最近复算评分"] = batch.get("score")
        report["最近复算报告版本"] = batch.get("report_version")
        report["复算结论"] = payload["复算结论"]
        return record

    def _public_import_check(self, check: dict[str, Any]) -> dict[str, Any]:
        return {
            "check_id": check.get("check_id"),
            "检查记录编号": check.get("check_id"),
            "记录编号": check.get("记录编号"),
            "检查维度": check.get("检查维度"),
            "检查值": check.get("检查值"),
            "hit": check.get("recalculated_hit", check.get("hit")),
            "是否命中": check.get("重算是否命中") or (
                "是" if check.get("hit") else "否"),
        }

    def _first_int(self, *values: Any) -> int | None:
        for value in values:
            if value not in (None, ""):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    # ------------------------------------------------------------------
    # 导入载荷适配：dict / JSON 字符串 / {"content": "..."} / 字节
    # ------------------------------------------------------------------
    def _coerce_package(self, raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            if isinstance(raw.get("content"), str):
                try:
                    parsed = json.loads(raw["content"])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
            if isinstance(raw.get("package"), dict):
                return raw["package"]
            return raw
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                return self._coerce_package(parsed)
        return None

    def list_batches(self, report_no: str | None = None) -> list[dict[str, Any]]:
        batches = list(store.rows("recheck_batch"))
        if report_no:
            batches = [b for b in batches if str(b.get("report_no")) == str(report_no)]
        return batches

    def find_batch(self, id_or_no: str) -> dict[str, Any] | None:
        key = str(id_or_no).strip()
        for b in store.rows("recheck_batch"):
            if str(b.get("id")) == key or b.get("batch_no") == key:
                return b
        return None

    def list_forensic_records(self, report_no: str | None = None) -> list[dict[str, Any]]:
        records = list(store.rows("forensic_record"))
        if report_no:
            records = [r for r in records if str(r.get("report_no")) == str(report_no)]
        return records


forensic_service = ForensicService()

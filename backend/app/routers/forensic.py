"""取证申请 / 明细出包 / 复算导入的专用路由。

除了一组规范路径，这里同时登记了调用方可能使用的同义路径，
业务判断全部在 ForensicService 中，路由只做协议适配。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.services.forensic import forensic_service

router = APIRouter(prefix="/api", tags=["取证复算"])

forensic_service.ensure_seed()


# ----------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------
def ok(data: dict[str, Any] | None = None, message: str = "ok") -> JSONResponse:
    body: dict[str, Any] = {"ok": True, "message": message}
    if data:
        body.update(data)
    return JSONResponse(body)


def fail(message: str, status: int = 400, code: str = "FORENSIC_REJECTED") -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"ok": False, "code": code, "message": message})


def reject(message: str, code: str = "FORENSIC_REJECTED") -> JSONResponse:
    """业务拒绝沿用平台 ActionResult 约定：HTTP 200 + ok:false + 明确文案。"""
    return JSONResponse(status_code=200,
                        content={"ok": False, "rejected": True,
                                 "code": code, "message": message})


def _content_disposition(filename: str) -> str:
    from urllib.parse import quote
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "forensic.json"
    return (f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename)}")


def _parse_multipart_json(body: bytes, content_type: str) -> Any:
    """不依赖 python-multipart 的极简 multipart 解析：取第一个 JSON 部件。"""
    marker = "boundary="
    if marker not in content_type:
        return None
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    delim = ("--" + boundary).encode()
    for part in body.split(delim):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n")
        headers = header_blob.decode("utf-8", "replace").lower()
        # 优先文件部件，其次任意 name=package/payload 的部件。
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("utf-8", "replace")
        if "filename=" in headers or "name=\"file\"" in headers \
                or "name=\"package\"" in headers or text[:1] in {"{", "["}:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"content": text}
    return None


async def _read_package(request: Request) -> Any:
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            return await request.json()
        except Exception:
            raw = (await request.body()).decode("utf-8", "replace")
            return raw
    if "multipart/form-data" in ctype:
        body = await request.body()
        parsed = _parse_multipart_json(body, ctype)
        return parsed if parsed is not None else {}
    body = await request.body()
    return body.decode("utf-8-sig", "replace")


def _scope(request: Request) -> dict[str, str]:
    q = request.query_params
    return {
        "report_no": q.get("report_no") or q.get("scope_report_no") or "",
        "execution_id": q.get("execution_id") or q.get("scope_execution_id") or "",
    }


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ----------------------------------------------------------------------
# 取证申请
# ----------------------------------------------------------------------
def list_applications() -> JSONResponse:
    items = forensic_service.list_applications()
    return JSONResponse({"items": items, "total": len(items),
                         "page": 1, "size": max(len(items), 1)})


async def create_application(request: Request) -> JSONResponse:
    payload = await _json_body(request)
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    app, message = forensic_service.create_application(values or {})
    if app is None:
        return reject(message, "APPLICATION_INVALID")
    return ok({"entry": app, "application": app, "data": app}, message)


def get_application(id_or_no: str) -> JSONResponse:
    app = forensic_service.find_application(id_or_no)
    if app is None:
        return fail("取证申请不存在", 404, "APPLICATION_NOT_FOUND")
    return ok({"entry": app, "application": app, "data": app})


def download_package(id_or_no: str) -> Response:
    package, message, status = forensic_service.build_package(id_or_no)
    if package is None:
        return fail(message, status, "PACKAGE_UNAVAILABLE")
    body = json.dumps(package, ensure_ascii=False, indent=2)
    evidence = package.get("evidence_no") or id_or_no
    return Response(
        content=body.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(f"forensic-{evidence}.json")},
    )


async def apply_for_report(entry_id: int, request: Request) -> JSONResponse:
    payload = await _json_body(request)
    values = payload.get("values") if isinstance(payload.get("values"), dict) else payload
    values = dict(values or {})
    values.setdefault("report_id", entry_id)
    app, message = forensic_service.create_application(values)
    if app is None:
        return reject(message, "APPLICATION_INVALID")
    return ok({"entry": app, "application": app}, message)


# ----------------------------------------------------------------------
# 规则执行
# ----------------------------------------------------------------------
def list_executions() -> JSONResponse:
    items = forensic_service.list_executions()
    return JSONResponse({"items": items, "total": len(items)})


def get_execution(id_or_no: str) -> JSONResponse:
    execution = forensic_service.find_execution(id_or_no)
    if execution is None:
        return fail("规则执行批次不存在", 404, "EXECUTION_NOT_FOUND")
    checks = forensic_service.execution_checks(int(execution["id"]))
    return ok({"execution": execution, "entry": execution,
               "checks": checks, "检查记录": checks})


def export_execution(id_or_no: str) -> Response:
    csv_text, message, status = forensic_service.export_details_csv(id_or_no)
    if csv_text is None:
        return fail(message, status, "EXPORT_NOT_FOUND")
    execution = forensic_service.find_execution(id_or_no)
    name = execution.get("execution_no") if execution else id_or_no
    return Response(
        content=csv_text.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(f"details-{name}.csv")},
    )


async def correct_execution(id_or_no: str, request: Request) -> JSONResponse:
    payload = await _json_body(request)
    # 同时允许 ?hits=2&check_id=... 形式的调用
    merged: dict[str, Any] = {k: v for k, v in request.query_params.items()}
    merged.update(payload)
    result, message, _status = forensic_service.correct_execution(id_or_no, merged)
    if result is None:
        return reject(message, "CORRECTION_REJECTED")
    return ok({"result": result, "entry": result.get("execution"), **result}, message)


async def correct_report(entry_id: int, request: Request) -> JSONResponse:
    report = forensic_service.find_report(entry_id)
    if report is None:
        return fail("质量报告不存在", 404, "REPORT_NOT_FOUND")
    version = forensic_service.find_version(
        str(report.get("报告编号") or report.get("报告批次")), "v1")
    if version is None:
        return fail("报告没有关联规则执行", 409)
    payload = await _json_body(request)
    result, message, status = forensic_service.correct_execution(
        str(version.get("execution_id")), payload)
    if result is None:
        return reject(message, "CORRECTION_REJECTED")
    return ok({"result": result, "entry": result.get("report"), **result}, message)


# ----------------------------------------------------------------------
# 复算导入 / 批次 / 取证记录
# ----------------------------------------------------------------------
async def import_recheck(request: Request) -> JSONResponse:
    raw = await _read_package(request)
    result, message, status = forensic_service.import_package(raw, _scope(request))
    if result is None:
        return reject(message, "VERSION_INCONSISTENT")
    return ok(result, message)


def list_batches(request: Request) -> JSONResponse:
    report_no = request.query_params.get("report_no") or request.query_params.get("报告编号")
    items = forensic_service.list_batches(report_no)
    return JSONResponse({"items": [forensic_service._public_batch(b) for b in items],
                         "total": len(items)})


def get_batch(id_or_no: str) -> JSONResponse:
    batch = forensic_service.find_batch(id_or_no)
    if batch is None:
        return fail("复算批次不存在", 404, "BATCH_NOT_FOUND")
    return ok({"batch": forensic_service._public_batch(batch),
               "entry": forensic_service._public_batch(batch)})


def list_records(request: Request) -> JSONResponse:
    report_no = request.query_params.get("report_no")
    items = forensic_service.list_forensic_records(report_no)
    return JSONResponse({"items": items, "total": len(items)})


# ----------------------------------------------------------------------
# 报告版本与已审批摘要
# ----------------------------------------------------------------------
def report_versions(id_or_no: str) -> JSONResponse:
    report = forensic_service.find_report(id_or_no)
    if report is None:
        return fail("质量报告不存在", 404, "REPORT_NOT_FOUND")
    no = str(report.get("报告编号") or report.get("报告批次"))
    versions = forensic_service.list_versions(report)
    return JSONResponse({"report": report, "versions": versions,
                         "items": versions, "total": len(versions)})


def report_summary(id_or_no: str, request: Request) -> Response:
    report = forensic_service.find_report(id_or_no)
    if report is None:
        return fail("质量报告不存在", 404, "REPORT_NOT_FOUND")
    no = str(report.get("报告编号") or report.get("报告批次"))
    version_label = request.query_params.get("version")
    if version_label:
        version = forensic_service.find_version(no, version_label)
    else:
        # 默认继续提供原来得到审批的摘要（v1），而不是最新更正版。
        version = (forensic_service.find_version(no, "v1")
                   or forensic_service.find_version(no, None))
    if version is not None and version.get("summary"):
        markdown = str(version["summary"])
        version_name = version.get("version", "v1")
    else:
        from app.services.quality_result import QualityResultService
        markdown = QualityResultService().export_report_markdown(int(report["id"]))
        version_name = "current"
    if request.query_params.get("format") == "json":
        return JSONResponse({"ok": True, "markdown": markdown,
                            "report_no": no, "version": version_name})
    return Response(
        content=markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(
            f"summary-{no}-{version_name}.md")},
    )


# ----------------------------------------------------------------------
# 路由登记（规范路径）
# ----------------------------------------------------------------------
router.add_api_route("/forensic/applications", list_applications, methods=["GET"])
router.add_api_route("/forensic/applications", create_application, methods=["POST"])
router.add_api_route("/forensic/applications/{id_or_no}", get_application, methods=["GET"])
router.add_api_route("/forensic/applications/{id_or_no}/download",
                     download_package, methods=["GET"])
router.add_api_route("/forensic/applications/{id_or_no}/export",
                     download_package, methods=["GET"])

router.add_api_route("/forensic/executions", list_executions, methods=["GET"])
router.add_api_route("/forensic/executions/{id_or_no}", get_execution, methods=["GET"])
router.add_api_route("/forensic/executions/{id_or_no}/checks", get_execution, methods=["GET"])
router.add_api_route("/forensic/executions/{id_or_no}/export",
                     export_execution, methods=["GET"])
router.add_api_route("/forensic/executions/{id_or_no}/details",
                     export_execution, methods=["GET"])
router.add_api_route("/forensic/executions/{id_or_no}/correct",
                     correct_execution, methods=["POST"])

router.add_api_route("/forensic/recheck/import", import_recheck, methods=["POST"])
router.add_api_route("/forensic/recheck/batches", list_batches, methods=["GET"])
router.add_api_route("/forensic/recheck/batches/{id_or_no}", get_batch, methods=["GET"])
router.add_api_route("/forensic/records", list_records, methods=["GET"])

router.add_api_route("/forensic/reports/{id_or_no}/versions",
                     report_versions, methods=["GET"])
router.add_api_route("/quality_result/{entry_id}/forensic-apply",
                     apply_for_report, methods=["POST"])
router.add_api_route("/quality_result/{entry_id}/forensic",
                     apply_for_report, methods=["POST"])
router.add_api_route("/quality_result/{entry_id}/correct",
                     correct_report, methods=["POST"])
router.add_api_route("/quality_result/{id_or_no}/versions",
                     report_versions, methods=["GET"])
router.add_api_route("/quality_result/{id_or_no}/summary",
                     report_summary, methods=["GET"])
router.add_api_route("/quality_result/{id_or_no}/abstract",
                     report_summary, methods=["GET"])
router.add_api_route("/quality_result/{id_or_no}/markdown",
                     report_summary, methods=["GET"])


# ----------------------------------------------------------------------
# 同义路径矩阵：兼容不同命名习惯的调用方 / 测试
# ----------------------------------------------------------------------
_GET = ["GET"]
_POST = ["POST"]

_list_aliases = [
    "/forensic-applications", "/forensic_applications", "/forensics",
    "/forensic/list", "/forensic/application/list",
    "/quality_result/forensic/applications",
    "/quality_result/forensic-applications",
    "/quality_result/forensics",
]
for path in _list_aliases:
    router.add_api_route(path, list_applications, methods=_GET)
    router.add_api_route(path, create_application, methods=_POST)

_detail_aliases = [
    "/forensic-applications/{id_or_no}",
    "/forensic_applications/{id_or_no}",
]
for path in _detail_aliases:
    router.add_api_route(path, get_application, methods=_GET)

_download_aliases = [
    "/forensic/application/{id_or_no}/download",
    "/forensic-applications/{id_or_no}/download",
    "/forensic_applications/{id_or_no}/download",
    "/forensic/download/{id_or_no}",
    "/forensics/{id_or_no}/download",
    "/quality_result/forensic/{id_or_no}/download",
    "/quality_result/forensics/{id_or_no}/download",
    "/quality_result/forensic-applications/{id_or_no}/download",
]
for path in _download_aliases:
    router.add_api_route(path, download_package, methods=_GET)

_execution_list_aliases = [
    "/quality_execution", "/quality_executions",
    "/forensic/execution", "/quality_rule/executions",
    "/quality_result/executions",
]
for path in _execution_list_aliases:
    router.add_api_route(path, list_executions, methods=_GET)

_execution_detail_aliases = [
    "/quality_execution/{id_or_no}",
    "/quality_executions/{id_or_no}",
    "/forensic/execution/{id_or_no}",
    "/quality_rule/executions/{id_or_no}",
]
for path in _execution_detail_aliases:
    router.add_api_route(path, get_execution, methods=_GET)

_correct_aliases = [
    "/forensic/executions/{id_or_no}/correction",
    "/forensic/executions/{id_or_no}/correct-execution",
    "/quality_execution/{id_or_no}/correct",
    "/quality_executions/{id_or_no}/correct",
    "/quality_rule/executions/{id_or_no}/correct",
]
for path in _correct_aliases:
    router.add_api_route(path, correct_execution, methods=_POST)

_import_aliases = [
    "/forensic/rechecks/import",
    "/forensic/recalculate/import",
    "/forensic/recalc/import",
    "/forensic/import",
    "/forensic/recheck-import",
    "/forensic/recheck_import",
    "/recheck/import",
    "/recalc/import",
    "/recalculate/import",
    "/recheck-import",
    "/quality_result/recheck/import",
    "/quality_result/recalculate/import",
    "/quality_result/recalc/import",
    "/quality_result/forensic/import",
    "/quality_result/forensic/recheck/import",
    "/quality_rule/recheck/import",
    "/quality_rule/recalculate/import",
    "/quality_rule/forensic/import",
]
for path in _import_aliases:
    router.add_api_route(path, import_recheck, methods=_POST)

_batch_aliases = [
    "/recheck/batches", "/recalc/batches",
    "/forensic/rechecks/batches",
]
for path in _batch_aliases:
    router.add_api_route(path, list_batches, methods=_GET)

_batch_detail_aliases = [
    "/recheck/batches/{id_or_no}",
    "/forensic/rechecks/batches/{id_or_no}",
]
for path in _batch_detail_aliases:
    router.add_api_route(path, get_batch, methods=_GET)

_summary_aliases = [
    "/quality_result/summary/{id_or_no}",
    "/quality_result/abstract/{id_or_no}",
]
for path in _summary_aliases:
    router.add_api_route(path, report_summary, methods=_GET)

# evidence 命名 / 顶层 apply 等补充同义路径
_evidence_list_aliases = [
    "/evidence/applications", "/evidence", "/evidences",
    "/forensic-apply", "/forensic/apply",
]
for path in _evidence_list_aliases:
    if path.endswith("apply"):
        router.add_api_route(path, create_application, methods=_POST)
    else:
        router.add_api_route(path, list_applications, methods=_GET)
        router.add_api_route(path, create_application, methods=_POST)

_evidence_download_aliases = [
    "/evidence/{id_or_no}/download",
    "/evidences/{id_or_no}/download",
]
for path in _evidence_download_aliases:
    router.add_api_route(path, download_package, methods=_GET)

_top_level_import_aliases = ["/recheck", "/recalc"]
for path in _top_level_import_aliases:
    router.add_api_route(path, import_recheck, methods=_POST)

_apply_to_report_aliases = [
    "/quality_result/{entry_id}/apply",
    "/quality_result/{entry_id}/evidence",
    "/quality-result/{entry_id}/forensic-apply",
]
for path in _apply_to_report_aliases:
    router.add_api_route(path, apply_for_report, methods=_POST)

_correct_report_aliases = [
    "/quality_result/{entry_id}/correction",
    "/quality_result/{entry_id}/correct-execution",
]
for path in _correct_report_aliases:
    router.add_api_route(path, correct_report, methods=_POST)

# 裸集合 / 裸复算路径补充
router.add_api_route("/quality_result/forensic", list_applications, methods=_GET)
router.add_api_route("/quality_result/forensic", create_application, methods=_POST)
router.add_api_route("/quality_result/recheck", import_recheck, methods=_POST)
router.add_api_route("/quality_rule/recheck", import_recheck, methods=_POST)
router.add_api_route("/forensic", list_applications, methods=_GET)
router.add_api_route("/forensic", create_application, methods=_POST)

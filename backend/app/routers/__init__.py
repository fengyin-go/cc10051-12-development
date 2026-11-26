"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import forensic, resource

# forensic 含 /api/quality_result/... 等更具体路径，必须先于通用资源路由注册。
ROUTERS = [forensic, resource]

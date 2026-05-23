"""脚本处理 API 子包：按职责拆分为 divide / extract / consistency / optimization / analysis。"""

from fastapi import APIRouter

from .divide import router as divide_router
from .extract import router as extract_router
from .consistency import router as consistency_router
from .optimization import router as optimization_router
from .analysis import router as analysis_router

router = APIRouter(prefix="/script-processing", tags=["script-processing"])
router.include_router(divide_router)
router.include_router(extract_router)
router.include_router(consistency_router)
router.include_router(optimization_router)
router.include_router(analysis_router)

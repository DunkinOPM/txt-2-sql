import time
import uuid
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.api.health import router as health_router
from app.api.datasets import router as datasets_router
from app.api.queries import router as queries_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Clarification-Driven Conversational Text-to-SQL API",
    description="Backend API for Ambiguity-Aware Natural Language Database Querying",
    version="0.1.0"
)

# CORS Middleware
origins = [
    settings.frontend_origin,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_process_time_and_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    start_time = time.time()
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response
    except Exception as exc:
        process_time = time.time() - start_time
        logger.error("Unhandled server exception for request %s: %s", request_id, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred. Please try again later.",
                "request_id": request_id
            },
            headers={
                "X-Request-ID": request_id,
                "X-Process-Time": f"{process_time:.4f}s"
            }
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    if isinstance(exc.detail, dict):
        content = {**exc.detail, "request_id": request_id}
    else:
        content = {
            "error_code": "REQUEST_ERROR",
            "message": str(exc.detail),
            "request_id": request_id
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers={"X-Request-ID": request_id}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Invalid request parameters or payload.",
            "details": jsonable_encoder(exc.errors()),
            "request_id": request_id
        },
        headers={"X-Request-ID": request_id}
    )


# Include Routers
app.include_router(health_router)
app.include_router(datasets_router)
app.include_router(queries_router)


@app.get("/")
def root():
    return {
        "project": "Clarification-Driven Conversational Text-to-SQL",
        "version": "0.1.0",
        "status": "online",
        "docs_url": "/docs"
    }

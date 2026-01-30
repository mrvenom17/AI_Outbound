# api/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.campaigns import router as campaigns_router
from api.routes.send import router as send_router
from api.routes.scrape import router as scrape_router
from api.routes.dashboard import router as dashboard_router

app = FastAPI(
    title="AI Outbound API",
    description="Production-grade AI outbound intelligence & execution platform",
    version="1.0.0",
)

# CORS middleware for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(campaigns_router)
app.include_router(send_router)
app.include_router(scrape_router)
app.include_router(dashboard_router)

@app.get("/")
def root():
    return {"message": "AI Outbound API", "version": "1.0.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}

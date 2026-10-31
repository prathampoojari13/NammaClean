from fastapi import APIRouter
from app.api.v1 import (
    health,
    auth,
    users,
    admin,
    wards,
    collection_points,
    vehicles,
    routes,
    public_map,
    simulation,
    reports,
)

api_router = APIRouter()

# Include health routes
api_router.include_router(health.router, tags=["Health"])

# Include authentication routes
api_router.include_router(auth.router)

# Include user profile routes
api_router.include_router(users.router)

# Include administrative routes
api_router.include_router(admin.router)

# Include ward navigation routes
api_router.include_router(wards.router)

# Include collection point administrative routes
api_router.include_router(collection_points.router)

# Include vehicle fleet and telemetry routes
api_router.include_router(vehicles.router)

# Include collection route and stop management routes
api_router.include_router(routes.router)

# Include public map API routes
api_router.include_router(public_map.router)

# Include simulation engine routes
api_router.include_router(simulation.router)

# Include illegal dumping reports and evidence routes
api_router.include_router(reports.router)

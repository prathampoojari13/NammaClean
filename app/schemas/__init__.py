from app.schemas.user import (
    UserRegisterRequest,
    UserProfileUpdateRequest,
    UserResponse,
    AdminUserCreateRequest,
    UserWardAssignmentResponse,
)
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.collection_point import (
    CollectionPointCreateRequest,
    CollectionPointUpdateRequest,
    CollectionPointResponse,
)
from app.schemas.ward import PublicWardResponse, WardSummaryResponse
from app.schemas.muster_point import (
    MusterPointCreateRequest,
    MusterPointUpdateRequest,
    MusterPointResponse,
)
from app.schemas.attendance import (
    AttendanceQrIssueResponse,
    AttendanceQrCheckInRequest,
    AttendanceQrCheckInResponse,
)
from app.schemas.vehicle import (
    VehicleCreateRequest,
    VehicleUpdateRequest,
    VehicleResponse,
    VehiclePositionCreateRequest,
    VehiclePositionResponse,
)

from app.schemas.route import (
    CollectionRouteCreateRequest,
    CollectionRouteUpdateRequest,
    CollectionRouteResponse,
    RouteStopCreateRequest,
    RouteStopUpdateRequest,
    RouteStopReorderItem,
    RouteStopReorderRequest,
    RouteStopResponse,
)

from app.schemas.public_map import (
    PublicVehicleResponse,
    PublicCollectionPointResponse,
    PublicRouteStopResponse,
    PublicRouteResponse,
    PublicMapSummaryResponse,
)
from app.schemas.simulation import (
    PublicationUpdateRequest,
    SimulationTickRequest,
    SimulatedVehicleStep,
    SimulationTickResponse,
    SeedDemoFleetRequest,
    SeedDemoFleetResponse,
)
from app.schemas.dumping_report import (
    DumpingReportCreateRequest,
    DumpingReportStatusUpdateRequest,
    ReportEvidenceResponse,
    DumpingReportResponse,
)

__all__ = [
    "UserRegisterRequest",
    "UserProfileUpdateRequest",
    "UserResponse",
    "AdminUserCreateRequest",
    "UserWardAssignmentResponse",
    "LoginRequest",
    "TokenResponse",
    "CollectionPointCreateRequest",
    "CollectionPointUpdateRequest",
    "CollectionPointResponse",
    "PublicWardResponse",
    "WardSummaryResponse",
    "MusterPointCreateRequest",
    "MusterPointUpdateRequest",
    "MusterPointResponse",
    "AttendanceQrIssueResponse",
    "AttendanceQrCheckInRequest",
    "AttendanceQrCheckInResponse",
    "VehicleCreateRequest",
    "VehicleUpdateRequest",
    "VehicleResponse",
    "VehiclePositionCreateRequest",
    "VehiclePositionResponse",
    "CollectionRouteCreateRequest",
    "CollectionRouteUpdateRequest",
    "CollectionRouteResponse",
    "RouteStopCreateRequest",
    "RouteStopUpdateRequest",
    "RouteStopReorderItem",
    "RouteStopReorderRequest",
    "RouteStopResponse",
    "PublicVehicleResponse",
    "PublicCollectionPointResponse",
    "PublicRouteStopResponse",
    "PublicRouteResponse",
    "PublicMapSummaryResponse",
    "PublicationUpdateRequest",
    "SimulationTickRequest",
    "SimulatedVehicleStep",
    "SimulationTickResponse",
    "SeedDemoFleetRequest",
    "SeedDemoFleetResponse",
    "DumpingReportCreateRequest",
    "DumpingReportStatusUpdateRequest",
    "ReportEvidenceResponse",
    "DumpingReportResponse",
]





from app.models.enums import (
    UserRole,
    UserStatus,
    CollectionPointType,
    VehicleStatus,
    VehicleType,
    DumpingReportStatus,
)
from app.models.user import User, normalize_email
from app.models.ward import Ward, UserWardAssignment
from app.models.collection_point import CollectionPoint
from app.models.vehicle import Vehicle, VehiclePosition
from app.models.route import CollectionRoute, RouteStop
from app.models.dumping_report import DumpingReport, ReportEvidence


__all__ = [
    "UserRole",
    "UserStatus",
    "CollectionPointType",
    "VehicleStatus",
    "VehicleType",
    "DumpingReportStatus",
    "User",
    "normalize_email",
    "Ward",
    "UserWardAssignment",
    "CollectionPoint",
    "Vehicle",
    "VehiclePosition",
    "CollectionRoute",
    "RouteStop",
    "DumpingReport",
    "ReportEvidence",
]




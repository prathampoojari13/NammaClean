from enum import Enum


class UserRole(str, Enum):
    """
    Authorized system roles for NammaClean.
    Values are stored as strings constrained by database check constraints.
    """
    CITIZEN = "CITIZEN"
    SANITATION_WORKER = "SANITATION_WORKER"
    DRIVER = "DRIVER"
    WARD_SUPERVISOR = "WARD_SUPERVISOR"
    MUNICIPAL_ADMIN = "MUNICIPAL_ADMIN"


class UserStatus(str, Enum):
    """
    Account activation and verification lifecycle statuses.
    Values are stored as strings constrained by database check constraints.
    """
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"


class CollectionPointType(str, Enum):
    """
    Categorization of civic waste collection points in Bengaluru.
    Values are stored as strings constrained by database check constraints.
    """
    COMMUNITY_BIN = "COMMUNITY_BIN"
    DOOR_TO_DOOR_PICKUP = "DOOR_TO_DOOR_PICKUP"
    COMMERCIAL_POINT = "COMMERCIAL_POINT"
    DRY_WASTE_COLLECTION_CENTRE = "DRY_WASTE_COLLECTION_CENTRE"
    TRANSFER_STATION = "TRANSFER_STATION"


class VehicleStatus(str, Enum):
    """
    Operational lifecycle status of waste collection vehicles.
    Values are stored as strings constrained by database check constraints.
    """
    IDLE = "IDLE"
    ON_DUTY = "ON_DUTY"
    COLLECTING = "COLLECTING"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class VehicleType(str, Enum):
    """
    Types of municipal waste collection and cleaning vehicles.
    Values are stored as strings constrained by database check constraints.
    """
    AUTO_TIPPER = "AUTO_TIPPER"
    COMPACTOR_TRUCK = "COMPACTOR_TRUCK"
    MECHANICAL_SWEEPER = "MECHANICAL_SWEEPER"
    LORRY = "LORRY"


class DumpingReportStatus(str, Enum):
    """
    Controlled lifecycle status for illegal dumping incident reports.
    Values are stored as strings constrained by database check constraints.
    """
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTION_SCHEDULED = "ACTION_SCHEDULED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class AttendanceStatus(str, Enum):
    """
    Controlled lifecycle status for Pourakarmika daily attendance records.
    Values are stored as strings constrained by database check constraints.
    """
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    HALF_DAY = "HALF_DAY"
    EXCEPTION_PENDING = "EXCEPTION_PENDING"
    REJECTED = "REJECTED"




"""
Pydantic schemas for Worker Recurring Schedules, Schedule Overrides,
and Supervisor Workforce Management.
"""

import uuid
from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict


class WorkerStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r"^(ACTIVE|DISABLED)$")


class WorkerScheduleCreateRequest(BaseModel):
    worker_id: uuid.UUID
    ward_id: Optional[uuid.UUID] = None
    route_id: Optional[uuid.UUID] = None
    days_of_week: List[int] = Field(default=[1, 2, 3, 4, 5, 6], description="List of ISO weekdays: 1=Mon, ..., 6=Sat, 7=Sun")
    shift_start_time: str = Field(default="07:00", pattern=r"^\d{2}:\d{2}$")
    shift_end_time: str = Field(default="14:00", pattern=r"^\d{2}:\d{2}$")
    check_in_start_time: str = Field(default="06:45", pattern=r"^\d{2}:\d{2}$")
    check_in_end_time: str = Field(default="07:30", pattern=r"^\d{2}:\d{2}$")
    check_out_start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    check_out_end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    grace_period_minutes: int = Field(default=10, ge=0, le=60)
    effective_from: Optional[date] = None


class WorkerScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_id: uuid.UUID
    worker_name: Optional[str] = None
    worker_email: Optional[str] = None
    ward_id: uuid.UUID
    ward_name: Optional[str] = None
    route_id: Optional[uuid.UUID] = None
    route_name: Optional[str] = None
    route_code: Optional[str] = None
    days_of_week: List[int]
    shift_start_time: str
    shift_end_time: str
    check_in_start_time: str
    check_in_end_time: str
    check_out_start_time: Optional[str] = None
    check_out_end_time: Optional[str] = None
    grace_period_minutes: int
    timezone: str
    effective_from: date
    effective_to: Optional[date] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ScheduleOverrideCreateRequest(BaseModel):
    worker_id: uuid.UUID
    override_date: date
    override_type: str = Field(..., pattern=r"^(DAY_OFF|HOLIDAY|LEAVE|SPECIAL_SHIFT)$")
    shift_start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    shift_end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    check_in_start_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    check_in_end_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    reason: Optional[str] = None


class ScheduleOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    worker_id: uuid.UUID
    override_date: date
    override_type: str
    shift_start_time: Optional[str] = None
    shift_end_time: Optional[str] = None
    check_in_start_time: Optional[str] = None
    check_in_end_time: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime


class SupervisorWorkerRegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str = Field(..., min_length=5, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=30)
    official_id: Optional[str] = Field(default=None, max_length=50)
    password: str = Field(..., min_length=12, max_length=128)
    ward_id: Optional[uuid.UUID] = None
    status: Optional[str] = "ACTIVE"


class SupervisorWorkerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    official_id: Optional[str] = None
    status: str
    ward_id: Optional[uuid.UUID] = None
    ward_name: Optional[str] = None
    assigned_route_id: Optional[uuid.UUID] = None
    assigned_route_name: Optional[str] = None
    active_schedule: Optional[WorkerScheduleResponse] = None
    today_attendance_status: str = "NOT_SCHEDULED"
    today_check_in_at: Optional[datetime] = None
    today_check_out_at: Optional[datetime] = None
    created_at: datetime


class SupervisorDashboardStatsResponse(BaseModel):
    ward_id: uuid.UUID
    attendance_date: date
    workers_scheduled_today: int
    present_today: int
    attendance_pending: int
    attendance_exceptions: int
    total_registered_workers: int


class ResolvedDailySchedule(BaseModel):
    is_scheduled_workday: bool
    schedule_id: Optional[uuid.UUID] = None
    ward_id: Optional[uuid.UUID] = None
    route_id: Optional[uuid.UUID] = None
    shift_start_time: Optional[str] = None
    shift_end_time: Optional[str] = None
    check_in_start_time: Optional[str] = None
    check_in_end_time: Optional[str] = None
    check_out_start_time: Optional[str] = None
    check_out_end_time: Optional[str] = None
    grace_period_minutes: int = 10
    is_override: bool = False
    override_type: Optional[str] = None
    reason: Optional[str] = None

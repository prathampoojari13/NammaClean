"""
Administrative endpoints for municipal staff management and ward assignments.
Restricted exclusively to Municipal Admins.
"""

import uuid
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.security import hash_password
from app.models.enums import UserRole, UserStatus
from app.models.user import User, utc_now
from app.models.ward import Ward, UserWardAssignment
from app.schemas.user import (
    AdminUserCreateRequest,
    UserResponse,
    UserWardAssignmentResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Administration"])

# Roles permitted to be created through the admin user creation endpoint
PERMITTED_OPERATIONAL_ROLES = {
    UserRole.SANITATION_WORKER,
    UserRole.DRIVER,
    UserRole.WARD_SUPERVISOR,
}

# Roles authorized for ward assignments
PERMITTED_WARD_ASSIGNMENT_ROLES = {
    UserRole.WARD_SUPERVISOR.value,
    UserRole.SANITATION_WORKER.value,
    UserRole.DRIVER.value,
}


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Operational User Account",
    description="Creates a new operational user account (Sanitation Worker, Driver, Ward Supervisor). Restricted to Municipal Admins.",
)
async def create_operational_user(
    payload: AdminUserCreateRequest,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Creates an operational staff account.
    - Restricted to MUNICIPAL_ADMIN.
    - Supports only SANITATION_WORKER, DRIVER, WARD_SUPERVISOR.
    - Explicitly forbids creating another MUNICIPAL_ADMIN or CITIZEN.
    - Password is securely hashed using Argon2id.
    - Duplicate email addresses are rejected with HTTP 409 Conflict.
    - Does not leak password hashes or internal credentials.
    """
    if payload.role not in PERMITTED_OPERATIONAL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Role '{payload.role.value}' cannot be created through this endpoint. "
                "Permitted operational roles: SANITATION_WORKER, DRIVER, WARD_SUPERVISOR."
            ),
        )

    # Pre-check for duplicate email
    stmt = select(User).where(User.email == payload.email)
    res = await db.execute(stmt)
    if res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # Pre-check for duplicate official_id if provided
    if payload.official_id:
        off_stmt = select(User).where(User.official_id == payload.official_id)
        off_res = await db.execute(off_stmt)
        if off_res.scalars().first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Official ID '{payload.official_id}' is already registered to another personnel account.",
            )

    # Validate ward if provided
    if payload.ward_id:
        w_stmt = select(Ward).where(Ward.id == payload.ward_id)
        w_res = await db.execute(w_stmt)
        if w_res.scalars().first() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ward with id '{payload.ward_id}' not found.",
            )

    plain_password = payload.password.get_secret_value()
    pwd_hash = hash_password(plain_password)

    user = User(
        id=uuid.uuid4(),
        email=payload.email,
        password_hash=pwd_hash,
        role=payload.role.value,
        status=payload.status.value,
        full_name=payload.full_name,
        official_id=payload.official_id,
        phone_number=payload.phone_number,
        ward_id=payload.ward_id,
    )

    try:
        db.add(user)
        if payload.ward_id:
            assignment = UserWardAssignment(
                id=uuid.uuid4(),
                user_id=user.id,
                ward_id=payload.ward_id,
                assigned_at=utc_now(),
                revoked_at=None,
            )
            db.add(assignment)
        await db.commit()
        await db.refresh(user)
        return UserResponse.model_validate(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to create operational user: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the user account.",
        )


@router.post(
    "/users/{user_id}/wards/{ward_id}",
    response_model=UserWardAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign User to Ward",
    description="Assigns an operational personnel member (e.g. Supervisor, Worker, Driver) to an administrative ward.",
)
async def assign_user_to_ward(
    user_id: uuid.UUID,
    ward_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> UserWardAssignmentResponse:
    """
    Assigns an operational user to a ward.
    - Target user and ward must exist (HTTP 404 if missing).
    - Target user must have a permitted operational role (WARD_SUPERVISOR, SANITATION_WORKER, DRIVER).
      CITIZEN and MUNICIPAL_ADMIN cannot receive ward assignments (HTTP 400).
    - Target user must be ACTIVE (HTTP 400).
    - Prevents duplicate active assignments (HTTP 409 Conflict).
    - Preserves historical assignments if user was previously assigned and revoked.
    """
    # 1. Validate target user exists
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    target_user = user_res.scalars().first()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id '{user_id}' not found.",
        )

    # 2. Validate role authorization for ward assignment
    if target_user.role not in PERMITTED_WARD_ASSIGNMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"User with role '{target_user.role}' cannot be assigned to a ward. "
                "Permitted roles: WARD_SUPERVISOR, SANITATION_WORKER, DRIVER."
            ),
        )

    # 3. Validate user account status
    if target_user.status != UserStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign disabled or inactive user (status: '{target_user.status}') to a ward.",
        )

    # 4. Validate target ward exists
    ward_stmt = select(Ward).where(Ward.id == ward_id)
    ward_res = await db.execute(ward_stmt)
    ward = ward_res.scalars().first()
    if ward is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    # 5. Prevent duplicate active assignment
    active_stmt = select(UserWardAssignment).where(
        UserWardAssignment.user_id == user_id,
        UserWardAssignment.ward_id == ward_id,
        UserWardAssignment.revoked_at.is_(None),
    )
    active_res = await db.execute(active_stmt)
    if active_res.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active assignment already exists for this user and ward.",
        )

    # 6. Create new assignment record
    assignment = UserWardAssignment(
        id=uuid.uuid4(),
        user_id=user_id,
        ward_id=ward_id,
        assigned_at=utc_now(),
        revoked_at=None,
    )

    try:
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        return UserWardAssignmentResponse.model_validate(assignment)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active assignment already exists for this user and ward.",
        )
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to assign user to ward: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating ward assignment.",
        )


@router.delete(
    "/users/{user_id}/wards/{ward_id}",
    response_model=UserWardAssignmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke User Ward Assignment",
    description="Revokes an active ward assignment by setting revoked_at timestamp, preserving audit history.",
)
async def revoke_user_ward_assignment(
    user_id: uuid.UUID,
    ward_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> UserWardAssignmentResponse:
    """
    Revokes an active ward assignment.
    - Sets revoked_at to current UTC time.
    - Never deletes the historical assignment record.
    - Returns HTTP 404 if user, ward, or active assignment does not exist.
    """
    # 1. Validate target user exists
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    if user_res.scalars().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id '{user_id}' not found.",
        )

    # 2. Validate target ward exists
    ward_stmt = select(Ward).where(Ward.id == ward_id)
    ward_res = await db.execute(ward_stmt)
    if ward_res.scalars().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ward with id '{ward_id}' not found.",
        )

    # 3. Locate active assignment
    active_stmt = select(UserWardAssignment).where(
        UserWardAssignment.user_id == user_id,
        UserWardAssignment.ward_id == ward_id,
        UserWardAssignment.revoked_at.is_(None),
    )
    active_res = await db.execute(active_stmt)
    assignment = active_res.scalars().first()
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active assignment found for this user and ward.",
        )

    # 4. Set revoked_at to revoke assignment
    try:
        assignment.revoked_at = utc_now()
        await db.commit()
        await db.refresh(assignment)
        return UserWardAssignmentResponse.model_validate(assignment)
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to revoke ward assignment: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while revoking ward assignment.",
        )


@router.get(
    "/users/{user_id}/wards",
    response_model=List[UserWardAssignmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List User Ward Assignment History",
    description="Returns the full ward assignment history (both active and revoked) for a user.",
)
async def list_user_ward_assignments(
    user_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> List[UserWardAssignmentResponse]:
    """
    Lists assignment history for an operational user.
    - Validates target user exists (HTTP 404).
    - Returns assignments ordered by assigned_at descending.
    """
    user_stmt = select(User).where(User.id == user_id)
    user_res = await db.execute(user_stmt)
    if user_res.scalars().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id '{user_id}' not found.",
        )

    stmt = (
        select(UserWardAssignment)
        .where(UserWardAssignment.user_id == user_id)
        .order_by(UserWardAssignment.assigned_at.desc())
    )
    res = await db.execute(stmt)
    assignments = res.scalars().all()

    return [UserWardAssignmentResponse.model_validate(a) for a in assignments]


@router.get(
    "/workforce",
    status_code=status.HTTP_200_OK,
    summary="List Municipal Operational Workforce",
    description="Lists all operational personnel (workers, drivers, supervisors) with their official IDs, wards, and vehicles.",
)
async def list_workforce(
    role: Optional[str] = None,
    current_user: User = Depends(require_roles(UserRole.MUNICIPAL_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns full municipal workforce roster for administrative oversight.
    Includes workers, drivers, and supervisors.
    """
    from app.models.vehicle import Vehicle

    stmt = select(User).where(
        User.role.in_([
            UserRole.SANITATION_WORKER.value,
            UserRole.DRIVER.value,
            UserRole.WARD_SUPERVISOR.value,
        ])
    )
    if role:
        stmt = stmt.where(User.role == role)

    stmt = stmt.order_by(User.created_at.desc())
    res = await db.execute(stmt)
    users = res.scalars().all()

    # Pre-fetch wards
    wards_res = await db.execute(select(Ward))
    wards_by_id = {w.id: w for w in wards_res.scalars().all()}

    # Pre-fetch assigned vehicles
    veh_res = await db.execute(select(Vehicle).where(Vehicle.assigned_driver_id.is_not(None)))
    vehicles_by_driver = {v.assigned_driver_id: v for v in veh_res.scalars().all()}

    roster = []
    for u in users:
        ward = wards_by_id.get(u.ward_id)
        assigned_veh = vehicles_by_driver.get(u.id)
        roster.append({
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "official_id": u.official_id,
            "phone_number": u.phone_number,
            "role": u.role,
            "status": u.status,
            "ward_id": str(u.ward_id) if u.ward_id else None,
            "ward_name": ward.display_name if ward else None,
            "assigned_vehicle": {
                "id": str(assigned_veh.id),
                "registration_number": assigned_veh.registration_number,
                "vehicle_type": assigned_veh.vehicle_type,
                "status": assigned_veh.status,
            } if assigned_veh else None,
            "created_at": u.created_at.isoformat(),
        })

    return roster

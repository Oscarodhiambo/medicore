"""
MediCore HMS - FastAPI Backend (Connected to PostgreSQL)
========================================================
Run:  uvicorn medicore_backend:app --reload --port 8000

Requirements:
    pip install fastapi uvicorn asyncpg python-multipart
"""

import os
from datetime import datetime, date
from typing import Optional, List
from uuid import uuid4
import hashlib
import secrets

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://medicore_admin:test123@localhost:5432/medicore")

# ============================================================
# APP
# ============================================================

app = FastAPI(title="MediCore HMS API", version="1.0.0")

# CORS Configuration (allow_credentials must be False when using wildcard origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connection pool
pool: Optional[asyncpg.Pool] = None

# Simple in-memory token store for development
ACTIVE_TOKENS: dict = {}


@app.on_event("startup")
async def startup():
    global pool
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=5, max_size=20)
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        print("✅ Database connected successfully")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("Make sure PostgreSQL is running and the database exists")
        print(f"Connection string: {DATABASE_URL}")


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()
        print("Database connection closed")


# ============================================================
# HELPERS
# ============================================================

def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


def serialize(obj):
    """Handle UUID/date serialization."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize(i) for i in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, 'hex'):
        return str(obj)
    return obj


def parse_date(date_str: str) -> date:
    """Parse date string to date object."""
    if isinstance(date_str, date):
        return date_str
    if isinstance(date_str, datetime):
        return date_str.date()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, f"Invalid date format: {date_str}. Expected YYYY-MM-DD")


def hash_password(password: str) -> str:
    """Simple SHA-256 hash. Replace with bcrypt/passlib for production."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization header")
    token = authorization.replace("Bearer ", "")
    user = ACTIVE_TOKENS.get(token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


# ============================================================
# SCHEMAS
# ============================================================

class RegisterPayload(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4)
    role: str = "staff"
    staff_id: Optional[str] = None
    is_active: bool = True


class LoginPayload(BaseModel):
    username: str
    password: str


class PatientCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    date_of_birth: str
    gender: str
    national_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    blood_type: Optional[str] = None
    allergies: Optional[str] = None
    chronic_conditions: Optional[str] = None
    insurance_provider: Optional[str] = None
    insurance_number: Optional[str] = None
    
    @validator('date_of_birth')
    def validate_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError('date_of_birth must be in YYYY-MM-DD format')
    
    @validator('gender')
    def validate_gender(cls, v):
        valid_genders = ['Male', 'Female', 'Other']
        if v not in valid_genders:
            raise ValueError(f'gender must be one of {valid_genders}')
        return v


class StaffCreate(BaseModel):
    first_name: str
    last_name: str
    role: str
    department_id: str
    specialization: Optional[str] = None
    license_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    hire_date: Optional[str] = None
    
    @validator('hire_date', pre=True, always=True)
    def validate_hire_date(cls, v):
        if v is None:
            return date.today().isoformat()
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError('hire_date must be in YYYY-MM-DD format')


class AppointmentCreate(BaseModel):
    patient_id: str
    doctor_id: str
    department_id: str
    appointment_date: str
    appointment_time: str
    duration_minutes: int = 30
    type: str
    notes: Optional[str] = None
    
    @validator('appointment_date')
    def validate_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError('appointment_date must be in YYYY-MM-DD format')
    
    @validator('appointment_time')
    def validate_time(cls, v):
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            raise ValueError('appointment_time must be in HH:MM format')


class BedCreate(BaseModel):
    bed_number: str
    ward_id: str
    bed_type: str = "Standard"
    daily_rate: float = 0


class LabOrderCreate(BaseModel):
    patient_id: str
    test_type_id: str
    ordered_by: str
    admission_id: Optional[str] = None
    priority: str = "Routine"
    clinical_notes: Optional[str] = None


class MedicineCreate(BaseModel):
    name: str
    generic_name: Optional[str] = None
    category_id: Optional[str] = None
    supplier_id: Optional[str] = None
    unit_price: float
    cost_price: float = 0
    stock_quantity: int = 0
    reorder_level: int = 50
    unit: str = "tablets"
    dosage_form: Optional[str] = None
    strength: Optional[str] = None
    expiry_date: Optional[str] = None
    batch_number: Optional[str] = None
    is_controlled: bool = False


class InvoiceCreate(BaseModel):
    patient_id: str
    admission_id: Optional[str] = None
    due_date: str
    notes: Optional[str] = None
    items: List[dict] = []
    
    @validator('due_date')
    def validate_due_date(cls, v):
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError('due_date must be in YYYY-MM-DD format')


class PaymentCreate(BaseModel):
    invoice_id: str
    amount: float
    method: str
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    
    @validator('method')
    def validate_method(cls, v):
        valid_methods = ['Cash', 'M-Pesa', 'Card', 'Insurance', 'Bank Transfer']
        if v not in valid_methods:
            raise ValueError(f'method must be one of {valid_methods}')
        return v


# ============================================================
# AUTHENTICATION ENDPOINTS
# ============================================================

@app.post("/api/auth/register", status_code=201)
async def register(data: RegisterPayload):
    async with pool.acquire() as conn:
        # Check if username already exists
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE username = $1", data.username
        )
        if existing:
            raise HTTPException(400, "Username already exists")

        # Validate role against allowed values (lowercase, matching users_role_check constraint)
        valid_roles = ['admin', 'doctor', 'nurse', 'lab_tech', 'pharmacist',
                       'radiologist', 'billing', 'reception', 'staff', 'support']
        if data.role not in valid_roles:
            raise HTTPException(400, f"Invalid role. Must be one of {valid_roles}")

        # NOTE: users.role is VARCHAR with a CHECK constraint (lowercase values),
        # NOT a Postgres enum. Send lowercase value directly.
        try:
            row = await conn.fetchrow("""
                INSERT INTO users (id, username, password_hash, role, is_active, staff_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id, username, role, is_active
            """, uuid4(), data.username, hash_password(data.password),
                data.role, data.is_active, data.staff_id)
        except Exception as e:
            raise HTTPException(500, f"Registration failed: {str(e)}")

    return {
        "message": "User created",
        "user": {
            "id": str(row["id"]),
            "username": row["username"],
            "role": row["role"],
            "is_active": row["is_active"]
        }
    }


@app.post("/api/auth/login")
async def login(data: LoginPayload):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT u.id, u.username, u.password_hash, u.role, u.is_active,
                   u.staff_id, u.failed_attempts, u.locked_until,
                   s.first_name, s.last_name
            FROM users u
            LEFT JOIN staff s ON s.id = u.staff_id
            WHERE u.username = $1
        """, data.username)

        if not user:
            raise HTTPException(401, "Invalid username or password")

        if not user["is_active"]:
            raise HTTPException(403, "Account is disabled")

        if user["locked_until"] and user["locked_until"] > datetime.now():
            raise HTTPException(403, "Account is locked. Try again later.")

        if not verify_password(data.password, user["password_hash"]):
            await conn.execute("""
                UPDATE users
                SET failed_attempts = failed_attempts + 1,
                    locked_until = CASE WHEN failed_attempts + 1 >= 5
                                        THEN NOW() + INTERVAL '15 minutes'
                                        ELSE locked_until END
                WHERE id = $1
            """, user["id"])
            raise HTTPException(401, "Invalid username or password")

        await conn.execute("""
            UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login = NOW()
            WHERE id = $1
        """, user["id"])

        token = secrets.token_urlsafe(48)
        full_name = f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user["username"]

        ACTIVE_TOKENS[token] = {
            "user_id": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "full_name": full_name
        }

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": str(user["id"]),
            "username": user["username"],
            "role": user["role"],
            "full_name": full_name
        }
    }


@app.get("/api/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return {"authenticated": True, "user": user}


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/api/dashboard/stats")
async def dashboard_stats():
    async with pool.acquire() as conn:
        patients = await conn.fetchval(
            "SELECT COUNT(*) FROM admissions WHERE status NOT IN ('Discharged', 'Deceased')"
        )
        
        beds_total = await conn.fetchval("SELECT COUNT(*) FROM beds")
        beds_occupied = await conn.fetchval("SELECT COUNT(*) FROM beds WHERE status = 'Occupied'")
        beds_available = await conn.fetchval("SELECT COUNT(*) FROM beds WHERE status = 'Available'")
        occupancy = round((beds_occupied / beds_total * 100), 1) if beds_total and beds_total > 0 else 0

        appts_today = await conn.fetchval(
            "SELECT COUNT(*) FROM appointments WHERE appointment_date = CURRENT_DATE"
        )
        appts_completed = await conn.fetchval(
            "SELECT COUNT(*) FROM appointments WHERE appointment_date = CURRENT_DATE AND status = 'Completed'"
        )

        er_queue = await conn.fetchval("""
            SELECT COUNT(*) FROM admissions a
            JOIN departments d ON d.id = a.department_id
            WHERE d.code = 'ER' AND a.status NOT IN ('Discharged', 'Deceased')
        """) or 0
        
        er_critical = await conn.fetchval("""
            SELECT COUNT(*) FROM admissions a
            JOIN departments d ON d.id = a.department_id
            WHERE d.code = 'ER' AND a.status = 'Critical'
        """) or 0

    return {
        "total_patients": patients or 0,
        "bed_occupancy_pct": occupancy,
        "beds_available": beds_available or 0,
        "beds_total": beds_total or 0,
        "today_appointments": appts_today or 0,
        "appointments_completed": appts_completed or 0,
        "er_queue": er_queue,
        "er_critical": er_critical
    }


@app.get("/api/dashboard/activity")
async def dashboard_activity(limit: int = Query(20, ge=1, le=50)):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                'Admission' AS event,
                p.first_name || ' ' || p.last_name AS patient,
                COALESCE(d.name, 'N/A') AS department,
                COALESCE(s.first_name || ' ' || s.last_name, 'System') AS staff,
                a.admission_date AS event_time
            FROM admissions a
            JOIN patients p ON p.id = a.patient_id
            LEFT JOIN departments d ON d.id = a.department_id
            LEFT JOIN staff s ON s.id = a.attending_doctor_id
            ORDER BY a.admission_date DESC
            LIMIT $1
        """, limit)

    items = []
    for r in rows:
        if r['event_time']:
            now = datetime.now()
            elapsed = now - r['event_time'].replace(tzinfo=None)
            mins = int(elapsed.total_seconds() / 60)
            if mins < 60:
                time_str = f"{mins} min ago"
            elif mins < 1440:
                time_str = f"{mins // 60} hr{'s' if mins//60 > 1 else ''} ago"
            else:
                time_str = f"{mins // 1440} day{'s' if mins//1440 > 1 else ''} ago"
        else:
            time_str = ""

        items.append({
            "time": time_str,
            "event": r["event"],
            "patient": r["patient"],
            "department": r["department"],
            "staff": r["staff"]
        })

    return {"items": items}


# ============================================================
# PATIENTS
# ============================================================

@app.get("/api/patients")
async def list_patients(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    department: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        base = """
            FROM patients p
            LEFT JOIN LATERAL (
                SELECT a.status, a.department_id FROM admissions a
                WHERE a.patient_id = p.id ORDER BY a.admission_date DESC LIMIT 1
            ) la ON true
            LEFT JOIN departments d ON d.id = la.department_id
        """

        if search:
            where_clauses.append(f"(p.first_name ILIKE ${idx} OR p.last_name ILIKE ${idx} OR p.patient_number ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1
        if status:
            where_clauses.append(f"la.status = ${idx}")
            params.append(status)
            idx += 1
        if department:
            where_clauses.append(f"d.name = ${idx}")
            params.append(department)
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        total = await conn.fetchval(f"SELECT COUNT(*) {base} {where}", *params)

        rows = await conn.fetch(f"""
            SELECT p.id, p.patient_number, p.first_name, p.last_name,
                   p.date_of_birth, p.gender, p.phone, p.insurance_provider,
                   p.created_at
            {base} {where}
            ORDER BY p.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {
        "items": serialize(rows_to_list(rows)),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 0
    }


@app.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM patients WHERE id = $1", patient_id)
        if not row:
            raise HTTPException(404, "Patient not found")
    return serialize(row_to_dict(row))


@app.post("/api/patients", status_code=201)
async def create_patient(data: PatientCreate):
    try:
        dob = parse_date(data.date_of_birth)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO patients (
                    first_name, last_name, date_of_birth, gender,
                    national_id, phone, email, address,
                    emergency_contact_name, emergency_contact_phone,
                    blood_type, allergies, chronic_conditions,
                    insurance_provider, insurance_number
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                RETURNING id, patient_number
            """, 
                data.first_name, data.last_name, dob, data.gender,
                data.national_id, data.phone, data.email, data.address,
                data.emergency_contact_name, data.emergency_contact_phone,
                data.blood_type, data.allergies, data.chronic_conditions,
                data.insurance_provider, data.insurance_number
            )
            
            return {
                "message": "Patient registered", 
                "id": str(row["id"]), 
                "patient_number": row["patient_number"]
            }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error creating patient: {e}")
        raise HTTPException(500, f"Database error: {str(e)}")


@app.put("/api/patients/{patient_id}")
async def update_patient(patient_id: str, request: Request):
    body = await request.json()
    if not body:
        raise HTTPException(400, "No fields to update")

    allowed = ['first_name', 'last_name', 'phone', 'email', 'address',
               'emergency_contact_name', 'emergency_contact_phone',
               'allergies', 'chronic_conditions', 'insurance_provider', 'insurance_number']
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(400, "No valid fields to update")

    set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates.keys())]
    query = f"UPDATE patients SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = $1"
    params = [patient_id] + list(updates.values())

    async with pool.acquire() as conn:
        await conn.execute(query, *params)
    return {"message": "Patient updated"}


# ============================================================
# STAFF
# ============================================================

@app.get("/api/staff")
async def list_staff(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[str] = None,
    department_id: Optional[str] = None,
    search: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        if role:
            where_clauses.append(f"s.role = ${idx}")
            params.append(role)
            idx += 1
        if department_id:
            where_clauses.append(f"s.department_id = ${idx}")
            params.append(department_id)
            idx += 1
        if search:
            where_clauses.append(f"(s.first_name ILIKE ${idx} OR s.last_name ILIKE ${idx} OR s.staff_number ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1

        where = "WHERE s.is_active = true" + (" AND " + " AND ".join(where_clauses) if where_clauses else "")

        total = await conn.fetchval(f"SELECT COUNT(*) FROM staff s {where}", *params)

        rows = await conn.fetch(f"""
            SELECT s.id, s.staff_number, s.first_name, s.last_name, s.role,
                   COALESCE(d.name, 'N/A') AS department, s.specialization, s.phone, 
                   COALESCE(s.status, 'Off Duty') AS status
            FROM staff s
            LEFT JOIN departments d ON d.id = s.department_id
            {where}
            ORDER BY s.last_name
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.post("/api/staff", status_code=201)
async def create_staff(data: StaffCreate):
    async with pool.acquire() as conn:
        try:
            hire_date_obj = parse_date(data.hire_date) if data.hire_date else date.today()
            
            row = await conn.fetchrow("""
                INSERT INTO staff (staff_number, first_name, last_name, role, department_id,
                                   specialization, license_number, phone, email, hire_date)
                VALUES (
                    'STF-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(staff_number FROM 5) AS INTEGER)) FROM staff), 0)::TEXT, 3, '0'),
                    $1, $2, $3, $4, $5, $6, $7, $8, $9
                )
                RETURNING id, staff_number
            """, data.first_name, data.last_name, data.role, data.department_id,
                data.specialization, data.license_number, data.phone, data.email, hire_date_obj)
            
            return {"message": "Staff added", "id": str(row["id"]), "staff_number": row["staff_number"]}
        except Exception as e:
            raise HTTPException(500, f"Error creating staff: {str(e)}")


@app.put("/api/staff/{staff_id}")
async def update_staff(staff_id: str, request: Request):
    body = await request.json()
    allowed = ['role', 'department_id', 'specialization', 'phone', 'email', 'status']
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(400, "No valid fields")

    set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates.keys())]
    query = f"UPDATE staff SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = $1"

    async with pool.acquire() as conn:
        await conn.execute(query, *[staff_id] + list(updates.values()))
    return {"message": "Staff updated"}


# ============================================================
# APPOINTMENTS
# ============================================================

@app.get("/api/appointments")
async def list_appointments(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    doctor_id: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        if status:
            where_clauses.append(f"ap.status = ${idx}")
            params.append(status)
            idx += 1
        if doctor_id:
            where_clauses.append(f"ap.doctor_id = ${idx}")
            params.append(doctor_id)
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        total = await conn.fetchval(f"SELECT COUNT(*) FROM appointments ap {where}", *params)

        rows = await conn.fetch(f"""
            SELECT ap.id, ap.appointment_number,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   s.first_name || ' ' || s.last_name AS doctor_name,
                   d.name AS department,
                   ap.appointment_date, ap.appointment_time, ap.type, ap.status
            FROM appointments ap
            JOIN patients p ON p.id = ap.patient_id
            JOIN staff s ON s.id = ap.doctor_id
            JOIN departments d ON d.id = ap.department_id
            {where}
            ORDER BY ap.appointment_date DESC, ap.appointment_time DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.post("/api/appointments", status_code=201)
async def create_appointment(data: AppointmentCreate):
    async with pool.acquire() as conn:
        try:
            appointment_date_obj = parse_date(data.appointment_date)
            
            row = await conn.fetchrow("""
                INSERT INTO appointments (
                    appointment_number, patient_id, doctor_id, department_id,
                    appointment_date, appointment_time, duration_minutes, type, notes
                )
                VALUES (
                    'APT-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(appointment_number FROM 5) AS INTEGER)) FROM appointments), 0)::TEXT, 3, '0'),
                    $1, $2, $3, $4, $5, $6, $7, $8
                )
                RETURNING id, appointment_number
            """, data.patient_id, data.doctor_id, data.department_id,
                appointment_date_obj, data.appointment_time, data.duration_minutes,
                data.type, data.notes)
            
            return {"message": "Appointment scheduled", "id": str(row["id"]), "appointment_number": row["appointment_number"]}
        except Exception as e:
            raise HTTPException(500, f"Error creating appointment: {str(e)}")


@app.post("/api/appointments/{appointment_id}/cancel")
async def cancel_appointment(appointment_id: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE appointments SET status = 'Cancelled', updated_at = NOW() WHERE id = $1", appointment_id)
    return {"message": "Appointment cancelled"}


@app.put("/api/appointments/{appointment_id}")
async def update_appointment(appointment_id: str, request: Request):
    body = await request.json()
    allowed = ['appointment_date', 'appointment_time', 'status', 'notes', 'duration_minutes']
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(400, "No valid fields")

    if 'appointment_date' in updates:
        updates['appointment_date'] = parse_date(updates['appointment_date'])

    set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates.keys())]
    query = f"UPDATE appointments SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = $1"

    async with pool.acquire() as conn:
        await conn.execute(query, *[appointment_id] + list(updates.values()))
    return {"message": "Appointment updated"}


# ============================================================
# BEDS & WARDS
# ============================================================

@app.get("/api/wards")
async def list_wards():
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.id, w.name, w.code, w.floor, COALESCE(d.name, 'N/A') AS department,
                   COUNT(b.id) AS total_beds,
                   COUNT(b.id) FILTER (WHERE b.status = 'Available') AS available,
                   COUNT(b.id) FILTER (WHERE b.status = 'Occupied') AS occupied
            FROM wards w
            LEFT JOIN departments d ON d.id = w.department_id
            LEFT JOIN beds b ON b.ward_id = w.id
            WHERE w.is_active = true
            GROUP BY w.id, d.name ORDER BY w.name
        """)
    return {"items": serialize(rows_to_list(rows))}


@app.get("/api/beds")
async def list_beds(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    ward_id: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        if status:
            where_clauses.append(f"b.status = ${idx}")
            params.append(status)
            idx += 1
        if ward_id:
            where_clauses.append(f"b.ward_id = ${idx}")
            params.append(ward_id)
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        total = await conn.fetchval(f"SELECT COUNT(*) FROM beds b {where}", *params)

        rows = await conn.fetch(f"""
            SELECT b.id, b.bed_number, w.name AS ward, w.floor, b.bed_type, b.status,
                   b.daily_rate,
                   CASE WHEN b.status = 'Occupied' THEN
                       (SELECT p.first_name || ' ' || p.last_name FROM admissions a
                        JOIN patients p ON p.id = a.patient_id
                        WHERE a.bed_id = b.id AND a.status NOT IN ('Discharged','Deceased') LIMIT 1)
                   ELSE NULL END AS patient_name
            FROM beds b
            JOIN wards w ON w.id = b.ward_id
            {where}
            ORDER BY w.name, b.bed_number
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.get("/api/beds/occupancy")
async def bed_occupancy():
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.name AS ward, w.floor,
                   COUNT(*) AS total_beds,
                   COUNT(*) FILTER (WHERE b.status = 'Occupied') AS occupied,
                   COUNT(*) FILTER (WHERE b.status = 'Available') AS available,
                   COALESCE(ROUND(COUNT(*) FILTER (WHERE b.status = 'Occupied')::NUMERIC / NULLIF(COUNT(*), 0) * 100, 1), 0) AS occupancy_pct
            FROM beds b JOIN wards w ON w.id = b.ward_id
            GROUP BY w.name, w.floor ORDER BY occupancy_pct DESC
        """)
    return {"items": serialize(rows_to_list(rows))}


@app.post("/api/beds", status_code=201)
async def create_bed(data: BedCreate):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO beds (bed_number, ward_id, bed_type, daily_rate, status)
            VALUES ($1, $2, $3, $4, 'Available')
            RETURNING id, bed_number
        """, data.bed_number, data.ward_id, data.bed_type, data.daily_rate)
    return {"message": "Bed added", "id": str(row["id"]), "bed_number": row["bed_number"]}


@app.put("/api/beds/{bed_id}")
async def update_bed(bed_id: str, request: Request):
    body = await request.json()
    allowed = ['status', 'daily_rate', 'notes', 'bed_type']
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(400, "No valid fields")

    set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates.keys())]
    query = f"UPDATE beds SET {', '.join(set_parts)}, updated_at = NOW() WHERE id = $1"

    async with pool.acquire() as conn:
        await conn.execute(query, *[bed_id] + list(updates.values()))
    return {"message": "Bed updated"}


# ============================================================
# LAB ORDERS
# ============================================================

@app.get("/api/lab/orders")
async def list_lab_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    patient_id: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        if status:
            where_clauses.append(f"lo.status = ${idx}")
            params.append(status)
            idx += 1
        if patient_id:
            where_clauses.append(f"lo.patient_id = ${idx}")
            params.append(patient_id)
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        total = await conn.fetchval(f"SELECT COUNT(*) FROM lab_orders lo {where}", *params)

        rows = await conn.fetch(f"""
            SELECT lo.id, lo.order_number,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   COALESCE(lt.name, 'Unknown') AS test_type,
                   s.first_name || ' ' || s.last_name AS ordered_by_name,
                   lo.priority, lo.status, lo.result, lo.is_abnormal,
                   lo.ordered_at, lo.completed_at
            FROM lab_orders lo
            JOIN patients p ON p.id = lo.patient_id
            LEFT JOIN lab_test_types lt ON lt.id = lo.test_type_id
            JOIN staff s ON s.id = lo.ordered_by
            {where}
            ORDER BY lo.ordered_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.get("/api/lab/test-types")
async def list_test_types():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, category, normal_range, unit, base_price FROM lab_test_types WHERE is_active = true ORDER BY name")
    return {"items": serialize(rows_to_list(rows))}


@app.post("/api/lab/orders", status_code=201)
async def create_lab_order(data: LabOrderCreate):
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO lab_orders (
                    order_number, patient_id, admission_id, test_type_id, ordered_by, priority, clinical_notes
                )
                VALUES (
                    'LAB-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(order_number FROM 5) AS INTEGER)) FROM lab_orders), 0)::TEXT, 3, '0'),
                    $1, $2, $3, $4, $5, $6
                )
                RETURNING id, order_number
            """, data.patient_id, data.admission_id, data.test_type_id, data.ordered_by, data.priority, data.clinical_notes)
            
            return {"message": "Lab test ordered", "id": str(row["id"]), "order_number": row["order_number"]}
        except Exception as e:
            raise HTTPException(500, f"Error creating lab order: {str(e)}")


@app.put("/api/lab/orders/{order_id}")
async def update_lab_order(order_id: str, request: Request):
    body = await request.json()
    allowed = ['status', 'result', 'result_value', 'result_unit', 'is_abnormal', 'performed_by']
    updates = {k: v for k, v in body.items() if k in allowed and v is not None}

    if updates.get('status') in ['Normal', 'Abnormal']:
        updates['completed_at'] = datetime.utcnow()

    if updates:
        set_parts = [f"{k} = ${i+2}" for i, k in enumerate(updates.keys())]
        query = f"UPDATE lab_orders SET {', '.join(set_parts)} WHERE id = $1"

        async with pool.acquire() as conn:
            await conn.execute(query, *[order_id] + list(updates.values()))
    
    return {"message": "Lab order updated"}


# ============================================================
# PHARMACY
# ============================================================

@app.get("/api/pharmacy/medicines")
async def list_medicines(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    low_stock: bool = False
):
    async with pool.acquire() as conn:
        where_clauses = ["m.is_active = true"]
        params = []
        idx = 1

        if search:
            where_clauses.append(f"(m.name ILIKE ${idx} OR m.code ILIKE ${idx})")
            params.append(f"%{search}%")
            idx += 1
        if low_stock:
            where_clauses.append("m.stock_quantity <= m.reorder_level")

        where = "WHERE " + " AND ".join(where_clauses)
        total = await conn.fetchval(f"SELECT COUNT(*) FROM medicines m {where}", *params)

        rows = await conn.fetch(f"""
            SELECT m.id, m.code, m.name, mc.name AS category,
                   m.stock_quantity, m.unit_price, sup.name AS supplier,
                   m.expiry_date, m.is_controlled
            FROM medicines m
            LEFT JOIN medicine_categories mc ON mc.id = m.category_id
            LEFT JOIN suppliers sup ON sup.id = m.supplier_id
            {where}
            ORDER BY m.name
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.post("/api/pharmacy/medicines", status_code=201)
async def create_medicine(data: MedicineCreate):
    async with pool.acquire() as conn:
        try:
            expiry_date_obj = parse_date(data.expiry_date) if data.expiry_date else None
            
            row = await conn.fetchrow("""
                INSERT INTO medicines (
                    code, name, generic_name, category_id, supplier_id,
                    unit_price, cost_price, stock_quantity, reorder_level,
                    unit, dosage_form, strength, expiry_date, batch_number, is_controlled
                )
                VALUES (
                    'MED-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(code FROM 5) AS INTEGER)) FROM medicines), 0)::TEXT, 3, '0'),
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
                )
                RETURNING id, code
            """, data.name, data.generic_name, data.category_id, data.supplier_id,
                data.unit_price, data.cost_price, data.stock_quantity, data.reorder_level,
                data.unit, data.dosage_form, data.strength, expiry_date_obj, data.batch_number,
                data.is_controlled)
            
            return {"message": "Medicine added", "id": str(row["id"]), "code": row["code"]}
        except Exception as e:
            raise HTTPException(500, f"Error creating medicine: {str(e)}")


# ============================================================
# BILLING
# ============================================================

@app.get("/api/billing/invoices")
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    patient_id: Optional[str] = None
):
    async with pool.acquire() as conn:
        where_clauses = []
        params = []
        idx = 1

        if status:
            where_clauses.append(f"i.status = ${idx}")
            params.append(status)
            idx += 1
        if patient_id:
            where_clauses.append(f"i.patient_id = ${idx}")
            params.append(patient_id)
            idx += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
        total = await conn.fetchval(f"SELECT COUNT(*) FROM invoices i {where}", *params)

        rows = await conn.fetch(f"""
            SELECT i.id, i.invoice_number,
                   p.first_name || ' ' || p.last_name AS patient_name,
                   i.total_amount, i.paid_amount, i.balance,
                   i.status, i.invoice_date, i.due_date, i.notes AS description
            FROM invoices i
            JOIN patients p ON p.id = i.patient_id
            {where}
            ORDER BY i.invoice_date DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """, *params, page_size, (page - 1) * page_size)

    return {"items": serialize(rows_to_list(rows)), "total": total, "page": page, "page_size": page_size, "pages": (total + page_size - 1) // page_size if total else 0}


@app.post("/api/billing/invoices", status_code=201)
async def create_invoice(data: InvoiceCreate):
    total = sum(item.get("quantity", 1) * item.get("unit_price", 0) for item in data.items)

    async with pool.acquire() as conn:
        try:
            due_date_obj = parse_date(data.due_date)
            
            inv = await conn.fetchrow("""
                INSERT INTO invoices (invoice_number, patient_id, admission_id, total_amount, due_date, notes)
                VALUES (
                    'INV-' || TO_CHAR(CURRENT_DATE, 'YYYY') || '-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(invoice_number FROM 12) AS INTEGER)) FROM invoices WHERE invoice_number LIKE 'INV-' || TO_CHAR(CURRENT_DATE, 'YYYY') || '-%'), 0)::TEXT, 4, '0'),
                    $1, $2, $3, $4, $5
                )
                RETURNING id, invoice_number
            """, data.patient_id, data.admission_id, total, due_date_obj, data.notes)

            for item in data.items:
                await conn.execute("""
                    INSERT INTO invoice_items (invoice_id, description, category, quantity, unit_price)
                    VALUES ($1, $2, $3, $4, $5)
                """, inv["id"], item.get("description", ""), item.get("category", "Other"),
                    item.get("quantity", 1), item.get("unit_price", 0))

            return {"message": "Invoice created", "id": str(inv["id"]), "invoice_number": inv["invoice_number"], "total_amount": total}
        except Exception as e:
            raise HTTPException(500, f"Error creating invoice: {str(e)}")


@app.post("/api/billing/payments", status_code=201)
async def record_payment(data: PaymentCreate):
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                INSERT INTO payments (payment_number, invoice_id, amount, method, reference_number, notes)
                VALUES (
                    'PAY-' || TO_CHAR(CURRENT_DATE, 'YYYYMMDD') || '-' || LPAD(COALESCE((SELECT MAX(CAST(SUBSTRING(payment_number FROM 15) AS INTEGER)) FROM payments WHERE payment_number LIKE 'PAY-' || TO_CHAR(CURRENT_DATE, 'YYYYMMDD') || '-%'), 0)::TEXT, 3, '0'),
                    $1, $2, $3, $4, $5
                )
                RETURNING payment_number
            """, data.invoice_id, data.amount, data.method, data.reference_number, data.notes)

            return {"message": "Payment recorded", "payment_number": row["payment_number"]}
        except Exception as e:
            raise HTTPException(500, f"Error recording payment: {str(e)}")


# ============================================================
# DEPARTMENTS
# ============================================================

@app.get("/api/departments")
async def list_departments():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, code, floor FROM departments WHERE is_active = true ORDER BY name")
    return {"items": serialize(rows_to_list(rows))}


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
async def health():
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/")
async def root():
    return {
        "message": "MediCore HMS API",
        "version": "1.0.0",
        "endpoints": {
            "auth": "/api/auth/register",
            "patients": "/api/patients",
            "staff": "/api/staff",
            "appointments": "/api/appointments",
            "beds": "/api/beds",
            "pharmacy": "/api/pharmacy/medicines",
            "billing": "/api/billing/invoices",
            "health": "/api/health"
        }
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("medicore_backend:app", host="0.0.0.0", port=8000, reload=True)

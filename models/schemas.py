from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class LeaveCreate(BaseModel):
    leave_type: str
    start_date: str
    end_date: str
    reason: str

class LeaveResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: Optional[str] = None
    leave_type: str
    start_date: str
    end_date: str
    days: int
    status: str
    reason: Optional[str] = None
    manager_comment: Optional[str] = None
    created_at: datetime

class LeaveStatusUpdate(BaseModel):
    status: str
    manager_comment: Optional[str] = None

class LeaveBalanceResponse(BaseModel):
    employee_id: str
    employee_name: Optional[str] = None
    vacation_total: int
    vacation_used: int
    vacation_remaining: int
    sick_total_monthly: int
    sick_used: int
    sick_remaining: int
    extra_leave: int

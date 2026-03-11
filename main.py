from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
import bcrypt
from models.schemas import UserCreate, UserLogin, UserResponse, Token, LeaveCreate, LeaveResponse, LeaveStatusUpdate, LeaveBalanceResponse
from bson import ObjectId
from datetime import datetime, timedelta
from jose import JWTError, jwt
from pymongo import MongoClient
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
client = MongoClient(MONGO_URI)
DB_CONNECTED = False

try:
    client.admin.command('ping')
    DB_CONNECTED = True
    print("✅ Connected to MongoDB Atlas")
except Exception as e:
    DB_CONNECTED = False
    print(f"❌ MongoDB connection failed: {e}")

db = client.employee_management
users_collection = db["users"]
leave_applications_collection = db["leave_applications"]
leave_balance_collection = db["leave_balance"]

@app.get("/health")
async def health_check():
    if not DB_CONNECTED:
        raise HTTPException(status_code=503, detail="Database connection failed")
    return {"status": "healthy", "database": "connected"}

# Security Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-that-should-be-in-env")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# SMTP Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "biswapvt506@gmail.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "ccxq roxy mqjm hrrn")

# Helper Functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def send_email(to_email: str, subject: str, content: str):
    msg = EmailMessage()
    msg.set_content(content)
    msg['Subject'] = subject
    msg['From'] = SMTP_EMAIL
    msg['To'] = to_email

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent successfully to {to_email}")
    except Exception as e:
        print(f"Failed to send email to {to_email}: {e}")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = users_collection.find_one({"email": email})
    if user is None:
        raise credentials_exception
    return user

async def check_manager_role(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "manager":
        raise HTTPException(status_code=403, detail="Not authorized")
    return current_user

# Startup Event for Default Manager
@app.on_event("startup")
async def startup_event():
    manager_email = "biswapvt506@gmail.com"
    existing_manager = users_collection.find_one({"email": manager_email})
    if not existing_manager:
        hashed_password = get_password_hash("Manager1@123")
        new_manager = {
            "name": "Default Manager",
            "email": manager_email,
            "password": hashed_password,
            "role": "manager",
            "created_at": datetime.utcnow()
        }
        users_collection.insert_one(new_manager)
        print("Default manager created")

# Authentication Routes
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/login")
async def login_user(user_login: UserLogin):
    user = users_collection.find_one({"email": user_login.email})
    if not user or not verify_password(user_login.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "role": user["role"]
        }
    }

# Manager Routes
@app.post("/employees", response_model=UserResponse)
async def create_employee(user: UserCreate, background_tasks: BackgroundTasks, current_user: dict = Depends(check_manager_role)):
    existing_user = users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    new_user = {
        "name": user.name,
        "email": user.email,
        "password": hashed_password,
        "role": "employee",
        "created_at": datetime.utcnow()
    }
    result = users_collection.insert_one(new_user)
    
    # Initialize Leave Balance
    leave_balance = {
        "employee_id": str(result.inserted_id),
        "vacation_total": 20,
        "vacation_used": 0,
        "vacation_remaining": 20,
        "sick_total_monthly": 3,
        "sick_used": 0,
        "sick_remaining": 3,
        "extra_leave": 0
    }
    leave_balance_collection.insert_one(leave_balance)
    
    # Send Email Notification
    email_content = f"""
    Subject: Your Employee Account

    Welcome to the company.

    Your employee account has been created.

    Login Credentials:

    Email: {user.email}
    Password: {user.password}

    Please login and change your password.
    """
    background_tasks.add_task(send_email, user.email, "Your Employee Account", email_content)
    
    user_out = users_collection.find_one({"_id": result.inserted_id})
    user_out["id"] = str(user_out["_id"])
    del user_out["_id"]
    return user_out

@app.get("/employees", response_model=list[UserResponse])
async def get_employees(current_user: dict = Depends(check_manager_role)):
    employees = list(users_collection.find({"role": "employee"}))
    for emp in employees:
        emp["id"] = str(emp["_id"])
        del emp["_id"]
    return employees

@app.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, current_user: dict = Depends(check_manager_role)):
    try:
        obj_id = ObjectId(employee_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid employee ID")
    
    result = users_collection.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Employee not found")
        
    leave_applications_collection.delete_many({"employee_id": employee_id})
    leave_balance_collection.delete_one({"employee_id": employee_id})
    
    return {"message": "Employee deleted successfully"}

# Leave Routes

def calculate_leave_days(start_date_str, end_date_str):
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        
        if end_date < start_date:
            return 0
            
        days = 0
        current_date = start_date
        while current_date <= end_date:
            if current_date.weekday() != 6: # 6 is Sunday
                days += 1
            current_date += timedelta(days=1)
        return days
    except ValueError:
        return 0

@app.post("/leaves", response_model=LeaveResponse)
async def apply_leave(leave: LeaveCreate, current_user: dict = Depends(get_current_user)):
    days = calculate_leave_days(leave.start_date, leave.end_date)
    if days <= 0:
        raise HTTPException(status_code=400, detail="Invalid date range or no working days selected")
        
    new_leave = {
        "employee_id": str(current_user["_id"]),
        "leave_type": leave.leave_type,
        "start_date": leave.start_date,
        "end_date": leave.end_date,
        "reason": leave.reason, # Keeping it to store, not added in schema return
        "days": days,
        "status": "pending",
        "manager_comment": None,
        "created_at": datetime.utcnow()
    }
    
    result = leave_applications_collection.insert_one(new_leave)
    leave_out = leave_applications_collection.find_one({"_id": result.inserted_id})
    leave_out["id"] = str(leave_out["_id"])
    del leave_out["_id"]
    return leave_out

@app.get("/my-leaves", response_model=list[LeaveResponse])
async def get_my_leaves(current_user: dict = Depends(get_current_user)):
    leaves = list(leave_applications_collection.find({"employee_id": str(current_user["_id"])}).sort("created_at", -1))
    for leave in leaves:
        leave["id"] = str(leave["_id"])
        del leave["_id"]
    return leaves

@app.get("/leaves", response_model=list[LeaveResponse])
async def get_all_leaves(current_user: dict = Depends(check_manager_role)):
    # Filter out leaves that the manager has explicitly hidden from their feed
    leaves = list(leave_applications_collection.find({
        "hidden_from_manager_feed": {"$ne": True}
    }).sort("created_at", -1))
    
    for leave in leaves:
        leave["id"] = str(leave["_id"])
        del leave["_id"]
        
        # Add employee name for UI convenience if needed
        emp = users_collection.find_one({"_id": ObjectId(leave["employee_id"])})
        if emp:
            leave["employee_name"] = emp["name"]
            
    return leaves

@app.put("/leaves/{leave_id}")
async def update_leave_status(leave_id: str, update_data: LeaveStatusUpdate, background_tasks: BackgroundTasks, current_user: dict = Depends(check_manager_role)):
    try:
        obj_id = ObjectId(leave_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid leave ID")
        
    leave_req = leave_applications_collection.find_one({"_id": obj_id})
    if not leave_req:
        raise HTTPException(status_code=404, detail="Leave request not found")
        
    # Update Status
    leave_applications_collection.update_one(
        {"_id": obj_id},
        {"$set": {
            "status": update_data.status,
            "manager_comment": update_data.manager_comment
        }}
    )

    employee = users_collection.find_one({"_id": ObjectId(leave_req["employee_id"])})
    
    if update_data.status == "approved":
        # Deduct balances
        balance = leave_balance_collection.find_one({"employee_id": leave_req["employee_id"]})
        if balance:
            days = leave_req["days"]
            update_fields = {}
            
            if leave_req["leave_type"].lower() == "vacation leave":
                vacation_remaining = balance.get("vacation_remaining", 20)
                if vacation_remaining >= days:
                    update_fields = {
                        "vacation_remaining": vacation_remaining - days,
                        "vacation_used": balance.get("vacation_used", 0) + days
                    }
                else: # Extra leave
                    update_fields = {
                        "vacation_remaining": 0,
                        "vacation_used": balance.get("vacation_total", 20),
                        "extra_leave": balance.get("extra_leave", 0) + (days - vacation_remaining)
                    }
            elif leave_req["leave_type"].lower() == "sick leave":
                sick_remaining = balance.get("sick_remaining", 3)
                if sick_remaining >= days:
                    update_fields = {
                        "sick_remaining": sick_remaining - days,
                        "sick_used": balance.get("sick_used", 0) + days
                    }
                else: # Extra leave
                    update_fields = {
                        "sick_remaining": 0,
                        "sick_used": balance.get("sick_total_monthly", 3),
                        "extra_leave": balance.get("extra_leave", 0) + (days - sick_remaining)
                    }
            
            if update_fields:
                leave_balance_collection.update_one(
                    {"employee_id": leave_req["employee_id"]},
                    {"$set": update_fields}
                )
        
        # Send Email
        if employee:
            background_tasks.add_task(
                send_email,
                employee["email"],
                "Leave Application Approved",
                f"Your leave request for {leave_req['days']} days from {leave_req['start_date']} to {leave_req['end_date']} has been approved."
            )
            
    elif update_data.status == "rejected":
        if employee:
            admin_comment = update_data.manager_comment or "No reason provided."
            background_tasks.add_task(
                send_email,
                employee["email"],
                "Leave Application Rejected",
                f"Your leave request from {leave_req['start_date']} to {leave_req['end_date']} has been rejected.\nManager Comment: {admin_comment}"
            )
            
    return {"message": f"Leave {update_data.status} successfully"}

@app.delete("/leaves/{leave_id}")
async def delete_leave(leave_id: str, current_user: dict = Depends(check_manager_role)):
    try:
        obj_id = ObjectId(leave_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid leave ID")
        
    # Instead of deleting, we hide it from the manager's view
    # This keeps the 'Holiday Data' intact for the employee
    result = leave_applications_collection.update_one(
        {"_id": obj_id},
        {"$set": {"hidden_from_manager_feed": True}}
    )
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Leave request not found")
        
    return {"message": "Leave record hidden from manager feed"}

@app.get("/my-balance", response_model=LeaveBalanceResponse)
async def get_my_balance(current_user: dict = Depends(get_current_user)):
    balance = leave_balance_collection.find_one({"employee_id": str(current_user["_id"])})
    if not balance:
        raise HTTPException(status_code=404, detail="Leave balance not found")
    balance["id"] = str(balance["_id"])
    del balance["_id"]
    return balance

@app.get("/employee-balance/{employee_id}")
async def get_employee_balance(employee_id: str, current_user: dict = Depends(check_manager_role)):
    balance = leave_balance_collection.find_one({"employee_id": employee_id})
    if not balance:
        raise HTTPException(status_code=404, detail="Leave balance not found")
    # Fetch user for name details in UI
    try:
        user = users_collection.find_one({"_id": ObjectId(employee_id)})
        if user:
             balance['employee_name'] = user['name']
    except:
        pass
    balance["id"] = str(balance["_id"])
    del balance["_id"]
    return balance

@app.get("/employee-leaves/{employee_id}")
async def get_employee_leaves(employee_id: str, current_user: dict = Depends(check_manager_role)):
    leaves = list(leave_applications_collection.find({"employee_id": employee_id}).sort("created_at", -1))
    for leave in leaves:
        leave["id"] = str(leave["_id"])
        del leave["_id"]
    return leaves

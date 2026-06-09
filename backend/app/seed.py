"""Seed demo users on startup."""

from passlib.context import CryptContext
from sqlalchemy.orm import Session
import uuid

from app.models import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

DEMO_USERS = [
    ("lili", "小李", "finance123", UserRole.FINANCE),
    ("wangzong", "王总", "manager123", UserRole.MANAGER),
    ("ops1", "运营张三", "ops123", UserRole.OPS),
    ("admin", "系统管理员", "admin123", UserRole.ADMIN),
]


def seed_users(db: Session):
    for username, display_name, password, role in DEMO_USERS:
        exists = db.query(User).filter(User.username == username).first()
        if exists:
            continue
        db.add(
            User(
                id=str(uuid.uuid4()),
                username=username,
                display_name=display_name,
                password_hash=pwd_context.hash(password),
                role=role.value,
            )
        )
    db.commit()

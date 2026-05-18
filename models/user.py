from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship, validates

from database.base import Base
from models._validation import clean_string, utc_now, validate_email


class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    username = Column(String(100), nullable=False)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    videos = relationship("Video", back_populates="user", cascade="all, delete-orphan")
    analysis_jobs = relationship("AnalysisJob", back_populates="user", cascade="all, delete-orphan")

    @validates("username")
    def validate_username(self, _key, value):
        return clean_string(value, "username", min_length=3, max_length=100, required=True)

    @validates("email")
    def validate_user_email(self, _key, value):
        return validate_email(value)

    @validates("password_hash")
    def validate_password_hash(self, _key, value):
        return clean_string(value, "password_hash", max_length=255, required=True)

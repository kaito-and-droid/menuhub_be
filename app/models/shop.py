import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPkMixin
from app.models.enums import UserRole


class Shop(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "shops"

    # use_alter breaks the shops<->users FK cycle: this FK is added after both tables exist
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", use_alter=True, name="fk_shops_owner_id")
    )
    shop_name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(500))
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Ho_Chi_Minh")
    currency: Mapped[str] = mapped_column(String(10), default="VND")
    payment_methods: Mapped[dict] = mapped_column(
        JSONB, default=lambda: {"cash": True, "bank_transfer": True, "stripe": False}
    )
    facebook_page_id: Mapped[str | None] = mapped_column(String(100))
    facebook_app_access_token: Mapped[str | None] = mapped_column(String(500))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list["User"]] = relationship(
        back_populates="shop", foreign_keys="User.shop_id"
    )


class User(Base, UUIDPkMixin, CreatedAtMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("shop_id", "email", name="uq_users_shop_email"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shops.id"))
    # Globally unique for now so login-by-email is unambiguous (deviation from spec noted in docs)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"))

    shop: Mapped[Shop] = relationship(back_populates="users", foreign_keys=[shop_id])

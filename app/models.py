from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Position(Base):
    __tablename__ = "positions"

    id = Column(String(20), primary_key=True)
    name = Column(String(50), nullable=False)
    approval_level = Column(Integer, nullable=False, default=0)
    can_approve = Column(Boolean, nullable=False, default=False)


class Department(Base):
    __tablename__ = "departments"

    id = Column(String(20), primary_key=True)
    name = Column(String(80), nullable=False)
    manager_employee_id = Column(String(20), ForeignKey("employees.id"))


class Section(Base):
    __tablename__ = "sections"

    id = Column(String(20), primary_key=True)
    name = Column(String(80), nullable=False)
    department_id = Column(String(20), ForeignKey("departments.id"), nullable=False)
    manager_employee_id = Column(String(20), ForeignKey("employees.id"))

    department = relationship("Department", foreign_keys=[department_id])


class Employee(Base):
    __tablename__ = "employees"

    id = Column(String(20), primary_key=True)
    name = Column(String(80), nullable=False)
    email = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=False)
    department_id = Column(String(20), ForeignKey("departments.id"), nullable=False)
    section_id = Column(String(20), ForeignKey("sections.id"), nullable=False)
    position_id = Column(String(20), ForeignKey("positions.id"), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    department = relationship("Department", foreign_keys=[department_id])
    section = relationship("Section", foreign_keys=[section_id])
    position = relationship("Position")


class ApplicationType(Base):
    __tablename__ = "application_types"

    id = Column(String(20), primary_key=True)
    name = Column(String(50), nullable=False)
    description = Column(String(255), nullable=False)
    requires_amount = Column(Boolean, nullable=False, default=False)
    requires_target_date = Column(Boolean, nullable=False, default=False)

    approval_route_steps = relationship(
        "ApplicationTypeApprovalRoute",
        order_by="ApplicationTypeApprovalRoute.step_no",
        back_populates="application_type",
        cascade="all, delete-orphan",
    )


class ApplicationTypeApprovalRoute(Base):
    __tablename__ = "application_type_approval_routes"

    application_type_id = Column(
        String(20),
        ForeignKey("application_types.id", ondelete="CASCADE"),
        primary_key=True,
    )
    step_no = Column(Integer, primary_key=True)
    position_id = Column(String(20), ForeignKey("positions.id"), nullable=False)

    application_type = relationship("ApplicationType", back_populates="approval_route_steps")
    position = relationship("Position")


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_type_id = Column(String(20), ForeignKey("application_types.id"), nullable=False)
    applicant_id = Column(String(20), ForeignKey("employees.id"), nullable=False)
    title = Column(String(120), nullable=False)
    amount = Column(Numeric(12, 0))
    target_date = Column(Date)
    detail_json = Column(Text)
    returned_fields_json = Column(Text)
    reason = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    current_step_no = Column(Integer)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    application_type = relationship("ApplicationType")
    applicant = relationship("Employee", foreign_keys=[applicant_id])
    approval_steps = relationship("ApprovalStep", order_by="ApprovalStep.step_no", back_populates="application")
    histories = relationship("ApprovalHistory", order_by="ApprovalHistory.created_at", back_populates="application")


class ApplicationTemplate(Base):
    __tablename__ = "application_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), ForeignKey("employees.id"), nullable=False)
    name = Column(String(120), nullable=False)
    application_type_id = Column(String(20), ForeignKey("application_types.id"), nullable=False)
    form_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    employee = relationship("Employee", foreign_keys=[employee_id])
    application_type = relationship("ApplicationType")


class ApprovalStep(Base):
    __tablename__ = "approval_steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    step_no = Column(Integer, nullable=False)
    approver_id = Column(String(20), ForeignKey("employees.id"), nullable=False)
    role_label = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False, default="not_reached")
    acted_at = Column(DateTime)
    comment = Column(Text)

    application = relationship("Application", back_populates="approval_steps")
    approver = relationship("Employee", foreign_keys=[approver_id])


class ApprovalHistory(Base):
    __tablename__ = "approval_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    step_no = Column(Integer)
    actor_id = Column(String(20), ForeignKey("employees.id"), nullable=False)
    action = Column(String(30), nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    application = relationship("Application", back_populates="histories")
    actor = relationship("Employee", foreign_keys=[actor_id])


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), ForeignKey("employees.id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.id"))
    message = Column(String(255), nullable=False)
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

from functools import wraps
import time

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .db import db_session
from .models import (
    Application,
    ApplicationTemplate,
    ApplicationType,
    ApplicationTypeApprovalRoute,
    ApprovalHistory,
    ApprovalStep,
    Department,
    Employee,
    Notification,
    Position,
    Section,
)
from .pdf import build_application_pdf
from .services import (
    act_on_application,
    action_label,
    approval_progress,
    approval_route_catalog,
    application_to_form_values,
    build_form_snapshot,
    confirmation_items,
    create_application,
    create_template_from_application,
    current_approval_label,
    detail_dict,
    detail_items,
    returned_field_items,
    returned_field_keys,
    review_fields,
    save_draft_application,
    status_label,
    submit_draft_application,
    step_status_label,
    template_to_form_values,
    update_returned_application,
)


bp = Blueprint("main", __name__)


@bp.app_template_filter("status_label")
def _status_label(value):
    return status_label(value)


@bp.app_template_filter("step_status_label")
def _step_status_label(value):
    return step_status_label(value)


@bp.app_template_filter("detail_items")
def _detail_items(value):
    return detail_items(value)


@bp.app_template_filter("action_label")
def _action_label(value):
    return action_label(value)


@bp.app_template_filter("current_approval_label")
def _current_approval_label(value):
    return current_approval_label(value)


@bp.app_template_filter("approval_progress")
def _approval_progress(value):
    return approval_progress(value)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "employee_id" not in session:
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped


def current_user(session_db):
    return session_db.get(Employee, session["employee_id"])


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        with db_session() as session_db:
            user = current_user(session_db)
            if not user or not user.is_admin:
                flash("管理者のみ利用できます。")
                return redirect(url_for("main.dashboard"))
        return view(*args, **kwargs)

    return wrapped


def bool_from_form(name):
    return request.form.get(name) == "on"


@bp.app_context_processor
def nav_counts():
    if "employee_id" not in session:
        return {"nav_unread_count": 0, "nav_waiting_count": 0}
    with db_session() as session_db:
        employee_id = session["employee_id"]
        unread_count = session_db.scalar(
            select(func.count()).select_from(Notification).where(
                Notification.employee_id == employee_id,
                Notification.is_read.is_(False),
            )
        )
        waiting_count = session_db.scalar(
            select(func.count()).select_from(ApprovalStep).where(
                ApprovalStep.approver_id == employee_id,
                ApprovalStep.status == "waiting",
            )
        )
        return {"nav_unread_count": unread_count, "nav_waiting_count": waiting_count}


def update_primary_id(session_db, table_name, old_id, new_id, references):
    if old_id == new_id:
        return
    exists = session_db.execute(
        text(f"SELECT id FROM {table_name} WHERE id = :new_id"),
        {"new_id": new_id},
    ).first()
    if exists:
        raise ValueError(f"ID {new_id} はすでに使用されています。")

    session_db.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        for ref_table, ref_column in references:
            session_db.execute(
                text(f"UPDATE {ref_table} SET {ref_column} = :new_id WHERE {ref_column} = :old_id"),
                {"new_id": new_id, "old_id": old_id},
            )
        session_db.execute(
            text(f"UPDATE {table_name} SET id = :new_id WHERE id = :old_id"),
            {"new_id": new_id, "old_id": old_id},
        )
    finally:
        session_db.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def admin_master_data(session_db):
    return {
        "all_applications": session_db.scalars(
            select(Application).order_by(Application.created_at.desc(), Application.id.desc())
        ).all(),
        "all_histories": session_db.scalars(
            select(ApprovalHistory).order_by(ApprovalHistory.created_at.desc(), ApprovalHistory.id.desc())
        ).all(),
        "employees": session_db.scalars(select(Employee).order_by(Employee.id)).all(),
        "departments": session_db.scalars(select(Department).order_by(Department.id)).all(),
        "sections": session_db.scalars(select(Section).order_by(Section.id)).all(),
        "positions": session_db.scalars(select(Position).order_by(Position.id)).all(),
        "application_types": session_db.scalars(select(ApplicationType).order_by(ApplicationType.id)).all(),
    }


def can_view_application(user, application):
    if user.is_admin or application.applicant_id == user.id:
        return True
    return any(step.approver_id == user.id for step in application.approval_steps)


def approval_positions(session_db):
    return session_db.scalars(
        select(Position)
        .where(Position.can_approve.is_(True))
        .order_by(Position.approval_level, Position.id)
    ).all()


def normalize_route_position_ids(session_db):
    route_position_ids = [
        position_id
        for position_id in request.form.getlist("route_position_id")
        if position_id
    ]
    valid_positions = {
        position.id: position
        for position in approval_positions(session_db)
    }
    if not route_position_ids:
        raise ValueError("承認経路に役職を1つ以上設定してください。")
    if len(route_position_ids) != len(set(route_position_ids)):
        raise ValueError("同じ役職を承認経路に複数回設定することはできません。")
    invalid_ids = [position_id for position_id in route_position_ids if position_id not in valid_positions]
    if invalid_ids:
        raise ValueError("承認可能ではない役職が選択されています。")

    if bool_from_form("requires_amount"):
        if "POS006" not in valid_positions:
            raise ValueError("金額を扱う申請に必要な経理責任者の役職がありません。")
        route_position_ids = [position_id for position_id in route_position_ids if position_id != "POS006"]
        route_position_ids.append("POS006")
    return route_position_ids


def replace_application_type_route(session_db, application_type_id, route_position_ids):
    session_db.execute(
        delete(ApplicationTypeApprovalRoute).where(
            ApplicationTypeApprovalRoute.application_type_id == application_type_id
        )
    )
    session_db.add_all(
        [
            ApplicationTypeApprovalRoute(
                application_type_id=application_type_id,
                step_no=step_no,
                position_id=position_id,
            )
            for step_no, position_id in enumerate(route_position_ids, start=1)
        ]
    )


@bp.route("/", methods=["GET"])
def index():
    if "employee_id" in session:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("main.login"))


@bp.route("/healthz", methods=["GET"])
def healthz():
    return {"status": "ok"}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        employee_id = request.form["employee_id"]
        password = request.form["password"]
        with db_session() as session_db:
            employee = session_db.get(Employee, employee_id)
            if employee and employee.is_active and check_password_hash(employee.password_hash, password):
                session.clear()
                session.permanent = True
                session["employee_id"] = employee.id
                session["_startup_id"] = current_app.config["SESSION_STARTUP_ID"]
                session["_last_activity"] = int(time.time())
                return redirect(url_for("main.dashboard"))
        flash("社員IDまたはパスワードが正しくありません。")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    if request.args.get("reason") == "timeout":
        flash("一定時間操作がなかったため、自動的にログアウトしました。")
    return redirect(url_for("main.login"))


@bp.route("/session/keepalive", methods=["POST"])
@login_required
def session_keepalive():
    return "", 204


@bp.route("/account")
@login_required
def account():
    with db_session() as session_db:
        user = current_user(session_db)
        my_count = session_db.scalar(select(func.count()).select_from(Application).where(Application.applicant_id == user.id))
        waiting_count = session_db.scalar(
            select(func.count()).select_from(ApprovalStep).where(
                ApprovalStep.approver_id == user.id,
                ApprovalStep.status == "waiting",
            )
        )
        return render_template("account.html", user=user, my_count=my_count, waiting_count=waiting_count)


@bp.route("/account/password", methods=["POST"])
@login_required
def account_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    password_confirmation = request.form.get("password_confirmation", "")

    if not current_password or not new_password or not password_confirmation:
        flash("すべてのパスワード欄を入力してください。")
        return redirect(url_for("main.account"))
    if len(new_password) < 8:
        flash("新しいパスワードは8文字以上で入力してください。")
        return redirect(url_for("main.account"))
    if len(new_password) > 128:
        flash("新しいパスワードは128文字以内で入力してください。")
        return redirect(url_for("main.account"))
    if new_password != password_confirmation:
        flash("新しいパスワードと確認用パスワードが一致しません。")
        return redirect(url_for("main.account"))

    with db_session() as session_db:
        user = current_user(session_db)
        if not check_password_hash(user.password_hash, current_password):
            flash("現在のパスワードが正しくありません。")
            return redirect(url_for("main.account"))
        if check_password_hash(user.password_hash, new_password):
            flash("現在とは異なるパスワードを設定してください。")
            return redirect(url_for("main.account"))
        user.password_hash = generate_password_hash(new_password)

    session.clear()
    flash("パスワードを変更しました。新しいパスワードでログインしてください。")
    return redirect(url_for("main.login"))


@bp.route("/help")
@login_required
def help_page():
    with db_session() as session_db:
        user = current_user(session_db)
        return render_template("help.html", user=user)


@bp.route("/approval-routes")
@login_required
def approval_routes():
    with db_session() as session_db:
        user = current_user(session_db)
        application_types = session_db.scalars(select(ApplicationType).order_by(ApplicationType.id)).all()
        employees = session_db.scalars(select(Employee).order_by(Employee.id)).all()
        employee_by_id = {employee.id: employee for employee in employees}

        departments = []
        for department in session_db.scalars(select(Department).order_by(Department.id)).all():
            manager = employee_by_id.get(department.manager_employee_id)
            departments.append(
                {
                    "id": department.id,
                    "name": department.name,
                    "manager_employee_id": department.manager_employee_id,
                    "manager_name": manager.name if manager else "-",
                }
            )

        sections = []
        for section in session_db.scalars(select(Section).order_by(Section.department_id, Section.id)).all():
            manager = employee_by_id.get(section.manager_employee_id)
            sections.append(
                {
                    "id": section.id,
                    "name": section.name,
                    "department_name": section.department.name,
                    "manager_employee_id": section.manager_employee_id,
                    "manager_name": manager.name if manager else "-",
                }
            )

        common_roles = [
            {"label": "経理責任者", "position_id": "POS006", "description": "金額を扱うすべての申請を最終段階で確認します。"},
            {"label": "購買担当", "position_id": "POS007", "description": "一定額以上の購買申請を確認します。"},
            {"label": "役員", "position_id": "POS005", "description": "高額な購買申請や稟議申請を最終承認します。"},
        ]
        for role in common_roles:
            approvers = [employee for employee in employees if employee.position_id == role["position_id"] and employee.is_active]
            role["approvers"] = approvers

        return render_template(
            "approval_routes.html",
            user=user,
            route_catalog=approval_route_catalog(application_types),
            departments=departments,
            sections=sections,
            common_roles=common_roles,
        )


@bp.route("/dashboard")
@login_required
def dashboard():
    with db_session() as session_db:
        user = current_user(session_db)
        my_count = session_db.scalar(select(func.count()).select_from(Application).where(Application.applicant_id == user.id))
        waiting_count = session_db.scalar(
            select(func.count()).select_from(ApprovalStep).where(
                ApprovalStep.approver_id == user.id,
                ApprovalStep.status == "waiting",
            )
        )
        unread_notifications = session_db.scalars(
            select(Notification)
            .where(Notification.employee_id == user.id, Notification.is_read.is_(False))
            .order_by(Notification.created_at.desc())
            .limit(5)
        ).all()
        status_counts = {
            status: session_db.scalar(
                select(func.count()).select_from(Application).where(
                    Application.applicant_id == user.id,
                    Application.status == status,
                )
            )
            for status in ["draft", "pending", "returned", "approved", "rejected"]
        }
        recent_applications = session_db.scalars(
            select(Application)
            .where(Application.applicant_id == user.id)
            .order_by(Application.updated_at.desc())
            .limit(5)
        ).all()
        return render_template(
            "dashboard.html",
            user=user,
            my_count=my_count,
            waiting_count=waiting_count,
            notifications=unread_notifications,
            status_counts=status_counts,
            recent_applications=recent_applications,
        )


@bp.route("/applications")
@login_required
def applications():
    with db_session() as session_db:
        user = current_user(session_db)
        application_types = session_db.scalars(select(ApplicationType).order_by(ApplicationType.id)).all()
        stmt = select(Application).where(Application.applicant_id == user.id)
        status = request.args.get("status", "")
        application_type_id = request.args.get("application_type_id", "")
        keyword = request.args.get("keyword", "").strip()
        date_from = request.args.get("date_from", "")
        date_to = request.args.get("date_to", "")
        amount_min = request.args.get("amount_min", "")
        amount_max = request.args.get("amount_max", "")
        sort = request.args.get("sort", "created_desc")
        if status:
            stmt = stmt.where(Application.status == status)
        if application_type_id:
            stmt = stmt.where(Application.application_type_id == application_type_id)
        if keyword:
            stmt = stmt.where(Application.title.like(f"%{keyword}%"))
        if date_from:
            stmt = stmt.where(func.date(Application.created_at) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(Application.created_at) <= date_to)
        if amount_min:
            stmt = stmt.where(Application.amount >= int(amount_min))
        if amount_max:
            stmt = stmt.where(Application.amount <= int(amount_max))
        sort_columns = {
            "created_asc": Application.created_at.asc(),
            "created_desc": Application.created_at.desc(),
            "amount_asc": Application.amount.asc(),
            "amount_desc": Application.amount.desc(),
            "updated_desc": Application.updated_at.desc(),
        }
        items = session_db.scalars(stmt.order_by(sort_columns.get(sort, Application.created_at.desc()))).all()
        return render_template(
            "applications/list.html",
            user=user,
            applications=items,
            application_types=application_types,
            filters={
                "status": status,
                "application_type_id": application_type_id,
                "keyword": keyword,
                "date_from": date_from,
                "date_to": date_to,
                "amount_min": amount_min,
                "amount_max": amount_max,
                "sort": sort,
            },
        )


@bp.route("/applications/new", methods=["GET", "POST"])
@login_required
def application_new():
    with db_session() as session_db:
        user = current_user(session_db)
        types = session_db.scalars(select(ApplicationType).order_by(ApplicationType.id)).all()
        departments = session_db.scalars(select(Department).order_by(Department.id)).all()
        templates = session_db.scalars(
            select(ApplicationTemplate)
            .where(ApplicationTemplate.employee_id == user.id)
            .order_by(ApplicationTemplate.created_at.desc())
        ).all()
        template = session_db.get(ApplicationTemplate, request.args.get("template")) if request.args.get("template") else None
        template_values = template_to_form_values(template) if template and template.employee_id == user.id else {}
        selected_type_id = request.form.get("application_type_id") or request.args.get("type") or template_values.get("application_type_id") or (types[0].id if types else "")
        selected_application_type = next((item for item in types if item.id == selected_type_id), None)
        if request.method == "POST":
            try:
                form_action = request.form.get("form_action", "confirm")
                if form_action == "draft":
                    app = save_draft_application(session_db, user, request.form)
                    flash(f"申請 No.{app.id} を下書き保存しました。")
                    return redirect(url_for("main.applications", status="draft"))
                if form_action == "submit":
                    app = create_application(session_db, user, request.form)
                    flash(f"申請 No.{app.id} を提出しました。")
                    return redirect(url_for("main.application_detail", application_id=app.id))
                return render_template(
                    "applications/confirm.html",
                    user=user,
                    app=None,
                    form_values=build_form_snapshot(request.form),
                    confirm_items=confirmation_items(request.form, types, departments),
                    submit_label="この内容で申請する",
                    back_url=url_for("main.application_new", type=request.form["application_type_id"]),
                )
            except ValueError as exc:
                flash(str(exc))
                selected_type_id = request.form.get("application_type_id") or selected_type_id
                selected_application_type = next((item for item in types if item.id == selected_type_id), None)
        return render_template(
            "applications/form.html",
            user=user,
            application_types=types,
            departments=departments,
            templates=templates,
            selected_type_id=selected_type_id,
            selected_application_type=selected_application_type,
            app=None,
            detail_values=template_values,
            form_values=template_values,
            returned_fields=set(),
            returned_items=[],
        )


@bp.route("/applications/<int:application_id>")
@login_required
def application_detail(application_id):
    with db_session() as session_db:
        user = current_user(session_db)
        app = session_db.get(Application, application_id)
        if not app:
            flash("申請が見つかりません。")
            return redirect(url_for("main.dashboard"))
        if not can_view_application(user, app):
            flash("この申請を表示する権限がありません。")
            return redirect(url_for("main.dashboard"))
        can_act = any(step.approver_id == user.id and step.status == "waiting" for step in app.approval_steps)
        current_step = next((step for step in app.approval_steps if step.status == "waiting"), None)
        can_edit = app.applicant_id == user.id and app.status in {"returned", "draft"}
        session_db.query(Notification).filter(
            Notification.employee_id == user.id,
            Notification.application_id == app.id,
            Notification.is_read.is_(False),
        ).update({"is_read": True})
        return render_template(
            "applications/detail.html",
            user=user,
            app=app,
            can_act=can_act,
            can_edit=can_edit,
            current_step=current_step,
            review_fields=review_fields(app),
            returned_items=returned_field_items(app),
        )


@bp.route("/applications/<int:application_id>/pdf")
@login_required
def application_pdf(application_id):
    with db_session() as session_db:
        user = current_user(session_db)
        app = session_db.get(Application, application_id)
        if not app:
            flash("申請が見つかりません。")
            return redirect(url_for("main.applications"))
        if not can_view_application(user, app):
            flash("この申請のPDFを出力する権限がありません。")
            return redirect(url_for("main.dashboard"))
        download = request.args.get("download") == "1"
        pdf = build_application_pdf(app)
        return send_file(
            pdf,
            mimetype="application/pdf",
            as_attachment=download,
            download_name=f"{app.application_type.name}_{app.id}.pdf",
        )


@bp.route("/applications/<int:application_id>/template", methods=["POST"])
@login_required
def application_template_create(application_id):
    with db_session() as session_db:
        user = current_user(session_db)
        app = session_db.get(Application, application_id)
        if not app:
            flash("申請が見つかりません。")
            return redirect(url_for("main.applications"))
        try:
            create_template_from_application(session_db, user, app, request.form.get("template_name"))
            flash("テンプレートを保存しました。")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("main.application_detail", application_id=application_id))


@bp.route("/applications/<int:application_id>/edit", methods=["GET", "POST"])
@login_required
def application_edit(application_id):
    with db_session() as session_db:
        user = current_user(session_db)
        app = session_db.get(Application, application_id)
        if not app:
            flash("申請が見つかりません。")
            return redirect(url_for("main.applications"))
        if app.applicant_id != user.id or app.status not in {"returned", "draft"}:
            flash("差し戻しまたは下書き状態の自分の申請のみ編集できます。")
            return redirect(url_for("main.application_detail", application_id=application_id))
        templates = session_db.scalars(
            select(ApplicationTemplate)
            .where(ApplicationTemplate.employee_id == user.id)
            .order_by(ApplicationTemplate.created_at.desc())
        ).all()
        types = session_db.scalars(select(ApplicationType).order_by(ApplicationType.id)).all()
        departments = session_db.scalars(select(Department).order_by(Department.id)).all()
        selected_type_id = request.form.get("application_type_id") or request.args.get("type") or app.application_type_id
        selected_application_type = next((item for item in types if item.id == selected_type_id), None)
        if request.method == "POST":
            try:
                form_action = request.form.get("form_action", "confirm")
                if form_action == "draft":
                    save_draft_application(session_db, user, request.form, app)
                    flash(f"申請 No.{app.id} を下書き保存しました。")
                    return redirect(url_for("main.applications", status="draft"))
                if form_action == "submit":
                    if app.status == "draft":
                        submit_draft_application(session_db, app, user, request.form)
                        flash(f"申請 No.{app.id} を提出しました。")
                    else:
                        update_returned_application(session_db, app, user, request.form)
                        flash(f"申請 No.{app.id} を再申請しました。")
                    return redirect(url_for("main.application_detail", application_id=app.id))
                return render_template(
                    "applications/confirm.html",
                    user=user,
                    app=app,
                    form_values=build_form_snapshot(request.form),
                    confirm_items=confirmation_items(request.form, types, departments),
                    submit_label="この内容で提出する" if app.status == "draft" else "この内容で再申請する",
                    back_url=url_for("main.application_edit", application_id=app.id, type=request.form["application_type_id"]),
                )
            except ValueError as exc:
                flash(str(exc))
                selected_type_id = request.form.get("application_type_id") or selected_type_id
                selected_application_type = next((item for item in types if item.id == selected_type_id), None)
        return render_template(
            "applications/form.html",
            user=user,
            application_types=types,
            departments=departments,
            templates=templates,
            selected_type_id=selected_type_id,
            selected_application_type=selected_application_type,
            app=app,
            detail_values=detail_dict(app),
            form_values=application_to_form_values(app),
            returned_fields=returned_field_keys(app),
            returned_items=returned_field_items(app),
        )


@bp.route("/approvals")
@login_required
def approvals():
    with db_session() as session_db:
        user = current_user(session_db)
        steps = session_db.scalars(
            select(ApprovalStep)
            .where(ApprovalStep.approver_id == user.id, ApprovalStep.status == "waiting")
            .order_by(ApprovalStep.id)
        ).all()
        return render_template("approvals/list.html", user=user, steps=steps)


@bp.route("/notifications")
@login_required
def notifications():
    with db_session() as session_db:
        user = current_user(session_db)
        items = session_db.scalars(
            select(Notification)
            .where(Notification.employee_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(50)
        ).all()
        return render_template("notifications.html", user=user, notifications=items)


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    with db_session() as session_db:
        user = current_user(session_db)
        session_db.query(Notification).filter(
            Notification.employee_id == user.id,
            Notification.is_read.is_(False),
        ).update({"is_read": True})
        flash("通知をすべて既読にしました。")
        return redirect(url_for("main.notifications"))


@bp.route("/approvals/<int:application_id>/act", methods=["POST"])
@login_required
def approval_act(application_id):
    with db_session() as session_db:
        user = current_user(session_db)
        app = session_db.get(Application, application_id)
        if not app:
            flash("申請が見つかりません。")
            return redirect(url_for("main.approvals"))
        try:
            action = request.form["action"]
            comment = request.form.get("comment", "").strip()
            return_fields = request.form.getlist("return_fields")
            if action in {"return", "reject"} and not comment:
                raise ValueError("差し戻し・却下の場合は理由を入力してください。")
            if action == "return" and not return_fields:
                raise ValueError("差し戻しの場合は、不備のある項目を1つ以上選択してください。")
            act_on_application(session_db, app, user, action, comment, return_fields)
            flash("承認操作を保存しました。")
        except ValueError as exc:
            flash(str(exc))
        return redirect(url_for("main.application_detail", application_id=application_id))


@bp.route("/admin")
@admin_required
def admin_index():
    with db_session() as session_db:
        user = current_user(session_db)
        return render_template("admin/index.html", user=user, **admin_master_data(session_db))


@bp.route("/admin/employees/new", methods=["GET", "POST"])
@admin_required
def admin_employee_new():
    with db_session() as session_db:
        user = current_user(session_db)
        data = admin_master_data(session_db)
        if request.method == "POST":
            password = request.form.get("password", "")
            if not 8 <= len(password) <= 128:
                flash("パスワードは8文字以上128文字以内で入力してください。")
                return render_template("admin/employee_form.html", user=user, employee=None, **data)
            employee = Employee(
                id=request.form["id"],
                name=request.form["name"],
                email=request.form["email"],
                password_hash=generate_password_hash(password),
                department_id=request.form["department_id"],
                section_id=request.form["section_id"],
                position_id=request.form["position_id"],
                is_admin=bool_from_form("is_admin"),
                is_active=bool_from_form("is_active"),
            )
            session_db.add(employee)
            try:
                session_db.flush()
                flash("社員を追加しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("社員IDが重複しているか、部・課・役職IDが正しくありません。")
        return render_template("admin/employee_form.html", user=user, employee=None, **data)


@bp.route("/admin/employees/<employee_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_employee_edit(employee_id):
    with db_session() as session_db:
        user = current_user(session_db)
        employee = session_db.get(Employee, employee_id)
        if not employee:
            flash("社員が見つかりません。")
            return redirect(url_for("main.admin_index"))
        data = admin_master_data(session_db)
        if request.method == "POST":
            new_id = request.form["id"]
            try:
                update_primary_id(
                    session_db,
                    "employees",
                    employee_id,
                    new_id,
                    [
                        ("departments", "manager_employee_id"),
                        ("sections", "manager_employee_id"),
                        ("applications", "applicant_id"),
                        ("approval_steps", "approver_id"),
                        ("approval_histories", "actor_id"),
                        ("notifications", "employee_id"),
                    ],
                )
                employee = session_db.get(Employee, new_id)
                employee.name = request.form["name"]
                employee.email = request.form["email"]
                employee.department_id = request.form["department_id"]
                employee.section_id = request.form["section_id"]
                employee.position_id = request.form["position_id"]
                employee.is_admin = bool_from_form("is_admin")
                employee.is_active = bool_from_form("is_active")
                if request.form.get("password"):
                    employee.password_hash = generate_password_hash(request.form["password"])
                if session["employee_id"] == employee_id:
                    session["employee_id"] = new_id
                flash("社員情報を更新しました。")
                return redirect(url_for("main.admin_index"))
            except (IntegrityError, ValueError) as exc:
                session_db.rollback()
                flash(str(exc) or "社員情報を更新できませんでした。")
        return render_template("admin/employee_form.html", user=user, employee=employee, **data)


@bp.route("/admin/employees/<employee_id>/delete", methods=["POST"])
@admin_required
def admin_employee_delete(employee_id):
    if employee_id == session.get("employee_id"):
        flash("ログイン中の自分自身は削除できません。")
        return redirect(url_for("main.admin_index"))
    with db_session() as session_db:
        employee = session_db.get(Employee, employee_id)
        if employee:
            session_db.delete(employee)
            try:
                session_db.flush()
                flash("社員を削除しました。")
            except IntegrityError:
                session_db.rollback()
                flash("申請や承認履歴で使われている社員は削除できません。編集画面で無効化してください。")
    return redirect(url_for("main.admin_index"))


@bp.route("/admin/departments/new", methods=["GET", "POST"])
@admin_required
def admin_department_new():
    with db_session() as session_db:
        user = current_user(session_db)
        data = admin_master_data(session_db)
        if request.method == "POST":
            session_db.add(
                Department(
                    id=request.form["id"],
                    name=request.form["name"],
                    manager_employee_id=request.form.get("manager_employee_id") or None,
                )
            )
            try:
                session_db.flush()
                flash("部を追加しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("部IDが重複しているか、部長社員IDが正しくありません。")
        return render_template("admin/department_form.html", user=user, department=None, **data)


@bp.route("/admin/departments/<department_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_department_edit(department_id):
    with db_session() as session_db:
        user = current_user(session_db)
        department = session_db.get(Department, department_id)
        if not department:
            flash("部が見つかりません。")
            return redirect(url_for("main.admin_index"))
        data = admin_master_data(session_db)
        if request.method == "POST":
            try:
                update_primary_id(session_db, "departments", department_id, request.form["id"], [("employees", "department_id"), ("sections", "department_id")])
                department = session_db.get(Department, request.form["id"])
                department.name = request.form["name"]
                department.manager_employee_id = request.form.get("manager_employee_id") or None
                flash("部を更新しました。")
                return redirect(url_for("main.admin_index"))
            except (IntegrityError, ValueError) as exc:
                session_db.rollback()
                flash(str(exc) or "部を更新できませんでした。")
        return render_template("admin/department_form.html", user=user, department=department, **data)


@bp.route("/admin/departments/<department_id>/delete", methods=["POST"])
@admin_required
def admin_department_delete(department_id):
    with db_session() as session_db:
        item = session_db.get(Department, department_id)
        if item:
            session_db.delete(item)
            try:
                session_db.flush()
                flash("部を削除しました。")
            except IntegrityError:
                session_db.rollback()
                flash("社員または課で使用中の部は削除できません。")
    return redirect(url_for("main.admin_index"))


@bp.route("/admin/sections/new", methods=["GET", "POST"])
@admin_required
def admin_section_new():
    with db_session() as session_db:
        user = current_user(session_db)
        data = admin_master_data(session_db)
        if request.method == "POST":
            session_db.add(
                Section(
                    id=request.form["id"],
                    name=request.form["name"],
                    department_id=request.form["department_id"],
                    manager_employee_id=request.form.get("manager_employee_id") or None,
                )
            )
            try:
                session_db.flush()
                flash("課を追加しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("課IDが重複しているか、部ID・課長社員IDが正しくありません。")
        return render_template("admin/section_form.html", user=user, section=None, **data)


@bp.route("/admin/sections/<section_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_section_edit(section_id):
    with db_session() as session_db:
        user = current_user(session_db)
        section = session_db.get(Section, section_id)
        if not section:
            flash("課が見つかりません。")
            return redirect(url_for("main.admin_index"))
        data = admin_master_data(session_db)
        if request.method == "POST":
            try:
                update_primary_id(session_db, "sections", section_id, request.form["id"], [("employees", "section_id")])
                section = session_db.get(Section, request.form["id"])
                section.name = request.form["name"]
                section.department_id = request.form["department_id"]
                section.manager_employee_id = request.form.get("manager_employee_id") or None
                flash("課を更新しました。")
                return redirect(url_for("main.admin_index"))
            except (IntegrityError, ValueError) as exc:
                session_db.rollback()
                flash(str(exc) or "課を更新できませんでした。")
        return render_template("admin/section_form.html", user=user, section=section, **data)


@bp.route("/admin/sections/<section_id>/delete", methods=["POST"])
@admin_required
def admin_section_delete(section_id):
    with db_session() as session_db:
        item = session_db.get(Section, section_id)
        if item:
            session_db.delete(item)
            try:
                session_db.flush()
                flash("課を削除しました。")
            except IntegrityError:
                session_db.rollback()
                flash("社員で使用中の課は削除できません。")
    return redirect(url_for("main.admin_index"))


@bp.route("/admin/positions/new", methods=["GET", "POST"])
@admin_required
def admin_position_new():
    with db_session() as session_db:
        user = current_user(session_db)
        if request.method == "POST":
            session_db.add(
                Position(
                    id=request.form["id"],
                    name=request.form["name"],
                    approval_level=int(request.form.get("approval_level") or 0),
                    can_approve=bool_from_form("can_approve"),
                )
            )
            try:
                session_db.flush()
                flash("役職を追加しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("役職IDが重複しています。")
        return render_template("admin/position_form.html", user=user, position=None)


@bp.route("/admin/positions/<position_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_position_edit(position_id):
    with db_session() as session_db:
        user = current_user(session_db)
        position = session_db.get(Position, position_id)
        if not position:
            flash("役職が見つかりません。")
            return redirect(url_for("main.admin_index"))
        if request.method == "POST":
            try:
                update_primary_id(
                    session_db,
                    "positions",
                    position_id,
                    request.form["id"],
                    [
                        ("employees", "position_id"),
                        ("application_type_approval_routes", "position_id"),
                    ],
                )
                position = session_db.get(Position, request.form["id"])
                position.name = request.form["name"]
                position.approval_level = int(request.form.get("approval_level") or 0)
                position.can_approve = bool_from_form("can_approve")
                flash("役職を更新しました。")
                return redirect(url_for("main.admin_index"))
            except (IntegrityError, ValueError) as exc:
                session_db.rollback()
                flash(str(exc) or "役職を更新できませんでした。")
        return render_template("admin/position_form.html", user=user, position=position)


@bp.route("/admin/positions/<position_id>/delete", methods=["POST"])
@admin_required
def admin_position_delete(position_id):
    with db_session() as session_db:
        item = session_db.get(Position, position_id)
        if item:
            session_db.delete(item)
            try:
                session_db.flush()
                flash("役職を削除しました。")
            except IntegrityError:
                session_db.rollback()
                flash("社員または承認経路で使用中の役職は削除できません。")
    return redirect(url_for("main.admin_index"))


@bp.route("/admin/application-types/new", methods=["GET", "POST"])
@admin_required
def admin_application_type_new():
    with db_session() as session_db:
        user = current_user(session_db)
        positions = approval_positions(session_db)
        selected_route_position_ids = request.form.getlist("route_position_id") if request.method == "POST" else []
        if request.method == "POST":
            try:
                selected_route_position_ids = normalize_route_position_ids(session_db)
                application_type = ApplicationType(
                    id=request.form["id"],
                    name=request.form["name"],
                    description=request.form["description"],
                    requires_amount=bool_from_form("requires_amount"),
                    requires_target_date=bool_from_form("requires_target_date"),
                )
                session_db.add(application_type)
                session_db.flush()
                replace_application_type_route(session_db, application_type.id, selected_route_position_ids)
                flash("申請種別を追加しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("申請種別IDが重複しているか、設定内容に整合性がありません。")
            except ValueError as exc:
                session_db.rollback()
                flash(str(exc))
        return render_template(
            "admin/application_type_form.html",
            user=user,
            application_type=None,
            positions=positions,
            selected_route_position_ids=selected_route_position_ids,
            form_values=request.form if request.method == "POST" else {},
        )


@bp.route("/admin/application-types/<application_type_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_application_type_edit(application_type_id):
    with db_session() as session_db:
        user = current_user(session_db)
        application_type = session_db.get(ApplicationType, application_type_id)
        if not application_type:
            flash("申請種別が見つかりません。")
            return redirect(url_for("main.admin_index"))
        positions = approval_positions(session_db)
        selected_route_position_ids = (
            request.form.getlist("route_position_id")
            if request.method == "POST"
            else [step.position_id for step in application_type.approval_route_steps]
        )
        if request.method == "POST":
            try:
                selected_route_position_ids = normalize_route_position_ids(session_db)
                update_primary_id(
                    session_db,
                    "application_types",
                    application_type_id,
                    request.form["id"],
                    [
                        ("applications", "application_type_id"),
                        ("application_templates", "application_type_id"),
                        ("application_type_approval_routes", "application_type_id"),
                    ],
                )
                application_type = session_db.get(ApplicationType, request.form["id"])
                application_type.name = request.form["name"]
                application_type.description = request.form["description"]
                application_type.requires_amount = bool_from_form("requires_amount")
                application_type.requires_target_date = bool_from_form("requires_target_date")
                replace_application_type_route(session_db, application_type.id, selected_route_position_ids)
                flash("申請種別を更新しました。")
                return redirect(url_for("main.admin_index"))
            except IntegrityError:
                session_db.rollback()
                flash("申請種別IDが重複しているか、設定内容に整合性がありません。")
            except ValueError as exc:
                session_db.rollback()
                flash(str(exc))
        return render_template(
            "admin/application_type_form.html",
            user=user,
            application_type=application_type,
            positions=positions,
            selected_route_position_ids=selected_route_position_ids,
            form_values=request.form if request.method == "POST" else {},
        )


@bp.route("/admin/application-types/<application_type_id>/delete", methods=["POST"])
@admin_required
def admin_application_type_delete(application_type_id):
    with db_session() as session_db:
        item = session_db.get(ApplicationType, application_type_id)
        if item:
            session_db.delete(item)
            try:
                session_db.flush()
                flash("申請種別を削除しました。")
            except IntegrityError:
                session_db.rollback()
                flash("申請で使用中の申請種別は削除できません。")
    return redirect(url_for("main.admin_index"))

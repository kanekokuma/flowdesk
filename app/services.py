import json
from datetime import datetime

from sqlalchemy import delete, select

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
    Section,
)


STATUS_LABELS = {
    "draft": "下書き",
    "pending": "申請中",
    "returned": "差し戻し",
    "rejected": "却下",
    "approved": "承認完了",
}

STEP_STATUS_LABELS = {
    "waiting": "承認待ち",
    "not_reached": "未到達",
    "approved": "承認済",
    "returned": "差し戻し",
    "rejected": "却下",
}

ACTION_LABELS = {
    "draft": "下書き保存",
    "submit": "申請提出",
    "resubmit": "再申請",
    "approve": "承認",
    "return": "差し戻し",
    "reject": "却下",
}

APPLICATION_DETAIL_FIELDS = {
    "APP_TYPE_001": [
        ("expense_date", "利用日"),
        ("expense_category", "費目"),
        ("payment_method", "支払方法"),
        ("vendor", "支払先"),
        ("receipt_status", "領収書提出状況"),
        ("project_code", "案件・プロジェクトコード"),
        ("tax_category", "税区分"),
        ("cost_burden_department", "費用負担部門"),
    ],
    "APP_TYPE_002": [
        ("item_name", "購入品名"),
        ("quantity", "数量"),
        ("unit_price", "単価"),
        ("vendor", "購入先"),
        ("desired_delivery_date", "希望納期"),
        ("budget_code", "予算コード"),
        ("quote_status", "見積書提出状況"),
        ("selection_reason", "購入先選定理由"),
    ],
    "APP_TYPE_003": [
        ("attendance_type", "勤怠区分"),
        ("start_time", "開始時刻"),
        ("end_time", "終了時刻"),
        ("substitute_date", "振替日"),
        ("work_location", "勤務場所"),
        ("contact_note", "緊急連絡事項"),
    ],
    "APP_TYPE_004": [
        ("proposal_category", "稟議区分"),
        ("proposal_content", "稟議内容"),
        ("background", "背景・課題"),
        ("cost_breakdown", "費用内訳"),
        ("expected_effect", "期待効果"),
        ("risk_note", "リスク・懸念点"),
        ("related_department", "関係部門"),
        ("desired_decision_date", "希望決裁日"),
    ],
    "APP_TYPE_005": [
        ("travel_date", "利用日"),
        ("departure", "出発地"),
        ("arrival", "到着地"),
        ("transportation_type", "交通手段"),
        ("round_trip", "往復区分"),
        ("visited_place", "訪問先"),
        ("business_purpose", "業務目的"),
        ("receipt_status", "領収書提出状況"),
    ],
    "APP_TYPE_006": [
        ("work_date", "在宅勤務日"),
        ("remote_work_type", "在宅勤務区分"),
        ("work_location", "勤務場所"),
        ("start_time", "開始時刻"),
        ("end_time", "終了時刻"),
        ("planned_tasks", "予定業務"),
        ("network_environment", "通信環境"),
        ("emergency_contact", "緊急連絡先"),
    ],
}

APPROVAL_ROUTE_CATALOG = [
    {
        "application_type_id": "APP_TYPE_001",
        "conditions": [
            {"condition": "1万円未満", "steps": ["section_manager", "accounting_manager"]},
            {"condition": "1万円以上10万円未満", "steps": ["section_manager", "department_manager", "accounting_manager"]},
            {"condition": "10万円以上", "steps": ["section_manager", "department_manager", "accounting_manager"]},
        ],
    },
    {
        "application_type_id": "APP_TYPE_002",
        "conditions": [
            {"condition": "10万円未満", "steps": ["section_manager", "department_manager", "accounting_manager"]},
            {"condition": "10万円以上30万円未満", "steps": ["section_manager", "department_manager", "purchasing_manager", "accounting_manager"]},
            {"condition": "30万円以上", "steps": ["section_manager", "department_manager", "purchasing_manager", "executive", "accounting_manager"]},
        ],
    },
    {
        "application_type_id": "APP_TYPE_003",
        "conditions": [
            {"condition": "条件なし", "steps": ["section_manager"]},
        ],
    },
    {
        "application_type_id": "APP_TYPE_004",
        "conditions": [
            {"condition": "条件なし", "steps": ["section_manager", "department_manager", "executive", "accounting_manager"]},
        ],
    },
    {
        "application_type_id": "APP_TYPE_005",
        "conditions": [
            {"condition": "1万円未満", "steps": ["section_manager", "accounting_manager"]},
            {"condition": "1万円以上5万円未満", "steps": ["section_manager", "department_manager", "accounting_manager"]},
            {"condition": "5万円以上", "steps": ["section_manager", "department_manager", "accounting_manager"]},
        ],
    },
    {
        "application_type_id": "APP_TYPE_006",
        "conditions": [
            {"condition": "条件なし", "steps": ["section_manager"]},
        ],
    },
]

APPROVAL_ROUTE_STEP_DEFINITIONS = {
    "section_manager": {
        "label": "課長",
        "scope": "部署別",
        "description": "申請者が所属する課の課長が承認します。",
    },
    "department_manager": {
        "label": "部長",
        "scope": "部署別",
        "description": "申請者が所属する部の部長が承認します。",
    },
    "accounting_manager": {
        "label": "経理責任者",
        "scope": "共通",
        "description": "金額を扱うすべての申請を、最終段階で全社共通の経理責任者が確認します。",
        "position_id": "POS006",
    },
    "purchasing_manager": {
        "label": "購買担当",
        "scope": "共通",
        "description": "一定額以上の購買申請を全社共通の購買担当が確認します。",
        "position_id": "POS007",
    },
    "executive": {
        "label": "役員",
        "scope": "共通",
        "description": "高額または重要な申請を全社共通の役員が最終承認します。",
        "position_id": "POS005",
    },
}


def status_label(status):
    return STATUS_LABELS.get(status, status)


def step_status_label(status):
    return STEP_STATUS_LABELS.get(status, status)


def action_label(action):
    return ACTION_LABELS.get(action, action)


def detail_fields(application_type_id):
    return APPLICATION_DETAIL_FIELDS.get(application_type_id, [])


def application_type_name(application_types, application_type_id):
    match = next((item for item in application_types if item.id == application_type_id), None)
    return match.name if match else application_type_id


def approval_route_catalog(application_types):
    type_names = {application_type.id: application_type.name for application_type in application_types}
    catalog = []
    custom_type_ids = {
        application_type.id
        for application_type in application_types
        if application_type.approval_route_steps
    }
    for application_type in application_types:
        if application_type.id not in custom_type_ids:
            continue
        steps = []
        for route_step in application_type.approval_route_steps:
            is_local = route_step.position_id in {"POS003", "POS004"}
            steps.append(
                {
                    "label": route_step.position.name,
                    "scope": "部署別" if is_local else "共通",
                    "description": (
                        "申請者の所属組織に設定された承認者が承認します。"
                        if is_local
                        else "該当役職の有効な社員が承認します。"
                    ),
                    "position_id": route_step.position_id,
                }
            )
        catalog.append(
            {
                "application_type_id": application_type.id,
                "application_type_name": application_type.name,
                "conditions": [{"condition": "設定済み経路", "steps": steps}],
            }
        )

    for item in APPROVAL_ROUTE_CATALOG:
        application_type_id = item["application_type_id"]
        if application_type_id not in type_names or application_type_id in custom_type_ids:
            continue
        conditions = []
        for condition in item["conditions"]:
            steps = [APPROVAL_ROUTE_STEP_DEFINITIONS[step_key] for step_key in condition["steps"]]
            conditions.append({"condition": condition["condition"], "steps": steps})
        catalog.append(
            {
                "application_type_id": application_type_id,
                "application_type_name": type_names[application_type_id],
                "conditions": conditions,
            }
        )
    return sorted(catalog, key=lambda item: item["application_type_id"])


def detail_label(application_type_id, key):
    return dict(detail_fields(application_type_id)).get(key, key)


def detail_items(application):
    details = detail_dict(application)
    labels = dict(detail_fields(application.application_type_id))
    return [(labels.get(key, key), value) for key, value in details.items() if value]


def review_fields(application):
    fields = [("title", "件名")]
    if application.amount is not None:
        fields.append(("amount", "金額"))
    if application.target_date:
        fields.append(("target_date", "対象日"))
    fields.extend(detail_fields(application.application_type_id))
    fields.append(("reason", "理由・補足"))
    return fields


def returned_field_keys(application):
    try:
        values = json.loads(application.returned_fields_json or "[]")
    except json.JSONDecodeError:
        return set()
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values}


def returned_field_items(application):
    keys = returned_field_keys(application)
    return [(key, label) for key, label in review_fields(application) if key in keys]


def detail_dict(application):
    try:
        return json.loads(application.detail_json or "{}")
    except json.JSONDecodeError:
        return {}


def build_detail_json(form):
    application_type_id = form["application_type_id"]
    details = {}
    for key, _label in detail_fields(application_type_id):
        value = form.get(key)
        if value:
            details[key] = value
    return json.dumps(details, ensure_ascii=False)


def build_form_snapshot(form):
    keys = ["application_type_id", "title", "amount", "target_date", "reason"]
    for key, _label in detail_fields(form["application_type_id"]):
        keys.append(key)
    return {key: form.get(key, "") for key in keys}


def application_to_form_values(application):
    values = {
        "application_type_id": application.application_type_id,
        "title": application.title,
        "amount": str(int(application.amount)) if application.amount is not None else "",
        "target_date": application.target_date.isoformat() if application.target_date else "",
        "reason": application.reason,
    }
    values.update(detail_dict(application))
    return values


def template_to_form_values(template):
    try:
        values = json.loads(template.form_json or "{}")
    except json.JSONDecodeError:
        values = {}
    if not isinstance(values, dict):
        values = {}
    values.setdefault("application_type_id", template.application_type_id)
    return values


def department_lookup(departments):
    return {department.id: department.name for department in departments}


def display_detail_value(application_type_id, key, value, departments=None):
    if key in {"cost_burden_department", "related_department"} and departments:
        return department_lookup(departments).get(value, value)
    return value


def confirmation_items(form, application_types, departments=None):
    application_type_id = form["application_type_id"]
    items = [
        ("申請種別", application_type_name(application_types, application_type_id)),
        ("件名", form.get("title") or "-"),
    ]
    if form.get("amount"):
        items.append(("金額", f"{int(form.get('amount')):,}円"))
    if form.get("target_date"):
        items.append(("対象日", form.get("target_date")))
    for key, label in detail_fields(application_type_id):
        value = form.get(key)
        if value:
            items.append((label, display_detail_value(application_type_id, key, value, departments)))
    items.append(("理由・補足", form.get("reason") or "-"))
    return items


def validate_application_form(form, application_type=None):
    application_type_id = form["application_type_id"]
    amount = form.get("amount")
    target_date = form.get("target_date")

    requires_amount = (
        application_type.requires_amount
        if application_type is not None
        else application_type_id in {"APP_TYPE_001", "APP_TYPE_002", "APP_TYPE_004", "APP_TYPE_005"}
    )
    requires_target_date = (
        application_type.requires_target_date
        if application_type is not None
        else application_type_id in {"APP_TYPE_003", "APP_TYPE_006"}
    )

    if requires_amount and not amount:
        raise ValueError("この申請種別では金額を入力してください。")
    if requires_target_date and not target_date:
        raise ValueError("この申請種別では対象日を入力してください。")

    required_by_type = {
        "APP_TYPE_001": ["expense_date", "expense_category", "payment_method", "cost_burden_department"],
        "APP_TYPE_002": ["item_name", "quantity", "unit_price", "desired_delivery_date", "quote_status"],
        "APP_TYPE_003": ["attendance_type"],
        "APP_TYPE_004": ["proposal_category", "proposal_content", "background", "expected_effect", "desired_decision_date"],
        "APP_TYPE_005": ["travel_date", "departure", "arrival", "transportation_type", "business_purpose"],
        "APP_TYPE_006": ["work_date", "remote_work_type", "work_location", "start_time", "end_time", "planned_tasks", "network_environment"],
    }
    labels = dict(detail_fields(application_type_id))
    for key in required_by_type.get(application_type_id, []):
        if not form.get(key):
            raise ValueError(f"{labels.get(key, key)}を入力してください。")


def create_notification(session, employee_id, application_id, message):
    session.add(
        Notification(
            employee_id=employee_id,
            application_id=application_id,
            message=message,
        )
    )


def approval_progress(application):
    steps = application.approval_steps
    total = len(steps)
    approved = len([step for step in steps if step.status == "approved"])
    if total == 0:
        return {"approved": 0, "total": 0, "percent": 0}
    return {
        "approved": approved,
        "total": total,
        "percent": round((approved / total) * 100),
    }


def current_approval_label(application):
    if application.status == "approved":
        return "承認完了"
    if application.status == "returned":
        return "申請者修正待ち"
    if application.status == "rejected":
        return "却下"
    current_step = next((step for step in application.approval_steps if step.status == "waiting"), None)
    if not current_step:
        return "-"
    return f"{current_step.role_label}: {current_step.approver.name}"


def resolve_approval_plan(session, applicant, application_type_id, amount):
    section = session.get(Section, applicant.section_id)
    department = session.get(Department, applicant.department_id)
    if not section or not section.manager_employee_id:
        raise ValueError("申請者の課長が設定されていません。")
    if not department or not department.manager_employee_id:
        raise ValueError("申請者の部長が設定されていません。")

    plan = []

    def add_step(role_label, approver_id):
        if approver_id == applicant.id:
            return
        if plan and plan[-1]["approver_id"] == approver_id:
            return
        plan.append({"role_label": role_label, "approver_id": approver_id})

    custom_route = session.scalars(
        select(ApplicationTypeApprovalRoute)
        .where(ApplicationTypeApprovalRoute.application_type_id == application_type_id)
        .order_by(ApplicationTypeApprovalRoute.step_no)
    ).all()

    if custom_route:
        for route_step in custom_route:
            if route_step.position_id == "POS003":
                add_step(route_step.position.name, section.manager_employee_id)
            elif route_step.position_id == "POS004":
                add_step(route_step.position.name, department.manager_employee_id)
            else:
                approver = find_employee_by_position(
                    session,
                    route_step.position_id,
                    excluded_employee_id=applicant.id,
                )
                add_step(route_step.position.name, approver.id)
    else:
        add_step("課長", section.manager_employee_id)

        amount_value = int(amount or 0)
        if application_type_id == "APP_TYPE_001":
            if amount_value >= 10000:
                add_step("部長", department.manager_employee_id)
        elif application_type_id == "APP_TYPE_002":
            add_step("部長", department.manager_employee_id)
            if amount_value >= 100000:
                purchasing_manager = find_employee_by_position(session, "POS007")
                add_step("購買担当", purchasing_manager.id)
            if amount_value >= 300000:
                executive = find_employee_by_position(session, "POS005")
                add_step("役員", executive.id)
        elif application_type_id == "APP_TYPE_003":
            pass
        elif application_type_id == "APP_TYPE_004":
            add_step("部長", department.manager_employee_id)
            executive = find_employee_by_position(session, "POS005")
            add_step("役員", executive.id)
        elif application_type_id == "APP_TYPE_005":
            if amount_value >= 10000:
                add_step("部長", department.manager_employee_id)
        elif application_type_id == "APP_TYPE_006":
            pass

    application_type = session.get(ApplicationType, application_type_id)
    if application_type and application_type.requires_amount:
        accounting_manager = find_employee_by_position(
            session,
            "POS006",
            excluded_employee_id=applicant.id,
        )
        plan[:] = [
            step
            for step in plan
            if step["approver_id"] != accounting_manager.id
        ]
        add_step("経理責任者", accounting_manager.id)

    if not plan:
        add_step("部長", department.manager_employee_id)
    return plan


def find_employee_by_position(session, position_id, excluded_employee_id=None):
    statement = select(Employee).where(
        Employee.position_id == position_id,
        Employee.is_active.is_(True),
    )
    if excluded_employee_id:
        statement = statement.where(Employee.id != excluded_employee_id)
    employee = session.scalar(
        statement.order_by(Employee.is_admin, Employee.id)
    )
    if not employee:
        raise ValueError(f"役職ID {position_id} の承認者が設定されていません。")
    return employee


def create_application(session, applicant, form):
    application_type = session.get(ApplicationType, form["application_type_id"])
    if not application_type:
        raise ValueError("申請種別が見つかりません。")
    validate_application_form(form, application_type)
    amount_raw = form.get("amount") or None
    amount = int(amount_raw) if amount_raw else None
    target_date = form.get("target_date") or None
    app = Application(
        application_type_id=form["application_type_id"],
        applicant_id=applicant.id,
        title=form["title"],
        amount=amount,
        target_date=target_date,
        detail_json=build_detail_json(form),
        reason=form["reason"],
        returned_fields_json=None,
        status="pending",
        current_step_no=1,
    )
    session.add(app)
    session.flush()

    plan = resolve_approval_plan(session, applicant, app.application_type_id, amount)
    for index, step in enumerate(plan, start=1):
        session.add(
            ApprovalStep(
                application_id=app.id,
                step_no=index,
                approver_id=step["approver_id"],
                role_label=step["role_label"],
                status="waiting" if index == 1 else "not_reached",
            )
        )

    session.add(
        ApprovalHistory(
            application_id=app.id,
            actor_id=applicant.id,
            action="submit",
            comment="申請を提出しました。",
        )
    )
    create_notification(session, plan[0]["approver_id"], app.id, f"承認依頼: {app.title}")
    return app


def save_draft_application(session, applicant, form, application=None):
    application_type_id = form.get("application_type_id")
    if not application_type_id:
        raise ValueError("申請種別を選択してください。")
    amount_raw = form.get("amount") or None
    amount = int(amount_raw) if amount_raw else None
    target_date = form.get("target_date") or None

    if application is None:
        application = Application(
            applicant_id=applicant.id,
            status="draft",
            current_step_no=None,
        )
        session.add(application)

    application.application_type_id = application_type_id
    application.title = form.get("title") or "下書き"
    application.amount = amount
    application.target_date = target_date
    application.detail_json = build_detail_json(form)
    application.reason = form.get("reason") or ""
    application.returned_fields_json = None
    application.status = "draft"
    application.current_step_no = None
    return application


def submit_draft_application(session, application, applicant, form):
    if application.applicant_id != applicant.id:
        raise ValueError("この下書きを提出する権限がありません。")
    if application.status != "draft":
        raise ValueError("下書きのみ提出できます。")

    application_type = session.get(ApplicationType, form["application_type_id"])
    if not application_type:
        raise ValueError("申請種別が見つかりません。")
    validate_application_form(form, application_type)
    amount_raw = form.get("amount") or None
    amount = int(amount_raw) if amount_raw else None
    target_date = form.get("target_date") or None

    application.application_type_id = form["application_type_id"]
    application.title = form["title"]
    application.amount = amount
    application.target_date = target_date
    application.detail_json = build_detail_json(form)
    application.reason = form["reason"]
    application.status = "pending"
    application.current_step_no = 1

    plan = resolve_approval_plan(session, applicant, application.application_type_id, amount)
    for index, step in enumerate(plan, start=1):
        session.add(
            ApprovalStep(
                application_id=application.id,
                step_no=index,
                approver_id=step["approver_id"],
                role_label=step["role_label"],
                status="waiting" if index == 1 else "not_reached",
            )
        )

    session.add(
        ApprovalHistory(
            application_id=application.id,
            actor_id=applicant.id,
            action="submit",
            comment="下書きから申請を提出しました。",
        )
    )
    create_notification(session, plan[0]["approver_id"], application.id, f"承認依頼: {application.title}")
    return application


def create_template_from_application(session, employee, application, name):
    if application.applicant_id != employee.id:
        raise ValueError("自分の申請のみテンプレート化できます。")
    template = ApplicationTemplate(
        employee_id=employee.id,
        name=name or f"{application.title}のテンプレート",
        application_type_id=application.application_type_id,
        form_json=json.dumps(application_to_form_values(application), ensure_ascii=False),
    )
    session.add(template)
    return template


def update_returned_application(session, application, applicant, form):
    if application.applicant_id != applicant.id:
        raise ValueError("この申請を編集する権限がありません。")
    if application.status != "returned":
        raise ValueError("差し戻し状態の申請のみ再申請できます。")

    application_type = session.get(ApplicationType, form["application_type_id"])
    if not application_type:
        raise ValueError("申請種別が見つかりません。")
    validate_application_form(form, application_type)
    amount_raw = form.get("amount") or None
    amount = int(amount_raw) if amount_raw else None
    target_date = form.get("target_date") or None

    application.application_type_id = form["application_type_id"]
    application.title = form["title"]
    application.amount = amount
    application.target_date = target_date
    application.detail_json = build_detail_json(form)
    application.reason = form["reason"]
    application.returned_fields_json = None
    application.status = "pending"
    application.current_step_no = 1

    session.execute(delete(ApprovalStep).where(ApprovalStep.application_id == application.id))
    session.flush()

    plan = resolve_approval_plan(session, applicant, application.application_type_id, amount)
    for index, step in enumerate(plan, start=1):
        session.add(
            ApprovalStep(
                application_id=application.id,
                step_no=index,
                approver_id=step["approver_id"],
                role_label=step["role_label"],
                status="waiting" if index == 1 else "not_reached",
            )
        )

    session.add(
        ApprovalHistory(
            application_id=application.id,
            actor_id=applicant.id,
            action="resubmit",
            comment="差し戻し内容を修正して再申請しました。",
        )
    )
    create_notification(session, plan[0]["approver_id"], application.id, f"再申請の承認依頼: {application.title}")
    return application


def act_on_application(session, application, actor, action, comment, returned_fields=None):
    current_step = next(
        (
            step
            for step in application.approval_steps
            if step.step_no == application.current_step_no and step.status == "waiting"
        ),
        None,
    )
    if not current_step:
        raise ValueError("現在承認待ちのステップがありません。")
    if current_step.approver_id != actor.id:
        raise ValueError("この申請を承認する権限がありません。")

    current_step.acted_at = datetime.now()
    current_step.comment = comment

    if action == "approve":
        application.returned_fields_json = None
        current_step.status = "approved"
        next_step = next(
            (step for step in application.approval_steps if step.step_no == current_step.step_no + 1),
            None,
        )
        if next_step:
            next_step.status = "waiting"
            application.current_step_no = next_step.step_no
            create_notification(session, next_step.approver_id, application.id, f"承認依頼: {application.title}")
        else:
            application.status = "approved"
            application.current_step_no = None
            create_notification(session, application.applicant_id, application.id, f"承認完了: {application.title}")
    elif action == "return":
        current_step.status = "returned"
        application.returned_fields_json = json.dumps(returned_fields or [], ensure_ascii=False)
        application.status = "returned"
        application.current_step_no = None
        create_notification(session, application.applicant_id, application.id, f"差し戻し: {application.title}")
    elif action == "reject":
        current_step.status = "rejected"
        application.returned_fields_json = None
        application.status = "rejected"
        application.current_step_no = None
        create_notification(session, application.applicant_id, application.id, f"却下: {application.title}")
    else:
        raise ValueError("不明な操作です。")

    session.add(
        ApprovalHistory(
            application_id=application.id,
            step_no=current_step.step_no,
            actor_id=actor.id,
            action=action,
            comment=comment,
        )
    )

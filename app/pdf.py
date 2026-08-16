from io import BytesIO
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .services import action_label, detail_dict, detail_items, status_label, step_status_label


PDF_FONT = "HeiseiKakuGo-W5"
PDF_FONT_BOLD = "HeiseiKakuGo-W5"


def _register_fonts():
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT))


def _styles():
    _register_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "JapaneseTitle",
            parent=base["Title"],
            fontName=PDF_FONT_BOLD,
            fontSize=17,
            leading=22,
            alignment=TA_CENTER,
            spaceAfter=4 * mm,
        ),
        "heading": ParagraphStyle(
            "JapaneseHeading",
            parent=base["Heading2"],
            fontName=PDF_FONT_BOLD,
            fontSize=12,
            leading=16,
            spaceBefore=5 * mm,
            spaceAfter=2 * mm,
        ),
        "body": ParagraphStyle(
            "JapaneseBody",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=9,
            leading=13,
        ),
        "small": ParagraphStyle(
            "JapaneseSmall",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#64748b"),
        ),
        "right": ParagraphStyle(
            "JapaneseRight",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8.5,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "note": ParagraphStyle(
            "JapaneseNote",
            parent=base["BodyText"],
            fontName=PDF_FONT,
            fontSize=8,
            leading=12,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#334155"),
        ),
    }


def _paragraph(value, style):
    text = "-" if value is None or value == "" else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _table(rows, widths, body_style, header=False):
    data = [[_paragraph(cell, body_style) for cell in row] for row in rows]
    table = Table(data, colWidths=widths, hAlign="LEFT")
    style = [
        ("FONTNAME", (0, 0), (-1, -1), PDF_FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dbe3ea")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                ("FONTNAME", (0, 0), (-1, 0), PDF_FONT_BOLD),
            ]
        )
    table.setStyle(TableStyle(style))
    return table


def _section(title, content):
    return KeepTogether([Paragraph(title, _styles()["heading"]), content])


def _date(value):
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _datetime(value):
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _money(value):
    return f"{int(value):,}円" if value is not None else "-"


def _detail(application, key, default="-"):
    return detail_dict(application).get(key) or default


def _business_form_title(application):
    titles = {
        "APP_TYPE_001": "経費精算申請書",
        "APP_TYPE_002": "購買申請書",
        "APP_TYPE_003": "勤怠申請書",
        "APP_TYPE_004": "稟議書",
        "APP_TYPE_005": "交通費精算申請書",
        "APP_TYPE_006": "在宅勤務申請書",
    }
    return titles.get(application.application_type_id, f"{application.application_type.name}申請書")


def _header_block(application, styles):
    applicant = application.applicant
    return _table(
        [
            ["申請番号", f"#{application.id}", "申請日", _datetime(application.created_at)],
            ["申請者", applicant.name, "社員ID", applicant.id],
            ["所属", f"{applicant.department.name} / {applicant.section.name}", "役職", applicant.position.name],
            ["状態", status_label(application.status), "現在の処理", _current_process(application)],
        ],
        [25 * mm, 60 * mm, 25 * mm, 60 * mm],
        styles["body"],
    )


def _approval_stamp_table(application, styles):
    steps = application.approval_steps[:4]
    if not steps:
        return _table([["承認欄", "-"]], [28 * mm, 142 * mm], styles["body"])

    header = [step.role_label for step in steps]
    names = [step.approver.name for step in steps]
    statuses = [
        f"{step_status_label(step.status)}\n{_datetime(step.acted_at) if step.acted_at else ''}".strip()
        for step in steps
    ]
    width = 170 * mm / len(steps)
    return _table([header, names, statuses], [width] * len(steps), styles["body"], header=True)


def _summary_table(application, styles):
    return _table(
        [
            ["件名", application.title],
            ["申請種別", application.application_type.name],
            ["金額", _money(application.amount)],
            ["対象日", _date(application.target_date)],
        ],
        [30 * mm, 140 * mm],
        styles["body"],
    )


def _body_table(rows, styles, first_width=38):
    return _table(rows, [first_width * mm, (170 - first_width) * mm], styles["body"])


def _type_specific_sections(application, styles):
    type_id = application.application_type_id
    if type_id == "APP_TYPE_001":
        return [
            ("精算内容", _body_table(
                [
                    ["利用日", _detail(application, "expense_date")],
                    ["費目", _detail(application, "expense_category")],
                    ["支払方法", _detail(application, "payment_method")],
                    ["支払先", _detail(application, "vendor")],
                    ["金額", _money(application.amount)],
                    ["税区分", _detail(application, "tax_category")],
                    ["費用負担部門", _detail(application, "cost_burden_department")],
                    ["案件・プロジェクトコード", _detail(application, "project_code")],
                    ["領収書提出状況", _detail(application, "receipt_status")],
                ],
                styles,
                first_width=46,
            )),
            ("申請理由", _body_table([["理由・補足", application.reason]], styles)),
        ]
    if type_id == "APP_TYPE_002":
        quantity = _detail(application, "quantity")
        unit_price = _detail(application, "unit_price")
        return [
            ("購入内容", _body_table(
                [
                    ["購入品名", _detail(application, "item_name")],
                    ["数量", quantity],
                    ["単価", f"{int(unit_price):,}円" if str(unit_price).isdigit() else unit_price],
                    ["申請金額", _money(application.amount)],
                    ["購入先", _detail(application, "vendor")],
                    ["希望納期", _detail(application, "desired_delivery_date")],
                    ["予算コード", _detail(application, "budget_code")],
                    ["見積書提出状況", _detail(application, "quote_status")],
                ],
                styles,
            )),
            ("購入先選定理由・補足", _body_table(
                [
                    ["選定理由", _detail(application, "selection_reason")],
                    ["理由・補足", application.reason],
                ],
                styles,
            )),
        ]
    if type_id == "APP_TYPE_003":
        return [
            ("勤怠内容", _body_table(
                [
                    ["対象日", _date(application.target_date)],
                    ["勤怠区分", _detail(application, "attendance_type")],
                    ["開始時刻", _detail(application, "start_time")],
                    ["終了時刻", _detail(application, "end_time")],
                    ["振替日", _detail(application, "substitute_date")],
                    ["勤務場所", _detail(application, "work_location")],
                    ["緊急連絡事項", _detail(application, "contact_note")],
                ],
                styles,
            )),
            ("申請理由", _body_table([["理由・補足", application.reason]], styles)),
        ]
    if type_id == "APP_TYPE_004":
        return [
            ("起案概要", _body_table(
                [
                    ["稟議区分", _detail(application, "proposal_category")],
                    ["件名", application.title],
                    ["申請金額", _money(application.amount)],
                    ["関係部門", _detail(application, "related_department")],
                    ["希望決裁日", _detail(application, "desired_decision_date")],
                ],
                styles,
            )),
            ("起案内容", _body_table(
                [
                    ["稟議内容", _detail(application, "proposal_content")],
                    ["背景・課題", _detail(application, "background")],
                    ["費用内訳", _detail(application, "cost_breakdown")],
                    ["期待効果", _detail(application, "expected_effect")],
                    ["リスク・懸念点", _detail(application, "risk_note")],
                    ["理由・補足", application.reason],
                ],
                styles,
            )),
        ]
    if type_id == "APP_TYPE_005":
        route = f"{_detail(application, 'departure')} → {_detail(application, 'arrival')}（{_detail(application, 'round_trip')}）"
        return [
            ("交通費明細", _table(
                [
                    ["利用日", "経路", "交通手段", "訪問先・用務", "金額"],
                    [
                        _detail(application, "travel_date"),
                        route,
                        _detail(application, "transportation_type"),
                        f"{_detail(application, 'visited_place')}\n{_detail(application, 'business_purpose')}",
                        _money(application.amount),
                    ],
                ],
                [24 * mm, 46 * mm, 26 * mm, 46 * mm, 28 * mm],
                styles["body"],
                header=True,
            )),
            ("証憑・補足", _body_table(
                [
                    ["領収書提出状況", _detail(application, "receipt_status")],
                    ["理由・補足", application.reason],
                ],
                styles,
            )),
        ]
    if type_id == "APP_TYPE_006":
        return [
            ("在宅勤務内容", _body_table(
                [
                    ["在宅勤務日", _detail(application, "work_date")],
                    ["勤務区分", _detail(application, "remote_work_type")],
                    ["勤務場所", _detail(application, "work_location")],
                    ["勤務時間", f"{_detail(application, 'start_time')} ～ {_detail(application, 'end_time')}"],
                    ["通信環境", _detail(application, "network_environment")],
                    ["緊急連絡先", _detail(application, "emergency_contact")],
                ],
                styles,
            )),
            ("予定業務・理由", _body_table(
                [
                    ["予定業務", _detail(application, "planned_tasks")],
                    ["理由・補足", application.reason],
                ],
                styles,
            )),
        ]
    detail_rows = detail_items(application)
    return [(f"{application.application_type.name}の詳細項目", _body_table(detail_rows, styles))] if detail_rows else []


def build_application_pdf(application):
    styles = _styles()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"申請書_{application.id}",
    )
    story = [
        Paragraph(_business_form_title(application), styles["title"]),
        _header_block(application, styles),
        Spacer(1, 4 * mm),
        Paragraph("承認欄", styles["heading"]),
        _approval_stamp_table(application, styles),
        Spacer(1, 3 * mm),
        Paragraph("申請概要", styles["heading"]),
        _summary_table(application, styles),
    ]

    for title, table in _type_specific_sections(application, styles):
        story.append(Paragraph(title, styles["heading"]))
        story.append(table)

    if application.approval_steps:
        story.append(Paragraph("承認フロー", styles["heading"]))
        rows = [["順番", "役割", "承認者", "状態", "コメント"]]
        for step in application.approval_steps:
            rows.append(
                [
                    step.step_no,
                    step.role_label,
                    step.approver.name,
                    step_status_label(step.status),
                    step.comment or "",
                ]
            )
        story.append(_table(rows, [14 * mm, 26 * mm, 34 * mm, 26 * mm, 70 * mm], styles["body"], header=True))

    if application.histories:
        story.append(Paragraph("承認履歴", styles["heading"]))
        rows = [["日時", "操作者", "操作", "コメント"]]
        for history in application.histories:
            rows.append(
                [
                    history.created_at.strftime("%Y-%m-%d %H:%M"),
                    history.actor.name,
                    action_label(history.action),
                    history.comment or "",
                ]
            )
        story.append(_table(rows, [38 * mm, 34 * mm, 28 * mm, 70 * mm], styles["body"], header=True))

    story.append(Spacer(1, 5 * mm))
    story.append(
        _paragraph(
            "備考: 領収書・見積書などの原本提出が必要な申請は、社内ルールに従って別途提出してください。出力元: 電子申請ワークフロー",
            styles["small"],
        )
    )

    document.build(story)
    buffer.seek(0)
    return buffer


def _current_process(application):
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

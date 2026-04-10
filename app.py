import base64
import smtplib
from datetime import date
from email.message import EmailMessage
from io import BytesIO

import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from supabase import Client, create_client

st.set_page_config(page_title="Cash Advance Application", page_icon="💼", layout="wide")

# ============================================================
# Config
# ============================================================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
ALLOWED_GOOGLE_DOMAIN = st.secrets.get("ALLOWED_GOOGLE_DOMAIN", "").strip().lower()
AUTO_CREATE_UNKNOWN_USERS = str(st.secrets.get("AUTO_CREATE_UNKNOWN_USERS", "true")).lower() == "true"

SMTP_ENABLED = str(st.secrets.get("SMTP_ENABLED", "false")).lower() == "true"
SMTP_HOST = st.secrets.get("SMTP_HOST", "")
SMTP_PORT = int(st.secrets.get("SMTP_PORT", 587))
SMTP_USERNAME = st.secrets.get("SMTP_USERNAME", "")
SMTP_PASSWORD = st.secrets.get("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = st.secrets.get("SMTP_FROM_EMAIL", "")
SMTP_USE_TLS = str(st.secrets.get("SMTP_USE_TLS", "true")).lower() == "true"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

ROLE_USER = "user"
ROLE_APPROVER1 = "approver1_user"
ROLE_APPROVER2 = "approver2_admin"
ALL_ROLES = [ROLE_USER, ROLE_APPROVER1, ROLE_APPROVER2]


# ============================================================
# Utility
# ============================================================
def current_email() -> str:
    return (st.user.get("email") or "").strip().lower()


def current_name() -> str:
    return (st.user.get("name") or st.user.get("email") or "").strip()


def allowed_domain(email: str) -> bool:
    if not ALLOWED_GOOGLE_DOMAIN:
        return True
    if "@" not in email:
        return False
    return email.split("@", 1)[1].lower() == ALLOWED_GOOGLE_DOMAIN


def role_of(profile: dict) -> str:
    return (profile.get("role") or ROLE_USER).lower()


def money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def api_error_block(title: str, err: Exception):
    st.error(title)
    st.code(str(err))
    st.stop()


def flash_success(msg: str):
    st.session_state["_flash_success"] = msg


def show_flash():
    msg = st.session_state.pop("_flash_success", None)
    if msg:
        st.success(msg)


# ============================================================
# Data access
# ============================================================
def get_profile_by_email(email: str) -> dict | None:
    try:
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        api_error_block("Profile lookup failed.", e)


def get_profile_by_id(profile_id: str) -> dict | None:
    try:
        res = (
            supabase.table("profiles")
            .select("*")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        api_error_block("Profile lookup failed.", e)


def list_profiles(active_only: bool = False) -> list[dict]:
    try:
        query = supabase.table("profiles").select("*").order("created_at")
        if active_only:
            query = query.eq("is_active", True)
        res = query.execute()
        return res.data or []
    except Exception as e:
        api_error_block("Could not load profiles.", e)


def create_profile(payload: dict) -> dict | None:
    try:
        res = supabase.table("profiles").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        api_error_block("Profile creation failed.", e)


def update_profile(profile_id: str, payload: dict):
    try:
        supabase.table("profiles").update(payload).eq("id", profile_id).execute()
    except Exception as e:
        api_error_block("Profile update failed.", e)


def delete_profile(profile_id: str):
    try:
        supabase.table("profiles").delete().eq("id", profile_id).execute()
    except Exception as e:
        api_error_block("Profile delete failed.", e)


def ensure_profile() -> dict:
    email = current_email()
    name = current_name()

    if not email:
        st.error("Google account email was not returned.")
        st.stop()

    if not allowed_domain(email):
        st.error(f"This app only allows @{ALLOWED_GOOGLE_DOMAIN} accounts.")
        st.button("Log out", on_click=st.logout, use_container_width=True)
        st.stop()

    existing = get_profile_by_email(email)
    if existing:
        return existing

    if not AUTO_CREATE_UNKNOWN_USERS:
        st.error("Your account is not registered yet. Please contact the administrator.")
        st.button("Log out", on_click=st.logout, use_container_width=True)
        st.stop()

    payload = {
        "email": email,
        "full_name": name,
        "department": "",
        "office": "",
        "role": ROLE_USER,
        "is_active": True,
    }
    created = create_profile(payload)
    if created:
        return created

    existing = get_profile_by_email(email)
    if existing:
        return existing

    st.error("Profile could not be created.")
    st.stop()


def list_requests_for_employee(email: str) -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("employee_email", email)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load your requests.", e)


def list_requests_for_approver1(email: str) -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("approver1_email", email)
            .eq("status", "submitted")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load approver1 queue.", e)


def list_requests_for_approver2(email: str) -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("approver2_email", email)
            .eq("status", "approver1_approved")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load approver2 queue.", e)


def list_all_requests() -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load all requests.", e)


def get_request_by_id(request_id: str) -> dict | None:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("id", request_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        api_error_block("Could not load request.", e)


def create_request(payload: dict) -> dict | None:
    try:
        res = supabase.table("cash_advance_requests").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        api_error_block("Request submission failed.", e)


def update_request(request_id: str, payload: dict):
    try:
        supabase.table("cash_advance_requests").update(payload).eq("id", request_id).execute()
    except Exception as e:
        api_error_block("Request update failed.", e)


def create_inbox_message(payload: dict):
    try:
        supabase.table("inbox_messages").insert(payload).execute()
    except Exception as e:
        api_error_block("Inbox message creation failed.", e)


def list_inbox_messages(email: str) -> list[dict]:
    try:
        res = (
            supabase.table("inbox_messages")
            .select("*")
            .eq("recipient_email", email)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load inbox.", e)


def update_inbox_message(message_id: str, payload: dict):
    try:
        supabase.table("inbox_messages").update(payload).eq("id", message_id).execute()
    except Exception as e:
        api_error_block("Inbox update failed.", e)


def delete_inbox_message(message_id: str):
    try:
        supabase.table("inbox_messages").delete().eq("id", message_id).execute()
    except Exception as e:
        api_error_block("Inbox delete failed.", e)


# ============================================================
# PDF and email
# ============================================================
def build_request_pdf(request_row: dict) -> bytes:
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    except Exception:
        pass

    font_name = "HeiseiKakuGo-W5"

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    left = 18 * mm
    y = height - 18 * mm
    line_gap = 7 * mm

    def line(label: str, value: str):
        nonlocal y
        c.setFont(font_name, 10)
        c.drawString(left, y, label)
        c.drawString(left + 56 * mm, y, value or "")
        y -= line_gap

    c.setTitle(f"Cash Advance - {request_row.get('employee_name', '')}")
    c.setFont(font_name, 16)
    c.drawString(left, y, "Cash Advance Application / C/A申請書")
    y -= 12 * mm

    line("Request ID", str(request_row.get("id", "")))
    line("Name / 名前", str(request_row.get("employee_name", "")))
    line("Department / 所属", str(request_row.get("department", "")))
    line("Office / オフィス", str(request_row.get("office", "")))
    line("Amount / 金額", money(request_row.get("amount", 0)))
    line("Purpose / 目的", str(request_row.get("purpose", "")))
    line("Liquidation Due Date / 清算予定日", str(request_row.get("liquidation_due_date", "")))
    line("Status / ステータス", str(request_row.get("status", "")))
    line("Approver 1", str(request_row.get("approver1_name", "")))
    line("Approver 2", str(request_row.get("approver2_name", "")))
    line("Employee Sign / 本人サイン", str(request_row.get("employee_signed_name", "")))
    line("Approver 1 Sign", str(request_row.get("approver1_signed_name", "")))
    line("Approver 2 Sign", str(request_row.get("approver2_signed_name", "")))

    y -= 4 * mm
    c.setFont(font_name, 11)
    c.drawString(left, y, "Undertaking / 誓約")
    y -= 6 * mm

    text = c.beginText(left, y)
    text.setFont(font_name, 9)
    undertaking = (
        "I agree that if I fail to liquidate or return the amount by the due date, "
        "the company may deduct the outstanding balance from my salary, subject to "
        "company rules and applicable laws. / 予定日までに清算または返金できない場合、"
        "会社規程および適用法令の範囲内で、未清算額を給与から控除することに同意します。"
    )
    for i in range(0, len(undertaking), 68):
        text.textLine(undertaking[i:i + 68])
    c.drawText(text)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()


def send_email_with_attachment(to_email: str, subject: str, body: str, attachment_name: str, attachment_bytes: bytes):
    if not SMTP_ENABLED:
        return

    if not all([SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL]):
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_attachment(attachment_bytes, maintype="application", subtype="pdf", filename=attachment_name)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)


def notify_user(recipient_email: str, subject: str, body: str, request_row: dict):
    pdf_bytes = build_request_pdf(request_row)
    file_name = f"cash_advance_{request_row['id']}.pdf"
    attachment_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    create_inbox_message(
        {
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "related_request_id": request_row["id"],
            "attachment_filename": file_name,
            "attachment_base64": attachment_base64,
            "is_read": False,
        }
    )

    try:
        send_email_with_attachment(
            to_email=recipient_email,
            subject=subject,
            body=body,
            attachment_name=file_name,
            attachment_bytes=pdf_bytes,
        )
    except Exception as e:
        # do not break the app if SMTP fails
        st.warning(f"Email send failed for {recipient_email}: {e}")


# ============================================================
# Screens
# ============================================================
def login_screen():
    st.title("Cash Advance Application")
    st.subheader("Google Login")
    st.button("Log in with Google", on_click=st.login, use_container_width=True)
    st.info("Googleログイン後に自動でアプリへ戻ります。")


def sidebar(profile: dict):
    with st.sidebar:
        st.markdown("### User")
        st.write(profile.get("full_name", ""))
        st.write(profile.get("email", ""))
        st.write(f"Role: {role_of(profile)}")
        st.button("Log out", on_click=st.logout, use_container_width=True)


def inbox_tab(profile: dict):
    st.subheader("Inbox")
    rows = list_inbox_messages(profile["email"])
    if not rows:
        st.info("No inbox messages.")
        return

    unread_count = sum(1 for r in rows if not r.get("is_read", False))
    st.caption(f"Unread: {unread_count}")

    for row in rows:
        title_prefix = "● " if not row.get("is_read", False) else ""
        title = f"{title_prefix}{row.get('subject', '')} | {row.get('created_at', '')[:16]}"
        with st.expander(title):
            st.write(row.get("body", ""))
            if row.get("attachment_base64"):
                pdf_bytes = base64.b64decode(row["attachment_base64"])
                st.download_button(
                    "Download PDF",
                    data=pdf_bytes,
                    file_name=row.get("attachment_filename") or "attachment.pdf",
                    mime="application/pdf",
                    key=f"inbox_pdf_{row['id']}",
                    use_container_width=True,
                )

            c1, c2 = st.columns(2)
            with c1:
                if not row.get("is_read", False):
                    if st.button("Mark as Read", key=f"read_{row['id']}", use_container_width=True):
                        update_inbox_message(row["id"], {"is_read": True})
                        flash_success("Message marked as read.")
                        st.rerun()
            with c2:
                if st.button("Delete", key=f"delete_msg_{row['id']}", use_container_width=True):
                    delete_inbox_message(row["id"])
                    flash_success("Message deleted.")
                    st.rerun()


# ============================================================
# Employee
# ============================================================
def request_form_tab(profile: dict):
    st.subheader("New C/A Request")

    profiles = list_profiles(active_only=True)
    approver1_profiles = [p for p in profiles if role_of(p) in {ROLE_APPROVER1, ROLE_APPROVER2}]
    approver2_profiles = [p for p in profiles if role_of(p) == ROLE_APPROVER2]

    approver1_map = {
        f"{p.get('full_name', '')} ({p.get('email', '')})": p
        for p in approver1_profiles
    }
    approver2_map = {
        f"{p.get('full_name', '')} ({p.get('email', '')})": p
        for p in approver2_profiles
    }

    with st.form("ca_request_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            full_name = st.text_input("Name", value=profile.get("full_name", ""))
        with c2:
            department = st.text_input("Department", value=profile.get("department", ""))
        with c3:
            office = st.text_input("Office", value=profile.get("office", ""))

        amount = st.number_input("Amount", min_value=0.0, step=100.0, format="%.2f")
        purpose = st.text_area("Purpose")
        liquidation_due_date = st.date_input("Liquidation Due Date", value=date.today())

        approver1_label = st.selectbox("Approver 1", options=[""] + list(approver1_map.keys()))
        approver2_label = st.selectbox("Approver 2", options=[""] + list(approver2_map.keys()))

        st.markdown("**Undertaking / 誓約**")
        st.caption(
            "I agree that if I fail to liquidate or return the amount by the due date, "
            "the company may deduct the outstanding amount from my salary subject to company rules and applicable laws."
        )
        undertaking = st.checkbox("I agree / 同意します")

        submitted = st.form_submit_button("Submit Request", use_container_width=True)

    if submitted:
        if amount <= 0:
            st.error("Amount must be greater than zero.")
            return
        if not purpose.strip():
            st.error("Purpose is required.")
            return
        if not undertaking:
            st.error("You must agree to the undertaking.")
            return
        if not approver1_label:
            st.error("Please select Approver 1.")
            return
        if not approver2_label:
            st.error("Please select Approver 2.")
            return

        approver1 = approver1_map[approver1_label]
        approver2 = approver2_map[approver2_label]

        payload = {
            "employee_email": profile["email"],
            "employee_name": full_name.strip(),
            "department": department.strip(),
            "office": office.strip(),
            "amount": float(amount),
            "purpose": purpose.strip(),
            "liquidation_due_date": str(liquidation_due_date),
            "approver1_id": approver1["id"],
            "approver1_email": approver1["email"],
            "approver1_name": approver1["full_name"],
            "approver2_id": approver2["id"],
            "approver2_email": approver2["email"],
            "approver2_name": approver2["full_name"],
            "employee_signed_name": full_name.strip(),
            "payroll_deduction_consent": True,
            "status": "submitted",
        }
        created = create_request(payload)
        if not created:
            st.error("Request was not created.")
            return

        requester_body = (
            f"Your cash advance request was submitted.\n\n"
            f"Amount: {money(created.get('amount'))}\n"
            f"Purpose: {created.get('purpose')}\n"
            f"Approver 1: {created.get('approver1_name')}\n"
            f"Approver 2: {created.get('approver2_name')}"
        )
        notify_user(
            recipient_email=created["employee_email"],
            subject="Cash Advance Submitted",
            body=requester_body,
            request_row=created,
        )

        approver1_body = (
            f"A cash advance request is waiting for your approval.\n\n"
            f"Employee: {created.get('employee_name')}\n"
            f"Amount: {money(created.get('amount'))}\n"
            f"Purpose: {created.get('purpose')}"
        )
        notify_user(
            recipient_email=created["approver1_email"],
            subject="Cash Advance Approval Needed - Approver 1",
            body=approver1_body,
            request_row=created,
        )

        flash_success("Request submitted and notifications sent.")
        st.rerun()


def my_requests_tab(profile: dict):
    st.subheader("My Requests")
    rows = list_requests_for_employee(profile["email"])
    if not rows:
        st.info("No requests yet.")
        return

    for row in rows:
        title = f"{row.get('created_at', '')[:10]} | {row.get('status')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write(
                {
                    "Name": row.get("employee_name"),
                    "Department": row.get("department"),
                    "Office": row.get("office"),
                    "Amount": row.get("amount"),
                    "Purpose": row.get("purpose"),
                    "Due Date": row.get("liquidation_due_date"),
                    "Approver 1": row.get("approver1_name"),
                    "Approver 2": row.get("approver2_name"),
                    "Status": row.get("status"),
                }
            )
            pdf_bytes = build_request_pdf(row)
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name=f"cash_advance_{row['id']}.pdf",
                mime="application/pdf",
                key=f"my_pdf_{row['id']}",
                use_container_width=True,
            )


# ============================================================
# Approval
# ============================================================
def approver1_queue_tab(profile: dict):
    st.subheader("Approver 1 Queue")
    rows = list_requests_for_approver1(profile["email"])
    if not rows:
        st.info("No items for approval.")
        return

    for row in rows:
        title = f"{row.get('employee_name')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write(
                {
                    "Purpose": row.get("purpose"),
                    "Department": row.get("department"),
                    "Office": row.get("office"),
                    "Due Date": row.get("liquidation_due_date"),
                    "Employee Email": row.get("employee_email"),
                }
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Approve", key=f"ap1_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {"status": "approver1_approved", "approver1_signed_name": profile["full_name"]},
                    )
                    refreshed = get_request_by_id(row["id"])
                    if refreshed:
                        notify_user(
                            recipient_email=refreshed["approver2_email"],
                            subject="Cash Advance Approval Needed - Approver 2",
                            body=(
                                f"A cash advance request passed Approver 1 and is waiting for your approval.\n\n"
                                f"Employee: {refreshed.get('employee_name')}\n"
                                f"Amount: {money(refreshed.get('amount'))}\n"
                                f"Purpose: {refreshed.get('purpose')}"
                            ),
                            request_row=refreshed,
                        )
                        notify_user(
                            recipient_email=refreshed["employee_email"],
                            subject="Cash Advance Approved by Approver 1",
                            body=(
                                f"Your request was approved by Approver 1.\n\n"
                                f"Approver 1: {profile.get('full_name')}"
                            ),
                            request_row=refreshed,
                        )
                    flash_success("Request approved and forwarded to Approver 2.")
                    st.rerun()
            with c2:
                if st.button("Reject", key=f"ap1rej_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {"status": "rejected", "approver1_signed_name": profile["full_name"]},
                    )
                    refreshed = get_request_by_id(row["id"])
                    if refreshed:
                        notify_user(
                            recipient_email=refreshed["employee_email"],
                            subject="Cash Advance Rejected by Approver 1",
                            body=f"Your request was rejected by Approver 1: {profile.get('full_name')}.",
                            request_row=refreshed,
                        )
                    flash_success("Request rejected.")
                    st.rerun()


def approver2_queue_tab(profile: dict):
    st.subheader("Approver 2 Queue")
    rows = list_requests_for_approver2(profile["email"])
    if not rows:
        st.info("No items for approval.")
        return

    for row in rows:
        title = f"{row.get('employee_name')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write(
                {
                    "Purpose": row.get("purpose"),
                    "Department": row.get("department"),
                    "Office": row.get("office"),
                    "Due Date": row.get("liquidation_due_date"),
                    "Employee Email": row.get("employee_email"),
                }
            )

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Approve", key=f"ap2_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {"status": "approved", "approver2_signed_name": profile["full_name"]},
                    )
                    refreshed = get_request_by_id(row["id"])
                    if refreshed:
                        notify_user(
                            recipient_email=refreshed["employee_email"],
                            subject="Cash Advance Fully Approved",
                            body=(
                                f"Your request was fully approved.\n\n"
                                f"Approver 2: {profile.get('full_name')}"
                            ),
                            request_row=refreshed,
                        )
                    flash_success("Request fully approved.")
                    st.rerun()
            with c2:
                if st.button("Reject", key=f"ap2rej_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {"status": "rejected", "approver2_signed_name": profile["full_name"]},
                    )
                    refreshed = get_request_by_id(row["id"])
                    if refreshed:
                        notify_user(
                            recipient_email=refreshed["employee_email"],
                            subject="Cash Advance Rejected by Approver 2",
                            body=f"Your request was rejected by Approver 2: {profile.get('full_name')}.",
                            request_row=refreshed,
                        )
                    flash_success("Request rejected.")
                    st.rerun()


# ============================================================
# Admin
# ============================================================
def admin_users_tab():
    st.subheader("User Management")

    with st.expander("Register New User", expanded=False):
        with st.form("register_user_form"):
            new_email = st.text_input("Email")
            new_name = st.text_input("Full Name")
            new_department = st.text_input("Department")
            new_office = st.text_input("Office")
            new_role = st.selectbox("Role", options=ALL_ROLES)
            new_active = st.checkbox("Active", value=True)
            create_btn = st.form_submit_button("Create User", use_container_width=True)

        if create_btn:
            email = new_email.strip().lower()
            if not email:
                st.error("Email is required.")
            elif get_profile_by_email(email):
                st.error("That email already exists.")
            else:
                create_profile(
                    {
                        "email": email,
                        "full_name": new_name.strip() or email,
                        "department": new_department.strip(),
                        "office": new_office.strip(),
                        "role": new_role,
                        "is_active": new_active,
                    }
                )
                flash_success("User created.")
                st.rerun()

    rows = list_profiles()
    if not rows:
        st.info("No users found.")
        return

    for user in rows:
        title = f"{user.get('full_name', '')} | {user.get('email', '')} | {role_of(user)}"
        with st.expander(title):
            with st.form(f"user_{user['id']}"):
                full_name = st.text_input("Full Name", value=user.get("full_name", ""))
                department = st.text_input("Department", value=user.get("department", ""))
                office = st.text_input("Office", value=user.get("office", ""))
                role = st.selectbox("Role", options=ALL_ROLES, index=ALL_ROLES.index(role_of(user)))
                is_active = st.checkbox("Active", value=bool(user.get("is_active", True)))
                save_btn = st.form_submit_button("Save Changes", use_container_width=True)

            if save_btn:
                update_profile(
                    user["id"],
                    {
                        "full_name": full_name.strip(),
                        "department": department.strip(),
                        "office": office.strip(),
                        "role": role,
                        "is_active": is_active,
                    },
                )
                flash_success("User updated.")
                st.rerun()

            if st.button(f"Delete User: {user.get('email')}", key=f"del_{user['id']}", use_container_width=True):
                delete_profile(user["id"])
                flash_success("User deleted.")
                st.rerun()


def admin_requests_tab():
    st.subheader("All Requests")
    rows = list_all_requests()
    if not rows:
        st.info("No requests yet.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


# ============================================================
# Main
# ============================================================
def main():
    if not st.user.is_logged_in:
        login_screen()
        st.stop()

    profile = ensure_profile()

    if not profile.get("is_active", True):
        st.error("Your account is inactive.")
        st.button("Log out", on_click=st.logout, use_container_width=True)
        st.stop()

    sidebar(profile)
    show_flash()

    st.title("Cash Advance Application")

    role = role_of(profile)

    tab_names = ["Inbox", "Request Form", "My Requests"]

    if role in {ROLE_APPROVER1, ROLE_APPROVER2}:
        tab_names.append("Approver 1 Queue")

    if role == ROLE_APPROVER2:
        tab_names.extend(["Approver 2 Queue", "User Management", "All Requests"])

    tabs = st.tabs(tab_names)
    idx = 0

    with tabs[idx]:
        inbox_tab(profile)
    idx += 1

    with tabs[idx]:
        request_form_tab(profile)
    idx += 1

    with tabs[idx]:
        my_requests_tab(profile)
    idx += 1

    if role in {ROLE_APPROVER1, ROLE_APPROVER2}:
        with tabs[idx]:
            approver1_queue_tab(profile)
        idx += 1

    if role == ROLE_APPROVER2:
        with tabs[idx]:
            approver2_queue_tab(profile)
        idx += 1

        with tabs[idx]:
            admin_users_tab()
        idx += 1

        with tabs[idx]:
            admin_requests_tab()


if __name__ == "__main__":
    main()

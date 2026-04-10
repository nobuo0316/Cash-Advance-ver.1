import streamlit as st
from supabase import create_client, Client
from datetime import date
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Cash Advance Application", page_icon="💼", layout="wide")

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
ALLOWED_GOOGLE_DOMAIN = st.secrets.get("ALLOWED_GOOGLE_DOMAIN", "").strip().lower()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


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
    return (profile.get("role") or "employee").lower()


def money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)


def api_error_block(title: str, err: Exception):
    st.error(title)
    st.code(str(err))
    st.stop()


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


def list_profiles() -> list[dict]:
    try:
        res = supabase.table("profiles").select("*").order("created_at").execute()
        return res.data or []
    except Exception as e:
        api_error_block("Could not load profiles.", e)


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

    payload = {
        "email": email,
        "full_name": name,
        "department": "",
        "office": "",
        "role": "employee",
        "is_active": True,
        "manager_id": None,
    }

    try:
        created = supabase.table("profiles").insert(payload).execute()
        if created.data:
            return created.data[0]
    except Exception as e:
        api_error_block("Profile creation failed.", e)

    created_again = get_profile_by_email(email)
    if created_again:
        return created_again

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


def list_requests_for_manager(manager_email: str) -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("manager_email", manager_email)
            .in_("status", ["submitted"])
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load manager queue.", e)


def list_requests_for_finance() -> list[dict]:
    try:
        res = (
            supabase.table("cash_advance_requests")
            .select("*")
            .in_("status", ["manager_approved", "finance_approved", "payroll_deduction"])
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        api_error_block("Could not load finance queue.", e)


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


def create_request(payload: dict):
    try:
        supabase.table("cash_advance_requests").insert(payload).execute()
    except Exception as e:
        api_error_block("Request submission failed.", e)


def update_request(request_id: str, payload: dict):
    try:
        supabase.table("cash_advance_requests").update(payload).eq("id", request_id).execute()
    except Exception as e:
        api_error_block("Request update failed.", e)


def update_profile(profile_id: str, payload: dict):
    try:
        supabase.table("profiles").update(payload).eq("id", profile_id).execute()
    except Exception as e:
        api_error_block("Profile update failed.", e)


def build_request_pdf(request_row: dict) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    left = 18 * mm
    y = height - 18 * mm
    line_gap = 7 * mm

    def line(label: str, value: str):
        nonlocal y
        c.setFont("HeiseiKakuGo-W5", 10)
        c.drawString(left, y, label)
        c.drawString(left + 52 * mm, y, value or "")
        y -= line_gap

    c.setTitle(f"Cash Advance - {request_row.get('employee_name', '')}")
    c.setFont("HeiseiKakuGo-W5", 16)
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
    line("Manager / 上長", str(request_row.get("manager_name", "")))
    line("Employee Sign / 本人サイン", str(request_row.get("employee_signed_name", "")))
    line("Manager Sign / 上長サイン", str(request_row.get("manager_signed_name", "")))
    line("Finance Sign / 財務サイン", str(request_row.get("finance_signed_name", "")))

    y -= 4 * mm
    c.setFont("HeiseiKakuGo-W5", 11)
    c.drawString(left, y, "Undertaking / 誓約")
    y -= 6 * mm

    text = c.beginText(left, y)
    text.setFont("HeiseiKakuGo-W5", 9)
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
        if profile.get("department"):
            st.write(f"Department: {profile['department']}")
        if profile.get("office"):
            st.write(f"Office: {profile['office']}")
        st.button("Log out", on_click=st.logout, use_container_width=True)


def tab_request_form(profile: dict):
    st.subheader("New C/A Request")

    profiles = list_profiles()
    manager_profiles = [
        p for p in profiles
        if p.get("is_active", True) and role_of(p) in {"manager", "admin"}
    ]
    manager_labels = {
        f"{p.get('full_name', '')} ({p.get('email', '')})": p
        for p in manager_profiles
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

        manager_label = st.selectbox(
            "Approving Manager",
            options=[""] + list(manager_labels.keys()),
            index=0,
        )

        st.markdown("**Undertaking / 誓約**")
        st.caption(
            "I agree that if I fail to liquidate or return the amount by the due date, "
            "the company may deduct the outstanding amount from my salary subject to "
            "company rules and applicable laws."
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
        if not manager_label:
            st.error("Please select an approving manager.")
            return
        if not undertaking:
            st.error("You must agree to the undertaking.")
            return

        manager = manager_labels[manager_label]
        payload = {
            "employee_email": profile["email"],
            "employee_name": full_name.strip(),
            "department": department.strip(),
            "office": office.strip(),
            "amount": float(amount),
            "purpose": purpose.strip(),
            "liquidation_due_date": str(liquidation_due_date),
            "manager_id": manager["id"],
            "manager_email": manager["email"],
            "manager_name": manager["full_name"],
            "employee_signed_name": full_name.strip(),
            "payroll_deduction_consent": True,
            "status": "submitted",
        }
        create_request(payload)
        st.success("Request submitted.")
        st.rerun()


def tab_my_requests(profile: dict):
    st.subheader("My Requests")
    rows = list_requests_for_employee(profile["email"])
    if not rows:
        st.info("No requests yet.")
        return

    for row in rows:
        title = f"{row.get('created_at', '')[:10]} | {row.get('status')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write({
                "Name": row.get("employee_name"),
                "Department": row.get("department"),
                "Office": row.get("office"),
                "Amount": row.get("amount"),
                "Purpose": row.get("purpose"),
                "Due Date": row.get("liquidation_due_date"),
                "Manager": row.get("manager_name"),
                "Status": row.get("status"),
            })
            pdf_bytes = build_request_pdf(row)
            st.download_button(
                "Download PDF",
                data=pdf_bytes,
                file_name=f"cash_advance_{row['id']}.pdf",
                mime="application/pdf",
                key=f"pdf_{row['id']}",
                use_container_width=True,
            )


def tab_manager_queue(profile: dict):
    st.subheader("Manager Approval Queue")
    rows = list_requests_for_manager(profile["email"])
    if not rows:
        st.info("No items for approval.")
        return

    for row in rows:
        title = f"{row.get('employee_name')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write({
                "Purpose": row.get("purpose"),
                "Department": row.get("department"),
                "Office": row.get("office"),
                "Due Date": row.get("liquidation_due_date"),
                "Employee Email": row.get("employee_email"),
            })
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Approve", key=f"mgr_appr_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {
                            "status": "manager_approved",
                            "manager_signed_name": profile["full_name"],
                        },
                    )
                    st.success("Approved.")
                    st.rerun()
            with c2:
                if st.button("Reject", key=f"mgr_rej_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {
                            "status": "rejected",
                            "manager_signed_name": profile["full_name"],
                        },
                    )
                    st.success("Rejected.")
                    st.rerun()


def tab_finance_queue(profile: dict):
    st.subheader("Finance Queue")
    rows = list_requests_for_finance()
    if not rows:
        st.info("No finance items.")
        return

    for row in rows:
        title = f"{row.get('employee_name')} | {row.get('status')} | {money(row.get('amount', 0))}"
        with st.expander(title):
            st.write({
                "Purpose": row.get("purpose"),
                "Manager": row.get("manager_name"),
                "Employee": row.get("employee_email"),
                "Due Date": row.get("liquidation_due_date"),
            })

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Finance Approve", key=f"fin_appr_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {
                            "status": "finance_approved",
                            "finance_signed_name": profile["full_name"],
                        },
                    )
                    st.success("Marked as finance approved.")
                    st.rerun()
            with c2:
                if st.button("Liquidated", key=f"fin_liq_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {
                            "status": "liquidated",
                            "finance_signed_name": profile["full_name"],
                        },
                    )
                    st.success("Marked as liquidated.")
                    st.rerun()
            with c3:
                if st.button("Payroll Deduction", key=f"fin_pay_{row['id']}", use_container_width=True):
                    update_request(
                        row["id"],
                        {
                            "status": "payroll_deduction",
                            "finance_signed_name": profile["full_name"],
                        },
                    )
                    st.success("Marked as payroll deduction.")
                    st.rerun()


def tab_admin_users():
    st.subheader("Admin - User Management")
    rows = list_profiles()
    if not rows:
        st.info("No users found.")
        return

    managers = [r for r in rows if role_of(r) in {"manager", "admin"}]
    manager_options = {"": None}
    for m in managers:
        label = f"{m.get('full_name', '')} ({m.get('email', '')})"
        manager_options[label] = m["id"]

    for user in rows:
        title = f"{user.get('full_name', '')} | {user.get('email', '')} | {role_of(user)}"
        with st.expander(title):
            with st.form(f"profile_{user['id']}"):
                full_name = st.text_input("Full Name", value=user.get("full_name", ""))
                department = st.text_input("Department", value=user.get("department", ""))
                office = st.text_input("Office", value=user.get("office", ""))
                role = st.selectbox(
                    "Role",
                    options=["employee", "manager", "finance", "admin"],
                    index=["employee", "manager", "finance", "admin"].index(role_of(user)),
                )
                is_active = st.checkbox("Active", value=bool(user.get("is_active", True)))

                current_manager_id = user.get("manager_id")
                labels = list(manager_options.keys())
                default_idx = 0
                for idx, label in enumerate(labels):
                    if manager_options[label] == current_manager_id:
                        default_idx = idx
                        break

                selected_manager = st.selectbox(
                    "Default Manager",
                    options=labels,
                    index=default_idx,
                )

                saved = st.form_submit_button("Save", use_container_width=True)

            if saved:
                update_profile(
                    user["id"],
                    {
                        "full_name": full_name.strip(),
                        "department": department.strip(),
                        "office": office.strip(),
                        "role": role,
                        "is_active": is_active,
                        "manager_id": manager_options[selected_manager],
                    },
                )
                st.success("User updated.")
                st.rerun()


def tab_admin_requests():
    st.subheader("Admin - All Requests")
    rows = list_all_requests()
    if not rows:
        st.info("No requests yet.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)


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

    st.title("Cash Advance Application")

    role = role_of(profile)

    tab_names = ["Request Form", "My Requests"]
    if role in {"manager", "admin"}:
        tab_names.append("Manager Queue")
    if role in {"finance", "admin"}:
        tab_names.append("Finance Queue")
    if role == "admin":
        tab_names.extend(["User Management", "All Requests"])

    tabs = st.tabs(tab_names)
    idx = 0

    with tabs[idx]:
        tab_request_form(profile)
    idx += 1

    with tabs[idx]:
        tab_my_requests(profile)
    idx += 1

    if role in {"manager", "admin"}:
        with tabs[idx]:
            tab_manager_queue(profile)
        idx += 1

    if role in {"finance", "admin"}:
        with tabs[idx]:
            tab_finance_queue(profile)
        idx += 1

    if role == "admin":
        with tabs[idx]:
            tab_admin_users()
        idx += 1

        with tabs[idx]:
            tab_admin_requests()


if __name__ == "__main__":
    main()

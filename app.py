import streamlit as st
from supabase import create_client, Client
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Cash Advance Application", page_icon="💼", layout="wide")

# =========================================================
# Secrets
# =========================================================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]
ALLOWED_DOMAIN = st.secrets.get("ALLOWED_GOOGLE_DOMAIN", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# =========================================================
# Helpers
# =========================================================
def safe_email() -> str:
    return (st.user.get("email") or "").strip().lower()

def safe_name() -> str:
    return (st.user.get("name") or st.user.get("email") or "").strip()

def is_allowed_domain(email: str) -> bool:
    if not ALLOWED_DOMAIN:
        return True
    if "@" not in email:
        return False
    return email.split("@", 1)[1].lower() == ALLOWED_DOMAIN.lower()

def profile_by_email(email: str) -> dict | None:
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

def list_profiles() -> list[dict]:
    res = supabase.table("profiles").select("*").order("created_at", desc=False).execute()
    return res.data or []

def ensure_profile() -> dict | None:
    email = safe_email()
    name = safe_name()

    if not email:
        st.error("Google account email was not returned.")
        return None

    if not is_allowed_domain(email):
        st.error(f"This app only allows @{ALLOWED_DOMAIN} accounts.")
        st.button("Log out", on_click=st.logout)
        st.stop()

    existing = profile_by_email(email)
    if existing:
        return existing

    payload = {
        "email": email,
        "full_name": name,
        "department": "",
        "office": "",
        "role": "employee",
        "is_active": True,
    }
    created = supabase.table("profiles").insert(payload).execute()
    if created.data:
        return created.data[0]
    return profile_by_email(email)

def role_of(profile: dict) -> str:
    return (profile.get("role") or "employee").lower()

def money(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except Exception:
        return str(value)

def yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"

def load_my_requests(email: str) -> list[dict]:
    res = (
        supabase.table("cash_advance_requests")
        .select("*")
        .eq("employee_email", email)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

def load_manager_requests(profile: dict) -> list[dict]:
    email = profile["email"]
    res = (
        supabase.table("cash_advance_requests")
        .select("*")
        .eq("manager_email", email)
        .in_("status", ["submitted", "manager_approved"])
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

def load_finance_requests() -> list[dict]:
    res = (
        supabase.table("cash_advance_requests")
        .select("*")
        .in_("status", ["manager_approved", "finance_approved", "payroll_deduction"])
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

def load_all_requests() -> list[dict]:
    res = (
        supabase.table("cash_advance_requests")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

def update_profile(profile_id: str, payload: dict):
    return supabase.table("profiles").update(payload).eq("id", profile_id).execute()

def update_request(request_id: str, payload: dict):
    return supabase.table("cash_advance_requests").update(payload).eq("id", request_id).execute()

def build_request_pdf(request_row: dict) -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"CA Request - {request_row.get('employee_name', '')}")

    width, height = A4
    left = 18 * mm
    top = height - 18 * mm
    line_gap = 7 * mm

    def draw_line(label: str, value: str, y: float):
        c.setFont("HeiseiKakuGo-W5", 10)
        c.drawString(left, y, label)
        c.drawString(left + 45 * mm, y, value if value is not None else "")

    c.setFont("HeiseiKakuGo-W5", 16)
    c.drawString(left, top, "Cash Advance Application / C/A申請書")

    y = top - 12 * mm
    draw_line("Request ID", str(request_row.get("id", "")), y); y -= line_gap
    draw_line("Name / 名前", str(request_row.get("employee_name", "")), y); y -= line_gap
    draw_line("Department / 所属", str(request_row.get("department", "")), y); y -= line_gap
    draw_line("Office / オフィス", str(request_row.get("office", "")), y); y -= line_gap
    draw_line("Amount / 金額", money(request_row.get("amount", 0)), y); y -= line_gap
    draw_line("Purpose / 目的", str(request_row.get("purpose", "")), y); y -= line_gap
    draw_line("Liquidation Due Date / 清算予定日", str(request_row.get("liquidation_due_date", "")), y); y -= line_gap
    draw_line("Status / ステータス", str(request_row.get("status", "")), y); y -= line_gap
    draw_line("Manager / 上長", str(request_row.get("manager_name", "")), y); y -= line_gap
    draw_line("Employee Sign / 本人サイン", str(request_row.get("employee_signed_name", "")), y); y -= line_gap
    draw_line("Manager Sign / 上長サイン", str(request_row.get("manager_signed_name", "")), y); y -= line_gap
    draw_line("Finance Sign / 財務サイン", str(request_row.get("finance_signed_name", "")), y); y -= line_gap

    y -= 4 * mm
    c.setFont("HeiseiKakuGo-W5", 11)
    c.drawString(left, y, "Undertaking / 誓約")
    y -= 6 * mm

    text = c.beginText(left, y)
    text.setFont("HeiseiKakuGo-W5", 9)
    undertaking = (
        "I agree that if I fail to liquidate or return the amount by the due date, "
        "the company may deduct the outstanding balance from my salary, subject to company rules "
        "and applicable laws. / 予定日までに清算または返金できない場合、会社規程および適用法令の範囲内で、"
        "未清算額を給与から控除することに同意します。"
    )
    for chunk in [
        undertaking[i:i + 70] for i in range(0, len(undertaking), 70)
    ]:
        text.textLine(chunk)
    c.drawText(text)

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

# =========================================================
# Login
# =========================================================
def login_screen():
    st.title("Cash Advance Application")
    st.subheader("Google login")
    st.button("Log in with Google", on_click=st.login, use_container_width=True)
    st.info("Googleログイン後に自動でアプリへ戻ります。")

# =========================================================
# Sidebar
# =========================================================
def sidebar_user(profile: dict):
    with st.sidebar:
        st.markdown("### User")
        st.write(profile.get("full_name", ""))
        st.write(profile.get("email", ""))
        st.write(f"Role: {role_of(profile)}")
        if profile.get("department"):
            st.write(f"Department: {profile.get('department')}")
        if profile.get("office"):
            st.write(f"Office: {profile.get('office')}")
        st.button("Log out", on_click=st.logout, use_container_width=True)

# =========================================================
# Employee Views
# =========================================================
def employee_request_form(profile: dict):
    st.subheader("New C/A Request")

    profiles = list_profiles()
    manager_options = [p for p in profiles if role_of(p) in {"manager", "admin"} and p.get("is_active", True)]
    manager_labels = {f"{p.get('full_name', '')} ({p.get('email', '')})": p for p in manager_options}

    with st.form("ca_request_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            name = st.text_input("Name", value=profile.get("full_name", ""))
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
            "the company may deduct the outstanding amount from my salary subject to company rules and applicable laws."
        )
        undertaking_ok = st.checkbox("I agree / 同意します")

        submit = st.form_submit_button("Submit Request", use_container_width=True)

    if submit:
        if amount <= 0:
            st.error("Amount must be greater than zero.")
            return
        if not purpose.strip():
            st.error("Purpose is required.")
            return
        if not undertaking_ok:
            st.error("You must agree to the undertaking.")
            return
        if not manager_label:
            st.error("Please select an approving manager.")
            return

        manager_profile = manager_labels[manager_label]
        payload = {
            "employee_email": profile["email"],
            "employee_name": name.strip(),
            "department": department.strip(),
            "office": office.strip(),
            "amount": float(amount),
            "purpose": purpose.strip(),
            "liquidation_due_date": str(liquidation_due_date),
            "manager_id": manager_profile["id"],
            "manager_email": manager_profile["email"],
            "manager_name": manager_profile["full_name"],
            "employee_signed_name": name.strip(),
            "payroll_deduction_consent": True,
            "status": "submitted",
        }

        try:
            supabase.table("cash_advance_requests").insert(payload).execute()
            st.success("Request submitted.")
            st.rerun()
        except Exception as e:
            st.error(f"Submit failed: {e}")

def employee_my_requests(profile: dict):
    st.subheader("My Requests")
    rows = load_my_requests(profile["email"])
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
                "Liquidation Due Date": row.get("liquidation_due_date"),
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

# =========================================================
# Manager
# =========================================================
def manager_queue(profile: dict):
    st.subheader("Manager Approval Queue")
    rows = load_manager_requests(profile)
    if not rows:
        st.info("No items for approval.")
        return

    for row in rows:
        title = f"{row.get('employee_name')} | {money(row.get('amount', 0))} | {row.get('status')}"
        with st.expander(title):
            st.write({
                "Purpose": row.get("purpose"),
                "Liquidation Due Date": row.get("liquidation_due_date"),
                "Department": row.get("department"),
                "Office": row.get("office"),
                "Employee": row.get("employee_email"),
            })

            c1, c2 = st.columns(2)
            with c1:
                if st.button("Approve", key=f"mgr_approve_{row['id']}", use_container_width=True):
                    try:
                        update_request(
                            row["id"],
                            {
                                "status": "manager_approved",
                                "manager_signed_name": profile["full_name"],
                            },
                        )
                        st.success("Approved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Approve failed: {e}")
            with c2:
                if st.button("Reject", key=f"mgr_reject_{row['id']}", use_container_width=True):
                    try:
                        update_request(
                            row["id"],
                            {
                                "status": "rejected",
                                "manager_signed_name": profile["full_name"],
                            },
                        )
                        st.success("Rejected.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Reject failed: {e}")

# =========================================================
# Finance
# =========================================================
def finance_queue(profile: dict):
    st.subheader("Finance Queue")
    rows = load_finance_requests()
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
                    try:
                        update_request(
                            row["id"],
                            {
                                "status": "finance_approved",
                                "finance_signed_name": profile["full_name"],
                            },
                        )
                        st.success("Marked as finance approved.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")
            with c2:
                if st.button("Liquidated", key=f"fin_liq_{row['id']}", use_container_width=True):
                    try:
                        update_request(
                            row["id"],
                            {
                                "status": "liquidated",
                                "finance_signed_name": profile["full_name"],
                            },
                        )
                        st.success("Marked as liquidated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")
            with c3:
                if st.button("Payroll Deduction", key=f"fin_pay_{row['id']}", use_container_width=True):
                    try:
                        update_request(
                            row["id"],
                            {
                                "status": "payroll_deduction",
                                "finance_signed_name": profile["full_name"],
                            },
                        )
                        st.success("Marked as payroll deduction.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")

# =========================================================
# Admin
# =========================================================
def admin_user_management(current_profile: dict):
    st.subheader("Admin - User Management")

    rows = list_profiles()
    if not rows:
        st.info("No users found.")
        return

    # Summary
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Users", len(rows))
    c2.metric("Employees", sum(1 for r in rows if role_of(r) == "employee"))
    c3.metric("Managers", sum(1 for r in rows if role_of(r) == "manager"))
    c4.metric("Finance/Admin", sum(1 for r in rows if role_of(r) in {"finance", "admin"}))

    st.divider()

    managers = [r for r in rows if role_of(r) in {"manager", "admin"}]
    manager_options = {"": ""}
    for m in managers:
        manager_options[f"{m.get('full_name', '')} ({m.get('email', '')})"] = m["id"]

    for user in rows:
        title = f"{user.get('full_name', '')} | {user.get('email', '')} | {role_of(user)}"
        with st.expander(title):
            with st.form(f"admin_user_{user['id']}"):
                full_name = st.text_input("Full Name", value=user.get("full_name", ""))
                department = st.text_input("Department", value=user.get("department", ""))
                office = st.text_input("Office", value=user.get("office", ""))
                role = st.selectbox(
                    "Role",
                    options=["employee", "manager", "finance", "admin"],
                    index=["employee", "manager", "finance", "admin"].index(role_of(user)),
                )
                is_active = st.checkbox("Active", value=bool(user.get("is_active", True)))

                current_manager_id = user.get("manager_id") or ""
                manager_keys = list(manager_options.keys())
                current_index = 0
                for idx, key in enumerate(manager_keys):
                    if manager_options[key] == current_manager_id:
                        current_index = idx
                        break

                manager_label = st.selectbox(
                    "Default Manager (for profile)",
                    options=manager_keys,
                    index=current_index,
                )
                save = st.form_submit_button("Save", use_container_width=True)

            if save:
                try:
                    payload = {
                        "full_name": full_name.strip(),
                        "department": department.strip(),
                        "office": office.strip(),
                        "role": role,
                        "is_active": is_active,
                        "manager_id": manager_options[manager_label] or None,
                    }
                    update_profile(user["id"], payload)
                    st.success("User updated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")

def admin_request_overview():
    st.subheader("Admin - All Requests")
    rows = load_all_requests()
    if not rows:
        st.info("No requests yet.")
        return

    st.dataframe(rows, use_container_width=True, hide_index=True)

# =========================================================
# Main
# =========================================================
def main():
    if not st.user.is_logged_in:
        login_screen()
        st.stop()

    profile = ensure_profile()
    if not profile:
        st.stop()

    if not profile.get("is_active", True):
        st.error("Your account is inactive.")
        st.button("Log out", on_click=st.logout)
        st.stop()

    sidebar_user(profile)

    st.title("Cash Advance Application")
    role = role_of(profile)

    tabs = ["Request Form", "My Requests"]
    if role in {"manager", "admin"}:
        tabs.append("Manager Queue")
    if role in {"finance", "admin"}:
        tabs.append("Finance Queue")
    if role == "admin":
        tabs.extend(["User Management", "All Requests"])

    tab_objs = st.tabs(tabs)
    idx = 0

    with tab_objs[idx]:
        employee_request_form(profile)
    idx += 1

    with tab_objs[idx]:
        employee_my_requests(profile)
    idx += 1

    if role in {"manager", "admin"}:
        with tab_objs[idx]:
            manager_queue(profile)
        idx += 1

    if role in {"finance", "admin"}:
        with tab_objs[idx]:
            finance_queue(profile)
        idx += 1

    if role == "admin":
        with tab_objs[idx]:
            admin_user_management(profile)
        idx += 1

        with tab_objs[idx]:
            admin_request_overview()

if __name__ == "__main__":
    main()

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

import pandas as pd
import streamlit as st
from postgrest.exceptions import APIError
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from supabase import Client, create_client

st.set_page_config(page_title="Cash Advance Application", page_icon="💸", layout="wide")

APP_TITLE = "💸 Cash Advance Application"
APP_URL = "https://avg-salary-at-manila-ffmzzkydywu9cnqwks5za9.streamlit.app/"
DEFAULT_PLEDGE = (
    "If I fail to liquidate or return the cash advance on or before the due date, "
    "I authorize the company to deduct the outstanding balance from my salary, "
    "subject to company policy and applicable law."
)
ROLE_OPTIONS = ["employee", "manager", "finance", "admin"]


# -----------------------------------------------------------------------------
# Supabase client / session helpers
# -----------------------------------------------------------------------------
def get_base_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


def get_client() -> Client:
    client = get_base_client()
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        try:
            client.auth.set_session(access_token, refresh_token)
        except Exception:
            pass
    return client


def save_session(auth_response) -> None:
    session = getattr(auth_response, "session", None)
    user = getattr(auth_response, "user", None)
    if session is None or user is None:
        raise RuntimeError("Login succeeded but no session was returned.")

    st.session_state["access_token"] = session.access_token
    st.session_state["refresh_token"] = session.refresh_token
    st.session_state["user_email"] = user.email


def clear_session() -> None:
    for key in [
        "access_token",
        "refresh_token",
        "user_email",
        "profile_cache",
        "oauth_url",
    ]:
        st.session_state.pop(key, None)


def current_user():
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if not access_token or not refresh_token:
        return None

    client = get_client()
    try:
        response = client.auth.get_user()
        return getattr(response, "user", None)
    except Exception:
        clear_session()
        return None


def start_google_login() -> None:
    try:
        client = get_base_client()
        auth_response = client.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": APP_URL,
                    "skip_browser_redirect": True,
                },
            }
        )
        oauth_url = getattr(auth_response, "url", None)
        if not oauth_url:
            raise RuntimeError("Supabase did not return an OAuth URL.")
        st.session_state["oauth_url"] = oauth_url
    except Exception as e:
        st.error(f"Google sign-in start failed: {e}")



def handle_oauth_callback() -> None:
    if st.session_state.get("access_token"):
        return

    code = st.query_params.get("code")
    if not code:
        return

    try:
        client = get_base_client()
        auth_response = client.auth.exchange_code_for_session({"auth_code": code})
        save_session(auth_response)
        st.session_state.pop("oauth_url", None)
        st.query_params.clear()
        st.success("Google login completed.")
        st.rerun()
    except Exception as e:
        st.error(f"Google sign-in callback failed: {e}")


# -----------------------------------------------------------------------------
# Data access
# -----------------------------------------------------------------------------
def normalize_rows(rows):
    for row in rows:
        for key, value in list(row.items()):
            if isinstance(value, Decimal):
                row[key] = float(value)
    return rows


def ensure_profile(client: Client):
    user = current_user()
    if not user:
        return None

    try:
        data = (
            client.table("profiles")
            .select("id,email,full_name,department,office,role,manager_id,is_active")
            .eq("id", user.id)
            .single()
            .execute()
        )
        profile = data.data
        st.session_state["profile_cache"] = profile
        return profile
    except Exception:
        metadata = getattr(user, "user_metadata", {}) or {}
        full_name = (
            metadata.get("full_name")
            or metadata.get("name")
            or metadata.get("display_name")
            or (user.email.split("@")[0] if getattr(user, "email", None) else "")
        )
        department = metadata.get("department") or ""
        office = metadata.get("office") or ""

        payload = {
            "id": user.id,
            "email": user.email,
            "full_name": full_name,
            "department": department,
            "office": office,
        }
        client.table("profiles").upsert(payload).execute()
        data = (
            client.table("profiles")
            .select("id,email,full_name,department,office,role,manager_id,is_active")
            .eq("id", user.id)
            .single()
            .execute()
        )
        profile = data.data
        st.session_state["profile_cache"] = profile
        return profile


def fetch_profile(client: Client):
    user = current_user()
    if not user:
        return None

    cached = st.session_state.get("profile_cache")
    if cached and cached.get("id") == user.id:
        return cached

    return ensure_profile(client)


def list_my_requests(client: Client, profile_id: str):
    data = (
        client.table("cash_advance_requests")
        .select("*")
        .eq("employee_id", profile_id)
        .order("created_at", desc=True)
        .execute()
    )
    return normalize_rows(data.data or [])


def list_manager_requests(client: Client, manager_id: str):
    data = (
        client.table("cash_advance_requests")
        .select("*")
        .eq("manager_id", manager_id)
        .order("created_at", desc=True)
        .execute()
    )
    return normalize_rows(data.data or [])


def list_finance_requests(client: Client):
    data = (
        client.table("cash_advance_requests")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return normalize_rows(data.data or [])


def list_profiles(client: Client):
    data = (
        client.table("profiles")
        .select("id,email,full_name,department,office,role,manager_id,is_active")
        .order("full_name")
        .execute()
    )
    return data.data or []


def submit_request(client: Client, profile: dict, payload: dict):
    form_data = {
        "employee_id": profile["id"],
        "employee_name": profile["full_name"],
        "department": payload["department"],
        "office": payload["office"],
        "amount": payload["amount"],
        "purpose": payload["purpose"],
        "liquidation_due_date": payload["liquidation_due_date"].isoformat(),
        "payroll_deduction_consent": payload["consent"],
        "payroll_deduction_text": DEFAULT_PLEDGE,
        "employee_signed_name": payload["signed_name"],
        "employee_signed_at": datetime.utcnow().isoformat(),
        "manager_id": profile.get("manager_id"),
        "status": "submitted",
    }
    return client.table("cash_advance_requests").insert(form_data).execute()


def update_request_status(client: Client, request_id: str, fields: dict):
    return client.table("cash_advance_requests").update(fields).eq("id", request_id).execute()


def update_profile(client: Client, profile_id: str, fields: dict):
    return client.table("profiles").update(fields).eq("id", profile_id).execute()


# -----------------------------------------------------------------------------
# PDF helper
# -----------------------------------------------------------------------------
def request_to_pdf_bytes(row: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
    story = [Paragraph("Cash Advance Application", styles["Title"]), Spacer(1, 6 * mm)]

    fields = [
        ("Status", row.get("status")),
        ("Employee", row.get("employee_name")),
        ("Department", row.get("department")),
        ("Office", row.get("office")),
        ("Amount", f"{float(row.get('amount') or 0):,.2f}"),
        ("Purpose", row.get("purpose")),
        ("Liquidation due date", row.get("liquidation_due_date")),
        ("Employee signature", row.get("employee_signed_name")),
        ("Manager signature", row.get("manager_signed_name")),
        ("Finance signature", row.get("finance_signed_name")),
        ("Undertaking", row.get("payroll_deduction_text") or DEFAULT_PLEDGE),
        ("Rejection reason", row.get("rejection_reason") or "-"),
        ("Liquidation notes", row.get("liquidation_notes") or "-"),
    ]

    for label, value in fields:
        safe_value = str(value or "-").replace("\n", "<br/>")
        story.append(Paragraph(f"<b>{label}:</b> {safe_value}", styles["BodyText"]))
        story.append(Spacer(1, 2 * mm))

    doc.build(story)
    return buffer.getvalue()


# -----------------------------------------------------------------------------
# UI helpers
# -----------------------------------------------------------------------------
def show_header(profile: dict):
    st.title(APP_TITLE)
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
    c1.write(f"**User:** {profile['full_name']}")
    c2.write(f"**Role:** {profile['role']}")
    c3.write(f"**Office:** {profile.get('office') or '-'}")
    if c4.button("Log out"):
        try:
            get_client().auth.sign_out()
        except Exception:
            pass
        clear_session()
        st.rerun()


def login_screen():
    st.title(APP_TITLE)
    st.caption("Supabase Auth + Streamlit starter for Cash Advance Application")

    st.subheader("Google sign-in")
    if st.button("Sign in with Google", use_container_width=True):
        start_google_login()
        st.rerun()

    oauth_url = st.session_state.get("oauth_url")
    if oauth_url:
        st.link_button("Continue to Google", oauth_url, use_container_width=True)
        st.info("After Google sign-in, you will be redirected back to this app.")

    st.divider()

    tabs = st.tabs(["Login", "Sign up"])

    with tabs[0]:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
                return
            try:
                client = get_base_client()
                auth_response = client.auth.sign_in_with_password({"email": email, "password": password})
                save_session(auth_response)
                st.success("Logged in.")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tabs[1]:
        with st.form("signup_form"):
            full_name = st.text_input("Full name")
            email = st.text_input("Work email")
            department = st.text_input("Department")
            office = st.text_input("Office")
            password = st.text_input("Password", type="password", key="signup_pw")
            signup = st.form_submit_button("Create account", use_container_width=True)

        if signup:
            if not full_name or not email or not password:
                st.error("Full name, email, and password are required.")
                return
            try:
                client = get_base_client()
                client.auth.sign_up(
                    {
                        "email": email,
                        "password": password,
                        "options": {
                            "data": {
                                "full_name": full_name,
                                "department": department,
                                "office": office,
                            }
                        },
                    }
                )
                st.success(
                    "Account created. If email confirmation is enabled in Supabase, confirm the email first."
                )
            except Exception as e:
                st.error(f"Sign-up failed: {e}")


def employee_form_tab(client: Client, profile: dict):
    st.subheader("New C/A Application")
    with st.form("ca_form", clear_on_submit=False):
        st.text_input("Name", value=profile.get("full_name") or "", disabled=True)
        col1, col2 = st.columns(2)
        with col1:
            department = st.text_input("Department", value=profile.get("department") or "")
            office = st.text_input("Office", value=profile.get("office") or "")
            amount = st.number_input("Amount", min_value=0.01, step=100.0, format="%.2f")
        with col2:
            liquidation_due_date = st.date_input(
                "Liquidation due date",
                value=date.today(),
                min_value=date.today(),
            )
            signed_name = st.text_input(
                "Employee signature (type full name)",
                value=profile.get("full_name") or "",
            )

        purpose = st.text_area("Purpose", height=120)
        st.markdown("**Payroll deduction undertaking**")
        st.info(DEFAULT_PLEDGE)
        consent = st.checkbox("I agree to the undertaking above.")

        submitted = st.form_submit_button("Submit application", use_container_width=True)

    if submitted:
        errors = []
        if amount <= 0:
            errors.append("Amount must be greater than 0.")
        if not purpose.strip():
            errors.append("Purpose is required.")
        if not signed_name.strip():
            errors.append("Employee signature is required.")
        if not consent:
            errors.append("You must agree to the payroll deduction undertaking.")

        if errors:
            for error in errors:
                st.error(error)
            return

        try:
            submit_request(
                client,
                profile,
                {
                    "department": department,
                    "office": office,
                    "amount": float(amount),
                    "purpose": purpose.strip(),
                    "liquidation_due_date": liquidation_due_date,
                    "signed_name": signed_name.strip(),
                    "consent": consent,
                },
            )
            st.success("Application submitted.")
            st.session_state.pop("profile_cache", None)
            st.rerun()
        except APIError as e:
            st.error(f"Submit failed: {e.message}")
        except Exception as e:
            st.error(f"Submit failed: {e}")


def my_requests_tab(client: Client, profile: dict):
    st.subheader("My Requests")
    rows = list_my_requests(client, profile["id"])
    if not rows:
        st.info("No requests yet.")
        return

    df = pd.DataFrame(rows)
    display_cols = [
        "created_at",
        "status",
        "amount",
        "purpose",
        "liquidation_due_date",
        "manager_signed_name",
        "finance_signed_name",
        "rejection_reason",
        "liquidation_notes",
    ]
    show_cols = [c for c in display_cols if c in df.columns]
    st.dataframe(df[show_cols], use_container_width=True)

    st.markdown("### Download PDF")
    for idx, row in enumerate(rows):
        file_name = f"cash_advance_{row['id']}.pdf"
        st.download_button(
            label=f"Download PDF: {row['status']} | {row['amount']:,.2f} | {row['liquidation_due_date']}",
            data=request_to_pdf_bytes(row),
            file_name=file_name,
            mime="application/pdf",
            key=f"pdf_{idx}_{row['id']}",
            use_container_width=True,
        )


def manager_tab(client: Client, profile: dict):
    st.subheader("Manager Approval")
    rows = list_manager_requests(client, profile["id"])
    pending = [r for r in rows if r["status"] == "submitted"]

    if not pending:
        st.info("No pending requests for approval.")
        return

    for row in pending:
        with st.expander(
            f"{row['employee_name']} | {row['amount']:,.2f} | due {row['liquidation_due_date']}",
            expanded=False,
        ):
            st.write(f"**Department:** {row.get('department') or '-'}")
            st.write(f"**Office:** {row.get('office') or '-'}")
            st.write(f"**Purpose:** {row.get('purpose') or '-'}")
            st.write(f"**Employee signed:** {row.get('employee_signed_name') or '-'}")
            st.write(f"**Undertaking accepted:** {'Yes' if row.get('payroll_deduction_consent') else 'No'}")
            sign_name = st.text_input(
                f"Manager signature for {row['id']}", value=profile.get("full_name") or "", key=f"mgr_sig_{row['id']}"
            )
            reason = st.text_area(f"Remarks / rejection reason ({row['id']})", key=f"mgr_reason_{row['id']}")
            c1, c2 = st.columns(2)
            if c1.button("Approve", key=f"mgr_ok_{row['id']}", use_container_width=True):
                try:
                    update_request_status(
                        client,
                        row["id"],
                        {
                            "status": "manager_approved",
                            "manager_signed_name": sign_name.strip() or profile.get("full_name"),
                            "manager_signed_at": datetime.utcnow().isoformat(),
                            "rejection_reason": None,
                        },
                    )
                    st.success("Approved by manager.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Approval failed: {e}")
            if c2.button("Reject", key=f"mgr_ng_{row['id']}", use_container_width=True):
                if not reason.strip():
                    st.error("Enter a rejection reason.")
                else:
                    try:
                        update_request_status(
                            client,
                            row["id"],
                            {
                                "status": "rejected",
                                "manager_signed_name": sign_name.strip() or profile.get("full_name"),
                                "manager_signed_at": datetime.utcnow().isoformat(),
                                "rejection_reason": reason.strip(),
                            },
                        )
                        st.success("Rejected.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Reject failed: {e}")


def finance_tab(client: Client, profile: dict):
    st.subheader("Finance Processing")
    rows = list_finance_requests(client)
    actionable = [
        r
        for r in rows
        if r["status"] in ("manager_approved", "finance_approved", "submitted", "liquidated", "payroll_deduction")
    ]

    if not actionable:
        st.info("No finance-side records found.")
        return

    for row in actionable:
        with st.expander(
            f"{row['status']} | {row['employee_name']} | {row['amount']:,.2f}",
            expanded=False,
        ):
            st.write(f"**Purpose:** {row.get('purpose') or '-'}")
            st.write(f"**Due date:** {row.get('liquidation_due_date') or '-'}")
            st.write(f"**Manager signed:** {row.get('manager_signed_name') or '-'}")
            st.write(f"**Consent:** {'Yes' if row.get('payroll_deduction_consent') else 'No'}")
            sign_name = st.text_input(
                f"Finance signature for {row['id']}", value=profile.get("full_name") or "", key=f"fin_sig_{row['id']}"
            )
            notes = st.text_area(f"Finance notes ({row['id']})", key=f"fin_notes_{row['id']}")
            c1, c2, c3 = st.columns(3)

            if c1.button("Finance approve", key=f"fin_ok_{row['id']}", use_container_width=True):
                try:
                    update_request_status(
                        client,
                        row["id"],
                        {
                            "status": "finance_approved",
                            "finance_id": profile["id"],
                            "finance_signed_name": sign_name.strip() or profile.get("full_name"),
                            "finance_signed_at": datetime.utcnow().isoformat(),
                        },
                    )
                    st.success("Finance approved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Finance approval failed: {e}")

            if c2.button("Mark liquidated", key=f"fin_liq_{row['id']}", use_container_width=True):
                try:
                    update_request_status(
                        client,
                        row["id"],
                        {
                            "status": "liquidated",
                            "finance_id": profile["id"],
                            "finance_signed_name": sign_name.strip() or profile.get("full_name"),
                            "finance_signed_at": datetime.utcnow().isoformat(),
                            "liquidation_notes": notes.strip() or "Liquidated by finance.",
                            "liquidated_at": datetime.utcnow().isoformat(),
                        },
                    )
                    st.success("Marked as liquidated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Liquidation update failed: {e}")

            if c3.button("Mark payroll deduction", key=f"fin_pay_{row['id']}", use_container_width=True):
                try:
                    update_request_status(
                        client,
                        row["id"],
                        {
                            "status": "payroll_deduction",
                            "finance_id": profile["id"],
                            "finance_signed_name": sign_name.strip() or profile.get("full_name"),
                            "finance_signed_at": datetime.utcnow().isoformat(),
                            "liquidation_notes": notes.strip() or "Marked for payroll deduction.",
                            "payroll_deduction_marked_at": datetime.utcnow().isoformat(),
                        },
                    )
                    st.success("Marked for payroll deduction.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Payroll deduction update failed: {e}")


def admin_tab(client: Client, profile: dict):
    st.subheader("Admin / Master Data")
    rows = list_profiles(client)
    if not rows:
        st.info("No profiles found.")
        return

    profiles_df = pd.DataFrame(rows)
    st.dataframe(profiles_df, use_container_width=True)

    options = {f"{r['full_name']} ({r['email']})": r["id"] for r in rows}

    with st.form("admin_profile_update"):
        target_label = st.selectbox("Employee", list(options.keys()))
        role = st.selectbox("Role", ROLE_OPTIONS)
        manager_label = st.selectbox("Manager", ["<None>"] + list(options.keys()))
        office = st.text_input("Office override")
        department = st.text_input("Department override")
        is_active = st.checkbox("Is active", value=True)
        submitted = st.form_submit_button("Update profile", use_container_width=True)

    if submitted:
        manager_id = None if manager_label == "<None>" else options[manager_label]
        fields = {
            "role": role,
            "manager_id": manager_id,
            "is_active": is_active,
        }
        if office.strip():
            fields["office"] = office.strip()
        if department.strip():
            fields["department"] = department.strip()
        try:
            update_profile(client, options[target_label], fields)
            st.success("Profile updated.")
            st.session_state.pop("profile_cache", None)
            st.rerun()
        except Exception as e:
            st.error(f"Profile update failed: {e}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    if "access_token" not in st.session_state:
        st.session_state["access_token"] = None
    if "refresh_token" not in st.session_state:
        st.session_state["refresh_token"] = None

    handle_oauth_callback()
    user = current_user()
    if not user:
        login_screen()
        return

    client = get_client()
    try:
        profile = fetch_profile(client)
    except Exception as e:
        st.error(f"Could not load profile. Check your schema/RLS/profile trigger. Details: {e}")
        return

    if not profile:
        st.error("No profile found for this user.")
        return

    show_header(profile)

    tabs = ["New Request", "My Requests"]
    if profile["role"] in ["manager", "admin"]:
        tabs.append("Manager")
    if profile["role"] in ["finance", "admin"]:
        tabs.append("Finance")
    if profile["role"] == "admin":
        tabs.append("Admin")

    rendered_tabs = st.tabs(tabs)
    idx = 0
    with rendered_tabs[idx]:
        employee_form_tab(client, profile)
    idx += 1
    with rendered_tabs[idx]:
        my_requests_tab(client, profile)
    idx += 1

    if profile["role"] in ["manager", "admin"]:
        with rendered_tabs[idx]:
            manager_tab(client, profile)
        idx += 1
    if profile["role"] in ["finance", "admin"]:
        with rendered_tabs[idx]:
            finance_tab(client, profile)
        idx += 1
    if profile["role"] == "admin":
        with rendered_tabs[idx]:
            admin_tab(client, profile)

    st.divider()
    st.caption(
        "Setup note: use SUPABASE_URL and SUPABASE_ANON_KEY in Streamlit secrets. "
        "Create users first, then assign role / manager_id from the Admin tab or directly in Supabase."
    )


if __name__ == "__main__":
    try:
        main()
    except APIError as e:
        st.error(f"Supabase API error: {e.message}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")

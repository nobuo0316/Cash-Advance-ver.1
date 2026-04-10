import streamlit as st
from supabase import create_client, Client
from datetime import date

st.set_page_config(page_title="Cash Advance Application", page_icon="💼", layout="wide")

# ---------- Config ----------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

# Streamlit native Google login requires .streamlit/secrets.toml:
# [auth]
# redirect_uri = "https://avg-salary-at-manila-ffmzzkydywu9cnqwks5za9.streamlit.app/oauth2callback"
# cookie_secret = "long-random-string"
# client_id = "google-client-id"
# client_secret = "google-client-secret"
# server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

ALLOWED_DOMAIN = st.secrets.get("ALLOWED_GOOGLE_DOMAIN", "")  # e.g. "yourcompany.com"


# ---------- Auth helpers ----------
def login_screen() -> None:
    st.title("Cash Advance Application")
    st.subheader("Please log in with Google")
    st.button("Log in with Google", on_click=st.login, use_container_width=True)
    st.info("After login, Streamlit will return you to this app automatically.")


def ensure_profile() -> dict | None:
    if not st.user.is_logged_in:
        return None

    email = st.user.get("email", "")
    name = st.user.get("name", "") or email.split("@")[0]
    if not email:
        st.error("Google account email was not returned.")
        return None

    if ALLOWED_DOMAIN and email.split("@")[-1].lower() != ALLOWED_DOMAIN.lower():
        st.error(f"This app only allows @{ALLOWED_DOMAIN} accounts.")
        st.button("Log out", on_click=st.logout)
        st.stop()

    try:
        existing = (
            supabase.table("profiles")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
        )

        if existing.data:
            return existing.data[0]

        insert_payload = {
            "email": email,
            "full_name": name,
            "department": "",
            "office": "",
            "role": "employee",
            "is_active": True,
        }
        created = supabase.table("profiles").insert(insert_payload).execute()
        if created.data:
            return created.data[0]

        refreshed = (
            supabase.table("profiles")
            .select("*")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        return refreshed.data[0] if refreshed.data else None

    except Exception as e:
        st.error(f"Failed to load/create profile: {e}")
        return None


# ---------- UI helpers ----------
def sidebar_user(profile: dict) -> None:
    with st.sidebar:
        st.markdown("### User")
        st.write(profile.get("full_name", ""))
        st.write(profile.get("email", ""))
        st.write(f"Role: {profile.get('role', '')}")
        if profile.get("department"):
            st.write(f"Department: {profile.get('department')}")
        if profile.get("office"):
            st.write(f"Office: {profile.get('office')}")
        st.button("Log out", on_click=st.logout, use_container_width=True)


def my_requests(profile: dict) -> None:
    st.subheader("My Requests")
    try:
        rows = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("employee_email", profile["email"])
            .order("created_at", desc=True)
            .execute()
        )
        data = rows.data or []
        if not data:
            st.info("No requests yet.")
            return
        st.dataframe(data, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error(f"Could not load requests: {e}")


def new_request_form(profile: dict) -> None:
    st.subheader("New Cash Advance Request")

    with st.form("ca_form", clear_on_submit=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            name = st.text_input("Name", value=profile.get("full_name", ""))
        with col2:
            department = st.text_input("Department", value=profile.get("department", ""))
        with col3:
            office = st.text_input("Office", value=profile.get("office", ""))

        amount = st.number_input("Amount", min_value=0.0, step=100.0, format="%.2f")
        purpose = st.text_area("Purpose")
        liquidation_due_date = st.date_input("Liquidation Due Date", value=date.today())

        st.markdown("**Undertaking**")
        undertaking = st.checkbox(
            "I agree that if I fail to liquidate or return the amount by the due date, "
            "the company may deduct the outstanding amount from my salary subject to company rules and applicable laws."
        )

        submitted = st.form_submit_button("Submit Request", use_container_width=True)

    if submitted:
        if not undertaking:
            st.error("You must agree to the undertaking.")
            return
        if amount <= 0:
            st.error("Amount must be greater than zero.")
            return
        if not purpose.strip():
            st.error("Purpose is required.")
            return

        payload = {
            "employee_email": profile["email"],
            "employee_name": name.strip(),
            "department": department.strip(),
            "office": office.strip(),
            "amount": amount,
            "purpose": purpose.strip(),
            "liquidation_due_date": str(liquidation_due_date),
            "payroll_deduction_consent": True,
            "status": "submitted",
        }

        try:
            supabase.table("cash_advance_requests").insert(payload).execute()
            st.success("Request submitted.")
            st.rerun()
        except Exception as e:
            st.error(f"Submit failed: {e}")


def manager_queue(profile: dict) -> None:
    st.subheader("Manager Approval Queue")
    st.caption("This view expects your schema/app logic to map managers to requests.")
    try:
        rows = (
            supabase.table("cash_advance_requests")
            .select("*")
            .eq("status", "submitted")
            .order("created_at", desc=True)
            .execute()
        )
        data = rows.data or []
        if not data:
            st.info("No pending requests.")
            return

        for row in data:
            with st.expander(f"{row.get('employee_name')} | {row.get('amount')} | {row.get('purpose')[:40]}"):
                st.write(row)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Approve", key=f"mgr_appr_{row['id']}", use_container_width=True):
                        try:
                            supabase.table("cash_advance_requests").update(
                                {"status": "manager_approved"}
                            ).eq("id", row["id"]).execute()
                            st.success("Approved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Approve failed: {e}")
                with c2:
                    if st.button("Reject", key=f"mgr_rej_{row['id']}", use_container_width=True):
                        try:
                            supabase.table("cash_advance_requests").update(
                                {"status": "rejected"}
                            ).eq("id", row["id"]).execute()
                            st.success("Rejected.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Reject failed: {e}")
    except Exception as e:
        st.error(f"Could not load manager queue: {e}")


def finance_queue(profile: dict) -> None:
    st.subheader("Finance Queue")
    try:
        rows = (
            supabase.table("cash_advance_requests")
            .select("*")
            .in_("status", ["manager_approved", "finance_approved"])
            .order("created_at", desc=True)
            .execute()
        )
        data = rows.data or []
        if not data:
            st.info("No finance items.")
            return

        for row in data:
            with st.expander(f"{row.get('employee_name')} | {row.get('status')} | {row.get('amount')}"):
                st.write(row)
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Mark Finance Approved", key=f"fin_ok_{row['id']}", use_container_width=True):
                        try:
                            supabase.table("cash_advance_requests").update(
                                {"status": "finance_approved"}
                            ).eq("id", row["id"]).execute()
                            st.success("Updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Update failed: {e}")
                with c2:
                    if st.button("Mark Payroll Deduction", key=f"fin_pay_{row['id']}", use_container_width=True):
                        try:
                            supabase.table("cash_advance_requests").update(
                                {"status": "payroll_deduction"}
                            ).eq("id", row["id"]).execute()
                            st.success("Updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Update failed: {e}")
    except Exception as e:
        st.error(f"Could not load finance queue: {e}")


# ---------- Main ----------
def main() -> None:
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

    role = (profile.get("role") or "employee").lower()

    tabs = ["Request Form", "My Requests"]
    if role in {"manager", "admin"}:
        tabs.append("Manager Queue")
    if role in {"finance", "admin"}:
        tabs.append("Finance Queue")

    tab_objs = st.tabs(tabs)

    idx = 0
    with tab_objs[idx]:
        new_request_form(profile)
    idx += 1

    with tab_objs[idx]:
        my_requests(profile)
    idx += 1

    if role in {"manager", "admin"}:
        with tab_objs[idx]:
            manager_queue(profile)
        idx += 1

    if role in {"finance", "admin"}:
        with tab_objs[idx]:
            finance_queue(profile)


if __name__ == "__main__":
    main()

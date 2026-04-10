import streamlit as st
from supabase import create_client, Client
from datetime import date

st.set_page_config(page_title="Cash Advance App", page_icon="💼", layout="wide")

# =========================
# Secrets
# =========================
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]  # 🔥ここ重要
ALLOWED_DOMAIN = st.secrets.get("ALLOWED_GOOGLE_DOMAIN", "")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# Auth
# =========================
def login_screen():
    st.title("Cash Advance Application")
    st.button("Log in with Google", on_click=st.login, use_container_width=True)

def logout():
    st.logout()

# =========================
# Profile
# =========================
def ensure_profile():
    email = st.user.get("email")
    name = st.user.get("name")

    if not email:
        st.error("Email not found")
        st.stop()

    # ドメイン制限
    if ALLOWED_DOMAIN:
        if email.split("@")[1] != ALLOWED_DOMAIN:
            st.error("Not allowed domain")
            st.stop()

    # 既存確認
    res = supabase.table("profiles").select("*").eq("email", email).execute()

    if res.data:
        return res.data[0]

    # 新規作成
    new_user = {
        "email": email,
        "full_name": name,
        "role": "employee",
        "is_active": True
    }

    supabase.table("profiles").insert(new_user).execute()

    return new_user

# =========================
# UI
# =========================
def sidebar(profile):
    with st.sidebar:
        st.write(profile["full_name"])
        st.write(profile["email"])
        st.write(f"Role: {profile['role']}")
        st.button("Logout", on_click=logout)

# =========================
# Employee
# =========================
def create_request(profile):
    st.subheader("New Request")

    amount = st.number_input("Amount", min_value=0.0)
    purpose = st.text_area("Purpose")
    due = st.date_input("Liquidation Date", value=date.today())

    if st.button("Submit"):
        if amount <= 0:
            st.error("Invalid amount")
            return

        payload = {
            "employee_email": profile["email"],
            "employee_name": profile["full_name"],
            "amount": amount,
            "purpose": purpose,
            "liquidation_due_date": str(due),
            "status": "submitted"
        }

        supabase.table("cash_advance_requests").insert(payload).execute()

        st.success("Submitted")

def my_requests(profile):
    st.subheader("My Requests")

    res = supabase.table("cash_advance_requests") \
        .select("*") \
        .eq("employee_email", profile["email"]) \
        .execute()

    st.dataframe(res.data)

# =========================
# Manager
# =========================
def manager_view():
    st.subheader("Manager Approval")

    res = supabase.table("cash_advance_requests") \
        .select("*") \
        .eq("status", "submitted") \
        .execute()

    for row in res.data:
        st.write(row)

        if st.button(f"Approve {row['id']}"):
            supabase.table("cash_advance_requests") \
                .update({"status": "manager_approved"}) \
                .eq("id", row["id"]).execute()

        if st.button(f"Reject {row['id']}"):
            supabase.table("cash_advance_requests") \
                .update({"status": "rejected"}) \
                .eq("id", row["id"]).execute()

# =========================
# Finance
# =========================
def finance_view():
    st.subheader("Finance")

    res = supabase.table("cash_advance_requests") \
        .select("*") \
        .eq("status", "manager_approved") \
        .execute()

    for row in res.data:
        st.write(row)

        if st.button(f"Finance OK {row['id']}"):
            supabase.table("cash_advance_requests") \
                .update({"status": "finance_approved"}) \
                .eq("id", row["id"]).execute()

# =========================
# Admin
# =========================
def admin_users():
    st.subheader("User Management")

    res = supabase.table("profiles").select("*").execute()

    for user in res.data:
        st.write(user)

        role = st.selectbox(
            f"Role {user['email']}",
            ["employee", "manager", "finance", "admin"],
            index=["employee","manager","finance","admin"].index(user["role"])
        )

        if st.button(f"Save {user['id']}"):
            supabase.table("profiles") \
                .update({"role": role}) \
                .eq("id", user["id"]).execute()

# =========================
# Main
# =========================
def main():

    if not st.user.is_logged_in:
        login_screen()
        st.stop()

    profile = ensure_profile()

    sidebar(profile)

    st.title("Cash Advance System")

    role = profile["role"]

    tab_list = ["Request", "My Requests"]

    if role in ["manager", "admin"]:
        tab_list.append("Manager")

    if role in ["finance", "admin"]:
        tab_list.append("Finance")

    if role == "admin":
        tab_list.append("Admin")

    tabs = st.tabs(tab_list)

    idx = 0

    with tabs[idx]:
        create_request(profile)
    idx += 1

    with tabs[idx]:
        my_requests(profile)
    idx += 1

    if role in ["manager", "admin"]:
        with tabs[idx]:
            manager_view()
        idx += 1

    if role in ["finance", "admin"]:
        with tabs[idx]:
            finance_view()
        idx += 1

    if role == "admin":
        with tabs[idx]:
            admin_users()

if __name__ == "__main__":
    main()

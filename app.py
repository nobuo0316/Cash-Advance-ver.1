import streamlit as st
from supabase import create_client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

APP_URL = "https://avg-salary-at-manila-ffmzzkydywu9cnqwks5za9.streamlit.app/"

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# =========================
# 🔥 重要：現在ユーザー取得
# =========================
def get_user():
    try:
        res = supabase.auth.get_user()
        return res.user
    except:
        return None

# =========================
# Googleログイン
# =========================
def google_login():
    res = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": APP_URL
        }
    })
    st.link_button("👉 Continue with Google", res.url)

# =========================
# ログアウト
# =========================
def logout():
    supabase.auth.sign_out()
    st.rerun()

# =========================
# メイン
# =========================
def main():

    user = get_user()

    if not user:
        st.title("Cash Advance App")

        if st.button("Sign in with Google"):
            google_login()

        st.stop()

    # ✅ ログイン成功
    st.success(f"Logged in: {user.email}")

    if st.button("Logout"):
        logout()

if __name__ == "__main__":
    main()

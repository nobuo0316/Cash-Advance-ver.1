import streamlit as st

st.set_page_config(page_title="Login Test", page_icon="🔐")

if not st.user.is_logged_in:
    st.title("Login Test")
    st.button("Log in with Google", on_click=st.login, use_container_width=True)
    st.stop()

st.success(f"Logged in: {st.user.get('email', '')}")
st.write(dict(st.user))
st.button("Log out", on_click=st.logout, use_container_width=True)

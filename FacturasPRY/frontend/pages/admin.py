import streamlit as st
import requests

st.set_page_config(page_title="Admin", layout="wide")

# 🔐 Protección
if "user" not in st.session_state:
    st.switch_page("main.py")

if st.session_state["user"]["rol"] != 1:
    st.error("No tienes permisos")
    st.stop()

st.title("👨‍💼 Gestión de Usuarios")

BASE_URL = "http://localhost:8000"


# -------------------------------
# 📥 Cargar usuarios
# -------------------------------
def load_users():
    try:
        response = requests.get(f"{BASE_URL}/users")
        if response.status_code == 200:
            return response.json()
        return []
    except:
        return []


users = load_users()


# -------------------------------
# ➕ Crear usuario
# -------------------------------
with st.expander("➕ Crear usuario"):
    with st.form("create_user"):
        nombre = st.text_input("Nombre")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if st.form_submit_button("Crear"):
            requests.post(f"{BASE_URL}/users", json={
                "nombre": nombre,
                "email": email,
                "password": password,
                "rol": 2
            })
            st.rerun()


# -------------------------------
# 📊 Lista
# -------------------------------
for u in users:
    with st.expander(f"{u['nombre']} ({u['email']})"):

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Eliminar", key=u["id"]):
                requests.delete(f"{BASE_URL}/users/{u['id']}")
                st.rerun()

        with col2:
            new_name = st.text_input("Nuevo nombre", value=u["nombre"], key=f"name{u['id']}")
            if st.button("Actualizar", key=f"upd{u['id']}"):
                requests.put(f"{BASE_URL}/users/{u['id']}", json={
                    "nombre": new_name,
                    "email": u["email"]
                })
                st.rerun()
import streamlit as st


def cerrar_sesion():

    for key in [
        "access_token",
        "rol",
        "IdArea",
        "usuario_id",
        "nombre"
    ]:
        st.session_state.pop(key, None)

    st.switch_page("main.py")


def mostrar_sidebar():

    st.sidebar.title("🏢 Sistema Presupuestal")

    nombre = st.session_state.get("nombre", "")
    rol = st.session_state.get("rol")

    st.sidebar.subheader(f"Usuario: {nombre}")

    roles = {
        1: "👑 Admin",
        2: "📊 Gestor",
        3: "👤 Usuario"
    }

    st.sidebar.write(
        roles.get(rol, "Rol desconocido")
    )

    st.sidebar.divider()

    if st.sidebar.button(
        "🔓 Cerrar Sesión",
        use_container_width=True
    ):
        cerrar_sesion()
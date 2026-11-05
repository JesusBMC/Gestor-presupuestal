import streamlit as st

from utils.auth import mostrar_sidebar

from api.client import (
    get_roles,
    get_areas,
    crear_usuario
)

mostrar_sidebar()
st.set_page_config(
    page_title="Gestión de Usuarios",
    layout="wide"
)


# ============================================================
# VALIDAR SESIÓN
# ============================================================

if not st.session_state.get("access_token"):

    st.error("❌ No hay una sesión activa.")
    st.stop()


# ============================================================
# VALIDAR ADMIN
# ============================================================

if st.session_state.get("rol") != 1:

    st.error(
        "❌ No tienes permisos para acceder a esta sección."
    )

    st.stop()


# ============================================================
# TÍTULO
# ============================================================

st.title("👥 Gestión de Usuarios")

st.write(
    "Crea nuevos usuarios y asígnales un rol y un área."
)


# ============================================================
# CARGAR ROLES
# ============================================================

success_roles, roles = get_roles()

if not success_roles:

    st.error("❌ No fue posible cargar los roles.")
    st.write(roles)
    st.stop()


# ============================================================
# CARGAR ÁREAS
# ============================================================

success_areas, areas = get_areas()

if not success_areas:

    st.error("❌ No fue posible cargar las áreas.")
    st.write(areas)
    st.stop()


# ============================================================
# DICCIONARIOS
# ============================================================

roles_dict = {
    rol["IdRol"]: rol["NombreRol"]
    for rol in roles
}


areas_dict = {
    area["IdArea"]: area["Nombre"]
    for area in areas
}


# ============================================================
# FORMULARIO
# ============================================================

st.subheader("➕ Crear usuario")


with st.form("form_crear_usuario"):

    nombre = st.text_input(
        "Nombre",
        placeholder="Nombre completo"
    )

    email = st.text_input(
        "Correo institucional",
        placeholder="usuario@bolsamercantil.com.co"
    )

    password = st.text_input(
        "Contraseña",
        type="password"
    )

    password_confirm = st.text_input(
        "Confirmar contraseña",
        type="password"
    )

    col1, col2 = st.columns(2)

    with col1:

        rol_id = st.selectbox(
            "Rol",
            options=list(roles_dict.keys()),
            format_func=lambda x: roles_dict[x]
        )

    with col2:

        area_id = st.selectbox(
            "Área",
            options=list(areas_dict.keys()),
            format_func=lambda x: areas_dict[x]
        )

    crear = st.form_submit_button(
        "Crear usuario",
        use_container_width=True
    )


# ============================================================
# CREAR
# ============================================================

if crear:

    nombre = nombre.strip()
    email = email.strip().lower()

    if not nombre:

        st.warning("⚠️ Debes ingresar el nombre.")

    elif not email:

        st.warning("⚠️ Debes ingresar el correo.")

    elif not email.endswith("@bolsamercantil.com.co"):

        st.warning(
            "⚠️ El correo debe terminar en "
            "@bolsamercantil.com.co"
        )

    elif not password:

        st.warning("⚠️ Debes ingresar una contraseña.")

    elif password != password_confirm:

        st.warning("⚠️ Las contraseñas no coinciden.")

    else:

        success, response = crear_usuario(
            nombre=nombre,
            email=email,
            password=password,
            id_area=area_id,
            id_rol=rol_id,
            activo=True
        )

        if success:

            st.success(
                f"✅ Usuario {nombre} creado correctamente."
            )

            st.rerun()

        else:

            st.error(
                "❌ No fue posible crear el usuario."
            )

            st.write(response)
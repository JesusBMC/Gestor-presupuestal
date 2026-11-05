import streamlit as st

from api.client import (
    get_areas,
    crear_area,
    editar_area,
    eliminar_area
)


st.set_page_config(
    page_title="Gestión de Áreas",
    layout="wide"
)


# ============================================================
# VALIDAR ADMIN
# ============================================================

if (
    not st.session_state.get("access_token")
    or st.session_state.get("rol") != 1
):

    st.error("❌ Solo Administradores pueden acceder")
    st.stop()


# ============================================================
# TÍTULO
# ============================================================

st.title("🏢 Gestión de Áreas")

st.write(
    "Administra las áreas disponibles en el sistema."
)


# ============================================================
# LISTAR ÁREAS
# ============================================================

success, areas = get_areas()

if not success:

    st.error("❌ No fue posible cargar las áreas.")
    st.write(areas)
    st.stop()


if areas:

    st.subheader("📋 Áreas disponibles")

    datos_tabla = []

    for area in areas:

        datos_tabla.append({
            "ID": area["IdArea"],
            "Nombre": area["Nombre"],
            "Descripción": area.get("Descripcion", ""),
            "Estado": "Activo" if area["activo"] == -1 else "Inactivo"
        })

    st.dataframe(
        datos_tabla,
        use_container_width=True,
        hide_index=True
    )

else:

    st.info("ℹ️ No hay áreas registradas todavía.")


st.divider()


# ============================================================
# CREAR ÁREA
# ============================================================

st.subheader("➕ Crear Área")

col1, col2 = st.columns(2)

with col1:

    nueva_area_nombre = st.text_input(
        "Nombre",
        placeholder="Ej. Tecnología",
        key="crear_area_nombre"
    )

with col2:

    nueva_area_descripcion = st.text_input(
        "Descripción",
        placeholder="Descripción del área",
        key="crear_area_descripcion"
    )


if st.button(
    "✅ Crear Área",
    use_container_width=True,
    key="crear_area_boton"
):

    nombre = nueva_area_nombre.strip()
    descripcion = nueva_area_descripcion.strip()

    if not nombre:

        st.warning("⚠️ Ingresa un nombre para el área.")

    else:

        success, response = crear_area(
            nombre,
            descripcion
        )

        if success:

            st.success(
                "✅ Área creada correctamente."
            )

            st.rerun()

        else:

            st.error(
                "❌ No fue posible crear el área."
            )

            st.write(response)


# ============================================================
# EDITAR ÁREA
# ============================================================

if areas:

    st.divider()

    st.subheader("✏️ Editar Área")

    area_sel = st.selectbox(
        "Selecciona un área",
        options=[area["IdArea"] for area in areas],
        format_func=lambda x: next(
            area["Nombre"]
            for area in areas
            if area["IdArea"] == x
        ),
        key="editar_area_selector"
    )

    area_actual = next(
        area
        for area in areas
        if area["IdArea"] == area_sel
    )

    col1, col2 = st.columns(2)

    with col1:

        edit_nombre = st.text_input(
            "Nombre",
            value=area_actual["Nombre"],
            key="editar_area_nombre"
        )

    with col2:

        edit_descripcion = st.text_input(
            "Descripción",
            value=area_actual.get("Descripcion", ""),
            key="editar_area_descripcion"
        )

    edit_activo = st.checkbox(
        "Área activa",
        value=area_actual["activo"] == -1,
        key="editar_area_activo"
    )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "💾 Guardar Cambios",
            use_container_width=True,
            key="editar_area_guardar"
        ):

            nombre = edit_nombre.strip()
            descripcion = edit_descripcion.strip()

            if not nombre:

                st.warning(
                    "⚠️ El nombre no puede estar vacío."
                )

            else:

                success, response = editar_area(
                    area_sel,
                    nombre,
                    descripcion,
                    edit_activo
                )

                if success:

                    st.success(
                        "✅ Área actualizada correctamente."
                    )

                    st.rerun()

                else:

                    st.error(
                        "❌ No fue posible actualizar el área."
                    )

                    st.write(response)

    with col2:

        if st.button(
            "🗑️ Desactivar Área",
            use_container_width=True,
            key="editar_area_eliminar"
        ):

            success, response = eliminar_area(
                area_sel
            )

            if success:

                st.success(
                    "✅ Área desactivada correctamente."
                )

                st.rerun()

            else:

                st.error(
                    "❌ No fue posible desactivar el área."
                )

                st.write(response)
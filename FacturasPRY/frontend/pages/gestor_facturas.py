import streamlit as st
from api import client
from utils.auth import mostrar_sidebar


mostrar_sidebar()
st.set_page_config(page_title="Gestión de Facturas", layout="wide")
st.title("📋 Gestión de Facturas")

id_area = st.session_state.get("IdArea")

if not id_area:
    st.error("No hay área en sesión")
    st.stop()

# =========================================================
# 🔹 DATA
# =========================================================

ok, facturas = client.get_facturas_area(id_area)
ok_v, verticales = client.get_verticales(id_area)
ok_a, agrupaciones = client.get_agrupaciones(id_area)

if not ok or not ok_v or not ok_a:
    st.error("Error cargando datos")
    st.stop()

st.caption(f"{len(facturas)} facturas encontradas")

# 🔹 TABLA
st.dataframe(facturas, width="stretch")

# =========================================================
# 🔹 MAPEO (🔥 CORREGIDO)
# =========================================================

# 👇 AJUSTADO A TU BACKEND
vertical_dict = {v["Nombre"]: v["IdVertical"] for v in verticales}
vertical_reverse = {v["IdVertical"]: v["Nombre"] for v in verticales}

agrup_dict = {a["Nombre"]: a["IdAgrupacion"] for a in agrupaciones}
agrup_reverse = {a["IdAgrupacion"]: a["Nombre"] for a in agrupaciones}

# =========================================================
# ✏️ EDICIÓN
# =========================================================

st.divider()
st.subheader("✏️ Editar factura")

factura_sel = st.selectbox(
    "Selecciona una factura",
    facturas,
    format_func=lambda x: f"{x['NumFactura']} | ID {x['Id']}"
)

col1, col2 = st.columns(2)

# =========================================================
# 🔹 IZQUIERDA
# =========================================================

with col1:
    # MES
    mes_actual = factura_sel.get("Mes") or 1
    mes = st.selectbox(
        "Mes",
        list(range(1, 13)),
        index=mes_actual - 1
    )

    # TIPO
    tipo_actual = factura_sel.get("Tipo") or "CAPEX"
    tipo = st.selectbox(
        "Tipo",
        ["CAPEX", "OPEX"],
        index=0 if tipo_actual == "CAPEX" else 1
    )

    # PERIODICIDAD
    periodicidad_opciones = [7, 15, 30, 60, 90, 180, 365]

    periodicidad_actual = factura_sel.get("Periodicidad")

    periodicidad = st.selectbox(
        "Periodicidad (días)",
        periodicidad_opciones,
        index=periodicidad_opciones.index(periodicidad_actual)
        if periodicidad_actual in periodicidad_opciones
        else 2  # default = 30
    )

# =========================================================
# 🔹 DERECHA
# =========================================================

with col2:
    # 🔹 VERTICAL
    vertical_actual_id = factura_sel.get("IdVertical")
    vertical_actual_nombre = vertical_reverse.get(vertical_actual_id)

    lista_verticales = list(vertical_dict.keys())

    vertical_nombre = st.selectbox(
        "Vertical",
        lista_verticales,
        index=lista_verticales.index(vertical_actual_nombre)
        if vertical_actual_nombre in lista_verticales
        else 0
    )

    id_vertical = vertical_dict[vertical_nombre]

    # 🔹 AGRUPACIÓN
    agrup_actual_id = factura_sel.get("IdAgrupacion")
    agrup_actual_nombre = agrup_reverse.get(agrup_actual_id)

    lista_agrup = list(agrup_dict.keys())

    agrup_nombre = st.selectbox(
        "Agrupación",
        lista_agrup,
        index=lista_agrup.index(agrup_actual_nombre)
        if agrup_actual_nombre in lista_agrup
        else 0
    )

    id_agrupacion = agrup_dict[agrup_nombre]

# =========================================================
# 💾 GUARDAR
# =========================================================

if st.button("💾 Guardar cambios"):
    ok, resp = client.actualizar_factura(
        factura_sel["Id"],
        {
            "Mes": mes,
            "Tipo": tipo,
            "IdVertical": id_vertical,
            "IdAgrupacion": id_agrupacion,
            "Periodicidad": periodicidad
        }
    )

    if ok:
        st.success("Factura actualizada")
        st.rerun()
    else:
        st.error(resp)
import streamlit as st

import pandas as pd
 
from api.client import get_facturas_pendientes, simular_presupuesto
 
st.set_page_config(page_title="Simulación", layout="wide")
 
if not st.session_state.get("access_token"):

    st.error("❌ No autenticado")

    st.stop()
 
st.title("🧠 Simulador de Presupuesto")
 
id_area = st.session_state.get("IdArea")
 
if not id_area:

    st.error("❌ Tu usuario no tiene un área asignada")

    st.stop()
 
MESES_NOMBRE = {

    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",

    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"

}
 
 
def cop(valor):

    if valor is None:

        return "-"

    return f"${valor:,.0f}".replace(",", ".")
 
 
# ============================================================

# TRAER FACTURAS PENDIENTES

# ============================================================

ok, facturas = get_facturas_pendientes(id_area)
 
if not ok or not facturas:

    st.info("✅ No hay facturas pendientes para simular")

    st.stop()
 
# ============================================================

# TABLA DE SELECCIÓN

# ============================================================

st.subheader("Selecciona Facturas para Simular")
 
selected_ids = []
 
col_num, col_fecha, col_monto, col_estado, col_check = st.columns([1, 2, 2, 1.5, 1])

with col_num: st.write("**Factura**")

with col_fecha: st.write("**Fecha**")

with col_monto: st.write("**Monto**")

with col_estado: st.write("**Estado**")

with col_check: st.write("**Sel.**")
 
st.divider()
 
for factura in facturas:

    col_num, col_fecha, col_monto, col_estado, col_check = st.columns([1, 2, 2, 1.5, 1])

    with col_num:

        st.write(factura['NumFactura'])

    with col_fecha:

        st.write(factura['FechaRecepcion'][:10] if factura.get('FechaRecepcion') else "-")

    with col_monto:

        st.write(cop(factura['ValorCOP_M1']))

    with col_estado:

        st.write(factura['Estado'])

    with col_check:

        if st.checkbox("✓", key=f"cb_{factura['Id']}"):

            selected_ids.append(factura['Id'])
 
st.divider()
 
# ============================================================

# BOTÓN SIMULAR

# ============================================================

if st.button("🧮 Simular Aprobación", type="primary", use_container_width=True):

    if not selected_ids:

        st.warning("⚠️ Selecciona al menos una factura")

    else:

        ok, resultado = simular_presupuesto(selected_ids, id_area)
 
        if not ok:

            st.error(f"❌ Error al simular: {resultado.get('error', 'desconocido')}")

            st.stop()
 
        # ========================================================

        # 1) ENCABEZADO DE SUGERENCIA — lo primero que se lee

        # ========================================================

        sugerencia = resultado["sugerencia"]

        razones = resultado["razones"]
 
        estilos = {

            "bloquear": ("🔴", "#FF4444", "NO APROBAR — supera el presupuesto General"),

            "revisar": ("🟠", "#FF8800", "REVISAR ANTES DE APROBAR"),

            "aprobar_con_precaucion": ("🟡", "#FFAA00", "APROBAR CON PRECAUCIÓN"),

            "aprobar": ("🟢", "#44AA44", "SE PUEDE APROBAR"),

        }

        icono, color, texto = estilos.get(sugerencia, ("⚪", "#888888", sugerencia))
 
        st.markdown(f"""
<div style="background-color: {color}22; border-left: 6px solid {color}; border-radius: 8px; padding: 18px 20px;">
<div style="font-size: 20px; font-weight: 700;">{icono} {texto}</div>
</div>

""", unsafe_allow_html=True)
 
        with st.container():

            for r in razones:

                st.write(f"• {r}")
 
        st.divider()
 
        # ========================================================

        # 2) IMPACTO EN PRESUPUESTO GENERAL (techo duro anual)

        # ========================================================

        st.subheader("📊 Impacto en Presupuesto General")
 
        for g in resultado["general"]:

            cols = st.columns(4)

            cols[0].metric(f"General {g['Ano']}", cop(g["PresupuestoGeneral"]))

            cols[1].metric("Gastado Actual", cop(g["GastadoActual"]))

            cols[2].metric("Facturas Seleccionadas", cop(g["FacturasSeleccionadas"]))

            cols[3].metric("Nuevo Gastado", cop(g["NuevoGastado"]),

                            delta="EXCEDE" if g["Excede"] else None,

                            delta_color="inverse")
 
            pct = g["Porcentaje"]

            barra_color = "#FF4444" if g["Excede"] else "#44AA44"

            st.markdown(f"""
<div style="background-color: #ddd; border-radius: 5px; height: 24px; overflow: hidden; margin-bottom: 4px;">
<div style="background-color: {barra_color}; height: 100%; width: {min(pct, 100)}%;"></div>
</div>
<div style="font-size: 13px; margin-bottom: 16px;">{pct:.1f}% del presupuesto General {g['Ano']} · Disponible: {cop(g['Disponible'])}</div>

""", unsafe_allow_html=True)
 
        st.divider()
 
        # ========================================================

        # 3) IMPACTO POR MES (esto decide la alerta)

        # ========================================================

        st.subheader("📅 Impacto por Mes")

        st.caption("El presupuesto mensual es el que determina la alerta operativa (🟢🟡🔴).")
 
        meses_data = []

        for m in resultado["meses"]:

            nombre_mes = MESES_NOMBRE.get(m["Mes"], m["Mes"])

            if m["Alerta"] == "sin_dato":

                estado_txt = "⚪ Sin presupuesto mensual asignado"

            elif m["Alerta"] == "critico":

                estado_txt = "🔴 Crítico"

            elif m["Alerta"] == "warning":

                estado_txt = "🟡 Advertencia"

            else:

                estado_txt = "🟢 OK"
 
            meses_data.append({

                "Mes": f"{nombre_mes} {m['Ano']}",

                "Presupuesto Mensual": cop(m["PresupuestoMensual"]),

                "Gastado Actual": cop(m["GastadoActual"]),

                "Facturas Simuladas": cop(m["FacturasSeleccionadas"]),

                "Nuevo Gastado": cop(m["NuevoGastado"]),

                "% Uso": f"{m['Porcentaje']:.1f}%" if m["Porcentaje"] is not None else "-",

                "Estado": estado_txt

            })
 
        st.dataframe(pd.DataFrame(meses_data), use_container_width=True, hide_index=True)
 
        st.divider()
 
        # ========================================================

        # 4) DESGLOSE POR VERTICAL — informativo, sin alertas

        # ========================================================

        st.subheader("🏷️ Desglose por Vertical")

        st.caption("Solo informativo — no todas las verticales tienen presupuesto asignado todavía.")
 
        vert_data = [{"Vertical": v["Vertical"], "Monto": cop(v["Monto"])}

                     for v in resultado["desgloseVertical"]]

        st.dataframe(pd.DataFrame(vert_data), use_container_width=True, hide_index=True)
 
        st.divider()
 
        # ========================================================

        # 5) PROYECCIÓN DE TENDENCIA

        # ========================================================

        proyeccion = resultado.get("proyeccion")

        if proyeccion:

            st.subheader("📈 Proyección de Tendencia")

            st.caption(

                f"Con el ritmo de gasto acumulado a {MESES_NOMBRE.get(proyeccion['MesActual'])} "

                f"más estas facturas, así se vería el cierre del año {proyeccion['Ano']}:"

            )
 
            cols = st.columns(3)

            cols[0].metric("Promedio Mensual", cop(proyeccion["PromedioMensual"]))

            cols[1].metric("Proyección Fin de Año", cop(proyeccion["ProyeccionFinAnio"]))

            pct_p = proyeccion["PorcentajeProyectado"]

            cols[2].metric(

                "% Proyectado del General",

                f"{pct_p:.1f}%" if pct_p is not None else "N/A",

                delta="Excede" if pct_p and pct_p > 100 else None,

                delta_color="inverse"

            )

        else:

            st.caption("📈 Proyección no disponible (las facturas seleccionadas no pertenecen todas al año en curso).")
 
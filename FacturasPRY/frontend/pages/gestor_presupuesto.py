import streamlit as st
import pandas as pd
import datetime
from utils.auth import mostrar_sidebar
from api.client import (
    get_presupuesto_general,
    guardar_presupuesto_general,
    get_presupuesto,
    crear_presupuesto,
    editar_presupuesto,
    eliminar_presupuesto,
    get_agrupaciones,
    get_proyeccion_gasto,
    guardar_proyeccion_gasto_batch,
    # NUEVAS - agregar estas 3 funciones a api/client.py (ver snippet al final)
    get_presupuesto_tipo,
    guardar_presupuesto_tipo,
    guardar_proyeccion_tipo_batch,
)
mostrar_sidebar()

st.set_page_config(
    page_title="Presupuesto",
    layout="wide"
)

# ============================================================
# VALIDAR SESIÓN Y ROL
# ============================================================
if not st.session_state.get("access_token"):
    st.error("❌ Debes iniciar sesión")
    st.stop()

if st.session_state.get("rol") not in (1, 2):
    st.error("❌ Solo Gestor o Admin pueden acceder")
    st.stop()

id_area = st.session_state.get("IdArea")

if not id_area:
    st.error("❌ Tu usuario no tiene un área asignada")
    st.stop()

st.title("💰 Presupuesto del Área")


# ============================================================
# CACHÉ DE LECTURAS DE REFERENCIA
# ============================================================
# Streamlit re-ejecuta TODO el script en cada edición de celda del
# data_editor de abajo. Sin caché, estas 3 lecturas se dispararían por
# cada tecla que el usuario escribe en la matriz OPEX/CAPEX/Agrupación,
# generando llamadas de red innecesarias y, si alguna falla o tarda,
# hace que la matriz "desaparezca" momentáneamente en ese rerun.
# Con cache_data, solo se vuelve a golpear la API cada cierto tiempo
# (ttl) o cuando se invalida explícitamente tras un guardado exitoso.
@st.cache_data(ttl=60, show_spinner=False)
def _get_presupuesto_general_cached(id_area, ano):
    return get_presupuesto_general(id_area, ano)


@st.cache_data(ttl=60, show_spinner=False)
def _get_presupuesto_tipo_cached(id_area, ano):
    return get_presupuesto_tipo(id_area, ano)


@st.cache_data(ttl=120, show_spinner=False)
def _get_agrupaciones_cached(id_area):
    return get_agrupaciones(id_area)


def cop(valor):
    """Formato de presentación en pesos colombianos: '$ 1.000.000'.
    Solo afecta texto mostrado (st.metric, etc.), nunca los valores
    numéricos que se envían al backend."""
    if valor is None:
        return "-"
    return f"$ {valor:,.0f}".replace(",", ".")


MESES_NOMBRE = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

# ============================================================
# AÑO DE TRABAJO (controla todas las secciones)
# ============================================================
anio_actual = datetime.datetime.now().year
ano = st.number_input(
    "Año",
    value=anio_actual,
    min_value=2020,
    max_value=2100,
    step=1,
    key="filtro_ano"
)

# ============================================================
# PRESUPUESTO GENERAL — necesario como referencia para todas las secciones
# ============================================================
success_general, general = _get_presupuesto_general_cached(id_area, ano)
presupuesto_general_actual = (general or {}).get("MontoAsignado", 0) or 0

# NUEVO - Presupuesto OPEX/CAPEX del área/año
success_tipo, presupuesto_tipo_rows = _get_presupuesto_tipo_cached(id_area, ano) if general else (True, [])
presupuesto_tipo_rows = presupuesto_tipo_rows or []
presupuesto_opex = next((r["MontoAsignado"] for r in presupuesto_tipo_rows if r["Tipo"] == "OPEX"), 0.0) or 0.0
presupuesto_capex = next((r["MontoAsignado"] for r in presupuesto_tipo_rows if r["Tipo"] == "CAPEX"), 0.0) or 0.0

tab_general, tab_mensual = st.tabs(
    ["📌 General", "📅 Mensual"]
)

# ============================================================
# TAB GENERAL
# ============================================================
with tab_general:
    st.subheader(f"📌 Presupuesto General {ano}")

    if not general:
        st.info(
            f"ℹ️ Todavía no existe un presupuesto general para el año {ano}. "
            f"Crea uno para poder asignar OPEX, CAPEX o proyecciones."
        )

    col1, col2 = st.columns([2, 1])
    with col1:
        st.metric("Presupuesto General Actual", cop(presupuesto_general_actual))
    with col2:
        nuevo_presupuesto_general = st.number_input(
            "Nuevo valor",
            value=float(presupuesto_general_actual),
            min_value=0.0,
            step=1000.0,
            key="input_presupuesto_general"
        )

    if st.button("💾 Guardar Presupuesto General", key="guardar_presupuesto_general"):
        success, response = guardar_presupuesto_general(id_area, ano, nuevo_presupuesto_general)
        if success:
            _get_presupuesto_general_cached.clear()
            st.success("✅ Presupuesto general guardado")
            st.rerun()
        else:
            st.error(f"❌ Error: {response.get('detail', response)}")

    # ========================================================
    # NUEVO - PRESUPUESTO OPEX / CAPEX (hijas del General)
    # ========================================================
    st.markdown("---")
    st.markdown("#### 🧩 Distribución OPEX / CAPEX")

    if not general:
        st.warning("⚠️ Primero crea el presupuesto general de este año.")
    else:
        disponible_sin_repartir = presupuesto_general_actual - presupuesto_opex - presupuesto_capex

        col1, col2, col3 = st.columns(3)
        with col1:
            nuevo_opex = st.number_input(
                "OPEX",
                value=float(presupuesto_opex),
                min_value=0.0,
                step=1000.0,
                key="input_presupuesto_opex"
            )
        with col2:
            nuevo_capex = st.number_input(
                "CAPEX",
                value=float(presupuesto_capex),
                min_value=0.0,
                step=1000.0,
                key="input_presupuesto_capex"
            )
        with col3:
            st.metric("Disponible del General sin repartir", cop(disponible_sin_repartir))

        if st.button("💾 Guardar OPEX / CAPEX", key="guardar_presupuesto_tipo"):
            errores = []

            success_opex, resp_opex = guardar_presupuesto_tipo(id_area, ano, "OPEX", nuevo_opex)
            if not success_opex:
                errores.append(f"OPEX: {resp_opex.get('detail', resp_opex)}")

            success_capex, resp_capex = guardar_presupuesto_tipo(id_area, ano, "CAPEX", nuevo_capex)
            if not success_capex:
                errores.append(f"CAPEX: {resp_capex.get('detail', resp_capex)}")

            if errores:
                for err in errores:
                    st.error(f"❌ {err}")
            else:
                _get_presupuesto_tipo_cached.clear()
                st.success("✅ Presupuesto OPEX/CAPEX guardado")
                st.rerun()

# ============================================================
# TAB MENSUAL (Tipo="Mensual", cuelga del General)
# ============================================================
# SIN CAMBIOS: se deja de crear Tipo='Mensual' desde el flujo nuevo,
# pero esta pestaña sigue funcionando igual sobre lo que ya exista.
with tab_mensual:
    st.subheader("📅 Presupuestos Mensuales")

    if not general:
        st.warning("⚠️ Primero crea el presupuesto general de este año para poder asignar meses.")
        presupuestos = []
    else:
        success_p, presupuestos = get_presupuesto(id_area, ano=ano)

        if success_p:
            presupuestos = presupuestos or []
            total_asignado = sum(p["MontoAsignado"] for p in presupuestos)
            col1, col2 = st.columns(2)
            col1.metric("Total asignado en meses", cop(total_asignado))
            col2.metric("Disponible sin asignar", cop(presupuesto_general_actual - total_asignado))

            if presupuestos:
                df_p = pd.DataFrame(presupuestos)
                df_p["Mes"] = df_p["Mes"].map(MESES_NOMBRE)
                st.dataframe(df_p[["Id", "Mes", "MontoAsignado"]], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Todavía no has asignado presupuesto a ningún mes de este año")
        else:
            presupuestos = []
            st.error(f"❌ Error al cargar presupuestos: {presupuestos}")

        st.markdown("#### ➕ Asignar / Actualizar mes")
        meses_ya_asignados = {p["Mes"]: p["Id"] for p in presupuestos} if presupuestos else {}
        col1, col2 = st.columns(2)
        with col1:
            mes_sel_nombre = st.selectbox(
                "Mes", options=list(MESES_NOMBRE.values()), key="nuevo_presupuesto_mes"
            )
            mes_sel_num = [k for k, v in MESES_NOMBRE.items() if v == mes_sel_nombre][0]
        with col2:
            monto_mes = st.number_input(
                "Monto", min_value=0.0, step=1000.0, key="nuevo_presupuesto_monto"
            )

        if st.button("✅ Guardar Mes", key="guardar_presupuesto_mes"):
            if mes_sel_num in meses_ya_asignados:
                success, response = editar_presupuesto(meses_ya_asignados[mes_sel_num], monto_mes)
            else:
                success, response = crear_presupuesto(id_area, ano, mes_sel_num, monto_mes)
            if success:
                st.success("✅ Presupuesto mensual guardado")
                st.rerun()
            else:
                st.error(f"❌ Error: {response.get('detail', response)}")

        if presupuestos:
            st.markdown("#### 🗑️ Eliminar mes asignado")
            id_eliminar = st.selectbox(
                "Selecciona el registro a eliminar",
                options=[p["Id"] for p in presupuestos],
                format_func=lambda x: next(MESES_NOMBRE[p["Mes"]] for p in presupuestos if p["Id"] == x),
                key="eliminar_presupuesto_selector"
            )
            if st.button("🗑️ Eliminar", key="eliminar_presupuesto_boton"):
                success, response = eliminar_presupuesto(id_eliminar)
                if success:
                    st.success("✅ Presupuesto mensual eliminado")
                    st.rerun()
                else:
                    st.error(f"❌ Error: {response.get('detail', response)}")

# ============================================================
# NUEVA SECCIÓN: PROYECCIÓN DE GASTOS
# ============================================================

st.markdown("---")
st.subheader("📊 Proyección de Gastos (Matriz Mes × Agrupación + OPEX/CAPEX)")

if not general:
    st.warning("⚠️ Primero crea el presupuesto general de este año para poder definir proyecciones.")
else:
    # ============================================================
    # CARGAR AGRUPACIONES DEL ÁREA
    # ============================================================
    ok_agr, agrupaciones = _get_agrupaciones_cached(id_area)

    if not ok_agr or not agrupaciones:
        st.info("ℹ️ No hay agrupaciones creadas para esta área todavía.")
    else:
        # ========================================================
        # ESTADO LOCAL DE LA MATRIZ
        # ========================================================
        # Se comporta como una hoja de Excel:
        #   - Primera carga del Área/Año: GET
        #   - Ediciones: memoria de Streamlit
        #   - Guardar Todo: POST batch (dos llamadas: agrupación + tipo)
        # No se vuelve a consultar Access en cada rerun del editor.

        contexto_proyeccion = (id_area, ano)

        if st.session_state.get("proyeccion_contexto") != contexto_proyeccion:
            # Primera carga para este Área/Año.
            ok_proy, proyecciones = get_proyeccion_gasto(id_area, ano)

            if not ok_proy:
                proyecciones = []
                st.error("❌ Error al cargar proyecciones")
            else:
                proyecciones = proyecciones or []

            # Separar las filas: Agrupación (IdAgrupacion con valor, Tipo NULL)
            # vs Tipo OPEX/CAPEX (Tipo con valor, IdAgrupacion NULL).
            proyecciones_dict = {}
            proyecciones_tipo_dict = {}
            for p in proyecciones:
                if p.get("IdVertical") is not None:
                    # Fuera de alcance por ahora (consumo real por vertical/factura).
                    continue
                if p.get("IdAgrupacion") is not None:
                    proyecciones_dict[(p["Mes"], p["IdAgrupacion"])] = p["MontoProyectado"]
                elif p.get("Tipo") is not None:
                    proyecciones_tipo_dict[(p["Mes"], p["Tipo"])] = p["MontoProyectado"]

            # Construir la matriz una sola vez.
            datos_matriz = []
            for mes in range(1, 13):
                fila = {"Mes": MESES_NOMBRE[mes]}
                total_mes = 0

                for agr in agrupaciones:
                    id_agr = agr["IdAgrupacion"]
                    nombre_agr = agr["Nombre"]
                    monto = proyecciones_dict.get((mes, id_agr), 0.0)
                    fila[nombre_agr] = monto
                    total_mes += monto

                # Columnas de Tipo, independientes de Agrupación.
                fila["OPEX"] = proyecciones_tipo_dict.get((mes, "OPEX"), 0.0)
                fila["CAPEX"] = proyecciones_tipo_dict.get((mes, "CAPEX"), 0.0)

                # Dos totales separados: NUNCA se suman entre sí.
                fila["Total/Mes"] = total_mes  # solo suma de agrupaciones
                fila["Total Naturaleza Gasto"] = fila["OPEX"] + fila["CAPEX"]  # solo suma OPEX+CAPEX
                datos_matriz.append(fila)

            # Fila de totales por agrupación + totales de Tipo.
            fila_totales = {"Mes": "TOTAL/AGRUP"}
            for agr in agrupaciones:
                id_agr = agr["IdAgrupacion"]
                nombre_agr = agr["Nombre"]
                fila_totales[nombre_agr] = sum(
                    proyecciones_dict.get((mes, id_agr), 0.0)
                    for mes in range(1, 13)
                )

            fila_totales["OPEX"] = sum(
                proyecciones_tipo_dict.get((mes, "OPEX"), 0.0) for mes in range(1, 13)
            )
            fila_totales["CAPEX"] = sum(
                proyecciones_tipo_dict.get((mes, "CAPEX"), 0.0) for mes in range(1, 13)
            )

            # Dos totales separados: NUNCA se suman entre sí.
            fila_totales["Total/Mes"] = sum(
                fila_totales[agr["Nombre"]]
                for agr in agrupaciones
            )
            fila_totales["Total Naturaleza Gasto"] = fila_totales["OPEX"] + fila_totales["CAPEX"]
            datos_matriz.append(fila_totales)

            # Estado de trabajo: queda en memoria mientras se mantiene
            # este contexto Área/Año.
            st.session_state["proyeccion_contexto"] = contexto_proyeccion
            st.session_state["proyeccion_df"] = pd.DataFrame(datos_matriz)
            st.session_state["proyecciones_dict"] = proyecciones_dict
            st.session_state["proyecciones_tipo_dict"] = proyecciones_tipo_dict

        else:
            # Rerun normal de Streamlit por edición: NO hacemos GET.
            proyecciones_dict = st.session_state.get("proyecciones_dict", {})
            proyecciones_tipo_dict = st.session_state.get("proyecciones_tipo_dict", {})

        # ============================================================
        # MATRIZ EDITABLE
        # ============================================================
        st.write(
            '**Edita los montos proyectados por mes, agrupación y OPEX/CAPEX. '
            'Presiona "Guardar Todo" al final.**'
        )
        st.caption(
            "🟦 Las columnas **OPEX** y **CAPEX** son independientes de las agrupaciones: "
            "no se suman entre sí. Hay **dos totales separados**: "
            "**Total Mes Agrupación** (solo suma las agrupaciones) y "
            "**Total Naturaleza Gasto** (solo suma OPEX + CAPEX). "
            "Cada uno se valida contra su propio presupuesto (General vs. OPEX/CAPEX). "
            "Valores en pesos colombianos (COP)."
        )

        # ------------------------------------------------------------
        # ENCABEZADO VISUAL AGRUPADO (solo presentación)
        # ------------------------------------------------------------
        # st.data_editor se renderiza sobre un <canvas> (glide-data-grid),
        # por lo que no es posible pintar sus encabezados de columna
        # individualmente vía CSS. Como alternativa segura, se dibuja una
        # franja HTML/CSS independiente justo encima de la tabla, con
        # anchos proporcionales al número de columnas de cada bloque, para
        # simular visualmente un encabezado multinivel sin tocar el editor.
        n_agrupaciones = len(agrupaciones)
        n_tipo = 2  # OPEX + CAPEX

        st.markdown(
            """
            <style>
            .proy-header-wrap {
                display: flex;
                width: 100%;
                gap: 3px;
                margin-top: 6px;
                margin-bottom: 2px;
            }
            .proy-header-block {
                padding: 6px 4px;
                text-align: center;
                font-weight: 600;
                font-size: 0.82rem;
                border-radius: 6px 6px 0 0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .proy-header-neutro {
                background-color: transparent;
                color: #31333F;
            }
            .proy-header-agrupaciones {
                background-color: #E4E6EB;
                color: #3B3F45;
                border: 1px solid #D3D6DA;
            }
            .proy-header-tipo {
                background-color: #1B4F91;
                color: #FFFFFF;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="proy-header-wrap">
                <div class="proy-header-block proy-header-neutro" style="flex-grow:1;">Mes</div>
                <div class="proy-header-block proy-header-tipo" style="flex-grow:{n_tipo};">TIPO DE GASTO</div>
                <div class="proy-header-block proy-header-agrupaciones" style="flex-grow:{n_agrupaciones};">AGRUPACIONES</div>
                <div class="proy-header-block proy-header-neutro" style="flex-grow:1;">Total Naturaleza Gasto</div>
                <div class="proy-header-block proy-header-neutro" style="flex-grow:1;">Total Mes Agrupación</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        df_matriz = st.session_state["proyeccion_df"]

        # ------------------------------------------------------------
        # column_config: solo etiquetas visuales (índices independientes
        # por bloque) y formato de moneda. No cambia nombres reales de
        # columna del DataFrame ni el orden/estructura de la matriz.
        # ------------------------------------------------------------
        column_config_matriz = {
            "OPEX": st.column_config.NumberColumn(
                "1. OPEX",
                help="Proyección mensual de OPEX (independiente de agrupación)",
                format="localized",
            ),
            "CAPEX": st.column_config.NumberColumn(
                "2. CAPEX",
                help="Proyección mensual de CAPEX (independiente de agrupación)",
                format="localized",
            ),
            "Total/Mes": st.column_config.NumberColumn(
                "Total Mes Agrupación",
                help="Solo suma las agrupaciones de este mes. No incluye OPEX ni CAPEX.",
                format="localized",
            ),
            "Total Naturaleza Gasto": st.column_config.NumberColumn(
                "Total Naturaleza Gasto",
                help="Solo suma OPEX + CAPEX de este mes. No incluye agrupaciones.",
                format="localized",
            ),
        }
        for _idx, _agr in enumerate(agrupaciones, start=1):
            column_config_matriz[_agr["Nombre"]] = st.column_config.NumberColumn(
                f"{_idx}. {_agr['Nombre']}",
                format="localized",
            )

        column_order_matriz = (
            ["Mes", "OPEX", "CAPEX"]
            + [agr["Nombre"] for agr in agrupaciones]
            + ["Total Naturaleza Gasto", "Total/Mes"]
        )

        df_editado = st.data_editor(
            df_matriz,
            key="matriz_proyecciones",
            use_container_width=True,
            hide_index=True,
            disabled=["Mes", "Total/Mes", "Total Naturaleza Gasto"],
            column_config=column_config_matriz,
            column_order=column_order_matriz,
        )

        # Guardamos inmediatamente la versión editada en memoria.
        st.session_state["proyeccion_df"] = df_editado.copy()

        # ============================================================
        # BOTÓN GUARDAR TODOa
        # ============================================================
        col1, col2 = st.columns([1, 3])

        with col1:
            if st.button("💾 Guardar Todo", key="guardar_matriz_proyecciones"):
                datos_a_guardar = []
                datos_tipo_a_guardar = []

                for _, fila in df_editado.iterrows():
                    if fila["Mes"] == "TOTAL/AGRUP":
                        continue

                    mes_num = next(
                        k for k, v in MESES_NOMBRE.items()
                        if v == fila["Mes"]
                    )

                    # --- Celdas de Agrupación (lógica original, sin cambios) ---
                    for agr in agrupaciones:
                        id_agr = agr["IdAgrupacion"]
                        nombre_agr = agr["Nombre"]
                        monto = fila.get(nombre_agr, 0.0)

                        if monto > 0 or (mes_num, id_agr) in proyecciones_dict:
                            datos_a_guardar.append({
                                "IdArea": id_area,
                                "Ano": ano,
                                "Mes": mes_num,
                                "IdAgrupacion": id_agr,
                                "IdVertical": None,
                                "MontoProyectado": float(monto)
                            })

                    # --- Celdas de Tipo OPEX/CAPEX (nuevo) ---
                    for tipo in ("OPEX", "CAPEX"):
                        monto_tipo = fila.get(tipo, 0.0)

                        if monto_tipo > 0 or (mes_num, tipo) in proyecciones_tipo_dict:
                            datos_tipo_a_guardar.append({
                                "IdArea": id_area,
                                "Ano": ano,
                                "Mes": mes_num,
                                "Tipo": tipo,
                                "IdVertical": None,
                                "MontoProyectado": float(monto_tipo)
                            })

                success_agr, response_agr = guardar_proyeccion_gasto_batch(
                    id_area, ano, datos_a_guardar
                )

                success_tipo_batch, response_tipo_batch = guardar_proyeccion_tipo_batch(
                    id_area, ano, datos_tipo_a_guardar
                )

                if success_agr and success_tipo_batch:
                    st.success(
                        f"✅ Proyecciones guardadas\n"
                        f"   • Agrupación → INSERT: {response_agr['inserted']}, "
                        f"UPDATE: {response_agr['updated']}, DELETE: {response_agr['deleted']}\n"
                        f"   • OPEX/CAPEX → INSERT: {response_tipo_batch['inserted']}, "
                        f"UPDATE: {response_tipo_batch['updated']}, DELETE: {response_tipo_batch['deleted']}"
                    )

                    # NO GET después del POST.
                    # La matriz local ya contiene exactamente lo que se envió.
                    proyecciones_dict = {}
                    proyecciones_tipo_dict = {}
                    for _, fila in df_editado.iterrows():
                        if fila["Mes"] == "TOTAL/AGRUP":
                            continue

                        mes_num = next(
                            k for k, v in MESES_NOMBRE.items()
                            if v == fila["Mes"]
                        )

                        for agr in agrupaciones:
                            id_agr = agr["IdAgrupacion"]
                            nombre_agr = agr["Nombre"]
                            monto = fila.get(nombre_agr, 0.0)
                            if monto > 0:
                                proyecciones_dict[(mes_num, id_agr)] = float(monto)

                        for tipo in ("OPEX", "CAPEX"):
                            monto_tipo = fila.get(tipo, 0.0)
                            if monto_tipo > 0:
                                proyecciones_tipo_dict[(mes_num, tipo)] = float(monto_tipo)

                    st.session_state["proyecciones_dict"] = proyecciones_dict
                    st.session_state["proyecciones_tipo_dict"] = proyecciones_tipo_dict
                else:
                    if not success_agr:
                        st.error(f"❌ Error en agrupación: {response_agr.get('detail', response_agr)}")
                    if not success_tipo_batch:
                        st.error(f"❌ Error en OPEX/CAPEX: {response_tipo_batch.get('detail', response_tipo_batch)}")

        with col2:
            st.info(
                "💡 Edita directamente en las celdas. Los cambios se mantienen "
                "en memoria y se guardan TODOS juntos al hacer clic en 'Guardar Todo'."
            )

        # ============================================================
        # RESUMEN VISUAL
        # ============================================================
        if not df_editado.empty:
            st.markdown("#### 📈 Resumen")

            # Solo las 12 filas de meses; no usamos la fila de totales
            # para evitar depender de una fórmula reconstruida desde BD.
            total_proyectado_agrup = sum(
                float(df_editado.iloc[idx][agr["Nombre"]] or 0)
                for idx in range(min(12, len(df_editado)))
                for agr in agrupaciones
            )
            total_opex_proyectado = sum(
                float(df_editado.iloc[idx]["OPEX"] or 0)
                for idx in range(min(12, len(df_editado)))
            )
            total_capex_proyectado = sum(
                float(df_editado.iloc[idx]["CAPEX"] or 0)
                for idx in range(min(12, len(df_editado)))
            )

            disponible_agrup = presupuesto_general_actual - total_proyectado_agrup
            disponible_opex = presupuesto_opex - total_opex_proyectado
            disponible_capex = presupuesto_capex - total_capex_proyectado

            col1, col2, col3 = st.columns(3)
            col1.metric("Total Proyectado (Agrupación)", cop(total_proyectado_agrup))
            col2.metric("Disponible (vs General)", cop(disponible_agrup))
            if disponible_agrup >= 0:
                col3.success("✅ Dentro del presupuesto")
            else:
                col3.error(f"⚠️ EXCEDE en {cop(abs(disponible_agrup))}")

            st.markdown("##### 🧩 OPEX / CAPEX")
            col4, col5, col6, col7 = st.columns(4)
            col4.metric("Proyectado OPEX", cop(total_opex_proyectado))
            col5.metric("Disponible OPEX", cop(disponible_opex))
            col6.metric("Proyectado CAPEX", cop(total_capex_proyectado))
            col7.metric("Disponible CAPEX", cop(disponible_capex))

            if disponible_opex < 0:
                st.error(f"⚠️ OPEX excede en {cop(abs(disponible_opex))}")
            if disponible_capex < 0:
                st.error(f"⚠️ CAPEX excede en {cop(abs(disponible_capex))}")
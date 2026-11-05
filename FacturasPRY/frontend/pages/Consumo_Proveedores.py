"""Vista de consulta. No consume, aprueba ni modifica facturas."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json
from copy import deepcopy
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from api.client import get_consumo_proveedores, get_esquema_consumo_proveedores

MESES = {1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
         7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"}
COLORES = {"CAPEX": "#2563eb", "OPEX": "#14b8a6", "SinClasificar": "#94a3b8"}


def cop(valor):
    if valor is None or pd.isna(valor):
        return "—"
    return "$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def error_legible(respuesta):
    raw = respuesta.get("error", respuesta)
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
        return payload.get("detail", str(payload)) if isinstance(payload, dict) else str(payload)
    except (ValueError, TypeError):
        return str(raw)


def tabla_montos(df, columnas):
    # Los números se conservan como números para ordenar y exportar.
    formato = {c: cop for c in columnas if c in df.columns}
    st.dataframe(df.style.format(formato, na_rep="—"), use_container_width=True, hide_index=True)


def csv_seguro(df):
    export = df.copy()
    for col in export.select_dtypes(include=["object", "string"]).columns:
        export[col] = export[col].map(
            lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
        )
    return export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def barras_mensuales(df, clave):
    fig = go.Figure()
    for columna in COLORES:
        if columna == "SinClasificar" and not df[columna].abs().sum():
            continue
        fig.add_bar(x=[MESES[m] for m in df["Mes"]], y=df[columna],
                    name="Sin clasificar" if columna == "SinClasificar" else columna,
                    marker_color=COLORES[columna],
                    hovertemplate="%{x}<br>%{y:,.2f} COP<extra>%{fullData.name}</extra>")
    fig.update_layout(barmode="relative", height=350, yaxis_title="COP", margin=dict(l=10, r=10, t=20, b=20),
                      legend=dict(orientation="h", y=1.15))
    st.plotly_chart(fig, use_container_width=True, key=clave)


def filtrar_rango(datos, desde, hasta):
    """Filtra la presentación; conserva las referencias anuales calculadas por la API."""
    if not 1 <= desde <= hasta <= datos["periodo"]["mes_corte"]:
        raise ValueError("El mes Desde debe ser anterior o igual a Hasta.")
    resultado = deepcopy(datos)
    resultado["periodo"]["mes_desde"] = desde
    cantidad = hasta - desde + 1
    mensual = [f for f in resultado["mensual"] if desde <= f["Mes"] <= hasta]
    resultado["mensual"] = mensual
    def suma(filas, campo):
        return float(sum((Decimal(str(f[campo])) for f in filas), Decimal("0")))
    for proveedor in resultado["proveedores"]:
        filas = [f for f in mensual if f["ClaveProveedor"] == proveedor["ClaveProveedor"]]
        # La media de meses completos y la estimación anual siguen siendo referencias anuales.
        proveedor["AcumuladoAnualAlCorte"] = proveedor["Acumulado"]
        proveedor["Acumulado"] = suma(filas, "Total")
        for campo in ("CAPEX", "OPEX", "SinClasificar"):
            proveedor[campo] = suma(filas, campo)
        proveedor["PromedioMensualAlCorte"] = proveedor["Acumulado"] / cantidad
        proveedor["MesesConConsumo"] = sum(any(f[c] != 0 for c in ("CAPEX", "OPEX", "SinClasificar")) for f in filas)
    r = resultado["resumen"]
    r["AcumuladoAnualAlCorte"] = r["Acumulado"]
    for campo in ("CAPEX", "OPEX", "SinClasificar"):
        r[campo] = suma(mensual, campo)
    r["Acumulado"] = suma(mensual, "Total")
    r["PromedioMensualAlCorte"] = r["Acumulado"] / cantidad
    r["PastelValido"] = r["Acumulado"] > 0 and all(p["Acumulado"] >= 0 for p in resultado["proveedores"])
    for proveedor in resultado["proveedores"]:
        proveedor["ParticipacionPct"] = round(proveedor["Acumulado"] / r["Acumulado"] * 100, 4) if r["PastelValido"] else None
    resultado["proveedores"].sort(key=lambda p: (-p["Acumulado"], p["Proveedor"].casefold()))
    resultado["serie"] = [f for f in resultado["serie"] if desde <= f["Mes"] <= hasta]
    acumulado = Decimal("0")
    for fila in resultado["serie"]:
        acumulado += Decimal(str(fila["Total"]))
        fila["Acumulado"] = float(acumulado)
    return resultado


def mostrar():
    st.set_page_config(page_title="Consumo por proveedor", layout="wide")
    if not st.session_state.get("access_token"):
        st.error("Debes iniciar sesión.")
        st.stop()
    if str(st.session_state.get("rol")) not in ("1", "2"):
        st.error("Solo Gestor o Admin pueden acceder.")
        st.stop()
    id_area = st.session_state.get("IdArea")
    if not id_area:
        st.error("Tu usuario no tiene un área asignada.")
        st.stop()
    try:
        hoy = datetime.now(ZoneInfo("America/Bogota"))
    except ZoneInfoNotFoundError:
        st.error("Falta tzdata. Instálalo en el entorno Python de Streamlit.")
        st.stop()
    st.title("Consumo por proveedor")
    st.caption("Gasto registrado · Evolución mensual · CAPEX / OPEX")
    c1, c2, c3, c4, c5 = st.columns([1, 1.2, 1.2, 1.4, 1])
    ano = int(c1.number_input("Año", min_value=2020, max_value=hoy.year, value=hoy.year, step=1, key="cp_ano"))
    limite = hoy.month if ano == hoy.year else 12
    mes_desde = c2.selectbox("Desde", list(range(1, limite + 1)), index=0,
                              format_func=lambda m: MESES[m], key=f"cp_desde_{ano}_{limite}")
    key_hasta = f"cp_corte_{ano}_{limite}"
    if st.session_state.get(key_hasta, limite) < mes_desde:
        st.session_state[key_hasta] = mes_desde
    mes_corte = c3.selectbox("Hasta", list(range(mes_desde, limite + 1)), index=limite - mes_desde,
                              format_func=lambda m: MESES[m], key=key_hasta)
    tipo = c4.selectbox("Tipo de gasto", ["TODOS", "CAPEX", "OPEX", "SIN CLASIFICAR"], key="cp_tipo")
    c5.write("")
    c5.button("Actualizar", key="cp_actualizar", use_container_width=True)
    # Cada interacción consulta de nuevo; no existe caché compartida entre usuarios.
    with st.spinner("Consultando el consumo…"):
        ok, datos = get_consumo_proveedores(id_area, ano, mes_corte, tipo)
    if not ok:
        st.error(error_legible(datos))
        if st.button("Comprobar configuración de proveedor", key="cp_esquema"):
            ok_esquema, esquema = get_esquema_consumo_proveedores(id_area)
            if ok_esquema:
                st.json(esquema)
            else:
                st.error(error_legible(esquema))
        st.stop()
    datos = filtrar_rango(datos, mes_desde, mes_corte)
    p, r = datos["periodo"], datos["resumen"]
    parcial = " · mes en curso, parcial" if p["mes_parcial"] else ""
    st.caption(f"{MESES[mes_desde]} a {MESES[p['mes_corte']].lower()} de {ano}{parcial} · Consulta: {p['consultado_en'][:19].replace('T', ' ')} (Colombia).")
    st.caption("Lee los acumulados guardados por proveedor en tb_Consumo. El mes corresponde al período registrado al consumir.")
    for aviso in datos["advertencias"]:
        st.warning(aviso)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Consumido en el rango", cop(r["Acumulado"]))
    k2.metric(f"Consumo de {MESES[mes_corte].lower()}", cop(r["ConsumoMesCorte"]))
    k3.metric("Promedio mensual del rango", cop(r["PromedioMensualAlCorte"]))
    k4.metric("Estimación de cierre anual", cop(r["EstimacionAnual"]))
    st.caption(f"CAPEX: {cop(r['CAPEX'])} · OPEX: {cop(r['OPEX'])} · Sin clasificar: {cop(r['SinClasificar'])} · "
               f"{r['Proveedores']} proveedores identificados.")
    st.caption(f"Referencia anual: enero a {MESES[mes_corte].lower()}, acumulado {cop(r['AcumuladoAnualAlCorte'])}. La estimación anual usa ese historial y no cambia al ajustar Desde.")
    with st.expander("Cómo se calcula el promedio y la estimación"):
        st.write("El promedio del rango es su consumo dividido entre la cantidad de meses seleccionados, incluidos Desde y Hasta. Incluye meses sin consumo como cero y, si aplica, el mes actual parcial.")
        st.write(f"La estimación usa el promedio de {p['meses_completos']} meses completos, de enero al último mes cerrado. "
                 "Por proveedor: conserva lo consumido, completa el mes en curso hasta ese promedio si todavía está por debajo, "
                 "y agrega ese promedio por cada mes restante del año. La tasa de gasto futuro tiene mínimo cero.")
        st.write("En enero en curso no hay estimación; para un año cerrado se muestra el total real. "
                 "Es una extrapolación del gasto registrado: no considera contratos, estacionalidad ni compras extraordinarias. "
                 "Un mes sin registro se toma como cero, por lo que meses pendientes de cargar reducen el promedio.")
        st.write("La consulta lee el resumen guardado al consumir. Seleccionar un corte pasado limita los meses, sin reconstruir una versión histórica de la base.")
    if datos.get("sin_mes"):
        with st.expander("Consumo registrado sin mes asignado", expanded=True):
            st.caption("Estos importes pertenecen al año consultado, pero no se incluyen en el corte mensual ni en su estimación. MontoFiltro respeta el tipo seleccionado.")
            st.metric("Consumo sin mes (según filtro)", cop(r.get("MontoSinMes", 0)))
            st.dataframe(pd.DataFrame(datos["sin_mes"]), hide_index=True, use_container_width=True)
    if not datos["proveedores"]:
        st.info("No hay consumo con mes válido para el área, año y tipo seleccionados hasta el mes de corte.")
        return

    if not any(f["Total"] != 0 or f["CAPEX"] != 0 or f["OPEX"] != 0 or f["SinClasificar"] != 0 for f in datos["mensual"]):
        st.info("No hay consumo en el rango seleccionado. Se mantienen en cero los proveedores del historial anual consultado.")
    proveedores = pd.DataFrame(datos["proveedores"])
    mensual = pd.DataFrame(datos["mensual"])
    serie = pd.DataFrame(datos["serie"])
    # IDs visibles en los selectores si hay proveedores con el mismo nombre.
    etiquetas = {f["ClaveProveedor"]: f"{f['Proveedor']} · {f['ClaveProveedor']}" for f in datos["proveedores"]}
    tab1, tab2, tab3 = st.tabs(["Resumen y participación", "Meses por proveedor", "Detalle del proveedor"])
    with tab1:
        izq, der = st.columns(2)
        with izq:
            st.subheader("Participación en el consumo")
            st.caption("Porcentaje del total acumulado del área con los filtros seleccionados.")
            if r["PastelValido"]:
                principales = proveedores.iloc[:8]
                labels = [etiquetas[k] for k in principales["ClaveProveedor"]]
                valores = principales["Acumulado"].tolist()
                if len(proveedores) > 8:
                    labels.append(f"Otros proveedores ({len(proveedores) - 8})")
                    valores.append(float(proveedores.iloc[8:]["Acumulado"].sum()))
                fig = go.Figure(go.Pie(labels=labels, values=valores, hole=0.45, sort=False,
                                       textinfo="percent", hovertemplate="%{label}<br>%{value:,.2f} COP<br>%{percent}<extra></extra>"))
                fig.update_layout(height=360, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.1))
                st.plotly_chart(fig, use_container_width=True, key="cp_pastel")
            else:
                st.info("El pastel requiere total positivo y consumos por proveedor no negativos. Se muestra la comparación de importes netos.")
                fig = go.Figure(go.Bar(x=proveedores["Acumulado"], y=[etiquetas[k] for k in proveedores["ClaveProveedor"]], orientation="h"))
                fig.update_layout(height=360, xaxis_title="Consumo neto (COP)", margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig, use_container_width=True, key="cp_netos")
        with der:
            st.subheader("Consumo mensual del área")
            barras_mensuales(serie, "cp_mensual_area")
        resumen = proveedores.rename(columns={"ParticipacionPct": "Participación %", "Acumulado": "Consumido en el rango",
                                               "PromedioMesesCompletos": "Promedio meses completos (base anual)", "EstimacionAnual": "Estimación anual (referencia)",
                                               "SinClasificar": "Sin clasificar"})
        columnas = ["Proveedor", "ClaveProveedor", "CAPEX", "OPEX", "Sin clasificar", "Consumido en el rango", "Participación %", "Promedio meses completos (base anual)", "Estimación anual (referencia)"]
        tabla_montos(resumen[columnas], ["CAPEX", "OPEX", "Sin clasificar", "Consumido en el rango", "Promedio meses completos (base anual)", "Estimación anual (referencia)"])
        st.download_button("Descargar resumen CSV", csv_seguro(resumen[columnas]), f"proveedores_{ano}_desde_{mes_desde:02d}_hasta_{mes_corte:02d}_{tipo.replace(' ', '_')}.csv", "text/csv", key="cp_csv_resumen")
    with tab2:
        st.subheader("Matriz de consumo mensual")
        detalle_tipo = st.checkbox("Separar filas por CAPEX / OPEX", key="cp_matriz_tipo")
        if detalle_tipo:
            largo = mensual.melt(id_vars=["ClaveProveedor", "Proveedor", "Mes"], value_vars=list(COLORES), var_name="Tipo", value_name="Consumo")
            largo["Tipo"] = largo["Tipo"].replace({"SinClasificar": "SIN CLASIFICAR"})
            tipos_visibles = [tipo] if tipo != "TODOS" else ["CAPEX", "OPEX"] + (["SIN CLASIFICAR"] if (mensual["SinClasificar"] != 0).any() else [])
            largo = largo[largo["Tipo"].isin(tipos_visibles)]
            matriz = largo.pivot_table(index=["ClaveProveedor", "Proveedor", "Tipo"], columns="Mes", values="Consumo", aggfunc="sum", fill_value=0)
        else:
            matriz = mensual.pivot_table(index=["ClaveProveedor", "Proveedor"], columns="Mes", values="Total", aggfunc="sum", fill_value=0)
        matriz = matriz.reindex(columns=list(range(mes_desde, mes_corte + 1)), fill_value=0)
        matriz.columns = [MESES[m] for m in matriz.columns]
        matriz["Acumulado"] = matriz.sum(axis=1)
        importes = matriz.columns.tolist()
        matriz = matriz.reset_index().sort_values("Acumulado", ascending=False)
        tabla_montos(matriz, importes)
        st.caption("Se muestran únicamente los meses entre Desde y Hasta. Los meses sin consumo aparecen en cero.")
        st.download_button("Descargar matriz CSV", csv_seguro(matriz), f"consumo_mensual_{ano}_desde_{mes_desde:02d}_hasta_{mes_corte:02d}.csv", "text/csv", key="cp_csv_matriz")
    with tab3:
        clave = st.selectbox("Proveedor", proveedores["ClaveProveedor"].tolist(), format_func=lambda k: etiquetas[k], key="cp_proveedor")
        item = proveedores.loc[proveedores["ClaveProveedor"] == clave].iloc[0]
        d1, d2, d3 = st.columns(3)
        d1.metric("Consumido en el rango", cop(item["Acumulado"]))
        d2.metric("Promedio meses completos (base anual)", cop(item["PromedioMesesCompletos"]))
        d3.metric("Estimación anual (referencia)", cop(item["EstimacionAnual"]))
        serie_proveedor = mensual[mensual["ClaveProveedor"] == clave].sort_values("Mes")
        barras_mensuales(serie_proveedor, "cp_meses_proveedor")
        curva = go.Figure(go.Scatter(x=[MESES[m] for m in serie_proveedor["Mes"]], y=serie_proveedor["Total"].cumsum(), mode="lines+markers", name="Acumulado"))
        curva.update_layout(height=250, yaxis_title="Acumulado (COP)", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(curva, use_container_width=True, key="cp_acumulado_proveedor")
        st.subheader("Desglose del consumo")
        tabla_montos(serie_proveedor[["Mes", "CAPEX", "OPEX", "SinClasificar", "Total"]].assign(
            Mes=lambda df: df["Mes"].map(MESES)), ["CAPEX", "OPEX", "SinClasificar", "Total"])
        if item.get("Servicio"):
            st.write("Servicio del proveedor:", item["Servicio"])
        if item.get("Descripcion"):
            st.write("Descripción del proveedor:", item["Descripcion"])
        st.caption("Servicio y descripción provienen del catálogo de proveedores. Los importes provienen del resumen de consumo.")



mostrar()

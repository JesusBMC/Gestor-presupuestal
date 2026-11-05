import streamlit as st

import datetime

import plotly.graph_objects as go

from api.client import get_dashboard_presupuesto


st.set_page_config(
    page_title="Panel de Presupuesto",
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

st.title("📊 Panel de Presupuesto")

# ============================================================
# BOTÓN DE RECARGA MANUAL
#
# No hay @st.cache_data en get_dashboard_presupuesto (api/client.py
# hace la petición HTTP directa cada vez), así que los datos ya se
# refrescan en cada rerun. Este botón sirve para forzar ese rerun
# manualmente (por ejemplo, si el presupuesto o el consumo cambiaron
# en otra sesión/pestaña y quieres traer lo último sin tocar ningún
# filtro). No reinicia el Año, la Vista ni el Mes seleccionados:
# esos son elecciones válidas del usuario, no estado "pegado".
# ============================================================

col_recargar, _ = st.columns([1, 6])

with col_recargar:
    if st.button("🔄 Recargar", key="btn_recargar_dashboard_presupuesto", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

COLOR_AGRUPACION = "#2563EB"
COLOR_CAPEX = "#7C3AED"
COLOR_OPEX = "#EA580C"

PALETA_AGRUPACIONES = ["#2563EB", "#0EA5E9", "#14B8A6", "#84CC16", "#F59E0B", "#F43F5E", "#8B5CF6", "#EC4899"]


def cop(v):
    if v is None:
        return "-"
    try:
        return f"${float(v):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "-"


def copCorto(v):
    v = float(v)
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:.0f}"


def pct(v):
    return f"{v * 100:.0f}%"


# ============================================================
# SELECTOR DE AÑO
# ============================================================

anio_actual = datetime.datetime.now().year

ano = st.number_input(
    "Año",
    value=anio_actual,
    min_value=2020,
    max_value=2100,
    step=1,
    key="filtro_ano_dashboard"
)

# Corte de datos: si es el año en curso, el mes actual; si es un
# año pasado, se asume el año completo cerrado; si es futuro, 0.
if ano == anio_actual:
    mes_actual = datetime.datetime.now().month
elif ano < anio_actual:
    mes_actual = 12
else:
    mes_actual = 0

# ============================================================
# CARGAR DATOS
# ============================================================

ok, datos = get_dashboard_presupuesto(id_area, ano)

if not ok:
    st.error(f"❌ Error al cargar el dashboard: {datos.get('error')}")
    st.stop()

presupuesto_general = datos.get("presupuesto_general", 0.0)
buckets_agrupacion_raw = datos.get("buckets_agrupacion", [])
buckets_tipo_raw = datos.get("buckets_tipo", [])
totales = datos.get("totales", {})

if not buckets_agrupacion_raw and not buckets_tipo_raw:
    st.info("ℹ️ No hay proyecciones ni consumo registrados para esta área/año todavía.")
    st.stop()

st.caption(f"Área {id_area} · Año {ano} · corte de datos: {MESES[mes_actual - 1] if mes_actual else 'sin datos aún'}")


# ============================================================
# CÁLCULOS POR BUCKET (mismo run-rate simple que el mockup)
# ============================================================

def calcular_bucket(nombre, proyectado_mensual, consumido_mensual, color):

    proy_anual = sum(proyectado_mensual)
    proy_acum = sum(proyectado_mensual[:mes_actual])
    cons_acum = sum(consumido_mensual[:mes_actual])

    pct_ejecutado = (cons_acum / proy_anual) if proy_anual > 0 else 0.0
    pct_plan_acum = (proy_acum / proy_anual) if proy_anual > 0 else 0.0
    proyeccion_cierre = (cons_acum / mes_actual * 12) if mes_actual > 0 else 0.0
    diff_cierre = proyeccion_cierre - proy_anual
    disponible = proy_anual - cons_acum

    return {
        "nombre": nombre,
        "color": color,
        "proyectado_mensual": proyectado_mensual,
        "consumido_mensual": consumido_mensual,
        "proy_anual": proy_anual,
        "proy_acum": proy_acum,
        "cons_acum": cons_acum,
        "pct_ejecutado": pct_ejecutado,
        "pct_plan_acum": pct_plan_acum,
        "proyeccion_cierre": proyeccion_cierre,
        "diff_cierre": diff_cierre,
        "disponible": disponible,
    }


buckets_agrupacion = [
    calcular_bucket(
        b["nombre"],
        b["proyectado_mensual"],
        b["consumido_mensual"],
        PALETA_AGRUPACIONES[i % len(PALETA_AGRUPACIONES)]
    )
    for i, b in enumerate(buckets_agrupacion_raw)
]

buckets_tipo = [
    calcular_bucket(
        b["tipo"],
        b["proyectado_mensual"],
        b["consumido_mensual"],
        COLOR_CAPEX if b["tipo"] == "CAPEX" else COLOR_OPEX
    )
    for b in buckets_tipo_raw
]


def sumar_series(buckets, campo):
    if not buckets:
        return [0.0] * 12
    return [sum(b[campo][i] for b in buckets) for i in range(12)]


# Series CONSOLIDADAS de cada hemisferio (esto SÍ es aditivo:
# sumar todas las agrupaciones entre sí es válido, igual que
# sumar CAPEX+OPEX entre sí. Lo que nunca se suma es un
# hemisferio con el otro).
serie_proy_agrupacion = sumar_series(buckets_agrupacion, "proyectado_mensual")
serie_cons_agrupacion = sumar_series(buckets_agrupacion, "consumido_mensual")
serie_proy_tipo = sumar_series(buckets_tipo, "proyectado_mensual")
serie_cons_tipo = sumar_series(buckets_tipo, "consumido_mensual")

consumo_vista_agrupacion = totales.get("consumo_vista_agrupacion", sum(serie_cons_agrupacion[:mes_actual]))
consumo_vista_tipo = totales.get("consumo_vista_tipo", sum(serie_cons_tipo[:mes_actual]))
vistas_consistentes = totales.get("vistas_consistentes", True)

cons_acum_capex = next(
    (b["cons_acum"] for b in buckets_tipo if b["nombre"] == "CAPEX"),
    0.0
)

cons_acum_opex = next(
    (b["cons_acum"] for b in buckets_tipo if b["nombre"] == "OPEX"),
    0.0
)
# ============================================================
# KPIs GENERALES — el General se compara contra los DOS
# hemisferios EN PARALELO, no se suman entre sí.
# ============================================================

st.subheader("Presupuesto General")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Presupuesto General", cop(presupuesto_general))
col2.metric("Consumido CAPEX", cop(cons_acum_capex))
col3.metric("Consumido OPEX", cop(cons_acum_opex))
col4.metric("Consumido Agrupaciones", cop(consumo_vista_agrupacion))


if not vistas_consistentes:
    st.warning(
        f"⚠️ Las dos vistas no coinciden: Agrupación reporta {cop(consumo_vista_agrupacion)} "
        f"y Tipo reporta {cop(consumo_vista_tipo)}. Esto no debería pasar si toda factura "
        f"impacta ambas dimensiones al consumirse — revisa los registros de tb_Consumo."
    )
else:
    st.success("✅ Las dos vistas (Agrupación y Tipo) coinciden en el consumo total, como debe ser.")


# ============================================================
# TARJETAS POR HEMISFERIO (Agrupación consolidada, CAPEX, OPEX)
# ============================================================

st.markdown("---")

col_a, col_b, col_c = st.columns(3)


def tarjeta_hemisferio(col, nombre, color, proy_anual, cons_acum, proyeccion_cierre):

    sobregira = proyeccion_cierre > proy_anual
    porcentaje_barra = min(100, (cons_acum / proy_anual * 100)) if proy_anual > 0 else 0

    with col:
        st.markdown(f"**{nombre}**")
        st.markdown(f"### {cop(proy_anual)}")
        st.caption("proyectado anual")

        c1, c2 = st.columns(2)
        c1.metric("Consumido", cop(cons_acum), label_visibility="visible")
        c2.metric(
            "Proyección cierre",
            cop(proyeccion_cierre),
            delta_color="inverse" if sobregira else "normal"
        )

        st.progress(porcentaje_barra / 100)


proy_anual_agr = sum(serie_proy_agrupacion)
proy_anual_capex = next((b["proy_anual"] for b in buckets_tipo if b["nombre"] == "CAPEX"), 0.0)
proy_anual_opex = next((b["proy_anual"] for b in buckets_tipo if b["nombre"] == "OPEX"), 0.0)

cierre_capex = next((b["proyeccion_cierre"] for b in buckets_tipo if b["nombre"] == "CAPEX"), 0.0)
cierre_opex = next((b["proyeccion_cierre"] for b in buckets_tipo if b["nombre"] == "OPEX"), 0.0)

cierre_agrupacion = (sum(serie_cons_agrupacion[:mes_actual]) / mes_actual * 12) if mes_actual > 0 else 0.0

tarjeta_hemisferio(col_a, "Agrupación (consolidado)", COLOR_AGRUPACION, proy_anual_agr, sum(serie_cons_agrupacion[:mes_actual]), cierre_agrupacion)
tarjeta_hemisferio(col_b, "CAPEX", COLOR_CAPEX, proy_anual_capex, cons_acum_capex, cierre_capex)
tarjeta_hemisferio(col_c, "OPEX", COLOR_OPEX, proy_anual_opex, cons_acum_opex, cierre_opex)


# ============================================================
# SELECTOR DE VISTA + GRÁFICO ACUMULADO
#
# Ya no existe una opción "Total" que mezcle ambos hemisferios.
# Cada opción es, por sí sola, una serie internamente aditiva.
# ============================================================

st.markdown("---")

vista = st.radio(
    "Vista",
    options=["Agrupación (consolidado)", "CAPEX", "OPEX"],
    horizontal=True,
    key="vista_dashboard"
)

if vista == "Agrupación (consolidado)":
    serie_proy = serie_proy_agrupacion
    serie_cons = serie_cons_agrupacion
    color_vista = COLOR_AGRUPACION
elif vista == "CAPEX":
    b = next((x for x in buckets_tipo if x["nombre"] == "CAPEX"), None)
    serie_proy = b["proyectado_mensual"] if b else [0.0] * 12
    serie_cons = b["consumido_mensual"] if b else [0.0] * 12
    color_vista = COLOR_CAPEX
else:
    b = next((x for x in buckets_tipo if x["nombre"] == "OPEX"), None)
    serie_proy = b["proyectado_mensual"] if b else [0.0] * 12
    serie_cons = b["consumido_mensual"] if b else [0.0] * 12
    color_vista = COLOR_OPEX

# Serie acumulada mes a mes
proy_acumulado = []
cons_acumulado = []
acc_p, acc_c = 0.0, 0.0

for i in range(12):
    acc_p += serie_proy[i]
    proy_acumulado.append(acc_p)
    if i < mes_actual:
        acc_c += serie_cons[i]
        cons_acumulado.append(acc_c)
    else:
        cons_acumulado.append(None)

st.markdown("##### Proyectado vs. Consumido acumulado")
st.caption("El área sombreada entre las líneas es el disponible restante")

fig_area = go.Figure()

fig_area.add_trace(go.Scatter(
    x=MESES, y=proy_acumulado, name="Proyectado",
    mode="lines", line=dict(color="#94A3B8", dash="dash"),
    fill="tozeroy", fillcolor="rgba(148,163,184,0.15)"
))

def _hex_a_rgba(hex_color, alpha=0.2):
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


fig_area.add_trace(go.Scatter(
    x=MESES, y=cons_acumulado, name="Consumido",
    mode="lines", line=dict(color=color_vista),
    fill="tozeroy", fillcolor=_hex_a_rgba(color_vista),
    connectgaps=False
))

fig_area.update_layout(
    height=320,
    margin=dict(t=20, b=20, l=10, r=10),
    yaxis_tickformat=",.0f",
    legend=dict(orientation="h", yanchor="bottom", y=1.02)
)

st.plotly_chart(fig_area, use_container_width=True)


# ============================================================
# GRÁFICO MENSUAL (no acumulado)
# ============================================================

st.markdown("##### Proyectado vs. Consumido por mes")

cons_mensual_mostrado = [
    serie_cons[i] if i < mes_actual else 0.0
    for i in range(12)
]

fig_bar = go.Figure()
fig_bar.add_trace(go.Bar(x=MESES, y=serie_proy, name="Proyectado", marker_color="#CBD5E1"))
fig_bar.add_trace(go.Bar(x=MESES, y=cons_mensual_mostrado, name="Consumido", marker_color=color_vista))
fig_bar.update_layout(
    height=280,
    barmode="group",
    margin=dict(t=20, b=20, l=10, r=10),
    yaxis_tickformat=",.0f"
)

st.plotly_chart(fig_bar, use_container_width=True)


# ============================================================
# COMPOSICIÓN — un pastel POR HEMISFERIO, nunca mezclados
# ============================================================

st.markdown("---")

col_pie1, col_pie2 = st.columns(2)

with col_pie1:
    st.markdown("##### Composición por Agrupación")
    st.caption("Participación de cada agrupación dentro del consumo de ese hemisferio")

    if buckets_agrupacion and sum(b["cons_acum"] for b in buckets_agrupacion) > 0:
        fig_pie_agr = go.Figure(data=[go.Pie(
            labels=[b["nombre"] for b in buckets_agrupacion],
            values=[b["cons_acum"] for b in buckets_agrupacion],
            marker=dict(colors=[b["color"] for b in buckets_agrupacion]),
            hole=0.45
        )])
        fig_pie_agr.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_pie_agr, use_container_width=True)
    else:
        st.info("Sin consumo registrado todavía.")

with col_pie2:
    st.markdown("##### Composición por Tipo")
    st.caption("CAPEX vs OPEX dentro del consumo de ese hemisferio")

    if buckets_tipo and sum(b["cons_acum"] for b in buckets_tipo) > 0:
        fig_pie_tipo = go.Figure(data=[go.Pie(
            labels=[b["nombre"] for b in buckets_tipo],
            values=[b["cons_acum"] for b in buckets_tipo],
            marker=dict(colors=[b["color"] for b in buckets_tipo]),
            hole=0.45
        )])
        fig_pie_tipo.update_layout(height=280, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_pie_tipo, use_container_width=True)
    else:
        st.info("Sin consumo registrado todavía.")
        
        
# ============================================================
# COMPOSICIÓN MENSUAL CAPEX vs OPEX
# ============================================================

st.markdown("---")
st.markdown("##### Composición del consumo por mes")
st.caption("CAPEX vs OPEX únicamente para el mes seleccionado")

mes_seleccionado = st.selectbox(
    "Mes",
    options=list(range(1, mes_actual + 1)),
    format_func=lambda x: MESES[x - 1],
    key="mes_composicion_dashboard"
)

capex_bucket = next(
    (b for b in buckets_tipo if b["nombre"] == "CAPEX"),
    None
)

opex_bucket = next(
    (b for b in buckets_tipo if b["nombre"] == "OPEX"),
    None
)

consumo_capex_mes = (
    capex_bucket["consumido_mensual"][mes_seleccionado - 1]
    if capex_bucket else 0.0
)

consumo_opex_mes = (
    opex_bucket["consumido_mensual"][mes_seleccionado - 1]
    if opex_bucket else 0.0
)

consumo_mes_total = consumo_capex_mes + consumo_opex_mes

if consumo_mes_total > 0:

    fig_pie_mes = go.Figure(data=[go.Pie(
        labels=["CAPEX", "OPEX"],
        values=[consumo_capex_mes, consumo_opex_mes],
        marker=dict(
            colors=[COLOR_CAPEX, COLOR_OPEX]
        ),
        hole=0.45,
        textinfo="label+percent",
        hovertemplate="%{label}: $%{value:,.0f}<extra></extra>"
    )])

    fig_pie_mes.update_layout(
        height=320,
        margin=dict(t=10, b=10, l=10, r=10)
    )

    st.plotly_chart(
        fig_pie_mes,
        use_container_width=True
    )

else:
    st.info(
        f"No hay consumo registrado para {MESES[mes_seleccionado - 1]}."
    )


# ============================================================
# EJECUCIÓN POR CATEGORÍA (cada bucket, sin sumarlos)
# ============================================================

st.markdown("---")
st.markdown("##### Ejecución por categoría")
st.caption("% del proyectado anual consumido a la fecha, vs. ritmo esperado según el plan mensual")

for b in buckets_agrupacion + buckets_tipo:

    if b["proy_anual"] <= 0:
        continue

    sobre_ritmo = b["pct_ejecutado"] > b["pct_plan_acum"] + 0.05
    bajo_ritmo = b["pct_ejecutado"] < b["pct_plan_acum"] - 0.15

    st.markdown(f"**{b['nombre']}** — {pct(b['pct_ejecutado'])} de {cop(b['proy_anual'])}")
    st.progress(min(1.0, b["pct_ejecutado"]))

st.caption("La barra muestra % ejecutado del proyectado anual. El plan mensual acumulado esperado a la fecha se usa para el reporte automático de abajo.")


# ============================================================
# REPORTE AUTOMÁTICO
# ============================================================

st.markdown("---")
st.markdown("##### 📋 Reporte automático")
st.caption("Generado a partir del consumo acumulado vs. el plan mensual y una proyección simple de cierre de año")

for b in buckets_agrupacion + buckets_tipo:

    if b["proy_anual"] <= 0:
        continue

    desvio = b["pct_ejecutado"] - b["pct_plan_acum"]

    if b["diff_cierre"] > 0:
        st.error(
            f"**{b['nombre']}**: al ritmo actual cerraría el año en {cop(b['proyeccion_cierre'])}, "
            f"{cop(b['diff_cierre'])} por encima del proyectado ({cop(b['proy_anual'])})."
        )
    elif desvio < -0.15:
        st.info(
            f"**{b['nombre']}**: va {pct(abs(desvio))} por debajo del plan mensual acumulado — "
            f"posible subejecución o gasto concentrado en meses futuros."
        )
    elif desvio > 0.1:
        st.warning(
            f"**{b['nombre']}**: ritmo de consumo {pct(desvio)} por encima del plan — vigilar los próximos meses."
        )
    else:
        st.success(
            f"**{b['nombre']}**: ejecución alineada con el plan mensual "
            f"({pct(b['pct_ejecutado'])} del anual, corte a {MESES[mes_actual - 1] if mes_actual else '-'})."
        )
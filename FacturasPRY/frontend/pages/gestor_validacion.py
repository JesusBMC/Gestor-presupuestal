import streamlit as st

import pandas as pd

import plotly.graph_objects as go

import datetime
import json
from zoneinfo import ZoneInfo

from api.client import (
    get_facturas_con_simulacion,
    simular_facturas,       # NUEVO - agregar esta función a api/client.py (ver nota abajo)
    rechazar_factura,
    consumir_facturas,
)

# ============================================================
# NOTA PARA api/client.py
# ============================================================
# Agregar esta función junto a las demás (mismo patrón de
# retorno (bool success, dict data) que usan las otras):
#
# def simular_facturas(id_area, ano, ids):
#     resp = requests.post(
#         f"{BASE_URL}/facturas-validacion/{id_area}/{ano}/simular",
#         json={"ids": ids},
#         headers=_auth_headers(),
#     )
#     if resp.ok:
#         return True, resp.json()
#     return False, {"error": resp.text}
# ============================================================


st.set_page_config(
    page_title="Validación de Facturas",
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

st.title("📋 Validación de Facturas Pendientes")

# ============================================================
# BOTÓN DE RECARGA MANUAL
#
# Streamlit no vuelve a ejecutar el script solo por "entrar" a la
# pantalla: solo corre de nuevo con una interacción (click, cambio
# de input) o un rerun explícito. Si además get_facturas_con_simulacion
# está cacheada (@st.cache_data) en api/client.py, los datos pueden
# quedar desactualizados hasta que expire el caché. Este botón fuerza
# ambas cosas: limpia cualquier caché de datos y relanza el script.
# ============================================================

col_recargar, _ = st.columns([1, 6])

with col_recargar:
    if st.button("🔄 Recargar", key="btn_recargar_dashboard", use_container_width=True):
        # No hay @st.cache_data en api/client.py, así que esto es solo
        # una salvaguarda por si se agrega caché más adelante.
        st.cache_data.clear()

        # Lo que sí queda "pegado" entre reruns es el session_state:
        # checkboxes de selección y el resultado de la última
        # simulación. Sin esto, la data se refresca pero se ve igual
        # porque las selecciones y el gráfico anterior siguen ahí.
        st.session_state.facturas_seleccionadas = set()
        st.session_state.resultado_simulacion = None

        for key in list(st.session_state.keys()):
            if key.startswith("chk_sim_"):
                del st.session_state[key]

        st.rerun()

# ============================================================
# SELECTOR DE AÑO
# ============================================================

anio_actual = datetime.datetime.now(ZoneInfo("America/Bogota")).year

ano = st.number_input(
    "Año de las facturas",
    value=anio_actual,
    min_value=2020,
    max_value=2100,
    step=1,
    key="filtro_ano_validacion"
)

# ============================================================
# ESTADO DE SELECCIÓN PARA SIMULACIÓN
# ============================================================

if "facturas_seleccionadas" not in st.session_state:
    st.session_state.facturas_seleccionadas = set()

if "resultado_simulacion" not in st.session_state:
    st.session_state.resultado_simulacion = None

# ============================================================
# BOTÓN: CONSUMIR FACTURAS APROBADAS
# ============================================================

if st.button("💰 Consumir facturas aprobadas", key="btn_consumir_facturas"):
    success, response = consumir_facturas(id_area, ano)

    if success:
        st.success(response.get("message", "Facturas consumidas correctamente"))
        st.rerun()
    else:
        st.error(f"❌ Error al consumir facturas: {response.get('error', response)}")

# ============================================================
# CARGAR DATOS CON SIMULACIÓN
# ============================================================

ok_validacion, datos_validacion = get_facturas_con_simulacion(id_area, ano)

if not ok_validacion:
    st.error(f"❌ Error al cargar facturas: {datos_validacion.get('error')}")
    st.stop()

# ============================================================
# EXTRAER Y PROCESAR DATOS
# ============================================================

resumen = datos_validacion.get("resumen", {})
facturas = datos_validacion.get("facturas", [])

total_pendientes = resumen.get("total_pendientes", 0)
pueden_aprobarse = resumen.get("pueden_aprobarse", 0)
sobregirado_count = resumen.get("sobregirado", 0)

meses_nombre = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}


periodo = datos_validacion.get("periodo_evaluacion")
if not periodo:
    st.error("Actualiza también el backend: falta el período de evaluación.")
    st.stop()
periodo_texto = f"{meses_nombre[periodo['mes']]} {periodo['ano']}"
st.info(f"Marco proyectado: **{periodo_texto}** · Facturas del año **{ano}**. "
        "Todas las pendientes se comparan con este período, sin cambiar su mes original.")
st.caption(f"Consulta: {periodo['consultado_en']} · Hora de Colombia. "
           "Recarga para actualizar al cambiar de mes. La evaluación individual no implica que todas quepan juntas.")

# Invalida resultados ante cambios de período, área, filtro o datos presupuestales.
firma = json.dumps({"area": id_area, "ano": ano,
                    "periodo": [periodo["ano"], periodo["mes"]],
                    "facturas": facturas}, sort_keys=True, default=str)
if st.session_state.get("firma_validacion") != firma:
    st.session_state.facturas_seleccionadas = set()
    st.session_state.resultado_simulacion = None
    for key in list(st.session_state):
        if key.startswith("chk_sim_"):
            del st.session_state[key]
    st.session_state.firma_validacion = firma


def cop(valor):
    """Formatea a COP."""
    if valor is None:
        return "-"
    try:
        return f"${float(valor):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "-"


def pct_local(v):
    if v is None:
        return "-"
    return f"{v * 100:.0f}%"


# ============================================================
# INFORME EJECUTIVO — análisis determinista por factura
#
# Regla de decisión (sin ambigüedad, siempre la misma para
# los mismos números):
#
#   1. Se calcula el margen que quedaría en CADA dimensión
#      después de aprobar esta factura, como % de lo proyectado.
#   2. Si ambas dimensiones quedan con margen >= 15%  -> APROBAR
#   3. Si ambas caben pero el margen mínimo es < 15%  -> APROBAR CON PRECAUCIÓN
#   4. Si cabe en una dimensión pero no en la otra    -> REQUIERE REVISIÓN
#   5. Si no cabe en ninguna de las dos                -> NO APROBAR
#
# El umbral de 15% es el único parámetro subjetivo; todo lo
# demás es aritmética directa sobre Disponible/Proyectado/Valor.
#
# IMPORTANTE: el contexto estadístico (mediana histórica,
# z-score, burn-rate) que llega en fac["estadistico"] es
# SOLO INFORMATIVO. Nunca cambia este veredicto determinístico,
# solo se muestra al lado para dar más elementos de juicio.
# ============================================================

UMBRAL_MARGEN_SANO = 0.15


def _evaluar_dimension(disponible, proyectado, valor_factura):
    """
    Calcula cuánto quedaría disponible en esta dimensión después
    de aprobar la factura, y ese remanente como % de lo proyectado
    (el "margen"). Si proyectado es 0, el margen se define en base
    a si el remanente es negativo o no, para no dividir por cero.
    """
    disponible_post = disponible - valor_factura

    if proyectado > 0:
        margen_pct = disponible_post / proyectado
    else:
        margen_pct = 0.0 if disponible_post < 0 else 1.0

    return disponible_post, margen_pct


def generar_informe_ejecutivo(fac):
    """
    Analiza una factura contra sus dos dimensiones (Agrupación y
    Tipo) y devuelve una recomendación determinista con su
    justificación numérica. No usa nada de fac["estadistico"]:
    ese contexto se muestra aparte, nunca decide el veredicto.
    """

    agr = fac.get("agrupacion", {})
    tipo = fac.get("tipo", {})
    valor = fac.get("ValorFactura", 0)

    disp_post_agr, margen_agr = _evaluar_dimension(
        agr.get("Disponible", 0), agr.get("Proyectado", 0), valor
    )
    disp_post_tipo, margen_tipo = _evaluar_dimension(
        tipo.get("Disponible", 0), tipo.get("Proyectado", 0), valor
    )

    cabe_agr = disp_post_agr >= 0
    cabe_tipo = disp_post_tipo >= 0
    margen_minimo = min(margen_agr, margen_tipo)

    if cabe_agr and cabe_tipo:

        if margen_minimo >= UMBRAL_MARGEN_SANO:
            nivel = "aprobar"
            titulo = "✅ APROBAR"
            detalle = (
                f"Cabe en ambas dimensiones con margen saludable. "
                f"Después de aprobar quedaría {pct_local(margen_agr)} disponible en "
                f"Agrupación y {pct_local(margen_tipo)} en {tipo.get('Tipo', fac.get('Tipo', 'Tipo'))}."
            )
        else:
            nivel = "precaucion"
            titulo = "⚠️ APROBAR CON PRECAUCIÓN"
            dimension_ajustada = "Agrupación" if margen_agr <= margen_tipo else fac.get("Tipo", "Tipo")
            detalle = (
                f"Cabe en ambas dimensiones, pero el margen queda ajustado (mínimo "
                f"{pct_local(margen_minimo)}, en {dimension_ajustada}). "
                f"Vigilar las próximas facturas de este mes en esa dimensión."
            )

    elif cabe_agr or cabe_tipo:
        nivel = "revisar"
        titulo = "🔍 REQUIERE REVISIÓN"
        dimension_excedida = "Tipo (CAPEX/OPEX)" if not cabe_tipo else "Agrupación"
        exceso = abs(disp_post_tipo) if not cabe_tipo else abs(disp_post_agr)
        detalle = (
            f"Cabe en una dimensión pero excede en {dimension_excedida} por {cop(exceso)}. "
            f"Requiere decisión manual: aprobar igual, esperar a otro mes, o reclasificar la factura."
        )

    else:
        nivel = "rechazar"
        titulo = "❌ NO APROBAR"
        detalle = (
            f"Excede el disponible en AMBAS dimensiones a la vez: "
            f"{cop(abs(disp_post_agr))} en Agrupación y {cop(abs(disp_post_tipo))} en "
            f"{fac.get('Tipo', 'Tipo')}."
        )

    return {
        "nivel": nivel,
        "titulo": titulo,
        "detalle": detalle,
        "margen_agr": margen_agr,
        "margen_tipo": margen_tipo,
        "margen_minimo": margen_minimo,
        "disp_post_agr": disp_post_agr,
        "disp_post_tipo": disp_post_tipo,
    }


_COLOR_NIVEL = {
    "aprobar": st.success,
    "precaucion": st.warning,
    "revisar": st.warning,
    "rechazar": st.error,
}

_COLOR_BANDA_Z = {
    "normal": st.success,
    "atipico_moderado": st.warning,
    "atipico_alto": st.error,
    "sin_historial": st.info,
}

_ETIQUETA_BANDA_Z = {
    "normal": "Normal",
    "atipico_moderado": "⚠️ Atípico moderado",
    "atipico_alto": "🔍 Atípico alto",
    "sin_historial": "ℹ️ Sin historial suficiente",
}

_ETIQUETA_BANDA_BURN = {
    "acelerado": "⚡ Ritmo acelerado",
    "lento": "🐢 Ritmo lento",
    "normal": "Ritmo normal",
    "sin_proyeccion_anual": "ℹ️ Sin proyección anual",
}


def _render_valor_vs_disponible(nombre_dimension, disponible_actual, valor_factura, nuevo_disponible):
    """
    Muestra, para una dimensión, la comparación directa que pediste:
    Valor de la factura vs. Disponible actual, y el Nuevo Disponible
    que quedaría después de aprobar. La barra representa qué
    proporción del disponible actual se consumiría con esta factura.
    """

    st.markdown(f"**{nombre_dimension}**")

    c1, c2 = st.columns(2)
    c1.metric("Disponible actual", cop(disponible_actual))
    c2.metric("Valor de la factura", cop(valor_factura))

    if disponible_actual > 0:
        proporcion_consumida = min(1.0, valor_factura / disponible_actual)
    else:
        proporcion_consumida = 1.0 if valor_factura > 0 else 0.0

    st.progress(max(0.0, min(1.0, proporcion_consumida)))

    if nuevo_disponible >= 0:
        st.caption(f"✅ Nuevo disponible después de aprobar: **{cop(nuevo_disponible)}**")
    else:
        st.caption(f"❌ Se excedería por: **{cop(abs(nuevo_disponible))}**")


def _render_contexto_estadistico(nombre_dimension, estadistico):
    """
    Contexto adicional (NO determina el veredicto): compara lo que
    quedaría acumulado este mes en el bucket, si se aprueba esta
    factura, contra la mediana de meses ya cerrados de este año, y
    muestra el ritmo de gasto (burn-rate) del año hasta la fecha.
    """

    if estadistico is None:
        return

    st.markdown(f"**Contexto estadístico — {nombre_dimension}**")

    banda_z = estadistico.get("banda", "sin_historial")
    render_z = _COLOR_BANDA_Z.get(banda_z, st.info)

    if estadistico.get("suficiente"):
        n = estadistico.get("n_meses_historial")
        mediana = estadistico.get("mediana")
        z = estadistico.get("z_robusto")
        z_txt = f", z-score robusto: {z:.1f}" if z is not None else ""
        render_z(
            f"**{_ETIQUETA_BANDA_Z.get(banda_z, banda_z)}** — {estadistico.get('mensaje')}\n\n"
            f"Comparado contra {n} mes(es) cerrado(s) de este año (mediana mensual: {cop(mediana)}{z_txt})."
        )
    else:
        render_z(f"**{_ETIQUETA_BANDA_Z.get(banda_z, banda_z)}** — {estadistico.get('mensaje')}")

    burn = estadistico.get("burn_rate")
    if burn:
        banda_burn = burn.get("banda", "sin_proyeccion_anual")
        render_burn = _COLOR_BANDA_Z.get(
            "atipico_moderado" if banda_burn in ("acelerado", "lento") else banda_burn,
            st.info
        )
        render_burn(f"**{_ETIQUETA_BANDA_BURN.get(banda_burn, banda_burn)}** — {burn.get('mensaje')}")


def render_informe_ejecutivo(fac):
    """
    Pinta el informe ejecutivo de una factura:
      1. Alerta de duplicidad, si aplica (determinístico)
      2. Valor de la factura vs. Disponible actual, por dimensión
      3. Nuevo disponible que quedaría después de aprobar
      4. Recomendación/análisis basada en esos números (determinístico)
      5. Contexto estadístico por dimensión (informativo, no decide)
    """

    st.caption(f"Período evaluado: {periodo_texto} · Mes original: {meses_nombre.get(fac.get("Mes_pendiente"), "-")}")

    if fac.get("duplicada"):
        st.error(
            f"🚩 **Posible duplicado**: ya existe otra factura Aprobada o Pendiente "
            f"con el número **{fac.get('NumFactura')}** en esta área/año. Revisar antes de continuar."
        )

    informe = generar_informe_ejecutivo(fac)
    agr = fac.get("agrupacion", {})
    tipo = fac.get("tipo", {})
    valor = fac.get("ValorFactura", 0)
    nombre_tipo = fac.get("Tipo", "Tipo")

    c1, c2 = st.columns(2)

    with c1:
        _render_valor_vs_disponible(
            "Agrupación",
            agr.get("Disponible", 0),
            valor,
            informe["disp_post_agr"]
        )

    with c2:
        _render_valor_vs_disponible(
            nombre_tipo,
            tipo.get("Disponible", 0),
            valor,
            informe["disp_post_tipo"]
        )

    st.divider()

    render_fn = _COLOR_NIVEL.get(informe["nivel"], st.info)
    render_fn(f"**{informe['titulo']}**\n\n{informe['detalle']}")

    estadistico = fac.get("estadistico") or {}

    est_agr = estadistico.get("agrupacion")
    est_tipo = estadistico.get("tipo")

    if est_agr or est_tipo:
        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            _render_contexto_estadistico("Agrupación", est_agr)
        with c4:
            _render_contexto_estadistico(nombre_tipo, est_tipo)


# ============================================================
# SEPARAR FACTURAS POR DIMENSIÓN
#
# FIX: Agrupación no depende del Tipo. TODA factura participa
# en la dimensión Agrupación, sin importar si además es CAPEX
# u OPEX. Antes esta lista salía siempre vacía porque filtraba
# por Tipo IS NULL, y ninguna factura real tiene Tipo nulo.
#
# FIX 2 (el importante): las tablas de "Pueden aprobarse" /
# "Sobregirado" de cada dimensión estaban clasificando por el
# campo COMBINADO fac["Cabe"] (= cabe_agrupacion AND cabe_tipo)
# en AMBAS tablas. Por eso una factura podía aparecer marcada
# igual en Agrupación y en Tipo aunque solo excediera en una de
# las dos dimensiones. Ahora cada tabla filtra ÚNICAMENTE por su
# propio "Cabe" de dimensión (fac["agrupacion"]["Cabe"] o
# fac["tipo"]["Cabe"]), que es justo lo que ya calcula bien el
# backend mes a mes.
# ============================================================

facturas_agrupacion = facturas  # todas, sin filtrar por Tipo

facturas_capex_opex = [
    f for f in facturas
    if f.get("Tipo") in ('CAPEX', 'OPEX')
]

facturas_agrupacion_aprob = [f for f in facturas_agrupacion if f.get("agrupacion", {}).get("Cabe", False)]
facturas_agrupacion_sobre = [f for f in facturas_agrupacion if not f.get("agrupacion", {}).get("Cabe", False)]

facturas_capex_opex_aprob = [f for f in facturas_capex_opex if f.get("tipo", {}).get("Cabe", False)]
facturas_capex_opex_sobre = [f for f in facturas_capex_opex if not f.get("tipo", {}).get("Cabe", False)]


# ============================================================
# WIDGET REUTILIZABLE: checkbox de selección para simular
# ============================================================

def _suffix_agrupacion(fac):
    """Determina en cuál de las dos secciones de Agrupación vive esta factura."""
    return "agr" if fac.get("agrupacion", {}).get("Cabe") else "sobre_agr"


def _suffix_tipo(fac):
    """Determina en cuál de las dos secciones de Tipo vive esta factura."""
    return "tipo" if fac.get("tipo", {}).get("Cabe") else "sobre_tipo"


def _on_toggle_seleccion(id_fac, widget_key, otro_widget_key):
    """
    Callback: se ejecuta ANTES de que el script vuelva a correr, así que
    el set compartido y el checkbox gemelo (misma factura, otra sección)
    quedan sincronizados sin ningún retraso de un clic.
    """
    st.session_state.resultado_simulacion = None
    marcado = st.session_state.get(widget_key, False)

    if marcado:
        st.session_state.facturas_seleccionadas.add(id_fac)
    else:
        st.session_state.facturas_seleccionadas.discard(id_fac)

    if otro_widget_key is not None:
        st.session_state[otro_widget_key] = marcado


def widget_seleccion(fac, key_suffix, otro_key_suffix):
    """Checkbox para incluir/excluir una factura de la simulación combinada."""
    id_fac = fac["Id"]
    widget_key = f"chk_sim_{key_suffix}_{id_fac}"
    otro_widget_key = f"chk_sim_{otro_key_suffix}_{id_fac}"

    if widget_key not in st.session_state:
        st.session_state[widget_key] = id_fac in st.session_state.facturas_seleccionadas

    st.checkbox(
        "🔎 Incluir en simulación",
        key=widget_key,
        on_change=_on_toggle_seleccion,
        args=(id_fac, widget_key, otro_widget_key)
    )


def widget_rechazar(fac, key_suffix):
    """Botón de rechazo, sin cambios de comportamiento respecto al original."""
    if st.button("❌ Rechazar", key=f"rechazar_{key_suffix}_{fac['Id']}", use_container_width=True):
        motivo = st.text_input("Motivo del rechazo:", key=f"motivo_{key_suffix}_{fac['Id']}")

        if motivo:
            success, response = rechazar_factura(fac["Id"], motivo=motivo)

            if success:
                st.warning(f"❌ {fac['NumFactura']} RECHAZADA")
                st.session_state.facturas_seleccionadas.discard(fac["Id"])
                st.rerun()
            else:
                st.error(f"❌ Error: {response.get('error')}")


# ============================================================
# BARRA LATERAL: SIMULACIÓN COMBINADA
# ============================================================

with st.sidebar:

    st.markdown("### 🧮 Simulación combinada")

    ids_sel = sorted(st.session_state.facturas_seleccionadas)

    st.write(f"**{len(ids_sel)}** factura(s) seleccionada(s)")

    if ids_sel:

        facturas_por_id = {f["Id"]: f for f in facturas}
        total_seleccionado = sum(
            facturas_por_id[i]["ValorFactura"]
            for i in ids_sel
            if i in facturas_por_id
        )
        st.caption(f"Suma seleccionada: {cop(total_seleccionado)}")

        col_sim, col_limpiar = st.columns(2)

        with col_sim:
            if st.button("📊 Simular", use_container_width=True, type="primary"):
                success, resultado = simular_facturas(id_area, ano, ids_sel)

                if success:
                    nuevo_periodo = resultado.get("periodo_evaluacion", {})
                    if (nuevo_periodo.get("ano"), nuevo_periodo.get("mes")) != (periodo["ano"], periodo["mes"]):
                        st.session_state.resultado_simulacion = None
                        st.warning("Cambió el período de evaluación. Recarga antes de simular.")
                    else:
                        st.session_state.resultado_simulacion = resultado
                else:
                    st.session_state.resultado_simulacion = None
                    st.error(f"❌ Error al simular: {resultado.get('error')}")

        with col_limpiar:
            if st.button("🗑️ Limpiar", use_container_width=True):
                st.session_state.facturas_seleccionadas = set()
                st.session_state.resultado_simulacion = None
                for key in list(st.session_state):
                    if key.startswith("chk_sim_"):
                        del st.session_state[key]
                st.rerun()
    else:
        st.info("Marca facturas con el checkbox '🔎 Incluir en simulación' para empezar.")


# ============================================================
# GRÁFICO DE PASTEL POR CADA CLAVE AFECTADA
# ============================================================

def grafico_pastel(titulo, consumo_actual, monto_seleccionado, disponible_simulado, proyectado):
    """
    Pastel de 3 franjas:
      - Consumo actual (ya aprobado antes de esta simulación)
      - Monto que se sumaría con la selección
      - Disponible restante después (0 si se excede)
    Si se excede, se muestra el exceso como una franja roja aparte.
    """

    if disponible_simulado >= 0:
        labels = ["Consumo actual", "Selección simulada", "Disponible restante"]
        values = [consumo_actual, monto_seleccionado, disponible_simulado]
        colors = ["#94a3b8", "#f59e0b", "#22c55e"]
    else:
        exceso = abs(disponible_simulado)
        labels = ["Consumo actual", "Selección (cubierta)", "Exceso (no cabe)"]
        values = [consumo_actual, max(monto_seleccionado - exceso, 0), exceso]
        colors = ["#94a3b8", "#f59e0b", "#ef4444"]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker=dict(colors=colors),
        hole=0.45,
        textinfo="label+percent"
    )])

    fig.update_layout(
        title=titulo,
        showlegend=True,
        margin=dict(t=60, b=20, l=20, r=20),
        height=380
    )

    st.plotly_chart(fig, use_container_width=True)


def mostrar_resultado_simulacion(resultado):

    st.markdown("## 📊 Resultado de la simulación combinada")
    st.caption(f"Todas las facturas seleccionadas contra {periodo_texto}. Resultado hipotético; no registra consumos.")

    total_sel = resultado.get("total_seleccionado", 0)
    st.metric("Total simulado (todas las facturas seleccionadas)", cop(total_sel))

    resultado_agr = resultado.get("agrupacion", [])
    resultado_tipo = resultado.get("tipo", [])

    if resultado_agr:
        st.markdown("### 🏢 Impacto por Agrupación")

        cols = st.columns(2)

        for i, r in enumerate(resultado_agr):
            with cols[i % 2]:
                titulo = f"{r['NombreAgrupacion']} - {meses_nombre.get(r['Mes'], r['Mes'])}"
                grafico_pastel(
                    titulo,
                    r["ConsumoActual"],
                    r["MontoSeleccionado"],
                    r["DisponibleSimulado"],
                    r["Proyectado"]
                )
                estado = "✅ Cabe" if r["Cabe"] else "❌ Excede el presupuesto"
                st.caption(
                    f"{estado} — Facturas: {', '.join(str(n) for n in r['Facturas'])} · "
                    f"Proyectado: {cop(r['Proyectado'])} · "
                    f"Disponible después: {cop(r['DisponibleSimulado'])}"
                )

    if resultado_tipo:
        st.markdown("### 📊 Impacto por CAPEX / OPEX")

        cols = st.columns(2)

        for i, r in enumerate(resultado_tipo):
            with cols[i % 2]:
                titulo = f"{r['Tipo']} - {meses_nombre.get(r['Mes'], r['Mes'])}"
                grafico_pastel(
                    titulo,
                    r["ConsumoActual"],
                    r["MontoSeleccionado"],
                    r["DisponibleSimulado"],
                    r["Proyectado"]
                )
                estado = "✅ Cabe" if r["Cabe"] else "❌ Excede el presupuesto"
                st.caption(
                    f"{estado} — Facturas: {', '.join(str(n) for n in r['Facturas'])} · "
                    f"Proyectado: {cop(r['Proyectado'])} · "
                    f"Disponible después: {cop(r['DisponibleSimulado'])}"
                )

    if not resultado_agr and not resultado_tipo:
        st.info("La selección no generó ningún impacto calculable.")


if st.session_state.resultado_simulacion:
    mostrar_resultado_simulacion(st.session_state.resultado_simulacion)
    st.markdown("---")


# ============================================================
# TARJETAS DE RESUMEN
# ============================================================

st.subheader("📊 Resumen General")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Pendientes", total_pendientes, delta=None)
col2.metric("Pueden Aprobarse ✅", pueden_aprobarse, delta_color="normal")
col3.metric("Sobregirado ❌", sobregirado_count, delta_color="inverse")
col4.metric("Posibles duplicados", sum(bool(f.get("duplicada")) for f in facturas), delta_color="off")


# ============================================================
# VISTA: AGRUPACIÓN
# ============================================================

st.markdown("---")
st.subheader("🏢 AGRUPACIÓN")
st.markdown("*Dimensión de gasto por agrupación — aplica a TODAS las facturas. Clasificación exclusiva por el disponible de Agrupación.*")

col_aprob_agr, col_sobre_agr = st.columns(2)

with col_aprob_agr:

    st.markdown("### ✅ PUEDEN APROBARSE (Agrupación)")

    if facturas_agrupacion_aprob:

        df_aprob_agr = pd.DataFrame([
            {
                "Factura": f.get("NumFactura"),
                "Tipo": f.get("Tipo"),
                "Mes factura": meses_nombre.get(f.get("Mes_pendiente"), f.get("Mes_pendiente", "-")),
                "Período evaluado": periodo_texto,
                "Agrupación": f.get("NombreAgrupacion", "-"),
                "Proyectado": cop(f.get("agrupacion", {}).get("Proyectado")),
                "Consumo": cop(f.get("agrupacion", {}).get("ConsumoAprobado")),
                "Disponible": cop(f.get("agrupacion", {}).get("Disponible")),
                "Valor": cop(f.get("ValorFactura"))
            }
            for f in facturas_agrupacion_aprob
        ])

        st.dataframe(df_aprob_agr, use_container_width=True, hide_index=True)

        st.markdown("#### Detalles")

        for fac in facturas_agrupacion_aprob:

            mes_pendiente = fac.get("Mes_pendiente")
            valor_factura = fac.get("ValorFactura", 0)

            with st.expander(
                f"📄 {fac.get('NumFactura')} - "
                f"{meses_nombre.get(mes_pendiente, mes_pendiente)} - "
                f"{cop(valor_factura)}"
            ):

                render_informe_ejecutivo(fac)

                st.divider()

                widget_seleccion(fac, "agr", _suffix_tipo(fac))
                widget_rechazar(fac, "agr")

    else:
        st.info("ℹ️ No hay facturas de agrupación que quepan en el presupuesto.")

with col_sobre_agr:

    st.markdown("### ❌ SOBREGIRADO (Agrupación)")

    if facturas_agrupacion_sobre:

        df_sobre_agr = pd.DataFrame([
            {
                "Factura": f.get("NumFactura"),
                "Tipo": f.get("Tipo"),
                "Mes factura": meses_nombre.get(f.get("Mes_pendiente"), f.get("Mes_pendiente", "-")),
                "Período evaluado": periodo_texto,
                "Agrupación": f.get("NombreAgrupacion", "-"),
                "Proyectado": cop(f.get("agrupacion", {}).get("Proyectado")),
                "Consumo": cop(f.get("agrupacion", {}).get("ConsumoAprobado")),
                "Disponible": cop(f.get("agrupacion", {}).get("Disponible")),
                "Valor": cop(f.get("ValorFactura")),
                "Exceso": cop(abs(f.get("ValorFactura", 0) - f.get("agrupacion", {}).get("Disponible", 0)))
            }
            for f in facturas_agrupacion_sobre
        ])

        st.dataframe(df_sobre_agr, use_container_width=True, hide_index=True)

        st.markdown("#### Detalles")

        for fac in facturas_agrupacion_sobre:

            mes_pendiente = fac.get("Mes_pendiente")
            valor_factura = fac.get("ValorFactura", 0)

            with st.expander(
                f"📄 {fac.get('NumFactura')} - "
                f"{meses_nombre.get(mes_pendiente, mes_pendiente)} - "
                f"{cop(valor_factura)}"
            ):

                render_informe_ejecutivo(fac)

                st.divider()

                widget_seleccion(fac, "sobre_agr", _suffix_tipo(fac))
                widget_rechazar(fac, "sobre_agr")

    else:
        st.success("✅ Todas las facturas de agrupación caben en el presupuesto.")


# ============================================================
# VISTA: CAPEX / OPEX
# ============================================================

st.markdown("---")
st.subheader("📊 CAPEX / OPEX")
st.markdown("*Facturas por tipo de gasto (Inversión vs Operación). Clasificación exclusiva por el disponible de Tipo — independiente de Agrupación.*")

col_aprob_tipo, col_sobre_tipo = st.columns(2)

with col_aprob_tipo:

    st.markdown("### ✅ PUEDEN APROBARSE (CAPEX/OPEX)")

    if facturas_capex_opex_aprob:

        df_aprob_tipo = pd.DataFrame([
            {
                "Factura": f.get("NumFactura"),
                "Tipo": f.get("Tipo"),
                "Mes factura": meses_nombre.get(f.get("Mes_pendiente"), f.get("Mes_pendiente", "-")),
                "Período evaluado": periodo_texto,
                "Agrupación": f.get("NombreAgrupacion", "-"),
                "Proyectado": cop(f.get("tipo", {}).get("Proyectado")),
                "Consumo": cop(f.get("tipo", {}).get("ConsumoAprobado")),
                "Disponible": cop(f.get("tipo", {}).get("Disponible")),
                "Valor": cop(f.get("ValorFactura"))
            }
            for f in facturas_capex_opex_aprob
        ])

        st.dataframe(df_aprob_tipo, use_container_width=True, hide_index=True)

        st.markdown("#### Detalles")

        for fac in facturas_capex_opex_aprob:

            mes_pendiente = fac.get("Mes_pendiente")
            tipo = fac.get("Tipo")
            valor_factura = fac.get("ValorFactura", 0)

            with st.expander(
                f"📄 {fac.get('NumFactura')} - {tipo} - "
                f"{meses_nombre.get(mes_pendiente, mes_pendiente)} - "
                f"{cop(valor_factura)}"
            ):

                render_informe_ejecutivo(fac)

                st.divider()

                widget_seleccion(fac, "tipo", _suffix_agrupacion(fac))
                widget_rechazar(fac, "tipo")

    else:
        st.info("ℹ️ No hay facturas de CAPEX/OPEX que quepan en el presupuesto.")

with col_sobre_tipo:

    st.markdown("### ❌ SOBREGIRADO (CAPEX/OPEX)")

    if facturas_capex_opex_sobre:

        df_sobre_tipo = pd.DataFrame([
            {
                "Factura": f.get("NumFactura"),
                "Tipo": f.get("Tipo"),
                "Mes factura": meses_nombre.get(f.get("Mes_pendiente"), f.get("Mes_pendiente", "-")),
                "Período evaluado": periodo_texto,
                "Agrupación": f.get("NombreAgrupacion", "-"),
                "Proyectado": cop(f.get("tipo", {}).get("Proyectado")),
                "Consumo": cop(f.get("tipo", {}).get("ConsumoAprobado")),
                "Disponible": cop(f.get("tipo", {}).get("Disponible")),
                "Valor": cop(f.get("ValorFactura")),
                "Exceso": cop(abs(f.get("ValorFactura", 0) - f.get("tipo", {}).get("Disponible", 0)))
            }
            for f in facturas_capex_opex_sobre
        ])

        st.dataframe(df_sobre_tipo, use_container_width=True, hide_index=True)

        st.markdown("#### Detalles")

        for fac in facturas_capex_opex_sobre:

            mes_pendiente = fac.get("Mes_pendiente")
            tipo = fac.get("Tipo")
            valor_factura = fac.get("ValorFactura", 0)

            with st.expander(
                f"📄 {fac.get('NumFactura')} - {tipo} - "
                f"{meses_nombre.get(mes_pendiente, mes_pendiente)} - "
                f"{cop(valor_factura)}"
            ):

                render_informe_ejecutivo(fac)

                st.divider()

                widget_seleccion(fac, "sobre_tipo", _suffix_agrupacion(fac))
                widget_rechazar(fac, "sobre_tipo")

    else:
        st.success("✅ Todas las facturas de CAPEX/OPEX caben en el presupuesto.")


# ============================================================
# FOOTER INFORMATIVO
# ============================================================

st.markdown("---")

st.info(
    """
    **Cómo funciona esta pantalla (DOS DIMENSIONES SIMULTÁNEAS, evaluadas y presentadas por separado):**

    **DIMENSIÓN 1: AGRUPACIÓN** — aplica a TODAS las facturas. La sección "AGRUPACIÓN"
    clasifica Puede aprobarse / Sobregirado ÚNICAMENTE con el disponible de Agrupación.

    **DIMENSIÓN 2: CAPEX / OPEX** — aplica según el tipo de cada factura. La sección
    "CAPEX / OPEX" clasifica Puede aprobarse / Sobregirado ÚNICAMENTE con el disponible
    de Tipo, sin importar cómo le fue en Agrupación.

    Cada detalle de factura muestra: Disponible actual → Valor de la factura → Nuevo
    disponible si se aprueba, un veredicto determinístico basado en esos números, y un
    contexto estadístico adicional (mediana de meses cerrados de este año, z-score
    robusto y ritmo de gasto del año) que **informa pero no decide** el veredicto.

    Marca el checkbox "🔎 Incluir en simulación" en las facturas que quieras evaluar
    (puedes elegir cuantas quieras, de cualquier combinación de mes, agrupación o tipo).
    Luego usa el botón "📊 Simular" en la barra lateral para ver el impacto COMBINADO de
    aprobarlas todas juntas, en gráficos de pastel por cada Agrupación y cada Tipo afectados.

    La validación y la simulación no aprueban ni descuentan facturas.
    Los controles existentes de consumo y rechazo son acciones separadas.
    El año seleccionado filtra las facturas; la proyección y el consumo de referencia
    corresponden siempre al año y mes actuales de Colombia.
    """
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from decimal import Decimal
import statistics

from db.connection import get_connection

from auth.jwt import verify_token

from auth.permisos import validar_permiso_area



router = APIRouter(
    prefix="/facturas-validacion",
    tags=["Facturas Validación"]
)


# ============================================================
# UTILIDADES
# ============================================================

def _to_float(value):
    """Convierte valores numéricos a float. None -> 0.0"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ============================================================
# HELPERS: PROYECCIÓN Y CONSUMO
#
# 2 MUNDOS INDEPENDIENTES (sin Vertical, confirmado que no se usa)
#
# IMPORTANTE: estas funciones son la ÚNICA fuente de verdad para
# el cálculo de Disponible/presupuesto (aprobar o no aprobar).
# La capa estadística nueva (más abajo) las REUTILIZA tal cual,
# sin modificarlas ni duplicar su lógica, porque el veredicto de
# aprobación tiene que seguir dependiendo exclusivamente de ellas.
# ============================================================

# ============================================================
# MUNDO 1: AGRUPACIÓN
# ============================================================

def _get_proyeccion_agrupacion(cursor, id_area: int, ano: int, mes: int, id_agrupacion: int):
    """Proyección por IdArea + Ano + Mes + IdAgrupacion"""
    cursor.execute("""
        SELECT MontoProyectado
        FROM tb_ProyeccionGasto
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND IdAgrupacion = ?
          AND Tipo IS NULL
    """, (id_area, ano, mes, id_agrupacion))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


def _get_consumo_agrupacion(cursor, id_area: int, ano: int, mes: int, id_agrupacion: int):
    """Consumo por IdArea + Ano + Mes + IdAgrupacion (suma si hay múltiples)"""
    cursor.execute("""
        SELECT SUM(Monto)
        FROM tb_Consumo
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND IdAgrupacion = ?
          AND Tipo IS NULL
    """, (id_area, ano, mes, id_agrupacion))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


# ============================================================
# MUNDO 2: TIPO (CAPEX / OPEX)
# ============================================================

def _get_proyeccion_capex(cursor, id_area: int, ano: int, mes: int):
    cursor.execute("""
        SELECT MontoProyectado
        FROM tb_ProyeccionGasto
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND Tipo = 'CAPEX'
          AND IdAgrupacion IS NULL
    """, (id_area, ano, mes))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


def _get_consumo_capex(cursor, id_area: int, ano: int, mes: int):
    cursor.execute("""
        SELECT SUM(Monto)
        FROM tb_Consumo
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND Tipo = 'CAPEX'
          AND IdAgrupacion IS NULL
    """, (id_area, ano, mes))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


def _get_proyeccion_opex(cursor, id_area: int, ano: int, mes: int):
    cursor.execute("""
        SELECT MontoProyectado
        FROM tb_ProyeccionGasto
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND Tipo = 'OPEX'
          AND IdAgrupacion IS NULL
    """, (id_area, ano, mes))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


def _get_consumo_opex(cursor, id_area: int, ano: int, mes: int):
    cursor.execute("""
        SELECT SUM(Monto)
        FROM tb_Consumo
        WHERE IdArea = ?
          AND Ano = ?
          AND Mes = ?
          AND Tipo = 'OPEX'
          AND IdAgrupacion IS NULL
    """, (id_area, ano, mes))

    row = cursor.fetchone()
    return _to_float(row[0]) if row else 0.0


# ============================================================
# CAPA ESTADÍSTICA (NUEVA)
#
# Todo lo de aquí abajo es SOLO CONTEXTO INFORMATIVO. Nunca decide
# si una factura cabe o no cabe en el presupuesto — eso lo sigue
# decidiendo exclusivamente la comparación Disponible vs Valor,
# con las funciones de arriba. Esta capa no puede aprobar ni
# rechazar nada por sí sola.
#
# El historial se construye leyendo tb_Facturas con
# Estado = 'Aprobado' directamente (NO tb_Consumo), para no
# depender de ni interferir con la lógica de consumo/presupuesto
# ya existente. No hay años anteriores disponibles: el historial
# es intra-año, limitado a los meses ya cerrados de este mismo año.
# ============================================================

N_MINIMO_HISTORIAL = 3  # por debajo de esto, no se calcula z-score (no es confiable con tan pocos puntos)
UMBRAL_BURN_GAP = 0.15  # 15 puntos porcentuales de diferencia entre % tiempo y % consumido; umbral ajustable, no calibrado con datos históricos de resultados


def _get_historial_mensual_agrupacion(cursor, id_area, ano, id_agrupacion, mes_actual):
    """
    Totales de facturas APROBADAS por mes para esta Agrupación,
    en meses anteriores al mes evaluado (meses ya cerrados de
    este mismo año). Un valor por mes con datos.
    """
    cursor.execute("""
        SELECT Mes_pendiente, SUM(ValorCOP_M1)
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND IdAgrupacion = ?
          AND Estado = 'Aprobado'
          AND Mes_pendiente < ?
        GROUP BY Mes_pendiente
    """, (id_area, ano, id_agrupacion, mes_actual))

    return [_to_float(row[1]) for row in cursor.fetchall()]


def _get_historial_mensual_tipo(cursor, id_area, ano, tipo, mes_actual):
    """Igual que la anterior, pero para la dimensión Tipo (CAPEX/OPEX)."""
    cursor.execute("""
        SELECT Mes_pendiente, SUM(ValorCOP_M1)
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND Tipo = ?
          AND Estado = 'Aprobado'
          AND Mes_pendiente < ?
        GROUP BY Mes_pendiente
    """, (id_area, ano, tipo, mes_actual))

    return [_to_float(row[1]) for row in cursor.fetchall()]


def _calcular_stats_historial(historial):
    """
    Calcula mediana y MAD (más robusto que desviación estándar
    clásica con pocos datos) de una lista de totales mensuales ya
    cerrados. NO depende de ninguna factura específica, así que es
    cacheable por bucket (mes + Agrupación, o mes + Tipo) para no
    recalcularse una vez por cada factura que caiga en ese mismo
    bucket.
    """
    n = len(historial)

    if n < N_MINIMO_HISTORIAL:
        return {
            "n_meses_historial": n,
            "suficiente": False,
            "mediana": None,
            "mad": None
        }

    mediana = statistics.median(historial)
    desvios_abs = [abs(v - mediana) for v in historial]
    mad = statistics.median(desvios_abs) * 1.4826  # escala para aproximar a desviación estándar

    return {
        "n_meses_historial": n,
        "suficiente": True,
        "mediana": mediana,
        "mad": mad
    }


def _evaluar_frente_a_historial(stats, total_bucket_si_aprueba):
    """
    Toma las stats ya calculadas del bucket (mediana/MAD) y las
    compara contra "lo que quedaría acumulado este mes en el bucket
    si se aprueba esta factura" (no solo el valor de la factura
    sola, porque puede haber varias facturas en el mismo mes/bucket).
    Esto sí es específico de cada factura, porque cada una suma un
    valor distinto al mismo consumo base del mes.
    """
    if not stats["suficiente"]:
        return {
            **stats,
            "z_robusto": None,
            "banda": "sin_historial",
            "mensaje": f"Historial insuficiente ({stats['n_meses_historial']} mes(es) cerrado(s); se requieren al menos {N_MINIMO_HISTORIAL})."
        }

    mediana = stats["mediana"]
    mad = stats["mad"]

    if mad == 0:
        if total_bucket_si_aprueba == mediana:
            z = 0.0
            banda = "normal"
            mensaje = "Dentro del comportamiento habitual."
        else:
            z = None
            banda = "atipico_alto"
            mensaje = "El historial no tiene variación entre meses y este monto es distinto a todos ellos."
    else:
        z = (total_bucket_si_aprueba - mediana) / mad
        if abs(z) < 1:
            banda = "normal"
            mensaje = "Dentro del comportamiento habitual."
        elif abs(z) < 2:
            banda = "atipico_moderado"
            mensaje = "Moderadamente fuera del comportamiento habitual de meses anteriores."
        else:
            banda = "atipico_alto"
            mensaje = "Marcadamente fuera del comportamiento habitual de meses anteriores."

    return {
        **stats,
        "z_robusto": z,
        "banda": banda,
        "mensaje": mensaje
    }


def _calcular_burn_rate(proyectado_anual, consumido_a_la_fecha, mes_actual):
    """
    % del año transcurrido vs % del presupuesto anual ya consumido
    (solo con facturas Aprobadas, vía las funciones de consumo
    existentes, sumadas mes a mes hasta el mes evaluado).
    """
    pct_tiempo = mes_actual / 12

    if proyectado_anual > 0:
        pct_consumido = consumido_a_la_fecha / proyectado_anual
    else:
        pct_consumido = None

    if pct_consumido is None:
        gap = None
        banda = "sin_proyeccion_anual"
        mensaje = "No hay proyección anual definida para calcular el ritmo de gasto."
    else:
        gap = pct_consumido - pct_tiempo
        resumen = f"({pct_consumido*100:.0f}% consumido vs {pct_tiempo*100:.0f}% del año transcurrido)"
        if gap > UMBRAL_BURN_GAP:
            banda = "acelerado"
            mensaje = f"El gasto va más rápido que el tiempo transcurrido del año {resumen}."
        elif gap < -UMBRAL_BURN_GAP:
            banda = "lento"
            mensaje = f"El gasto va más lento que el tiempo transcurrido del año {resumen}."
        else:
            banda = "normal"
            mensaje = f"El ritmo de gasto es consistente con el tiempo transcurrido del año {resumen}."

    return {
        "proyectado_anual": proyectado_anual,
        "consumido_a_la_fecha": consumido_a_la_fecha,
        "pct_tiempo": pct_tiempo,
        "pct_consumido": pct_consumido,
        "gap": gap,
        "banda": banda,
        "mensaje": mensaje
    }


def _burn_rate_agrupacion(cursor, id_area, ano, id_agrupacion, mes_actual):
    proyectado_anual = sum(
        _get_proyeccion_agrupacion(cursor, id_area, ano, m, id_agrupacion)
        for m in range(1, 13)
    )
    consumido_a_la_fecha = sum(
        _get_consumo_agrupacion(cursor, id_area, ano, m, id_agrupacion)
        for m in range(1, mes_actual + 1)
    )
    return _calcular_burn_rate(proyectado_anual, consumido_a_la_fecha, mes_actual)


def _burn_rate_tipo(cursor, id_area, ano, tipo, mes_actual):
    if tipo == 'CAPEX':
        get_proy, get_cons = _get_proyeccion_capex, _get_consumo_capex
    elif tipo == 'OPEX':
        get_proy, get_cons = _get_proyeccion_opex, _get_consumo_opex
    else:
        return None

    proyectado_anual = sum(get_proy(cursor, id_area, ano, m) for m in range(1, 13))
    consumido_a_la_fecha = sum(get_cons(cursor, id_area, ano, m) for m in range(1, mes_actual + 1))
    return _calcular_burn_rate(proyectado_anual, consumido_a_la_fecha, mes_actual)


def _stats_historial_agrupacion_cached(cache, cursor, id_area, ano, id_agrupacion, mes_actual):
    """
    Envuelve _get_historial_mensual_agrupacion + _calcular_stats_historial
    con caché por (IdAgrupacion, mes), para no repetir la consulta y el
    cálculo cuando varias facturas pendientes caen en el mismo bucket.
    """
    key = (id_agrupacion, mes_actual)
    if key not in cache:
        historial = _get_historial_mensual_agrupacion(cursor, id_area, ano, id_agrupacion, mes_actual)
        cache[key] = _calcular_stats_historial(historial)
    return cache[key]


def _stats_historial_tipo_cached(cache, cursor, id_area, ano, tipo, mes_actual):
    key = (tipo, mes_actual)
    if key not in cache:
        historial = _get_historial_mensual_tipo(cursor, id_area, ano, tipo, mes_actual)
        cache[key] = _calcular_stats_historial(historial)
    return cache[key]


def _burn_rate_agrupacion_cached(cache, cursor, id_area, ano, id_agrupacion, mes_actual):
    """
    El burn-rate de un bucket (mes + Agrupación) no depende de qué
    factura específica se esté evaluando, así que se calcula una
    sola vez por bucket y se reutiliza.
    """
    key = (id_agrupacion, mes_actual)
    if key not in cache:
        cache[key] = _burn_rate_agrupacion(cursor, id_area, ano, id_agrupacion, mes_actual)
    return cache[key]


def _burn_rate_tipo_cached(cache, cursor, id_area, ano, tipo, mes_actual):
    key = (tipo, mes_actual)
    if key not in cache:
        cache[key] = _burn_rate_tipo(cursor, id_area, ano, tipo, mes_actual)
    return cache[key]


def _es_duplicada(cursor, id_area, ano, num_factura, id_propia):
    """
    Validación determinística: ¿ya existe otra factura con el
    mismo NumFactura, Aprobada o Pendiente, en esta área/año?
    """
    cursor.execute("""
        SELECT COUNT(*)
        FROM tb_Facturas
        WHERE IdArea = ?
          AND Ano = ?
          AND NumFactura = ?
          AND Estado IN ('Aprobado', 'Pendiente')
          AND Id <> ?
    """, (id_area, ano, num_factura, id_propia))
    row = cursor.fetchone()
    return _to_float(row[0]) > 0 if row else False


# ============================================================
# 📋 GET - FACTURAS PENDIENTES CON SIMULACIÓN (pairwise, existente)
#
# DOS DIMENSIONES SIMULTÁNEAS:
# 1. AGRUPACIÓN (IdAgrupacion)
# 2. TIPO (CAPEX/OPEX)
#
# Una factura valida contra AMBAS dimensiones.
#
# NOTA: esta simulación es "una factura a la vez": el impacto en
# otras pendientes asume que SOLO esta se aprueba. Para simular
# varias facturas seleccionadas al tiempo, usar el endpoint
# POST /{id_area}/{ano}/simular más abajo.
#
# NOTA 2: se agrega bloque "estadistico" y "duplicada" por
# factura, de solo contexto (no afecta "Cabe" ni "Estado").
# ============================================================

@router.get("/{id_area}/{ano}")
def get_facturas_con_simulacion(
    id_area: int,
    ano: int,
    user: dict = Depends(verify_token)
):
    """
    Obtiene las facturas pendientes y calcula su impacto
    en AMBAS dimensiones: Agrupación + Tipo (CAPEX/OPEX).
    """

    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT
                f.Id,
                f.NumFactura,
                f.Mes_pendiente,
                f.IdAgrupacion,
                a.Nombre AS NombreAgrupacion,
                f.Tipo,
                f.ValorCOP_M1
            FROM tb_Facturas AS f
            LEFT JOIN tb_Agrupacion AS a
                ON f.IdAgrupacion = a.Id
            WHERE f.IdArea = ?
              AND f.Ano = ?
              AND f.Estado = 'Pendiente'
            ORDER BY
                f.Tipo ASC,
                f.Mes_pendiente ASC,
                f.NumFactura ASC
        """, (id_area, ano))

        facturas_raw = []

        for row in cursor.fetchall():
            facturas_raw.append({
                "Id": row[0],
                "NumFactura": row[1],
                "Mes_pendiente": row[2],
                "IdAgrupacion": row[3],
                "NombreAgrupacion": row[4],
                "Tipo": row[5],  # 'CAPEX' o 'OPEX' (toda factura tiene Tipo)
                "ValorFactura": _to_float(row[6])
            })

        facturas_validadas = []
        count_aprobables = 0
        count_sobregirado = 0

        # Cachés por bucket (mes+Agrupación / mes+Tipo), vigentes solo
        # durante esta petición: evitan recalcular historial y burn-rate
        # cuando varias facturas pendientes caen en el mismo bucket.
        cache_stats_agr = {}
        cache_stats_tipo = {}
        cache_burn_agr = {}
        cache_burn_tipo = {}

        for fac in facturas_raw:

            mes = fac["Mes_pendiente"]
            id_agrupacion = fac["IdAgrupacion"]
            tipo = fac["Tipo"]
            valor_factura = fac["ValorFactura"]

            # DIMENSIÓN 1: AGRUPACIÓN

            proyectado_agr = _get_proyeccion_agrupacion(cursor, id_area, ano, mes, id_agrupacion)
            consumo_actual_agr = _get_consumo_agrupacion(cursor, id_area, ano, mes, id_agrupacion)
            disponible_actual_agr = proyectado_agr - consumo_actual_agr
            cabe_agrupacion = valor_factura <= disponible_actual_agr

            # DIMENSIÓN 2: TIPO (CAPEX/OPEX)

            if tipo == 'CAPEX':
                proyectado_tipo = _get_proyeccion_capex(cursor, id_area, ano, mes)
                consumo_actual_tipo = _get_consumo_capex(cursor, id_area, ano, mes)
            elif tipo == 'OPEX':
                proyectado_tipo = _get_proyeccion_opex(cursor, id_area, ano, mes)
                consumo_actual_tipo = _get_consumo_opex(cursor, id_area, ano, mes)
            else:
                proyectado_tipo = 0.0
                consumo_actual_tipo = 0.0

            disponible_actual_tipo = proyectado_tipo - consumo_actual_tipo
            cabe_tipo = valor_factura <= disponible_actual_tipo if tipo else True

            cabe = cabe_agrupacion and cabe_tipo

            if cabe:
                count_aprobables += 1
            else:
                count_sobregirado += 1

            # Simulación pairwise (impacto de aprobar SOLO esta)

            consumo_si_aprueba_agr = consumo_actual_agr + valor_factura
            disponible_si_aprueba_agr = proyectado_agr - consumo_si_aprueba_agr

            consumo_si_aprueba_tipo = consumo_actual_tipo + valor_factura
            disponible_si_aprueba_tipo = proyectado_tipo - consumo_si_aprueba_tipo

            impacto_otras_agrupacion = []
            impacto_otras_tipo = []

            for otra_fac in facturas_raw:

                if otra_fac["Id"] == fac["Id"]:
                    continue

                mismo_mes_agr = otra_fac["Mes_pendiente"] == mes
                misma_agr = otra_fac["IdAgrupacion"] == id_agrupacion

                if mismo_mes_agr and misma_agr:
                    valor_otra = otra_fac["ValorFactura"]
                    cabe_si_se_aprueba_esta_agr = valor_otra <= disponible_si_aprueba_agr

                    impacto_otras_agrupacion.append({
                        "Id": otra_fac["Id"],
                        "NumFactura": otra_fac["NumFactura"],
                        "Tipo": otra_fac["Tipo"],
                        "ValorFactura": valor_otra,
                        "cabe_si_se_aprueba": cabe_si_se_aprueba_esta_agr,
                        "disponible_si_se_aprueba": disponible_si_aprueba_agr
                    })

                mismo_mes_tipo = otra_fac["Mes_pendiente"] == mes
                mismo_tipo = otra_fac["Tipo"] == tipo

                if mismo_mes_tipo and mismo_tipo and tipo:
                    valor_otra = otra_fac["ValorFactura"]
                    cabe_si_se_aprueba_esta_tipo = valor_otra <= disponible_si_aprueba_tipo

                    impacto_otras_tipo.append({
                        "Id": otra_fac["Id"],
                        "NumFactura": otra_fac["NumFactura"],
                        # antes decía "Agrupacion" (inconsistente con el resto del archivo)
                        "NombreAgrupacion": otra_fac["NombreAgrupacion"],
                        "ValorFactura": valor_otra,
                        "cabe_si_se_aprueba": cabe_si_se_aprueba_esta_tipo,
                        "disponible_si_se_aprueba": disponible_si_aprueba_tipo
                    })

            # ================================================
            # CAPA ESTADÍSTICA (contexto, no decide el veredicto)
            # ================================================

            stats_agr = _stats_historial_agrupacion_cached(cache_stats_agr, cursor, id_area, ano, id_agrupacion, mes)
            estadistico_agr = _evaluar_frente_a_historial(stats_agr, consumo_si_aprueba_agr)
            burn_agr = _burn_rate_agrupacion_cached(cache_burn_agr, cursor, id_area, ano, id_agrupacion, mes)

            if tipo in ('CAPEX', 'OPEX'):
                stats_tipo = _stats_historial_tipo_cached(cache_stats_tipo, cursor, id_area, ano, tipo, mes)
                estadistico_tipo = _evaluar_frente_a_historial(stats_tipo, consumo_si_aprueba_tipo)
                burn_tipo = _burn_rate_tipo_cached(cache_burn_tipo, cursor, id_area, ano, tipo, mes)
            else:
                estadistico_tipo = None
                burn_tipo = None

            duplicada = _es_duplicada(cursor, id_area, ano, fac["NumFactura"], fac["Id"])

            facturas_validadas.append({
                "Id": fac["Id"],
                "NumFactura": fac["NumFactura"],
                "Mes_pendiente": mes,
                "IdAgrupacion": id_agrupacion,
                "NombreAgrupacion": fac["NombreAgrupacion"],
                "Tipo": tipo,
                "ValorFactura": valor_factura,

                "agrupacion": {
                    "Proyectado": proyectado_agr,
                    "ConsumoAprobado": consumo_actual_agr,
                    "Disponible": disponible_actual_agr,
                    "Cabe": cabe_agrupacion,
                    "simulacion": {
                        "consumo_si_se_aprueba": consumo_si_aprueba_agr,
                        "disponible_si_se_aprueba": disponible_si_aprueba_agr,
                        "impacto_otras": impacto_otras_agrupacion
                    }
                },

                "tipo": {
                    "Proyectado": proyectado_tipo,
                    "ConsumoAprobado": consumo_actual_tipo,
                    "Disponible": disponible_actual_tipo,
                    "Cabe": cabe_tipo,
                    "simulacion": {
                        "consumo_si_se_aprueba": consumo_si_aprueba_tipo,
                        "disponible_si_se_aprueba": disponible_si_aprueba_tipo,
                        "impacto_otras": impacto_otras_tipo
                    }
                },

                "estadistico": {
                    "agrupacion": {**estadistico_agr, "burn_rate": burn_agr},
                    "tipo": ({**estadistico_tipo, "burn_rate": burn_tipo} if estadistico_tipo else None)
                },

                "duplicada": duplicada,

                "Cabe": cabe,
                "Estado": "✅ APROBAR" if cabe else "❌ SOBREGIRADO"
            })

        conn.close()

        return {
            "resumen": {
                "total_pendientes": len(facturas_validadas),
                "pueden_aprobarse": count_aprobables,
                "sobregirado": count_sobregirado
            },
            "facturas": facturas_validadas
        }

    except Exception as e:
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Error validando facturas: {str(e)}"
        )


# ============================================================
# 📊 POST - SIMULAR VARIAS FACTURAS SELECCIONADAS AL TIEMPO
#
# A diferencia del GET de arriba (que simula "una factura a la
# vez"), este endpoint recibe una LISTA de IDs y calcula el
# impacto COMBINADO de aprobarlas todas juntas.
#
# Agrupa la selección por cada clave de Agrupación (Mes+IdAgrupacion)
# y por cada clave de Tipo (Mes+Tipo) que se vea afectada, y
# devuelve, para cada una, cuánto se sumaría en total y cómo
# quedaría el disponible. Pensado para alimentar un gráfico de
# pastel por cada combinación tocada por la selección.
# ============================================================

class SimularFacturasRequest(BaseModel):
    ids: list[int]


@router.post("/{id_area}/{ano}/simular")
def simular_facturas(
    id_area: int,
    ano: int,
    payload: SimularFacturasRequest,
    user: dict = Depends(verify_token)
):
    """
    Simula el efecto combinado de aprobar TODAS las facturas
    seleccionadas al mismo tiempo (no una por una).

    No modifica ningún dato: es de solo lectura.
    """

    validar_permiso_area(user, id_area)

    if not payload.ids:
        raise HTTPException(
            status_code=400,
            detail="Debes seleccionar al menos una factura para simular"
        )

    conn = get_connection()
    cursor = conn.cursor()

    try:

        placeholders = ",".join("?" for _ in payload.ids)

        cursor.execute(f"""
            SELECT
                f.Id,
                f.NumFactura,
                f.Mes_pendiente,
                f.IdAgrupacion,
                a.Nombre AS NombreAgrupacion,
                f.Tipo,
                f.ValorCOP_M1
            FROM tb_Facturas AS f
            LEFT JOIN tb_Agrupacion AS a
                ON f.IdAgrupacion = a.Id
            WHERE f.IdArea = ?
              AND f.Ano = ?
              AND f.Estado = 'Pendiente'
              AND f.Id IN ({placeholders})
        """, (id_area, ano, *payload.ids))

        seleccionadas = []

        for row in cursor.fetchall():
            seleccionadas.append({
                "Id": row[0],
                "NumFactura": row[1],
                "Mes": row[2],
                "IdAgrupacion": row[3],
                "NombreAgrupacion": row[4],
                "Tipo": row[5],
                "ValorFactura": _to_float(row[6])
            })

        if not seleccionadas:
            conn.close()
            raise HTTPException(
                status_code=404,
                detail="Ninguna de las facturas seleccionadas es una pendiente válida de esta área/año"
            )

        # ====================================================
        # AGRUPAR LA SELECCIÓN POR CADA CLAVE AFECTADA
        # ====================================================

        suma_por_agr = {}   # (Mes, IdAgrupacion) -> monto acumulado
        suma_por_tipo = {}  # (Mes, Tipo) -> monto acumulado

        for f in seleccionadas:

            key_agr = (f["Mes"], f["IdAgrupacion"])
            if key_agr not in suma_por_agr:
                suma_por_agr[key_agr] = {
                    "monto": 0.0,
                    "nombre_agrupacion": f["NombreAgrupacion"],
                    "facturas": []
                }
            suma_por_agr[key_agr]["monto"] += f["ValorFactura"]
            suma_por_agr[key_agr]["facturas"].append(f["NumFactura"])

            if f["Tipo"] in ("CAPEX", "OPEX"):
                key_tipo = (f["Mes"], f["Tipo"])
                if key_tipo not in suma_por_tipo:
                    suma_por_tipo[key_tipo] = {
                        "monto": 0.0,
                        "facturas": []
                    }
                suma_por_tipo[key_tipo]["monto"] += f["ValorFactura"]
                suma_por_tipo[key_tipo]["facturas"].append(f["NumFactura"])

        # ====================================================
        # RESULTADO POR CADA CLAVE DE AGRUPACIÓN TOCADA
        # ====================================================

        resultado_agrupacion = []

        for (mes, id_agr), datos in suma_por_agr.items():

            proyectado = _get_proyeccion_agrupacion(cursor, id_area, ano, mes, id_agr)
            consumo_actual = _get_consumo_agrupacion(cursor, id_area, ano, mes, id_agr)
            disponible_actual = proyectado - consumo_actual
            disponible_simulado = disponible_actual - datos["monto"]

            resultado_agrupacion.append({
                "Mes": mes,
                "IdAgrupacion": id_agr,
                "NombreAgrupacion": datos["nombre_agrupacion"],
                "Facturas": datos["facturas"],
                "Proyectado": proyectado,
                "ConsumoActual": consumo_actual,
                "MontoSeleccionado": datos["monto"],
                "DisponibleActual": disponible_actual,
                "DisponibleSimulado": disponible_simulado,
                "Cabe": disponible_simulado >= 0
            })

        # ====================================================
        # RESULTADO POR CADA CLAVE DE TIPO TOCADA
        # ====================================================

        resultado_tipo = []

        for (mes, tipo), datos in suma_por_tipo.items():

            if tipo == 'CAPEX':
                proyectado = _get_proyeccion_capex(cursor, id_area, ano, mes)
                consumo_actual = _get_consumo_capex(cursor, id_area, ano, mes)
            else:
                proyectado = _get_proyeccion_opex(cursor, id_area, ano, mes)
                consumo_actual = _get_consumo_opex(cursor, id_area, ano, mes)

            disponible_actual = proyectado - consumo_actual
            disponible_simulado = disponible_actual - datos["monto"]

            resultado_tipo.append({
                "Mes": mes,
                "Tipo": tipo,
                "Facturas": datos["facturas"],
                "Proyectado": proyectado,
                "ConsumoActual": consumo_actual,
                "MontoSeleccionado": datos["monto"],
                "DisponibleActual": disponible_actual,
                "DisponibleSimulado": disponible_simulado,
                "Cabe": disponible_simulado >= 0
            })

        conn.close()

        return {
            "facturas_seleccionadas": seleccionadas,
            "total_seleccionado": sum(f["ValorFactura"] for f in seleccionadas),
            "agrupacion": resultado_agrupacion,
            "tipo": resultado_tipo
        }

    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Error simulando facturas: {str(e)}"
        )


# ============================================================
# ✅ PUT - APROBAR FACTURA
#
# Se deja intacto. El frontend de validación ya no lo llama
# desde esta pantalla (ver validacion_facturas_streamlit.py),
# pero el endpoint sigue disponible por si otra pantalla u
# proceso lo necesita.
# ============================================================

@router.put("/{id_factura}/aprobar")
def aprobar_factura(
    id_factura: int,
    request: dict = None,
    user: dict = Depends(verify_token)
):
    """
    Aprueba una factura pendiente.
    Cambia: Pendiente → Aprobado
    """

    confirmado = (
        request.get("confirmado", True)
        if request
        else True
    )

    if not confirmado:
        return {"message": "Aprobación cancelada"}

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT IdArea, Estado
            FROM tb_Facturas
            WHERE Id = ?
        """, (id_factura,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Factura no encontrada")

        id_area = row[0]
        estado_actual = row[1]

        validar_permiso_area(user, id_area)

        if estado_actual != "Pendiente":
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"Factura ya está en estado '{estado_actual}'. No se puede aprobar."
            )

        cursor.execute("""
            UPDATE tb_Facturas
            SET Estado = 'Aprobado'
            WHERE Id = ?
        """, (id_factura,))

        conn.commit()

        cursor.execute("""
            SELECT
                Id,
                NumFactura,
                Estado,
                Mes_pendiente,
                IdAgrupacion,
                Tipo,
                ValorCOP_M1
            FROM tb_Facturas
            WHERE Id = ?
        """, (id_factura,))

        row_actualizado = cursor.fetchone()
        conn.close()

        return {
            "message": "Factura aprobada correctamente",
            "factura": {
                "Id": row_actualizado[0],
                "NumFactura": row_actualizado[1],
                "Estado": row_actualizado[2],
                "Mes_pendiente": row_actualizado[3],
                "IdAgrupacion": row_actualizado[4],
                "Tipo": row_actualizado[5],
                "Monto": _to_float(row_actualizado[6])
            }
        }

    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Error aprobando factura: {str(e)}"
        )


# ============================================================
# ❌ PUT - RECHAZAR FACTURA
#
# Sin cambios. Rechazar no consume presupuesto, así que no
# necesita pasar por el flujo de simulación.
# ============================================================

@router.put("/{id_factura}/rechazar")
def rechazar_factura(
    id_factura: int,
    motivo: str = None,
    user: dict = Depends(verify_token)
):
    """Rechaza una factura pendiente."""

    conn = get_connection()
    cursor = conn.cursor()

    try:

        cursor.execute("""
            SELECT IdArea, Estado
            FROM tb_Facturas
            WHERE Id = ?
        """, (id_factura,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail="Factura no encontrada")

        id_area = row[0]
        estado_actual = row[1]

        validar_permiso_area(user, id_area)

        if estado_actual != "Pendiente":
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"Factura ya está en estado '{estado_actual}'."
            )

        cursor.execute("""
            UPDATE tb_Facturas
            SET Estado = 'Rechazado'
            WHERE Id = ?
        """, (id_factura,))

        conn.commit()
        conn.close()

        return {
            "message": "Factura rechazada correctamente",
            "IdFactura": id_factura,
            "Motivo": motivo
        }

    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Error rechazando factura: {str(e)}"
        )
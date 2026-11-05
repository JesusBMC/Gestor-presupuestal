from fastapi import APIRouter, HTTPException, Depends

from decimal import Decimal

from datetime import datetime

from collections import defaultdict
 
from db.connection import get_connection

from auth.jwt import verify_token

from auth.permisos import validar_permiso_area

from schemas.simulacion import SimulacionRequest
 
router = APIRouter(prefix="/simulacion", tags=["Simulacion"])
 
UMBRAL_CRITICO = 90

UMBRAL_WARNING = 70
 
 
def _f(value):

    """Decimal/None -> float seguro"""

    if value is None:

        return 0.0

    if isinstance(value, Decimal):

        return float(value)

    return float(value)
 
 
def _alerta_por_porcentaje(pct):

    if pct > UMBRAL_CRITICO:

        return "critico"

    if pct > UMBRAL_WARNING:

        return "warning"

    return "ok"
 
 
# ============================================================

# 🧠 MOTOR DE SIMULACIÓN

# ============================================================

# Reglas de negocio (definidas con el equipo):

#   - El presupuesto MENSUAL es el que decide la alerta operativa

#     (verde/amarillo/rojo) que ve el aprobador.

#   - El presupuesto ANUAL (General) es un techo DURO: si la suma

#     de las facturas simuladas hace que el año se pase del General,

#     el sistema BLOQUEA, sin importar cómo esté cualquier mes.

#   - Si un mes no tiene presupuesto mensual asignado todavía, ese

#     mes queda como "sin_dato": es informativo, no bloquea ni alerta

#     (igual que ya hace /dashboard/gasto-mensual).

# ============================================================
 
@router.post("/calcular")

def calcular_simulacion(data: SimulacionRequest, user: dict = Depends(verify_token)):

    validar_permiso_area(user, data.IdArea)
 
    if not data.facturaIds:

        raise HTTPException(400, "Selecciona al menos una factura")
 
    conn = get_connection()

    cursor = conn.cursor()
 
    # ------------------------------------------------------

    # 1) Traer las facturas seleccionadas (solo Pendiente,

    #    solo del área del usuario -> evita manipular otras áreas)

    # ------------------------------------------------------

    placeholders = ",".join("?" * len(data.facturaIds))

    cursor.execute(f"""

        SELECT f.Id, f.ValorCOP_M1, f.Ano, f.Mes, f.IdVertical, v.Nombre

        FROM tb_Facturas f

        LEFT JOIN tb_Vertical v ON f.IdVertical = v.Id

        WHERE f.Id IN ({placeholders})

          AND f.IdArea = ?

          AND f.Estado = 'Pendiente'

    """, (*data.facturaIds, data.IdArea))
 
    facturas = cursor.fetchall()
 
    if not facturas:

        conn.close()

        raise HTTPException(

            404,

            "Ninguna de las facturas seleccionadas está Pendiente en esta área "

            "(puede que ya hayan sido aprobadas o rechazadas)."

        )
 
    # ------------------------------------------------------

    # 2) Agrupar por año y por (año, mes)

    # ------------------------------------------------------

    monto_por_ano = defaultdict(float)

    monto_por_mes = defaultdict(float)      # key = (ano, mes)

    monto_por_vertical = defaultdict(float)  # key = nombre vertical
 
    for _id, valor_m1, ano, mes, id_vertical, nombre_vertical in facturas:

        valor = _f(valor_m1)

        monto_por_ano[ano] += valor

        if mes is not None:

            monto_por_mes[(ano, mes)] += valor

        monto_por_vertical[nombre_vertical or "Sin Vertical"] += valor
 
    total_seleccionado = sum(monto_por_ano.values())
 
    # ------------------------------------------------------

    # 3) TECHO DURO — presupuesto General por cada año involucrado

    # ------------------------------------------------------

    general_por_ano = {}

    excede_general = False

    razones = []
 
    for ano, monto_ano in monto_por_ano.items():

        cursor.execute("""

            SELECT MontoAsignado FROM tb_Presupuesto

            WHERE IdArea = ? AND Ano = ? AND Tipo = 'General'

        """, (data.IdArea, ano))

        row = cursor.fetchone()

        presupuesto_general = _f(row[0]) if row else 0.0
 
        cursor.execute("""

            SELECT SUM(ValorCOP_M2) FROM tb_Facturas

            WHERE IdArea = ? AND Ano = ? AND Estado = 'Aprobado'

        """, (data.IdArea, ano))

        gastado_actual = _f(cursor.fetchone()[0])
 
        nuevo_gastado = gastado_actual + monto_ano

        disponible = presupuesto_general - nuevo_gastado

        pct = round((nuevo_gastado / presupuesto_general) * 100, 2) if presupuesto_general else 0.0
 
        excede_este_ano = presupuesto_general > 0 and nuevo_gastado > presupuesto_general

        if presupuesto_general == 0:

            excede_este_ano = True

            razones.append(f"El área no tiene presupuesto General definido para {ano}.")

        elif excede_este_ano:

            excede_general = True

            razones.append(

                f"La suma de facturas superaría el presupuesto General {ano} "

                f"por ${nuevo_gastado - presupuesto_general:,.0f}."

            )
 
        if excede_este_ano:

            excede_general = True
 
        general_por_ano[ano] = {

            "Ano": ano,

            "PresupuestoGeneral": presupuesto_general,

            "GastadoActual": gastado_actual,

            "FacturasSeleccionadas": monto_ano,

            "NuevoGastado": nuevo_gastado,

            "Disponible": disponible,

            "Porcentaje": pct,

            "Excede": excede_este_ano

        }
 
    # ------------------------------------------------------

    # 4) ALERTA — presupuesto Mensual (esto decide el semáforo)

    # ------------------------------------------------------

    meses_detalle = []

    peor_alerta_mensual = "ok"  # ok < warning < critico
 
    orden_alerta = {"ok": 0, "warning": 1, "critico": 2}
 
    for (ano, mes), monto_mes in sorted(monto_por_mes.items()):

        cursor.execute("""

            SELECT MontoAsignado FROM tb_Presupuesto

            WHERE IdArea = ? AND Ano = ? AND Mes = ? AND Tipo = 'Mensual'

        """, (data.IdArea, ano, mes))

        row = cursor.fetchone()

        presupuesto_mensual = _f(row[0]) if row else None
 
        cursor.execute("""

            SELECT SUM(ValorCOP_M2) FROM tb_Facturas

            WHERE IdArea = ? AND Ano = ? AND Mes = ? AND Estado = 'Aprobado'

        """, (data.IdArea, ano, mes))

        gastado_actual_mes = _f(cursor.fetchone()[0])
 
        nuevo_gastado_mes = gastado_actual_mes + monto_mes
 
        if presupuesto_mensual is None or presupuesto_mensual == 0:

            alerta_mes = "sin_dato"

            pct_mes = None

        else:

            pct_mes = round((nuevo_gastado_mes / presupuesto_mensual) * 100, 2)

            alerta_mes = _alerta_por_porcentaje(pct_mes)

            if orden_alerta[alerta_mes] > orden_alerta[peor_alerta_mensual]:

                peor_alerta_mensual = alerta_mes

            if alerta_mes == "critico":

                razones.append(f"El mes {mes}/{ano} quedaría en {pct_mes:.1f}% de su presupuesto mensual.")

            elif alerta_mes == "warning":

                razones.append(f"El mes {mes}/{ano} quedaría en {pct_mes:.1f}% de su presupuesto mensual (atención).")
 
        meses_detalle.append({

            "Ano": ano,

            "Mes": mes,

            "PresupuestoMensual": presupuesto_mensual,

            "GastadoActual": gastado_actual_mes,

            "FacturasSeleccionadas": monto_mes,

            "NuevoGastado": nuevo_gastado_mes,

            "Porcentaje": pct_mes,

            "Alerta": alerta_mes

        })
 
    # ------------------------------------------------------

    # 5) Desglose por vertical — SOLO INFORMATIVO

    #    (no todas las verticales tienen presupuesto asignado

    #    todavía, así que aquí no se valida ni se colorea nada)

    # ------------------------------------------------------

    desglose_vertical = [

        {"Vertical": nombre, "Monto": monto}

        for nombre, monto in sorted(monto_por_vertical.items(), key=lambda x: -x[1])

    ]
 
    # ------------------------------------------------------

    # 6) Proyección de tendencia (solo si el año es el año actual)

    # ------------------------------------------------------

    proyeccion = None

    ano_actual = datetime.now().year

    if len(monto_por_ano) == 1:

        (unico_ano,) = monto_por_ano.keys()

        if unico_ano == ano_actual:

            mes_actual = datetime.now().month
 
            cursor.execute("""

                SELECT SUM(ValorCOP_M2) FROM tb_Facturas

                WHERE IdArea = ? AND Ano = ? AND Estado = 'Aprobado'

            """, (data.IdArea, unico_ano))

            gastado_ejecutado = _f(cursor.fetchone()[0])
 
            comprometido = gastado_ejecutado + monto_por_ano[unico_ano]

            meses_transcurridos = max(mes_actual, 1)

            promedio_mensual = comprometido / meses_transcurridos

            meses_restantes = max(12 - meses_transcurridos, 0)

            proyeccion_fin_anio = comprometido + (promedio_mensual * meses_restantes)
 
            presupuesto_general_actual = general_por_ano.get(unico_ano, {}).get("PresupuestoGeneral", 0.0)

            pct_proyectado = (

                round((proyeccion_fin_anio / presupuesto_general_actual) * 100, 2)

                if presupuesto_general_actual else None

            )
 
            proyeccion = {

                "Ano": unico_ano,

                "MesActual": mes_actual,

                "PromedioMensual": round(promedio_mensual, 2),

                "ProyeccionFinAnio": round(proyeccion_fin_anio, 2),

                "PresupuestoGeneral": presupuesto_general_actual,

                "PorcentajeProyectado": pct_proyectado

            }
 
    conn.close()
 
    # ------------------------------------------------------

    # 7) Sugerencia final — jerarquía de decisión

    #    Techo anual manda: si se excede, es BLOQUEO, punto.

    #    Si no, la alerta mensual decide la sugerencia.

    # ------------------------------------------------------

    if excede_general:

        sugerencia = "bloquear"

    elif peor_alerta_mensual == "critico":

        sugerencia = "revisar"

    elif peor_alerta_mensual == "warning":

        sugerencia = "aprobar_con_precaucion"

    else:

        sugerencia = "aprobar"
 
    if not razones:

        razones.append("Todos los meses afectados están dentro de rango normal.")
 
    return {

        "sugerencia": sugerencia,

        "razones": razones,

        "totalSeleccionado": total_seleccionado,

        "general": list(general_por_ano.values()),

        "meses": meses_detalle,

        "desgloseVertical": desglose_vertical,

        "proyeccion": proyeccion

    }
 
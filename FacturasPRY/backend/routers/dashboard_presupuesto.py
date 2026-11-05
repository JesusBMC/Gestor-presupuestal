from fastapi import APIRouter, Depends, HTTPException

from decimal import Decimal

from db.connection import get_connection
from auth.jwt import verify_token
from auth.permisos import validar_permiso_area

router = APIRouter(
    prefix="/dashboard-presupuesto",
    tags=["Dashboard Presupuesto"]
)

# ============================================================
# UTILIDADES
# ============================================================

def _to_float(value):
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


# ============================================================
# GET - DASHBOARD DE PRESUPUESTO (Agrupación + Tipo, mensual)
#
# El General es el ancla única. Se compara contra DOS vistas
# paralelas del MISMO consumo real, no aditivas entre sí:
#
#   - Vista Agrupación: suma de todas las agrupaciones
#   - Vista Tipo:        CAPEX + OPEX
#
# Ambas vistas deberían converger al mismo total consumido,
# porque cada factura impacta su agrupación Y su tipo a la vez
# (mismo dinero, dos maneras de mirarlo). Si no coinciden, es
# una señal de inconsistencia de datos que el dashboard expone
# en vez de ocultar sumándolas como si fueran categorías
# distintas.
# ============================================================

@router.get("/{id_area}/{ano}")
def get_dashboard_presupuesto(
    id_area: int,
    ano: int,
    user: dict = Depends(verify_token)
):
    validar_permiso_area(user, id_area)

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # ========================================================
        # PRESUPUESTO GENERAL (ancla)
        # ========================================================

        cursor.execute("""
            SELECT MontoAsignado
            FROM tb_Presupuesto
            WHERE IdArea = ? AND Ano = ? AND Tipo = 'General'
        """, (id_area, ano))

        row_general = cursor.fetchone()
        presupuesto_general = _to_float(row_general[0]) if row_general else 0.0

        # ========================================================
        # AGRUPACIONES DEL ÁREA (todas, aunque no tengan movimiento)
        # ========================================================

        cursor.execute("""
            SELECT Id, Nombre
            FROM tb_Agrupacion
            WHERE IdArea = ?
            ORDER BY Nombre
        """, (id_area,))

        agrupaciones = [{"Id": r[0], "Nombre": r[1]} for r in cursor.fetchall()]

        # ========================================================
        # PROYECCIÓN Y CONSUMO MENSUAL POR AGRUPACIÓN
        # ========================================================

        cursor.execute("""
            SELECT IdAgrupacion, Mes, MontoProyectado
            FROM tb_ProyeccionGasto
            WHERE IdArea = ? AND Ano = ?
              AND (IdAgrupacion IS NOT NULL AND IdAgrupacion <> 0)
              AND (Tipo IS NULL OR Tipo = '')
        """, (id_area, ano))

        proyeccion_agr = {}
        for id_agr, mes, monto in cursor.fetchall():
            proyeccion_agr[(id_agr, mes)] = proyeccion_agr.get((id_agr, mes), 0.0) + _to_float(monto)

        cursor.execute("""
            SELECT IdAgrupacion, Mes, SUM(Monto)
            FROM tb_Consumo
            WHERE IdArea = ? AND Ano = ?
              AND (IdAgrupacion IS NOT NULL AND IdAgrupacion <> 0)
              AND (Tipo IS NULL OR Tipo = '')
              AND (IdProvedor IS NULL OR IdProvedor = 0)
            GROUP BY IdAgrupacion, Mes
        """, (id_area, ano))

        consumo_agr = {}
        for id_agr, mes, monto in cursor.fetchall():
            consumo_agr[(id_agr, mes)] = _to_float(monto)

        buckets_agrupacion = []

        for agr in agrupaciones:

            proyectado_mensual = [
                proyeccion_agr.get((agr["Id"], mes), 0.0)
                for mes in range(1, 13)
            ]
            consumido_mensual = [
                consumo_agr.get((agr["Id"], mes), 0.0)
                for mes in range(1, 13)
            ]

            buckets_agrupacion.append({
                "id": agr["Id"],
                "nombre": agr["Nombre"],
                "proyectado_mensual": proyectado_mensual,
                "consumido_mensual": consumido_mensual
            })

        # ========================================================
        # PROYECCIÓN Y CONSUMO MENSUAL POR TIPO (CAPEX / OPEX)
        # ========================================================

        cursor.execute("""
            SELECT Tipo, Mes, MontoProyectado
            FROM tb_ProyeccionGasto
            WHERE IdArea = ? AND Ano = ?
              AND Tipo IS NOT NULL
              AND (IdAgrupacion IS NULL OR IdAgrupacion = 0)
        """, (id_area, ano))

        proyeccion_tipo = {}
        for tipo, mes, monto in cursor.fetchall():
            proyeccion_tipo[(tipo, mes)] = proyeccion_tipo.get((tipo, mes), 0.0) + _to_float(monto)

        cursor.execute("""
            SELECT Tipo, Mes, SUM(Monto)
            FROM tb_Consumo
            WHERE IdArea = ? AND Ano = ?
              AND Tipo IS NOT NULL
              AND (IdAgrupacion IS NULL OR IdAgrupacion = 0)
              AND (IdProvedor IS NULL OR IdProvedor = 0)
            GROUP BY Tipo, Mes
        """, (id_area, ano))

        consumo_tipo = {}
        for tipo, mes, monto in cursor.fetchall():
            consumo_tipo[(tipo, mes)] = _to_float(monto)

        buckets_tipo = []

        for tipo in ("CAPEX", "OPEX"):

            proyectado_mensual = [
                proyeccion_tipo.get((tipo, mes), 0.0)
                for mes in range(1, 13)
            ]
            consumido_mensual = [
                consumo_tipo.get((tipo, mes), 0.0)
                for mes in range(1, 13)
            ]

            buckets_tipo.append({
                "tipo": tipo,
                "proyectado_mensual": proyectado_mensual,
                "consumido_mensual": consumido_mensual
            })

        # ========================================================
        # TOTALES DE CADA VISTA (para el chequeo de consistencia)
        # ========================================================

        consumo_total_vista_agrupacion = sum(
            sum(b["consumido_mensual"]) for b in buckets_agrupacion
        )
        consumo_total_vista_tipo = sum(
            sum(b["consumido_mensual"]) for b in buckets_tipo
        )

        proyectado_total_vista_agrupacion = sum(
            sum(b["proyectado_mensual"]) for b in buckets_agrupacion
        )
        proyectado_total_vista_tipo = sum(
            sum(b["proyectado_mensual"]) for b in buckets_tipo
        )

        # Tolerancia pequeña por redondeo de flotantes, no de negocio
        EPSILON = 1.0
        vistas_consistentes = abs(
            consumo_total_vista_agrupacion - consumo_total_vista_tipo
        ) <= EPSILON

        conn.close()

        return {
            "presupuesto_general": presupuesto_general,
            "buckets_agrupacion": buckets_agrupacion,
            "buckets_tipo": buckets_tipo,
            "totales": {
                "consumo_vista_agrupacion": consumo_total_vista_agrupacion,
                "consumo_vista_tipo": consumo_total_vista_tipo,
                "proyectado_vista_agrupacion": proyectado_total_vista_agrupacion,
                "proyectado_vista_tipo": proyectado_total_vista_tipo,
                "vistas_consistentes": vistas_consistentes
            }
        }

    except Exception as e:
        conn.close()
        raise HTTPException(
            status_code=500,
            detail=f"Error obteniendo dashboard de presupuesto: {str(e)}"
        )

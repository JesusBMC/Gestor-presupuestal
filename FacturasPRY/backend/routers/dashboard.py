from fastapi import APIRouter, HTTPException, Depends

from decimal import Decimal
 
from db.connection import execute_query

from auth.jwt import verify_token

from auth.permisos import validar_permiso_area
 
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
 
 
def _to_float(value):

    """Convierte Decimal (típico en columnas Moneda de Access) a float. None -> 0.0"""

    if value is None:

        return 0.0

    if isinstance(value, Decimal):

        return float(value)

    return float(value)
 
 
# =========================================================

# 📊 RESUMEN DEL ÁREA (tarjetas + consumo del presupuesto general)

# =========================================================
 
@router.get("/{id_area}/resumen")

def resumen_area(

    id_area: int,

    periodo: int,

    user: dict = Depends(verify_token)

):
 
    validar_permiso_area(user, id_area)
 
    try:

        # Confirmar que el área existe

        rows_area = execute_query("""

            SELECT Id

            FROM tb_Area

            WHERE Id = ?

        """, (id_area,), fetch=True)
 
        if not rows_area:

            raise HTTPException(404, "Área no encontrada")
 
        # 🔁 Presupuesto GENERAL del área para ese año.

        # Ya no vive en tb_Area — ahora es una fila Tipo='General' en tb_Presupuesto,

        # enlazada al año (Ano) igual que las facturas.

        rows_general = execute_query("""

            SELECT MontoAsignado

            FROM tb_Presupuesto

            WHERE IdArea = ?

              AND Ano = ?

              AND Tipo = 'General'

        """, (id_area, periodo), fetch=True)
 
        presupuesto_general = _to_float(rows_general[0].get("MontoAsignado")) if rows_general else 0.0
 
        # Gasto acumulado: solo facturas Aprobadas, ValorCOP_M2, del año seleccionado

        # ⚠️ FIX: el valor real en tb_Facturas.Estado es 'Aprobado' (masculino),

        # no 'Aprobada'. Con el string anterior el filtro nunca coincidía con

        # ninguna fila y el dashboard siempre mostraba gasto en cero.

        rows_gasto = execute_query("""

            SELECT SUM(ValorCOP_M2) AS GastoTotal

            FROM tb_Facturas

            WHERE IdArea = ?

              AND Estado = 'Aprobado'

              AND Ano = ?

        """, (id_area, periodo), fetch=True)
 
        gasto_total = _to_float(rows_gasto[0].get("GastoTotal")) if rows_gasto else 0.0
 
        disponible = presupuesto_general - gasto_total

        excedido = presupuesto_general > 0 and gasto_total > presupuesto_general
 
        return {

            "PresupuestoGeneral": presupuesto_general,

            "GastoTotal": gasto_total,

            "Disponible": disponible,

            "Excedido": excedido

        }
 
    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(500, f"Error cargando resumen: {str(e)}")
 
 
# =========================================================

# 📋 GASTO POR VERTICAL / AGRUPACIÓN / MES (solo Aprobadas)

# =========================================================
 
@router.get("/{id_area}/agrupacion")

def gasto_por_agrupacion(

    id_area: int,

    periodo: int,

    user: dict = Depends(verify_token)

):
 
    validar_permiso_area(user, id_area)
 
    try:

        rows = execute_query("""

            SELECT

                v.Nombre AS Vertical,

                a.Nombre AS Agrupacion,

                f.Mes AS Mes,

                SUM(f.ValorCOP_M2) AS Monto

            FROM ((tb_Facturas f

                LEFT JOIN tb_Vertical v ON f.IdVertical = v.Id)

                LEFT JOIN tb_Agrupacion a ON f.IdAgrupacion = a.Id)

            WHERE f.IdArea = ?

              AND f.Estado = 'Aprobado'

              AND f.Ano = ?

            GROUP BY v.Nombre, a.Nombre, f.Mes

        """, (id_area, periodo), fetch=True)
 
        for r in rows:

            r["Vertical"] = r.get("Vertical") or "Sin Vertical"

            r["Agrupacion"] = r.get("Agrupacion") or "Sin Agrupación"

            r["Monto"] = _to_float(r.get("Monto"))
 
        return rows
 
    except Exception as e:

        raise HTTPException(500, f"Error cargando gasto por agrupación: {str(e)}")
 
 
# =========================================================

# 📅 GASTO MENSUAL (para cruzar visualmente contra tb_Presupuesto)

# =========================================================
 
@router.get("/{id_area}/gasto-mensual")

def gasto_mensual(

    id_area: int,

    periodo: int,

    user: dict = Depends(verify_token)

):

    """

    Devuelve el gasto (SUM ValorCOP_M2, solo Aprobado) agrupado por Mes.

    Es solo para comparación VISUAL contra el presupuesto mensual asignado

    (tb_Presupuesto, Tipo='Mensual') -> no valida ni bloquea nada, no genera

    error si el mes no tiene presupuesto asignado.

    """
 
    validar_permiso_area(user, id_area)
 
    try:

        rows = execute_query("""

            SELECT

                f.Mes AS Mes,

                SUM(f.ValorCOP_M2) AS Gasto

            FROM tb_Facturas f

            WHERE f.IdArea = ?

              AND f.Estado = 'Aprobado'

              AND f.Ano = ?

            GROUP BY f.Mes

        """, (id_area, periodo), fetch=True)
 
        for r in rows:

            r["Gasto"] = _to_float(r.get("Gasto"))
 
        return rows
 
    except Exception as e:

        raise HTTPException(500, f"Error cargando gasto mensual: {str(e)}")
 
 
# =========================================================

# 🔍 DIAGNÓSTICO TEMPORAL (borrar cuando ya no se necesite)

# =========================================================
 
@router.get("/{id_area}/debug")

def debug_facturas(

    id_area: int,

    user: dict = Depends(verify_token)

):

    """

    Muestra, SIN NINGÚN FILTRO de Estado ni Ano, qué hay realmente

    en tb_Facturas para esta área: cuántas filas, qué valores tiene

    Estado, qué valores tiene Ano, y 5 filas de muestra completas.

    Esto es para diagnosticar por qué el dashboard no encuentra nada.

    """
 
    validar_permiso_area(user, id_area)
 
    try:

        todas = execute_query("""

            SELECT *

            FROM tb_Facturas

            WHERE IdArea = ?

        """, (id_area,), fetch=True)
 
        estados_distintos = sorted(set(

            repr(r.get("Estado")) for r in todas

        ))
 
        anios_distintos = sorted(set(

            repr(r.get("Ano")) for r in todas

        ))
 
        muestra = []

        for r in todas[:5]:

            muestra.append({

                "Id": r.get("Id"),

                "NumFactura": r.get("NumFactura"),

                "Estado": repr(r.get("Estado")),

                "Ano": repr(r.get("Ano")),

                "IdArea": repr(r.get("IdArea")),

                "ValorCOP_M2": repr(r.get("ValorCOP_M2")),

            })
 
        return {

            "total_facturas_del_area": len(todas),

            "valores_distintos_de_Estado": estados_distintos,

            "valores_distintos_de_Ano": anios_distintos,

            "muestra_5_filas": muestra

        }
 
    except Exception as e:

        raise HTTPException(500, f"Error en diagnóstico: {str(e)}")
 
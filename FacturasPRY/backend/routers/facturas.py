from fastapi import APIRouter, HTTPException, Depends

from db.connection import execute_query

from auth.jwt import verify_token

from auth.permisos import validar_permiso_area
 
router = APIRouter(prefix="/facturas", tags=["Facturas"])
 
 
# =========================================================

# 📋 FACTURAS POR ÁREA

# =========================================================
 
@router.get("/area/{id_area}")

def facturas_area(id_area: int, user: dict = Depends(verify_token)):
 
    validar_permiso_area(user, id_area)
 
    try:

        rows = execute_query("""

            SELECT

                f.Id,

                f.NumFactura,

                f.Estado,

                f.FechaFacturacion,

                f.ValorCOP_M1,

                f.ValorCOP_M2,

                f.FechaM2,

                f.IdVertical,

                f.IdAgrupacion,

                f.Tipo,

                f.Mes,

                f.Periodicidad

            FROM tb_Facturas f

            WHERE f.IdArea = ?

            ORDER BY f.Id DESC

        """, (id_area,), fetch=True)
 
        for r in rows:

            if r.get("FechaFacturacion"):

                r["FechaFacturacion"] = str(r["FechaFacturacion"])

            if r.get("FechaM2"):

                r["FechaM2"] = str(r["FechaM2"])

            if r.get("ValorCOP_M1") is None:

                r["ValorCOP_M1"] = 0

            if r.get("ValorCOP_M2") is None:

                r["ValorCOP_M2"] = 0
 
        return rows
 
    except Exception as e:

        raise HTTPException(500, f"Error cargando facturas: {str(e)}")
 
 
# =========================================================

# ⏳ FACTURAS PENDIENTES (usado por el Simulador de Presupuesto)

# =========================================================

# Antes no existía: client.py -> get_facturas_pendientes() llamaba a

# /facturas/pendientes/{id_area}, una ruta que nunca se creó en el

# backend. Por eso el simulador siempre daba 404 ("not found"), no un

# problema de datos ni de Estado.
 
@router.get("/pendientes/{id_area}")

def facturas_pendientes(id_area: int, user: dict = Depends(verify_token)):
 
    validar_permiso_area(user, id_area)
 
    try:

        rows = execute_query("""

            SELECT

                f.Id,

                f.NumFactura,

                f.Estado,

                f.FechaFacturacion,

                f.ValorCOP_M1,

                f.IdVertical,

                f.Mes,

                f.Ano

            FROM tb_Facturas f

            WHERE f.IdArea = ?

              AND f.Estado = 'Pendiente'

            ORDER BY f.FechaFacturacion ASC

        """, (id_area,), fetch=True)
 
        for r in rows:

            if r.get("FechaFacturacion"):

                r["FechaFacturacion"] = str(r["FechaFacturacion"])

            if r.get("ValorCOP_M1") is None:

                r["ValorCOP_M1"] = 0
 
        return rows
 
    except Exception as e:

        raise HTTPException(500, f"Error cargando facturas pendientes: {str(e)}")
 
 
# =========================================================

# ✏️ ACTUALIZAR FACTURA

# =========================================================
 
@router.put("/{id_factura}")

def actualizar_factura(

    id_factura: int,

    data: dict,

    user: dict = Depends(verify_token)

):

    try:

        # 🔍 Verificar que existe

        rows = execute_query("""

            SELECT IdArea FROM tb_Facturas WHERE Id = ?

        """, (id_factura,), fetch=True)
 
        if not rows:

            raise HTTPException(404, "Factura no encontrada")
 
        factura = rows[0]
 
        # 🔐 Validar permisos

        validar_permiso_area(user, factura["IdArea"])
 
        # 🛠️ Update

        execute_query("""

            UPDATE tb_Facturas

            SET

                Mes = ?,

                Tipo = ?,

                IdVertical = ?,

                IdAgrupacion = ?,

                Periodicidad = ?

            WHERE Id = ?

        """, (

            data.get("Mes"),

            data.get("Tipo"),

            data.get("IdVertical"),

            data.get("IdAgrupacion"),

            data.get("Periodicidad"),

            id_factura

        ), fetch=False)
 
        return {"msg": "Factura actualizada correctamente"}
 
    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(500, f"Error actualizando factura: {str(e)}")
 
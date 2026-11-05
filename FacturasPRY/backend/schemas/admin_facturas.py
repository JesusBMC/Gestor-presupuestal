from fastapi import APIRouter, HTTPException
from db.connection import get_connection
from schemas.factura import FacturaUpdate

router = APIRouter(prefix="/admin", tags=["Admin Facturas"])


# =========================
# 🔍 GET FACTURAS
# =========================
@router.get("/facturas")
def get_facturas():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Id, NumFactura, Estado, FechaRecepcion, Descripcion
        FROM tb_Facturas
        WHERE activo = 1
        ORDER BY Id DESC
    """)

    rows = cursor.fetchall()

    result = []
    for r in rows:
        result.append({
            "Id": r[0],
            "NumFactura": r[1],
            "Estado": r[2],
            "FechaRecepcion": str(r[3]) if r[3] else None,
            "Descripcion": r[4]
        })

    return result


# =========================
# ✏️ PUT EDITAR
# =========================
@router.put("/facturas/{id}")
def update_factura(id: int, data: FacturaUpdate):

    data = data.dict(exclude_unset=True)

    campos_prohibidos = [
        "IdProveedor",
        "ValorTotalFactura",
        "ValorCOP_M1",
        "ValorCOP_M2"
    ]

    for campo in data.keys():
        if campo in campos_prohibidos:
            raise HTTPException(
                status_code=400,
                detail="No está permitido modificar campos financieros o proveedor"
            )

    campos_permitidos = ["NumFactura", "Estado", "FechaRecepcion", "Descripcion"]

    updates = []
    values = []

    for campo in campos_permitidos:
        if campo in data:
            updates.append(f"{campo}=?")
            values.append(data[campo])

    if not updates:
        raise HTTPException(status_code=400, detail="No hay campos válidos para actualizar")

    values.append(id)

    query = f"""
        UPDATE tb_Facturas
        SET {', '.join(updates)}
        WHERE Id = ?
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(query, values)
    conn.commit()

    return {"message": "Factura actualizada correctamente"}


# =========================
# 🗑️ DELETE SOFT
# =========================
@router.delete("/facturas/{id}")
def delete_factura(id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tb_Facturas
        SET activo = 0
        WHERE Id = ?
    """, (id,))

    conn.commit()

    return {"message": "Factura eliminada (soft delete)"}

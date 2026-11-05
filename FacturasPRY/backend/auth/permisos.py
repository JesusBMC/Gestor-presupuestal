from fastapi import HTTPException


def validar_permiso_area(user: dict, area_requerida: int) -> None:
    """
    Valida que el usuario tenga permiso sobre el área solicitada.
    Lanza HTTPException si no lo tiene. No retorna nada útil,
    así que no dependas de un valor de retorno.
    """
    if user.get("rol") == 1:
        return  # admin, acceso total

    if user.get("area") != area_requerida:
        raise HTTPException(status_code=403, detail="No tienes permiso en esa área")


def validar_rol(user: dict, rol_requerido: int) -> None:
    """
    Valida que el usuario tenga el rol requerido (o sea admin).
    """
    if user.get("rol") != rol_requerido and user.get("rol") != 1:
        raise HTTPException(status_code=403, detail="No tienes permiso")
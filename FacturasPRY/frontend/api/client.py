import requests
import streamlit as st

BASE_URL = "http://localhost:8000"


# ============================================================
# HEADERS
# ============================================================

def get_headers():

    if "access_token" not in st.session_state:
        return {}

    return {
        "Authorization": f"Bearer {st.session_state['access_token']}"
    }


# ============================================================
# FUNCIÓN CENTRAL
# ============================================================

def request_api(method, endpoint, data=None, params=None):

    try:

        response = requests.request(
            method=method,
            url=f"{BASE_URL}{endpoint}",
            json=data,
            params=params,
            headers=get_headers(),
            timeout=10
        )

        if response.status_code == 200:
            return True, response.json()

        return False, {
            "status": response.status_code,
            "error": response.text
        }

    except Exception as e:

        return False, {
            "error": str(e)
        }


# ============================================================
# AUTH
# ============================================================

def login(email, password):

    return request_api(
        "POST",
        "/auth/login",
        {
            "email": email,
            "password": password
        }
    )


# ============================================================
# ÁREAS
# ============================================================

def get_areas():

    return request_api(
        "GET",
        "/areas/"
    )


def crear_area(nombre, descripcion):

    return request_api(
        "POST",
        "/areas/",
        {
            "Nombre": nombre,
            "Descripcion": descripcion
        }
    )


def editar_area(id_area, nombre, descripcion, activo):

    return request_api(
        "PUT",
        f"/areas/{id_area}",
        {
            "Nombre": nombre,
            "Descripcion": descripcion,
            "Activo": activo
        }
    )


def eliminar_area(id_area):

    return request_api(
        "DELETE",
        f"/areas/{id_area}"
    )


# ============================================================
# DASHBOARD
# ============================================================

def get_gasto_por_agrupacion(id_area, periodo):

    return request_api(
        "GET",
        f"/dashboard/{id_area}/agrupacion",
        params={
            "periodo": periodo
        }
    )


def get_resumen_area(id_area, periodo):

    return request_api(
        "GET",
        f"/dashboard/{id_area}/resumen",
        params={
            "periodo": periodo
        }
    )


def get_gasto_mensual(id_area, periodo):

    return request_api(
        "GET",
        f"/dashboard/{id_area}/gasto-mensual",
        params={
            "periodo": periodo
        }
    )


# ============================================================
# AGRUPACIONES
# ============================================================

def get_agrupaciones(id_area):

    return request_api(
        "GET",
        f"/agrupaciones/{id_area}"
    )


def crear_agrupacion(id_area, nombre):

    return request_api(
        "POST",
        "/agrupaciones/",
        {
            "IdArea": id_area,
            "Nombre": nombre
        }
    )


def editar_agrupacion(id_agrupacion, nombre, activo):

    return request_api(
        "PUT",
        f"/agrupaciones/{id_agrupacion}",
        {
            "Nombre": nombre,
            "Activo": activo
        }
    )


def eliminar_agrupacion(id_agrupacion):

    return request_api(
        "DELETE",
        f"/agrupaciones/{id_agrupacion}"
    )


# ============================================================
# VERTICALES
# ============================================================

def get_verticales(id_area):

    return request_api(
        "GET",
        f"/verticales/{id_area}"
    )


def crear_vertical(id_area, nombre):

    return request_api(
        "POST",
        "/verticales/",
        {
            "IdArea": id_area,
            "Nombre": nombre
        }
    )


def editar_vertical(id_vertical, nombre, activo):

    return request_api(
        "PUT",
        f"/verticales/{id_vertical}",
        {
            "Nombre": nombre,
            "Activo": activo
        }
    )


def eliminar_vertical(id_vertical):

    return request_api(
        "DELETE",
        f"/verticales/{id_vertical}"
    )


# ============================================================
# PRESUPUESTO GENERAL
# Tipo="General" en tb_Presupuesto
# ============================================================

def get_presupuesto_general(id_area, ano):

    """
    Devuelve el presupuesto general del área para ese año,
    o None si todavía no existe.
    """

    return request_api(
        "GET",
        f"/presupuesto/general/{id_area}",
        params={
            "ano": ano
        }
    )


def guardar_presupuesto_general(id_area, ano, monto):

    """
    Crea o actualiza (upsert) el presupuesto general
    del área/año.
    """

    return request_api(
        "POST",
        "/presupuesto/general",
        {
            "IdArea": id_area,
            "Ano": ano,
            "MontoAsignado": monto
        }
    )


# ============================================================
# PRESUPUESTO OPEX / CAPEX
# Tipo="OPEX" / Tipo="CAPEX"
# ============================================================

def get_presupuesto_tipo(id_area, ano):

    """
    Obtiene los presupuestos OPEX/CAPEX del área para un año.

    Retorna las filas existentes de Tipo='OPEX' y
    Tipo='CAPEX'.
    """

    return request_api(
        "GET",
        f"/presupuesto/tipo/{id_area}",
        params={
            "ano": ano
        }
    )


def guardar_presupuesto_tipo(id_area, ano, tipo, monto):

    """
    Crea o actualiza (upsert) el presupuesto OPEX/CAPEX.

    tipo:
        - OPEX
        - CAPEX
    """

    return request_api(
        "POST",
        "/presupuesto/tipo",
        {
            "IdArea": id_area,
            "Ano": ano,
            "Tipo": tipo,
            "MontoAsignado": monto
        }
    )


# ============================================================
# PRESUPUESTO MENSUAL
# Tipo="Mensual" en tb_Presupuesto
# ============================================================

def get_presupuesto(id_area, ano=None):

    params = {
        "ano": ano
    } if ano else None

    return request_api(
        "GET",
        f"/presupuesto/{id_area}",
        params=params
    )


def crear_presupuesto(id_area, ano, mes, monto):

    return request_api(
        "POST",
        "/presupuesto/",
        {
            "IdArea": id_area,
            "Ano": ano,
            "Mes": mes,
            "MontoAsignado": monto
        }
    )


def editar_presupuesto(id_presupuesto, monto):

    return request_api(
        "PUT",
        f"/presupuesto/{id_presupuesto}",
        {
            "MontoAsignado": monto
        }
    )


def eliminar_presupuesto(id_presupuesto):

    return request_api(
        "DELETE",
        f"/presupuesto/{id_presupuesto}"
    )


# ============================================================
# FACTURAS
# Módulo final: pendientes + gestor de clasificación
# ============================================================

def get_facturas_pendientes(id_area):

    """
    Facturas pendientes/aprobadas de un área,
    con indicador de vertical asignada.
    """

    return request_api(
        "GET",
        f"/facturas/pendientes/{id_area}"
    )


def get_facturas_area(id_area):

    """
    Todas las facturas de un área,
    usadas en el gestor de clasificación.
    """

    return request_api(
        "GET",
        f"/facturas/area/{id_area}"
    )


def anexar_factura_vertical(id_factura, id_vertical):

    """
    Asigna o reasigna la vertical de una factura.
    """

    return request_api(
        "POST",
        "/facturas/anexar-vertical",
        {
            "IdFactura": id_factura,
            "IdVertical": id_vertical
        }
    )


# ============================================================
# SIMULACIÓN
# ============================================================

def simular_presupuesto(factura_ids, id_area):

    return request_api(
        "POST",
        "/simulacion/calcular",
        {
            "facturaIds": factura_ids,
            "IdArea": id_area
        }
    )


# ============================================================
# USUARIOS
# ============================================================

def get_usuarios():

    return request_api(
        "GET",
        "/usuarios"
    )


def crear_usuario(
    nombre,
    email,
    password,
    id_area,
    id_rol,
    activo=True
):

    return request_api(
        "POST",
        "/usuarios",
        {
            "Nombre": nombre,
            "Email": email,
            "Contraseña": password,
            "IdArea": id_area,
            "IdRol": id_rol,
            "Activo": activo
        }
    )


def editar_usuario(
    id_usuario,
    nombre,
    email,
    password,
    id_area,
    id_rol,
    activo=True
):

    return request_api(
        "PUT",
        f"/usuarios/{id_usuario}",
        {
            "Nombre": nombre,
            "Email": email,
            "Contraseña": password,
            "IdArea": id_area,
            "IdRol": id_rol,
            "Activo": activo
        }
    )


def eliminar_usuario(id_usuario):

    return request_api(
        "DELETE",
        f"/usuarios/{id_usuario}"
    )


# ============================================================
# ADMIN FACTURAS
# ============================================================

def get_facturas_admin():

    return request_api(
        "GET",
        "/admin/facturas"
    )


def editar_factura(
    id_factura,
    num_factura,
    estado,
    fecha_recepcion,
    descripcion
):

    return request_api(
        "PUT",
        f"/admin/facturas/{id_factura}",
        {
            "NumFactura": num_factura,
            "Estado": estado,
            "FechaRecepcion": fecha_recepcion,
            "Descripcion": descripcion
        }
    )


def eliminar_factura(id_factura):

    return request_api(
        "DELETE",
        f"/admin/facturas/{id_factura}"
    )


def actualizar_factura(id_factura, data):

    return request_api(
        "PUT",
        f"/facturas/{id_factura}",
        data=data
    )


# ============================================================
# PROYECCIÓN DE GASTOS
# tb_ProyeccionGasto
# ============================================================

def get_proyeccion_gasto(id_area, ano):

    """
    Obtiene todas las proyecciones de gastos del área/año.

    Incluye:
        - Proyecciones por Agrupación
        - Proyecciones OPEX/CAPEX
    """

    return request_api(
        "GET",
        f"/presupuesto/proyeccion/{id_area}",
        params={
            "ano": ano
        }
    )


def guardar_proyeccion_gasto_batch(id_area, ano, datos):

    """
    Guarda la matriz completa de proyecciones por Agrupación.

    Payload:
        {
            "IdArea": int,
            "Ano": int,
            "datos": [...]
        }
    """

    return request_api(
        "POST",
        "/presupuesto/proyeccion/batch",
        {
            "IdArea": id_area,
            "Ano": ano,
            "datos": datos
        }
    )


def guardar_proyeccion_tipo_batch(id_area, ano, datos):

    """
    Guarda la matriz completa de proyecciones OPEX/CAPEX.

    Payload:
        {
            "IdArea": int,
            "Ano": int,
            "datos": [...]
        }

    Cada elemento de datos contiene:

        {
            "IdArea": int,
            "Ano": int,
            "Mes": int,
            "Tipo": "OPEX" | "CAPEX",
            "IdVertical": int | None,
            "MontoProyectado": float
        }
    """

    return request_api(
        "POST",
        "/presupuesto/proyeccion-tipo/batch",
        {
            "IdArea": id_area,
            "Ano": ano,
            "datos": datos
        }
    )


def eliminar_proyeccion_gasto(id_proyeccion):

    """
    Elimina una proyección específica por ID.
    """

    return request_api(
        "DELETE",
        f"/presupuesto/proyeccion/{id_proyeccion}"
    )


# ============================================================
# VALIDACIÓN DE FACTURAS
# Nuevo router: facturas_validacion_v2
# ============================================================

def get_facturas_con_simulacion(id_area: int, ano: int):

    """
    Obtiene facturas PENDIENTES con simulación de aprobación.

    NO modifica BD.
    Solo retorna datos para preview.
    """

    try:

        url = f"{BASE_URL}/facturas-validacion/{id_area}/{ano}"

        headers = get_headers()

        response = requests.get(
            url,
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            return True, response.json()

        try:
            detalle = response.json()

        except Exception:
            detalle = {
                "error": response.text
            }

        return False, {
            "status": response.status_code,
            "error": detalle
        }

    except Exception as e:

        return False, {
            "error": str(e)
        }


def aprobar_factura_confirmar(
    id_factura: int,
    confirmado: bool = True
):

    """
    Confirma la aprobación de una factura.

    Este endpoint modifica BD.
    """

    try:

        url = f"{BASE_URL}/facturas-validacion/{id_factura}/aprobar"

        headers = get_headers()

        payload = {
            "confirmado": confirmado
        }

        response = requests.put(
            url,
            json=payload,
            headers=headers
        )

        response.raise_for_status()

        return True, response.json()

    except Exception as e:

        return False, {
            "error": str(e)
        }


def rechazar_factura(
    id_factura: int,
    motivo: str = None
):

    """
    Rechaza una factura.

    Este endpoint modifica BD.
    """

    try:

        url = f"{BASE_URL}/facturas-validacion/{id_factura}/rechazar"

        headers = get_headers()

        params = {}

        if motivo:
            params["motivo"] = motivo

        response = requests.put(
            url,
            params=params,
            headers=headers
        )

        response.raise_for_status()

        return True, response.json()

    except Exception as e:

        return False, {
            "error": str(e)
        }
    
def simular_facturas(id_area, ano, ids):

    return request_api(
        "POST",
        f"/facturas-validacion/{id_area}/{ano}/simular",
        {
            "ids": ids
        }
    )


# ============================================================
# CONSUMIR FACTURAS
# ============================================================

def consumir_facturas(id_area: int, ano: int):

    """
    Ejecuta el consumo de facturas aprobadas (Descontado=False)
    y llena tb_Consumo agrupando por:

        Mes + IdAgrupacion

    IdVertical NO participa en el consumo.

    Este endpoint modifica BD.
    """

    try:

        url = f"{BASE_URL}/consumir-facturas/{id_area}/{ano}"

        headers = get_headers()

        response = requests.post(
            url,
            headers=headers
        )

        response.raise_for_status()

        return True, response.json()

    except Exception as e:

        return False, {
            "error": str(e)
        }
# ============================================================
# DASHBOARD DE PRESUPUESTO (Agrupación + Tipo, mensual)
# ============================================================

def get_dashboard_presupuesto(id_area: int, ano: int):
    """
    Obtiene proyección y consumo mensual agregados por Agrupación
    y por Tipo (CAPEX/OPEX), anclados al Presupuesto General.
    """

    return request_api(
        "GET",
        f"/dashboard-presupuesto/{id_area}/{ano}"
    )
    

# ============================================================
# ROLES
# ============================================================

def get_roles():

    return request_api(
        "GET",
        "/usuarios/roles"
    )

# ============================================================
# CREWAI — CLASIFICACIÓN PRESUPUESTAL
# ============================================================

def iniciar_clasificacion_ia(
    archivo_csv,
    email_destino,
    modo,
    validaciones
):
    """
    Carga el CSV e inicia el orquestador CrewAI.
    """

    try:
        url = f"{BASE_URL}/crew-ai/ejecuciones"

        files = {
            "csv_sin_clasificar": (
                archivo_csv.name,
                archivo_csv.getvalue(),
                "text/csv"
            )
        }

        data = {
            "email_destino": email_destino,
            "modo": modo,
            "validaciones": validaciones
        }

        response = requests.post(
            url,
            files=files,
            data=data,
            headers=get_headers(),
            timeout=30
        )

        if 200 <= response.status_code < 300:
            return True, response.json()

        return False, {
            "status": response.status_code,
            "error": response.text
        }

    except Exception as e:
        return False, {
            "error": str(e)
        }


def get_estado_clasificacion_ia(run_id):
    """
    Consulta el estado y resultado de una ejecución.
    """

    return request_api(
        "GET",
        f"/crew-ai/ejecuciones/{run_id}"
    )


# Pegar AL FINAL de tu api/client.py. Reutiliza request_api y get_headers.
def get_consumo_proveedores(id_area, ano, mes_corte=None, tipo=None):
    params = {}
    if mes_corte is not None:
        params["mes_corte"] = int(mes_corte)
    if tipo and tipo != "TODOS":
        params["tipo"] = tipo
    return request_api("GET", f"/consumo-proveedores/{int(id_area)}/{int(ano)}", params=params)


def get_esquema_consumo_proveedores(id_area):
    return request_api("GET", f"/consumo-proveedores/{int(id_area)}/esquema")

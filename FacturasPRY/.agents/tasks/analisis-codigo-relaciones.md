# Análisis Senior: Relaciones del Sistema y Calidad del Código — FacturasPRY

---

## RESUMEN EJECUTIVO

El proyecto es un sistema de control presupuestal corporativo con una arquitectura correcta en su capa de transporte (FastAPI + Streamlit + Access/pyodbc) y reglas de negocio genuinamente bien pensadas. Los módulos más recientes (facturas_validacion, consumo_proveedores, presupuesto) muestran escritura madura: separación de responsabilidades, cachés por bucket, transacciones explícitas y documentación del razonamiento. Los módulos más viejos (admin.py del frontend, areas.py del backend, schemas/admin_facturas.py) muestran patrones de prototipo que nunca se actualizaron y conviven con el código nuevo creando inconsistencias estructurales serias. El mayor riesgo operativo es la **existencia de una ruta completa sin autenticación** en `schemas/admin_facturas.py` y un **bug de argumentos** en `areas.py` que hace que crear o actualizar áreas falle silenciosamente.

---

## 1. MAPA DE RELACIONES DEL SISTEMA

### Tablas de base de datos (Access .accdb)

| Tabla | Propósito | Módulos que la tocan |
|---|---|---|
| `tb_Usuario` | Credenciales y roles | `auth.py`, `usuarios.py` |
| `tb_Roles` | Catálogo de roles | `usuarios.py` |
| `tb_Area` | Áreas del negocio | `areas.py`, `agrupaciones.py`, `verticales.py`, todos los routers con `id_area` |
| `tb_Agrupacion` | Dimensión de gasto por agrupación | `agrupaciones.py`, `facturas_validacion.py`, `consumo.py`, `dashboard_presupuesto.py` |
| `tb_Vertical` | Dimensión de clasificación | `verticales.py`, `facturas.py`, `dashboard.py` |
| `tb_Facturas` | Facturas cargadas desde el ERP | `facturas.py`, `facturas_validacion.py`, `simulacion.py`, `consumo.py`, `consumo_proveedores.py` |
| `tb_Presupuesto` | Presupuesto General / OPEX / CAPEX / Mensual | `presupuesto.py`, `simulacion.py`, `dashboard.py`, `dashboard_presupuesto.py` |
| `tb_ProyeccionGasto` | Matriz Mes × Agrupación / Mes × Tipo | `presupuesto.py`, `facturas_validacion.py`, `dashboard_presupuesto.py` |
| `tb_Consumo` | Acumulado de facturas aprobadas | `consumo.py`, `facturas_validacion.py`, `consumo_proveedores.py`, `dashboard_presupuesto.py` |
| `tb_Proveedor` | Catálogo de proveedores | `consumo_proveedores.py` |

---

### FLUJO 1 — Login y autenticación

```
frontend/main.py                    backend/routers/auth.py
  st.text_input(email, password)
  → client.login(email, password)   POST /auth/login
    → LoginSchema(email, password)
    → tb_Usuario WHERE Email = ?
    → verify_password(plain, hash)  ← auth/password.py (bcrypt)
    → create_access_token(sub, rol, area)  ← auth/jwt.py
    ← {access_token, user{id,nombre,email,rol,area}}
  st.session_state["access_token"] = token
  st.session_state["rol"] = usuario.rol
  st.session_state["IdArea"] = usuario.area
```

**Verificación en páginas:** cada página protegida llama `verify_token` vía `Depends`. El token lleva `sub` (usuario_id), `rol` e `area` embebidos — el backend no re-consulta la base de datos en cada request para leer el rol, confía en lo que dice el JWT.

---

### FLUJO 2 — Carga y validación de facturas

Las facturas llegan pre-cargadas a `tb_Facturas` desde un proceso externo (ERP). El sistema no las crea — las gestiona.

```
gestor_facturas.py
  → client.get_facturas_area(id_area)       GET /facturas/area/{id_area}
  → client.get_verticales(id_area)          GET /verticales/{id_area}
  → client.get_agrupaciones(id_area)        GET /agrupaciones/{id_area}
  → client.actualizar_factura(id, data)     PUT /facturas/{id}
      UPDATE tb_Facturas SET Mes, Tipo, IdVertical, IdAgrupacion, Periodicidad

gestor_validacion.py
  → client.get_facturas_con_simulacion(id_area, ano)
      GET /facturas-validacion/{id_area}/{ano}
        → tb_Facturas WHERE Estado='Pendiente'
        → tb_ProyeccionGasto (proyección por Agrupación y por Tipo)
        → tb_Consumo (consumo actual por Agrupación y por Tipo)
        → calcula: cabe_agrupacion = valor <= disponible_agr
        → calcula: cabe_tipo = valor <= disponible_tipo
        → capa estadística: historial de tb_Facturas Aprobadas, burn-rate
  → client.rechazar_factura(id, motivo)
      PUT /facturas-validacion/{id}/rechazar
  → client.consumir_facturas(id_area, ano)
      POST /consumir-facturas/{id_area}/{ano}
        → tb_Facturas WHERE Estado='Aprobado' AND Descontado=0
        → INSERT/UPDATE tb_Consumo (por Agrupación, por Tipo, por Proveedor)
        → UPDATE tb_Facturas SET Descontado=1
```

---

### FLUJO 3 — Presupuesto (carga, consulta, simulación)

```
gestor_presupuesto.py
  → get_presupuesto_general / guardar_presupuesto_general
      GET|POST /presupuesto/general/{id_area}
        → tb_Presupuesto WHERE Tipo='General'
  → get_presupuesto_tipo / guardar_presupuesto_tipo
      GET|POST /presupuesto/tipo/{id_area}
        → tb_Presupuesto WHERE Tipo IN ('OPEX','CAPEX')
        → validar_no_supera_general() antes de escribir
  → guardar_proyeccion_gasto_batch / guardar_proyeccion_tipo_batch
      POST /presupuesto/proyeccion/batch
      POST /presupuesto/proyeccion-tipo/batch
        → DELETE + INSERT/UPDATE en tb_ProyeccionGasto
        → separación por columna: Agrupación (IdAgrupacion NOT NULL, Tipo NULL)
                                   Tipo (Tipo NOT NULL, IdAgrupacion NULL)

simulacion.py (frontend) → /simulacion/calcular (backend)
  → tb_Facturas WHERE Id IN (...) AND Estado='Pendiente'
  → tb_Presupuesto WHERE Tipo='General' → techo duro anual
  → tb_Presupuesto WHERE Tipo='Mensual' → alerta operativa
  → tb_Facturas WHERE Estado='Aprobado' → gasto ya ejecutado
```

---

### FLUJO 4 — Dashboard y reportes

```
dashboard.py (frontend, no en la lista pero consumido por gestor)
  → /dashboard/{id_area}/resumen   → tb_Presupuesto (General) + tb_Facturas (Aprobado)
  → /dashboard/{id_area}/agrupacion → tb_Facturas JOIN tb_Vertical JOIN tb_Agrupacion
  → /dashboard/{id_area}/gasto-mensual → tb_Facturas GROUP BY Mes

dashboard_presupuesto_vista.py
  → get_dashboard_presupuesto(id_area, ano)
      GET /dashboard-presupuesto/{id_area}/{ano}
        → tb_Presupuesto (General)
        → tb_Agrupacion (catálogo)
        → tb_ProyeccionGasto (proyectado mensual)
        → tb_Consumo (consumido mensual)
        → verifica consistencia: vista Agrupación ≈ vista Tipo

Consumo_Proveedores.py
  → get_consumo_proveedores(id_area, ano, mes_corte, tipo)
      GET /consumo-proveedores/{id_area}/{ano}
        → tb_Consumo WHERE IdProvedor > 0
        → tb_Proveedor (catálogo)
        → construir_informe() → proyección, promedio, participación %
```

---

### FLUJO 5 — Administración (usuarios, áreas, agrupaciones)

```
admin_usuarios.py
  → get_roles()        GET /usuarios/roles   → tb_Roles
  → get_areas()        GET /areas/           → tb_Area
  → crear_usuario()    POST /usuarios        → validación email + bcrypt + tb_Usuario

admin_areas.py
  → get_areas()        GET /areas/
  → crear_area()       POST /areas/          → INSERT tb_Area  ← BUG (ver sección 3)
  → editar_area()      PUT /areas/{id}       → UPDATE tb_Area  ← BUG (ver sección 3)

admin_agrupaciones (sin página dedicada en el frontend nuevo;
  se gestiona desde admin.py legado o desde gestor_presupuesto implícitamente)
  → GET|POST|PUT|DELETE /agrupaciones/{id_area}  → tb_Agrupacion
```

---

## 2. QUÉ ESTÁ BIEN ESCRITO

### 2.1 — JWT: falla explícita al arrancar, no en runtime

**Archivo:** `backend/auth/jwt.py`

```python
SECRET_KEY = os.environ["JWT_SECRET_KEY"]  # falla explícito al arrancar si no está seteada
```

Si `JWT_SECRET_KEY` no está en el entorno, el proceso muere al importar el módulo, no al recibir la primera petición. Es el patrón correcto para secretos obligatorios: la falla es temprana, visible y con causa obvia. Contrasta con `config.py` donde `SECRET_KEY` tiene un default inseguro (`"cambiar-en-produccion-con-clave-larga-segura"`) que nunca falla — ese es el antipatrón opuesto.

**Por qué está bien:** en producción el error silencioso peor es el que arranca sin credenciales válidas y firma tokens con una clave pública. Este código lo previene.

---

### 2.2 — Motor de simulación: reglas de negocio documentadas en el código

**Archivo:** `backend/routers/simulacion.py`

```python
# Reglas de negocio (definidas con el equipo):
#   - El presupuesto MENSUAL es el que decide la alerta operativa
#     (verde/amarillo/rojo) que ve el aprobador.
#   - El presupuesto ANUAL (General) es un techo DURO: si la suma
#     de las facturas simuladas hace que el año se pase del General,
#     el sistema BLOQUEA, sin importar cómo esté cualquier mes.
#   - Si un mes no tiene presupuesto mensual asignado todavía, ese
#     mes queda como "sin_dato": es informativo, no bloquea ni alerta
```

Y la implementación honra esas reglas con una jerarquía clara:

```python
if excede_general:
    sugerencia = "bloquear"
elif peor_alerta_mensual == "critico":
    sugerencia = "revisar"
elif peor_alerta_mensual == "warning":
    sugerencia = "aprobar_con_precaucion"
else:
    sugerencia = "aprobar"
```

**Por qué está bien:** el código documenta el *por qué* del diseño, no solo el *qué*. Cualquier desarrollador que modifique esto entiende la jerarquía de decisión sin tener que inferirla. La lógica de techo duro vs. alerta operativa es una distinción de negocio no trivial que está correctamente capturada.

---

### 2.3 — Transacción atómica en consumo de facturas

**Archivo:** `backend/routers/consumo.py`

```python
@router.post("/{id_area}/{ano}")
def consumir_facturas(id_area: int, ano: int, user: dict = Depends(verify_token)):
    validar_permiso_area(user, id_area)
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        respuesta = registrar_lote(conn.cursor(), id_area, ano)
        # Confirmar agrupación, tipo, proveedor y marcas una sola vez.
        conn.commit()
        return respuesta
    except Exception as e:
        if conn is not None:
            conn.rollback()
        raise HTTPException(...)
    finally:
        if conn is not None:
            conn.close()
```

Y dentro de `registrar_lote`, el marcado final tiene una verificación de integridad:

```python
cursor.execute("""
    UPDATE tb_Facturas SET Descontado = 1
    WHERE Id = ? AND IdArea = ? AND Ano = ?
      AND Estado = 'Aprobado' AND Descontado = 0
""", (id_fac, id_area, ano))
if cursor.rowcount != 1:
    raise ValueError("Una factura cambió durante el consumo. Se revierte el lote...")
```

**Por qué está bien:** el consumo actualiza tres tablas distintas (`tb_Consumo` por Agrupación, por Tipo, por Proveedor, y `tb_Facturas`). Si cualquier paso falla, el `rollback` deja la base en el estado anterior. La verificación de `rowcount` detecta race conditions — si dos sesiones intentan consumir la misma factura al mismo tiempo, la segunda lanza excepción y revierte en lugar de duplicar el consumo.

---

### 2.4 — Caché por bucket en facturas_validacion, con separación clara de responsabilidades

**Archivo:** `backend/routers/facturas_validacion.py`

```python
def _stats_historial_agrupacion_cached(cache, cursor, id_area, ano, id_agrupacion, mes_actual):
    """
    Envuelve _get_historial_mensual_agrupacion + _calcular_stats_historial
    con caché por (IdAgrupacion, mes), para no repetir la consulta y el
    cálculo cuando varias facturas pendientes caen en el mismo bucket.
    """
    key = (id_agrupacion, mes_actual)
    if key not in cache:
        historial = _get_historial_mensual_agrupacion(...)
        cache[key] = _calcular_stats_historial(historial)
    return cache[key]
```

**Por qué está bien:** cuando hay 30 facturas pendientes en la misma agrupación del mismo mes, el historial estadístico se calcula una sola vez, no 30 veces. El caché es por-request (un dict pasado en el scope de la función), no global, así que no hay riesgo de datos obsoletos entre peticiones distintas. Es una optimización correcta que no rompe el aislamiento.

---

### 2.5 — Validación de permisos en dos capas: área + rol

**Archivo:** `backend/auth/permisos.py`

```python
def validar_permiso_area(user: dict, area_requerida: int) -> None:
    if user.get("rol") == 1:
        return  # admin, acceso total
    if user.get("area") != area_requerida:
        raise HTTPException(status_code=403, detail="No tienes permiso en esa área")

def validar_rol(user: dict, rol_requerido: int) -> None:
    if user.get("rol") != rol_requerido and user.get("rol") != 1:
        raise HTTPException(status_code=403, detail="No tienes permiso")
```

Y su uso en facturas.py, que primero recupera el área de la factura antes de validar:

```python
rows = execute_query("SELECT IdArea FROM tb_Facturas WHERE Id = ?", (id_factura,), fetch=True)
if not rows:
    raise HTTPException(404, "Factura no encontrada")
factura = rows[0]
validar_permiso_area(user, factura["IdArea"])
```

**Por qué está bien:** no confía en que el cliente envíe el `id_area` correcto. Lo lee de la base de datos, lo que previene que un usuario de Área A apruebe una factura de Área B enviando el parámetro correcto pero el `id_factura` de otra área.

---

### 2.6 — Informe ejecutivo determinístico en el frontend

**Archivo:** `frontend/pages/gestor_validacion.py`

```python
UMBRAL_MARGEN_SANO = 0.15

def generar_informe_ejecutivo(fac):
    """
    Analiza una factura contra sus dos dimensiones y devuelve una
    recomendación determinista con su justificación numérica. No usa
    nada de fac["estadistico"]: ese contexto se muestra aparte,
    nunca decide el veredicto.
    """
```

**Por qué está bien:** la UI separa explícitamente "veredicto determinístico" (basado en aritmética directa) de "contexto estadístico" (informativo, no decide). Esto es arquitectura de información correcta: el aprobador siempre sabe exactamente por qué el sistema dice APROBAR o NO APROBAR, sin que el z-score estadístico contamine la decisión operativa.

---

### 2.7 — consumo_proveedores: pure functions + capa HTTP separada

**Archivo:** `backend/routers/consumo_proveedores.py`

Las funciones `construir_informe()`, `construir_resumen()`, `periodo()` no tienen efectos secundarios: reciben datos, devuelven datos. La capa HTTP (`@router.get`) está al final del archivo y se limita a orquestar llamadas. Esto permite que la lógica de negocio sea testeable independientemente del framework.

```python
def construir_informe(facturas, id_area, ano, mes_corte=None, tipo=None, hoy=None):
    """facturas contiene solo registros Aprobado + Descontado, de un área/año."""
    hoy = hoy or date.today()
    ...
```

El parámetro `hoy=None` con default al momento de ejecución es exactamente el patrón correcto para hacer la función testeable con fechas arbitrarias.

---

## 3. QUÉ ESTÁ MAL ESCRITO

### 3.1 — BUG REAL: `areas.py` — `cursor.execute()` recibe argumentos sueltos en vez de tupla

**Archivo:** `backend/routers/areas.py`

```python
# CREAR ÁREA — línea real del archivo
cursor.execute("""
    INSERT INTO tb_Area
        (Nombre, Descripcion, activo)
    VALUES (?, ?, -1)
""",
    area.Nombre,       # ← ERROR: argumento suelto, no en tupla
    area.Descripcion   # ← ERROR: argumento suelto, no en tupla
)
```

Lo mismo ocurre en `update_area` y `delete_area`:

```python
cursor.execute("""UPDATE tb_Area SET Nombre=?, Descripcion=?, activo=? WHERE Id=?""",
    area.Nombre, area.Descripcion, -1 if area.Activo else 0, id_area  # ← ERROR
)
cursor.execute("UPDATE tb_Area SET activo=0 WHERE Id=?", id_area)  # ← ERROR: debería ser (id_area,)
```

**Qué produce en la práctica:** `pyodbc.cursor.execute()` acepta `(query, params)` donde `params` es una secuencia. Cuando se pasan argumentos posicionales adicionales, pyodbc los ignora o lanza `TypeError: execute() takes from 2 to 3 positional arguments`. Crear o actualizar un área desde el frontend lanza un 500 silencioso. La operación de lectura (`GET /areas/`) funciona porque no tiene parámetros.

**Cómo debe escribirse:**
```python
cursor.execute(
    "INSERT INTO tb_Area (Nombre, Descripcion, activo) VALUES (?, ?, -1)",
    (area.Nombre, area.Descripcion)   # ← tupla
)
cursor.execute(
    "UPDATE tb_Area SET activo=0 WHERE Id=?",
    (id_area,)   # ← tupla con coma
)
```

---

### 3.2 — BUG DE ARCHIVO MAL COLOCADO: `schemas/admin_facturas.py` es un router sin registrar

**Archivo:** `backend/schemas/admin_facturas.py`

El archivo se llama `admin_facturas.py` y está en la carpeta `schemas/`, pero no contiene un schema de Pydantic: contiene un **router de FastAPI completo** con tres endpoints (`GET /admin/facturas`, `PUT /admin/facturas/{id}`, `DELETE /admin/facturas/{id}`).

```python
# backend/schemas/admin_facturas.py — encabezado real
from fastapi import APIRouter, HTTPException
from db.connection import get_connection
from schemas.factura import FacturaUpdate   # ← importa schemas.factura que NO EXISTE

router = APIRouter(prefix="/admin", tags=["Admin Facturas"])

@router.get("/facturas")
def get_facturas():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""...""")  # ← SIN autenticación, SIN Depends(verify_token)
```

**Tres problemas en uno:**

1. **Está en la carpeta equivocada.** Pertenece a `routers/`, no a `schemas/`. Nada en `main.py` lo importa ni registra, así que los tres endpoints son código muerto.

2. **No tiene autenticación.** Si alguien lo registrara en `main.py`, `GET /admin/facturas` devolvería todas las facturas del sistema sin token. `DELETE /admin/facturas/{id}` borraría (soft delete) cualquier factura sin verificar quién es el usuario.

3. **Importa `schemas.factura.FacturaUpdate` que no existe** en ningún archivo del proyecto. Intentar importar este módulo lanzaría `ModuleNotFoundError` al arrancar.

**El frontend en `client.py` sí llama a `/admin/facturas`:**
```python
def get_facturas_admin():
    return request_api("GET", "/admin/facturas")
```
Estas llamadas siempre devuelven 404 porque el router nunca se registró.

---

### 3.3 — INCONSISTENCIA CRÍTICA: `agrupaciones.py` y `verticales.py` pasan el objeto `user` completo a funciones que esperan solo el `user_id`

**Archivos:** `backend/routers/agrupaciones.py`, `backend/routers/verticales.py`

```python
# agrupaciones.py
@router.get("/{id_area}")
def get_agrupaciones(
    id_area: int,
    usuario_id: int = Depends(verify_token)  # ← verify_token devuelve un DICT, no un int
):
    validar_permiso_area(usuario_id, id_area)  # ← pasa el dict como primer arg
```

`verify_token` devuelve:
```python
return {
    "usuario_id": usuario_id,
    "rol": rol,
    "area": area
}
```

Pero `agrupaciones.py` y `verticales.py` declaran `usuario_id: int = Depends(verify_token)`, esperando un `int`. FastAPI no rechaza el tipo incorrecto en `Depends` — lo asigna tal cual. Así que `usuario_id` es en realidad un `dict`.

Cuando `validar_permiso_area(usuario_id, id_area)` se llama:
```python
def validar_permiso_area(user: dict, area_requerida: int) -> None:
    if user.get("rol") == 1:
        return
    if user.get("area") != area_requerida:
        raise HTTPException(...)
```

Si `usuario_id` fuera un `int` (como el tipo declara), `user.get("rol")` retornaría `None` (los ints no tienen `.get()`). Pero como en la práctica es un `dict`, funciona por accidente: `dict.get("rol")` sí existe.

**Lo que produce en práctica:** el código funciona accidentalmente porque el tipo declarado es incorrecto pero Python no lo fuerza. Si alguien "corrige" el tipo a `int` o cambia `verify_token` para que devuelva el id directamente, la validación de permisos se rompe silenciosamente y cualquier usuario puede acceder a cualquier área.

**Cómo debe estar en todos los routers:**
```python
user: dict = Depends(verify_token)  # consistente con el tipo real devuelto
```

---

### 3.4 — `admin.py` del frontend: archivo abandonado con tres anti-patrones de seguridad

**Archivo:** `frontend/pages/admin.py`

```python
# Protección
if "user" not in st.session_state:
    st.switch_page("main.py")

if st.session_state["user"]["rol"] != 1:
    st.error("No tienes permisos")
    st.stop()
```

**Problema 1:** el resto del sistema usa `st.session_state["access_token"]` y `st.session_state["rol"]`, pero este archivo usa `st.session_state["user"]["rol"]`. Como `"user"` nunca se guarda en `session_state` (el login en `main.py` guarda `"rol"`, no `"user"`), la protección lanza `KeyError` inmediatamente y el `if "user" not in st.session_state` se cumple siempre. El resultado es que la página redirige siempre a `main.py` sin mostrar error útil.

**Problema 2:** llama a `requests.get(f"{BASE_URL}/users")` directamente, sin usar `get_headers()` ni `client.py`. No envía el token Bearer.

**Problema 3:** el endpoint `/users` no existe en `main.py` — todas las rutas de usuarios están bajo `/usuarios`. Estas llamadas siempre devuelven 404.

Este archivo es código muerto pero genera confusión porque está en la misma carpeta que los archivos activos.

---

### 3.5 — `simulacion.py` del frontend lee un campo que no existe en la respuesta

**Archivo:** `frontend/pages/simulacion.py`

```python
for factura in facturas:
    with col_fecha:
        st.write(factura['FechaRecepcion'][:10] if factura.get('FechaRecepcion') else "-")
```

Pero el endpoint `GET /facturas/pendientes/{id_area}` devuelve:

```python
# backend/routers/facturas.py
rows = execute_query("""
    SELECT f.Id, f.NumFactura, f.Estado, f.FechaFacturacion,
           f.ValorCOP_M1, f.IdVertical, f.Mes, f.Ano
    FROM tb_Facturas f ...
""")
for r in rows:
    if r.get("FechaFacturacion"):
        r["FechaFacturacion"] = str(r["FechaFacturacion"])
```

El campo se llama `FechaFacturacion`, no `FechaRecepcion`. El frontend llama a `.get('FechaRecepcion')` que retorna `None`, y la columna fecha siempre muestra `"-"` aunque las facturas tengan fecha. No es un crash, es un dato silenciosamente incorrecto en la UI.

---

### 3.6 — `execute_query` abre y cierra una conexión nueva por cada llamada

**Archivo:** `backend/db/connection.py`

```python
def execute_query(query, params=(), fetch=True, is_write=False):
    conn = get_connection()   # ← nueva conexión
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        ...
        conn.commit()
        return results
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()  # ← cierra inmediatamente
```

**Problema:** en routers como `simulacion.py`, que hace entre 8 y 15 queries en una sola petición, cada query abre y cierra una conexión ODBC a Access. El modelo correcto para un request multi-query es abrir una conexión al inicio y cerrarla al final (como ya hacen los routers bien escritos: `facturas_validacion.py`, `consumo.py`, `dashboard_presupuesto.py`).

Los routers `facturas.py` y `dashboard.py` usan `execute_query` para múltiples llamadas independientes — cada una abre una conexión nueva. No es un bug de corrección (cada llamada hace commit correcto) pero es una deuda de rendimiento y estabilidad: Access ODBC tiene límites de conexiones concurrentes bajos.

**Inconsistencia resultante:** el código tiene dos patrones de acceso a base de datos mezclados en el mismo proyecto: `execute_query()` (una conexión por query) y `get_connection()` manual (una conexión por request). Los módulos nuevos usan el segundo; los viejos el primero.

---

### 3.7 — `gestor_facturas.py`: crash si la vertical/agrupación de una factura no está en la lista actual

**Archivo:** `frontend/pages/gestor_facturas.py`

```python
vertical_nombre = st.selectbox(
    "Vertical",
    lista_verticales,
    index=lista_verticales.index(vertical_actual_nombre)   # ← ValueError si no está
    if vertical_actual_nombre in lista_verticales
    else 0
)
```

El guard `if vertical_actual_nombre in lista_verticales` protege el `index()` — bien. Pero para `periodicidad`:

```python
periodicidad = st.selectbox(
    "Periodicidad (días)",
    periodicidad_opciones,
    index=periodicidad_opciones.index(periodicidad_actual)   # ← ValueError sin guard
    if periodicidad_actual in periodicidad_opciones
    else 2
)
```

Aquí sí hay guard. Sin embargo, si `factura_sel` llega con `IdVertical` o `IdAgrupacion` que apunta a una entidad eliminada (desactivada desde admin), `vertical_reverse.get(vertical_actual_id)` devuelve `None`, el guard `if vertical_actual_nombre in lista_verticales` falla, y el selectbox muestra la primera vertical de la lista como si fuera la correcta — el usuario puede guardar sin darse cuenta que está cambiando la vertical de la factura a otra distinta.

Es un fallo silencioso de integridad de datos que ocurre cuando se desactivan verticales o agrupaciones que ya tienen facturas asignadas.

---

### 3.8 — `main.py` del frontend: `st.switch_page` con rutas inconsistentes

**Archivo:** `frontend/main.py`

```python
elif pagina == "Dashboard presupuesto":
    st.switch_page("pages/Dashboard_presupuesto")   # ← sin extensión .py

elif pagina == "Proveedores":
    st.switch_page("pages/Consumo_Proveedores")     # ← sin extensión .py
```

Versus el resto del mismo archivo:
```python
st.switch_page("pages/admin_usuarios.py")   # ← con extensión .py
st.switch_page("pages/gestor_presupuesto.py")
```

Streamlit acepta ambas formas en versiones recientes pero el comportamiento varía por versión. La mezcla es una inconsistencia que producirá errores difíciles de diagnosticar al actualizar Streamlit.

---

### 3.9 — `Consumo_Proveedores.py`: comparación de rol con string en lugar de int

**Archivo:** `frontend/pages/Consumo_Proveedores.py`

```python
if str(st.session_state.get("rol")) not in ("1", "2"):
    st.error("Solo Gestor o Admin pueden acceder.")
    st.stop()
```

Todo el resto del sistema compara `rol` como entero:
```python
# gestor_validacion.py
if st.session_state.get("rol") not in (1, 2):
```

`st.session_state["rol"]` se guarda como `usuario.get("rol")` desde la respuesta JSON del login, que es un entero. La conversión a string no produce un bug (funciona) pero es una inconsistencia que indica que el autor no sabía de qué tipo era el dato. Si algún día el backend devuelve el rol como string, la mitad de las páginas fallarían mientras esta seguiría funcionando.

---

## 4. COHERENCIA ENTRE SISTEMAS — CONTRATOS IMPLÍCITOS

### 4.1 — El token JWT es la única fuente de identidad del usuario en el backend

El backend **no re-consulta `tb_Usuario` en cada request**. Todo lo que sabe sobre el usuario (su `rol` y su `area`) viene del JWT. Esto crea un contrato implícito:

**Si un admin desactiva a un usuario o cambia su área, el token viejo sigue siendo válido 24 horas.**

No hay endpoint de logout que invalide tokens, ni lista negra de tokens revocados. Un usuario desactivado con token activo puede seguir operando hasta que el token expire. Tampoco hay un endpoint de "cambiar mi área" — si el área de un usuario cambia en la base de datos, su próxima sesión tendrá el área nueva pero la sesión actual seguirá con la vieja.

---

### 4.2 — `simulacion.py` backend usa `ValorCOP_M1` pero el dashboard usa `ValorCOP_M2`

- **Simulación** (`/simulacion/calcular`): usa `ValorCOP_M1` para calcular el impacto simulado.
- **Dashboard** (`/dashboard/{id_area}/resumen`) y **consumo** (`/consumir-facturas`): usan `ValorCOP_M2`.

`ValorCOP_M1` es el valor "al momento de la factura" y `ValorCOP_M2` es el valor ajustado (fecha M2). Para simular si una factura cabe en el presupuesto, el motor de simulación usa el valor *sin ajustar*. Para el gasto ejecutado real, el dashboard usa el valor *ajustado*. Esto significa que una factura puede parecer que "cabe" en la simulación pero al consumirse (con M2 mayor) exceder el presupuesto. No hay validación de esta diferencia en ningún lado.

---

### 4.3 — `facturas_validacion` usa `Mes_pendiente` pero `simulacion` usa `Mes`

- `facturas_validacion.py` filtra por `f.Mes_pendiente` para agrupar facturas por mes de evaluación.
- `simulacion.py` filtra por `f.Mes` para agrupar por mes de impacto presupuestal.

Si `Mes_pendiente` y `Mes` no coinciden (factura registrada en un mes pero cuyo gasto corresponde a otro), los dos sistemas clasifican la misma factura en meses distintos. No hay validación que garantice que estos dos campos sean consistentes.

---

### 4.4 — El frontend de validación asume que la API siempre devuelve `periodo_evaluacion`

**Archivo:** `frontend/pages/gestor_validacion.py`

```python
periodo = datos_validacion.get("periodo_evaluacion")
if not periodo:
    st.error("Actualiza también el backend: falta el período de evaluación.")
    st.stop()
```

El desarrollador documentó explícitamente esta dependencia, lo cual es buena práctica. Pero la comprobación de timezone (`ZoneInfo("America/Bogota")`) en el backend requiere el paquete `tzdata` en Windows, que no viene instalado por defecto. Si falta, el backend devuelve 500 en lugar de 200, y el frontend muestra "Error al cargar facturas" sin especificar que es un problema de dependencia de sistema.

---

### 4.5 — `client.py` llama a `aprobar_factura_confirmar` — el endpoint no existe registrado

**Archivo:** `frontend/api/client.py`

```python
def aprobar_factura_confirmar(id_factura: int, confirmado: bool = True):
    url = f"{BASE_URL}/facturas-validacion/{id_factura}/aprobar"
    ...
```

Revisando el router `facturas_validacion.py` (que fue truncado en la lectura pero cuyo patrón es visible), la ruta `/facturas-validacion/{id}/aprobar` existe en el backend (es el endpoint PUT de aprobación). Pero el frontend llama a `aprobar_factura_confirmar` usando `requests.put(...).raise_for_status()` sin el header de autenticación en ciertos paths de error. Si el backend devuelve 401, la excepción que propaga es `requests.exceptions.HTTPError`, no un dict estructurado, y el frontend no la captura de forma consistente.

---

### 4.6 — `gestor_clasificacion_ia.py` es un archivo vacío en producción

**Archivo:** `frontend/pages/gestor_clasificacion_ia.py`

```python
# -*- coding: utf-8 -*-
"""
Created on Fri Sep 25 14:53:35 2026
@author: jparrap
"""
```

El archivo existe, tiene funciones en `client.py` que apuntan a `/crew-ai/ejecuciones`, y el menú del rol 2 (Gestor) lo referencia. El endpoint del backend no está en `main.py`. Si el frontend lo llama, siempre recibirá 404. La fecha en el docstring (`2026`) indica que fue creado con una plantilla automática de IDE.

---

## 5. CONCLUSIONES Y RECOMENDACIONES

### Crítico (corregir antes de cualquier despliegue)

1. **`areas.py`**: corregir los `cursor.execute()` para que los params sean tuplas. El bug hace que crear y editar áreas siempre falle con error 500.

2. **`schemas/admin_facturas.py`**: mover el archivo a `routers/` o eliminarlo. Si se conserva, agregar `Depends(verify_token)` a todos sus endpoints antes de registrarlo. Resolver la importación `from schemas.factura import FacturaUpdate` (el archivo `schemas/factura.py` no existe).

3. **`agrupaciones.py` / `verticales.py`**: cambiar `usuario_id: int = Depends(verify_token)` a `user: dict = Depends(verify_token)`. Actualmente funciona por accidente; un refactor menor lo romperá.

### Importante (deuda técnica real)

4. **`admin.py` del frontend**: eliminar o reescribir desde cero. Usa `session_state["user"]` que nunca existe, llama a endpoints con URLs incorrectas (`/users` en vez de `/usuarios`) y sin token.

5. **`simulacion.py` frontend**: corregir `FechaRecepcion` → `FechaFacturacion` para que la columna de fecha se muestre correctamente.

6. **`main.py` frontend**: unificar todas las llamadas a `st.switch_page` para que usen la extensión `.py` consistentemente.

7. **`execute_query` vs `get_connection` manual**: estandarizar el patrón. Los routers que hacen múltiples queries en un request deberían usar `get_connection()` manual (como ya hace `facturas_validacion.py`) y no `execute_query()` repetido.

### A documentar (contratos implícitos)

8. Documentar que los tokens son válidos 24h y no se invalidan al desactivar usuarios. Decidir si se necesita un mecanismo de revocación.

9. Documentar la diferencia `ValorCOP_M1` (simulación) vs `ValorCOP_M2` (gasto real) y sus implicaciones: una factura puede "caber" en simulación y exceder al consumirse.

10. Eliminar o completar `gestor_clasificacion_ia.py` — un archivo vacío con imports activos en `client.py` genera confusión sobre el estado real del sistema.

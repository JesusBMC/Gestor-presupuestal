# Revisión Técnica Senior — FacturasPRY
**Fecha:** Julio 2026  
**Revisor:** Kiro (análisis estático, lectura directa del código fuente)  
**Alcance:** Backend (FastAPI/Python), Frontend (Streamlit/Python), BD (Access .accdb)

---

## Resumen Ejecutivo

El proyecto es un sistema de control presupuestal interno para la Bolsa Mercantil de Colombia. Tiene un backend FastAPI sólido en su funcionalidad central (autenticación JWT, validación de facturas con lógica presupuestal real, cálculo estadístico), un frontend Streamlit funcional y una base de datos Access que es el punto de quiebre principal para cualquier escenario de producción.

**El sistema funciona y tiene lógica de negocio bien pensada. No está listo para producción en su estado actual.** Los problemas más graves son de infraestructura (Access como BD en producción, ausencia total de Docker/requirements.txt), seguridad operacional (la `.env` con la JWT secret key real está sin protección alguna), y deuda de código acumulada (routers duplicados, schemas zombie, debug endpoint expuesto).

---

## Calificaciones por Área

| Área | Puntuación | Comentario |
|------|-----------|------------|
| Arquitectura | 6/10 | Separación clara frontend/backend, pero routers duplicados y schemas huérfanos degradan la nota |
| Diseño del código | 6/10 | Lógica de negocio bien implementada; inconsistencias de convención y duplicación la frenan |
| Infraestructura | 3/10 | Sin requirements.txt, sin Docker, sin .gitignore; Access en lugar de una BD real |
| Seguridad | 5/10 | JWT bien hecho, bcrypt correcto; la `.env` con secret key real committada destruye todo lo demás |
| Escalabilidad/Producción | 2/10 | Access no soporta concurrencia, sin gestión de conexiones, sin tests, sin CI/CD |
| Calidad del código | 5/10 | Comentarios buenos, buenas docstrings; duplicación sistémica, naming inconsistente |

---

## 1. ARQUITECTURA

### Lo que funciona bien

La separación en capas es coherente: FastAPI en `backend/` expone una API REST, Streamlit en `frontend/` la consume vía `api/client.py`, y la BD está aislada en `database/`. El directorio `backend/auth/` agrupa correctamente las tres responsabilidades de autenticación (JWT, hashing, permisos). La presencia de `db/connection.py` como única puerta de entrada a la base de datos es correcta.

Los routers están bien segmentados por dominio: `facturas.py`, `presupuesto.py`, `simulacion.py`, `consumo.py`, `dashboard.py`, etc. Cada uno tiene una responsabilidad clara.

### Problemas

**Routers duplicados — el problema más obvio:**

- `routers/agrupaciones.py` y `routers/agrupaciones_router.py` coexisten. Son casi idénticos pero con diferencias de esquema: el de `agrupaciones.py` tiene `AgrupacionCreate(IdArea, Nombre)` sin campo `Periodicidad`; el de `agrupaciones_router.py` tiene `AgrupacionCreate(IdArea, Nombre, Periodicidad)` y usa `IdAgrupacion` en lugar de `Id` en las queries. **Solo `agrupaciones.py` está registrado en `main.py`**; `agrupaciones_router.py` es código muerto que nunca se ejecuta.

- `routers/areas_router.py` existe pero está completamente vacío (solo el header de Spyder con fecha 2026-07-28). Es un archivo fantasma.

**Inconsistencia en el patrón de `verify_token`:**

En los routers más antiguos (agrupaciones, verticales, areas) el parámetro se llama `usuario_id: int = Depends(verify_token)`, pero `verify_token` en realidad devuelve un `dict` con `{usuario_id, rol, area}`. Esto significa que `usuario_id` en esos handlers recibe un diccionario, no un entero. La función `validar_permiso_area(usuario_id, id_area)` recibe ese dict y llama `user.get("area")` correctamente, así que funciona en la práctica, pero la declaración del tipo es engañosa y confusa. Los routers más nuevos (facturas, dashboard, presupuesto, consumo) corrigen esto usando `user: dict = Depends(verify_token)`.

**El `admin/` router nunca se registra:**

`backend/schemas/admin_facturas.py` contiene un router completo (`/admin/facturas` con GET, PUT, DELETE). Este archivo está en el directorio `schemas/` (nombre incorrecto), no en `routers/`, y **no está incluido en `main.py`**. El frontend llama a `/admin/facturas` desde `api/client.py` (funciones `get_facturas_admin`, `editar_factura`, `eliminar_factura`), pero el endpoint nunca responderá porque el router no existe en la app. Además, `admin_facturas.py` importa `from schemas.factura import FacturaUpdate` que no existe en el árbol del proyecto.

**`schemas/presupuesto.py` y `schemas/user.py` son zombies:**

- `schemas/presupuesto.py` define `PresupuestoCreate`, `PresupuestoUpdate`, `PresupuestoVerticalCreate`. Ninguna es importada por ningún router; los schemas reales de presupuesto se definen directamente dentro de `routers/presupuesto.py`.
- `schemas/user.py` define `UserCreate` y `UserUpdate` con naming en snake_case. El sistema real usa `schemas/usuario.py` con naming en PascalCase. Nadie importa `user.py`.

**`DEBUG` endpoint expuesto en producción:**

`routers/dashboard.py` tiene un endpoint `GET /{id_area}/debug` con comentario "🔍 DIAGNÓSTICO TEMPORAL (borrar cuando ya no se necesite)". Este endpoint expone el contenido bruto de `tb_Facturas` sin ningún filtro, incluyendo todos los valores de `Estado`, `Ano`, `ValorCOP_M2` de todas las facturas del área. Está protegido por `verify_token` pero no requiere rol de admin.

---

## 2. DISEÑO

### Lo que funciona bien

**La lógica de validación de facturas (`facturas_validacion.py`) es el módulo más sofisticado y mejor diseñado del proyecto.** Implementa correctamente:
- Validación en dos dimensiones simultáneas (Agrupación + Tipo CAPEX/OPEX)
- Cálculo estadístico con mediana/MAD (más robusto que desviación estándar con pocos datos)
- Burn-rate anual comparando % del año transcurrido vs % del presupuesto consumido
- Cache por bucket para no repetir queries costosas dentro de una misma petición
- Clara separación entre la capa determinista (decide Cabe/No Cabe) y la capa estadística (solo contexto)

**El módulo `consumo_proveedores.py`** tiene funciones auxiliares bien separadas (`leer_saldos`, `construir_informe`, `construir_resumen`), manejo de tolerancia de redondeo con `_tolerancia()`, y buenas advertencias al usuario sobre datos inconsistentes.

**`auth/jwt.py`** falla explícito en el arranque si `JWT_SECRET_KEY` no está en el entorno (`os.environ["JWT_SECRET_KEY"]` vs `os.getenv(..., default)`). Esto es correcto.

**`auth/password.py`** usa bcrypt via passlib, correcto.

**`db/connection.py`** centraliza la conexión y maneja rollback en excepciones.

### Problemas

**Schemas Pydantic definidos inline dentro de los routers:**

En `agrupaciones.py`, `agrupaciones_router.py`, `verticales.py`, `presupuesto.py` y `simulacion.py` los schemas (`AgrupacionCreate`, `VerticalCreate`, `PresupuestoTipoCreate`, etc.) se definen directamente en el archivo del router. Esto viola el propósito del directorio `schemas/`. El resultado es que la carpeta `schemas/` está casi vacía y sin uso real, mientras los routers crecen de tamaño innecesariamente.

**`usuarios.py` rehashea la contraseña con un `CryptContext` propio:**

`routers/usuarios.py` instancia su propio `CryptContext(schemes=["bcrypt"])` en lugar de importar `hash_password` de `auth/password.py`. Son equivalentes funcionalmente, pero viola DRY: si el día de mañana se cambia la configuración de bcrypt (cost factor, algoritmo), hay que cambiarlo en dos lugares.

**`query_all()` se duplica en cada router:**

La función `def query_all(cursor): columns = [col[0] for col in cursor.description]; return [dict(zip(columns, row)) for row in cursor.fetchall()]` está copiada idéntica en `agrupaciones.py`, `agrupaciones_router.py`, `verticales.py`, `presupuesto.py`, `auth.py`. Debería estar en `db/connection.py` o un `db/utils.py`.

**`_to_float()` también se duplica:**

La función `def _to_float(value)` que convierte `Decimal`/`None` a `float` está duplicada en `dashboard.py`, `facturas_validacion.py`, `consumo.py`, y `dashboard_presupuesto.py`. Mismo problema.

**Parámetro `is_write` en `execute_query` no se usa:**

`db/connection.py` define `execute_query(query, params=(), fetch=True, is_write=False)` pero el parámetro `is_write` nunca se usa dentro de la función. Es deuda de código.

**`facturas.py` acepta `data: dict` sin validar en PUT:**

```python
@router.put("/{id_factura}")
def actualizar_factura(id_factura: int, data: dict, user: dict = Depends(verify_token)):
```

Aceptar un `dict` plano sin schema Pydantic significa que cualquier campo puede llegar en el payload y no hay validación de tipos. FastAPI no puede generar documentación útil para este endpoint. Debería tener un schema `FacturaUpdate`.

**Naming inconsistente entre `Id` e `IdAgrupacion`:**

En `agrupaciones.py` la query SELECT usa `Id AS IdAgrupacion`, pero el UPDATE usa `WHERE Id = ?`. En `agrupaciones_router.py` la tabla tiene columna `IdAgrupacion` y usa `WHERE IdAgrupacion = ?`. No queda claro cuál es el esquema real de la tabla `tb_Agrupacion`.

**`config.py` define `SECRET_KEY` con default inseguro pero `jwt.py` lo ignora:**

`config.py` define `SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion-con-clave-larga-segura")` y `DATABASE_URL` (SQL Server, no Access). `jwt.py` lee `JWT_SECRET_KEY` del entorno directamente. Son dos configuraciones paralelas que no convergen: `config.py` es legado que nunca se usa, `jwt.py` y `db/connection.py` leen del entorno directamente. `config.py` también tiene `DATABASE_URL` para SQL Server que contrasta con el Access real.

---

## 3. INFRAESTRUCTURA

### Hallazgos críticos

**No existe ningún archivo de dependencias:**
- ❌ No hay `requirements.txt`
- ❌ No hay `pyproject.toml`
- ❌ No hay `setup.py` ni `setup.cfg`
- ❌ No hay `Pipfile`

Esto hace imposible reproducir el entorno. Las dependencias inferidas del código son: `fastapi`, `uvicorn`, `python-jose`, `passlib[bcrypt]`, `pydantic`, `pyodbc`, `python-dotenv`, `requests`, `streamlit`, `plotly`, `pandas`, `statistics` (stdlib), `zoneinfo` (stdlib Python 3.9+), `tzdata` (Windows, mencionado en código). Sin versiones pinneadas, cualquier update puede romper el sistema silenciosamente.

**No existe Dockerfile ni docker-compose.yml.**

Esto no es solo un problema de deployment: en Windows, `pyodbc` con el driver `Microsoft Access Driver (*.mdb, *.accdb)` requiere el Microsoft Access Database Engine (redistribuible de 32 o 64 bits). Esto es una dependencia del sistema operativo, no de Python. En Linux o macOS este driver no existe. **El proyecto solo puede correr en Windows.** Un Dockerfile no resolvería esto sin una imagen base Windows, lo cual es poco práctico para la mayoría de infraestructuras cloud.

**No existe `.gitignore`.**

La `.env` con la JWT secret key real (`JWT_SECRET_KEY=34eabd0b...`) y la ruta hardcodeada al archivo `.accdb` (`DB_PATH=C:\Users\jparrap\...`) están en el repositorio sin ninguna protección. Cualquier persona con acceso al repo ve la clave de firma de tokens JWT.

**La base de datos Access tiene limitaciones de producción fundamentales:**
- **Sin concurrencia real:** Access usa bloqueos a nivel de archivo. Con dos usuarios simultáneos haciendo escrituras, es probable la corrupción o timeout.
- **Sin transactions aisladas:** el driver ODBC de Access tiene soporte muy limitado de transacciones. `conn.rollback()` en `execute_query` puede no funcionar como se espera para todas las operaciones.
- **Límite de tamaño:** 2 GB por archivo `.accdb`.
- **Sin usuarios/roles a nivel BD:** cualquier proceso con acceso al archivo tiene acceso completo; la seguridad depende 100% del backend.
- **No funciona en Linux/macOS ni en contenedores.**
- **El archivo `.accdb` está en una ruta local del desarrollador:** `C:\Users\jparrap\Sistemas_Excel\FacturasPRY\database\dbFacturas.accdb`. En cualquier otro equipo habría que cambiar la variable de entorno.

**Gestión de conexiones: se abre y cierra una conexión por request:**

No hay connection pool. Cada request a la API abre una conexión ODBC nueva y la cierra al finalizar. Esto es costoso en latencia y no escala. En bases de datos reales (PostgreSQL, SQL Server) se usaría un pool (ej. SQLAlchemy con `pool_size`). Con Access esto es moot porque el driver no soporta pool real, pero es un patrón que habrá que cambiar cuando se migre.

---

## 4. SEGURIDAD

### Hallazgos críticos

**La JWT secret key real está en el repositorio:**

`backend/.env` contiene:
```
JWT_SECRET_KEY=34eabd0b145ebe5cbe24cefd645c7278eecaaba9a9e6acc5fe86bbd0df3a8c90
```
Sin `.gitignore`, este archivo va al control de versiones. Si el repo es o fue público en algún momento, o si alguien con acceso al repo no debería tener esta clave, hay que rotar la clave **inmediatamente** y agregar `.env` a `.gitignore`.

**`config.py` tiene un default de SECRET_KEY inseguro:**
```python
SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion-con-clave-larga-segura")
```
Aunque `jwt.py` no usa esta variable, su existencia en el código es una mina: si alguien conecta `config.SECRET_KEY` a `jwt.py` por error, el sistema funcionará con una clave predecible.

### Lo que funciona bien

**JWT implementado correctamente:**
- `jwt.py` usa `python-jose` con HMAC-SHA256
- El token incluye `sub` (usuario_id), `rol`, `area` y `exp`
- `verify_token` lanza 401 explícito si falta `sub` o `rol`
- La key falla el arranque de la app si no está en el entorno (`os.environ["JWT_SECRET_KEY"]`)
- Token válido por 24 horas (razonable para uso interno)

**Passwords con bcrypt:**
- `auth/password.py` usa `passlib` con bcrypt, esquema correcto
- El login compara con `verify_password()`, no con igualdad de strings

**Validación de dominio de email:**
- `usuarios.py` valida `email.endswith("@bolsamercantil.com.co")` tanto en backend como en frontend. Correcto.

**Permisos a nivel de área:**
- `validar_permiso_area` protege que un usuario de un área no acceda a datos de otra. Está aplicado en todos los endpoints sensibles revisados.

### Problemas de seguridad adicionales

**`admin_facturas.py` (en `schemas/`) no tiene autenticación:**
```python
@router.get("/facturas")
def get_facturas():  # sin Depends(verify_token)
```
Los endpoints de admin no verifican token ni rol. Afortunadamente este router nunca se registra en `main.py`, así que no está expuesto. Pero si se registrara, cualquiera podría leer, editar y borrar facturas sin autenticarse.

**CORS configurado solo para localhost:**
```python
allow_origins=["http://localhost:8501", "http://localhost:3000"]
```
Correcto para desarrollo. En producción habría que cambiar esto a los dominios reales y **no** usar `allow_methods=["*"]` ni `allow_headers=["*"]`.

**Sin rate limiting en `/auth/login`:**
El endpoint de login no tiene ningún mecanismo anti-brute force. No hay límite de intentos, no hay captcha, no hay delay progresivo. En producción esto expone el login a ataques de diccionario.

**Error de login diferenciado:**
```python
if not rows:
    raise HTTPException(status_code=401, detail="Usuario no encontrado")
...
if not verify_password(data.password, usuario["Contraseña"]):
    raise HTTPException(status_code=401, detail="Contraseña incorrecta")
```
Los mensajes de error diferentes permiten enumerar usuarios válidos. Debería devolver el mismo mensaje genérico ("Credenciales inválidas") en ambos casos.

**`SimulacionRequest` acepta lista no tipada:**
```python
class SimulacionRequest(BaseModel):
    facturaIds: list  # sin tipo de elemento
    IdArea: int
```
`facturaIds: list` sin `list[int]` permite inyectar cualquier tipo en la lista. Debería ser `list[int]`.

---

## 5. ESCALABILIDAD Y PRODUCCIÓN

### Viabilidad del deployment actual

El sistema **no es desplegable en producción** en su estado actual por las siguientes razones concretas, ordenadas por severidad:

1. **Access como base de datos:** No soporta el nivel de concurrencia de un sistema de producción. Con más de 2-3 usuarios simultáneos haciendo escrituras se pueden producir corrupción de datos o errores de bloqueo. Access no tiene HA ni replicación.

2. **Sin gestión de dependencias:** No se puede reproducir el entorno en otro servidor sin adivinar qué versiones instalar.

3. **Solo corre en Windows:** El driver ODBC de Access es Windows-only. Cualquier infraestructura cloud (EC2 Linux, GCP, Azure Container Apps, etc.) requiere una instancia Windows o un workaround costoso.

4. **Sin tests:** Cero cobertura de tests automáticos. Cualquier cambio puede romper la lógica de negocio (que es compleja: la simulación pairwise, el burn-rate, la validación en dos dimensiones) sin ninguna red de seguridad.

5. **Sin health check real:** El endpoint `GET /` devuelve un JSON estático. No verifica la conexión a la BD, no hay liveness/readiness probe.

6. **Logs con `print()`:** `db/connection.py` usa `print(f"[DB ERROR] {e}")`. En producción los errores de BD deben ir al logger del sistema, no a stdout.

### Alternativas recomendadas para la BD

| Opción | Ventajas | Esfuerzo de migración |
|--------|----------|----------------------|
| **PostgreSQL** | Open source, robusto, pool de conexiones, Linux-compatible, soporte en todas las nubes | Medio — reescribir queries específicas de Access (IIF → CASE WHEN, True/-1 → TRUE/FALSE) |
| **SQL Server Express** | Sin cambio de driver (ya hay `DATABASE_URL` para SQL Server en `config.py`), misma sintaxis ODBC | Bajo — cambiar solo la connection string |
| **SQLite** | Zero-config, portable, sin servidor | Solo si el concurrency sigue siendo bajo (uso mono-área); no recomendado para multi-área |

La migración a SQL Server Express sería la de menor esfuerzo dado que `config.py` ya tiene un `DATABASE_URL` apuntando a SQL Server. Requiere cambiar el driver ODBC y revisar queries con sintaxis Access-específica (`IIF`, valores `-1` para True).

---

## 6. CALIDAD DEL CÓDIGO

### Positivo

- Los archivos más nuevos (`facturas_validacion.py`, `consumo_proveedores.py`, `consumo.py`, `dashboard.py`) tienen comentarios de bloque que explican el porqué, no el qué. Buen nivel de documentación inline.
- Los commits evidencian correcciones de bugs reales documentadas en el código (ej. el comentario en `dashboard.py` sobre `Estado = 'Aprobado'` vs `'Aprobada'`, el comentario en `facturas.py` sobre la ruta `/pendientes/{id_area}` que faltaba).
- El uso de `Decimal` para valores monetarios en lugar de `float` en los módulos críticos es correcto.

### Problemas

**Naming inconsistente a múltiples niveles:**

| Contexto | Problema |
|----------|----------|
| `schemas/user.py` vs `schemas/usuario.py` | Mismo concepto, dos archivos, dos idiomas |
| `usuario_id: int` vs `user: dict` en handlers | Mismo tipo de dato, dos nombres distintos |
| `IdAgrupacion` vs `Id AS IdAgrupacion` | Inconsistencia de columna en tabla tb_Agrupacion |
| `activo` (minúscula en tb_Area) vs `Activo` (mayúscula en tb_Agrupacion) | Inconsistencia de columna en la BD |
| `IdProvedor` (typo, falta 'e') en `tb_Consumo` | Typo que está en la BD y en el código; cambiarlo requiere migración |
| `Mes_pendiente` en `facturas_validacion.py` vs `Mes` en `facturas.py` | Dos nombres para el campo de mes de una factura |

**Espaciado y formato:**

Varios archivos (agrupaciones.py, verticales.py, presupuesto.py) tienen líneas en blanco dobles entre cada línea de código, posiblemente generadas por Spyder. Dificulta la lectura. El código nuevo (facturas_validacion.py, consumo.py) tiene formato consistente.

**`main.py` registra routers que no deberían estar en producción:**

El router de `facturas_validacion` incluye un endpoint `GET /{id_area}/debug` que expone datos crudos de la BD. Este endpoint debería eliminarse o al menos protegerse con `validar_rol(user, 1)`.

**`gestor_facturas.py` llama a `set_page_config` después de otras instrucciones:**

```python
mostrar_sidebar()  # ← ejecuta código Streamlit
st.set_page_config(...)  # ← debe ser la primera llamada st.*
```
Esto causa un `StreamlitAPIException` si el sidebar renderiza algún elemento. En Streamlit, `set_page_config` debe ser la primera llamada de Streamlit en el script.

**`frontend/main.py` tiene rutas de `st.switch_page` rotas:**

```python
st.switch_page("pages/Dashboard_presupuesto")   # sin extensión .py
st.switch_page("pages/Consumo_Proveedores")      # sin extensión .py
```
Las páginas existen como `dashboard_presupuesto_vista.py` y `Consumo_Proveedores.py`. Las rutas no coinciden.

---

## 7. HALLAZGOS CRÍTICOS (resumen accionable)

### 🔴 Prioridad 1 — Seguridad inmediata

1. **Rotar la `JWT_SECRET_KEY`** — la clave actual está en el repo. Generar una nueva, moverla a un gestor de secretos o variable de entorno del servidor, y agregar `*.env` a `.gitignore`.

2. **Crear `.gitignore`** — mínimo: `*.env`, `*.pyc`, `__pycache__/`, `database/*.accdb` (la BD no debería estar en el repo), `*.log`.

3. **Unificar el mensaje de error del login** — devolver siempre "Credenciales inválidas" para no permitir enumeración de usuarios.

### 🔴 Prioridad 2 — Infraestructura básica

4. **Crear `requirements.txt`** con versiones pinneadas. Comando: en el entorno donde corre el sistema, ejecutar `pip freeze > requirements.txt` y revisar las dependencias antes de commitar.

5. **Eliminar `agrupaciones_router.py` y `areas_router.py`** — son código muerto. Si `agrupaciones_router.py` tiene la versión correcta del schema (con `Periodicidad`), reemplazar `agrupaciones.py` con su contenido y registrar solo uno.

6. **Corregir o eliminar `schemas/admin_facturas.py`** — moverlo a `routers/admin_facturas.py`, agregar `Depends(verify_token)` y `validar_rol(user, 1)` a todos sus endpoints, crear el schema `FacturaUpdate` que importa, y registrarlo en `main.py`. O eliminarlo si la funcionalidad admin está cubierta por otros medios.

### 🟡 Prioridad 3 — Calidad y mantenibilidad

7. **Mover `query_all()` y `_to_float()` a `db/utils.py`** e importarlos desde ahí. Eliminar las 5+ copias duplicadas.

8. **Importar `hash_password` de `auth/password.py` en `usuarios.py`** en lugar de instanciar un segundo `CryptContext`.

9. **Tipificar `SimulacionRequest.facturaIds: list[int]`** en `schemas/simulacion.py`.

10. **Eliminar el endpoint `debug` de `dashboard.py`** o protegerlo con `validar_rol(user, 1)`.

11. **Corregir el orden en `gestor_facturas.py`**: mover `st.set_page_config()` antes de `mostrar_sidebar()`.

12. **Corregir las rutas `st.switch_page`** en `frontend/main.py` para que apunten a los nombres reales de los archivos.

13. **Eliminar `schemas/user.py` y `schemas/presupuesto.py`** — son zombies que confunden.

14. **Consolidar `config.py`**: eliminar el `SECRET_KEY` con valor por defecto inseguro o hacer que `jwt.py` lo importe desde ahí (y que falle si es el valor por defecto).

### 🟢 Prioridad 4 — Escalabilidad (planificación)

15. **Plan de migración de Access a SQL Server Express o PostgreSQL.** El esfuerzo de migración no es enorme si se hace sistemáticamente. Las queries con sintaxis Access-específica a cambiar son: `IIF(...)` → `CASE WHEN`, booleanos `-1/0` → `TRUE/FALSE` o `1/0`, `activo` inconsistente entre tablas.

16. **Agregar rate limiting al endpoint `/auth/login`** — con FastAPI puede usarse `slowapi` o similar.

17. **Escribir tests de la lógica de validación presupuestal** — los módulos `facturas_validacion.py` y `consumo.py` son los más críticos y los más complejos. Un bug aquí tiene impacto financiero directo. pytest + httpx para tests de integración del backend.

---

## Conclusión

El proyecto tiene una base sólida y lógica de negocio bien pensada — la validación pairwise de facturas contra dos dimensiones simultáneas con contexto estadístico es trabajo real. El desarrollador sabe lo que está construyendo.

Los problemas son los de siempre en un proyecto que nació como una herramienta interna y creció: deuda de infraestructura (no se configuró el setup desde el principio), código duplicado de evolución rápida, y una base de datos que era práctica para el MVP pero que no escala.

El camino a producción requiere resolver obligatoriamente los puntos 1-6 de la lista anterior. El resto es calidad que hará el sistema más mantenible pero no impide el despliegue si el entorno es Windows con un solo usuario por área a la vez.

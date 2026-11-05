import streamlit as st
 
from api.client import login

from dotenv import load_dotenv

load_dotenv()
 
st.set_page_config(

    page_title="Control Presupuestal",

    layout="wide"

)
 
# ============================================================

# INICIALIZAR SESSION STATE

# ============================================================
 
if "access_token" not in st.session_state:

    st.session_state["access_token"] = None

    st.session_state["rol"] = None

    st.session_state["IdArea"] = None

    st.session_state["usuario_id"] = None

    st.session_state["nombre"] = None
 


# ============================================================
 
# LOGIN

# ============================================================

if not st.session_state["access_token"]:

    st.title("🔐 Sistema de Control Presupuestal")

    st.subheader("Ingresa tus credenciales")

    email = st.text_input(
        "Correo institucional",
        placeholder="usuario@bolsamercantil.com.co"
    )

    password = st.text_input(
        "Contraseña",
        type="password"
    )

    if st.button("Ingresar", use_container_width=True):

        email = email.strip().lower()

        if not email or not password:

            st.warning("⚠️ Por favor completa los campos")

        elif not email.endswith("@bolsamercantil.com.co"):

            st.warning(
                "⚠️ Debes ingresar un correo institucional "
                "@bolsamercantil.com.co"
            )

        else:

            success, data = login(email, password)

            if success and isinstance(data, dict):

                token = data.get("access_token")
                usuario = data.get("user")

                if token and isinstance(usuario, dict):

                    st.session_state["access_token"] = token
                    st.session_state["rol"] = usuario.get("rol")
                    st.session_state["IdArea"] = usuario.get("area")
                    st.session_state["usuario_id"] = usuario.get("id")
                    st.session_state["nombre"] = usuario.get("nombre")

                    st.success(
                        f"¡Bienvenido {usuario.get('nombre', '')}!"
                    )

                    st.rerun()

                else:

                    st.error("❌ Respuesta inválida del servidor")
                    st.write("Respuesta:", data)

            else:

                st.error("❌ Error en autenticación")
                st.write("Respuesta:", data)
# ============================================================

# APP PRINCIPAL

# ============================================================
 
else:

    st.sidebar.title("🏢 Sistema Presupuestal")
 
    st.sidebar.subheader(f"Usuario: {st.session_state.get('nombre', '')}")

    rol = st.session_state.get("rol")

    # ================= NAVEGACIÓN =================

    if rol == 1:

        st.sidebar.markdown("### 👑 ADMIN")

        pagina = st.sidebar.radio(
 
            "Selecciona una opción:",
 
            [
 
 
                "Gestión de usuarios",
 

                "Gestión de áreas"
 
            ]
 
        )

 
        if pagina == "Gestión de usuarios":
 
            st.switch_page("pages/admin_usuarios.py")
  
 
        elif pagina == "Gestión de áreas":
 
            st.switch_page("pages/admin_areas.py")

    elif rol == 2:

        st.sidebar.markdown("### 📊 GESTOR")

        pagina = st.sidebar.radio(
 
            "Selecciona una opción:",
 
            [
 
 
                "Presupuesto",
 
                "Validación de facturas",
 
                "Simulación",
 
                "Facturas gestor",
                
                "Dashboard presupuesto",
                
                "Proveedores"
                
 
            ]
 
        )

        
 
        if pagina == "Presupuesto":
 
            st.switch_page("pages/gestor_presupuesto.py")
 
        elif pagina == "Validación de facturas":
 
            st.switch_page("pages/gestor_validacion.py")
        
        elif pagina == "Dashboard presupuesto":
        
            st.switch_page("pages/Dashboard_presupuesto")
 
        elif pagina == "Facturas gestor":
 
            st.switch_page("pages/gestor_facturas.py")
            
        elif pagina == "Proveedores":
     
            st.switch_page("pages/Consumo_Proveedores")
 
        elif pagina == "Simulación":
 
            st.switch_page("pages/simulacion.py")

    elif rol == 3:

        st.sidebar.markdown("### 👤 USUARIO")

        pagina = st.sidebar.radio(
 
            "Selecciona una opción:",
 
            [
 
      
 
 
                "Simulación"
 
            ]
 
        )

        
 
        
 
        if pagina == "Simulación":
 
            st.switch_page("pages/simulacion.py")

    else:
 
        st.error("⚠️ Rol no válido")

    # ================= LOGOUT =================

    if st.sidebar.button("🔓 Cerrar Sesión", use_container_width=True):

        for key in [
 
            "access_token",
 
            "rol",
 
            "IdArea",
 
            "usuario_id",
 
            "nombre"
 
        ]:
 
            st.session_state[key] = None

        st.rerun()

    # ================= CONTENIDO =================

    st.title(f"Bienvenido {st.session_state.get('nombre', '')}")

    rol_nombre = {
 
        1: "Admin",
 
        2: "Gestor",
 
        3: "Usuario"
 
    }.get(rol, "Desconocido")

    st.write(
 
        f"Área: {st.session_state.get('IdArea', '')} | Rol: {rol_nombre}"
 
    )
 
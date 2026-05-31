import streamlit as st
from supabase import create_client, Client
import pandas as pd
import time

# Configuración de Supabase
SUPABASE_URL = "https://paflyeftbszzjhkivmnh.supabase.co"
SUPABASE_KEY = "sb_publishable_PaacmUL99VUl3uaywHx3zw_coKNi0HX"

# Inicializar cliente
if 'supabase' not in st.session_state:
    st.session_state.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="EPIC Node Dashboard", layout="wide")

st.title("📊 EPIC Data Dashboard")

# Sidebar para control
st.sidebar.header("Configuración de Historial")
max_rows = st.sidebar.slider("Cantidad de puntos a mostrar", 100, 5000, 1000)
refresh_rate = st.sidebar.slider("Refresco (segundos)", 1, 10, 2)

def get_data(limit):
    try:
        # Traemos los N últimos datos. Ordenamos por ID (que siempre es incremental)
        # para asegurar que traemos lo más reciente sin importar los milisegundos internos.
        response = st.session_state.supabase.table("sensor_data") \
            .select("*") \
            .order("id", desc=True) \
            .limit(limit) \
            .execute()
        return response.data
    except Exception as e:
        st.error(f"Error al conectar con Supabase: {e}")
        return []

# Usamos st.fragment para que solo esta parte se actualice sin parpadeos
@st.fragment(run_every=refresh_rate)
def update_dashboard():
    data = get_data(max_rows)
    
    if data:
        df = pd.DataFrame(data)
        
        # Conversión a Gs
        SCALE = 256000.0
        df['x_g'] = df['x_raw'] / SCALE
        df['y_g'] = df['y_raw'] / SCALE
        df['z_g'] = df['z_raw'] / SCALE
        
        # Intentar usar sensor_timestamp_ms, si por alguna razón hay datos viejos sin esa columna, cae en created_at
        if 'sensor_timestamp_ms' in df.columns:
            # Creamos una columna visual en segundos relativos para el eje X (ej. 0s, 1.5s, 2s...)
            # Esto evita que el gráfico muestre números crudos gigantescos como 18273921
            df['tiempo_segundos'] = (df['sensor_timestamp_ms'] - df['sensor_timestamp_ms'].min()) / 1000.0
            eje_x = 'tiempo_segundos'
        else:
            df['created_at'] = pd.to_datetime(df['created_at'])
            eje_x = 'created_at'
        
        # IMPORTANTE: Ordenamos cronológicamente ascendente usando el tiempo del sensor o ID
        df_plot = df.sort_values('id', ascending=True)
        
        # Métricas (del dato más reciente en el DataFrame original que viene desc)
        latest = df.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("X (g)", f"{latest['x_g']:.4f}")
        c2.metric("Y (g)", f"{latest['y_g']:.4f}")
        c3.metric("Z (g)", f"{latest['z_g']:.4f}")
        
        st.subheader(f"📈 Historial de los últimos {len(df)} puntos")
        
        tab1, tab2, tab3 = st.tabs(["Eje X", "Eje Y", "Eje Z"])
        with tab1:
            st.line_chart(df_plot.set_index(eje_x)['x_g'], color="#ff4b4b")
        with tab2:
            st.line_chart(df_plot.set_index(eje_x)['y_g'], color="#0068c9")
        with tab3:
            st.line_chart(df_plot.set_index(eje_x)['z_g'], color="#29b09d")
        
        with st.expander("Ver tabla de datos crudos"):
            columnas_tabla = ['sensor_timestamp_ms', 'node_id', 'x_g', 'y_g', 'z_g'] if 'sensor_timestamp_ms' in df.columns else ['created_at', 'node_id', 'x_g', 'y_g', 'z_g']
            st.dataframe(df[columnas_tabla], use_container_width=True)
    else:
        st.info("Esperando datos de Supabase...")

# Ejecutar el fragmento
update_dashboard()
"""
App Streamlit - Promedios diarios por rango horario desde InfluxDB Cloud (Gallinas)
------------------------------------------------------------------------------------
Calcula, para cada día dentro de un rango seleccionado en un calendario,
el promedio de cada variable en 4 franjas horarias:
    - Madrugada : 00:00 - 06:00
    - Mañana    : 06:00 - 12:00
    - Tarde     : 12:00 - 18:00
    - Noche     : 18:00 - 24:00

Cada día genera UNA fila en el dataframe final, con una columna por
variable x franja horaria.

Despliegue: Streamlit Cloud.
Dependencias no estándar: streamlit, influxdb-client, pandas (todas van en requirements.txt)
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time, date
from zoneinfo import ZoneInfo
from influxdb_client import InfluxDBClient

# ----------------------------------------------------------------------------
# Configuración general
# ----------------------------------------------------------------------------
st.set_page_config(page_title="Consulta InfluxDB - Gallinas", layout="wide")

TZ = ZoneInfo("America/Bogota")  # UTC-5, sin horario de verano

FIELDS = [
    "temperatura",
    "humedad",
    "luz_raw",
    "luz_calibrada",
    "escala_lux",
    "ruido_adc",
    "ruido_ajustado",
]

PERIODOS = [
    ("Madrugada_00-06", 0, 6),
    ("Manana_06-12", 6, 12),
    ("Tarde_12-18", 12, 18),
    ("Noche_18-24", 18, 24),
]

# ----------------------------------------------------------------------------
# Credenciales (puedes moverlas a st.secrets para mayor seguridad)
# ----------------------------------------------------------------------------
DEFAULT_URL = "https://us-east-1-1.aws.cloud2.influxdata.com"
DEFAULT_TOKEN = "QVIbuDys9mh6I6IXa0lgse3EUGdxLfVFSoF1HMqV744b8Matifir0oLdSR8k3P-j1EQftZ3TAJ2hMVq2C88LtQ=="
DEFAULT_ORG = "a08be33e0c3549c1"
DEFAULT_BUCKET = "GALLINAS"

st.sidebar.header("Conexión InfluxDB")
url = st.sidebar.text_input("URL", value=DEFAULT_URL)
token = st.sidebar.text_input("Token", value=DEFAULT_TOKEN, type="password")
org = st.sidebar.text_input("Org", value=DEFAULT_ORG)
bucket = st.sidebar.text_input("Bucket", value=DEFAULT_BUCKET)
measurement = st.sidebar.text_input(
    "Measurement",
    value="sensorData",
    help="Nombre del measurement usado por el ESP32 al escribir los puntos.",
)

st.sidebar.header("Filtro de fechas")
hoy = date.today()
rango = st.sidebar.date_input(
    "Selecciona el rango de días",
    value=(hoy - timedelta(days=6), hoy),
    max_value=hoy,
)

if isinstance(rango, tuple) and len(rango) == 2:
    fecha_inicio, fecha_fin = rango
else:
    fecha_inicio = fecha_fin = rango

consultar = st.sidebar.button("Consultar", type="primary")


# ----------------------------------------------------------------------------
# Funciones auxiliares
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client(url, token, org):
    return InfluxDBClient(url=url, token=token, org=org, timeout=30_000)


def query_period_means(client, bucket, org, measurement, fields, start_dt, stop_dt):
    """Devuelve un dict {field: valor_promedio} para el rango [start_dt, stop_dt)."""
    field_filter = " or ".join([f'r._field == "{f}"' for f in fields])
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start_dt.isoformat()}, stop: {stop_dt.isoformat()})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> filter(fn: (r) => {field_filter})
  |> group(columns: ["_field"])
  |> mean()
'''
    tables = client.query_api().query_data_frame(flux, org=org)

    if isinstance(tables, list):
        df = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    else:
        df = tables

    result = {f: None for f in fields}
    if df is not None and not df.empty and "_field" in df.columns:
        for _, row in df.iterrows():
            result[row["_field"]] = row["_value"]
    return result


def build_daily_dataframe(client, bucket, org, measurement, fields, fecha_inicio, fecha_fin):
    dias = pd.date_range(fecha_inicio, fecha_fin, freq="D").date
    filas = []
    progreso = st.progress(0.0, text="Consultando InfluxDB...")

    for i, dia in enumerate(dias):
        fila = {"Fecha": dia.isoformat()}
        for nombre_periodo, hora_ini, hora_fin in PERIODOS:
            start_dt = datetime.combine(dia, time(hora_ini, 0), tzinfo=TZ)
            if hora_fin == 24:
                stop_dt = datetime.combine(dia + timedelta(days=1), time(0, 0), tzinfo=TZ)
            else:
                stop_dt = datetime.combine(dia, time(hora_fin, 0), tzinfo=TZ)

            medias = query_period_means(
                client, bucket, org, measurement, fields, start_dt, stop_dt
            )
            for f in fields:
                fila[f"{f}_{nombre_periodo}"] = medias.get(f)

        filas.append(fila)
        progreso.progress((i + 1) / len(dias), text=f"Consultando InfluxDB... ({dia.isoformat()})")

    progreso.empty()
    return pd.DataFrame(filas)


# ----------------------------------------------------------------------------
# App principal
# ----------------------------------------------------------------------------
st.title("Promedios diarios por franja horaria - Bucket GALLINAS")
st.caption(
    "Franjas: Madrugada 00:00-06:00 · Mañana 06:00-12:00 · Tarde 12:00-18:00 · Noche 18:00-24:00 "
    "(hora Colombia, UTC-5)"
)

if "df_resultado" not in st.session_state:
    st.session_state.df_resultado = None

if consultar:
    if fecha_inicio > fecha_fin:
        st.error("La fecha inicial no puede ser mayor que la fecha final.")
    else:
        try:
            client = get_client(url, token, org)
            with st.spinner("Ejecutando consultas..."):
                df = build_daily_dataframe(
                    client, bucket, org, measurement, FIELDS, fecha_inicio, fecha_fin
                )
            st.session_state.df_resultado = df
            st.success(f"Consulta completada: {len(df)} día(s) procesado(s).")
        except Exception as e:
            st.error(f"Error al consultar InfluxDB: {e}")

if st.session_state.df_resultado is not None:
    df = st.session_state.df_resultado
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar CSV",
        data=csv,
        file_name="promedios_diarios_gallinas.csv",
        mime="text/csv",
    )
else:
    st.info("Selecciona un rango de fechas en la barra lateral y pulsa **Consultar**.")

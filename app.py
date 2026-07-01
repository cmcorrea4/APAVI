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
    value="GALLINERO",
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

with st.sidebar.expander("🔍 Diagnóstico (ver datos crudos)"):
    st.caption(
        "Si todo sale en 'None', usa esto para confirmar el nombre real del "
        "measurement y de los fields que hay en el bucket."
    )
    dias_diag = st.number_input("Buscar en los últimos N días", min_value=1, max_value=90, value=7)
    diagnosticar = st.button("Ver muestra de datos crudos")


# ----------------------------------------------------------------------------
# Funciones auxiliares
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client(url, token, org):
    return InfluxDBClient(url=url, token=token, org=org, timeout=30_000)


def explorar_datos_crudos(client, bucket, org, dias, limite=30):
    """Trae una muestra cruda (sin filtrar measurement/field) para inspección."""
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -{int(dias)}d)
  |> limit(n: {int(limite)})
'''
    tables = client.query_api().query_data_frame(flux, org=org)
    if isinstance(tables, list):
        df = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    else:
        df = tables if tables is not None else pd.DataFrame()
    return df


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


def cargar_hoja_excel(archivo, nombre_hoja):
    """Lee una hoja específica de un Excel subido y devuelve el DataFrame."""
    xls = pd.ExcelFile(archivo)
    if nombre_hoja not in xls.sheet_names:
        return None, xls.sheet_names
    df = pd.read_excel(xls, sheet_name=nombre_hoja)
    return df, xls.sheet_names


def agregar_excel_por_dia(df_excel, col_marca_temporal, tz_asumida):
    """
    Agrupa el Excel por día (derivado de la columna Marca temporal).
    - Columnas numéricas -> promedio
    - Columnas no numéricas -> valores únicos concatenados con '; '
    - Se agrega columna 'Registros_Excel' con el conteo de filas por día.
    """
    df = df_excel.copy()

    # Si el Excel ya trae una columna llamada "Fecha", se renombra para no
    # chocar con la columna "Fecha" que se genera a partir de Marca temporal.
    if "Fecha" in df.columns:
        df = df.rename(columns={"Fecha": "Fecha_original_excel"})

    marca = pd.to_datetime(df[col_marca_temporal], errors="coerce")

    if tz_asumida == "UTC (convertir a Colombia)":
        if marca.dt.tz is None:
            marca = marca.dt.tz_localize("UTC")
        marca = marca.dt.tz_convert(TZ)
    else:
        if marca.dt.tz is not None:
            marca = marca.dt.tz_convert(TZ)

    df["_fecha_dia"] = marca.dt.date.astype(str)
    df = df.dropna(subset=["_fecha_dia"])

    cols_numericas = df.select_dtypes(include="number").columns.tolist()
    cols_texto = [
        c for c in df.columns
        if c not in cols_numericas and c not in [col_marca_temporal, "_fecha_dia"]
    ]

    agg_dict = {c: "mean" for c in cols_numericas}
    for c in cols_texto:
        agg_dict[c] = lambda serie: "; ".join(
            sorted(set(str(v) for v in serie.dropna() if str(v).strip() != ""))
        )

    agrupado = df.groupby("_fecha_dia").agg(agg_dict)
    agrupado["Registros_Excel"] = df.groupby("_fecha_dia").size()
    agrupado = agrupado.reset_index().rename(columns={"_fecha_dia": "Fecha"})
    return agrupado


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
if "df_cruce" not in st.session_state:
    st.session_state.df_cruce = None

tab_influx, tab_excel = st.tabs(["📡 Consulta InfluxDB", "📊 Cruce con Excel"])

# ============================== TAB 1: INFLUXDB ==============================
with tab_influx:
    if diagnosticar:
        try:
            client = get_client(url, token, org)
            with st.spinner("Consultando datos crudos..."):
                df_raw = explorar_datos_crudos(client, bucket, org, dias_diag)
            if df_raw.empty:
                st.warning(
                    "No se encontró ningún dato en el bucket en ese rango de días. "
                    "Revisa: token, org, bucket y que el ESP32 esté escribiendo datos."
                )
            else:
                st.success("Datos crudos encontrados. Revisa las columnas `_measurement` y `_field`:")
                cols_mostrar = [c for c in ["_time", "_measurement", "_field", "_value"] if c in df_raw.columns]
                st.dataframe(df_raw[cols_mostrar] if cols_mostrar else df_raw, use_container_width=True)
                if "_measurement" in df_raw.columns:
                    st.info(f"Measurement(s) encontrado(s): {sorted(df_raw['_measurement'].unique().tolist())}")
                if "_field" in df_raw.columns:
                    st.info(f"Field(s) encontrado(s): {sorted(df_raw['_field'].unique().tolist())}")
        except Exception as e:
            st.error(f"Error al consultar datos crudos: {e}")

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
                valores_cols = [c for c in df.columns if c != "Fecha"]
                if df[valores_cols].isna().all().all():
                    st.warning(
                        "La consulta se ejecutó pero todos los valores vinieron vacíos (None). "
                        "Es muy probable que el nombre del *measurement* no sea el correcto, "
                        "o que no haya datos en ese rango de fechas. "
                        "Usa el panel '🔍 Diagnóstico' en la barra lateral para confirmarlo."
                    )
                else:
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

# ============================== TAB 2: CRUCE CON EXCEL ==============================
with tab_excel:
    st.subheader("Cruce de datos: Excel (Tabla de datos) + InfluxDB")
    st.caption(
        "Se agrega la información del Excel como columnas extra en la tabla diaria "
        "de InfluxDB, cruzando por día a partir de la columna 'Marca temporal'."
    )

    if st.session_state.df_resultado is None:
        st.warning(
            "Primero ve a la pestaña '📡 Consulta InfluxDB' y pulsa **Consultar** "
            "para generar la tabla diaria con la que se hará el cruce."
        )

    archivo_excel = st.file_uploader("Sube el archivo Excel", type=["xlsx", "xls"])

    col1, col2 = st.columns(2)
    with col1:
        nombre_hoja = st.text_input("Nombre de la hoja", value="Tabla de datos")
    with col2:
        tz_asumida = st.selectbox(
            "Zona horaria de 'Marca temporal'",
            ["Ya está en hora Colombia (UTC-5)", "UTC (convertir a Colombia)"],
        )

    if archivo_excel is not None:
        try:
            df_excel, hojas_disponibles = cargar_hoja_excel(archivo_excel, nombre_hoja)
        except Exception as e:
            st.error(f"Error al leer el archivo Excel: {e}")
            df_excel, hojas_disponibles = None, []

        if df_excel is None:
            st.error(
                f"No se encontró la hoja '{nombre_hoja}'. "
                f"Hojas disponibles en el archivo: {hojas_disponibles}"
            )
        elif "Marca temporal" not in df_excel.columns:
            st.error(
                "La hoja no tiene una columna llamada 'Marca temporal'. "
                f"Columnas encontradas: {df_excel.columns.tolist()}"
            )
        else:
            st.success(f"Hoja '{nombre_hoja}' cargada: {df_excel.shape[0]} filas, {df_excel.shape[1]} columnas.")
            with st.expander("Ver muestra del Excel cargado"):
                st.dataframe(df_excel.head(10), use_container_width=True)

            if st.button("Cruzar con InfluxDB", type="primary"):
                if st.session_state.df_resultado is None:
                    st.error("No hay datos de InfluxDB. Ve a la pestaña de Consulta InfluxDB primero.")
                else:
                    try:
                        df_excel_agrupado = agregar_excel_por_dia(df_excel, "Marca temporal", tz_asumida)
                        df_cruce = st.session_state.df_resultado.merge(
                            df_excel_agrupado, on="Fecha", how="left"
                        )
                        st.session_state.df_cruce = df_cruce
                        n_match = df_excel_agrupado["Fecha"].isin(
                            st.session_state.df_resultado["Fecha"]
                        ).sum()
                        st.success(
                            f"Cruce completado: {n_match} de {len(df_excel_agrupado)} día(s) del Excel "
                            f"coincidieron con la tabla de InfluxDB."
                        )
                    except Exception as e:
                        st.error(f"Error al cruzar los datos: {e}")

    if st.session_state.df_cruce is not None:
        st.markdown("#### Resultado del cruce")
        st.dataframe(st.session_state.df_cruce, use_container_width=True)

        csv_cruce = st.session_state.df_cruce.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Descargar CSV del cruce",
            data=csv_cruce,
            file_name="cruce_influx_excel.csv",
            mime="text/csv",
        )

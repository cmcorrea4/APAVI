# 🐔 Promedios diarios GALLINAS - InfluxDB + Excel + Correlaciones

App en Streamlit para consultar datos de sensores del bucket `GALLINAS` en InfluxDB Cloud, cruzarlos con un archivo Excel de producción avícola, y analizar correlaciones entre variables.

## ¿Qué hace la app?

La app tiene **3 pestañas**:

### 📡 1. Consulta InfluxDB
- Consulta el bucket de InfluxDB Cloud y calcula el **promedio de cada variable por día**, dividido en 4 franjas horarias (hora Colombia, UTC-5):
  - **Madrugada**: 00:00 - 06:00
  - **Mañana**: 06:00 - 12:00
  - **Tarde**: 12:00 - 18:00
  - **Noche**: 18:00 - 24:00
- Variables consultadas: `temperatura`, `humedad`, `luz_raw`, `luz_calibrada`, `escala_lux`, `ruido_adc`, `ruido_ajustado`.
- Filtro de fechas con calendario (rango de días).
- Genera **una fila por día**, con una columna por variable x franja (ej. `temperatura_Manana_06-12`).
- Panel de **🔍 Diagnóstico** en el sidebar para ver datos crudos y confirmar el nombre real del *measurement* y los *fields* del bucket, sin filtrar (útil si todo sale en `None`).
- Descarga de resultados en CSV.

### 📊 2. Cruce con Excel
- Se sube un archivo Excel (`.xlsx`/`.xls`) y se lee la hoja **"Tabla de datos"** (nombre editable).
- Se agrupa el Excel por día usando la columna **"Fecha"** (nombre editable):
  - Columnas numéricas → promedio.
  - Columnas de texto → valores únicos concatenados.
  - Se agrega `Registros_Excel` con el conteo de filas por día.
- Se hace un `left join` por `Fecha` contra la tabla diaria de InfluxDB de la pestaña 1.
- Panel de **🔍 Diagnóstico de fechas** para comparar el valor original del Excel vs. cómo lo interpretó pandas, y ver el rango de fechas disponible en InfluxDB — muy útil para detectar problemas de formato de fecha o de fechas que no se solapan entre ambas fuentes.
- Descarga del resultado combinado en CSV.

### 📈 3. Correlaciones
- Trabaja sobre la tabla resultante del cruce (InfluxDB + Excel).
- Selección de variables numéricas y método de correlación (`pearson`, `spearman`, `kendall`).
- **Mapa de calor** de correlación (Altair).
- Tabla con las **parejas de variables más correlacionadas**, ordenadas por valor absoluto.
- **Gráfico de dispersión** entre dos variables elegidas.
- Descarga de la matriz de correlación en CSV.

## Requisitos

Ver [`requirements.txt`](./requirements.txt):

```
streamlit
pandas
influxdb-client
tzdata
openpyxl
```

> `altair` no se lista porque ya viene incluido como dependencia de Streamlit (se usa para el mapa de calor de correlación).
> `tzdata` es necesaria para que `zoneinfo` resuelva `America/Bogota` correctamente en Streamlit Cloud (Linux).
> `openpyxl` es necesaria para que `pandas` pueda leer archivos `.xlsx`.

## Instalación local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Despliegue en Streamlit Cloud

1. Sube `app.py` y `requirements.txt` a un repositorio de GitHub.
2. En [share.streamlit.io](https://share.streamlit.io), crea una nueva app apuntando a ese repo y a `app.py` como archivo principal.
3. Streamlit Cloud instalará automáticamente las dependencias de `requirements.txt`.

### Credenciales de InfluxDB

Las credenciales (`URL`, `Token`, `Org`, `Bucket`) están precargadas como valores por defecto editables en el sidebar. **Para producción se recomienda moverlas a `st.secrets`** en vez de dejarlas escritas en el código:

1. Crear el archivo `.streamlit/secrets.toml` (local) o configurar los "Secrets" desde el panel de Streamlit Cloud:
   ```toml
   INFLUXDB_URL = "https://us-east-1-1.aws.cloud2.influxdata.com"
   INFLUXDB_TOKEN = "tu_token"
   INFLUXDB_ORG = "tu_org_id"
   INFLUXDB_BUCKET = "GALLINAS"
   ```
2. Reemplazar en `app.py` los valores `DEFAULT_*` por `st.secrets["INFLUXDB_URL"]`, etc.

## Estructura esperada del Excel

- Hoja llamada **"Tabla de datos"**.
- Columna **"Fecha"** con la fecha real de cada registro (una fila por día).
- El resto de columnas se agregan automáticamente (numéricas → promedio, texto → concatenado) al agrupar por día.

## Limitaciones conocidas

- **Retención de datos en InfluxDB Cloud (Free Plan):** el plan gratuito solo retiene datos de los últimos **30 días**. Si consultas fechas más antiguas y no aparece nada, probablemente ya fueron eliminados por la política de retención del bucket (no es un error de la app). Para conservar más histórico hay que subir a un plan pago y aumentar la retención del bucket.
- **Rendimiento en rangos largos:** la consulta a InfluxDB hace 4 llamadas Flux por cada día del rango seleccionado (una por franja horaria). Rangos muy largos (ej. un año completo) pueden ser lentos y arriesgar timeouts o límites de rate del plan gratuito.
- El cruce con Excel es por **coincidencia exacta de fecha** (`Fecha` del Excel == `Fecha` calculada en InfluxDB); si los rangos de fechas de ambas fuentes no se solapan, no habrá coincidencias.

## Solución de problemas

| Síntoma | Posible causa |
|---|---|
| Todos los valores de InfluxDB salen en `None` | El nombre del *measurement* configurado no coincide con el real. Usa el panel de Diagnóstico del sidebar para verlo. |
| El cruce con Excel da "0 de N días coincidieron" | Las fechas del Excel y de InfluxDB no se solapan, o la columna de fecha no se está interpretando como se espera. Usa el panel "🔍 Diagnóstico de fechas" en la pestaña de Excel. |
| Error `ImportError: Missing optional dependency 'openpyxl'` | Falta `openpyxl` en `requirements.txt` (ya está incluido en este proyecto). |
| No aparecen datos de fechas antiguas | Revisa la retención configurada del bucket en la consola de InfluxDB Cloud. |

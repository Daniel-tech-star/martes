import streamlit as st
import pandas as pd
import numpy as np
import re
from io import BytesIO
import xlsxwriter

st.set_page_config(page_title="Autoevaluación & Plan de Carrera", layout="wide")

# ------------------------------------------------------------------
# 1. CARGA DE DATOS BASE
# ------------------------------------------------------------------
FILE_BASE = "Valoracion_Jobs.xlsx"  # debe estar en el mismo directorio que app.py

@st.cache_data(show_spinner=True)
def load_base(file_path: str):
    """Carga archivo base con competencias y comportamientos."""
    df_comp = pd.read_excel(file_path, sheet_name="Competencias")
    df_beh = pd.read_excel(file_path, sheet_name="Comportamientos")
    return df_comp, df_beh

try:
    df_comp, df_beh = load_base(FILE_BASE)
except FileNotFoundError:
    st.error("⚠️ No se encontró 'Valoracion_Jobs.xlsx' en el servidor. Sube el archivo al repositorio.")
    st.stop()

# Columnas de competencias (D‑K) — las 8
competencias_cols = df_comp.columns[3:11].tolist()

# ------------------------------------------------------------------
# 2. FORMULARIO DE IDENTIFICACIÓN
# ------------------------------------------------------------------
st.title("Formulario de Autoevaluación de Competencias y Comportamientos")

nombre = st.text_input("Nombre completo")

areas_unique = sorted(df_comp["Area"].dropna().unique())
area_placeholder = "-- Selecciona un área --"
selected_area = st.selectbox("Área", [area_placeholder] + areas_unique)

if selected_area != area_placeholder:
    puestos_area = sorted(df_comp[df_comp["Area"] == selected_area]["Job Title"].unique())
else:
    puestos_area = []

puesto_placeholder = "-- Selecciona tu puesto actual --"
selected_puesto = st.selectbox("Puesto actual", [puesto_placeholder] + puestos_area)

# ------------------------------------------------------------------
# 3. AUTOEVALUACIÓN DE COMPETENCIAS
# ------------------------------------------------------------------

st.header("1️⃣ Evaluación de Competencias (reparte 100 puntos)")
cols = st.columns(4)
competencias_input = {}
for idx, comp in enumerate(competencias_cols):
    with cols[idx % 4]:
        val = st.number_input(comp, min_value=0, max_value=100, step=1, key=f"comp_{comp}")
        competencias_input[comp] = val

suma_comp = sum(competencias_input.values())
st.markdown(f"**Total asignado:** {suma_comp} / 100")

# ------------------------------------------------------------------
# 4. AUTOEVALUACIÓN DE COMPORTAMIENTOS POR COMPETENCIA
# ------------------------------------------------------------------

st.header("2️⃣ Evaluación de Comportamientos (1 = Nunca, 5 = Muy frecuentemente)")
beh_input = {}
text_to_val = {"Nunca":1, "Raramente":2, "Ocasionalmente":3, "Frecuentemente":4, "Muy frecuentemente":5}

for comp in competencias_cols:
    st.subheader(comp)
    comportamientos_comp = df_beh[df_beh["Competencias"] == comp]["Comportamientos"].dropna().tolist()
    if not comportamientos_comp:
        st.info("Sin comportamientos definidos en archivo base para esta competencia.")
        continue
    for i, beh in enumerate(comportamientos_comp):
        clean_beh = re.sub(r"^\d+\.\s*", "", beh).strip()
        beh_input[clean_beh] = st.slider(clean_beh, 1, 5, 3, key=f"beh_{comp}_{i}")

# ------------------------------------------------------------------
# 5. PROCESAMIENTO Y PLAN DE CARRERA
# ------------------------------------------------------------------

def parse_ipe(val):
    if pd.isna(val):
        return np.nan
    s = str(val)
    if "-" in s:
        parts = [float(p) for p in s.split("-") if p.strip().isdigit()]
        return np.mean(parts) if parts else np.nan
    try:
        return float(s)
    except:
        return np.nan

# Pre‑procesar info de roles sólo una vez
roles_df = df_comp[["Job Title", "Area", *competencias_cols]].copy()
roles_df = roles_df.dropna(subset=["Job Title"]).reset_index(drop=True)
# Añadir columna IPE desde hoja de comportamientos
ipe_map = df_beh[["Job Title", "IPE"]].drop_duplicates()
ipe_map["IPE_val"] = ipe_map["IPE"].apply(parse_ipe)
roles_df = roles_df.merge(ipe_map[["Job Title", "IPE_val"]], on="Job Title", how="left")

# Botón principal
generar = st.button("✅ Generar Plan de Carrera")

if generar:
    # Validaciones
    if selected_area == area_placeholder or selected_puesto == puesto_placeholder:
        st.error("Selecciona tu área y puesto actual.")
        st.stop()
    if suma_comp != 100:
        st.error("Los puntos asignados a competencias deben sumar exactamente 100.")
        st.stop()
    if not nombre:
        st.error("Por favor, introduce tu nombre.")
        st.stop()

    # Datos de persona
    person_comp_series = pd.Series(competencias_input)
    weights = person_comp_series / 100  # ya suman 100

    # Comportamientos persona en DataFrame
    df_beh_person = pd.DataFrame({"Comportamientos_clean": list(beh_input.keys()),
                                 "Valor_Persona": list(beh_input.values())})

    # Algoritmo de score
    results = []
    current_row = roles_df[roles_df["Job Title"] == selected_puesto]
    ipe_current = current_row["IPE_val"].iloc[0] if not current_row.empty else 0

    for _, role in roles_df.iterrows():
        job = role["Job Title"]
        ipe = role["IPE_val"]
        area = role["Area"]
        # Gap de competencias ponderado
        role_comp = role[competencias_cols].astype(float)
        gap_comp = (role_comp - person_comp_series).abs()
        score_comp = (gap_comp * weights).sum()
        # Gap de comportamientos (cuando existan)
        role_beh = df_beh[df_beh["Job Title"] == job][["Comportamientos"]]
        role_beh["Comportamientos_clean"] = role_beh["Comportamientos"].apply(lambda x: re.sub(r"^\d+\.\s*", "", x).strip())
        merged = pd.merge(df_beh_person, role_beh, on="Comportamientos_clean", how="inner")
        if not merged.empty:
            # Asumir valor objetivo 5 si no hay puntaje en archivo base
            merged["Valor_Puesto"] = 5
            gap_beh = (merged["Valor_Puesto"] - merged["Valor_Persona"]).abs().mean()
        else:
            gap_beh = np.nan
        score_total = 0.7 * score_comp + 0.3 * (gap_beh if not np.isnan(gap_beh) else 0)
        results.append({
            "Job Title": job,
            "Area": area,
            "IPE": ipe,
            "Gap Competencias": round(score_comp, 2),
            "Gap Comportamientos": round(gap_beh, 2) if not np.isnan(gap_beh) else None,
            "Score Total": round(score_total, 2)
        })

    df_results = pd.DataFrame(results).sort_values("Score Total").reset_index(drop=True)

    # --------------------------------------------
    # CREAR EXCEL PLAN DE CARRERA
    # --------------------------------------------
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_results.to_excel(writer, index=False, sheet_name="Alternativas")
        # Formato
        ws = writer.sheets["Alternativas"]
        ws.set_column("A:F", 22)
    buffer.seek(0)

    st.success("Plan de carrera generado ✅")
    st.download_button(
        label="Descargar plan de carrera (Excel)",
        data=buffer,
        file_name=f"plan_carrera_{nombre.replace(' ', '_')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# app.py
import os
from io import BytesIO
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Simulador de Moldeo EPP", layout="wide", page_icon="🧪")
st.title("🧪 Simulador de Moldeo EPP – con Modelos y Wet/Dry")

st.markdown("""
Este simulador toma tus **parámetros de proceso** (vapor, filling, cooling, aging) y:
1) Calcula una **predicción** de peso **WET** y **DRY**.  
2) Te deja **elegir un modelo** desde tu Excel para traer **Part Number, Part Name, Bead y Cure Time**, más **targets** de wet/dry si existen.  
3) Compara **Simulación vs Teórico (Excel) vs Real (lo que midas)**.
""")

# =========================
# EXCEL: Carga de modelos
# =========================
st.sidebar.header("📄 Archivo de modelos")
up = st.sidebar.file_uploader("Sube tu Excel de modelos", type=["xlsx"])

# Opción: ruta local ya conocida (déjala vacía si no aplica)
ruta_local_opcional = "/mnt/data/EPP PARTS PRD-WI-023 RDC Part and Weight ALL Model Rev 86.xlsx"
if up is not None:
    excel_bytes = up.read()
    excel_file = BytesIO(excel_bytes)
elif os.path.exists(ruta_local_opcional):
    with open(ruta_local_opcional, "rb") as f:
        excel_file = BytesIO(f.read())
else:
    excel_file = None

def normaliza_col(s: str) -> str:
    return (
        s.strip()
        .lower()
        .replace("\n"," ")
        .replace("\r"," ")
        .replace("\t"," ")
        .replace("  "," ")
    )

# Intentar múltiples hojas
df_models = None
if excel_file is not None:
    # leer todas las hojas y concatenar columnas comunes
    xl = pd.ExcelFile(excel_file)
    frames = []
    for name in xl.sheet_names:
        try:
            tmp = xl.parse(name)
            if len(tmp.columns) == 0 or len(tmp) == 0:
                continue
            # Normalizar encabezados
            tmp.columns = [normaliza_col(str(c)) for c in tmp.columns]
            frames.append(tmp)
        except Exception:
            continue
    if frames:
        df_all = pd.concat(frames, ignore_index=True)
        # columnas candidatas
        # notación flexible para distintos nombres que pueda tener tu hoja
        cand_partnum = [c for c in df_all.columns if "part" in c and "number" in c or c == "partnumber" or c == "part no." or c == "p/n" or c == "pn"]
        cand_partname = [c for c in df_all.columns if "part" in c and "name" in c or c in ("description","desc")]
        cand_bead = [c for c in df_all.columns if "bead" in c or "density" in c or "material" in c]
        cand_cure = [c for c in df_all.columns if "cure" in c and "time" in c or "autocl" in c or "aging" in c]

        # Pesos target (intenta múltiple nomenclatura)
        cand_wet_min = [c for c in df_all.columns if "wet" in c and "min" in c]
        cand_wet_nom = [c for c in df_all.columns if "wet" in c and ("nom" in c or "target" in c)]
        cand_wet_max = [c for c in df_all.columns if "wet" in c and "max" in c]

        cand_dry_min = [c for c in df_all.columns if "dry" in c and "min" in c]
        cand_dry_nom = [c for c in df_all.columns if "dry" in c and ("nom" in c or "target" in c)]
        cand_dry_max = [c for c in df_all.columns if "dry" in c and "max" in c]

        # Mapear columnas
        col_partnum = cand_partnum[0] if cand_partnum else None
        col_partname = cand_partname[0] if cand_partname else None
        col_bead = cand_bead[0] if cand_bead else None
        col_cure = cand_cure[0] if cand_cure else None

        col_wet_min = cand_wet_min[0] if cand_wet_min else None
        col_wet_nom = cand_wet_nom[0] if cand_wet_nom else None
        col_wet_max = cand_wet_max[0] if cand_wet_max else None

        col_dry_min = cand_dry_min[0] if cand_dry_min else None
        col_dry_nom = cand_dry_nom[0] if cand_dry_nom else None
        col_dry_max = cand_dry_max[0] if cand_dry_max else None

        # Filtrar filas válidas (que tengan al menos PartNumber y PartName)
        df_core = df_all.copy()
        if col_partnum:
            df_core = df_core[~df_core[col_partnum].isna()]
        if col_partname:
            df_core = df_core[~df_core[col_partname].isna()]

        # Selección de columnas interesantes
        keep_cols = []
        for c in [col_partnum, col_partname, col_bead, col_cure,
                  col_wet_min, col_wet_nom, col_wet_max,
                  col_dry_min, col_dry_nom, col_dry_max]:
            if c and c in df_core.columns:
                keep_cols.append(c)
        df_models = df_core[keep_cols].drop_duplicates().reset_index(drop=True)

if df_models is None:
    st.info("🔼 Sube tu Excel de modelos para habilitar el selector (o coloca el archivo en la ruta local opcional).")
else:
    # Para mostrar bonito, crea columnas "amigables"
    def first_or_blank(row, col):
        return row[col] if (col and col in row and pd.notna(row[col])) else ""

    # Construir etiqueta lista
    def etiqueta_modelo(row):
        pn = first_or_blank(row, df_models.columns[0])  # asumimos la primera col es partnumber mapeada
        # intenta partname
        # busca una col que contenga 'name' o 'desc'
        colname = None
        for c in df_models.columns:
            if "name" in c or "desc" in c:
                colname = c; break
        nm = first_or_blank(row, colname) if colname else ""
        return f"{pn} — {nm}".strip(" —")

    opciones = [etiqueta_modelo(df_models.loc[i]) for i in range(len(df_models))]
    sel = st.selectbox("🧾 Modelo (desde Excel)", opciones) if opciones else None
    idx_sel = opciones.index(sel) if sel in opciones else None

# =========================
# Parámetros del MOLDE / proceso (simulador)
# =========================
st.sidebar.header("⚙️ Parámetros de proceso")
L_base = st.sidebar.number_input("Largo nominal (mm)", 200, 3000, 1200, 10)
W_base = st.sidebar.number_input("Ancho nominal (mm)", 200, 3000, 800, 10)
T_base = st.sidebar.number_input("Espesor nominal (mm)", 10, 400, 50, 1)

# Beads típicos EPP
BEAD_DENSITIES = {15:50, 22:30, 35:20, 42:16}

# Si el Excel trae bead (texto), intenta mapear a 15/22/35/42
def infer_bead_from_text(txt):
    if not isinstance(txt, str):
        return None
    t = txt.lower()
    for k in (15,22,35,42):
        if str(k) in t:
            return k
    # Si menciona g/l explícito:
    for k,v in BEAD_DENSITIES.items():
        if f"{v}" in t:
            return k
    return None

steam_pressure = st.sidebar.slider("Presión de vapor ICP (bar)", 0.6, 2.2, 1.5, 0.05)
steam_time = st.sidebar.slider("Tiempo de vapor (s)", 1, 20, 7, 1)
temp_fixed = st.sidebar.slider("Temperatura FIXED SIDE (°C)", 25, 110, 60, 1)
temp_mobile = st.sidebar.slider("Temperatura MOBILE SIDE (°C)", 25, 110, 50, 1)
fill_time1 = st.sidebar.slider("Filling time 1 (s)", 1, 10, 3, 1)
fill_time2 = st.sidebar.slider("Filling time 2 (s)", 0, 10, 2, 1)
cooling_time = st.sidebar.slider("Cooling time (s)", 3, 60, 20, 1)
water_on = st.sidebar.checkbox("Agua de enfriamiento ON", True)
aging_quality = st.sidebar.slider("Calidad de aging/autoclave (0=deficiente, 1=óptima)", 0.0, 1.0, 0.7, 0.05)

# =========================
# Modelo heurístico (como antes)
# =========================
vol_L_nominal = (L_base * W_base * T_base) * 1e-6
avg_mold_temp = (temp_fixed + temp_mobile) / 2
temp_delta = abs(temp_fixed - temp_mobile)

# Packing → densidad efectiva
pack_gain = 0.02*(fill_time1 - 3) + 0.015*(fill_time2 - 2)
pack_gain = float(np.clip(pack_gain, -0.05, 0.08))

# Si elegiste un modelo y hay bead declarado, úsalo para fijar densidad básica
bead_from_excel = None
if df_models is not None and idx_sel is not None:
    row = df_models.iloc[idx_sel]
    # Busca columna bead
    col_bead = None
    for c in df_models.columns:
        if "bead" in c or "density" in c or "material" in c:
            col_bead = c; break
    bead_from_excel = infer_bead_from_text(str(row[col_bead])) if col_bead else None

bead = bead_from_excel if bead_from_excel in BEAD_DENSITIES else st.sidebar.selectbox(
    "Bead (si Excel no especifica)", [15,22,35,42], index=2
)
densidad_bead_nom = BEAD_DENSITIES[bead]
densidad_efectiva = densidad_bead_nom * (1.0 + pack_gain)

# Expansión vs vapor/tiempo/temperatura
sigmoid = lambda x: 1/(1+np.exp(-x))
exp_steam = 0.03 * sigmoid(6*(steam_pressure - 1.35))
exp_time  = 0.015 * np.tanh((steam_time - 6)/6)
exp_temp  = 0.012 * np.tanh((avg_mold_temp - 55)/25)
expansion_total = 1.0 + exp_steam + exp_time + exp_temp

# Shrink / colapso
base_shrink = 0.008
shrink_deltaT = 0.001 * max(temp_delta - 20, 0)
shrink_cooling = 0.012 * max(15 - cooling_time, 0)/15
shrink_oversteam = 0.008 if (steam_pressure > 1.8 and steam_time > 10) else 0.0
aging_relief = 0.6 * aging_quality
total_shrink = max((base_shrink + shrink_deltaT + shrink_cooling + shrink_oversteam) - aging_relief*0.008, 0)

mult_dim = expansion_total * (1.0 - total_shrink)
L = max(L_base * mult_dim, 0)
W = max(W_base * mult_dim, 0)
vol_L_final = (L * W * T_base) * 1e-6

# ====== Predicción de PESO WET/DRY ======
# Peso “wet” (recién salida + agua superficial/intersticial)
peso_wet_sim = densidad_efectiva * vol_L_final

# Factor de humedad (heurístico): más cooling y mejor aging → menos agua retenida
# Rango típico 0.5%–3% del peso (ajústalo con tus datos)
hum_base = 0.025                              # 2.5% base
hum_cooling = -0.015 * min(max((cooling_time-15)/25, 0), 1)  # hasta -1.5% si cooling largo
hum_aging   = -0.010 * aging_quality                          # hasta -1.0% si aging óptimo
hum_water   = -0.003 if water_on else 0                       # -0.3% con agua
hum_penalty =  0.006 if (steam_pressure>1.8 and steam_time>10) else 0  # +0.6% si sobre-vapor
hum_frac = np.clip(hum_base + hum_cooling + hum_aging + hum_water + hum_penalty, 0.005, 0.03)

peso_dry_sim = peso_wet_sim * (1 - hum_frac)

# Redondeos
L = round(L,2); W = round(W,2)
peso_wet_sim = round(peso_wet_sim,1)
peso_dry_sim = round(peso_dry_sim,1)

# =========================
# Datos teóricos desde Excel
# =========================
teo = {
    "part_number":"", "part_name":"", "bead_text":"", "cure_time":"",
    "wet_min":None,"wet_nom":None,"wet_max":None,
    "dry_min":None,"dry_nom":None,"dry_max":None
}

if df_models is not None and idx_sel is not None:
    row = df_models.iloc[idx_sel]
    # Part Number
    teo["part_number"] = str(row[df_models.columns[0]])
    # Part Name (primera col con 'name' o 'desc')
    colname = None
    for c in df_models.columns:
        if "name" in c or "desc" in c:
            colname = c; break
    teo["part_name"] = str(row[colname]) if colname else ""

    # Bead text
    col_bead_txt = None
    for c in df_models.columns:
        if "bead" in c or "density" in c or "material" in c:
            col_bead_txt = c; break
    teo["bead_text"] = str(row[col_bead_txt]) if col_bead_txt else f"{bead} (≈{densidad_bead_nom} g/L)"

    # Cure time
    col_cure = None
    for c in df_models.columns:
        if ("cure" in c and "time" in c) or ("autocl" in c) or ("aging" in c):
            col_cure = c; break
    teo["cure_time"] = str(row[col_cure]) if col_cure else ""

    # Wet/Dry min/nom/max
    def safe_num(v):
        try:
            if pd.isna(v): return None
            return float(v)
        except: return None

    # Buscar columnas candidatas
    def find_col(substrs):
        for s in substrs:
            for c in df_models.columns:
                if s in c:
                    return c
        return None

    wet_min_c = find_col(["wet","min"])
    wet_nom_c = find_col(["wet","nom"])
    wet_max_c = find_col(["wet","max"])
    dry_min_c = find_col(["dry","min"])
    dry_nom_c = find_col(["dry","nom"])
    dry_max_c = find_col(["dry","max"])

    teo["wet_min"] = safe_num(row.get(wet_min_c)) if wet_min_c else None
    teo["wet_nom"] = safe_num(row.get(wet_nom_c)) if wet_nom_c else None
    teo["wet_max"] = safe_num(row.get(wet_max_c)) if wet_max_c else None

    teo["dry_min"] = safe_num(row.get(dry_min_c)) if dry_min_c else None
    teo["dry_nom"] = safe_num(row.get(dry_nom_c)) if dry_nom_c else None
    teo["dry_max"] = safe_num(row.get(dry_max_c)) if dry_max_c else None

# =========================
# Entrada de datos REALES
# =========================
st.subheader("🧪 Datos reales (ingrésalos para comparar)")
colR1, colR2 = st.columns(2)
with colR1:
    wet_real = st.number_input("Wet weight REAL (g)", min_value=0.0, value=0.0, step=1.0, format="%.1f")
with colR2:
    dry_real = st.number_input("Dry weight REAL (g)", min_value=0.0, value=0.0, step=1.0, format="%.1f")

# =========================
# Encabezado del modelo
# =========================
st.subheader("📦 Modelo seleccionado")
cM1, cM2, cM3, cM4 = st.columns([1.2,1.6,1,1])
cM1.metric("Part Number", teo["part_number"])
cM2.metric("Part Name", teo["part_name"])
cM3.metric("Bead", teo["bead_text"])
cM4.metric("Cure Time", teo["cure_time"])

# =========================
# KPIs simulados
# =========================
st.subheader("📊 Resultados simulados (proceso actual)")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Wet SIM (g)", f"{peso_wet_sim:,.1f}")
k2.metric("Dry SIM (g)", f"{peso_dry_sim:,.1f}")
k3.metric("Largo SIM (mm)", f"{L:,.2f}")
k4.metric("Ancho SIM (mm)", f"{W:,.2f}")

# =========================
# Comparaciones y cumplimiento
# =========================
def comp_status(valor, vmin, vmax):
    if valor is None: return "—"
    if vmin is not None and valor < vmin: return "⬇️ Bajo"
    if vmax is not None and valor > vmax: return "⬆️ Alto"
    return "✅ OK"

st.subheader("🧮 Comparativa Wet/Dry")
tabla = []

# Sim vs Teórico
tabla.append({
    "Métrica":"Wet SIM vs Wet NOM (Excel)",
    "Δ (g)": None if teo["wet_nom"] is None else round(peso_wet_sim - teo["wet_nom"],1),
    "Estado": comp_status(peso_wet_sim, teo["wet_min"], teo["wet_max"]) if teo["wet_min"] or teo["wet_max"] else "—"
})
tabla.append({
    "Métrica":"Dry SIM vs Dry NOM (Excel)",
    "Δ (g)": None if teo["dry_nom"] is None else round(peso_dry_sim - teo["dry_nom"],1),
    "Estado": comp_status(peso_dry_sim, teo["dry_min"], teo["dry_max"]) if teo["dry_min"] or teo["dry_max"] else "—"
})

# Real vs Teórico
if wet_real > 0:
    tabla.append({
        "Métrica":"Wet REAL vs Wet NOM (Excel)",
        "Δ (g)": None if teo["wet_nom"] is None else round(wet_real - teo["wet_nom"],1),
        "Estado": comp_status(wet_real, teo["wet_min"], teo["wet_max"]) if teo["wet_min"] or teo["wet_max"] else "—"
    })
if dry_real > 0:
    tabla.append({
        "Métrica":"Dry REAL vs Dry NOM (Excel)",
        "Δ (g)": None if teo["dry_nom"] is None else round(dry_real - teo["dry_nom"],1),
        "Estado": comp_status(dry_real, teo["dry_min"], teo["dry_max"]) if teo["dry_min"] or teo["dry_max"] else "—"
    })

st.dataframe(pd.DataFrame(tabla), use_container_width=True)

# =========================
# Barras comparativas
# =========================
def plot_barras(titulo, sim, real, nom):
    labels = []
    valores = []
    if sim is not None:
        labels.append("SIM")
        valores.append(sim)
    if real and real > 0:
        labels.append("REAL")
        valores.append(real)
    if nom is not None:
        labels.append("NOM")
        valores.append(nom)
    if not labels:
        st.info("No hay datos suficientes para graficar.")
        return
    fig, ax = plt.subplots()
    ax.bar(labels, valores)
    ax.set_title(titulo)
    ax.set_ylabel("g")
    for i, v in enumerate(valores):
        ax.text(i, v, f"{v:.1f}", ha='center', va='bottom')
    st.pyplot(fig, use_container_width=True)

colG1, colG2 = st.columns(2)
with colG1:
    plot_barras("WET: SIM vs REAL vs NOM", peso_wet_sim, wet_real, teo["wet_nom"])
with colG2:
    plot_barras("DRY: SIM vs REAL vs NOM", peso_dry_sim, dry_real, teo["dry_nom"])

# =========================
# Vista superior pieza (dimensiones)
# =========================
st.subheader("🧭 Vista superior de la pieza (W × L)")
fig, ax = plt.subplots()
rect = plt.Rectangle((0, 0), W, L, fc="#9AD1F5", ec="black")
ax.add_patch(rect)
ax.set_xlim(0, max(2000, W*1.1))
ax.set_ylim(0, max(2000, L*1.1))
ax.set_aspect('equal')
ax.set_xlabel("Ancho (mm)")
ax.set_ylabel("Largo (mm)")
st.pyplot(fig, use_container_width=True)

# =========================
# Exportar todo a Excel
# =========================
st.subheader("📥 Exportar reporte")
out = {
    "Part Number":[teo["part_number"]],
    "Part Name":[teo["part_name"]],
    "Bead (texto)":[teo["bead_text"]],
    "Cure Time":[teo["cure_time"]],
    "Bead asignado":[bead],
    "Densidad bead (g/L)":[BEAD_DENSITIES[bead]],
    "Largo_nom_mm":[L_base],
    "Ancho_nom_mm":[W_base],
    "Espesor_mm":[T_base],
    "ICP_bar":[steam_pressure],
    "Vapor_s":[steam_time],
    "Temp_FIXED_C":[temp_fixed],
    "Temp_MOBILE_C":[temp_mobile],
    "DeltaT_C":[temp_delta],
    "Fill1_s":[fill_time1],
    "Fill2_s":[fill_time2],
    "Cooling_s":[cooling_time],
    "Agua_ON":[water_on],
    "Aging_0a1":[aging_quality],
    "Wet_SIM_g":[peso_wet_sim],
    "Dry_SIM_g":[peso_dry_sim],
    "Wet_NOM_g":[teo["wet_nom"]],
    "Dry_NOM_g":[teo["dry_nom"]],
    "Wet_MIN_g":[teo["wet_min"]],
    "Wet_MAX_g":[teo["wet_max"]],
    "Dry_MIN_g":[teo["dry_min"]],
    "Dry_MAX_g":[teo["dry_max"]],
    "Wet_REAL_g":[wet_real if wet_real>0 else None],
    "Dry_REAL_g":[dry_real if dry_real>0 else None],
}
df_out = pd.DataFrame(out)
st.dataframe(df_out, use_container_width=True)

buf = BytesIO()
with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
    df_out.to_excel(wr, index=False, sheet_name="Reporte")
buf.seek(0)
st.download_button(
    "Descargar reporte (Excel)",
    data=buf,
    file_name="reporte_simulador_epp.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# =========================
# Tips/alertas rápidas
# =========================
# Riesgos
riesgos = []
collapse_score = 0.0
collapse_score += max(steam_pressure - 1.7, 0) * 1.2
collapse_score += max(steam_time - 10, 0) * 0.5
collapse_score += max(15 - cooling_time, 0) * 0.2
collapse_score += max(temp_delta - 25, 0) * 0.1
collapse_score -= aging_quality * 0.8

if collapse_score > 0.8:
    riesgos.append("⚠️ Riesgo de **colapso/warpage** por sobre-vapor, cooling corto o ΔT alto.")
elif collapse_score > 0.4:
    riesgos.append("ℹ️ Vigilar **colapso**: baja ICP o sube cooling / mejora aging.")

fusion_score = 0.0
fusion_score += max(1.2 - steam_pressure, 0) * 1.0
fusion_score += max(6 - steam_time, 0) * 0.3
fusion_score += max(50 - ((temp_fixed + temp_mobile)/2), 0) * 0.05
fusion_score -= pack_gain * 4
if fusion_score > 0.8:
    riesgos.append("⚠️ **Fusión débil**: +ICP/tiempo de vapor o +temperatura de molde.")
elif fusion_score > 0.4:
    riesgos.append("ℹ️ **Fusión justa**: considera +0.05 bar ICP o +2–3 s vapor.")

if pack_gain > 0.06:
    riesgos.append("ℹ️ **Sobre-packing**: puede inducir tensiones internas / marcas.")

for r in riesgos:
    st.warning(r)

st.caption("Modelo heurístico educativo. Ajusta coeficientes con tus datos de línea para mayor precisión.")

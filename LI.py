
import streamlit as st
import sqlite3
import pandas as pd
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
import plotly.express as px
import json
import requests
import urllib3  # <== Adicionado

# Desabilita os avisos de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Mapa de Volumes", layout="wide")

st.title("📦 Mapa e Heatmap de Volumes por Cidade, Estado e Região")
st.markdown("Este painel interativo mostra a distribuição dos volumes por localidade com base nos dados da tabela `Relatorios_CTEs`.")

# === CONFIGURAÇÕES === #
db_path = "logistica_interna.db"

uf_para_regiao = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste", "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul"
}

@st.cache_data(show_spinner=False)
def carregar_dados():
    conn = sqlite3.connect(db_path)
    query = """
    SELECT cidade_destinatario, uf_destinatario, SUM(quantidade_de_volumes) as total_volumes
    FROM Relatorios_CTEs
    GROUP BY cidade_destinatario, uf_destinatario
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

@st.cache_data(show_spinner=True)
def geocode_cidades(df):
    geolocator = Nominatim(user_agent="logistica_mapper")
    latitudes, longitudes = [], []
    for cidade, uf in zip(df['cidade_destinatario'], df['uf_destinatario']):
        try:
            loc = geolocator.geocode(f"{cidade}, {uf}, Brasil")
            if loc:
                latitudes.append(loc.latitude)
                longitudes.append(loc.longitude)
            else:
                latitudes.append(None)
                longitudes.append(None)
        except:
            latitudes.append(None)
            longitudes.append(None)
    df['lat'] = latitudes
    df['lon'] = longitudes
    return df.dropna(subset=['lat', 'lon'])

df = carregar_dados()
df['regiao'] = df['uf_destinatario'].map(uf_para_regiao)

# === SIDEBAR === #
with st.sidebar:
    st.header("🔎 Filtros")
    regioes = ["Todas"] + sorted(df['regiao'].dropna().unique().tolist())
    regiao_selecionada = st.selectbox("Selecione a Região:", regioes)

# === APLICA FILTRO === #
df_filtrado = df.copy() if regiao_selecionada == "Todas" else df[df['regiao'] == regiao_selecionada]

st.success(f"{len(df_filtrado)} registros encontrados para a região: **{regiao_selecionada}**")
st.dataframe(df_filtrado, use_container_width=True)

# === GEOLOCALIZAÇÃO === #
with st.spinner("🔍 Geocodificando cidades..."):
    df_geo = geocode_cidades(df_filtrado)

# === CARREGA GEOJSON DO BRASIL === #
geojson_url = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
try:
    response = requests.get(geojson_url, verify=False)
    response.raise_for_status()
    estados_geojson = response.json()
except requests.exceptions.RequestException as e:
    st.error(f"Erro ao carregar o GeoJSON: {e}")
    st.stop()

# === FUNÇÃO PARA AGRUPAR GEOJSON POR REGIÃO === #
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import geojson

def agrupar_por_regiao(geojson_obj, uf_to_regiao):
    regiao_geometrias = {}
    for feature in geojson_obj['features']:
        uf = feature['properties']['sigla']
        regiao = uf_to_regiao.get(uf)
        if regiao:
            regiao_geometrias.setdefault(regiao, []).append(feature['geometry'])

    features = []
    for regiao, geoms in regiao_geometrias.items():
        shapes = [shape(geom) for geom in geoms]
        multi = unary_union(shapes)
        features.append(geojson.Feature(geometry=mapping(multi), properties={"sigla": regiao}))

    return geojson.FeatureCollection(features)

regioes_geojson = agrupar_por_regiao(estados_geojson, uf_para_regiao)

# === ABA DE VISUALIZAÇÕES === #
tab1, tab2, tab3 = st.tabs(["📍 Mapa por Cidade", "🗺️ Heatmap por UF", "🧭 Heatmap por Região"])

with tab1:
    st.subheader(f"📍 Mapa de volumes por cidade ({regiao_selecionada})")
    if df_geo.empty:
        st.warning("Nenhum dado geocodificado para exibir o mapa.")
    else:
        mapa = folium.Map(location=[-15.788497, -47.879873], zoom_start=4)
        for _, row in df_geo.iterrows():
            folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=max(row['total_volumes']**0.5, 3),
                popup=f"{row['cidade_destinatario']} - {row['uf_destinatario']}: {row['total_volumes']} volumes",
                color='blue', fill=True, fill_opacity=0.6
            ).add_to(mapa)
        st_folium(mapa, width=900, height=600)

with tab2:
    st.subheader(f"🗺️ Heatmap por estado (UF) - {regiao_selecionada}")
    df_estado = df_filtrado.groupby('uf_destinatario')['total_volumes'].sum().reset_index()
    if df_estado.empty:
        st.warning("Nenhum dado para exibir o heatmap por estado.")
    else:
        fig_estado = px.choropleth(
            df_estado,
            geojson=estados_geojson,
            locations='uf_destinatario',
            featureidkey="properties.sigla",
            color='total_volumes',
            color_continuous_scale="YlOrRd",
            labels={'total_volumes': 'Volumes'}
        )
        fig_estado.update_geos(
            visible=False,
            fitbounds=None,
            projection_scale=5,
            center={"lat": -14.2350, "lon": -51.9253},
            lataxis_range=[-40, 5],
            lonaxis_range=[-75, -34]
        )
        fig_estado.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
        st.plotly_chart(fig_estado, use_container_width=True)

with tab3:
    st.subheader(f"🧭 Heatmap por região - {regiao_selecionada}")
    df_regiao = df_filtrado.groupby('regiao')['total_volumes'].sum().reset_index()
    if df_regiao.empty:
        st.warning("Nenhum dado para o heatmap por região.")
    else:
        fig_regiao = px.choropleth(
            df_regiao,
            geojson=regioes_geojson,
            locations='regiao',
            featureidkey="properties.sigla",
            color='total_volumes',
            color_continuous_scale="YlGnBu",
            labels={'total_volumes': 'Volumes'}
        )
        fig_regiao.update_geos(
            visible=False,
            fitbounds=None,
            projection_scale=5,
            center={"lat": -14.2350, "lon": -51.9253},
            lataxis_range=[-40, 5],
            lonaxis_range=[-75, -34]
        )
        fig_regiao.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
        st.plotly_chart(fig_regiao, use_container_width=True)
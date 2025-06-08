import streamlit as st
import sqlite3
import pandas as pd
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
import plotly.express as px
import json
import requests
import urllib3
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
import geojson

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Mapa de Volumes e Análise de Rotas", layout="wide")

st.title("📦 Mapa, Heatmap e KPIs de Volumes por Cidade, Estado e Região")
st.markdown("Este painel interativo mostra a distribuição dos volumes por localidade com base nos dados da tabela `Relatorios_CTEs`. Também apresenta análises para estudo das rotas e frentes de entrega.")

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

with st.sidebar:
    st.header("🔎 Filtros")
    regioes = ["Todas"] + sorted(df['regiao'].dropna().unique().tolist())
    regiao_selecionada = st.selectbox("Selecione a Região:", regioes)

df_filtrado = df.copy() if regiao_selecionada == "Todas" else df[df['regiao'] == regiao_selecionada]

# KPIs
total_volumes = df_filtrado['total_volumes'].sum()
total_cidades = df_filtrado['cidade_destinatario'].nunique()
total_ufs = df_filtrado['uf_destinatario'].nunique()
media_volume_rota = df_filtrado['total_volumes'].mean()

col1, col2, col3, col4 = st.columns(4)
col1.metric("📦 Total de Volumes", f"{total_volumes:,}")
col2.metric("🏙️ Total de Cidades", f"{total_cidades}")
col3.metric("🗺️ Total de UFs", f"{total_ufs}")
col4.metric("📊 Volume Médio por Rota", f"{media_volume_rota:.2f}")

st.markdown("---")

# Geocodificar para o mapa (com cache)
with st.spinner("🔍 Geocodificando cidades..."):
    df_geo = geocode_cidades(df_filtrado)

# Carregar GeoJSON dos estados
geojson_url = "https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/brazil-states.geojson"
try:
    response = requests.get(geojson_url, verify=False)
    response.raise_for_status()
    estados_geojson = response.json()
except requests.exceptions.RequestException as e:
    st.error(f"Erro ao carregar o GeoJSON: {e}")
    st.stop()

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

tab1, tab2, tab3, tab4 = st.tabs([
    "📍 Mapa por Cidade",
    "🗺️ Heatmap por UF",
    "🧭 Heatmap por Região",
    "📈 Análise Avançada"
])

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
                tooltip=f"{row['cidade_destinatario']} - {row['uf_destinatario']}: {row['total_volumes']} volumes",
                color='blue', fill=True, fill_opacity=0.6
            ).add_to(mapa)
        st_folium(mapa, width=900, height=600)

    st.markdown("---")
    st.subheader("📊 Total de volumes por UF e por Região")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Volumes por UF**")
        df_uf_bar = df_filtrado.groupby("uf_destinatario")["total_volumes"].sum().reset_index()
        fig_uf = px.bar(
            df_uf_bar,
            x="uf_destinatario",
            y="total_volumes",
            labels={"total_volumes": "Volumes", "uf_destinatario": "UF"},
            color="total_volumes",
            color_continuous_scale="Blues"
        )
        st.plotly_chart(fig_uf, use_container_width=True)

    with col2:
        st.markdown("**Volumes por Região**")
        df_regiao_bar = df_filtrado.groupby("regiao")["total_volumes"].sum().reset_index()
        fig_regiao = px.bar(
            df_regiao_bar,
            x="regiao",
            y="total_volumes",
            labels={"total_volumes": "Volumes", "regiao": "Região"},
            color="total_volumes",
            color_continuous_scale="Greens"
        )
        st.plotly_chart(fig_regiao, use_container_width=True)

with tab2:
    st.subheader(f"🗺️ Heatmap por estado (UF) - {regiao_selecionada}")
    df_estado = df_filtrado.groupby('uf_destinatario')['total_volumes'].sum().reset_index()
    ufs_todas = pd.DataFrame({"uf_destinatario": [f["properties"]["sigla"] for f in estados_geojson["features"]]})
    df_estado_completo = pd.merge(ufs_todas, df_estado, on="uf_destinatario", how="left").fillna(0)

    fig_estado = px.choropleth(
        df_estado_completo,
        geojson=estados_geojson,
        locations='uf_destinatario',
        featureidkey="properties.sigla",
        color='total_volumes',
        color_continuous_scale="YlOrRd",
        range_color=(0, df_estado_completo['total_volumes'].max()),
        labels={'total_volumes': 'Volumes'}
    )
    fig_estado.update_geos(fitbounds="geojson", visible=False)
    fig_estado.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig_estado, use_container_width=True)

with tab3:
    st.subheader(f"🧭 Heatmap por região - {regiao_selecionada}")
    regioes_todas = pd.DataFrame({"regiao": list(set(uf_para_regiao.values()))})
    df_regiao = df_filtrado.groupby('regiao')['total_volumes'].sum().reset_index()
    df_regiao_completo = pd.merge(regioes_todas, df_regiao, on="regiao", how="left").fillna(0)

    fig_regiao = px.choropleth(
        df_regiao_completo,
        geojson=regioes_geojson,
        locations='regiao',
        featureidkey="properties.sigla",
        color='total_volumes',
        color_continuous_scale="YlGnBu",
        range_color=(0, df_regiao_completo['total_volumes'].max()),
        labels={'total_volumes': 'Volumes'}
    )
    fig_regiao.update_geos(fitbounds="geojson", visible=False)
    fig_regiao.update_layout(margin={"r":0,"t":0,"l":0,"b":0})
    st.plotly_chart(fig_regiao, use_container_width=True)

with tab4:
    st.subheader("🏆 Top 10 Cidades com Maior Volume")
    top10_cidades = df_filtrado.groupby(['cidade_destinatario', 'uf_destinatario'])['total_volumes'].sum().reset_index()
    top10_cidades = top10_cidades.sort_values(by='total_volumes', ascending=False).head(10)
    fig_top10_cidades = px.bar(
        top10_cidades,
        x='cidade_destinatario',
        y='total_volumes',
        color='uf_destinatario',
        labels={'cidade_destinatario': 'Cidade', 'total_volumes': 'Volumes', 'uf_destinatario': 'UF'},
        title='Top 10 Cidades com Maior Volume'
    )
    st.plotly_chart(fig_top10_cidades, use_container_width=True)

    st.subheader("🏅 Top 10 UFs com Maior Volume")
    top10_ufs = df_filtrado.groupby('uf_destinatario')['total_volumes'].sum().reset_index()
    top10_ufs = top10_ufs.sort_values(by='total_volumes', ascending=False).head(10)
    fig_top10_ufs = px.bar(
        top10_ufs,
        x='uf_destinatario',
        y='total_volumes',
        labels={'uf_destinatario': 'UF', 'total_volumes': 'Volumes'},
        title='Top 10 UFs com Maior Volume',
        color='total_volumes',
        color_continuous_scale='Viridis'
    )
    st.plotly_chart(fig_top10_ufs, use_container_width=True)

    st.subheader("🚚 Top 5 Rotas (Cidade + UF) com Maior Volume")
    # As "rotas" vamos definir como combinação de cidade+UF
    top5_rotas = df_filtrado.groupby(['cidade_destinatario', 'uf_destinatario'])['total_volumes'].sum().reset_index()
    top5_rotas['rota'] = top5_rotas['cidade_destinatario'] + " - " + top5_rotas['uf_destinatario']
    top5_rotas = top5_rotas.sort_values(by='total_volumes', ascending=False).head(5)
    fig_top5_rotas = px.bar(
        top5_rotas,
        x='rota',
        y='total_volumes',
        labels={'rota': 'Rota', 'total_volumes': 'Volumes'},
        title='Top 5 Rotas com Maior Volume',
        color='total_volumes',
        color_continuous_scale='Inferno'
    )
    st.plotly_chart(fig_top5_rotas, use_container_width=True)


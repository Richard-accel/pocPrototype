from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import geopandas as gpd
import json
import os
from sqlalchemy import create_engine
from flask import Flask, Response, render_template
from keplergl import KeplerGl


app = FastAPI()

# Mount static and templates directories
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ✅ Apply config after data is loaded
config = {
    'version': 'v1',
    'config': {
        'visState': {
            'layers': [{
                'id': 'covid_layer',
                'type': 'geojson',
                'config': {
                    'dataId': 'Malaysia_COVID_Cases',
                    'label': 'COVID-19 Total Cases',
                    'color': [255, 203, 153],
                    'highlightColor': [252, 242, 26, 255],
                    'columns': {
                        'geojson': '_geojson'  
                    },
                    'isVisible': True,
                    'visConfig': {
                        'opacity': 0.7,
                        'strokeOpacity': 0.8,
                        'thickness': 0.5,
                        'colorRange': {
                            'name': 'ColorBrewer YlOrRd-6',
                            'type': 'sequential',
                            'category': 'ColorBrewer',
                            'colors': ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026']
                        },
                        'radius': 10,
                        'sizeRange': [0, 10],
                        'filled': True
                    }
                }
            }],
            'interactionConfig': {
                'tooltip': {
                    'fieldsToShow': {
                        'Malaysia_COVID_Cases': ['shapeName', 'total_cases']
                    },
                    'enabled': True
                }
            }
        },
        'mapState': {
            'latitude': 4.2105,
            'longitude': 101.9758,
            'zoom': 4,
        }
    }
}


# Load the CSV data
csv_data = pd.read_csv('https://raw.githubusercontent.com/MoH-Malaysia/covid19-public/refs/heads/main/epidemic/cases_state.csv')

# Sum total cases per state
state_totals = csv_data.groupby('state')['cases_new'].sum().reset_index()
state_totals.columns = ['state', 'total_cases']

# Load GeoJSON
geo_data = gpd.read_file('asserts/geoBoundaries-MYS-ADM1_simplified.geojson')

# Rename states to match
geo_data['shapeName'] = geo_data['shapeName'].replace({
    'Pulau Pinang': 'Penang',
    'Kuala Lumpur': 'W.P. Kuala Lumpur',
    'Labuan': 'W.P. Labuan',
    'Putrajaya': 'W.P. Putrajaya'
})

# Merge and clean
merged_data = geo_data.merge(state_totals, how='left', left_on='shapeName', right_on='state')
merged_data['total_cases'] = merged_data['total_cases'].fillna(0).astype(int)

# ✅ Clean geometry to avoid JSON serialization warnings
merged_data = merged_data[merged_data.is_valid]
merged_data = merged_data.dropna(subset=['geometry'])
merged_data.replace([float('inf'), float('-inf')], 0, inplace=True)

# ✅ Create map & add data BEFORE applying config
covid_map = KeplerGl(show_docs=False, height=450,read_only=True)
covid_map.add_data(data=merged_data, name="Malaysia_COVID_Cases")
covid_map.config=config

# === DB Config ===
DB_USER = "testing1_415q_user"
DB_PASSWORD = "syezjh72qciEKZUCBIcR4LF6YkiH7aXK"
DB_HOST = "dpg-cvr1u8ngi27c738j3acg-a.singapore-postgres.render.com"
DB_PORT = "5432"
DB_NAME = "testing1_415q"
engine = create_engine(f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
query = "SELECT name, amenity, latitude, longitude FROM health_facilities;"

cases_url = "https://raw.githubusercontent.com/MoH-Malaysia/covid19-public/main/epidemic/cases_malaysia.csv"
hospital_url = "https://raw.githubusercontent.com/MoH-Malaysia/covid19-public/main/epidemic/hospital.csv"
death_url = "https://raw.githubusercontent.com/MoH-Malaysia/covid19-public/main/epidemic/deaths_malaysia.csv"
state_cases_url = "https://raw.githubusercontent.com/MoH-Malaysia/covid19-public/main/epidemic/cases_state.csv"
# === Generate Charts ===
def generate_charts():
    df_cases = pd.read_csv(cases_url, parse_dates=['date'])
    df_hospital = pd.read_csv(hospital_url, parse_dates=['date'])
    df_deaths = pd.read_csv(death_url, parse_dates=['date'])
    df_state_cases = pd.read_csv(state_cases_url, parse_dates=['date'])

    today = df_cases['date'].max()
    new_cases = int(df_cases[df_cases['date'] == today]['cases_new'].fillna(0).values[0])
    deaths = int(df_deaths[df_deaths['date'] == today]['deaths_new'].fillna(0).values[0])
    hosp_today = df_hospital[df_hospital['date'] == today]
    hospitalized = int(hosp_today['admitted_covid'].fillna(0).values[0])
    discharged = int(hosp_today['discharged_covid'].fillna(0).values[0])

    df_cases['total_cases'] = df_cases['cases_new'].fillna(0).cumsum()
    line_fig = go.Figure()
    line_fig.add_trace(go.Scatter(x=df_cases['date'], y=df_cases['total_cases'], mode='lines', name='Total Cases'))
    line_fig.update_layout(title='Total COVID-19 Cases Over Time', xaxis_title='Date', yaxis_title='Cumulative Cases')

    df_hospital['year'] = df_hospital['date'].dt.year
    annual_data = df_hospital.groupby('year')[['admitted_covid', 'discharged_covid']].sum().reset_index()
    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(x=annual_data['year'], y=annual_data['admitted_covid'], name='Hospitalized', marker_color='orange'))
    bar_fig.add_trace(go.Bar(x=annual_data['year'], y=annual_data['discharged_covid'], name='Discharged', marker_color='green'))
    bar_fig.update_layout(title='Hospitalized vs Discharged per Year', xaxis_title='Year', yaxis_title='Patients', barmode='group')

    df_state_cases_today = df_state_cases[df_state_cases['date'] == today]
    state_fig = px.pie(df_state_cases_today, names='state', values='cases_new', title=f'COVID-19 New Cases by State on {today.strftime("%Y-%m-%d")}', hole=0.3)

    return {
        "today": today.strftime('%Y-%m-%d'),
        "new_cases": new_cases,
        "hospitalized": hospitalized,
        "discharged": discharged,
        "deaths": deaths,
        "line_chart": line_fig.to_html(full_html=False),
        "bar_chart": bar_fig.to_html(full_html=False),
        "state_chart": state_fig.to_html(full_html=False),
    }

@app.get("/")
def home(request: Request):
    data = generate_charts()
    return templates.TemplateResponse("index.html", {"request": request, **data})

@app.get("/empty_map", response_class=HTMLResponse)
def empty_map():
    empty_map = KeplerGl(show_docs=False, height=450,read_only=True)
    empty_map.config=config
    return HTMLResponse(content=empty_map._repr_html_(), status_code=200)

@app.get("/map/clinic", response_class=HTMLResponse)
def map_clinic():
    df = pd.read_sql(query, engine)
    clinic_df = df[df['amenity'].str.lower() == 'clinic']
    clinic_map = KeplerGl(height=450,read_only=True)
    clinic_map.add_data(data=clinic_df, name='Clinics Only')
    clinic_map.config = config
    return HTMLResponse(content=clinic_map._repr_html_(), status_code=200)

@app.get("/map/covid")
def covid_data():
    covid_map.config = config
    return HTMLResponse(content=covid_map._repr_html_(), status_code=200)
    

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

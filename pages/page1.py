import dash
from dash import html, dcc, Input, Output, callback
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable, GeocoderTimedOut
import requests_cache
from retry_requests import retry
import openmeteo_requests

# ---------- Initialize services ----------
placeFinder = Nominatim(user_agent="my_user_agent")
cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

# ---------- Register page ----------
dash.register_page(__name__, path="/weather", name="Weather Report")

# ---------- Animated Weather Icons ----------
def sun_icon():
    return html.Div(className="weather-icon-wrap", children=[
        html.Div(className="wx-icon sun", children=[
            html.Div(className="sun-core"),
            html.Div(className="sun-rays")
        ])
    ])

def cloud_icon():
    return html.Div(className="weather-icon-wrap", children=[
        html.Div(className="wx-icon cloud", children=[
            html.Div(className="cloud-bubble b1"),
            html.Div(className="cloud-bubble b2"),
            html.Div(className="cloud-bubble b3"),
        ])
    ])

def rain_icon():
    return html.Div(className="weather-icon-wrap", children=[
        html.Div(className="wx-icon rain", children=[
            html.Div(className="cloud-bubble b1"),
            html.Div(className="cloud-bubble b2"),
            html.Div(className="cloud-bubble b3"),
            html.Span(className="drop d1"),
            html.Span(className="drop d2"),
            html.Span(className="drop d3"),
        ])
    ])

# ---------- Layout ----------
layout = html.Div(className="weatherPage clear", children=[
    html.H1("Weather Report"),

    html.Div([
        html.Div([
            html.Label("City:"),
            dcc.Input(id="inputCity", type="text", value="Williamsburg", debounce=True)
        ]),
        html.Div([
            html.Label("Country:"),
            dcc.Input(id="inputCountry", type="text", value="USA", debounce=True)
        ])
    ], style={"display": "flex", "gap": "20px", "margin-bottom": "20px"}),

    html.Div([
        dcc.RadioItems(
            id="TempSetting",
            options=["Fahrenheit", "Celsius"],
            value="Fahrenheit",
            labelStyle={"display": "inline-block", "margin-right": "10px"}
        ),
        dcc.Checklist(
            id="paramSettings",
            options=["Temperature", "Rain", "Humidity"],
            value=["Temperature"],
            labelStyle={"display": "inline-block", "margin-right": "10px"}
        )
    ], style={"margin-bottom": "20px"}),

    dcc.Store(id="wx-data"),
    html.Div(id="weather-icon", style={"margin": "6px 0 12px"}),
    html.Div(id="GetWeather", className="wx-main-card"),
    dcc.Graph(id="place-map", figure={"data": [], "layout": {"title": "Location Map"}}),
    dcc.Graph(id="hourly-chart", figure={"data": [], "layout": {"title": "Hourly Temperature"}}),
    html.Div(id="summary-table", style={"maxWidth": "680px", "margin": "10px auto"}),
    html.Div(id="forecast-cards", style={"display": "flex", "overflowX": "auto", "padding": "10px"})
])

# ---------- Callbacks ----------
@callback(
    Output("wx-data", "data"),
    Input("inputCity", "value"),
    Input("inputCountry", "value"),
    Input("TempSetting", "value"),
)
def fetch_weather(city, country, tempUnit):
    try:
        # Geocode location
        location = placeFinder.geocode(f"{city}, {country}", timeout=10)
    except (GeocoderUnavailable, GeocoderTimedOut) as e:
        print(f"Geocoding failed: {e}")
        location = None

    if not location:
        return {"error": "Location not found."}

    lat, lon = float(location.latitude), float(location.longitude)
    resolved_place = location.address
    lat_str, lon_str = f"{lat:.3f}", f"{lon:.3f}"

    # Temperature unit
    temp_unit = "fahrenheit" if str(tempUnit).lower().startswith("f") else "celsius"
    unit_symbol = "°F" if temp_unit == "fahrenheit" else "°C"

    # API parameters
    api_params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "temperature_unit": temp_unit,
        "hourly": ["temperature_2m", "precipitation", "relative_humidity_2m"],
        "past_days": 3,
        "forecast_days": 4,
        "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"],
    }

    try:
        response = openmeteo.weather_api("https://api.open-meteo.com/v1/forecast", params=api_params)[0]

        # Hourly data
        hourly = response.Hourly()
        t_start = pd.to_datetime(hourly.Time(), unit="s", utc=True)
        t_end = pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True)
        step = pd.Timedelta(seconds=hourly.Interval())
        dt_idx = pd.date_range(start=t_start, end=t_end, freq=step, inclusive="left")

        local_tz = dt_idx.tz or pd.Timestamp.now().tz
        now_local = pd.Timestamp.now(tz=local_tz)
        diff_secs = ((dt_idx - now_local) / pd.Timedelta(seconds=1)).astype(float)
        idx_now = int(np.argmin(np.abs(diff_secs)))

        hourly_times_local = dt_idx.tz_convert(None).strftime("%Y-%m-%d %H:%M").tolist()
        hourly_temp = hourly.Variables(0).ValuesAsNumpy().tolist()
        hourly_precip = hourly.Variables(1).ValuesAsNumpy().tolist()
        hourly_humid = hourly.Variables(2).ValuesAsNumpy().tolist()

        # Daily data
        daily = response.Daily()
        d_start = pd.to_datetime(daily.Time(), unit="s", utc=True)
        d_end = pd.to_datetime(daily.TimeEnd(), unit="s", utc=True)
        d_step = pd.Timedelta(seconds=daily.Interval())
        d_idx = pd.date_range(start=d_start, end=d_end, freq=d_step, inclusive="left").tz_convert(local_tz)

        today = pd.Timestamp.now(tz=local_tz).normalize()
        offsets = ((d_idx.normalize() - today).days).tolist()

        daily_dates = d_idx.tz_convert(None).strftime("%Y-%m-%d").tolist()
        daily_tmax = daily.Variables(0).ValuesAsNumpy().tolist()
        daily_tmin = daily.Variables(1).ValuesAsNumpy().tolist()
        daily_rain = daily.Variables(2).ValuesAsNumpy().tolist()

        return {
            "meta": {
                "place": resolved_place,
                "lat": lat_str,
                "lon": lon_str,
                "unit_symbol": unit_symbol,
                "temp_unit": temp_unit,
            },
            "hourly": {
                "times": hourly_times_local,
                "temperature": hourly_temp,
                "precip": hourly_precip,
                "humidity": hourly_humid,
                "idx_now": idx_now,
            },
            "daily": {
                "dates": daily_dates,
                "tmax": daily_tmax,
                "tmin": daily_tmin,
                "precip_sum_mm": daily_rain,
                "offsets": offsets,
            }
        }

    except Exception as e:
        return {"error": f"Weather data fetch failed: {str(e)}"}

# ---------- Hourly Chart ----------
@callback(
    Output("hourly-chart", "figure"),
    Input("wx-data", "data"),
    prevent_initial_call=False
)
def render_hourly_chart(data):
    if not data or "error" in data:
        return {"data": [], "layout": {"title": "Hourly Temperature"}}

    H = data["hourly"]
    unit = data["meta"]["unit_symbol"]

    fig = {
        "data": [{
            "x": H["times"],
            "y": H["temperature"],
            "mode": "lines",
            "name": f"Temperature ({unit})",
            "hovertemplate": "%{x}<br>%{y:.1f} " + unit + "<extra></extra>",
        }],
        "layout": {
            "title": "Hourly Temperature (recent → near future)",
            "xaxis": {"title": "Local time"},
            "yaxis": {"title": unit},
            "margin": {"l": 40, "r": 10, "t": 50, "b": 40},
        },
    }
    return fig

# ---------- Location Map ----------
@callback(
    Output("place-map", "figure"),
    Input("wx-data", "data"),
    prevent_initial_call=False
)
def render_map(data):
    if not data or "error" in data:
        return {"data": [], "layout": {"title": "Location Map"}}

    meta = data["meta"]
    H = data["hourly"]
    idx = max(0, min(int(H["idx_now"]), len(H["times"]) - 1))

    temp = float(H["temperature"][idx])
    humid = float(H["humidity"][idx])
    precip = float(H["precip"][idx])
    unit = meta["unit_symbol"]
    rain_txt = f"{precip/25.4:.2f} in" if meta["temp_unit"] == "fahrenheit" else f"{precip:.2f} mm"

    hover = (
        f"<b>{meta['place']}</b><br>"
        f"Lat/Lon: {meta['lat']}, {meta['lon']}"

    )
    





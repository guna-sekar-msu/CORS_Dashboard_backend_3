import os
import numpy as np
import pandas as pd
import json
from django.conf import settings
import requests

# Constants for WGS84
a = 6378137.0         # Semi-major axis
f = 1 / 298.257223563 # Flattening
e2 = f * (2 - f)      # Square of eccentricity

def ecef_to_llh(x, y, z):
    lon = np.arctan2(y, x)
    p = np.sqrt(x**2 + y**2)
    lat = np.arctan2(z, p * (1 - e2))
    
    for _ in range(5):
        N = a / np.sqrt(1 - e2 * np.sin(lat)**2)
        lat = np.arctan2(z + e2 * N * np.sin(lat), p)
    
    N = a / np.sqrt(1 - e2 * np.sin(lat)**2)
    h = p / np.cos(lat) - N
    
    lat = np.degrees(lat)
    lon = np.degrees(lon)
    
    return lat, lon, h

def read_stacov(file):
    content = file.read().decode("utf-8").splitlines()
    header = content[0].strip()
    n = int(header.split()[0])
    nsta = n // 3
    cdate = header.split()[-1]

    station_names = []
    xyz = np.zeros((3, nsta))
    uncertainties = np.zeros((3, nsta))

    for i in range(n):
        line = content[i + 1].strip()
        parts = line.split()

        param_num = int(parts[0])
        station_name = parts[1]
        coordinate = parts[3]
        value = float(parts[4])
        uncertainty_value = float(parts[6])

        station_index = (param_num - 1) // 3
        coord_index = ['X', 'Y', 'Z'].index(coordinate[-1])

        if coord_index == 0:
            station_names.append(station_name)

        xyz[coord_index, station_index] = value
        uncertainties[coord_index, station_index] = uncertainty_value

    latitudes = []
    longitudes = []
    heights = []

    for i in range(nsta):
        lat, lon, h = ecef_to_llh(xyz[0, i], xyz[1, i], xyz[2, i])
        latitudes.append(lat)
        longitudes.append(lon)
        heights.append(h)
    
    df_xyz = pd.DataFrame({
        "Station Name": station_names,
        "Latitude": latitudes,
        "Longitude": longitudes,
        "Height": heights
    })

    return cdate, nsta, df_xyz

def generate_geojson(df_xyz):
    # Replace with your localhost URL
    # url = "http://127.0.0.1:8000/stations/MYCS2"

    # # Send GET request
    # response = requests.get(url)
    # # Check if the request was successful
    # if response.status_code == 200:
    #     data = response.json()  # Automatically parses JSON
    #     print(json.dumps(data, indent=4))  # Pretty print
    file_name = "CORS_All_Site_data.json"
    # Create the full file path
    file_path = os.path.join(settings.BASE_DIR, 'static', file_name)
    
    # Load CORS_All_Site_data.json for comparison
    with open(file_path, 'r') as cors_file:
        cors_data = json.load(cors_file)
    
    cors_site_ids = {feature['properties']['SITEID'] for feature in cors_data['features']}
    df_xyz_site_ids = set(df_xyz['Station Name'])
    
    data = []
    present_count = len(df_xyz_site_ids)

    # Mark all df_xyz sites as "Present"
    for index, row in df_xyz.iterrows():
        feature = {
            "type": "Feature",
            "properties": {
                "SITEID": row['Station Name'],
                "STATUS": "Present"
            },
            "geometry": {
                "type": "Point",
                "coordinates": [row['Longitude'], row['Latitude']]
            }
        }
        data.append(feature)

    # Mark remaining cors_site_ids not in df_xyz as "Not Present"
    missing_sites = cors_site_ids - df_xyz_site_ids
    
    for feature in cors_data['features']:
        if feature['properties']['SITEID'] in missing_sites:
            feature['properties']['STATUS'] = "Not Present"
            data.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "status_count": present_count,  # This counts only the sites marked as "Present"
        "features": data
    }
    
    return json.dumps(geojson, indent=4)

def generate_CSV_geojson(df):
    def dms_to_decimal(degrees, minutes, seconds):
        """
        Convert DMS (Degrees, Minutes, Seconds) to Decimal Degrees and round to 3 decimal places.
        """
        decimal_degrees = degrees + (minutes / 60) + (seconds / 3600)
        return round(decimal_degrees, 3)

    def convert_dms_string_to_decimal(dms_str, is_longitude=False):
        """
        Convert a DMS string (e.g., '50 47 52.1') into decimal degrees.
        If it's longitude, adjust the value if it's in the 0-360 system.
        """
        dms_parts = dms_str.split()
        degrees = int(dms_parts[0])
        minutes = int(dms_parts[1])
        seconds = float(dms_parts[2])
        
        decimal_degrees = dms_to_decimal(degrees, minutes, seconds)
        
        # If it's longitude and in the 0-360 range, convert to -180 to 180 range
        if is_longitude and decimal_degrees > 180:
            decimal_degrees -= 360
            
        return decimal_degrees

    def process_lat_lon(df):
        """
        Convert all Lat and Lon columns from DMS to Decimal Degrees in the given DataFrame.
        """
        # Convert the Lon and Lat columns to decimal degrees and round them to 3 decimal points
        df['Lon'] = df['Lon'].apply(lambda x: convert_dms_string_to_decimal(x, is_longitude=True))
        df['Lat'] = df['Lat'].apply(convert_dms_string_to_decimal)
        return df

    # Process the DataFrame
    df = process_lat_lon(df)
    data = []
    for index, row in df.iterrows():
        feature = {
            "type": "Feature",
            "properties": {
                "SITEID": row['Code'],
                "STATUS": "Present",
                "Description": row['Description'],
                "DOMES": row['DOMES']
            },
            "geometry": {
                "type": "Point",
                "coordinates": [row['Lon'], row['Lat']]
            }
        }
        data.append(feature)
        present_count = len(df['Code'])
        
    geojson = {
        "type": "FeatureCollection",
        "status_count": present_count,  # This counts only the sites marked as "Present"
        "features": data
    }
    return json.dumps(geojson, indent=4)

def generate_MYCS2_geojson(df,input_date,df_1):
    def filter_data_by_date(df,input_date,df_1):
        def dms_to_decimal(degrees, minutes, seconds):
            """
            Convert DMS (Degrees, Minutes, Seconds) to Decimal Degrees and round to 3 decimal places.
            """
            decimal_degrees = degrees + (minutes / 60) + (seconds / 3600)
            return round(decimal_degrees, 3)

        def convert_dms_string_to_decimal(dms_str, is_longitude=False):
            """
            Convert a DMS string (e.g., '50 47 52.1') into decimal degrees.
            If it's longitude, adjust the value if it's in the 0-360 system.
            """
            dms_parts = dms_str.split()
            degrees = int(dms_parts[0])
            minutes = int(dms_parts[1])
            seconds = float(dms_parts[2])
            
            decimal_degrees = dms_to_decimal(degrees, minutes, seconds)
            
            # If it's longitude and in the 0-360 range, convert to -180 to 180 range
            if is_longitude and decimal_degrees > 180:
                decimal_degrees -= 360
                
            return decimal_degrees

        def process_lat_lon(df):
            """
            Convert all Lat and Lon columns from DMS to Decimal Degrees in the given DataFrame.
            """
            # Convert the Lon and Lat columns to decimal degrees and round them to 3 decimal points
            df['Lon'] = df['Lon'].apply(lambda x: convert_dms_string_to_decimal(x, is_longitude=True))
            df['Lat'] = df['Lat'].apply(convert_dms_string_to_decimal)
            return df

        # Process the DataFrame
        df_1 = process_lat_lon(df_1)
        
        # Convert the 'Date' column to datetime format, allowing pandas to infer the format
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')  # Coerce will turn invalid formats into NaT
        
        # Convert the input date to a datetime object, ensuring it's only the date part
        input_date = pd.to_datetime(input_date).date()
        # Filter the dataframe for the rows where the date matches the input (ignoring the time)
        filtered_df = df[df['Date'].dt.date == input_date]
        
        if filtered_df.empty:
            print(f"No data found for the given date: {input_date.strftime('%Y-%m-%d')}")
        else:
            data = []
            for index, row in filtered_df.iterrows():
                feature = {
                    "type": "Feature",
                    "properties": {
                        "SITEID": row['Station'],
                        "STATUS": "MYCS2 Prediction"
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row['Longitude'],row['Latitude']]
                    }
                }
                data.append(feature)
            present_count = len(filtered_df['Station'])
            for index, row in df_1.iterrows():
                feature = {
                    "type": "Feature",
                    "properties": {
                        "SITEID": row['Code'],
                        "STATUS": "Observation",
                        "Description": row['Description'],
                        "DOMES": row['DOMES']
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [row['Lon'], row['Lat']]
                    }
                }
                data.append(feature)
            geojson = {
                "type": "FeatureCollection",
                "status_count": present_count,  # This counts only the sites marked as "Present"
                "mycs2_prediction": True,
                "features": data
            }

            return json.dumps(geojson, indent=4)

    filtered_data = filter_data_by_date(df,input_date,df_1)
    return filtered_data

def generate_OPUSNET_geojson(df,input_date,):
    # Convert the 'Date' column to datetime format, allowing pandas to infer the format
    df['Date'] = pd.to_datetime(df['measurement_date'], dayfirst=True, errors='coerce')  # Coerce will turn invalid formats into NaT
    # Convert the input date to a datetime object, ensuring it's only the date part
    input_date = pd.to_datetime(input_date).date()
    # Filter the dataframe for the rows where the date matches the input (ignoring the time)
    filtered_df = df[df['Date'].dt.date == input_date]
    if filtered_df.empty:
            print(f"No data found for the given date: {input_date.strftime('%Y-%m-%d')}")
    else:
        data = []
        for index, row in filtered_df.iterrows():
            feature = {
                "type": "Feature",
                "properties": {
                    "SITEID": row['site_id'],
                    "STATUS": "Uncertainty"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row['longitude'],row['latitude']],
                    "Uncertainty": [row['lon_uncertain'],row['lat_uncertain']]
                }
            }
            data.append(feature)
        present_count = len(filtered_df['site_id'])
        geojson = {
            "type": "FeatureCollection",
            "status_count": present_count,  # This counts only the sites marked as "Present"
            "uncertainty": True,
            "mycs2_prediction": True,
            "features": data
        }

        return json.dumps(geojson, indent=4)

    return filtered_df

def generate_MYCS_uncertainty_geojson(df,input_date,):
    # Convert the 'Date' column to datetime format, allowing pandas to infer the format
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce', format='%Y-%m-%d')  # Coerce will turn invalid formats into NaT
    # Convert the input date to a datetime object, ensuring it's only the date part
    input_date = pd.to_datetime(input_date).date()
    # Filter the dataframe for the rows where the date matches the input (ignoring the time)
    filtered_df = df[df['Date'].dt.date == input_date]
    if filtered_df.empty:
            print(f"No data found for the given date: {input_date.strftime('%Y-%m-%d')}")
    else:
        data = []
        for index, row in filtered_df.iterrows():
            feature = {
                "type": "Feature",
                "properties": {
                    "SITEID": row['Code'],
                    "STATUS": "Uncertainty"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row['Longitude'],row['Latitude']],
                    "Uncertainty": [row['Lon_Uncertainty'],row['Lat_Uncertainty']]
                }
            }
            data.append(feature)
        present_count = len(filtered_df['Code'])
        geojson = {
            "type": "FeatureCollection",
            "status_count": present_count,  # This counts only the sites marked as "Present"
            "uncertainty": True,
            "mycs2_prediction": True,
            "features": data
        }
        return json.dumps(geojson, indent=4)
    return filtered_df
    
def generate_MYCS_uncertainty_geojson(df,input_date,):
    # Convert the 'Date' column to datetime format, allowing pandas to infer the format
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce', format='%Y-%m-%d')  # Coerce will turn invalid formats into NaT
    # Convert the input date to a datetime object, ensuring it's only the date part
    input_date = pd.to_datetime(input_date).date()
    # Filter the dataframe for the rows where the date matches the input (ignoring the time)
    filtered_df = df[df['Date'].dt.date == input_date]
    if filtered_df.empty:
            print(f"No data found for the given date: {input_date.strftime('%Y-%m-%d')}")
    else:
        data = []
        for index, row in filtered_df.iterrows():
            feature = {
                "type": "Feature",
                "properties": {
                    "SITEID": row['Code'],
                    "STATUS": "Uncertainty"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row['Longitude'],row['Latitude']],
                    "Uncertainty": [row['Lon_Uncertainty'],row['Lat_Uncertainty']]
                }
            }
            data.append(feature)
        present_count = len(filtered_df['Code'])
        geojson = {
            "type": "FeatureCollection",
            "status_count": present_count,  # This counts only the sites marked as "Present"
            "uncertainty": True,
            "mycs2_prediction": True,
            "features": data
        }
        return json.dumps(geojson, indent=4)
    return filtered_df
def generate_station_list(X):
    # data=X.json()
    # stations = json.loads(X)
    stations=X
    
    geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    for station in stations:
        coords = station.get("approximate_coordinates", [None, None, None])
        if len(coords) >= 3:
            x, y, z = coords[:3]
            lat, lon, _ = ecef_to_llh(x, y, z)  # Convert ECEF to lat/lon/height

            feature = {
                "type": "Feature",
                "properties": {
                    "station_uuid": station["station_uuid"],
                    "station_id": station["station_id"],
                    "network": station["network"],
                    "domes": station["domes"],
                    "description": station["description"],
                    "model_id": station["model_id"],
                    "STATUS": "Present",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]  # GeoJSON expects [lon, lat]
                }
            }
            geojson["features"].append(feature)
    # print(geojson)
    # return json.dumps(geojson, indent=2)
    return geojson
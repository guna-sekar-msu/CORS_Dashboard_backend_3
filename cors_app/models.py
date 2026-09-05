import os
import math
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


def _extract_ecef_tuple(payload, prefix=''):
    if prefix:
        keys = (f'{prefix}x', f'{prefix}y', f'{prefix}z')
    else:
        keys = ('x', 'y', 'z')

    values = [payload.get(k) for k in keys]
    if all(value is not None for value in values):
        try:
            return tuple(float(value) for value in values)
        except (TypeError, ValueError):
            return None
    return None


def _is_ecef_list(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(isinstance(item, (int, float, str)) for item in value)
    )


def convert_ecef_data(payload):
    if isinstance(payload, dict):
        output = dict(payload)

        # Handle named ECEF fields.
        point = _extract_ecef_tuple(payload)

        if point is not None:
            lat, lon, h = ecef_to_llh(*point)
            output['lat'] = lat
            output['lon'] = lon
            output['height'] = h

        # Handle approximate coordinate array fields.
        approx = payload.get('approximate_coordinates')
        if _is_ecef_list(approx):
            try:
                approx_point = tuple(float(v) for v in approx)
                lat, lon, h = ecef_to_llh(*approx_point)
                output['approximate_lat'] = lat
                output['approximate_lon'] = lon
                output['approximate_height'] = h
            except (TypeError, ValueError):
                pass

        return {k: convert_ecef_data(v) for k, v in output.items()}

    if isinstance(payload, list):
        return [convert_ecef_data(item) for item in payload]

    return payload


def _normalize_xyz_value(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _calculate_3d_difference(x_value, y_value, z_value):
    if x_value is None or y_value is None or z_value is None:
        return None

    try:
        dx = float(x_value)
        dy = float(y_value)
        dz = float(z_value)
    except (TypeError, ValueError):
        return None

    magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)
    return {
        'meters': magnitude,
        'millimeters': magnitude * 1000,
        'centimeters': magnitude * 100,
    }


def _normalize_xyz_object(value, include_location=True):
    if isinstance(value, dict):
        normalized = {}
        for key in ('x', 'y', 'z'):
            if key in value:
                normalized[key] = _normalize_xyz_value(value.get(key))
        for key, item in value.items():
            if key not in {'x', 'y', 'z'}:
                normalized[key] = item

        if include_location:
            xyz_values = [normalized.get('x'), normalized.get('y'), normalized.get('z')]
            if all(v is not None for v in xyz_values):
                try:
                    lat, lon, _ = ecef_to_llh(float(xyz_values[0]), float(xyz_values[1]), float(xyz_values[2]))
                    normalized['latitude'] = lat
                    normalized['longitude'] = lon
                    normalized['location_details'] = {
                        'latitude': lat,
                        'longitude': lon,
                    }
                except (TypeError, ValueError):
                    pass

        return normalized

    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            normalized = {
                'x': _normalize_xyz_value(value[0]),
                'y': _normalize_xyz_value(value[1]),
                'z': _normalize_xyz_value(value[2]),
            }
            if include_location:
                xyz_values = [normalized.get('x'), normalized.get('y'), normalized.get('z')]
                if all(v is not None for v in xyz_values):
                    lat, lon, _ = ecef_to_llh(float(xyz_values[0]), float(xyz_values[1]), float(xyz_values[2]))
                    normalized['latitude'] = lat
                    normalized['longitude'] = lon
                    normalized['location_details'] = {
                        'latitude': lat,
                        'longitude': lon,
                    }
            return normalized
        except Exception:
            return value

    return value


def preprocess_comparison_payload(payload):
    if not isinstance(payload, dict):
        return payload

    processed = dict(payload)

    if 'measurement' in processed:
        processed['measurement'] = _normalize_xyz_object(processed['measurement'], include_location=True)
    if 'prediction' in processed:
        processed['prediction'] = _normalize_xyz_object(processed['prediction'], include_location=True)
    if 'difference' in processed:
        processed['difference'] = _normalize_xyz_object(processed['difference'], include_location=False)

    if 'difference' in processed and isinstance(processed['difference'], dict):
        diff = processed['difference']
        magnitude = _calculate_3d_difference(diff.get('x'), diff.get('y'), diff.get('z'))
        if magnitude is not None:
            diff['difference_3d'] = magnitude['meters']
            diff['difference_3d_mm'] = magnitude['millimeters']
            diff['difference_3d_cm'] = magnitude['centimeters']

    if 'error_threshold_exceeded' in processed:
        value = processed['error_threshold_exceeded']
        if isinstance(value, str):
            normalized = value.strip().lower()
            processed['error_threshold_exceeded'] = 'Yes' if normalized in {'yes', 'y', 'true', '1'} else 'No'
        elif isinstance(value, bool):
            processed['error_threshold_exceeded'] = 'Yes' if value else 'No'

    return processed

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
    
    cors_features_by_siteid = {
        feature['properties']['SITEID']: feature
        for feature in cors_data['features']
        if 'properties' in feature and 'SITEID' in feature['properties']
    }
    df_xyz_site_ids = set(df_xyz['Station Name'])
    
    data = []
    present_count = len(df_xyz_site_ids)

    # Mark all df_xyz sites as "Present" and preserve existing properties when available
    for index, row in df_xyz.iterrows():
        site_id = row['Station Name']
        base_feature = cors_features_by_siteid.get(site_id, {})
        properties = dict(base_feature.get('properties', {}))
        properties['SITEID'] = site_id
        properties['STATUS'] = 'Present'

        feature = {
            'type': 'Feature',
            'properties': properties,
            'geometry': {
                'type': 'Point',
                'coordinates': [row['Longitude'], row['Latitude']]
            }
        }
        data.append(feature)

    # Mark remaining cors_data features not in df_xyz as "Not Present"
    missing_sites = set(cors_features_by_siteid) - df_xyz_site_ids
    
    for site_id in missing_sites:
        feature = dict(cors_features_by_siteid[site_id])
        feature['properties'] = dict(feature.get('properties', {}))
        feature['properties']['STATUS'] = 'Not Present'
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
def _extract_station_id(item):
    if isinstance(item, dict):
        for key, value in item.items():
            key_name = str(key).lower()
            if key_name in {'siteid', 'site_id', 'station', 'station_id', 'id', 'site', 'code', 'name'}:
                return str(value)
        for value in item.values():
            extracted = _extract_station_id(value)
            if extracted is not None:
                return extracted
    elif isinstance(item, (list, tuple)):
        for value in item:
            extracted = _extract_station_id(value)
            if extracted is not None:
                return extracted
    return None


def annotate_station_filter(filtered_stations, base_stations=None):
    """Backward-compatible no-op for station preprocessing.

    Comparison and filter=yes/no flags were removed from the backend response.
    We still keep this helper so older callers do not break, but it now simply
    returns the processed GeoJSON for the filtered station list without adding any
    compare metadata.
    """
    stations = filtered_stations or []
    return generate_station_list(stations)


def generate_station_list(X):
    stations = X
    #print(stations)
    geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    for station in stations:
        coords = station.get("approximate_coordinates")
        if not coords:
            coords = station.get("current_coordinates")

        geometry = {
            "type": "Point",
            "coordinates": [None, None]
        }
        if isinstance(coords, (list, tuple)) and len(coords) >= 3:
            try:
                x, y, z = coords[:3]
                lat, lon, _ = ecef_to_llh(x, y, z)
                geometry["coordinates"] = [lon, lat]
            except (TypeError, ValueError):
                pass

        current_xyz = None
        current_latitude = None
        current_longitude = None
        if isinstance(station.get("current_x"), (int, float)) and isinstance(station.get("current_y"), (int, float)) and isinstance(station.get("current_z"), (int, float)):
            current_xyz = [station.get("current_x"), station.get("current_y"), station.get("current_z")]

        if isinstance(current_xyz, (list, tuple)) and len(current_xyz) >= 3:
            try:
                lat, lon, _ = ecef_to_llh(*current_xyz)
                geometry = {
                    "type": "Point",
                    "coordinates": [lon, lat]
                }
                current_latitude = lat
                current_longitude = lon
            except (TypeError, ValueError):
                pass

        properties = dict(station)
        properties["STATUS"] = "Present"
        if current_latitude is not None and current_longitude is not None:
            properties["current_latitude"] = current_latitude
            properties["current_longitude"] = current_longitude

        for source_key, target_key in (("wrms_x", "wrms_x_mm"), ("wrms_y", "wrms_y_mm"), ("wrms_z", "wrms_z_mm")):
            if source_key in station:
                properties.pop(source_key, None)
                raw_value = station[source_key]
                if isinstance(raw_value, (int, float)):
                    properties[target_key] = round(float(raw_value) * 1000.0, 2)

        feature = {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry
        }
        geojson["features"].append(feature)

    return geojson
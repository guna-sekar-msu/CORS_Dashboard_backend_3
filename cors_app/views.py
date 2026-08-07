from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import read_stacov, generate_geojson, generate_CSV_geojson,generate_MYCS2_geojson,generate_OPUSNET_geojson,generate_MYCS_uncertainty_geojson,generate_MYCS_uncertainty_geojson,generate_station_list, annotate_station_filter
import os
import json
from datetime import datetime
import pandas as pd
import boto3
from decouple import config
import requests
from django.http import JsonResponse
from .fastapi_service import FastAPIProxyService

# Set up the S3 connection
s3 = boto3.resource(
    service_name='s3',
    region_name=config('AWS_DEFAULT_REGION'),
    aws_access_key_id=config('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=config('AWS_SECRET_ACCESS_KEY')
)

def home(request):
    return JsonResponse({
        "status": "success",
        "message": "CORS application is running",
        "api_endpoint": "/api/json/"
    })

class StacovJsonView(APIView):
    def post(self, request):
        try:
            # Extract the date input from the frontend
            #print("Request Data:", request.data)  # Debugging line to print the incoming request data

            # If frontend sent query params for FastAPI, forward them first
            if request.data and request.data.get('input_data'):
                params = request.data.get('input_data') or {}
                # Allow caller to override endpoint (default to /stations)
                endpoint = request.data.get('endpoint', '/stations')
                #print(f"Forwarding request to FastAPI endpoint: {endpoint} with params: {params}")
                try:
                    response_data = FastAPIProxyService.proxy_request(
                        endpoint=endpoint,
                        method='GET',
                        params=params,
                        headers={
                            k: v
                            for k, v in request.headers.items()
                            if k.lower() not in {
                                'host', 'content-length', 'accept-encoding', 'connection', 'transfer-encoding'
                            }
                        },
                        timeout=30
                    )

                    if 'error' in response_data and response_data.get('status_code', 0) >= 400:
                        return Response(response_data, status=response_data.get('status_code', status.HTTP_502_BAD_GATEWAY))

                    # If FastAPI returned a non-200 status (validation error, not found, etc.),
                    # forward that response to the frontend instead of attempting to process it.
                    status_code = response_data.get('status_code', 200)
                    if status_code != 200:
                        body = response_data.get('body')
                        response_headers = response_data.get('headers', {}) or {}
                        content_type = response_data.get('content_type')

                        # Include status_code in the returned JSON so frontend can inspect it
                        if isinstance(body, dict):
                            forwarded_body = dict(body)
                            forwarded_body['status_code'] = status_code
                        else:
                            forwarded_body = {
                                'status_code': status_code,
                                'detail': body
                            }

                        if content_type:
                            return Response(forwarded_body, status=status_code, headers=response_headers, content_type=content_type)
                        return Response(forwarded_body, status=status_code, headers=response_headers)

                    body = response_data.get('body')

                    # FastAPI may wrap station list; try common keys
                    if isinstance(body, dict) and 'stations' in body:
                        print("Stations found in response body under 'stations' key.")
                        stations = body['stations']
                    elif isinstance(body, dict) and 'data' in body:
                        print("Stations found in response body under 'data' key.")
                        stations = body['data']
                    else:
                        print("Stations found in response body directly.")
                        stations = body

                    # Fetch base station list from the base /stations/ endpoint to compare
                    try:
                        base_response = FastAPIProxyService.proxy_request(endpoint='/stations', method='GET')
                        base_body = base_response.get('body') if isinstance(base_response, dict) else None
                        if isinstance(base_body, dict) and 'stations' in base_body:
                            base_stations = base_body['stations']
                        elif isinstance(base_body, dict) and 'data' in base_body:
                            base_stations = base_body['data']
                        else:
                            base_stations = base_body or []
                    except Exception:
                        base_stations = []

                    station_list = annotate_station_filter(stations, base_stations)
                    return Response(station_list, status=response_data.get('status_code', status.HTTP_200_OK))
                except Exception as e:
                    return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            elif request.data is None or not request.data.get('input_data'):
                 url = "http://127.0.0.1:8000/stations/"
                 response_data = requests.get(url)
                 try:
                     response_data.raise_for_status()
                     data = response_data.json()
                     station_list = generate_station_list(data)
                     return Response(station_list, status=status.HTTP_200_OK)
                 except requests.exceptions.RequestException as e:
                     return Response({"error": f"Failed to fetch data: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


#============================================================================================================================================
            # input_date_str = request.data.get('input', '')
            # if not input_date_str:
            #     return Response({"error": "No date input provided"}, status=status.HTTP_400_BAD_REQUEST)
            # if input_date_str['options'] == 'Static JSON + STACOV File' or input_date_str['options'] == 'Initial Load':

            #     # Convert the input date string to a datetime object
            #     input_date = datetime.strptime(input_date_str['date'], '%Y-%m-%dT%H:%M:%S.%fZ')

            #     # Format the date part for the filename
            #     day = input_date.strftime('%d')
            #     month = input_date.strftime('%b').lower()
            #     year = input_date.strftime('%y')

            #     # Construct the correct date part (e.g., '24apr16')
            #     date_part = f"{year}{month}{day}"
                
            #     # Construct the full file name
            #     file_name = f"{date_part}NOAM4.0_ambres_nfx20.stacov"
                
                
            #     # Create the full file path
            #     file_path = os.path.join(settings.BASE_DIR, 'static', file_name)
                
            #     if not os.path.exists(file_path):
                    
            #         return Response({"error": "Data not found"}, status=status.HTTP_400_BAD_REQUEST)
                    
                
            #     # Open and process the STACOV file
            #     with open(file_path, 'rb') as file:
            #         cdate, nsta, df_xyz = read_stacov(file)
            #         geojson_str = generate_geojson(df_xyz)
            #         geojson_data = json.loads(geojson_str)

            #     # Return the processed GeoJSON data
            #     return Response(geojson_data, status=status.HTTP_200_OK)
            # elif input_date_str['options'] ==  'Over All Site Info':
            #     file_name = 'site_id.csv'
            #     file_path = os.path.join(settings.BASE_DIR, 'static', file_name)
            #     with open(file_path, 'rb') as file:
            #         df = pd.read_csv(file)
            #         geojson_csv_str = generate_CSV_geojson(df)
            #         geojson_csv_data = json.loads(geojson_csv_str)
            #     return Response(geojson_csv_data,status=status.HTTP_200_OK)
            # elif input_date_str['options'] == 'Over All Vs MYCS2':
            #     file_name_1 = 'site_id.csv'
            #     file_path_1 = os.path.join(settings.BASE_DIR, 'static', file_name_1)
            #     with open(file_path_1, 'rb') as file:
            #         df_1 = pd.read_csv(file)
            #     input_date = datetime.strptime(input_date_str['date'], '%Y-%m-%dT%H:%M:%S.%fZ')
            #     file_name = 'mycs2_predictions.csv'
            #     # Fetch the MYCS2 predictions CSV from S3
            #     obj = s3.Bucket('cors-dashboard-dataset').Object(file_name).get()
            #     df = pd.read_csv(obj['Body'])
            #     geojson_MYCS2_str = generate_MYCS2_geojson(df,input_date,df_1)
            #     geojson_MYCS2_data = json.loads(geojson_MYCS2_str)
            #     return Response(geojson_MYCS2_data,status=status.HTTP_200_OK)
            # elif input_date_str['options'] == 'OPUSNET Data':
            #     # Convert the input date string to a datetime object
            #     input_date = datetime.strptime(input_date_str['date'], '%Y-%m-%dT%H:%M:%S.%fZ')
            #     file_name = 'opusnet_converted_corrected.csv'
            #     # file_path = os.path.join(settings.BASE_DIR, 'static', file_name)
            #     # with open(file_path, 'rb') as file:
            #     #     df = pd.read_csv(file)
            #     # df = fetch_all_opusnet_data()
            #     # Fetch the MYCS2 predictions CSV from S3
            #     obj = s3.Bucket('cors-dashboard-dataset').Object(file_name).get()
            #     df = pd.read_csv(obj['Body'])
            #     geojson_OPUSNET_str = generate_OPUSNET_geojson(df,input_date)
            #     geojson_OPUSNET_data = json.loads(geojson_OPUSNET_str)
            #     return Response(geojson_OPUSNET_data,status=status.HTTP_200_OK)
            # elif input_date_str['options'] ==  'MYCS Uncertainty':
            #     # Convert the input date string to a datetime object
            #     input_date = datetime.strptime(input_date_str['date'], '%Y-%m-%dT%H:%M:%S.%fZ')
            #     file_name = 'mycs2_uncertainty.csv'
            #     # file_path = os.path.join(settings.BASE_DIR, 'static', file_name)
            #     # with open(file_path, 'rb') as file:
            #     #     df = pd.read_csv(file)
            #     obj = s3.Bucket('cors-dashboard-dataset').Object(file_name).get()
            #     df = pd.read_csv(obj['Body'])
            #     geojson_MYCS_str = generate_MYCS_uncertainty_geojson(df,input_date)
            #     geojson_MYCS2_uncertainty_data = json.loads(geojson_MYCS_str)
            #     return Response(geojson_MYCS2_uncertainty_data,status=status.HTTP_200_OK)
            # elif input_date_str['options'] in ['MYCS2','IGS20_SIF','opusnet', 'NCN20_SIF','NCN14_SIF']:

            #     print("Success")
            #     if(input_date_str['options']=='MYCS2'):
            #         print("MYCS2")
            #         url = "http://127.0.0.1:8000/stations/MYCS2"
            #     elif(input_date_str['options']=='IGS20_SIF'):
            #         print("IGS")
            #         url = "http://127.0.0.1:8000/stations/IGS20_SIF"
            #     elif(input_date_str['options']=='opusnet'):
            #         print("OPUSNET")
            #         url = "http://127.0.0.1:8000/stations/opusnet"
            #     elif(input_date_str['options']=='NCN20_SIF'):
            #         print("NCN20")
            #         url = "http://127.0.0.1:8000/stations/NCN20_SIF"
            #     elif(input_date_str['options']=='NCN14_SIF'):
            #         print("NCN14")
            #         url = "http://127.0.0.1:8000/stations/NCN14_SIF"


            #     # Send GET request
            #     response = requests.get(url)

            #     # Check if the request was successful
            #     if response.status_code == 200:
            #         data = response.json()  # Automatically parses JSON
            #         # print(data)
            #         station_list = generate_station_list(data)  # Pass structured data
            #         # print(json.dumps(data, indent=4))  # Pretty print

            #         return Response(station_list, status=status.HTTP_200_OK)

            # #     except requests.exceptions.RequestException as e:
            #         # return Response({"error": f"Failed to fetch data: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
#============================================================================================================================================
        
        except ValueError:
            return Response({"error": "Invalid date format"}, status=status.HTTP_400_BAD_REQUEST)
        
        except Exception as e:
            # Handle any errors that occur during processing
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

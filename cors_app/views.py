from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from .models import read_stacov, generate_geojson, generate_CSV_geojson,generate_MYCS2_geojson,generate_OPUSNET_geojson,generate_MYCS_uncertainty_geojson,generate_MYCS_uncertainty_geojson,generate_station_list, preprocess_comparison_payload
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
            payload = request.data if isinstance(request.data, dict) else {}
            params = payload.get('input_data') or {}
            endpoint = payload.get('endpoint', '/stations')

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

                if response_data.get('status_code', 400) >= 400:
                    print(f"FastAPI returned error: {response_data}")
                    return Response(response_data, status=response_data.get('status_code', status.HTTP_502_BAD_GATEWAY))

                status_code = response_data.get('status_code', 200)
                if status_code != 200:
                    body = response_data.get('body')
                    response_headers = response_data.get('headers', {}) or {}
                    content_type = response_data.get('content_type')

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

                if isinstance(body, dict) and 'stations' in body:
                    stations = body['stations']
                elif isinstance(body, dict) and 'data' in body:
                    stations = body['data']
                else:
                    stations = body if isinstance(body, list) else []

                if isinstance(stations, list):
                    station_list = generate_station_list(stations)
                else:
                    station_list = stations or {"type": "FeatureCollection", "features": []}

                return Response(station_list, status=status_code)
            except Exception as e:
                return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ComparisonProxyView(APIView):
    """Proxy frontend comparison input to FastAPI and normalize xyz fields."""
    authentication_classes = []
    permission_classes = []
    http_method_names = ['get', 'post', 'options', 'head']

    def _get_params(self, request):
        if request.method.upper() == 'GET':
            params = request.query_params.dict()
            print(f"GET request params: {params}")
        else:
            params = {}
            payload = request.data if hasattr(request, 'data') else {}
            print(f"Received payload: {payload}")
            if isinstance(payload, dict):
                if 'input_data' in payload and isinstance(payload['input_data'], dict):
                    params = dict(payload['input_data'])
                elif 'input' in payload and isinstance(payload['input'], dict):
                    params = dict(payload['input'])
                else:
                    params = {k: v for k, v in payload.items() if v is not None}
            elif isinstance(payload, str):
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        params = {k: v for k, v in parsed.items() if v is not None}
                except (TypeError, ValueError):
                    params = {}

        return {k: v for k, v in params.items() if v is not None}

    def _handle_request(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        endpoint = payload.get('endpoint', '/comparison')
        params = self._get_params(request)
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
            timeout=30,
        )

        status_code = response_data.get('status_code', 200)
        if status_code >= 400:
            return Response(response_data, status=status_code)

        body = response_data.get('body')
        if isinstance(body, dict):
            body = preprocess_comparison_payload(body)
        elif isinstance(body, list):
            body = [preprocess_comparison_payload(item) if isinstance(item, dict) else item for item in body]

        return Response(body, status=status_code)

    def get(self, request):
        return self._handle_request(request)

    def post(self, request):
        return self._handle_request(request)


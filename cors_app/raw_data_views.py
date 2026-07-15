"""
Proxy Views - Django acts as POSTMAN
Simple pass-through proxy that forwards requests to FastAPI
"""

import json

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from .fastapi_service import FastAPIProxyService
from .models import convert_ecef_data

class RawDataView(APIView):
    """
    Django acts as POSTMAN proxy - forwards all requests to FastAPI
    No preprocessing, no file handling, just pure pass-through
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def _parse_payload(self, request):
        if request.data:
            payload = request.data
            if isinstance(payload, str):
                try:
                    return json.loads(payload)
                except ValueError:
                    pass

            if isinstance(payload, dict):
                if 'payload' in payload:
                    inner = payload['payload']
                    if isinstance(inner, str):
                        try:
                            return json.loads(inner)
                        except ValueError:
                            pass
                    return inner
                return payload

            try:
                return dict(payload)
            except Exception:
                return {}

        if request.body:
            raw_body = request.body.decode('utf-8', errors='ignore').strip()
            if raw_body:
                try:
                    return json.loads(raw_body)
                except ValueError:
                    from urllib.parse import parse_qs
                    parsed = parse_qs(raw_body)
                    if 'payload' in parsed:
                        candidate = parsed['payload'][-1]
                        try:
                            return json.loads(candidate)
                        except ValueError:
                            pass
                    return {k: v[-1] if len(v) == 1 else v for k, v in parsed.items()}

        return {}

    def post(self, request):
        """
        Receive request from frontend and proxy to FastAPI
        
        Expected request body example:
        {
            "method": "POST",
            "endpoint": "/stations/MYCS2",
            "headers": {
                "Authorization": "Bearer <token>",
                "Content-Type": "application/json"
            },
            "params": {
                "limit": 10
            },
            "json": {
                "input": { ... }
            }
        }
        """
        try:
            payload = self._parse_payload(request) or {}
            method = payload.get('method', 'POST').upper()
            endpoint = payload.get('endpoint')
            url = payload.get('url')
            headers = payload.get('headers', {})
            params = payload.get('params')
            json_body = payload.get('json')
            data = payload.get('data')
            timeout = payload.get('timeout', 30)

            if not endpoint and not url:
                return Response(
                    {
                        "error": "Missing endpoint or url in request body",
                        "parsed_payload": payload,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            forwarded_headers = {
                k: v
                for k, v in request.headers.items()
                if k.lower() not in {
                    'host', 'content-length', 'accept-encoding', 'connection', 'transfer-encoding'
                }
            }
            if isinstance(headers, dict):
                forwarded_headers.update(headers)

            response_data = FastAPIProxyService.proxy_request(
                endpoint=endpoint,
                url=url,
                method=method,
                headers=forwarded_headers,
                params=params,
                data=data,
                json_body=json_body,
                timeout=timeout
            )

            status_code = response_data.get('status_code', 200)
            response_headers = response_data.get('headers', {})
            content_type = response_data.get('content_type')
            body = response_data.get('body')

            if 'error' in response_data and status_code >= 400:
                return Response(response_data, status=status_code)

            if content_type:
                return Response(
                    body,
                    status=status_code,
                    headers=response_headers,
                    content_type=content_type
                )

            return Response(body, status=status_code, headers=response_headers)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ObservationProxyView(APIView):
    """
    Dedicated observations proxy endpoint.
    Receives frontend POST payload, forwards as query params to FastAPI /observations,
    converts any ECEF coordinates to latitude/longitude, and returns JSON.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ['get', 'post', 'options', 'head']

    def _get_request_params(self, request):
        if request.method.upper() == 'GET':
            return request.query_params.dict()

        payload = request.data or {}
        if isinstance(payload, dict) and 'input' in payload:
            payload = payload.get('input') or {}
        if not isinstance(payload, dict):
            return {}

        return {k: v for k, v in payload.items() if v is not None}

    def _handle_request(self, request):
        params = self._get_request_params(request)
        response_data = FastAPIProxyService.proxy_request(
            endpoint='/observations',
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
        response_headers = response_data.get('headers', {})
        body = response_data.get('body')

        if 'error' in response_data and status_code >= 400:
            return Response(response_data, status=status_code)

        if isinstance(body, (dict, list)):
            body = convert_ecef_data(body)

        return Response(body, status=status_code, headers=response_headers)

    def post(self, request):
        return self._handle_request(request)

    def get(self, request):
        return self._handle_request(request)

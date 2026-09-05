from django.test import TestCase

from cors_app.models import annotate_station_filter, generate_station_list, preprocess_comparison_payload


class GenerateStationListTests(TestCase):
    def test_feature_uses_current_geometry_and_requested_properties(self):
        station = {
            "station_id": "ABC",
            "current_x": 6378137.0,
            "current_y": 0.0,
            "current_z": 0.0,
            "wrms_x": 0.002332380744936875,
            "wrms_y": 0.002856571409288615,
            "wrms_z": 0.0023189543823647794,
        }

        result = generate_station_list([station])
        feature = result["features"][0]

        self.assertEqual(feature["geometry"]["type"], "Point")
        self.assertEqual(feature["geometry"]["coordinates"], [0.0, 0.0])
        self.assertEqual(feature["properties"]["current_latitude"], 0.0)
        self.assertEqual(feature["properties"]["current_longitude"], 0.0)
        self.assertEqual(feature["properties"]["wrms_x_mm"], 2.33)
        self.assertEqual(feature["properties"]["wrms_y_mm"], 2.86)
        self.assertEqual(feature["properties"]["wrms_z_mm"], 2.32)
        self.assertNotIn("wrms_x", feature["properties"])
        self.assertNotIn("wrms_y", feature["properties"])
        self.assertNotIn("wrms_z", feature["properties"])

    def test_annotate_station_filter_does_not_add_compare_flags(self):
        filtered_stations = [{"station_id": "ABC", "current_x": 6378137.0, "current_y": 0.0, "current_z": 0.0}]
        base_stations = [
            {"station_id": "ABC", "current_x": 6378137.0, "current_y": 0.0, "current_z": 0.0},
            {"station_id": "XYZ", "current_x": 6378137.0, "current_y": 0.0, "current_z": 0.0},
        ]

        result = annotate_station_filter(filtered_stations, base_stations)
        features = result["features"]

        self.assertEqual(len(features), 1)
        self.assertNotIn("filter", features[0]["properties"])

    def test_preprocess_comparison_payload_normalizes_xyz_values(self):
        payload = {
            "station_id": "1LSU00USA",
            "network": "NCN",
            "date": "2026-08-01",
            "measurement": {
                "x": -113403.113,
                "y": -5504361.292,
                "z": 3209404.161,
                "reference_frame": "ITRF2020"
            },
            "prediction": {
                "x": -113403.09285918128,
                "y": -5504361.296220205,
                "z": 3209404.1661519185,
                "model_name": "NCN20_SIF",
                "release_year": 2020
            },
            "difference": {
                "x": -0.02014081871311646,
                "y": 0.0042202044278383255,
                "z": -0.00515191862359643
            },
            "error_threshold_exceeded": "Yes"
        }

        result = preprocess_comparison_payload(payload)

        self.assertEqual(result["station_id"], "1LSU00USA")
        self.assertEqual(result["measurement"]["x"], -113403.113)
        self.assertEqual(result["prediction"]["model_name"], "NCN20_SIF")
        self.assertEqual(result["difference"]["z"], -0.00515191862359643)
        self.assertIn("location_details", result["measurement"])
        self.assertIn("latitude", result["measurement"])
        self.assertIn("longitude", result["measurement"])
        self.assertNotIn("height", result["measurement"]["location_details"])
        self.assertIn("location_details", result["prediction"])
        self.assertNotIn("latitude", result["difference"])
        self.assertNotIn("longitude", result["difference"])
        self.assertNotIn("location_details", result["difference"])
        self.assertIn("difference_3d", result["difference"])
        self.assertIn("difference_3d_mm", result["difference"])
        self.assertIn("difference_3d_cm", result["difference"])
        self.assertNotIn("difference_3d", result)
        self.assertEqual(result["error_threshold_exceeded"], "Yes")

    def test_comparison_proxy_uses_frontend_input_data_and_endpoint(self):
        from cors_app.views import ComparisonProxyView

        request = type('DummyRequest', (), {
            'method': 'POST',
            'data': {
                'input_data': {
                    'station_id': '1LSU00USA',
                    'date': '2026-08-01',
                    'model_name': 'NCN20_SIF',
                    'release_year': 2020,
                    'network': 'NCN',
                    'reference_frame': 'ITRF2020',
                    'error_threshold': 0.0001,
                },
                'endpoint': '/comparison'
            },
            'headers': {'Content-Type': 'application/json'}
        })()

        view = ComparisonProxyView()
        params = view._get_params(request)
        self.assertEqual(params['station_id'], '1LSU00USA')
        self.assertEqual(params['model_name'], 'NCN20_SIF')
        self.assertEqual(params['error_threshold'], 0.0001)

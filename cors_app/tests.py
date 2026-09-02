from django.test import TestCase

from cors_app.models import annotate_station_filter, generate_station_list


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

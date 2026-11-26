from __future__ import annotations

import json
import unittest

from baker import params as P


class ParamsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid = P.ColorParams.identity().to_document()

    def test_identity_document_is_valid(self) -> None:
        normalized = P.validate_params_document(self.valid)
        self.assertEqual(normalized, P.ColorParams.identity().as_dict())

    def test_extra_field_rejected(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["curve"] = []
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_missing_field_rejected(self) -> None:
        document = json.loads(json.dumps(self.valid))
        del document["params"]["tint"]
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_wrong_version_rejected(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["schema_version"] = "3.0"
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_legacy_v1_document_is_upgraded_with_zero_defaults(self) -> None:
        legacy = {
            "schema_version": "1.0",
            "algorithm_version": "sdr-srgb-v1.1",
            "params": {
                "exposure_ev": 0.25,
                "contrast": 10,
                "temperature": 5,
                "tint": 0,
                "highlights": -5,
                "shadows": 5,
                "saturation": 8,
            },
        }
        normalized = P.validate_params_document(legacy)
        self.assertEqual(normalized["contrast"], 10.0)
        # New v2 fields default to zero, so old documents keep their look.
        for key in ("whites", "blacks", "vibrance", "hue",
                    "split_shadow_amount", "split_balance"):
            self.assertEqual(normalized[key], 0.0)

    def test_hue_out_of_range_rejected(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["hue"] = 200
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_split_amounts_must_be_non_negative(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["split_shadow_amount"] = -1
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_bool_is_not_a_number(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["contrast"] = True
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_nan_rejected_by_parser(self) -> None:
        text = json.dumps(self.valid).replace('"contrast": 0.0', '"contrast": NaN')
        if "NaN" not in text:
            text = text.replace('"contrast": 0', '"contrast": NaN', 1)
        with self.assertRaises(P.ParamError):
            P.parse_params_text(text)

    def test_duplicate_key_rejected(self) -> None:
        text = json.dumps(self.valid)
        text = text.replace(
            '"temperature": 0.0,',
            '"temperature": 0.0, "temperature": 5.0,',
        )
        with self.assertRaises(P.ParamError):
            P.parse_params_text(text)

    def test_out_of_range_rejected(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["exposure_ev"] = 2.5
        with self.assertRaises(P.ParamError):
            P.validate_params_document(document)

    def test_normalization_rounds_and_removes_negative_zero(self) -> None:
        document = json.loads(json.dumps(self.valid))
        document["params"]["contrast"] = -0.0000001
        document["params"]["temperature"] = 12.3456789
        normalized = P.validate_params_document(document)
        self.assertEqual(normalized["contrast"], 0.0)
        self.assertEqual(normalized["temperature"], 12.345679)

    def test_canonical_json_is_stable(self) -> None:
        first = P.canonical_params(P.ColorParams(contrast=5))
        second = P.canonical_params({"contrast": 5, "exposure_ev": 0,
                                    "temperature": 0, "tint": 0,
                                    "highlights": 0, "shadows": 0,
                                    "saturation": 0})
        self.assertEqual(first, second)

    def test_cache_key_includes_strength_and_size(self) -> None:
        a = P.lut_cache_key(P.ColorParams(), 33, (0, 0, 0), (1, 1, 1), 1.0)
        b = P.lut_cache_key(P.ColorParams(), 33, (0, 0, 0), (1, 1, 1), 0.5)
        c = P.lut_cache_key(P.ColorParams(), 65, (0, 0, 0), (1, 1, 1), 1.0)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_presets_are_valid(self) -> None:
        for key, _label, params in P.list_presets():
            with self.subTest(key=key):
                P.validate_params_document(params.to_document())


if __name__ == "__main__":
    unittest.main()

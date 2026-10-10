import copy
import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location("profile_candidate", pathlib.Path(__file__).with_name("prepare-user-profile.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProfileTests(unittest.TestCase):
    def original(self):
        return {"unmanagedAttributePolicy": "DISABLED", "groups": [{"name": "unchanged"}], "attributes": [
            {"name": "username", "validations": {"length": {"min": 3}}, "permissions": {"edit": ["admin", "user"]}},
            *[{"name": name, "required": {"roles": ["user"]}, "validations": {"length": {"max": 255}}}
              for name in ("email", "firstName", "lastName")],
            {"name": "existingCustom", "required": {"scopes": ["custom"]}},
        ]}

    def test_preserves_existing_profile_but_relaxes_only_optional_contact_names(self):
        original = self.original()
        before = copy.deepcopy(original)
        candidate = module.prepare(original)
        self.assertEqual(original, before)
        self.assertEqual(candidate["groups"], original["groups"])
        self.assertEqual(candidate["unmanagedAttributePolicy"], "DISABLED")
        for old, new in zip(original["attributes"], candidate["attributes"]):
            expected = copy.deepcopy(old)
            if expected["name"] in {"email", "firstName", "lastName"}:
                expected.pop("required")
            self.assertEqual(expected, new)
        for attribute in candidate["attributes"][-2:]:
            self.assertEqual(attribute["permissions"], {"view": ["admin"], "edit": ["admin"]})
            self.assertNotIn("required", attribute)

    def test_refuses_conflicting_or_duplicate_attributes(self):
        for extra in ({"name": "pajio_registration_id"}, {"name": "username"}):
            profile = self.original()
            profile["attributes"].append(extra)
            with self.assertRaises(ValueError):
                module.prepare(profile)

    def test_refuses_missing_core_or_malformed_profile(self):
        for profile in ({"attributes": []}, {"attributes": [None]}, {}):
            with self.assertRaises(ValueError):
                module.prepare(profile)


if __name__ == "__main__":
    unittest.main()

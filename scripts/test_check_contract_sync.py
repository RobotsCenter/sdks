import copy
import unittest

from check_contract_sync import normalize_contract


class ContractNormalizationTest(unittest.TestCase):
    def test_required_arrays_are_set_like(self) -> None:
        left = {"schema": {"required": ["b", "a", "a"], "enum": ["b", "a"]}}
        right = {"schema": {"required": ["a", "b"], "enum": ["b", "a"]}}
        self.assertEqual(normalize_contract(left), normalize_contract(right))

    def test_other_arrays_keep_semantic_order(self) -> None:
        left = {"protocol": {"frame": ["join_ref", "ref", "topic"]}}
        right = {"protocol": {"frame": ["ref", "join_ref", "topic"]}}
        self.assertNotEqual(normalize_contract(left), normalize_contract(right))

    def test_normalization_does_not_mutate_input(self) -> None:
        document = {"required": ["b", "a"]}
        original = copy.deepcopy(document)
        normalize_contract(document)
        self.assertEqual(document, original)


if __name__ == "__main__":
    unittest.main()

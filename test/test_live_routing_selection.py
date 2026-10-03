"""The paid smoke requires user-selected catalog models; these checks are offline."""
import unittest

from integration import verify_live_routing


class LiveRoutingSelectionTests(unittest.TestCase):
    def test_profiles_select_distinct_advertised_models(self):
        catalog = [{'model': name, 'isDefault': index == 0, 'defaultReasoningEffort': 'adaptive',
            'supportedReasoningEfforts': [{'reasoningEffort': 'adaptive'}]}
            for index, name in enumerate(('provider/future-fast', 'provider/future-deep'))]
        first, second = verify_live_routing.select_models(catalog,
            {'fast': ['provider/future-fast'], 'deep': ['provider/future-deep']})
        self.assertEqual((first.model, second.model), ('provider/future-fast', 'provider/future-deep'))
        self.assertEqual((first.effort, second.effort), ('adaptive', 'adaptive'))
        for profiles in ({}, {'fast': ['missing'], 'deep': ['missing']},
                         {'fast': ['provider/future-fast'], 'deep': ['provider/future-fast']}):
            with self.subTest(profiles=profiles), self.assertRaisesRegex(ValueError, 'two distinct'):
                verify_live_routing.select_models(catalog, profiles)


if __name__ == '__main__':
    unittest.main()

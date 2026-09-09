import unittest
from calculator import add

class CalculatorTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(17, 25), 42)

if __name__ == "__main__":
    unittest.main()

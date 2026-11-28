import ast
import os
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "validate_new_kg.py"
)


def load_kg_id_exists():
    """Load only kg_id_exists without executing the validation script."""

    source = SCRIPT_PATH.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)

    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "kg_id_exists"
    )

    isolated_module = ast.Module(
        body=[function_node],
        type_ignores=[],
    )

    namespace = {"Path": Path}
    exec(compile(isolated_module, str(SCRIPT_PATH), "exec"), namespace)

    return namespace["kg_id_exists"]


class TestKgIdExists(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_directory = os.getcwd()
        os.chdir(self.temp_dir.name)
        self.kg_id_exists = load_kg_id_exists()

    def tearDown(self):
        os.chdir(self.original_directory)
        self.temp_dir.cleanup()

    def test_existing_kg_id_returns_true(self):
        metadata_file = (
            Path("knowledge-graphs")
            / "example-kg"
            / "metadata.yaml"
        )

        metadata_file.parent.mkdir(parents=True)
        metadata_file.write_text(
            "id: example-kg\n",
            encoding="utf-8",
        )

        self.assertTrue(self.kg_id_exists("example-kg"))

    def test_non_existing_kg_id_returns_false(self):
        self.assertFalse(self.kg_id_exists("unknown-kg"))

    def test_empty_kg_id_returns_false(self):
        self.assertFalse(self.kg_id_exists(""))


if __name__ == "__main__":
    unittest.main()
